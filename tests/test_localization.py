import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import httpx
from google import genai
from google.genai import types
from google.genai import errors

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import upload_youtube as upload


ZH_TW = {"title": "Mochi 與大狗 Titan 成為好朋友", "description": "一段溫暖的友誼。\nEP01 #shorts"}


class LocalizationTests(unittest.TestCase):
    def test_developer_request_translates_both_fields_in_one_json_call(self):
        captured = []

        def transport(request):
            captured.append(request)
            return httpx.Response(200, json={
                "candidates": [{"content": {"role": "model", "parts": [{"text": json.dumps(ZH_TW)}]}}],
                "usageMetadata": {"promptTokenCount": 120, "candidatesTokenCount": 35, "totalTokenCount": 155}})

        client = genai.Client(api_key="mock-only", vertexai=False, http_options=types.HttpOptions(
            httpx_client=httpx.Client(transport=httpx.MockTransport(transport))))
        meta = {"title": "Mochi Meets Titan", "description": "A warm friendship.\nEP01 #shorts"}
        with patch.dict(os.environ, {"GEMINI_API_KEY": "mock-only", "GEMINI_TRANSLATION_MODEL": ""}), \
                patch.object(genai, "Client", return_value=client):
            translated, usage = upload.translate_zh_tw(meta)
        self.assertEqual(translated, ZH_TW)
        self.assertEqual(usage["total_token_count"], 155)
        self.assertEqual(len(captured), 1)
        self.assertTrue(captured[0].url.path.endswith("gemini-2.5-flash-lite:generateContent"))
        body = json.loads(captured[0].content)
        self.assertEqual(json.loads(body["contents"][0]["parts"][0]["text"]), meta)
        self.assertEqual(body["generationConfig"]["responseMimeType"], "application/json")
        self.assertIn("Taiwan", body["systemInstruction"]["parts"][0]["text"])

    def test_invalid_translations_are_rejected_before_upload(self):
        cases = [None, [], {}, dict(ZH_TW, title=""), dict(ZH_TW, title="貓" * 101),
                 dict(ZH_TW, title="標題\n第二行"), dict(ZH_TW, title="<標題>"),
                 dict(ZH_TW, description=""), dict(ZH_TW, description="貓" * 1667),
                 dict(ZH_TW, description="<不合法>")]
        for value in cases:
            with self.subTest(value_type=type(value).__name__):
                with self.assertRaises(ValueError):
                    upload.validate_zh_tw_translation(value)

    def test_missing_translation_key_never_calls_api(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}), patch.object(genai, "Client") as client:
            with self.assertRaisesRegex(RuntimeError, "缺少 GEMINI_API_KEY"):
                upload.translate_zh_tw({"title": "title", "description": "description"})
            client.assert_not_called()

    def test_provider_error_does_not_expose_credentials(self):
        client = Mock()
        client.__enter__ = Mock(return_value=client)
        client.__exit__ = Mock(return_value=False)
        client.models.generate_content.side_effect = RuntimeError("secret-test-key in provider message")
        with patch.dict(os.environ, {"GEMINI_API_KEY": "secret-test-key"}), \
                patch.object(genai, "Client", return_value=client):
            with self.assertRaises(RuntimeError) as result:
                upload.translate_zh_tw({"title": "title", "description": "description"})
        self.assertNotIn("secret-test-key", str(result.exception))

    def test_missing_usage_is_reported_without_guessing(self):
        text = upload.format_image_usage({"translation_usage": {"total_token_count": None}})
        self.assertIn("中文翻譯 token：未提供", text)
        text = upload.format_image_usage({"translation_usage": {"total_token_count": 155}})
        self.assertIn("產圖 token：未提供", text)
        self.assertIn("中文翻譯 token：155", text)

    def test_http_reason_is_preserved_without_exposing_keys(self):
        error = errors.ClientError(429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED",
            "message": "Quota exceeded for model. key=secret-test-key https://host.test/?key=other-secret"}})
        with patch.dict(os.environ, {"GEMINI_API_KEY": "secret-test-key"}):
            message = upload.safe_translation_error(error)
        self.assertIn("HTTP 429", message)
        self.assertIn("RESOURCE_EXHAUSTED", message)
        self.assertIn("Quota exceeded", message)
        self.assertNotIn("secret-test-key", message)
        self.assertNotIn("other-secret", message)

    def run_mock_upload(self, directory, translate, youtube, report):
        with contextlib.chdir(directory), \
                patch.dict(os.environ, {"YT_CLIENT_ID": "test", "YT_CLIENT_SECRET": "test", "YT_REFRESH_TOKEN": "test"}), \
                patch.object(upload, "build", return_value=youtube), \
                patch.object(upload, "MediaFileUpload"), \
                patch.object(upload, "translate_zh_tw", translate), \
                patch.object(upload, "report_back_to_google_sheet", report), \
                contextlib.redirect_stdout(io.StringIO()):
            upload.upload_short()

    def youtube(self):
        youtube = Mock()
        youtube.channels.return_value.list.return_value.execute.return_value = {
            "items": [{"id": upload.TARGET_CHANNEL_ID, "snippet": {"title": "test"}}]}
        youtube.videos.return_value.insert.return_value.execute.return_value = {"id": "test-only"}
        return youtube

    def test_localizations_saved_and_inserted_without_changing_english_source(self):
        source = {"id": "EP01", "title": "Mochi Meets Titan", "description": "English description", "sent_count": 0}
        usage = {"model": "test-model", "total_token_count": 155}
        translate = Mock(return_value=(ZH_TW, usage))
        youtube, report = self.youtube(), Mock()
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "output"
            output.mkdir()
            (output / "metadata.json").write_text(json.dumps(source))
            self.run_mock_upload(temp, translate, youtube, report)
            stored = json.loads((output / "metadata.json").read_text())
        request = youtube.videos.return_value.insert.call_args.kwargs
        self.assertEqual(request["part"], "snippet,status,localizations")
        self.assertEqual(request["body"]["localizations"]["zh-TW"], ZH_TW)
        snippet = request["body"]["snippet"]
        self.assertEqual((snippet["title"], snippet["description"]), (source["title"], source["description"]))
        self.assertEqual((snippet["defaultLanguage"], snippet["defaultAudioLanguage"]), ("en", "en-US"))
        self.assertEqual(stored["translation_usage"], usage)
        self.assertEqual(stored["localizations"]["zh-TW"], ZH_TW)
        report.assert_called_once_with(stored, "https://youtube.com/shorts/test-only")

    def test_failed_translation_never_uploads_or_updates_sheet(self):
        youtube, report = self.youtube(), Mock()
        translate = Mock(side_effect=RuntimeError("Translation unavailable"))
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "output"
            output.mkdir()
            (output / "metadata.json").write_text(json.dumps({"title": "title", "description": "description"}))
            with self.assertRaisesRegex(RuntimeError, "Translation unavailable"):
                self.run_mock_upload(temp, translate, youtube, report)
            saved = json.loads((output / "metadata.json").read_text())
            self.assertEqual(saved["translation_error"], "Translation unavailable")
        youtube.videos.assert_not_called()
        report.assert_not_called()


if __name__ == "__main__":
    unittest.main()
