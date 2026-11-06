import base64
import contextlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

import httpx
from google import genai
from google.genai import types
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import preview_ep01 as preview


def operation(**kwargs):
    return types.GenerateVideosOperation(name="models/test/operations/preview", **kwargs)


class PreviewTests(unittest.TestCase):
    def test_fixed_ep01_preserves_cast_and_plot_without_using_live_queue(self):
        with patch.object(preview.factory, "fetch_next_episode_from_google_sheet", side_effect=AssertionError), \
                patch.object(preview.factory.requests, "get", side_effect=AssertionError), \
                patch.object(preview.factory.requests, "post", side_effect=AssertionError):
            story = preview.load_episode()
        original = json.loads(preview.FIXTURE.read_text())["episode"]
        self.assertEqual((story["id"], story["visual_style_id"]), ("EP01", "cinematic_3d"))
        self.assertIn("6-year-old", story["character_dna"])
        self.assertEqual([s["narration"] for s in story["scenes"]],
                         [original[f"s{i}_narration"] for i in range(1, 5)])
        self.assertIsNone(story["row_index"])
        self.assertFalse(story["youtube_upload"])
        self.assertFalse(story["sheet_writeback"])
        for i in range(4):
            self.assertIn("6-year-old", preview.video_prompt(story, i))

    def test_sdk_developer_api_wire_preserves_prompt_and_image(self):
        captured = []

        def transport(request):
            captured.append(request)
            return httpx.Response(200, json={
                "name": "models/test/operations/preview", "done": True,
                "response": {"generateVideoResponse": {"generatedSamples": [
                    {"video": {"encodedVideo": base64.b64encode(b"downloaded-mp4").decode(),
                               "encoding": "video/mp4"}}]}}})

        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            image = directory / "reference.png"
            Image.new("RGB", (16, 32), "orange").save(image)
            prompt = preview.video_prompt(preview.load_episode(), 0)
            with genai.Client(api_key="test-only", vertexai=False, http_options=types.HttpOptions(
                    httpx_client=httpx.Client(transport=httpx.MockTransport(transport)),
                    retry_options=types.HttpRetryOptions(attempts=1))) as client, \
                    patch.object(preview, "probe", return_value={
                        "streams": [{"codec_type": "video"}], "format": {"duration": "8"}}):
                preview.generate_clip(client, preview.PREFERRED_VIDEO_MODELS[0], prompt, image,
                                      directory / "clip.mp4", {}, lambda: None, float("inf"))
            self.assertEqual((directory / "clip.mp4").read_bytes(), b"downloaded-mp4")
        self.assertEqual(len(captured), 1)
        request = captured[0]
        self.assertEqual(request.url.host, "generativelanguage.googleapis.com")
        self.assertTrue(request.url.path.endswith(":predictLongRunning"))
        body = json.loads(request.content)
        self.assertEqual(body["instances"][0]["prompt"], prompt)
        self.assertIn("bytesBase64Encoded", body["instances"][0]["image"])
        self.assertEqual(body["parameters"], {
            "sampleCount": 1, "durationSeconds": 8, "aspectRatio": "9:16", "resolution": "720p"})

    def test_image_request_uses_full_prompt_and_records_actual_usage(self):
        image = io.BytesIO()
        Image.new("RGB", (300, 100), "orange").save(image, format="PNG")
        client = Mock()
        client.models.generate_content.return_value = types.GenerateContentResponse(
            candidates=[types.Candidate(content=types.Content(parts=[
                types.Part(inline_data=types.Blob(data=image.getvalue(), mime_type="image/png"))]))],
            usage_metadata=types.GenerateContentResponseUsageMetadata(total_token_count=321))
        record = {}
        prompt = preview.load_episode()["scenes"][0]["full_image_prompt"]
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "scene.png"
            preview.make_keyframe(client, "image-model", prompt, path, record)
            with Image.open(path) as actual:
                self.assertEqual(actual.size, (720, 1280))
        self.assertEqual(client.models.generate_content.call_args.kwargs["contents"], prompt)
        self.assertEqual((record["image_used"], record["total_tokens"]), (True, 321))

    def test_missing_image_stops_without_fallback(self):
        client = Mock()
        client.models.generate_content.return_value = types.GenerateContentResponse()
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "scene.png"
            with self.assertRaisesRegex(RuntimeError, "no image"):
                preview.make_keyframe(client, "model", "prompt", path, {})
            self.assertFalse(path.exists())
        self.assertEqual(client.models.generate_content.call_count, 1)

    def test_reference_image_bytes_are_sent_to_developer_generate_content(self):
        returned = io.BytesIO()
        Image.new("RGB", (100, 200), "orange").save(returned, format="PNG")
        requests = []

        def transport(request):
            requests.append(request)
            return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"inlineData": {
                "data": base64.b64encode(returned.getvalue()).decode(), "mimeType": "image/png"}}]}}],
                "usageMetadata": {"promptTokenCount": 1800, "candidatesTokenCount": 1200, "totalTokenCount": 3000}})

        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            reference = directory / "reference.jpg"
            Image.new("RGB", (64, 128), "green").save(reference)
            reference_bytes = reference.read_bytes()
            with genai.Client(api_key="test-only", vertexai=False, http_options=types.HttpOptions(
                    httpx_client=httpx.Client(transport=httpx.MockTransport(transport)))) as client:
                record = {}
                preview.make_keyframe(client, "image-model", "Preserve the reference outfit", directory / "scene.png",
                                      record, image_size=(1080, 1920), reference_image=reference)
            with Image.open(directory / "scene.png") as actual:
                self.assertEqual(actual.size, (1080, 1920))
        self.assertEqual(len(requests), 1)
        self.assertTrue(requests[0].url.path.endswith(":generateContent"))
        body = json.loads(requests[0].content)
        parts = body["contents"][0]["parts"]
        self.assertEqual(parts[0]["text"], "Preserve the reference outfit")
        blob = parts[1]["inlineData"]
        self.assertEqual(blob.get("mimeType") or blob.get("mime_type"), "image/jpeg")
        self.assertEqual(base64.urlsafe_b64decode(parts[1]["inlineData"]["data"]), reference_bytes)
        self.assertEqual(record["input_tokens"], 1800)
        self.assertEqual(record["total_tokens"], 3000)

    def test_invalid_reference_never_falls_back_to_text_only_generation(self):
        client = Mock()
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            invalid = directory / "invalid.png"
            invalid.write_bytes(b"not an image")
            for reference in (directory / "missing.png", invalid):
                with self.assertRaises((FileNotFoundError, OSError)):
                    preview.make_keyframe(client, "model", "prompt", directory / "out.png", {}, reference_image=reference)
                with self.assertRaises((FileNotFoundError, OSError)):
                    preview.make_keyframe(client, "model", "prompt", directory / "out.png", {},
                                          reference_images=[reference])
        client.models.generate_content.assert_not_called()

    def test_all_three_reference_images_reach_sdk_in_order(self):
        returned = io.BytesIO()
        Image.new("RGB", (90, 160), "gray").save(returned, format="PNG")
        sent = []

        def transport(request):
            sent.append(json.loads(request.content))
            return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"inlineData": {
                "data": base64.b64encode(returned.getvalue()).decode(), "mimeType": "image/png"}}]}}]})

        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            references = []
            for name, color in (("portrait", "red"), ("body", "green"), ("wardrobe", "blue")):
                path = directory / f"{name}.png"
                Image.new("RGB", (64, 128), color).save(path)
                references.append(path)
            with genai.Client(api_key="test-only", vertexai=False, http_options=types.HttpOptions(
                    httpx_client=httpx.Client(transport=httpx.MockTransport(transport)))) as client:
                preview.make_keyframe(client, "image-model", "Identity then wardrobe", directory / "out.png", {},
                                      reference_images=references)
            self.assertEqual(len(sent), 1)
            parts = sent[0]["contents"][0]["parts"]
            self.assertEqual(parts[0]["text"], "Identity then wardrobe")
            self.assertEqual([base64.urlsafe_b64decode(p["inlineData"]["data"]) for p in parts[1:]],
                             [path.read_bytes() for path in references])
            with self.assertRaises((FileNotFoundError, OSError)):
                preview.make_keyframe(client, "image-model", "No fallback", directory / "bad.png", {},
                                      reference_images=[references[0], directory / "missing.png"])
            self.assertEqual(len(sent), 1)

    def test_filtered_first_scene_stops_before_other_images_and_preserves_diagnostics(self):
        client = Mock()
        client.models.list.return_value = [types.Model(
            name="models/veo-3.0-fast-generate-001", supported_actions=["predictLongRunning"])]
        client.models.generate_videos.return_value = operation(
            done=True, response=types.GenerateVideosResponse(
                rai_media_filtered_count=1, rai_media_filtered_reasons=["Input not supported"]))
        with tempfile.TemporaryDirectory() as temp, \
                patch.object(preview, "make_keyframe") as image, \
                patch.object(preview.types.Image, "from_file", return_value=types.Image(image_bytes=b"test")), \
                patch.object(preview.factory, "generate_speech_audio", new_callable=AsyncMock) as speech, \
                patch.object(preview.factory.requests, "post", side_effect=AssertionError):
            with self.assertRaisesRegex(RuntimeError, "Input not supported"):
                preview.run_preview(client, temp)
            state = json.loads((Path(temp) / "metadata.json").read_text())
            self.assertFalse((Path(temp) / "EP01_animation_preview.mp4").exists())
        self.assertEqual(image.call_count, 1)
        self.assertEqual(client.models.generate_videos.call_count, 1)
        client.files.download.assert_not_called()
        speech.assert_not_called()
        self.assertEqual(state["status"], "failed")
        self.assertEqual(state["video_model"], "veo-3.0-fast-generate-001")
        self.assertEqual(len(state["video_requests"]), 1)
        self.assertIn("operation_name", state["video_requests"][0])

    def test_operation_timeout_does_not_submit_again(self):
        client = Mock()
        client.models.generate_videos.return_value = operation(done=False)
        client.operations.get.return_value = operation(done=False)
        record = {}
        with patch.object(preview.types.Image, "from_file", return_value=types.Image(image_bytes=b"test")):
            with self.assertRaisesRegex(TimeoutError, "operation ID saved"):
                preview.generate_clip(client, "model", "prompt", Path("input.png"), Path("out.mp4"),
                                      record, Mock(), deadline=1,
                                      clock=Mock(side_effect=[0, 0, 2]), sleep=Mock())
        self.assertEqual(client.models.generate_videos.call_count, 1)
        self.assertEqual(record["operation_name"], "models/test/operations/preview")

    def test_completed_operation_downloads_video_uri(self):
        client = Mock()
        client.models.generate_videos.return_value = operation(done=False)
        client.operations.get.return_value = operation(done=True, response=types.GenerateVideosResponse(
            generated_videos=[types.GeneratedVideo(video=types.Video(uri="https://example.test/clip"))]))
        client.files.download.side_effect = lambda **kw: Path(kw["destination"]).write_bytes(b"mp4")
        with tempfile.TemporaryDirectory() as temp, \
                patch.object(preview.types.Image, "from_file", return_value=types.Image(image_bytes=b"test")), \
                patch.object(preview, "probe", return_value={
                    "streams": [{"codec_type": "video"}], "format": {"duration": "8"}}):
            record = {}
            preview.generate_clip(client, "model", "prompt", Path("input.png"), Path(temp) / "out.mp4",
                                  record, Mock(), deadline=float("inf"), sleep=Mock())
        self.assertEqual(record["status"], "downloaded")
        self.assertEqual(client.files.download.call_count, 1)

    def test_existing_attempt_directory_prevents_paid_regeneration(self):
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp) / "metadata.json").write_text("{}")
            client = Mock()
            with self.assertRaisesRegex(ValueError, "empty"):
                preview.run_preview(client, temp)
            client.models.generate_content.assert_not_called()
            client.models.generate_videos.assert_not_called()

    def test_safe_error_redacts_api_credentials(self):
        with patch.dict(preview.os.environ, {"GEMINI_API_KEY": "private-value"}):
            message = preview.safe_error(RuntimeError("private-value https://host.test/path?key=other-value&x=1"))
        self.assertNotIn("private-value", message)
        self.assertNotIn("other-value", message)


