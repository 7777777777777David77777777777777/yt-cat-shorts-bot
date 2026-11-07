"""Tests for actual pixels and source reuse, independent of a model's prompt compliance."""

from pathlib import Path
import sys
import tempfile
import unittest

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shot_framing import crop_scene, validate_crop
from lookbook_render import photo_frame


class FramingTests(unittest.TestCase):
    def test_detail_really_excludes_upper_region_and_preserves_both_shoes(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "source.png"
            target = Path(temp) / "detail.png"
            image = Image.new("RGB", (100, 200), "blue")
            draw = ImageDraw.Draw(image)
            draw.rectangle((0, 0, 99, 99), fill="red")
            draw.rectangle((34, 177, 45, 195), fill="yellow")
            draw.rectangle((54, 177, 65, 195), fill="lime")
            image.save(source)
            info = crop_scene(source, target, [.32, .64, .68, 1], output_size=(180, 320))
            self.assertGreaterEqual(info["crop_pixels"][1], 128)
            with Image.open(target) as detail:
                colors = [detail.getpixel((x, y)) for y in range(detail.height) for x in range(detail.width)]
                self.assertFalse(any(r > 240 and g < 10 and b < 10 for r, g, b in colors))
                self.assertTrue(any(r > 240 and g > 240 and b < 10 for r, g, b in colors))
                self.assertTrue(any(r < 10 and g > 240 and b < 10 for r, g, b in colors))
                self.assertEqual(detail.size, (180, 320))

    def test_crop_keeps_source_unchanged_and_preserves_requested_region(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "source.png"
            Image.new("RGB", (1080, 1920), "gray").save(source)
            original = source.read_bytes()
            info = crop_scene(source, Path(temp) / "out.png", [.2, .7, .8, 1])
            left, top, right, bottom = info["crop_pixels"]
            self.assertLessEqual(left, .2 * 1080)
            self.assertLessEqual(top, .7 * 1920)
            self.assertGreaterEqual(right, .8 * 1080)
            self.assertGreaterEqual(bottom, 1920)
            self.assertEqual(source.read_bytes(), original)

    def test_invalid_crops_fail_instead_of_creating_a_wrong_frame(self):
        for box in ([], [0, 0, 1], [0, 0, 1, float("nan")], [0, 0, 1, float("inf")],
                    [True, 0, 1, 1], [0, 0, 2, 1], [.8, 0, .2, 1]):
            with self.subTest(box=box), self.assertRaises(ValueError):
                validate_crop(box)

    def test_still_detail_has_no_extra_zoom_to_cut_off_edge_details(self):
        image = Image.new("RGB", (1080, 1920), "black")
        ImageDraw.Draw(image).rectangle((0, 0, 25, 1919), fill="white")
        for progress in (0, .5, 1):
            self.assertEqual(photo_frame(image, progress, 0, zoom_amount=0).tobytes(), image.tobytes())


if __name__ == "__main__":
    unittest.main()
