"""Repair placement/range tests; synthetic sources never certify a seam or performance."""
import copy
from pathlib import Path
import sys
import unittest
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'desktop'))
import production_edit as edit
import production_project as project
import production_repair as repair
import production_jobs as jobs


class RepairTests(unittest.TestCase):
    def fixture(self):
        return dict(brief='Synthetic', decisions=[], unresolved=[], shots=[], assets=[], selections={}, undo=[], redo=[],
            edit=dict(fps='24', sample_rate=48000, segments=[dict(id='prefix', asset='original', in_frame=0, out_frame=120)], audio=[], markers=[], titles=[]))

    def binding(self, value, operation='Retake', modality='both'):
        return dict(id='synthetic-repair', operation=operation, modality=modality,
                    edit_projection=project.edit_token(value), anchors={'segment': copy.deepcopy(value['edit']['segments'][0])},
                    retake_in=24, retake_out=72, frames=48, source_in_frame=22, source_out_frame=70)

    def test_retake_preserves_prefix_suffix_and_unique_occurrences(self):
        value = self.fixture()
        repair.place(value, self.binding(value), 'repaired')
        segments = value['edit']['segments']
        self.assertEqual([(s['asset'], s['in_frame'], s['out_frame']) for s in segments],
                         [('original', 0, 24), ('repaired', 22, 70), ('original', 72, 120)])
        self.assertEqual(len({s['id'] for s in segments}), 3)
        self.assertEqual(edit.flatten(value['edit'])['frames'], 120)

    def test_picture_only_keeps_original_interval_sound(self):
        value = self.fixture()
        repair.place(value, self.binding(value, modality='picture'), 'repaired')
        self.assertTrue(value['edit']['segments'][1]['mute'])
        cue = value['edit']['audio'][0]
        self.assertEqual((cue['asset'], cue['start_sample'], cue['in_sample'], cue['samples']), ('original', 48000, 48000, 96000))

    def test_audio_only_keeps_original_picture_and_new_independent_sound(self):
        value = self.fixture()
        repair.place(value, self.binding(value, modality='audio'), 'sound-take')
        self.assertTrue(all(s['asset'] == 'original' for s in value['edit']['segments']))
        self.assertEqual(value['edit']['audio'][0]['asset'], 'sound-take')
        self.assertEqual(value['edit']['audio'][0]['in_sample'], 44000)

    def test_extension_trims_overlap_once_without_changing_prefix(self):
        value = self.fixture()
        original = copy.deepcopy(value['edit']['segments'][0])
        repair.place(value, self.binding(value, operation='Extend'), 'extension')
        self.assertEqual(value['edit']['segments'][0], original)
        self.assertEqual(value['edit']['segments'][1]['in_frame'], 22)
        self.assertEqual(edit.flatten(value['edit'])['frames'], 168)

    def test_changed_neighbour_or_mix_refuses_stale_placement(self):
        value = self.fixture(); binding = self.binding(value)
        value['edit']['markers'].append({'frame': 1, 'text': 'New edit'})
        with self.assertRaises(project.ProjectError):
            repair.place(value, binding, 'outdated')
        self.assertEqual(len(value['edit']['segments']), 1)

    def test_short_retake_endpoint_is_in_retained_interval_and_variants_are_distinct(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); media = root / 'source.mp4'; media.write_bytes(b'synthetic range fixture')
            value = self.fixture()
            value['assets'] = [dict(id='original', path='source.mp4', sha256=jobs.file_hash(media))]
            data = dict(repair='Retake', segment='prefix', frames=48, in_frame=24, out_frame=72,
                        prompt='Synthetic range validation', request={'Seed': 1}, defect='fixture')
            def write_still(args, timeout):
                Path(args[-1]).write_bytes(b'synthetic still fixture')
            with patch.object(edit, 'validate_cfr', return_value=120), patch.object(edit, 'run', side_effect=write_still):
                first = repair.prepare(root, value, data, {'ffmpeg': 'unused', 'ffprobe': 'unused'})
                self.assertEqual((first['source_out_frame'], first['request']['LastFrameAt']), (48, 47))
                data['request']['Seed'] = 2
                second = repair.prepare(root, value, data, {'ffmpeg': 'unused', 'ffprobe': 'unused'})
                self.assertNotEqual(first['id'], second['id'])


if __name__ == '__main__':
    unittest.main()
