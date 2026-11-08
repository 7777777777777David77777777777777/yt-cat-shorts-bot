import csv
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, unquote, urlsplit

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main


# 與使用者片單 A～R 欄順序相同，表頭在第 7 列，資料從第 8 列開始。
HEADERS = [
    "集數 ID", "發佈狀態", "已發送次數 (目標 6 次)",
    "視覺畫風 DNA (Art Style)", "角色 1 設定 (Character 1 DNA)",
    "角色 2 設定 (Character 2 DNA)", "角色 3 設定 (Character 3 DNA)",
    "第 1 幕：英文台詞 (Scene 1 Narration)", "第 1 幕：畫面動作 (Scene 1 Action)",
    "第 2 幕：英文台詞 (Scene 2 Narration)", "第 2 幕：畫面動作 (Scene 2 Action)",
    "第 3 幕：英文台詞 (Scene 3 Narration)", "第 3 幕：畫面動作 (Scene 3 Action)",
    "第 4 幕：英文台詞 (Scene 4 Loop Narration)", "第 4 幕：畫面動作 (Scene 4 Action)",
    "YouTube 爆款標題", "SEO 標籤 (Tags)", "已發佈 YouTube 網址紀錄",
]
ROW = [
    "EP01", "連發中 (Sending)", "1/6", "Warm 3D animation",
    "Character 1: Mia in a yellow raincoat", "Character 2: Mochi the orange kitten",
    "Character 3: Titan, a giant Siberian Husky",
    "Mia brings a kitten home.", "Scene 1: Mia holds Mochi near Titan.",
    "Titan offers his paw.", "Scene 2: Titan lies down.",
    "Mochi sleeps beside Titan.", "Scene 3: Mia covers them with a blanket.",
    "The three friends wear scarves.", "Scene 4: All three sit on the grass.",
    "A Kitten Finds a Family", "kitten, husky, friendship", "https://youtube.com/shorts/old",
]


def sheet_csv(rows=None, headers=None):
    output = io.StringIO()
    csv.writer(output).writerows([['Factory summary']] * 6 + [headers or HEADERS] + (rows if rows is not None else [ROW]))
    return output.getvalue()


def webhook_episode():
    data = {key: ROW[HEADERS.index(next(h for h in HEADERS if h.startswith(label)))]
            for key, label in main.SHEET_HEADERS.items()}
    data['row_index'] = 8
    return data


