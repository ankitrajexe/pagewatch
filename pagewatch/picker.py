import os
import re
import json
from datetime import datetime, timezone
from PIL import Image
from bs4 import BeautifulSoup

from pagewatch import config
from pagewatch.db import run_query, run_write


def generate_css_selector(soup, element):
    if element is None or not hasattr(element, "name") or not element.name:
        return ""

    tag_name = element.name.lower()

    elem_id = element.get("id")
    if elem_id and isinstance(elem_id, str) and elem_id.strip():
        elem_id = elem_id.strip()
        selector = f"#{elem_id}" if re.match(r"^[a-zA-Z_][a-zA-Z0-9_-]*$", elem_id) else f'[id="{elem_id}"]'
        if soup is None:
            return selector
        try:
            if len(soup.select(selector)) == 1:
                return selector
        except Exception:
            pass

    for attr, val in element.attrs.items():
        if attr.startswith("data-") and isinstance(val, str) and val.strip():
            selector = f'{tag_name}[{attr}="{val.strip()}"]'
            if soup is None:
                return selector
            try:
                if len(soup.select(selector)) == 1:
                    return selector
            except Exception:
                pass

    elem_classes = element.get("class")
    if elem_classes and isinstance(elem_classes, list):
        clean_classes = [c.strip() for c in elem_classes if c.strip() and not re.search(r"\s", c)]
        if clean_classes:
            selector = f"{tag_name}." + ".".join(clean_classes)
            if soup is None:
                return selector
            try:
                if len(soup.select(selector)) == 1:
                    return selector
            except Exception:
                pass

    path = []
    curr = element
    while curr and hasattr(curr, "name") and curr.name and curr.name != "[document]":
        current_tag = curr.name.lower()
        if current_tag in ("body", "html"):
            break

        anc_id = curr.get("id")
        if anc_id and isinstance(anc_id, str) and anc_id.strip() and re.match(r"^[a-zA-Z_][a-zA-Z0-9_-]*$", anc_id.strip()):
            id_sel = f"#{anc_id.strip()}"
            try:
                if soup is None or len(soup.select(id_sel)) == 1:
                    path.append(id_sel)
                    break
            except Exception:
                pass

        parent = curr.parent
        if parent and hasattr(parent, "find_all"):
            siblings = [s for s in parent.find_all(curr.name, recursive=False) if hasattr(s, "name")]
            if len(siblings) > 1:
                idx = siblings.index(curr) + 1
                segment = f"{current_tag}:nth-of-type({idx})"
            else:
                segment = current_tag
        else:
            segment = current_tag

        path.append(segment)
        curr = parent

    path.reverse()
    return " > ".join(path) if path else tag_name


