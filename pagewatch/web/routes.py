import json
import os
from datetime import datetime, timezone, timedelta
from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    abort,
    flash,
    send_from_directory,
    send_file,
    Response,
)

from pagewatch import config
from pagewatch import monitors_repo
from pagewatch.jobqueue import enqueue_job
from pagewatch.db import run_query
from pagewatch.urlutils import normalize_url
from pagewatch.scheduler import is_scheduler_running
from pagewatch.differ import text_diff_lines, count_diff_lines, side_by_side_html
from pagewatch.imgdiff import get_or_create_diff_image

bp = Blueprint("web", __name__, template_folder="templates")


def get_interval_choices():
    if config.DEV_FAST_MODE:
        return [
            (1, "1 min (demo)"),
            (2, "2 min (demo)"),
            (15, "15 min"),
            (30, "30 min"),
            (60, "1 hour"),
            (180, "3 hours"),
            (360, "6 hours"),
            (720, "12 hours"),
            (1440, "24 hours"),
        ]
    return [
        (15, "15 min"),
        (30, "30 min"),
        (60, "1 hour"),
        (180, "3 hours"),
        (360, "6 hours"),
        (720, "12 hours"),
        (1440, "24 hours"),
    ]


INTERVAL_CHOICES = get_interval_choices()


@bp.app_template_filter("time_ago")
def format_time_ago(iso_string):
    if not iso_string:
        return "never"
    try:
        dt = datetime.fromisoformat(iso_string)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        diff_seconds = (now - dt).total_seconds()
        if diff_seconds < 60:
            return "just now"
        if diff_seconds < 3600:
            return f"{int(diff_seconds // 60)} min ago"
        if diff_seconds < 86400:
            return f"{int(diff_seconds // 3600)} h ago"
        return f"{int(diff_seconds // 86400)} d ago"
    except Exception:
        return str(iso_string)[:16]


@bp.app_template_filter("format_interval")
def format_interval(minutes):
    try:
        minutes = int(minutes)
    except (ValueError, TypeError):
        return f"{minutes} min"

    for mins, label in get_interval_choices():
        if minutes == mins:
            return label
    if minutes >= 60 and minutes % 60 == 0:
        return f"{minutes // 60} h"
    return f"{minutes} min"


@bp.app_template_filter("short_hash")
def format_short_hash(val):
    return str(val)[:8] if val else ""


@bp.route("/")
def dashboard():
    monitors = monitors_repo.list_monitors()

    queued_row = run_query("SELECT COUNT(*) AS count FROM jobs WHERE status = 'queued'")
    queued_count = queued_row[0]["count"] if queued_row else 0

    running_row = run_query("SELECT COUNT(*) AS count FROM jobs WHERE status = 'running'")
    running_count = running_row[0]["count"] if running_row else 0

    cutoff_24h = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    failed_row = run_query(
        "SELECT COUNT(*) AS count FROM jobs WHERE status = 'failed' AND (finished_at >= ? OR created_at >= ?)",
        (cutoff_24h, cutoff_24h)
    )
    failed_24h_count = failed_row[0]["count"] if failed_row else 0
    scheduler_active = is_scheduler_running()

    return render_template(
        "dashboard.html",
        monitors=monitors,
        monitor_count=len(monitors),
        scheduler_active=scheduler_active,
        queued_count=queued_count,
        running_count=running_count,
        failed_24h_count=failed_24h_count,
        dev_fast_mode=config.DEV_FAST_MODE,
    )


@bp.route("/add")
def add_redirect():
    return redirect(url_for("web.add_monitor"))