class SheetMappingTests(unittest.TestCase):
    def test_three_characters_do_not_shift_scenes_or_title(self):
        ep = main.episode_from_sheet_csv(sheet_csv())
        self.assertEqual(ep['row_index'], 8)
        self.assertEqual(ep['sent_count'], 1)
        for i, scene in enumerate(ep['scenes']):
            self.assertEqual(scene['narration'], ROW[7 + i * 2])
            self.assertEqual(scene['scene_action'], ROW[8 + i * 2])
            self.assertIn('Titan', scene['full_image_prompt'])
        self.assertTrue(ep['title'].startswith(ROW[15]))
        self.assertEqual(ep['tags'], ['kitten', 'husky', 'friendship'])

    def test_reordered_columns_and_extra_columns(self):
        order = list(reversed(range(18)))
        ep = main.episode_from_sheet_csv(sheet_csv(
            [[ROW[i] for i in order] + ['unused']],
            [HEADERS[i] for i in order] + ['新增備註欄']))
        self.assertEqual(ep['scenes'][0]['narration'], ROW[7])
        self.assertTrue(ep['title'].startswith(ROW[15]))

    def test_ep10_without_ep0_and_numeric_excel_counts(self):
        row = ROW.copy()
        row[0], row[2] = 'EP10', '2.0'
        ep = main.episode_from_sheet_csv(sheet_csv([row]))
        self.assertEqual((ep['id'], ep['sent_count']), ('EP10', 2))

    def test_completed_rows_are_skipped_preserving_row_index(self):
        for count, status in [('6/6', 'Sending'), ('1', '已完成 (Completed)'), ('1', 'completed')]:
            with self.subTest(count=count, status=status):
                done, pending = ROW.copy(), ROW.copy()
                done[1], done[2], pending[0] = status, count, 'EP02'
                ep = main.episode_from_sheet_csv(sheet_csv([done, pending]))
                self.assertEqual((ep['id'], ep['row_index']), ('EP02', 9))

    def test_no_pending_rows_do_not_fall_back_to_webhook(self):
        response = Mock(text=sheet_csv([]))
        with patch.object(main.requests, 'get', return_value=response) as get:
            with self.assertRaises(main.NoPendingEpisodes):
                main.fetch_next_episode_from_google_sheet()
            self.assertEqual(get.call_count, 1)

    def test_missing_or_duplicate_headers_are_rejected(self):
        for replacement in ['其他欄', HEADERS[5]]:
            headers = HEADERS.copy()
            headers[6] = replacement
            with self.subTest(replacement=replacement), self.assertRaises(ValueError):
                main.episode_from_sheet_csv(sheet_csv(headers=headers))

    def test_shifted_webhook_data_is_rejected(self):
        old = webhook_episode()
        old.pop('char3_dna')
        old['s1_narration'], old['title'] = ROW[6], ROW[14]
        with self.assertRaises(ValueError):
            main.parse_episode_from_row(old)
        # 即使提供 char3_dna，也不允許把角色設定或動作讀成台詞。
        for field, value in [('s1_narration', ROW[6]), ('s1_narration', ROW[8]), ('title', ROW[14])]:
            bad = webhook_episode()
            bad[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                main.parse_episode_from_row(bad)

    def test_invalid_counts_are_rejected(self):
        for count in ['oops', '-1', '1.5', '7/6']:
            row = ROW.copy()
            row[2] = count
            with self.subTest(count=count), self.assertRaises(ValueError):
                main.episode_from_sheet_csv(sheet_csv([row]))

    def test_urls_in_q_are_not_used_as_tags(self):
        row = ROW.copy()
        row[16] += '\n[1/6] https://youtube.com/shorts/old'
        ep = main.episode_from_sheet_csv(sheet_csv([row]))
        self.assertEqual(ep['tags'], ['kitten', 'husky', 'friendship'])

    def test_valid_webhook_can_be_used_when_csv_is_unavailable(self):
        response = Mock()
        response.json.return_value = {'status': 'ok', 'episode': webhook_episode()}
        with patch.dict(main.os.environ, {'SHEET_WEBHOOK_URL': 'https://example.test/exec'}), \
                patch.object(main.requests, 'get', side_effect=[main.requests.ConnectionError(), response]):
            ep = main.fetch_next_episode_from_google_sheet()
        self.assertEqual(ep['scenes'][0]['narration'], ROW[7])

    def test_unavailable_sources_stop_instead_of_using_default_ep01(self):
        with patch.dict(main.os.environ, {'SHEET_WEBHOOK_URL': ''}), \
                patch.object(main.requests, 'get', side_effect=main.requests.ConnectionError()):
            with self.assertRaises(RuntimeError):
                main.fetch_next_episode_from_google_sheet()

    def test_old_webhook_cannot_bypass_validation_when_csv_fails(self):
        old = webhook_episode()
        old['s1_narration'] = ROW[6]
        response = Mock()
        response.json.return_value = {'status': 'ok', 'episode': old}
        with patch.dict(main.os.environ, {'SHEET_WEBHOOK_URL': 'https://example.test/exec'}), \
                patch.object(main.requests, 'get', side_effect=[main.requests.ConnectionError(), response]):
            with self.assertRaises(RuntimeError):
                main.fetch_next_episode_from_google_sheet()


def legacy_webhook_episode():
    """舊 Apps Script 的 G～P 欄讀取位置，套用到已新增角色 3 的 Sheet。"""
    current = webhook_episode()
    return {
        'id': current['id'], 'status': current['status'],
        'sent_count': current['sent_count'], 'row_index': current['row_index'],
        'art_dna': current['art_dna'],
        'char1_dna': current['char1_dna'], 'char2_dna': current['char2_dna'],
        's1_narration': current['char3_dna'],
        's1_action': current['s1_narration'],
        's2_narration': current['s1_action'],
        's2_action': current['s2_narration'],
        's3_narration': current['s2_action'],
        's3_action': current['s3_narration'],
        's4_narration': current['s3_action'],
        's4_action': current['s4_narration'],
        'title': current['s4_action'], 'tags': current['title'],
    }


class LegacyWebhookTests(unittest.TestCase):
    def test_recognized_legacy_mapping_restores_all_fields_without_mutating_input(self):
        old = legacy_webhook_episode()
        original = old.copy()
        corrected = main.normalize_webhook_episode(old)
        expected = webhook_episode()
        expected['tags'] = ''  # 舊回應沒有 Q 欄，不能補造標籤。
        self.assertEqual(corrected, expected)
        self.assertEqual(old, original)
        ep = main.parse_episode_from_row(corrected)
        self.assertEqual(ep['scenes'][0]['narration'], ROW[7])
        self.assertTrue(ep['title'].startswith(ROW[15]))
        self.assertEqual(ep['tags'], [])

    def test_csv_failure_and_legacy_webhook_can_still_select_correct_episode(self):
        response = Mock()
        response.json.return_value = {'status': 'ok', 'episode': legacy_webhook_episode()}
        with patch.dict(main.os.environ, {'SHEET_WEBHOOK_URL': 'https://example.test/exec'}), \
                patch.object(main.requests, 'get', side_effect=[main.requests.ConnectionError(), response]):
            ep = main.fetch_next_episode_from_google_sheet()
        self.assertEqual(ep['row_index'], 8)
        self.assertEqual(ep['sent_count'], 1)
        for i, scene in enumerate(ep['scenes']):
            self.assertEqual(scene['narration'], ROW[7 + i * 2])
            self.assertEqual(scene['scene_action'], ROW[8 + i * 2])
        self.assertIn('Titan', ep['character_dna'])
        self.assertTrue(ep['title'].startswith(ROW[15]))

    def test_modern_webhook_is_not_remapped(self):
        modern = webhook_episode()
        self.assertEqual(main.normalize_webhook_episode(modern), modern)

    def test_missing_character_without_shift_signature_remains_an_error(self):
        data = webhook_episode()
        data.pop('char3_dna')
        with self.assertRaises(ValueError):
            main.parse_episode_from_row(main.normalize_webhook_episode(data))

    def test_incomplete_or_inconsistent_legacy_data_is_rejected(self):
        for field, value in [('s1_narration', 'Unknown character'),
                             ('s2_narration', 'Scene 3: Wrong action'),
                             ('s3_narration', ''), ('title', 'Missing fourth scene'),
                             ('s2_action', '')]:
            data = legacy_webhook_episode()
            data[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                main.parse_episode_from_row(main.normalize_webhook_episode(data))

    def test_title_split_by_legacy_script_is_restored(self):
        data = legacy_webhook_episode()
        data['tags'] = ['A Kitten', 'A Dog', 'A New Family']
        corrected = main.normalize_webhook_episode(data)
        self.assertEqual(corrected['title'], 'A Kitten, A Dog, A New Family')

    def test_missing_title_is_not_invented(self):
        for title in ['', [], None, 'https://youtube.com/shorts/old']:
            data = legacy_webhook_episode()
            data['tags'] = title
            with self.subTest(title=title), self.assertRaises(ValueError):
                main.normalize_webhook_episode(data)

    def test_http_status_is_reported_without_private_request_url(self):
        for code in [400, 401, 403]:
            response = main.requests.Response()
            response.status_code = code
            response.url = 'https://example.test/private-secret-path'
            with self.subTest(code=code), \
                    patch.dict(main.os.environ, {'SHEET_WEBHOOK_URL': ''}), \
                    patch.object(main.requests, 'get', return_value=response), \
                    patch('sys.stdout', new_callable=io.StringIO) as output:
                with self.assertRaises(RuntimeError) as raised:
                    main.fetch_next_episode_from_google_sheet()
                self.assertIn(f'HTTP {code}', str(raised.exception))
                self.assertIn(f'HTTP {code}', output.getvalue())
                self.assertNotIn('private-secret-path', str(raised.exception) + output.getvalue())


class ImagePromptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        image_data = io.BytesIO()
        Image.effect_noise((256, 256), 70).convert('RGB').save(image_data, format='PNG')
        cls.image_bytes = image_data.getvalue()

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.image_path = str(Path(directory.name) / 'scene.jpg')
        self.prompt = main.parse_episode_from_row(webhook_episode())['scenes'][0]['full_image_prompt']
        self.prompt += '\nBoundary characters: /?&# 中文 END_OF_PROMPT'
        self.assertGreater(len(self.prompt), 280)
        self.assertGreater(len(self.image_bytes), 20000)

    def test_full_character_details_and_punctuation_are_preserved(self):
        data = webhook_episode()
        data['char2_dna'] = 'Character 2: Mochi, Mia’s kitten (green eyes, white-tipped paws)'
        data['s1_action'] = "Scene 1: Mochi rests on Titan's chest; Mia watches."
        ep = main.parse_episode_from_row(data)
        for scene in ep['scenes']:
            for i in scene['character_indices']:
                self.assertIn(main.clean_prompt_text(data[f'char{i}_dna']), scene['full_image_prompt'])
        self.assertIn('Mia’s kitten (green eyes, white-tipped paws)', ep['scenes'][0]['full_image_prompt'])
        self.assertIn("Mochi rests on Titan's chest; Mia watches.", ep['scenes'][0]['full_image_prompt'])
        self.assertEqual(ep['scenes'][0]['narration'], data['s1_narration'])

    def test_owl_character_is_not_forced_to_be_a_cat(self):
        data = webhook_episode()
        data.update({
            'art_dna': 'Hand-drawn watercolor, soft morning light',
            'char1_dna': 'Character 1: Luna, a tiny calico kitten with blue eyes',
            'char2_dna': 'Character 2: Ollie, a baby barn owl with a white heart-shaped face',
            'char3_dna': 'Character 3: Leo, a boy in a ranger vest',
        })
        for i in range(1, 5):
            data[f's{i}_action'] = f'Scene {i}: Close-up of Luna touching noses with Ollie.'
        ep = main.parse_episode_from_row(data)
        for scene in ep['scenes']:
            prompt = scene['full_image_prompt']
            self.assertIn('Ollie, a baby barn owl with a white heart-shaped face', prompt)
            self.assertNotIn('feline cat', prompt)
            self.assertNotIn('human baby', prompt)
            self.assertNotIn('3D', prompt)
            self.assertIn('Close-up of Luna touching noses with Ollie.', prompt)

    def test_d_setting_is_preserved_separately_from_rotating_visual_style(self):
        for genre in ['溫馨喜劇', '懸疑', 'Macro wildlife photography, 85mm f/1.4']:
            with self.subTest(genre=genre):
                data = webhook_episode()
                data['art_dna'] = genre
                episode = main.parse_episode_from_row(data)
                self.assertEqual(episode['story_genre'], genre)
                for scene in episode['scenes']:
                    prompt = scene['full_image_prompt']
                    self.assertIn(f"Visual style: {main.VISUAL_STYLE_ROTATION[1]['prompt']}", prompt)
                    self.assertNotIn(genre, prompt)
                    self.assertNotIn('Masterpiece 3D cinema quality', prompt)
                    self.assertIn('bottom 15%', prompt)
                    self.assertIn('9:16', prompt)

    def test_each_scene_keeps_its_own_action_and_framing(self):
        data = webhook_episode()
        data['s3_action'] = 'Scene 3: Extreme close-up of the kitten sleeping on the dog’s chest.'
        scenes = main.parse_episode_from_row(data)['scenes']
        for i, scene in enumerate(scenes, start=1):
            self.assertTrue(scene['full_image_prompt'].startswith(
                f"Scene action: {main.clean_prompt_text(data[f's{i}_action'])}\n"))
        self.assertNotIn('Extreme close-up', scenes[0]['full_image_prompt'])
        self.assertIn('Extreme close-up', scenes[2]['full_image_prompt'])

    def test_pollinations_receives_full_prompt_and_reserved_characters(self):
        response = Mock(status_code=200, content=self.image_bytes)
        with patch.dict(main.os.environ, {'HF_TOKEN': '', 'GEMINI_API_KEY': ''}), \
                patch.object(main.requests, 'get', return_value=response) as get, \
                patch.object(main.time, 'sleep'):
            main.download_ai_keyframe(self.prompt, self.image_path, 1234, 1)
        get.assert_called_once()
        url = urlsplit(get.call_args.args[0])
        self.assertEqual(unquote(url.path.removeprefix('/prompt/')), self.prompt)
        self.assertEqual(parse_qs(url.query)['width'], ['768'])
        self.assertEqual(url.fragment, '')
        with Image.open(self.image_path) as image:
            self.assertEqual(image.size, (1080, 1920))

    def test_huggingface_receives_the_same_full_prompt(self):
        response = Mock(status_code=200, content=self.image_bytes)
        with patch.dict(main.os.environ, {'HF_TOKEN': 'mock-only', 'GEMINI_API_KEY': ''}), \
                patch.object(main.requests, 'post', return_value=response) as post, \
                patch.object(main.requests, 'get') as get:
            main.download_ai_keyframe(self.prompt, self.image_path, 1234, 1)
        post.assert_called_once()
        self.assertEqual(post.call_args.kwargs['json']['inputs'], self.prompt)
        get.assert_not_called()
        self.assertTrue(Path(self.image_path).is_file())

    def test_google_receives_the_same_full_prompt(self):
        from google import genai
        from google.genai import types
        client = Mock()
        client.models.generate_content.return_value = types.GenerateContentResponse(candidates=[
            types.Candidate(content=types.Content(parts=[
                types.Part(inline_data=types.Blob(data=self.image_bytes, mime_type='image/png'))
            ]))
        ])
        with patch.dict(main.os.environ, {'HF_TOKEN': '', 'GEMINI_API_KEY': 'mock-only', 'GEMINI_IMAGE_MODEL': ''}), \
                patch.object(genai, 'Client', return_value=client), \
                patch.object(main.requests, 'get') as get:
            main.download_ai_keyframe(self.prompt, self.image_path, 1234, 1)
        client.models.generate_content.assert_called_once()
        self.assertEqual(client.models.generate_content.call_args.kwargs['contents'], self.prompt)
        self.assertEqual(client.models.generate_content.call_args.kwargs['config'].image_config.aspect_ratio, '9:16')
        client.models.generate_images.assert_not_called()
        get.assert_not_called()
        self.assertTrue(Path(self.image_path).is_file())

    def test_oversized_url_stops_without_truncation_or_placeholder(self):
        with patch.dict(main.os.environ, {'HF_TOKEN': '', 'GEMINI_API_KEY': ''}), \
                patch.object(main.requests, 'get', return_value=Mock(status_code=414)) as get, \
                patch.object(main.time, 'sleep'):
            with self.assertRaises(main.ImagePromptTooLongError):
                main.download_ai_keyframe(self.prompt, self.image_path, 1234, 1)
        get.assert_called_once()
        self.assertEqual(unquote(urlsplit(get.call_args.args[0]).path.removeprefix('/prompt/')), self.prompt)
        self.assertFalse(Path(self.image_path).exists())


class VisualStyleRotationTests(unittest.TestCase):
    def test_six_sends_select_six_distinct_media_in_order(self):
        names, ids, prompts = [], [], []
        for count in range(6):
            data = webhook_episode()
            data['sent_count'] = count
            episode = main.parse_episode_from_row(data)
            names.append(episode['visual_style_name'])
            ids.append(episode['visual_style_id'])
            prompts.append(episode['selected_visual_style'])
            self.assertEqual(episode['sent_count'], count)
        self.assertEqual(names, ['3D 電影動畫', '日系 2D 動畫', '水彩繪本', '黏土定格', '立體紙雕', '真實風格'])
        self.assertEqual(len(set(ids)), 6)
        self.assertEqual(len(set(prompts)), 6)

    def test_genre_cast_and_four_scene_pairs_stay_fixed_across_all_six_versions(self):
        source = webhook_episode()
        source['art_dna'] = '溫馨喜劇'
        cast = []
        for count in range(6):
            data = dict(source, sent_count=count)
            before = data.copy()
            episode = main.parse_episode_from_row(data)
            self.assertEqual(data, before)
            self.assertEqual(episode['story_genre'], '溫馨喜劇')
            cast.append(episode['character_dna'])
            for i, scene in enumerate(episode['scenes'], start=1):
                self.assertEqual(scene['narration'], source[f's{i}_narration'])
                self.assertEqual(scene['scene_action'], source[f's{i}_action'])
                self.assertIn(episode['selected_visual_style'], scene['full_image_prompt'])
        self.assertEqual(len(set(cast)), 1)

    def test_all_four_scenes_use_only_the_selected_medium(self):
        for count in range(6):
            episode = main.parse_episode_from_row(dict(webhook_episode(), sent_count=count))
            for scene in episode['scenes']:
                for i, style in enumerate(main.VISUAL_STYLE_ROTATION):
                    if i == count:
                        self.assertIn(style['prompt'], scene['full_image_prompt'])
                    else:
                        self.assertNotIn(style['prompt'], scene['full_image_prompt'])

    def test_resume_uses_sheet_count_and_next_episode_restarts_at_first_style(self):
        resumed = main.parse_episode_from_row(dict(webhook_episode(), sent_count='4/6'))
        self.assertEqual(resumed['visual_style_name'], '立體紙雕')
        next_episode = main.parse_episode_from_row(dict(webhook_episode(), id='EP02', sent_count=0))
        self.assertEqual(next_episode['visual_style_name'], '3D 電影動畫')

    def test_new_genre_header_and_legacy_d_header_are_supported(self):
        for label in ['劇本類型 (Genre)', '故事類型', HEADERS[3]]:
            headers, row = HEADERS.copy(), ROW.copy()
            headers[3], row[3] = label, '冒險喜劇'
            with self.subTest(header=label):
                episode = main.episode_from_sheet_csv(sheet_csv([row], headers))
                self.assertEqual(episode['story_genre'], '冒險喜劇')
                self.assertEqual(episode['visual_style_name'], '日系 2D 動畫')

    def test_new_webhook_genre_key_is_accepted_without_changing_original_data(self):
        data = webhook_episode()
        del data['art_dna']
        data['genre'] = '懸疑'
        episode = main.parse_episode_from_row(data)
        self.assertEqual(episode['story_genre'], '懸疑')
        self.assertNotIn('art_dna', data)


if __name__ == '__main__':
    unittest.main()
