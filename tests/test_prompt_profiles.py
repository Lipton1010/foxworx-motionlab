import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "desktop"))
import prompt_profiles as profiles
import rewrite_prompt as rewrite


class PromptProfilesTests(unittest.TestCase):
    def test_each_target_routes_without_universal_h3_syntax(self):
        for target in profiles.PROFILES:
            mode = "t2v" if target in ("minimax", "ltx") else "t2i"
            profile = profiles.profile_for(target, mode)
            self.assertEqual(len(profile['sha256']), 64)
            self.assertIn('meaning', profile['system'])
        self.assertNotIn('integrated_multimodal_description', profiles.profile_for('ltx', 't2v')['system'])
        self.assertIn('integrated_multimodal_description', profiles.profile_for('minimax', 't2v')['system'])

    def test_unknown_and_wrong_media_fail_closed(self):
        for target, mode in [('unknown', 't2i'), ('minimax', 'edit'), ('krea', 't2v')]:
            with self.assertRaises(ValueError):
                profiles.profile_for(target, mode)

    def test_editable_profile_has_different_identity(self):
        base = profiles.profile_for('minimax', 'i2v')
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, 'minimax.json').write_text(json.dumps({'version': 'local-2', 'guidance': 'Preserve camera direction.'}))
            custom = profiles.profile_for('minimax', 'i2v', folder)
        self.assertNotEqual(base['sha256'], custom['sha256'])
        self.assertTrue(custom['custom'])

    def test_truncated_or_invalid_output_preserves_original(self):
        for reason, content in [('length', '{"prompt":"x","warnings":[]}'), ('stop', 'not json'), ('stop', '{"prompt":"","warnings":[]}')]:
            with self.assertRaises((ValueError, json.JSONDecodeError)):
                rewrite.parse_result({'choices': [{'finish_reason': reason, 'message': {'content': content}}]})

    def test_h3_missing_sections_does_not_replace_draft(self):
        response = {'choices': [{'finish_reason': 'stop', 'message': {'content': '{"prompt":"Plain prose without sections","warnings":[]}'}}]}
        with self.assertRaisesRegex(ValueError, 'required profile sections'):
            rewrite.parse_result(response, 'minimax')

    def test_h3_format_marker_is_not_duplicated(self):
        for start in ('', '[Shot 1] '):
            prompt = 'integrated_multimodal_description: ' + start + 'Red square.\noverall_soundscape: N/A\nnon_diegetic_music: N/A'
            result = rewrite.parse_result({'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps({'prompt': prompt, 'warnings': []})}}]}, 'minimax')
            self.assertEqual(result['prompt'].count('[Shot 1]'), 1)

    def test_full_system_and_mode_participate_in_profile_hash(self):
        first = profiles.profile_for('qwen', 't2i')['sha256']
        self.assertNotEqual(first, profiles.profile_for('qwen', 'edit')['sha256'])
        with patch.object(profiles, 'COMMON', profiles.COMMON + ' Added preservation rule.'):
            self.assertNotEqual(first, profiles.profile_for('qwen', 't2i')['sha256'])

    def test_valid_output(self):
        result = rewrite.parse_result({'choices': [{'finish_reason': 'stop', 'message': {'content': '{"prompt":"Exact words","warnings":[]}'}}]})
        self.assertEqual(result['prompt'], 'Exact words')

    def test_wrong_model_receipt_cannot_substitute_restricted_pe(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(rewrite, 'ROOT', Path(folder)):
            target = Path(folder, 'models/prompt-refiner')
            target.mkdir(parents=True)
            (target / '4b.json').write_text(json.dumps({'family': 'qwen3.5', 'tier': '4b', 'license': 'Apache-2.0', 'model': {'sha256': '0'*64}}))
            with self.assertRaisesRegex(ValueError, 'reviewed Qwen3.5'):
                rewrite.configuration('4b', [])

    def test_absent_pack_does_not_download_or_start(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(rewrite, 'ROOT', Path(folder)):
            with self.assertRaisesRegex(ValueError, 'No model is downloaded'):
                rewrite.configuration('4b', [])


if __name__ == '__main__':
    unittest.main()
