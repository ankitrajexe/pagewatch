# tests/test_imgdiff.py
# ---------------------
# What it does: Unit tests for visual screenshot diffing and region highlighting using Pillow.
# Talks to: pagewatch/imgdiff.py, pagewatch/config.py.

import os
import pytest
from PIL import Image, ImageDraw
from pagewatch import config
from pagewatch.imgdiff import make_diff_image, get_or_create_diff_image


class TestImageDiff:
    """Tests for make_diff_image and get_or_create_diff_image."""

    def test_identical_images_produce_zero_percent_diff(self, tmp_path):
        """Comparing two identical images gives 0.0% change."""
        img1_path = str(tmp_path / "img1.png")
        img2_path = str(tmp_path / "img2.png")
        diff_path = str(tmp_path / "diff_identical.png")

        # Create two identical 100x100 white squares
        img = Image.new("RGB", (100, 100), (255, 255, 255))
        img.save(img1_path)
        img.save(img2_path)

        changed_percent = make_diff_image(img1_path, img2_path, diff_path)
        assert changed_percent == 0.0
        assert os.path.exists(diff_path)

    def test_different_images_produce_positive_percent_and_highlight(self, tmp_path):
        """Image with a colored square produces > 0% change and draws bounding boxes."""
        img1_path = str(tmp_path / "img1.png")
        img2_path = str(tmp_path / "img2.png")
        diff_path = str(tmp_path / "diff_changed.png")

        # Base white image
        img1 = Image.new("RGB", (120, 120), (255, 255, 255))
        img1.save(img1_path)

        # Image 2 has a large dark blue rectangle (definitely > 2% of pixels in tiles)
        img2 = Image.new("RGB", (120, 120), (255, 255, 255))
        draw = ImageDraw.Draw(img2)
        draw.rectangle([20, 20, 80, 80], fill=(0, 0, 180))
        img2.save(img2_path)

        changed_percent = make_diff_image(img1_path, img2_path, diff_path)
        assert changed_percent > 0.0
        assert os.path.exists(diff_path)

        # Output image should be valid PNG
        with Image.open(diff_path) as out:
            assert out.size == (120, 120)

    def test_mismatched_dimensions_padded_correctly(self, tmp_path):
        """Images of different sizes are padded with white canvas and compared cleanly."""
        img1_path = str(tmp_path / "small.png")
        img2_path = str(tmp_path / "large.png")
        diff_path = str(tmp_path / "diff_mismatched.png")

        small = Image.new("RGB", (80, 80), (255, 255, 255))
        small.save(img1_path)

        large = Image.new("RGB", (120, 100), (255, 255, 255))
        draw = ImageDraw.Draw(large)
        draw.rectangle([90, 10, 115, 60], fill=(200, 0, 0))
        large.save(img2_path)

        changed_percent = make_diff_image(img1_path, img2_path, diff_path)
        assert changed_percent > 0.0
        assert os.path.exists(diff_path)

        with Image.open(diff_path) as out:
            # Output matches max dimensions
            assert out.size == (120, 100)

    def test_get_or_create_diff_image_caching(self, tmp_path, monkeypatch):
        """get_or_create_diff_image saves file to config.DIFF_DIR and caches result."""
        diff_dir = tmp_path / "diffs"
        diff_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(config, "DIFF_DIR", str(diff_dir))

        img1_path = str(tmp_path / "snap1.png")
        img2_path = str(tmp_path / "snap2.png")

        img1 = Image.new("RGB", (80, 80), (255, 255, 255))
        img1.save(img1_path)
        img2 = Image.new("RGB", (80, 80), (0, 0, 0))
        img2.save(img2_path)

        diff_filename, percent1 = get_or_create_diff_image(10, 20, img1_path, img2_path)
        assert diff_filename == "diff_10_20.png"
        assert percent1 > 0.0
        assert os.path.exists(diff_dir / "diff_10_20.png")

        # Second call returns cached values
        diff_filename2, percent2 = get_or_create_diff_image(10, 20, img1_path, img2_path)
        assert diff_filename2 == diff_filename
        assert percent2 == percent1
