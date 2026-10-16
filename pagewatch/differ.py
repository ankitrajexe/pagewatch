import difflib


def text_diff_lines(old_text, new_text):
    old_lines = (old_text or "").splitlines()
    new_lines = (new_text or "").splitlines()

    diff = []
    matcher = difflib.SequenceMatcher(None, old_lines, new_lines)

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for line in old_lines[i1:i2]:
                diff.append(("same", line))
        elif tag == "replace":
            for line in old_lines[i1:i2]:
                diff.append(("removed", line))
            for line in new_lines[j1:j2]:
                diff.append(("added", line))
        elif tag == "delete":
            for line in old_lines[i1:i2]:
                diff.append(("removed", line))
        elif tag == "insert":
            for line in new_lines[j1:j2]:
                diff.append(("added", line))

    return diff


def count_diff_lines(old_text, new_text):
    diff = text_diff_lines(old_text, new_text)
    added = sum(1 for kind, _ in diff if kind == "added")
    removed = sum(1 for kind, _ in diff if kind == "removed")
    return added, removed


def side_by_side_html(old_text, new_text):
    old_lines = (old_text or "").splitlines()
    new_lines = (new_text or "").splitlines()

    hd = difflib.HtmlDiff(wrapcolumn=60)
    return hd.make_table(
        old_lines,
        new_lines,
        fromdesc="Older Snapshot",
        todesc="Newer Snapshot",
        context=True,
        numlines=3,
    )
