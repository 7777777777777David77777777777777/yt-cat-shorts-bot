import contextlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch
import wave

from PIL import Image

import main
import upload_youtube
from test_sheet_mapping import HEADERS, ROW, sheet_csv, webhook_episode


HEADERS_SIX = HEADERS[:15] + [
    '第 5 幕：英文台詞 (Scene 5 Narration)', '第 5 幕：畫面動作 (Scene 5 Action)',
    '第 6 幕：英文台詞 (Scene 6 Loop Narration)', '第 6 幕：畫面動作 (Scene 6 Action)',
] + HEADERS[15:]
ROW_SIX = ROW[:15] + [
    'The friends walk home.', 'Scene 5: Mia walks home with Mochi and Titan.',
    'Their new adventure begins.', 'Scene 6: All three open the garden gate.',
] + ROW[15:]


def six_episode():
    return dict(webhook_episode(), s5_narration=ROW_SIX[15], s5_action=ROW_SIX[16],
                s6_narration=ROW_SIX[17], s6_action=ROW_SIX[18])


class SixSceneTests(unittest.TestCase):
    def test_six_scene_csv_preserves_all_pairs_title_tags_and_progress(self):
        episode = main.episode_from_sheet_csv(sheet_csv([ROW_SIX], HEADERS_SIX))
        self.assertEqual(episode['scene_count'], 6)
        self.assertEqual(episode['row_index'], 8)
        self.assertEqual((episode['sent_count'], episode['target_sends']), (1, 6))
        for i, scene in enumerate(episode['scenes']):
            self.assertEqual(scene['narration'], ROW_SIX[7 + i * 2])
            self.assertEqual(scene['scene_action'], ROW_SIX[8 + i * 2])
            self.assertIn(episode['selected_visual_style'], scene['full_image_prompt'])
        self.assertTrue(episode['title'].startswith(ROW_SIX[19]))
        self.assertEqual(episode['tags'], ['kitten', 'husky', 'friendship'])

    def test_six_scene_columns_can_be_reordered(self):
        order = list(reversed(range(22)))
        episode = main.episode_from_sheet_csv(sheet_csv(
            [[ROW_SIX[i] for i in order]], [HEADERS_SIX[i] for i in order]))
        self.assertEqual(episode['scenes'][-1]['scene_action'], ROW_SIX[18])
        self.assertTrue(episode['title'].startswith(ROW_SIX[19]))

    def test_extra_unrelated_columns_do_not_turn_old_layout_into_six_scenes(self):
        episode = main.episode_from_sheet_csv(sheet_csv(
            [ROW + ['extra'] * 6], HEADERS + [f'備註{i}' for i in range(6)]))
        self.assertEqual(episode['scene_count'], 4)
        self.assertTrue(episode['title'].startswith(ROW[15]))

    def test_blank_extension_keeps_existing_four_scenes_in_new_layout(self):
        row = ROW_SIX.copy()
        row[15:19] = [''] * 4
        episode = main.episode_from_sheet_csv(sheet_csv([row], HEADERS_SIX))
        self.assertEqual(episode['scene_count'], 4)
        self.assertTrue(episode['title'].startswith(ROW_SIX[19]))

    def test_five_scene_script_is_valid(self):
        episode = main.parse_episode_from_row(dict(six_episode(), s6_narration='', s6_action=''))
        self.assertEqual(episode['scene_count'], 5)

    def test_half_filled_scenes_and_gaps_stop_instead_of_silently_dropping_content(self):
        for changes in [dict(s5_narration=''), dict(s5_action=None), dict(s6_narration=''),
                        dict(s6_action=None), dict(s5_narration='', s5_action='')]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                main.parse_episode_from_row(dict(six_episode(), **changes))

    def test_missing_or_duplicate_optional_headers_are_rejected(self):
        for index, value in [(16, '其他欄'), (17, HEADERS_SIX[15])]:
            headers = HEADERS_SIX.copy()
            headers[index] = value
            with self.subTest(index=index), self.assertRaises(ValueError):
                main.episode_from_sheet_csv(sheet_csv([ROW_SIX], headers))

    def test_scene_six_without_scene_five_headers_is_rejected(self):
        headers = HEADERS_SIX[:15] + HEADERS_SIX[17:]
        row = ROW_SIX[:15] + ROW_SIX[17:]
        with self.assertRaises(ValueError):
            main.episode_from_sheet_csv(sheet_csv([row], headers))

    def test_shifted_late_narrations_are_rejected(self):
        for field in ('s5_narration', 's6_narration'):
            with self.subTest(field=field), self.assertRaises(ValueError):
                main.parse_episode_from_row(dict(six_episode(), **{field: 'Scene 5: Action, not narration'}))

    def test_user_webhook_with_genre_dna_can_supply_all_six_scenes(self):
        data = six_episode()
        data['genre_dna'] = data.pop('art_dna')
        response = Mock()
        response.json.return_value = {'status': 'ok', 'episode': data}
        with patch.dict(main.os.environ, {'SHEET_WEBHOOK_URL': 'https://example.test/exec'}), \
                patch.object(main.requests, 'get', side_effect=[main.requests.ConnectionError(), response]):
            episode = main.fetch_next_episode_from_google_sheet()
        self.assertEqual(episode['scene_count'], 6)
        self.assertEqual(episode['scenes'][-1]['narration'], ROW_SIX[17])

    def test_pipeline_generates_six_pairs_and_saves_all_usage_without_network(self):
        story = main.parse_episode_from_row(six_episode())

        def download(prompt, path, master_seed, scene_idx, usage_records):
            record = main.start_image_request(usage_records, 'google', 'test-image', scene_idx)
            record.update(total_tokens=1000, image_used=True)

        with tempfile.TemporaryDirectory() as directory:
            scenes = Path(directory) / 'scenes'
            scenes.mkdir()
            with patch.object(main, 'OUTPUT_DIR', directory), patch.object(main, 'SCENE_DIR', str(scenes)), \
                    patch.object(main, 'fetch_next_episode_from_google_sheet', return_value=story), \
                    patch.object(main, 'generate_speech_audio', new_callable=AsyncMock) as speech, \
                    patch.object(main, 'download_ai_keyframe', side_effect=download) as image, \
                    patch.object(main, 'render_continuous_smooth_short') as render:
                main.main()
            metadata = json.loads((Path(directory) / 'metadata.json').read_text())
        self.assertEqual(speech.call_count, 6)
        self.assertEqual(image.call_count, 6)
        self.assertEqual([call.args[0] for call in speech.call_args_list],
                         [scene['narration'] for scene in story['scenes']])
        self.assertEqual(len(render.call_args.kwargs['raw_imgs']), 6)
        self.assertEqual(len(render.call_args.kwargs['audio_paths']), 6)
        self.assertEqual(metadata['scene_count'], 6)
        self.assertEqual(metadata['image_usage']['images_used'], 6)
        self.assertEqual(metadata['image_usage']['total_tokens'], 6000)

    def test_upload_acknowledgement_reports_v_column(self):
        response = Mock()
        response.json.return_value = {'status': 'updated', 'script_version': 'six-scenes-usage-v3', 'url_column': 22}
        with patch.dict(main.os.environ, {'SHEET_WEBHOOK_URL': 'https://example.test/exec'}), \
                patch.object(upload_youtube.requests, 'post', return_value=response), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            upload_youtube.report_back_to_google_sheet({'id': 'EP01'}, 'https://youtube.com/shorts/testVideo01')
        self.assertIn('V 欄（22）', output.getvalue())
        self.assertNotIn('未確認', output.getvalue())

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
    def test_real_encoder_includes_the_sixth_scene_and_all_audio(self):
        # 短測試素材驗證六幕時間軸與實際 MP4，不呼叫產圖、配音或 YouTube API。
        story = main.parse_episode_from_row(six_episode())
        with tempfile.TemporaryDirectory() as directory:
            images, audio = [], []
            colors = [(30 * i, 30, 200) for i in range(1, 7)]
            for i, color in enumerate(colors, 1):
                image = str(Path(directory) / f'{i}.png')
                sound = str(Path(directory) / f'{i}.wav')
                Image.new('RGB', (1080, 1920), color).save(image)
                with wave.open(sound, 'wb') as wav:
                    wav.setparams((1, 2, 44100, 0, 'NONE', 'not compressed'))
                    wav.writeframes(b'\x00\x00' * 8820)
                images.append(image)
                audio.append(sound)
            output = str(Path(directory) / 'six.mp4')
            with patch.object(main, 'SCENE_DIR', directory), \
                    patch.object(main, 'get_audio_duration', return_value=0.2):
                main.render_continuous_smooth_short(images, audio, story['scenes'], output)
            info = json.loads(subprocess.check_output([
                'ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', output]))
            video = next(s for s in info['streams'] if s['codec_type'] == 'video')
            self.assertEqual((video['width'], video['height']), (1080, 1920))
            self.assertEqual(int(video['nb_frames']), 36)
            self.assertAlmostEqual(float(info['format']['duration']), 1.2, delta=0.06)
            self.assertTrue(any(s['codec_type'] == 'audio' for s in info['streams']))
            pixel = subprocess.check_output([
                'ffmpeg', '-v', 'error', '-ss', '1.1', '-i', output, '-frames:v', '1',
                '-vf', 'crop=2:2:540:960,scale=1:1', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'])
            self.assertEqual(len(pixel), 3)
            self.assertTrue(all(abs(a - b) < 12 for a, b in zip(pixel, colors[-1])),
                            f'Last scene pixel {tuple(pixel)} differs from sixth image {colors[-1]}')


if __name__ == '__main__':
    unittest.main()