def capture_picker_snapshot(browser_session, url, monitor_id, out_png_path, out_json_path, timeout_seconds=45):
    os.makedirs(os.path.dirname(out_png_path), exist_ok=True)
    os.makedirs(os.path.dirname(out_json_path), exist_ok=True)

    timeout_ms = timeout_seconds * 1000
    context = None
    page = None

    try:
        from pagewatch.fetcher import USER_AGENT, VIEWPORT_WIDTH, VIEWPORT_HEIGHT
        context = browser_session._browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
        )
        page = context.new_page()
        page.set_default_timeout(timeout_ms)

        page.goto(url, wait_until="load", timeout=timeout_ms)
        try:
            page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass

        page.screenshot(path=out_png_path, full_page=True)

        js_code = """
        () => {
            function getSelector(el) {
                if (el.id && document.querySelectorAll('#' + CSS.escape(el.id)).length === 1) {
                    return '#' + CSS.escape(el.id);
                }
                for (let attr of el.getAttributeNames()) {
                    if (attr.startsWith('data-')) {
                        const val = el.getAttribute(attr);
                        const sel = `${el.tagName.toLowerCase()}[${attr}="${CSS.escape(val)}"]`;
                        if (document.querySelectorAll(sel).length === 1) {
                            return sel;
                        }
                    }
                }
                if (el.className && typeof el.className === 'string') {
                    const classes = el.className.trim().split(/\\s+/).filter(c => c && !c.includes(':')).map(c => CSS.escape(c)).join('.');
                    if (classes) {
                        const sel = `${el.tagName.toLowerCase()}.${classes}`;
                        if (document.querySelectorAll(sel).length === 1) {
                            return sel;
                        }
                    }
                }
                const path = [];
                let curr = el;
                while (curr && curr.nodeType === Node.ELEMENT_NODE && curr.tagName.toLowerCase() !== 'html') {
                    if (curr.id && document.querySelectorAll('#' + CSS.escape(curr.id)).length === 1) {
                        path.unshift('#' + CSS.escape(curr.id));
                        break;
                    }
                    let tag = curr.tagName.toLowerCase();
                    let parent = curr.parentElement;
                    if (parent) {
                        let siblings = Array.from(parent.children).filter(c => c.tagName.toLowerCase() === tag);
                        if (siblings.length > 1) {
                            let index = siblings.indexOf(curr) + 1;
                            tag += `:nth-of-type(${index})`;
                        }
                    }
                    path.unshift(tag);
                    if (curr.tagName.toLowerCase() === 'body') break;
                    curr = parent;
                }
                return path.join(' > ');
            }

            const skippedTags = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'SVG', 'PATH', 'LINK', 'META', 'BR', 'HR', 'HEAD', 'HTML', 'BODY']);
            const all = document.body ? document.body.querySelectorAll('*') : [];
            const elements = [];
            const scrollX = window.scrollX || window.pageXOffset || 0;
            const scrollY = window.scrollY || window.pageYOffset || 0;
            const seenBoxes = new Set();

            for (let el of all) {
                if (elements.length >= 300) break;
                if (skippedTags.has(el.tagName.toUpperCase())) continue;

                const rect = el.getBoundingClientRect();
                const w = Math.round(rect.width);
                const h = Math.round(rect.height);
                if (w < 15 || h < 15) continue;

                const style = window.getComputedStyle(el);
                if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') continue;

                const x = Math.round(rect.left + scrollX);
                const y = Math.round(rect.top + scrollY);

                const boxKey = `${x},${y},${w},${h}`;
                if (seenBoxes.has(boxKey)) continue;
                seenBoxes.add(boxKey);

                const selector = getSelector(el);
                if (selector) {
                    elements.push({
                        selector: selector,
                        tag: el.tagName.toLowerCase(),
                        x: x,
                        y: y,
                        w: w,
                        h: h
                    });
                }
            }

            return {
                page_width: Math.max(document.body ? document.body.scrollWidth : 0, document.documentElement.scrollWidth),
                page_height: Math.max(document.body ? document.body.scrollHeight : 0, document.documentElement.scrollHeight),
                elements: elements
            };
        }
        """
        eval_result = page.evaluate(js_code)

        img_w = eval_result.get("page_width", 1280)
        img_h = eval_result.get("page_height", 800)
        try:
            with Image.open(out_png_path) as im:
                img_w, img_h = im.size
        except Exception:
            pass

        data = {
            "monitor_id": monitor_id,
            "url": url,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "image_width": img_w,
            "image_height": img_h,
            "elements": eval_result.get("elements", []),
        }

        with open(out_json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        return data

    finally:
        if page is not None:
            try:
                page.close()
            except Exception:
                pass
        if context is not None:
            try:
                context.close()
            except Exception:
                pass


def add_selector_to_monitor(monitor_id, selector_type, selector):
    selector = selector.strip()
    if not selector or selector_type not in ("include", "ignore"):
        return False

    column = "include_selectors" if selector_type == "include" else "ignore_selectors"
    rows = run_query(f"SELECT {column} FROM monitors WHERE id = ?", (monitor_id,))
    if not rows:
        return False

    current_val = rows[0][column] or ""
    lines = [line.strip() for line in current_val.splitlines() if line.strip()]

    if selector not in lines:
        lines.append(selector)
        run_write(f"UPDATE monitors SET {column} = ? WHERE id = ?", ("\n".join(lines), monitor_id))
    return True


def remove_selector_from_monitor(monitor_id, selector_type, selector):
    selector = selector.strip()
    if not selector or selector_type not in ("include", "ignore"):
        return False

    column = "include_selectors" if selector_type == "include" else "ignore_selectors"
    rows = run_query(f"SELECT {column} FROM monitors WHERE id = ?", (monitor_id,))
    if not rows:
        return False

    current_val = rows[0][column] or ""
    lines = [line.strip() for line in current_val.splitlines() if line.strip() and line.strip() != selector]
    run_write(f"UPDATE monitors SET {column} = ? WHERE id = ?", ("\n".join(lines), monitor_id))
    return True