@bp.route("/monitors/add", methods=["GET", "POST"])
def add_monitor():
    errors = []
    form_data = {
        "name": "",
        "url": "",
        "interval_minutes": 60,
        "sensitivity": "medium",
        "include_selectors": "",
        "ignore_selectors": "",
        "keyword": "",
        "number_selector": "",
        "number_alert_below": None,
        "number_alert_above": None,
        "alert_email": "",
        "telegram_chat_id": "",
        "discord_webhook_url": "",
        "daily_digest": False,
    }

    if request.method == "POST":
        form_data["name"] = request.form.get("name", "").strip()
        form_data["url"] = request.form.get("url", "").strip()
        form_data["sensitivity"] = request.form.get("sensitivity", "medium").strip()
        form_data["include_selectors"] = request.form.get("include_selectors", "").strip()
        form_data["ignore_selectors"] = request.form.get("ignore_selectors", "").strip()
        form_data["keyword"] = request.form.get("keyword", "").strip()
        form_data["number_selector"] = request.form.get("number_selector", "").strip()

        raw_below = request.form.get("number_alert_below", "").strip()
        raw_above = request.form.get("number_alert_above", "").strip()
        try:
            form_data["number_alert_below"] = float(raw_below) if raw_below else None
        except ValueError:
            errors.append("Alert if Below must be a valid number.")

        try:
            form_data["number_alert_above"] = float(raw_above) if raw_above else None
        except ValueError:
            errors.append("Alert if Above must be a valid number.")

        form_data["alert_email"] = request.form.get("alert_email", "").strip()
        form_data["telegram_chat_id"] = request.form.get("telegram_chat_id", "").strip()
        form_data["discord_webhook_url"] = request.form.get("discord_webhook_url", "").strip()
        form_data["daily_digest"] = bool(request.form.get("daily_digest"))

        raw_interval = request.form.get("interval_minutes", "60").strip()

        if not form_data["name"]:
            errors.append("Monitor name is required.")

        try:
            clean_url = normalize_url(form_data["url"])
            form_data["url"] = clean_url
        except ValueError as err:
            errors.append(str(err))

        try:
            interval_val = int(raw_interval)
            form_data["interval_minutes"] = interval_val
            if not (config.MIN_INTERVAL_MINUTES <= interval_val <= config.MAX_INTERVAL_MINUTES):
                errors.append(
                    f"Check interval must be between {config.MIN_INTERVAL_MINUTES} "
                    f"and {config.MAX_INTERVAL_MINUTES} minutes."
                )
        except ValueError:
            errors.append("Please select a valid interval.")

        if form_data["sensitivity"] not in ("low", "medium", "high"):
            errors.append("Invalid sensitivity setting.")

        if not errors:
            monitors_repo.create_monitor(form_data)
            return redirect(url_for("web.dashboard"))

    return render_template(
        "add_monitor.html",
        errors=errors,
        form_data=form_data,
        intervals=get_interval_choices(),
    )


@bp.route("/monitors/<int:monitor_id>")
@bp.route("/monitor/<int:monitor_id>")
def view_monitor(monitor_id):
    monitor = monitors_repo.get_monitor(monitor_id)
    if not monitor:
        abort(404)

    check_logs = run_query(
        """
        SELECT * FROM check_log
        WHERE monitor_id = ?
        ORDER BY id DESC
        LIMIT 20
        """,
        (monitor_id,)
    )

    raw_snapshots = run_query(
        """
        SELECT * FROM snapshots
        WHERE monitor_id = ?
        ORDER BY id DESC
        """,
        (monitor_id,)
    )

    snapshots = []
    for i, row in enumerate(raw_snapshots):
        s = dict(row)
        prev_row = dict(raw_snapshots[i + 1]) if (i + 1 < len(raw_snapshots)) else None
        if prev_row:
            s["prev_id"] = prev_row["id"]
            try:
                if os.path.isfile(prev_row["text_path"]) and os.path.isfile(s["text_path"]):
                    with open(prev_row["text_path"], "r", encoding="utf-8") as f:
                        old_txt = f.read()
                    with open(s["text_path"], "r", encoding="utf-8") as f:
                        new_txt = f.read()
                    added, removed = count_diff_lines(old_txt, new_txt)
                    s["diff_summary"] = f"+{added} / -{removed} lines vs #{prev_row['id']}"
                    if not s.get("summary"):
                        from pagewatch.summary import make_summary
                        s["summary"] = make_summary(old_txt, new_txt, keyword=monitor.get("keyword"))
                else:
                    s["diff_summary"] = f"vs #{prev_row['id']}"
            except Exception:
                s["diff_summary"] = f"vs #{prev_row['id']}"
            s["compare_url"] = url_for("web.compare_snapshots", monitor_id=monitor_id, a=prev_row["id"], b=s["id"])
        else:
            s["prev_id"] = None
            s["diff_summary"] = "Initial baseline"
            if not s.get("summary"):
                s["summary"] = "Baseline snapshot created"
            s["compare_url"] = None

        s["text_filename"] = os.path.basename(s["text_path"])
        s["screenshot_filename"] = os.path.basename(s["screenshot_path"])
        snapshots.append(s)

    return render_template(
        "monitor.html",
        monitor=monitor,
        check_logs=check_logs,
        snapshots=snapshots,
    )


