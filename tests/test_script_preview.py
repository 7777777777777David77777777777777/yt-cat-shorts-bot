import asyncio
import contextlib
import copy
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import script_preview as preview


class ScriptReaderTests(unittest.TestCase):
    def fixture(self):
        return preview.parse_markdown((preview.STORIES / "EP01.md").read_text())

    def test_markdown_parses_handwritten_fields_and_scene_order(self):
        text = "# EP42\n## 標題\n試穿\n## 氛圍\nStudio\n## 角色\n- One adult model\n"
        for i in range(1, 5):
            text += f"## 第{i}幕\n### 旁白\nNarration {i}\n### 畫面\nAction {i}\n"
        data = preview.parse_markdown(text)
        self.assertEqual(data["id"], "EP42")
        self.assertEqual(data["title"], "試穿")
        self.assertEqual(data["characters"], ["One adult model"])
        self.assertEqual(data["tags"], [])
        self.assertEqual(data["scenes"], [{"narration": f"Narration {i}", "action": f"Action {i}"}
                                         for i in range(1, 5)])

    def test_user_title_and_narration_are_not_rewritten(self):
        source = self.fixture()
        story = preview.load_script("stories/EP01.md")
        self.assertEqual(story["title"], source["title"])
        self.assertEqual(story["characters"], source["characters"])
        for original, scene in zip(source["scenes"], story["scenes"]):
            self.assertEqual(scene["narration"], original["narration"])
            self.assertEqual(scene["scene_action"], original["action"])
            self.assertIn(source["genre"], scene["full_image_prompt"])
        self.assertFalse(story["script_rewritten"])
        self.assertNotIn("sent_count", story)
        self.assertNotIn("row_index", story)

    def test_fashion_template_uses_one_adult_and_realistic_style(self):
        story = preview.load_script("stories/EP01.md")
        self.assertEqual(story["title"], "服裝試穿")
        self.assertEqual(len(story["characters"]), 1)
        self.assertIn("28-year-old adult woman", story["characters"][0])
        self.assertEqual(story["visual_style_id"], "photorealistic")
        self.assertEqual(len(story["scenes"]), 4)
        for scene in story["scenes"]:
            self.assertNotIn("Mia", scene["full_image_prompt"])
            self.assertNotIn("6-year-old", scene["full_image_prompt"])
            self.assertIn("Ava", scene["full_image_prompt"])
        self.assertIn("knit top", story["scenes"][1]["narration"])
        self.assertIn("trousers", story["scenes"][2]["narration"])
        self.assertIn("socks", story["scenes"][3]["narration"])

    def test_one_two_or_three_characters_are_supported(self):
        for count in (1, 2, 3):
            source = self.fixture()
            source["characters"] = [f"Adult character {i}" for i in range(count)]
            self.assertEqual(len(preview.validate_script(source)["characters"]), count)

    def test_style_changes_do_not_change_handwritten_story(self):
        original = preview.load_script("stories/EP01.md")
        for style in preview.STYLES:
            with self.subTest(style=style):
                story = preview.load_script("stories/EP01.md", style)
                self.assertEqual(story["title"], original["title"])
                for old, new in zip(original["scenes"], story["scenes"]):
                    self.assertEqual(old["narration"], new["narration"])
                    self.assertEqual(old["scene_action"], new["scene_action"])
                    self.assertIn(preview.STYLES[style]["prompt"], new["full_image_prompt"])

    def test_bad_structures_are_rejected_before_api_calls(self):
        original = self.fixture()
        invalid = [None, [], dict(original, characters=[]), dict(original, characters=["cat"] * 4),
                   dict(original, characters=["cat", "dog", ""]), dict(original, scenes=original["scenes"][:3]),
                   dict(original, id="01"), dict(original, genre=""), dict(original, tags="cat,dog"),
                   dict(original, typo="unexpected")]
        bad = copy.deepcopy(original)
        bad["scenes"][2]["action"] = ""
        invalid.append(bad)
        for source in invalid:
            with self.subTest(source_type=type(source).__name__):
                with self.assertRaises(ValueError):
                    preview.validate_script(source)

    def test_markdown_typo_or_duplicate_section_is_rejected(self):
        text = (preview.STORIES / "EP01.md").read_text()
        for changed in (text.replace("## 氛圍", "## 畫風拼錯"),
                        text.replace("### 畫面", "### 旁白", 1),
                        text.replace("## 第2幕", "## 第1幕")):
            with self.assertRaises(ValueError):
                preview.parse_markdown(changed)

    def test_english_markdown_headings_are_supported(self):
        text = (preview.STORIES / "EP01.md").read_text()
        for before, after in {"標題": "Title", "氛圍": "Genre", "標籤": "Tags", "角色": "Characters",
                              "旁白": "Narration", "畫面": "Action"}.items():
            text = text.replace(before, after)
        for i in range(1, 5):
            text = text.replace(f"第{i}幕", f"Scene {i}")
        self.assertEqual(preview.parse_markdown(text), self.fixture())

    def test_sources_outside_stories_are_rejected(self):
        for path in ("/tmp/story.md", "stories/../requirements.txt", "../story.md", "stories/EP01.json"):
            with self.assertRaises(ValueError):
                preview.load_script(path)

    def test_animals_only_script_uses_only_handwritten_cast(self):
        source = self.fixture()
        source["characters"] = ["Pip, a small brown puppy", "Mochi, an orange kitten", "Ollie, a barn owl"]
        for scene in source["scenes"]:
            scene.update(narration="The three friends smile together.", action="Pip, Mochi and Ollie sit under a tree.")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "stories").mkdir()
            parts = ["# EP02", "## 標題", "Animal friends", "## 氛圍", "Warm friendship", "## 角色",
                     "\n".join("- " + c for c in source["characters"])]
            for i, scene in enumerate(source["scenes"], 1):
                parts.extend([f"## 第{i}幕", "### 旁白", scene["narration"], "### 畫面", scene["action"]])
            (root / "stories/animals.md").write_text("\n\n".join(parts))
            with patch.object(preview, "ROOT", root), patch.object(preview, "STORIES", root / "stories"):
                story = preview.load_script("stories/animals.md")
        for scene in story["scenes"]:
            self.assertNotIn("Mia", scene["full_image_prompt"])
            self.assertNotIn("girl", scene["full_image_prompt"])
            self.assertIn("Ollie", scene["full_image_prompt"])

    def test_validation_mode_never_reads_sheet_or_generates_content(self):
        from google import genai
        with patch.object(preview.sys, "argv", ["script_preview.py", "--validate-only"]), \
                patch.object(preview.factory, "fetch_next_episode_from_google_sheet", side_effect=AssertionError), \
                patch.object(preview.factory.requests, "get", side_effect=AssertionError), \
                patch.object(preview.factory.requests, "post", side_effect=AssertionError), \
                patch.object(genai, "Client", side_effect=AssertionError), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(preview.main(), 0)

    def test_image_failure_saves_diagnostics_and_never_renders_fake_video(self):
        story = preview.load_script("stories/EP01.md")
        with tempfile.TemporaryDirectory() as temp, \
                patch.object(preview, "make_keyframe", side_effect=RuntimeError("Image unavailable")), \
                patch.object(preview.factory, "generate_speech_audio", new_callable=AsyncMock) as speech, \
                patch.object(preview.factory, "render_continuous_smooth_short") as render:
            with self.assertRaisesRegex(RuntimeError, "Image unavailable"):
                preview.render_script(story, temp, Mock(), "test-image-model")
            state = json.loads((Path(temp) / "metadata.json").read_text())
            self.assertEqual(state["status"], "failed")
            self.assertEqual(state["video_generation_requests"], 0)
            self.assertFalse((Path(temp) / "preview.mp4").exists())
            speech.assert_not_called()
            render.assert_not_called()


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
class ScriptRenderTests(unittest.TestCase):
    def test_real_renderer_outputs_mp4_without_sheet_or_youtube(self):
        story = preview.load_script("stories/EP01.md")

        def image(client, model, prompt, path, record, image_size):
            self.assertEqual(image_size, (1080, 1920))
            Image.effect_noise((180, 320), 60).convert("RGB").save(path)
            record.update(image_used=True, returned_images=1, total_tokens=100)

        async def speech(text, path, voice):
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                            "sine=frequency=440:sample_rate=44100", "-t", "2.1", path], check=True)

        previous_dir = preview.factory.SCENE_DIR
        client = Mock()
        with tempfile.TemporaryDirectory() as temp, \
                patch.object(preview, "make_keyframe", side_effect=image) as generate_image, \
                patch.object(preview.factory, "generate_speech_audio", side_effect=speech) as generate_speech, \
                patch.object(preview.factory, "fetch_next_episode_from_google_sheet", side_effect=AssertionError), \
                patch.object(preview.factory.requests, "get", side_effect=AssertionError), \
                patch.object(preview.factory.requests, "post", side_effect=AssertionError):
            final = preview.render_script(story, temp, client, "test-image-model")
            info = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_format", "-of", "json", str(final)],
                                             capture_output=True, text=True, check=True).stdout)
            self.assertLess(abs(float(info["format"]["duration"]) - 8.4), 0.5)
            state = json.loads((Path(temp) / "metadata.json").read_text())
            self.assertEqual(state["status"], "completed")
            self.assertEqual(state["image_usage"]["images_used"], 4)
            self.assertFalse(state["youtube_upload"])
            self.assertFalse(state["sheet_read"])
            self.assertEqual(generate_image.call_count, 4)
            self.assertEqual(generate_speech.call_count, 4)
        self.assertEqual(preview.factory.SCENE_DIR, previous_dir)
        client.models.generate_videos.assert_not_called()


if __name__ == "__main__":
    unittest.main()
