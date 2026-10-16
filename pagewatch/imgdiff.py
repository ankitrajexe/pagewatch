import os
from PIL import Image, ImageChops, ImageDraw
from pagewatch import config

_DIFF_PERCENT_CACHE = {}


def make_diff_image(old_png_path, new_png_path, out_path):
    old_img = Image.open(old_png_path).convert("RGB")
    new_img = Image.open(new_png_path).convert("RGB")

    max_w = max(old_img.width, new_img.width)
    max_h = max(old_img.height, new_img.height)

    padded_old = Image.new("RGB", (max_w, max_h), (255, 255, 255))
    padded_old.paste(old_img, (0, 0))

    padded_new = Image.new("RGB", (max_w, max_h), (255, 255, 255))
    padded_new.paste(new_img, (0, 0))

    diff = ImageChops.difference(padded_old, padded_new).convert("L")
    # ignore minor anti-aliasing jitter
    diff_thresh = diff.point(lambda p: 255 if p > 25 else 0)

    total_pixels = max_w * max_h
    if total_pixels == 0:
        return 0.0

    histogram = diff_thresh.histogram()
    changed_pixel_count = histogram[255] if len(histogram) > 255 else 0
    changed_percent = round((changed_pixel_count / total_pixels) * 100.0, 2)

    tile_size = 40
    cols = (max_w + tile_size - 1) // tile_size
    rows = (max_h + tile_size - 1) // tile_size

    changed_tiles = set()
    for r in range(rows):
        y1 = r * tile_size
        y2 = min(y1 + tile_size, max_h)
        for c in range(cols):
            x1 = c * tile_size
            x2 = min(x1 + tile_size, max_w)

            tile_crop = diff_thresh.crop((x1, y1, x2, y2))
            tile_hist = tile_crop.histogram()
            tile_changed_pixels = tile_hist[255] if len(tile_hist) > 255 else 0
            tile_total_pixels = (x2 - x1) * (y2 - y1)

            if tile_total_pixels > 0 and (tile_changed_pixels / tile_total_pixels) > 0.02:
                changed_tiles.add((r, c))

    visited = set()
    rectangles = []

    for tile in sorted(changed_tiles):
        if tile in visited:
            continue

        component = []
        queue = [tile]
        visited.add(tile)

        while queue:
            curr_r, curr_c = queue.pop(0)
            component.append((curr_r, curr_c))

            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    if dr == 0 and dc == 0:
                        continue
                    nbr = (curr_r + dr, curr_c + dc)
                    if nbr in changed_tiles and nbr not in visited:
                        visited.add(nbr)
                        queue.append(nbr)

        min_r = min(r for r, c in component)
        max_r = max(r for r, c in component)
        min_c = min(c for r, c in component)
        max_c = max(c for r, c in component)

        box_x1 = max(0, min_c * tile_size)
        box_y1 = max(0, min_r * tile_size)
        box_x2 = min(max_w, (max_c + 1) * tile_size)
        box_y2 = min(max_h, (max_r + 1) * tile_size)
        rectangles.append((box_x1, box_y1, box_x2, box_y2))

    result_img = padded_new.copy()
    draw = ImageDraw.Draw(result_img)
    for box in rectangles:
        draw.rectangle(box, outline="red", width=3)

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    result_img.save(out_path, format="PNG")
    return changed_percent


def get_or_create_diff_image(snapshot_a_id, snapshot_b_id, old_png_path, new_png_path):
    cache_key = (snapshot_a_id, snapshot_b_id)
    diff_filename = f"diff_{snapshot_a_id}_{snapshot_b_id}.png"
    out_path = os.path.join(config.DIFF_DIR, diff_filename)

    if os.path.exists(out_path) and cache_key in _DIFF_PERCENT_CACHE:
        return diff_filename, _DIFF_PERCENT_CACHE[cache_key]

    changed_percent = make_diff_image(old_png_path, new_png_path, out_path)
    _DIFF_PERCENT_CACHE[cache_key] = changed_percent
    return diff_filename, changed_percent
