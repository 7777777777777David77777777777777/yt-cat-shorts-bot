import contextlib
import base64
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main
import upload_youtube
from test_sheet_mapping import webhook_episode
from PIL import Image
from google import genai
from google.genai import types
import httpx


class UsageReportingTests(unittest.TestCase):
    def record(self, total=None, used=True, provider='google'):
        record = main.start_image_request([], provider, 'test-image-model', 1)
        record.update(total_tokens=total, image_used=used)
        return record

    def test_sdk_usage_metadata_is_read_without_recalculating_total(self):
        record = self.record()
        response = types.GenerateContentResponse(usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=100, candidates_token_count=900, thoughts_token_count=50, total_token_count=1050))
        main.capture_token_usage(record, response)
        self.assertEqual((record['input_tokens'], record['output_tokens'], record['total_tokens']), (100, 900, 1050))

    def test_json_camel_case_metadata_is_supported(self):
        record = self.record()
        main.capture_token_usage(record, {'usageMetadata': {'promptTokenCount': 10, 'candidatesTokenCount': 20, 'totalTokenCount': 30}})
        self.assertEqual(record['total_tokens'], 30)

    def test_unreported_usage_is_not_zero_or_guessed_from_prompt(self):
        for response in [types.GenerateContentResponse(), {}, {'usage_metadata': {'total_token_count': -1}},
                         {'usage_metadata': {'total_token_count': True}}, {'usage_metadata': {'total_token_count': '100'}}]:
            record = self.record()
            main.capture_token_usage(record, response)
            usage = main.summarize_image_usage([record])
            self.assertIsNone(usage['total_tokens'])
            self.assertFalse(usage['token_usage_complete'])
            self.assertIn('未提供', upload_youtube.format_image_usage({'image_usage': usage}))

    def test_input_and_output_without_total_are_not_claimed_as_total(self):
        record = self.record()
        main.capture_token_usage(record, {'usage_metadata': {'prompt_token_count': 100, 'candidates_token_count': 900}})
        self.assertIsNone(record['total_tokens'])

    def test_four_calls_are_summed_for_one_video(self):
        usage = main.summarize_image_usage([self.record(1000) for _ in range(4)])
        self.assertEqual((usage['api_requests'], usage['images_used'], usage['total_tokens']), (4, 4, 4000))
        self.assertIn('產圖 token：4,000', upload_youtube.format_image_usage({'image_usage': usage}))

    def test_explicit_api_zero_is_distinguished_from_unknown(self):
        usage = main.summarize_image_usage([self.record(0)])
        self.assertTrue(usage['token_usage_complete'])
        self.assertIn('產圖 token：0', upload_youtube.format_image_usage({'image_usage': usage}))

    def test_failed_or_fallback_calls_make_total_partial(self):
        usage = main.summarize_image_usage([self.record(100, used=False), self.record(provider='pollinations')])
        self.assertIsNone(usage['total_tokens'])
        self.assertEqual(usage['reported_total_tokens'], 100)
        self.assertEqual(usage['api_requests'], 2)
        text = upload_youtube.format_image_usage({'image_usage': usage})
        self.assertIn('已回報產圖 token：100', text)
        self.assertIn('另 1 次請求未提供', text)

    def test_google_content_image_response_and_usage_are_recorded(self):
        image_data = io.BytesIO()
        Image.effect_noise((256, 256), 70).convert('RGB').save(image_data, format='PNG')
        response = types.GenerateContentResponse(
            model_version='test-served-image-version',
            candidates=[types.Candidate(content=types.Content(parts=[
                types.Part(inline_data=types.Blob(data=image_data.getvalue(), mime_type='image/png'))]))],
            usage_metadata=types.GenerateContentResponseUsageMetadata(
                prompt_token_count=100, candidates_token_count=900, total_token_count=1000))
        client = Mock()
        client.models.generate_content.return_value = response
        records = []
        with tempfile.TemporaryDirectory() as directory, \
                patch.dict(main.os.environ, {'HF_TOKEN': '', 'GEMINI_API_KEY': 'mock-only', 'GEMINI_IMAGE_MODEL': 'test-image-model'}), \
                patch.object(genai, 'Client', return_value=client) as constructor, \
                patch.object(main.requests, 'get') as get:
            path = str(Path(directory) / 'image.jpg')
            main.download_ai_keyframe('Complete scene prompt', path, 1234, 1, usage_records=records)
            self.assertTrue(Path(path).exists())
        constructor.assert_called_once_with(api_key='mock-only', vertexai=False)
        client.models.generate_images.assert_not_called()
        self.assertEqual(client.models.generate_content.call_args.kwargs['model'], 'test-image-model')
        self.assertEqual(records[0]['total_tokens'], 1000)
        self.assertTrue(records[0]['image_used'])
        self.assertEqual(main.summarize_image_usage(records)['models_used'], ['test-served-image-version'])
        get.assert_not_called()

    def test_google_failure_and_pollinations_retries_are_all_counted(self):
        image_data = io.BytesIO()
        Image.effect_noise((256, 256), 70).convert('RGB').save(image_data, format='PNG')
        client = Mock()
        client.models.generate_content.side_effect = RuntimeError('simulated API failure')
        records = []
        with tempfile.TemporaryDirectory() as directory, \
                patch.dict(main.os.environ, {'HF_TOKEN': '', 'GEMINI_API_KEY': 'mock-only'}), \
                patch.object(genai, 'Client', return_value=client), \
                patch.object(main.time, 'sleep'), \
                patch.object(main.requests, 'get', side_effect=[Mock(status_code=503), Mock(status_code=200, content=image_data.getvalue())]):
            main.download_ai_keyframe('Prompt', str(Path(directory) / 'image.jpg'), 1234, 1, usage_records=records)
        usage = main.summarize_image_usage(records)
        self.assertEqual(usage['api_requests'], 3)
        self.assertEqual(usage['images_used'], 1)
        self.assertEqual(usage['models_used'], ['flux'])
        self.assertEqual(usage['requests_without_token_usage'], 3)

    def test_real_sdk_uses_developer_generate_content_route_without_network(self):
        image_data = io.BytesIO()
        Image.effect_noise((256, 256), 70).convert('RGB').save(image_data, format='PNG')
        requests = []

        def handle(request):
            requests.append(request)
            self.assertTrue(request.url.path.endswith('/models/gemini-2.5-flash-image:generateContent'))
            body = json.loads(request.content)
            self.assertEqual(body['contents'][0]['parts'][0]['text'], 'Full image prompt')
            self.assertEqual(body['generationConfig']['imageConfig']['aspectRatio'], '9:16')
            self.assertEqual(body['generationConfig']['responseModalities'], ['IMAGE'])
            return httpx.Response(200, json={
                'candidates': [{'content': {'parts': [{'inlineData': {
                    'mimeType': 'image/png', 'data': base64.b64encode(image_data.getvalue()).decode(),
                }}]}}],
                'usageMetadata': {'promptTokenCount': 100, 'candidatesTokenCount': 900, 'totalTokenCount': 1000},
                'modelVersion': 'gemini-2.5-flash-image',
            })

        with httpx.Client(transport=httpx.MockTransport(handle)) as http:
            real_client = genai.Client(api_key='mock-only', vertexai=False,
                                       http_options=types.HttpOptions(httpx_client=http))
            records = []
            with tempfile.TemporaryDirectory() as directory, \
                    patch.dict(main.os.environ, {'HF_TOKEN': '', 'GEMINI_API_KEY': 'mock-only', 'GEMINI_IMAGE_MODEL': ''}), \
                    patch.object(genai, 'Client', return_value=real_client), \
                    patch.object(main.requests, 'get') as fallback:
                main.download_ai_keyframe('Full image prompt', str(Path(directory) / 'image.jpg'), 1234, 1, records)
            real_client.close()
        self.assertEqual(len(requests), 1)
        self.assertEqual(main.summarize_image_usage(records)['total_tokens'], 1000)
        fallback.assert_not_called()

    def test_metadata_survives_between_render_and_upload_processes(self):
        story = main.parse_episode_from_row(webhook_episode())

        def fake_download(prompt, path, master_seed, scene_idx, usage_records):
            record = main.start_image_request(usage_records, 'google', 'test-image-model', scene_idx)
            record.update(total_tokens=1000, image_used=True)

        with tempfile.TemporaryDirectory() as directory:
            scenes = Path(directory) / 'scenes'
            scenes.mkdir()
            with patch.object(main, 'OUTPUT_DIR', directory), patch.object(main, 'SCENE_DIR', str(scenes)), \
                    patch.object(main, 'fetch_next_episode_from_google_sheet', return_value=story), \
                    patch.object(main, 'generate_speech_audio', new_callable=AsyncMock), \
                    patch.object(main, 'download_ai_keyframe', side_effect=fake_download), \
                    patch.object(main, 'render_continuous_smooth_short'):
                main.main()
            metadata = json.loads((Path(directory) / 'metadata.json').read_text())
        usage = metadata['image_usage']
        self.assertEqual(usage['total_tokens'], 4000)
        response = Mock()
        response.json.return_value = {'status': 'updated'}
        with patch.dict(main.os.environ, {'SHEET_WEBHOOK_URL': 'https://example.test/exec'}), \
                patch.object(upload_youtube.requests, 'post', return_value=response) as post:
            upload_youtube.report_back_to_google_sheet(metadata, 'https://youtube.com/shorts/testVideo01')
        payload = post.call_args.kwargs['json']
        self.assertEqual(payload['youtube_url'], 'https://youtube.com/shorts/testVideo01')
        self.assertIn('產圖 token：4,000', payload['usage_summary'])
        self.assertEqual(payload['image_usage']['images_used'], 4)
        self.assertEqual(payload['new_sent_count'], 2)

    def test_older_metadata_without_usage_is_explicitly_unknown(self):
        self.assertEqual(upload_youtube.format_image_usage({}), '產圖 token：未提供')

    def test_http_200_without_updated_status_is_not_claimed_as_success(self):
        response = Mock()
        response.json.return_value = {'status': 'error', 'message': 'wrong row'}
        with patch.dict(main.os.environ, {'SHEET_WEBHOOK_URL': 'https://example.test/exec'}), \
                patch.object(upload_youtube.requests, 'post', return_value=response), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            upload_youtube.report_back_to_google_sheet({'id': 'EP01'}, 'https://youtube.com/shorts/testVideo01')
        self.assertIn('失敗', output.getvalue())
        self.assertNotIn('已同步回寫', output.getvalue())


if __name__ == '__main__':
    unittest.main()