class ModelDiscoveryTests(unittest.TestCase):
    def client(self, *models):
        client = Mock()
        client.models.list.return_value = [types.Model(name=name, supported_actions=actions)
                                           for name, actions in models]
        return client

    def test_only_a_listed_supported_model_is_selected(self):
        client = self.client(
            ("models/gemini-2.5-flash", ["generateContent"]),
            ("models/veo-3.1-generate-preview", ["predictLongRunning"]),
            ("models/veo-3.0-fast-generate-001", ["predictLongRunning"]))
        report = {}
        selected = preview.select_video_model(client, report=report)
        self.assertEqual(selected, "veo-3.0-fast-generate-001")
        self.assertEqual(report["selected_model"], selected)
        self.assertEqual(len(report["visible_veo_models"]), 2)
        client.models.generate_content.assert_not_called()
        client.models.generate_videos.assert_not_called()

    def test_only_regular_model_does_not_automatically_raise_spending(self):
        client = self.client(("models/veo-3.1-generate-preview", ["predictLongRunning"]))
        with self.assertRaisesRegex(RuntimeError, "GEMINI_VIDEO_MODEL"):
            preview.select_video_model(client)

    def test_explicit_listed_model_can_be_selected(self):
        client = self.client(("models/veo-3.1-generate-preview", ["predictLongRunning"]))
        selected = preview.select_video_model(client, "models/veo-3.1-generate-preview")
        self.assertEqual(selected, "veo-3.1-generate-preview")

    def test_video_name_without_video_action_is_rejected(self):
        client = self.client(("models/veo-3.1-fast-generate-001", ["generateContent"]))
        with self.assertRaisesRegex(RuntimeError, "產圖前停止"):
            preview.select_video_model(client)

    def test_missing_or_unlisted_override_stops_before_paid_requests(self):
        for requested in (None, "veo-3.1-fast-generate-preview"):
            with self.subTest(requested=requested), tempfile.TemporaryDirectory() as temp:
                client = self.client(("models/gemini-2.5-flash-image", ["generateContent"]))
                with self.assertRaisesRegex(RuntimeError, "產圖前停止"):
                    preview.run_preview(client, temp, video_model=requested)
                client.models.generate_content.assert_not_called()
                client.models.generate_videos.assert_not_called()
                state = json.loads((Path(temp) / "metadata.json").read_text())
                self.assertEqual((state["status"], state["stage"]), ("failed", "model_discovery"))
                self.assertEqual(state["model_discovery"]["visible_veo_models"], [])
                self.assertEqual(state["image_requests"], [])
                self.assertEqual(state["video_requests"], [])

    def test_listing_error_is_saved_and_stops_before_paid_requests(self):
        client = Mock()
        client.models.list.side_effect = RuntimeError("ListModels permission denied")
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(RuntimeError, "permission denied"):
                preview.run_preview(client, temp)
            state = json.loads((Path(temp) / "metadata.json").read_text())
            self.assertIn("permission denied", state["error"])
        client.models.generate_content.assert_not_called()
        client.models.generate_videos.assert_not_called()

    def test_sdk_pagination_reads_later_page_and_converts_supported_methods(self):
        urls = []

        def transport(request):
            urls.append(request.url)
            self.assertEqual(request.method, "GET")
            if request.url.params.get("pageToken") == "page-two":
                return httpx.Response(200, json={"models": [{
                    "name": "models/veo-3.1-lite-generate-preview",
                    "supportedGenerationMethods": ["predictLongRunning"]}]})
            return httpx.Response(200, json={"models": [{"name": "models/gemini-2.5-flash"}],
                                            "nextPageToken": "page-two"})

        with genai.Client(api_key="test-only", vertexai=False, http_options=types.HttpOptions(
                httpx_client=httpx.Client(transport=httpx.MockTransport(transport)))) as client:
            self.assertEqual(preview.select_video_model(client), "veo-3.1-lite-generate-preview")
        self.assertEqual(len(urls), 2)
        self.assertTrue(all(url.path.endswith("/models") for url in urls))


