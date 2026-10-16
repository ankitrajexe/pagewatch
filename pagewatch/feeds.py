import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import format_datetime
from pagewatch import config
from pagewatch.db import run_query


def format_rfc822(iso_str):
    if not iso_str:
        return format_datetime(datetime.now(timezone.utc))
    try:
        clean_iso = iso_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean_iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return format_datetime(dt)
    except Exception:
        return format_datetime(datetime.now(timezone.utc))


def generate_rss_feed(monitor):
    monitor = dict(monitor)
    monitor_id = monitor["id"]
    name = monitor.get("name", f"Monitor #{monitor_id}")
    url = monitor.get("url", "")
    monitor_url = f"{config.BASE_URL}/monitors/{monitor_id}"

    rows = run_query(
        """
        SELECT id, monitor_id, taken_at, content_hash, text_path, screenshot_path, text_length, summary
        FROM snapshots
        WHERE monitor_id = ?
        ORDER BY id DESC
        LIMIT 51
        """,
        (monitor_id,)
    )

    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")

    title_elem = ET.SubElement(channel, "title")
    title_elem.text = name

    link_elem = ET.SubElement(channel, "link")
    link_elem.text = monitor_url

    desc_elem = ET.SubElement(channel, "description")
    desc_elem.text = f"Change feed for {name} ({url})" if url else f"Change feed for {name}"

    lang_elem = ET.SubElement(channel, "language")
    lang_elem.text = "en"

    build_date = format_rfc822(rows[0]["taken_at"] if rows else None)
    build_elem = ET.SubElement(channel, "lastBuildDate")
    build_elem.text = build_date

    total_items = min(50, len(rows))
    for i in range(total_items):
        s = dict(rows[i])
        prev_s = dict(rows[i + 1]) if i + 1 < len(rows) else None

        item_elem = ET.SubElement(channel, "item")

        summary_text = (s.get("summary") or "").strip()
        if not summary_text:
            if prev_s is None and i == len(rows) - 1:
                summary_text = "Baseline snapshot created"
            else:
                summary_text = f"Snapshot #{s['id']} captured"

        if prev_s:
            compare_url = f"{config.BASE_URL}/monitors/{monitor_id}/compare?a={prev_s['id']}&b={s['id']}"
            item_desc = f"{summary_text} - Compare: {compare_url}"
        else:
            compare_url = monitor_url
            item_desc = f"{summary_text} - View monitor: {compare_url}"

        item_title = ET.SubElement(item_elem, "title")
        item_title.text = summary_text

        item_link = ET.SubElement(item_elem, "link")
        item_link.text = compare_url

        item_guid = ET.SubElement(item_elem, "guid", isPermaLink="false")
        item_guid.text = str(s["id"])

        item_pubdate = ET.SubElement(item_elem, "pubDate")
        item_pubdate.text = format_rfc822(s["taken_at"])

        item_desc_elem = ET.SubElement(item_elem, "description")
        item_desc_elem.text = item_desc

    ET.indent(rss, space="  ")
    xml_bytes = ET.tostring(rss, encoding="utf-8", xml_declaration=True)
    return xml_bytes.decode("utf-8")