@bp.route("/monitors/<int:monitor_id>/compare")
@bp.route("/monitor/<int:monitor_id>/compare")
def compare_snapshots(monitor_id):
    monitor = monitors_repo.get_monitor(monitor_id)
    if not monitor:
        abort(404)

    all_snapshots = run_query(
        "SELECT * FROM snapshots WHERE monitor_id = ? ORDER BY id DESC",
        (monitor_id,)
    )

    if len(all_snapshots) < 2:
        return render_template(
            "compare.html",
            monitor=monitor,
            all_snapshots=all_snapshots,
            snap_a=None,
            snap_b=None,
            error_message="At least 2 snapshots are needed to perform a comparison. Click 'Check Now' on the monitor page to capture another snapshot."
        )

    a_param = request.args.get("a", type=int)
    b_param = request.args.get("b", type=int)

    if not a_param or not b_param:
        b_param = all_snapshots[0]["id"]
        a_param = all_snapshots[1]["id"]

    snap_map = {s["id"]: dict(s) for s in all_snapshots}

    if a_param not in snap_map or b_param not in snap_map:
        return render_template(
            "compare.html",
            monitor=monitor,
            all_snapshots=all_snapshots,
            snap_a=None,
            snap_b=None,
            error_message=f"Both selected snapshots must belong to monitor '{monitor['name']}'."
        )

    if a_param == b_param:
        return render_template(
            "compare.html",
            monitor=monitor,
            all_snapshots=all_snapshots,
            snap_a=snap_map[a_param],
            snap_b=snap_map[b_param],
            error_message="You selected the same snapshot on both sides. Please choose two different snapshots to compare."
        )

    if snap_map[a_param]["id"] < snap_map[b_param]["id"]:
        snap_old = snap_map[a_param]
        snap_new = snap_map[b_param]
    else:
        snap_old = snap_map[b_param]
        snap_new = snap_map[a_param]

    text_error = None
    old_text = ""
    new_text = ""
    if not os.path.isfile(snap_old["text_path"]):
        text_error = f"Snapshot #{snap_old['id']} text file is missing from disk ({snap_old['text_path']})."
    elif not os.path.isfile(snap_new["text_path"]):
        text_error = f"Snapshot #{snap_new['id']} text file is missing from disk ({snap_new['text_path']})."
    else:
        try:
            with open(snap_old["text_path"], "r", encoding="utf-8") as f:
                old_text = f.read()
            with open(snap_new["text_path"], "r", encoding="utf-8") as f:
                new_text = f.read()
        except Exception as err:
            text_error = f"Error reading snapshot text: {err}"

    unified_diff = []
    side_by_side = ""
    added_count = 0
    removed_count = 0
    if not text_error:
        unified_diff = text_diff_lines(old_text, new_text)
        side_by_side = side_by_side_html(old_text, new_text)
        added_count, removed_count = count_diff_lines(old_text, new_text)

    image_error = None
    diff_filename = None
    changed_percent = 0.0
    if not os.path.isfile(snap_old["screenshot_path"]):
        image_error = f"Snapshot #{snap_old['id']} screenshot is missing from disk."
    elif not os.path.isfile(snap_new["screenshot_path"]):
        image_error = f"Snapshot #{snap_new['id']} screenshot is missing from disk."
    else:
        try:
            diff_filename, changed_percent = get_or_create_diff_image(
                snap_old["id"],
                snap_new["id"],
                snap_old["screenshot_path"],
                snap_new["screenshot_path"]
            )
        except Exception as err:
            image_error = f"Error generating visual screenshot diff: {err}"

    return render_template(
        "compare.html",
        monitor=monitor,
        all_snapshots=all_snapshots,
        snap_a=snap_old,
        snap_b=snap_new,
        text_error=text_error,
        unified_diff=unified_diff,
        side_by_side=side_by_side,
        added_count=added_count,
        removed_count=removed_count,
        image_error=image_error,
        diff_filename=diff_filename,
        changed_percent=changed_percent,
        old_screenshot=os.path.basename(snap_old["screenshot_path"]),
        new_screenshot=os.path.basename(snap_new["screenshot_path"]),
    )