class ModelCatalogTests(unittest.TestCase):
    def client(self):
        client = Mock()
        client.models.list.return_value = [
            types.Model(name="models/gemini-test", display_name="Gemini Test",
                        supported_actions=["generateContent", "countTokens"]),
            types.Model(name="models/embedding-test", supported_actions=["embedContent"]),
            types.Model(name="models/other-model")]
        return client

    def test_full_catalog_includes_non_video_models_and_raw_supported_methods(self):
        client = self.client()
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            report = preview.export_model_catalog(client, directory, directory / "summary.md")
            stored = json.loads((directory / "models.json").read_text())
            self.assertEqual(stored, report)
            self.assertEqual(report["model_count"], 3)
            self.assertEqual(report["models"][0]["supported_actions"], ["generateContent", "countTokens"])
            self.assertEqual(report["models"][2]["supported_actions"], [])
            self.assertEqual((directory / "models.md").read_text(), (directory / "summary.md").read_text())
            self.assertEqual(report["image_generation_requests"], 0)
            self.assertEqual(report["video_generation_requests"], 0)
        client.models.generate_content.assert_not_called()
        client.models.generate_videos.assert_not_called()

    def test_cli_list_mode_never_calls_preview_or_live_sheet(self):
        client = self.client()
        with tempfile.TemporaryDirectory() as temp, \
                patch.object(preview, "ROOT", Path(temp)), \
                patch.object(preview.genai, "Client", return_value=client), \
                patch.object(preview.sys, "argv", ["preview_ep01.py", "--list-models"]), \
                patch.dict(preview.os.environ, {"GEMINI_API_KEY": "secret-test-only", "GITHUB_STEP_SUMMARY": "",
                                               "GITHUB_ACTIONS": ""}), \
                patch.object(preview, "run_preview", side_effect=AssertionError), \
                patch.object(preview.factory.requests, "get", side_effect=AssertionError), \
                patch.object(preview.factory.requests, "post", side_effect=AssertionError):
            self.assertEqual(preview.main(), 0)
            content = (Path(temp) / "output/gemini-models/models.json").read_text()
            self.assertNotIn("secret-test-only", content)
            self.assertFalse((Path(temp) / "output/ep01-preview").exists())
        client.models.generate_content.assert_not_called()
        client.models.generate_videos.assert_not_called()
        client.close.assert_called_once()

    def test_notice_keeps_all_model_ids_and_escapes_workflow_commands(self):
        names = [f"models/test-{i}" for i in range(28)] + ["models/test\n::error::unexpected%"]
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            preview.emit_model_notices({"models": [{"name": name} for name in names]})
        lines = output.getvalue().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertTrue(all(line.startswith("::notice title=Gemini API model IDs") for line in lines))
        self.assertIn("models/test-27", output.getvalue())
        self.assertIn("%0A::error::unexpected%25", output.getvalue())

    def test_failed_catalog_exports_redacted_error_without_generation(self):
        client = self.client()
        client.models.list.side_effect = RuntimeError("lookup failed with secret-test-only")
        with tempfile.TemporaryDirectory() as temp, \
                patch.dict(preview.os.environ, {"GEMINI_API_KEY": "secret-test-only"}):
            with self.assertRaisesRegex(RuntimeError, "lookup failed"):
                preview.export_model_catalog(client, temp)
            content = (Path(temp) / "models.json").read_text()
            self.assertEqual(json.loads(content)["status"], "failed")
            self.assertNotIn("secret-test-only", content)
        client.models.generate_content.assert_not_called()
        client.models.generate_videos.assert_not_called()


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
class RenderIntegrationTests(unittest.TestCase):
    def test_motion_clips_retimed_with_complete_audio_and_portrait_output(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            clips, audios = [], []
            for index, duration in enumerate((0.5, 1.1), 1):
                clip, audio = directory / f"clip{index}.mp4", directory / f"audio{index}.wav"
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                                "testsrc2=size=160x90:rate=24", "-t", "0.8", "-c:v", "libx264", str(clip)], check=True)
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                                "sine=frequency=440:sample_rate=48000", "-t", str(duration), str(audio)], check=True)
                clips.append(clip)
                audios.append(audio)
            scenes = [{"narration": "Mia meets Mochi."}, {"narration": "Titan gently offers his warm paw."}]
            final, timings = preview.render_preview(directory, scenes, clips, audios)
            info = preview.probe(final)
            video = next(s for s in info["streams"] if s["codec_type"] == "video")
            self.assertEqual((video["width"], video["height"], video["r_frame_rate"]), (720, 1280, "24/1"))
            self.assertTrue(any(s["codec_type"] == "audio" for s in info["streams"]))
            self.assertLess(abs(float(info["format"]["duration"]) - 1.6), 0.15)
            self.assertLess(timings[0]["video_time_scale"], 1)
            self.assertGreater(timings[1]["video_time_scale"], 1)
            subtitles = (directory / "scene_2.srt").read_text()
            for word in scenes[1]["narration"].split():
                self.assertIn(word, subtitles)


if __name__ == "__main__":
    unittest.main()
