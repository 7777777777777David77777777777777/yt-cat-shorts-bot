from array import array
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
import wave
from unittest.mock import AsyncMock, Mock, patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import script_preview as preview


class ScriptReaderTests(unittest.TestCase):
    def fixture(self):
        data = preview.parse_markdown((preview.STORIES / "EP01.md").read_text())
        preview.expand_character_profile(data)
        return data

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
            self.assertEqual(scene["expression"], original.get("expression", ""))
            if scene["expression"]:
                self.assertIn(scene["expression"], scene["full_image_prompt"])
        self.assertFalse(story["script_rewritten"])
        self.assertNotIn("sent_count", story)
        self.assertNotIn("row_index", story)

    def test_fashion_template_uses_one_adult_and_realistic_style(self):
        story = preview.load_script("stories/EP01.md")
        self.assertEqual(story["title"], "辦公秘書寫真｜黑絲襪與高跟鞋")
        self.assertEqual(len(story["characters"]), 1)
        self.assertIn("28-year-old adult woman", story["characters"][0])
        self.assertEqual(story["visual_style_id"], "photorealistic")
        self.assertEqual(len(story["scenes"]), 4)
        for scene in story["scenes"]:
            self.assertNotIn("Mia", scene["full_image_prompt"])
            self.assertNotIn("6-year-old", scene["full_image_prompt"])
            self.assertIn("Ava", scene["full_image_prompt"])
        self.assertTrue(all(not scene["narration"] for scene in story["scenes"]))
        self.assertFalse(story["narration_enabled"])
        self.assertFalse(story["subtitles_enabled"])
        self.assertEqual([s["shot"]["type"] for s in story["scenes"]], ["full_body", "half_body", "full_body", "detail"])
        self.assertIn("pencil skirt", story["wardrobe"]["bottom"])
        self.assertFalse(story["scenes"][3]["shot"]["face_visible"])
        self.assertIn("complete foreground shoe", story["scenes"][3]["shot"]["coverage"])
        self.assertNotIn("blouse", story["characters"][0])

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

    def test_narration_is_optional_but_each_photo_needs_an_action(self):
        source = self.fixture()
        for scene in source["scenes"]:
            scene.pop("narration")
        preview.validate_script(source)
        source["scenes"][0]["action"] = ""
        with self.assertRaises(ValueError):
            preview.validate_script(source)

    def test_invalid_bgm_is_rejected_before_images(self):
        for bgm in ("../outside.wav", "README.md", "assets/bgm/missing.mp3"):
            with self.subTest(bgm=bgm), \
                    patch.object(sys, "argv", ["script_preview.py", "--bgm", bgm]), \
                    patch.object(preview, "make_keyframe") as image, \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(preview.main(), 1)
                image.assert_not_called()

    def test_markdown_typo_or_duplicate_section_is_rejected(self):
        text = (preview.STORIES / "EP01.md").read_text()
        for changed in (text.replace("## 氛圍", "## 畫風拼錯"),
                        text.replace("### 動作", "### 動作\n\nDuplicate\n\n### 動作", 1),
                        text.replace("## 第2幕", "## 第1幕")):
            with self.assertRaises(ValueError):
                preview.parse_markdown(changed)

    def test_english_markdown_headings_are_supported(self):
        text = (preview.STORIES / "EP01.md").read_text()
        original = preview.parse_markdown(text)
        for before, after in {"角色檔": "Character profile", "共同場景": "Setting", "服裝": "Wardrobe",
                              "標題": "Title", "氛圍": "Genre", "標籤": "Tags", "角色": "Characters",
                              "旁白": "Narration", "畫面": "Action", "主角參考": "Character references",
                              "表情": "Expression", "動作": "Action", "鏡頭": "Shot"}.items():
            text = text.replace(before, after)
        for i in range(1, 5):
            text = text.replace(f"第{i}幕", f"Scene {i}")
        self.assertEqual(preview.parse_markdown(text), original)

    def test_one_wardrobe_change_is_applied_to_all_scenes_without_changing_identity(self):
        source = self.fixture()
        before = preview.load_script("stories/EP01.md")
        source["wardrobe"] = {"one_piece": "Opaque emerald-green midi dress", "hosiery": "Plain ivory cotton socks",
                              "footwear": "Brown flat loafers", "accessories": "Small stud earrings"}
        preview.validate_script(source)
        for scene in source["scenes"]:
            prompt = preview.build_scene_prompt(scene, source, "photorealistic", before["character_profile"])
            self.assertIn("Opaque emerald-green midi dress", prompt)
            self.assertIn("Plain ivory cotton socks", prompt)
            self.assertNotIn("Ivory satin", prompt)
            self.assertNotIn("20-denier", prompt)
        self.assertNotIn("155 cm", preview.build_scene_prompt(source["scenes"][3], source, "photorealistic",
                                                              before["character_profile"]))

    def test_location_override_does_not_change_the_episode_outfit(self):
        source = self.fixture()
        source["scenes"][1]["location"] = "A quiet cafe beside a window"
        prompt = preview.build_scene_prompt(source["scenes"][1], source, "photorealistic", None)
        self.assertIn("A quiet cafe", prompt)
        self.assertNotIn(source["setting"]["location"], prompt)
        self.assertIn(source["wardrobe"]["top"], prompt)

    def test_structured_conflicts_stop_before_paid_client_creation(self):
        from google import genai
        original = (preview.STORIES / "EP01.md").read_text()
        cases = [
            original.replace("### 動作", "### 服裝", 1),
            original.replace("- 襪類：", "- 襪子拼錯：", 1),
            original.replace("- 襪類：", "- 上衣：Duplicate\n- 襪類：", 1),
            original.replace("- 上衣：", "- 連身衣：Contradictory dress\n- 上衣：", 1),
            original.replace("- 臉部入鏡：是", "- 臉部入鏡：否", 1),
            original.replace("- 臉部入鏡：否", "- 臉部入鏡：是"),
            original.replace("## 第4幕", "## 第4幕\n\n### 表情\n\nSmile at camera"),
            original.replace("## 服裝", "## 角色\n\n- A conflicting model\n\n## 服裝"),
            original.replace("assets/characters/ava/profile.md", "../outside.md"),
            original.replace("取景來源：第1幕", "取景來源：第4幕"),
            original.replace("0.33, 0.69, 0.64, 1.00", "0.8, 0.64, 0.3, 1.0"),
            original.replace("0.33, 0.69, 0.64, 1.00", "0.3, nan, 0.7, 1.0"),
            original.replace("- 裁切範圍：0.33, 0.69, 0.64, 1.00", ""),
        ]
        for text in cases:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".md", dir=preview.STORIES) as source:
                source.write(text)
                source.flush()
                with self.subTest(text=text[:20]), patch.object(sys, "argv", ["script_preview.py", "--script", source.name]), \
                        patch.object(genai, "Client", side_effect=AssertionError) as client, \
                        contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(preview.main(), 1)
                    client.assert_not_called()

    def test_reusable_profile_and_named_images_are_independent_of_field_order(self):
        from story_structure import parse_profile
        source = (preview.ROOT / "assets/characters/ava/profile.md").read_text()
        source = source.replace("- 肖像：portrait.png\n- 全身：full_body.png", "- 全身：full_body.png\n- 肖像：portrait.png")
        profile = parse_profile(source)
        self.assertEqual(profile["references"]["portrait"], "portrait.png")
        with self.assertRaises(ValueError):
            parse_profile(source.replace("## 外觀", "## 服裝"))

    def test_profile_image_paths_cannot_escape_the_character_directory(self):
        source = (preview.ROOT / "assets/characters/ava/profile.md").read_text()
        with tempfile.TemporaryDirectory(dir=preview.ROOT / "assets/characters") as temp:
            path = Path(temp) / "profile.md"
            path.write_text(source.replace("portrait.png", "/tmp/outside.png"))
            with self.assertRaisesRegex(ValueError, "不可離開"):
                preview.expand_character_profile({"character_profile": str(path.relative_to(preview.ROOT))})

    def test_character_reference_paths_are_checked_before_any_api_call(self):
        with tempfile.TemporaryDirectory(dir=preview.ROOT / "assets/characters") as temp:
            corrupt = Path(temp) / "corrupt.png"
            corrupt.write_bytes(b"not an image")
            cases = ["../outside.png", "README.md", "assets/characters/missing.png",
                     str(corrupt.relative_to(preview.ROOT))]
            for path in cases:
                with self.subTest(path=path), \
                        patch.object(preview, "make_keyframe") as image:
                    with self.assertRaises((ValueError, FileNotFoundError, OSError)):
                        preview.resolve_character_references([path])
                    image.assert_not_called()

    def test_invalid_reference_lists_and_expression_types_are_rejected(self):
        for refs in ("portrait.png", [None], [""], ["a.png"] * 3):
            with self.subTest(refs=refs), self.assertRaises(ValueError):
                preview.validate_script(dict(self.fixture(), character_references=refs))
        source = self.fixture()
        source["scenes"][0]["expression"] = 123
        with self.assertRaises(ValueError):
            preview.validate_script(source)

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
        self.assertEqual(story["character_reference_images"], [])
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
                patch.object(preview, "render_lookbook") as render:
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
    def test_generated_music_is_audible_and_custom_track_is_validated(self):
        with tempfile.TemporaryDirectory(dir=preview.ROOT / "assets/bgm") as temp:
            track = Path(temp) / "test.wav"
            preview.make_original_bgm(track, 0.2)
            with wave.open(str(track)) as audio:
                self.assertEqual(audio.getnframes(), 4410)
                samples = array("h", audio.readframes(audio.getnframes()))
                self.assertGreater(max(abs(x) for x in samples), 1000)
            self.assertEqual(preview.resolve_bgm(str(track.relative_to(preview.ROOT))), track)
            with tempfile.TemporaryDirectory() as output:
                image = Path(output) / "photo.png"
                Image.new("RGB", (90, 160), "gray").save(image)
                final = Path(output) / "loop.mp4"
                preview.render_lookbook([image], track, final, scene_seconds=0.8)
                pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", str(final), "-ss", "0.3", "-t", "0.2",
                                      "-vn", "-f", "s16le", "-ac", "1", "-"], capture_output=True, check=True).stdout
                self.assertGreater(max(abs(x) for x in array("h", pcm)), 100)

    def test_real_renderer_outputs_mp4_without_sheet_or_youtube(self):
        story = preview.load_script("stories/EP01.md")

        references = []

        def image(client, model, prompt, path, record, image_size, reference_images=None):
            self.assertEqual(image_size, (1080, 1920))
            self.assertEqual(len(reference_images), 2 if record["scene"] == 1 else 3)
            self.assertIn(preview.IDENTITY_INSTRUCTIONS, prompt)
            for reference, original in zip(reference_images[:2], story["character_reference_images"]):
                self.assertEqual(reference.read_bytes(), (preview.ROOT / original).read_bytes())
            if record["scene"] == 1:
                self.assertIsNone(record["reference_image"])
            else:
                self.assertEqual(reference_images[-1], path.parent / "scene_1.png")
                self.assertIn(preview.REFERENCE_INSTRUCTIONS, prompt)
                self.assertEqual(record["reference_image"], "scenes/scene_1.png")
                references.append(record["reference_sha256"])
            Image.new("RGB", (180, 320), (80 + record["scene"] * 20, 100, 140)).save(path)
            record.update(image_used=True, returned_images=1, total_tokens=100)

        previous_dir = preview.factory.SCENE_DIR
        client = Mock()
        with tempfile.TemporaryDirectory() as temp, \
                patch.object(preview, "make_keyframe", side_effect=image) as generate_image, \
                patch.object(preview.factory, "generate_speech_audio", side_effect=AssertionError) as generate_speech, \
                patch.object(preview.factory, "render_continuous_smooth_short", side_effect=AssertionError), \
                patch.object(preview.factory, "fetch_next_episode_from_google_sheet", side_effect=AssertionError), \
                patch.object(preview.factory.requests, "get", side_effect=AssertionError), \
                patch.object(preview.factory.requests, "post", side_effect=AssertionError):
            final = preview.render_script(story, temp, client, "test-image-model", scene_seconds=0.5)
            info = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(final)],
                                             capture_output=True, text=True, check=True).stdout)
            self.assertLess(abs(float(info["format"]["duration"]) - 2.0), 0.15)
            self.assertEqual({s["codec_type"] for s in info["streams"]}, {"video", "audio"})
            state = json.loads((Path(temp) / "metadata.json").read_text())
            self.assertEqual(state["status"], "completed")
            self.assertEqual(state["image_usage"]["images_used"], 3)
            self.assertEqual(state["reference_strategy"], "character_identity_and_fixed_first_scene")
            records = state["image_usage"]["requests"]
            self.assertEqual([len(r["reference_images"]) for r in records], [2, 3, 3])
            self.assertEqual(len({r["reference_images"][0]["sha256"] for r in records}), 1)
            self.assertEqual(len({r["reference_images"][1]["sha256"] for r in records}), 1)
            self.assertEqual(len(references), 2)
            self.assertEqual(len(set(references)), 1)
            self.assertTrue((Path(temp) / "scenes/scene_4.plan.txt").is_file())
            self.assertFalse((Path(temp) / "scenes/scene_4.prompt.txt").exists())
            self.assertEqual(len(state["scene_outputs"]), 4)
            self.assertEqual(state["scene_outputs"][1]["method"], "generated_then_crop")
            self.assertLessEqual(state["scene_outputs"][1]["crop_pixels"][3], 1000)
            detail = state["scene_outputs"][3]
            self.assertEqual(detail["method"], "source_crop")
            self.assertEqual(detail["source_scene"], 1)
            self.assertEqual(detail["source_image"], "scenes/scene_1.png")
            self.assertEqual(detail["source_sha256"], records[1]["reference_sha256"])
            self.assertFalse(state["youtube_upload"])
            self.assertFalse(state["sheet_read"])
            self.assertFalse(state["narration_enabled"])
            self.assertFalse(state["subtitles_enabled"])
            self.assertEqual(state["bgm_source"], "generated_instrumental_96bpm_v1")
            self.assertTrue((Path(temp) / "bgm.wav").is_file())
            self.assertEqual(generate_image.call_count, 3)
            generate_speech.assert_not_called()
            frame_bytes = subprocess.run(["ffmpeg", "-v", "error", "-ss", "0.2", "-i", str(final),
                                          "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"],
                                         capture_output=True, check=True).stdout
            with Image.open(io.BytesIO(frame_bytes)) as frame:
                center = frame.getpixel((540, 900))
                for coordinate in ((540, 1700), (100, 50)):
                    self.assertLess(max(abs(a - b) for a, b in zip(center, frame.getpixel(coordinate))), 4)
        self.assertEqual(preview.factory.SCENE_DIR, previous_dir)
        client.models.generate_videos.assert_not_called()


if __name__ == "__main__":
    unittest.main()