@bp.route("/monitors/<int:monitor_id>/check-now", methods=["POST"])
@bp.route("/monitor/<int:monitor_id>/check-now", methods=["POST"])
def check_now(monitor_id):
    monitor = monitors_repo.get_monitor(monitor_id)
    if not monitor:
        abort(404)

    job_id = enqueue_job(monitor["url_id"], monitor_id=monitor["id"])
    if job_id:
        flash("Check queued", "success")
    else:
        flash("A check is already queued or running for this URL.", "info")

    referrer = request.referrer
    if referrer and "/monitors" in referrer:
        return redirect(referrer)
    return redirect(url_for("web.view_monitor", monitor_id=monitor_id))


@bp.route("/monitors/<int:monitor_id>/test-alert", methods=["POST"])
@bp.route("/monitor/<int:monitor_id>/test-alert", methods=["POST"])
def test_alert(monitor_id):
    monitor = monitors_repo.get_monitor(monitor_id)
    if not monitor:
        abort(404)

    from pagewatch.alerts import send_test_alert
    results = send_test_alert(monitor)

    if not results:
        flash("No alert channels configured for this monitor. Add email, Telegram, or Discord webhook in Edit.", "info")
    else:
        sent_channels = [ch for ch, ok in results.items() if ok]
        failed_channels = [ch for ch, ok in results.items() if not ok]
        if sent_channels:
            flash(f"Test alert sent to: {', '.join(sent_channels)}.", "success")
        if failed_channels:
            flash(f"Failed to send to: {', '.join(failed_channels)}. Check server logs and credentials.", "error")

    referrer = request.referrer
    if referrer and ("/monitors" in referrer or "/monitor" in referrer):
        return redirect(referrer)
    return redirect(url_for("web.view_monitor", monitor_id=monitor_id))


@bp.route("/admin/send-digest-now", methods=["POST"])
def send_digest_now():
    if not config.DEV_FAST_MODE:
        abort(403)

    from pagewatch.digest import send_daily_digests
    count = send_daily_digests()
    flash(f"Daily digest executed for {count} monitor(s).", "success")
    return redirect(url_for("web.dashboard"))


