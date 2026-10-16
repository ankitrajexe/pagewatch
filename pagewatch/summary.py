import re
from pagewatch.differ import text_diff_lines


def make_summary(old_text, new_text, keyword=None):
    if old_text is None:
        old_text = ""
    if new_text is None:
        new_text = ""

    if old_text == new_text:
        return "0 lines added, 0 removed"

    old_lower = old_text.lower()
    new_lower = new_text.lower()

    if keyword and isinstance(keyword, str) and keyword.strip():
        kw_clean = keyword.strip()
        kw_lower = kw_clean.lower()
        was_in_old = kw_lower in old_lower
        is_in_new = kw_lower in new_lower
        if not was_in_old and is_in_new:
            return f"Keyword '{kw_clean}' appeared"
        elif was_in_old and not is_in_new:
            return f"Keyword '{kw_clean}' disappeared"

    out_phrases = ["out of stock", "sold out"]
    in_phrases = ["in stock", "back in stock"]
    has_out_old = any(p in old_lower for p in out_phrases)
    has_out_new = any(p in new_lower for p in out_phrases)
    has_in_old = any(p in old_lower for p in in_phrases) and not has_out_old
    has_in_new = any(p in new_lower for p in in_phrases) and not has_out_new

    if has_out_old and has_in_new:
        return "Changed from 'Out of stock' to 'In stock'"
    elif has_in_old and has_out_new:
        return "Changed from 'In stock' to 'Out of stock'"

    diff = text_diff_lines(old_text, new_text)
    added_lines = [line.strip() for kind, line in diff if kind == "added" and line.strip()]
    removed_lines = [line.strip() for kind, line in diff if kind == "removed" and line.strip()]

    num_pattern = r"\b\d+(?:[\.,]\d+)?\b"
    old_num = None
    new_num = None
    context_text = ""

    if len(removed_lines) == 1 and len(added_lines) == 1:
        old_nums = re.findall(num_pattern, removed_lines[0])
        new_nums = re.findall(num_pattern, added_lines[0])
        if len(old_nums) == 1 and len(new_nums) == 1 and old_nums[0] != new_nums[0]:
            masked_old = re.sub(num_pattern, "___NUM___", removed_lines[0])
            masked_new = re.sub(num_pattern, "___NUM___", added_lines[0])
            if masked_old == masked_new:
                old_num = old_nums[0]
                new_num = new_nums[0]
                context_text = removed_lines[0] + " " + added_lines[0]

    if old_num is None:
        all_old_nums = re.findall(num_pattern, old_text)
        all_new_nums = re.findall(num_pattern, new_text)
        if len(all_old_nums) == len(all_new_nums) and len(all_old_nums) > 0:
            diff_pairs = [(o, n) for o, n in zip(all_old_nums, all_new_nums) if o != n]
            if len(diff_pairs) == 1:
                masked_all_old = re.sub(num_pattern, "___NUM___", old_text)
                masked_all_new = re.sub(num_pattern, "___NUM___", new_text)
                if masked_all_old == masked_all_new:
                    old_num = diff_pairs[0][0]
                    new_num = diff_pairs[0][1]
                    context_text = old_text + " " + new_text

    if old_num is not None and new_num is not None:
        try:
            old_val = float(old_num.replace(",", ""))
            new_val = float(new_num.replace(",", ""))
        except ValueError:
            old_val, new_val = None, None

        if old_val is not None and new_val is not None:
            price_indicators = ["$", "€", "£", "₹", "rs", "usd", "eur", "gbp", "price", "cost", "sale"]
            ctx_lower = context_text.lower()
            is_price = any(ind in ctx_lower for ind in price_indicators)
            label = "Price" if is_price else "Number"

            if old_val == 0:
                pct_str = "(+0.0%)"
                verb = "changed"
            else:
                pct = ((new_val - old_val) / old_val) * 100.0
                pct_str = f"({pct:+.1f}%)"
                if new_val < old_val:
                    verb = "dropped"
                elif new_val > old_val:
                    verb = "rose"
                else:
                    verb = "changed"

            return f"{label} {verb} from {old_num} to {new_num} {pct_str}"

    if added_lines and len(removed_lines) <= 2:
        for line in added_lines:
            if re.match(r"^#{1,4}\s+[A-Za-z0-9]", line):
                sec_name = re.sub(r"^#{1,4}\s+", "", line).strip()
                return f"New section appeared: '{sec_name}'"
            if re.match(r"^[A-Z][A-Za-z0-9\s/&'-]{2,40}:$", line):
                sec_name = line.rstrip(":").strip()
                return f"New section appeared: '{sec_name}'"
            if re.match(r"^\[[A-Za-z0-9\s/&'-]{2,40}\]$", line):
                sec_name = line.strip("[]").strip()
                return f"New section appeared: '{sec_name}'"

    added_count = len(added_lines)
    removed_count = len(removed_lines)
    add_label = "1 line added" if added_count == 1 else f"{added_count} lines added"
    rem_label = "1 removed" if removed_count == 1 else f"{removed_count} removed"
    counts_str = f"{add_label}, {rem_label}"

    examples = []
    if added_lines:
        examples.append(f'+ "{_trim_line(added_lines[0], 80)}"')
    if removed_lines:
        examples.append(f'- "{_trim_line(removed_lines[0], 80)}"')
    elif len(added_lines) > 1:
        examples.append(f'+ "{_trim_line(added_lines[1], 80)}"')

    if not added_lines and len(removed_lines) > 1:
        examples.append(f'- "{_trim_line(removed_lines[1], 80)}"')

    if examples:
        return f"{counts_str}: {', '.join(examples)}"
    return counts_str


def _trim_line(text, max_len=80):
    text = text.replace("\r", " ").replace("\n", " ").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."
