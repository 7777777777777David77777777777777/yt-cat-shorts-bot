import unittest

import main
from test_sheet_mapping import webhook_episode


CAST = [
    'Don Ginger, a chubby orange tabby cat with green eyes',
    'Agent Oreo, a black-and-white tuxedo cat with white mittens',
    'Rookie Puff, a tiny cream Scottish Fold kitten with round eyes',
]


class SceneCastTests(unittest.TestCase):
    def test_only_oreo_is_injected_for_named_closeup(self):
        data = webhook_episode()
        data.update({f'char{i}_dna': character for i, character in enumerate(CAST, 1)})
        data['s3_action'] = 'Scene 3: Extreme close-up of Agent Oreo pushing a pen over the table edge.'
        scene = main.parse_episode_from_row(data)['scenes'][2]
        self.assertEqual(scene['character_indices'], [2])
        self.assertEqual(scene['character_selection'], 'names')
        self.assertIn(CAST[1], scene['full_image_prompt'])
        self.assertNotIn('Don Ginger', scene['full_image_prompt'])
        self.assertNotIn('Rookie Puff', scene['full_image_prompt'])
        self.assertIn('Do not add other characters', scene['full_image_prompt'])

    def test_two_named_characters_and_case_insensitive_short_names(self):
        self.assertEqual(main.scene_character_indices(CAST, 'ginger greets OREO.')[0], [0, 1])
        self.assertEqual(main.scene_character_indices(CAST, "Oreo's white paw holds a pen.")[0], [1])
        self.assertEqual(main.scene_character_indices(CAST, 'Puff watches from a doorway.')[0], [2])

    def test_boundaries_do_not_match_names_inside_other_words(self):
        indices, method = main.scene_character_indices(['Mia, a girl', 'Mochi, a kitten', 'Titan, a dog'],
                                                      'Mochi sits on a titanium chair in Miami.')
        self.assertEqual((indices, method), ([1], 'names'))

    def test_names_in_dna_do_not_leak_into_action_matching(self):
        cast = [CAST[0], CAST[1] + ', friendly with Don Ginger', CAST[2]]
        self.assertEqual(main.scene_character_indices(cast, 'Oreo raises his paw.')[0], [1])

    def test_all_three_and_pronoun_groups_are_conservative(self):
        for action in ['All three lick their paws.', 'Everyone looks toward Oreo.',
                       'Oreo and all the cats sit down.', 'Oreo watches them.', '三隻貓一起坐下']:
            with self.subTest(action=action):
                self.assertEqual(main.scene_character_indices(CAST, action)[0], [0, 1, 2])

    def test_missing_names_keep_legacy_scripts_and_report_fallback(self):
        indices, method = main.scene_character_indices(CAST, 'A cat raises one paw.')
        self.assertEqual(indices, [0, 1, 2])
        self.assertEqual(method, 'no_names')

    def test_unnamed_animal_is_not_dropped_when_only_customer_is_named(self):
        cast = ['Yuzu, an orange tabby cat', 'Kenji, a man wearing a business suit',
                'Store Manager Sato, a friendly man in a blue uniform']
        indices, method = main.scene_character_indices(cast, 'Kenji gives a high-five to an orange cat.')
        self.assertEqual(indices, [0, 1])
        self.assertEqual(method, 'names_and_type')
        self.assertEqual(main.scene_character_indices(cast, 'Manager Sato smiles.')[0], [2])

    def test_generic_appositive_can_keep_a_single_named_cat(self):
        self.assertEqual(main.scene_character_indices(CAST, 'Agent Oreo, the tuxedo cat, pushes a pen.')[0], [1])

    def test_shared_name_aliases_are_not_guessed(self):
        cast = ['Mia Rose, an adult woman', 'Mia Chen, an adult woman', 'Oreo, a cat']
        self.assertEqual(main.scene_character_indices(cast, 'Mia Rose waves.')[0], [0])
        self.assertEqual(main.scene_character_indices(cast, 'Mia waves.')[1], 'ambiguous_name')

    def test_simple_negative_and_offscreen_mentions_are_excluded(self):
        self.assertEqual(main.scene_character_indices(CAST, 'Oreo holds a pen without Ginger.')[0], [1])
        self.assertEqual(main.scene_character_indices(CAST, 'Oreo watches; Puff remains off-screen.')[0], [1])

    def test_legacy_name_without_comma_is_supported(self):
        self.assertEqual(main.character_name_aliases('Mia in a yellow raincoat'), {'mia'})
        self.assertEqual(main.character_name_aliases('Character 2: Agent Oreo, a tuxedo cat'), {'agent oreo', 'oreo'})

    def test_narration_does_not_force_offscreen_cast_into_image(self):
        data = webhook_episode()
        data.update({f'char{i}_dna': character for i, character in enumerate(CAST, 1)})
        data['s3_narration'] = 'Don Ginger sent Oreo to help Rookie Puff.'
        data['s3_action'] = 'Oreo pushes a pen off the desk.'
        episode = main.parse_episode_from_row(data)
        self.assertEqual(episode['scenes'][2]['character_indices'], [2])
        self.assertIn('Don Ginger', episode['character_dna'])
        self.assertEqual(episode['scenes'][2]['narration'], data['s3_narration'])


if __name__ == '__main__':
    unittest.main()