@bp.route("/monitors/<int:monitor_id>/edit", methods=["GET", "POST"])
def edit_monitor(monitor_id):
    monitor = monitors_repo.get_monitor(monitor_id)
    if not monitor:
        abort(404)

    errors = []
    form_data = {
        "name": monitor["name"],
        "url": monitor["url"],
        "interval_minutes": monitor["interval_minutes"],
        "sensitivity": monitor["sensitivity"],
        "include_selectors": monitor["include_selectors"],
        "ignore_selectors": monitor["ignore_selectors"],
        "keyword": monitor["keyword"],
        "number_selector": monitor["number_selector"],
        "number_alert_below": monitor["number_alert_below"],
        "number_alert_above": monitor["number_alert_above"],
        "alert_email": monitor["alert_email"],
        "telegram_chat_id": monitor["telegram_chat_id"],
        "discord_webhook_url": monitor["discord_webhook_url"],
        "daily_digest": bool(monitor["daily_digest"]),
    }

    if request.method == "POST":
        form_data["name"] = request.form.get("name", "").strip()
        form_data["url"] = request.form.get("url", "").strip()
        form_data["sensitivity"] = request.form.get("sensitivity", "medium").strip()
        form_data["include_selectors"] = request.form.get("include_selectors", "").strip()
        form_data["ignore_selectors"] = request.form.get("ignore_selectors", "").strip()
        form_data["keyword"] = request.form.get("keyword", "").strip()
        form_data["number_selector"] = request.form.get("number_selector", "").strip()

        raw_below = request.form.get("number_alert_below", "").strip()
        raw_above = request.form.get("number_alert_above", "").strip()
        try:
            form_data["number_alert_below"] = float(raw_below) if raw_below else None
        except ValueError:
            errors.append("Alert if Below must be a valid number.")

        try:
            form_data["number_alert_above"] = float(raw_above) if raw_above else None
        except ValueError:
            errors.append("Alert if Above must be a valid number.")

        form_data["alert_email"] = request.form.get("alert_email", "").strip()
        form_data["telegram_chat_id"] = request.form.get("telegram_chat_id", "").strip()
        form_data["discord_webhook_url"] = request.form.get("discord_webhook_url", "").strip()
        form_data["daily_digest"] = bool(request.form.get("daily_digest"))

        raw_interval = request.form.get("interval_minutes", "60").strip()

        if not form_data["name"]:
            errors.append("Monitor name is required.")

        try:
            clean_url = normalize_url(form_data["url"])
            form_data["url"] = clean_url
        except ValueError as err:
            errors.append(str(err))

        try:
            interval_val = int(raw_interval)
            form_data["interval_minutes"] = interval_val
            if not (config.MIN_INTERVAL_MINUTES <= interval_val <= config.MAX_INTERVAL_MINUTES):
                errors.append(
                    f"Check interval must be between {config.MIN_INTERVAL_MINUTES} "
                    f"and {config.MAX_INTERVAL_MINUTES} minutes."
                )
        except ValueError:
            errors.append("Please select a valid interval.")

        if not errors:
            monitors_repo.update_monitor(monitor_id, form_data)
            return redirect(url_for("web.dashboard"))

    return render_template(
        "edit_monitor.html",
        monitor=monitor,
        form_data=form_data,
        errors=errors,
        intervals=get_interval_choices(),
    )


@bp.route("/monitors/<int:monitor_id>/delete", methods=["GET", "POST"])
def delete_monitor(monitor_id):
    monitor = monitors_repo.get_monitor(monitor_id)
    if not monitor:
        abort(404)

    if request.method == "POST":
        monitors_repo.delete_monitor(monitor_id)
        return redirect(url_for("web.dashboard"))

    return render_template("delete_confirm.html", monitor=monitor)


@bp.route("/monitors/<int:monitor_id>/chart.png")
@bp.route("/monitor/<int:monitor_id>/chart.png")
def monitor_chart_png(monitor_id):
    monitor = monitors_repo.get_monitor(monitor_id)
    if not monitor:
        abort(404)

    from pagewatch.numbers import generate_number_chart
    png_bytes = generate_number_chart(monitor)
    return Response(png_bytes, mimetype="image/png")


@bp.route("/monitors/<int:monitor_id>/feed.xml")
@bp.route("/monitor/<int:monitor_id>/feed.xml")
def monitor_rss_feed(monitor_id):
    monitor = monitors_repo.get_monitor(monitor_id)
    if not monitor:
        abort(404)

    from pagewatch.feeds import generate_rss_feed
    rss_xml = generate_rss_feed(monitor)
    return Response(rss_xml, mimetype="application/rss+xml; charset=utf-8")


@bp.route("/monitors/<int:monitor_id>/picker")
@bp.route("/monitor/<int:monitor_id>/picker")
def visual_picker(monitor_id):
    monitor = monitors_repo.get_monitor(monitor_id)
    if not monitor:
        abort(404)
    monitor = dict(monitor)

    png_path = os.path.join(config.PICKER_DIR, f"monitor_{monitor_id}.png")
    json_path = os.path.join(config.PICKER_DIR, f"monitor_{monitor_id}.json")

    if not (os.path.isfile(png_path) and os.path.isfile(json_path)):
        active_job = run_query(
            """
            SELECT * FROM jobs
            WHERE monitor_id = ? AND job_type = 'picker_snapshot' AND status IN ('queued', 'running')
            ORDER BY id DESC LIMIT 1
            """,
            (monitor_id,)
        )
        if not active_job:
            enqueue_job(monitor["url_id"], monitor_id=monitor_id, job_type="picker_snapshot")

        return render_template("picker_loading.html", monitor=monitor)

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = {}

    elements = data.get("elements", [])
    image_width = data.get("image_width", 1280)
    image_height = data.get("image_height", 800)

    include_list = [s.strip() for s in (monitor.get("include_selectors") or "").splitlines() if s.strip()]
    ignore_list = [s.strip() for s in (monitor.get("ignore_selectors") or "").splitlines() if s.strip()]

    return render_template(
        "picker.html",
        monitor=monitor,
        elements=elements,
        image_width=image_width,
        image_height=image_height,
        screenshot_url=f"/data/picker/monitor_{monitor_id}.png",
        include_list=include_list,
        ignore_list=ignore_list,
    )


