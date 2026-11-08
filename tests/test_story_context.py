import unittest

import main
from test_scene_cast import CAST
from test_six_scenes import six_episode


SETTING = ('Dim 3AM modern living room with gray fabric sofa, low oak coffee table, '
           'beige rug, and warm amber floor nightlight under cool blue moonlight')


class StoryContextTests(unittest.TestCase):
    def episode(self, genre=None, **changes):
        data = six_episode()
        data.update({f'char{i}_dna': character for i, character in enumerate(CAST, 1)})
        data['art_dna'] = genre if genre is not None else '懸疑反差喜劇｜固定場景：' + SETTING
        data.update(changes)
        return main.parse_episode_from_row(data)

    def test_workbook_setting_is_applied_once_to_all_six_scene_prompts(self):
        episode = self.episode()
        context = episode['story_context']
        self.assertEqual(context['genre_label'], '懸疑反差喜劇')
        self.assertEqual(context['shared_setting'], SETTING)
        self.assertIn('comic', context['tone'])
        self.assertIn('suspense', context['tone'])
        for scene in episode['scenes']:
            self.assertEqual(scene['full_image_prompt'].count(SETTING), 1)
            self.assertIn('Otherwise use the shared environment for continuity', scene['full_image_prompt'])

    def test_background_does_not_add_unselected_characters_to_closeup(self):
        action = 'Extreme close-up side-angle shot of Agent Oreo pushing a blue pen off the table.'
        scene = self.episode(s3_action=action)['scenes'][2]
        self.assertEqual(scene['character_indices'], [2])
        prompt = scene['full_image_prompt']
        self.assertIn(CAST[1], prompt)
        self.assertNotIn('Don Ginger', prompt)
        self.assertNotIn('Rookie Puff', prompt)
        self.assertIn('do not widen the shot', prompt)
        self.assertIn('Do not add other characters', prompt)
        self.assertTrue(prompt.startswith(f'Scene action: {action}\n'))

    def test_explicit_scene_time_and_place_keep_priority_over_episode_defaults(self):
        action = 'At sunrise outside the cabin, Don Ginger steps into bright morning sunlight.'
        episode = self.episode(s6_action=action)
        prompt = episode['scenes'][5]['full_image_prompt']
        self.assertTrue(prompt.startswith(f'Scene action: {action}\n'))
        self.assertIn('Its explicit location, time, weather and lighting override', prompt)
        self.assertIn(SETTING, prompt)
        self.assertEqual(episode['scenes'][5]['scene_action'], action)

    def test_genre_does_not_invent_rain_darkness_or_expression(self):
        for label in ['溫馨喜劇', '懸疑', '悲劇', '恐怖']:
            context = main.parse_story_context(label)
            self.assertTrue(context['tone'])
            self.assertEqual(context['shared_setting'], '')
            self.assertNotIn('rain', context['tone'].lower())
            self.assertNotIn('lighting', context['tone'].lower())
            self.assertNotIn('smile', context['tone'].lower())

    def test_old_art_style_text_cannot_replace_the_six_rotating_media(self):
        for count, style in enumerate(main.VISUAL_STYLE_ROTATION):
            episode = self.episode('3D Pixar animation style', sent_count=count)
            self.assertTrue(episode['story_context']['unmapped_genre'])
            for scene in episode['scenes']:
                self.assertIn(f"Visual style: {style['prompt']}\n", scene['full_image_prompt'])
                self.assertNotIn('3D Pixar animation style', scene['full_image_prompt'])
                self.assertNotIn('Episode context', scene['full_image_prompt'])

    def test_unknown_genre_is_preserved_without_inventing_visual_rules(self):
        episode = self.episode('Unmapped custom category')
        self.assertEqual(episode['story_genre'], 'Unmapped custom category')
        self.assertTrue(episode['story_context']['unmapped_genre'])
        self.assertEqual(episode['story_context']['tone'], '')
        self.assertNotIn('Unmapped custom category', episode['scenes'][0]['full_image_prompt'])

    def test_chinese_and_english_setting_labels_are_supported(self):
        for label in ['固定場景', '共同場景', '場景設定', 'Shared setting', 'Common setting', 'Setting']:
            with self.subTest(label=label):
                context = main.parse_story_context('Comedy | ' + label + ': ' + SETTING)
                self.assertEqual(context['shared_setting'], SETTING)
                self.assertTrue(context['tone'])

    def test_empty_explicit_setting_is_rejected_before_generation(self):
        with self.assertRaisesRegex(ValueError, '未填寫場景內容'):
            self.episode('喜劇｜固定場景：')

    def test_setting_only_does_not_get_misclassified_as_a_genre(self):
        context = main.parse_story_context('固定場景：Warm sunny living room with a fantasy poster on the wall')
        self.assertEqual(context['genre_label'], '')
        self.assertEqual(context['tone'], '')
        self.assertIn('fantasy poster', context['shared_setting'])

    def test_unlabelled_environment_is_not_silently_guessed_from_prose(self):
        context = main.parse_story_context('Warm 3D animation')
        self.assertEqual(context['tone'], 'Warm, caring emotional tone')
        self.assertEqual(context['shared_setting'], '')
        self.assertNotIn('3D', main.story_context_prompt(context))

    def test_cast_resolution_does_not_use_names_or_groups_from_d_column(self):
        episode = self.episode('三隻貓的懸疑喜劇｜固定場景：' + SETTING,
                               s3_action='Agent Oreo pushes a pen off the table.')
        self.assertEqual(episode['scenes'][2]['character_indices'], [2])

    def test_original_d_and_all_narrations_stay_intact(self):
        source = six_episode()
        source['art_dna'] = '懸疑反差喜劇｜固定場景：' + SETTING
        before = source.copy()
        episode = main.parse_episode_from_row(source)
        self.assertEqual(source, before)
        self.assertEqual(episode['story_genre'], before['art_dna'])
        for i, scene in enumerate(episode['scenes'], 1):
            self.assertEqual(scene['narration'], before[f's{i}_narration'])
            self.assertEqual(scene['scene_action'], before[f's{i}_action'])


if __name__ == '__main__':
    unittest.main()