@bp.route("/monitors/<int:monitor_id>/picker/add", methods=["POST"])
@bp.route("/monitor/<int:monitor_id>/picker/add", methods=["POST"])
def visual_picker_add(monitor_id):
    monitor = monitors_repo.get_monitor(monitor_id)
    if not monitor:
        abort(404)

    selector_type = request.form.get("selector_type", "").strip().lower()
    selector = request.form.get("selector", "").strip()

    if selector and selector_type in ("include", "ignore"):
        from pagewatch.picker import add_selector_to_monitor
        add_selector_to_monitor(monitor_id, selector_type, selector)

    return redirect(url_for("web.visual_picker", monitor_id=monitor_id))


@bp.route("/monitors/<int:monitor_id>/picker/remove", methods=["POST"])
@bp.route("/monitor/<int:monitor_id>/picker/remove", methods=["POST"])
def visual_picker_remove(monitor_id):
    monitor = monitors_repo.get_monitor(monitor_id)
    if not monitor:
        abort(404)

    selector_type = request.form.get("selector_type", "").strip().lower()
    selector = request.form.get("selector", "").strip()

    if selector and selector_type in ("include", "ignore"):
        from pagewatch.picker import remove_selector_from_monitor
        remove_selector_from_monitor(monitor_id, selector_type, selector)

    return redirect(url_for("web.visual_picker", monitor_id=monitor_id))


@bp.route("/monitors/<int:monitor_id>/picker/refresh", methods=["POST"])
@bp.route("/monitor/<int:monitor_id>/picker/refresh", methods=["POST"])
def visual_picker_refresh(monitor_id):
    monitor = monitors_repo.get_monitor(monitor_id)
    if not monitor:
        abort(404)

    png_path = os.path.join(config.PICKER_DIR, f"monitor_{monitor_id}.png")
    json_path = os.path.join(config.PICKER_DIR, f"monitor_{monitor_id}.json")

    for p in (png_path, json_path):
        if os.path.isfile(p):
            try:
                os.remove(p)
            except OSError:
                pass

    enqueue_job(monitor["url_id"], monitor_id=monitor_id, job_type="picker_snapshot")
    return redirect(url_for("web.visual_picker", monitor_id=monitor_id))


@bp.route("/files/texts/<path:filename>")
def serve_text_file(filename):
    return send_from_directory(
        os.path.abspath(config.TEXT_DIR),
        filename,
        mimetype="text/plain; charset=utf-8"
    )


@bp.route("/files/screenshots/<path:filename>")
def serve_screenshot_file(filename):
    return send_from_directory(
        os.path.abspath(config.SCREENSHOT_DIR),
        filename,
        mimetype="image/png"
    )


@bp.route("/snapshots/<int:snapshot_id>/text")
def view_snapshot_text(snapshot_id):
    rows = run_query("SELECT text_path FROM snapshots WHERE id = ?", (snapshot_id,))
    if not rows or not rows[0]["text_path"]:
        abort(404)
    filename = os.path.basename(rows[0]["text_path"])
    return send_from_directory(
        os.path.abspath(config.TEXT_DIR),
        filename,
        mimetype="text/plain; charset=utf-8"
    )


@bp.route("/data/<path:filepath>")
def serve_data_file(filepath):
    base_dir = os.path.abspath(config.DATA_DIR)
    requested_path = os.path.abspath(os.path.join(base_dir, filepath))

    try:
        common = os.path.commonpath([base_dir, requested_path])
        if common != base_dir or requested_path == base_dir:
            abort(403)
    except ValueError:
        abort(403)

    if not os.path.isfile(requested_path):
        abort(404)

    return send_file(requested_path)
