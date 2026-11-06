"""Source-independent shared-interface tests. Synthetic media does not prove film quality."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'desktop'))
import production_service as service
import production_project as project
import production_coordinator as coordinator
import production_edit as edit
import production_jobs as jobs


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.counter = 0
        self.value = self.call('create', {'title': 'Synthetic fixture'})['result']

    def call(self, operation, data=None, expected=None, request_id=None):
        self.counter += 1
        request = dict(version=1, request_id=request_id or 'r' + str(self.counter), operation=operation,
                       project_id=getattr(self, 'value', {}).get('id'),
                       expected_revision=expected or getattr(self, 'value', {}).get('revision'), payload=data or {})
        result = service.dispatch(self.root, request)
        if result['ok'] and isinstance(result['result'], dict) and result['result'].get('project'):
            self.value = result['result']['project']
        return result

    def add(self):
        result = self.call('shot-add')
        self.assertTrue(result['ok'], result)
        return self.value['selected_shot']

    def test_conflicts_and_replay_precede_expected_revision(self):
        revision = self.value['revision']
        first = self.call('shot-add', expected=revision, request_id='same')
        replay = self.call('shot-add', expected=revision, request_id='same')
        self.assertTrue(replay['ok'])
        self.assertEqual(first['result']['receipt'], replay['result']['receipt'])
        self.assertEqual(len(self.value['shots']), 1)
        self.assertEqual(self.call('shot-add', {'name': 'changed'}, expected=revision, request_id='same')['code'], 'conflict')
        self.assertEqual(self.call('shot-add', expected=revision)['code'], 'conflict')

    def test_narrow_shot_and_broad_authority_invalidation(self):
        a, b = self.add(), self.add()
        old = project.projection(self.value, a)
        self.call('shot-update', {'shot': b, 'changes': {'prompt': 'Different shot'}})
        self.assertEqual(old, project.projection(self.value, a))
        self.call('shot-update', {'shot': a, 'changes': {'name': 'Metadata only'}})
        self.assertEqual(old, project.projection(self.value, a))
        self.call('plan', {'brief': 'Changed direction'})
        self.assertNotEqual(old, project.projection(self.value, a))

    def test_adopted_media_survives_original_and_same_name_is_distinct(self):
        shot = self.add()
        source = self.root / 'same.png'
        source.write_bytes(b'first synthetic media')
        self.call('asset-import', {'path': str(source), 'role': 'keyframe', 'shot': shot})
        first = self.value['assets'][0]
        source.write_bytes(b'changed synthetic media')
        self.call('asset-import', {'path': str(source), 'role': 'keyframe', 'shot': shot})
        second = self.value['assets'][1]
        self.assertNotEqual(first['path'], second['path'])
        source.unlink()
        jobs.file_hash(project.folder(self.root, self.value['id']) / first['path'], first['sha256'])

    def test_create_adoption_collects_declared_materials_and_null_reference_lists(self):
        image = self.root / 'create.png'; image.write_bytes(b'Synthetic generated media')
        reference = self.root / 'reference.png'; reference.write_bytes(b'Synthetic conditioning source')
        Path(str(image) + '.json').write_text(json.dumps({'Source': str(reference), 'References': None}))
        result = self.call('asset-import', {'path': str(image), 'role': 'keyframe'})
        self.assertTrue(result['ok'], result)
        asset = self.value['assets'][0]
        binding = asset['provenance']['material_bindings'][0]
        image.unlink(); reference.unlink()
        managed = project.folder(self.root, self.value['id'])
        jobs.file_hash(managed / asset['path'], asset['sha256'])
        jobs.file_hash(managed / binding['path'], binding['sha256'])

    def test_animatic_requires_keyframes_and_becomes_stale(self):
        shot = self.add()
        self.assertFalse(self.call('approve-animatic', {'reviewer': 'Synthetic', 'finding': 'Fixture only'})['ok'])
        source = self.root / 'panel.png'; source.write_bytes(b'panel')
        self.call('asset-import', {'path': str(source), 'role': 'keyframe', 'shot': shot})
        self.assertTrue(self.call('approve-animatic', {'reviewer': 'Synthetic', 'finding': 'Fixture only'})['ok'])
        self.assertTrue(self.value['animatic_current'])
        self.call('shot-update', {'shot': shot, 'changes': {'dialogue': 'Changed words'}})
        self.assertFalse(self.value['animatic_current'])

    def test_split_occurrences_undo_and_sample_audio(self):
        self.call('segment-insert', {'segment': {'asset': None, 'in_frame': 0, 'out_frame': 120}})
        segment = self.value['edit']['segments'][0]['id']
        self.call('segment-split', {'segment': segment, 'source_frame': 60})
        timeline = edit.flatten(self.value['edit'])
        self.assertEqual(timeline['frames'], 120)
        self.assertEqual(timeline['boundaries'][0]['frame'], 60)
        self.assertNotEqual(timeline['shots'][0]['id'], timeline['shots'][1]['id'])
        self.call('undo')
        self.assertEqual(len(self.value['edit']['segments']), 1)
        self.call('redo')
        self.assertEqual(len(self.value['edit']['segments']), 2)
        self.assertFalse(self.call('audio-add', {'item': {'track': 'music', 'start_sample': -1, 'samples': 100}})['ok'])

    def test_corrupt_project_preserved(self):
        root = project.folder(self.root, self.value['id'])
        (root / 'project.json').write_text('{broken')
        self.assertFalse(self.call('open')['ok'])
        self.assertEqual((root / 'project.json').read_text(), '{broken')

    def test_protocol_and_path_boundaries(self):
        self.assertEqual(service.dispatch(self.root, {'version': 22, 'request_id': 'x'})['code'], 'unsupported-version')
        self.assertEqual(service.dispatch(self.root, {'version': 1, 'request_id': 'x', 'operation': 'open', 'project_id': '../outside'})['code'], 'invalid-input')

    def test_collection_hashes_and_changed_byte_relink_rejected(self):
        shot = self.add()
        source = self.root / 'source.wav'; source.write_bytes(b'synthetic recording')
        self.call('asset-import', {'path': str(source), 'role': 'dialogue', 'shot': shot})
        asset = self.value['assets'][0]
        destination = self.root / 'collected'
        result = self.call('collect', {'destination': str(destination)})
        self.assertTrue(result['ok'], result)
        collected = project.folder(destination, self.value['id'])
        self.assertEqual(project.snapshot(collected)['id'], self.value['id'])
        for item in result['result']['collection']['files']:
            jobs.file_hash(collected / item['path'], item['sha256'])
        source.write_bytes(b'different same filename')
        self.assertFalse(self.call('relink', {'asset': asset['id'], 'path': str(source)})['ok'])
        another = self.root / 'another-studio'
        imported = service.dispatch(another, dict(version=1, operation='import-collection', request_id='import-one',
                                                payload={'manifest': str(destination / 'collection.json')}))
        self.assertTrue(imported['ok'], imported)
        self.assertEqual(imported['result']['id'], self.value['id'])
        moved_root = project.folder(another, self.value['id'])
        jobs.file_hash(moved_root / asset['path'], asset['sha256'])
        conflict = service.dispatch(another, dict(version=1, operation='import-collection', request_id='different-import',
                                                payload={'manifest': str(destination / 'collection.json')}))
        self.assertEqual(conflict['code'], 'conflict')

    def test_gpu_slot_excludes_other_work_and_no_ambiguous_replay(self):
        transport = lambda *args: {'queue_running': [], 'queue_pending': []}
        coordinator.command(self.root, 'gpu-claim', {'owner': 'create', 'intent': '1'}, transport)
        with self.assertRaises(project.ProjectError):
            coordinator.command(self.root, 'gpu-claim', {'owner': 'film', 'intent': '2'}, transport)
        coordinator.command(self.root, 'gpu-submitting', {'owner': 'create', 'prompt_id': 'id', 'payload': {'prompt': {}}})
        with self.assertRaises(project.ProjectError):
            coordinator.command(self.root, 'gpu-submitting', {'owner': 'create', 'prompt_id': 'id', 'payload': {'prompt': {}}})
        with self.assertRaises(project.ProjectError):
            coordinator.command(self.root, 'gpu-release', {'owner': 'create'})
        coordinator.command(self.root, 'gpu-release', {'owner': 'create', 'terminal': True})

    def test_cancel_queued_is_replay_safe_and_never_contacts_engine(self):
        root = project.folder(self.root, self.value['id'])
        with jobs.locked(root):
            value = project.load(root)
            value['queue'] = [dict(id='q1', status='queued', item={'name': 'fixture'}),
                              dict(id='q2', status='queued', item={'name': 'second'})]
            self.value = project.save(root, value)
        with patch.object(jobs, 'http_json') as transport:
            result = self.call('cancel', {'item_id': 'q1'}, request_id='cancel1')
            self.assertTrue(result['ok'], result)
            replay = self.call('cancel', {'item_id': 'q1'}, request_id='cancel1')
            self.assertTrue(replay['ok'])
            self.assertEqual(self.value['queue'][0]['status'], 'cancelled')
            self.assertEqual(self.value['queue'][1]['status'], 'queued')
            transport.assert_not_called()

    def test_gpu_mutation_receipts_survive_slot_release_and_conflict(self):
        request = dict(version=1, operation='gpu-claim', request_id='global-request', payload={'owner': 'first', 'intent': 'one'})
        transport = lambda *args: {'queue_running': [], 'queue_pending': []}
        accepted = coordinator.dispatch(self.root, request, transport)
        coordinator.command(self.root, 'gpu-release', {'owner': 'first'})
        coordinator.command(self.root, 'gpu-claim', {'owner': 'second', 'intent': 'two'}, transport)
        replay = coordinator.dispatch(self.root, request, transport)
        self.assertEqual(accepted, replay)
        self.assertEqual(coordinator.command(self.root, 'gpu-status', {})['owner'], 'second')
        with self.assertRaises(project.ProjectError):
            coordinator.dispatch(self.root, {**request, 'payload': {'owner': 'changed', 'intent': 'one'}}, transport)

    def test_tick_replay_cannot_admit_new_work_after_revision_advances(self):
        first = self.call('drive-one', request_id='bounded-tick')
        self.assertTrue(first['ok'], first)
        self.add()
        with patch.object(jobs, 'run') as runner:
            replay = self.call('drive-one', request_id='bounded-tick')
            self.assertTrue(replay['ok'], replay)
            self.assertEqual(replay['result']['status'], 'idle')
            runner.assert_not_called()
        self.assertEqual(self.call('plan', {'brief': 'different op'}, request_id='bounded-tick')['code'], 'conflict')

    @unittest.skipUnless(sys.platform == 'win32', 'Windows WDDM classification')
    def test_graphics_contexts_do_not_block_but_unknown_cuda_contexts_wait(self):
        import types
        for kind, expected in [('graphics-only', []), ('authorized-coexistence', []), ('compute-context', [123]), ('unknown-context', [123])]:
            responses = [types.SimpleNamespace(returncode=0, stdout='123\n'),
                         types.SimpleNamespace(returncode=0, stdout=json.dumps([{'pid': 123, 'kind': kind}]))]
            with patch.object(coordinator.shutil, 'which', return_value='nvidia-smi'), \
                 patch.object(coordinator.subprocess, 'run', side_effect=responses):
                self.assertEqual(coordinator.external_gpu_processes('http://127.0.0.1:8193', lambda *args: {'devices': [{'type': 'cuda'}], 'system': {'argv': []}}), expected)

    def test_coexistence_permission_is_scoped_expiring_and_content_bound(self):
        import datetime
        root = coordinator.coordinator_root(self.root)
        authority = self.root / 'approval.txt'; authority.write_text('Explicit current-process coexistence approval')
        now = datetime.datetime.now(datetime.timezone.utc)
        permission = dict(schema=1, owners=[self.value['id'] + '_item'],
            expires_utc=(now + datetime.timedelta(minutes=5)).isoformat(),
            authority={'path': str(authority), 'sha256': jobs.file_hash(authority)},
            processes=[dict(pid=123, executable=str((self.root / 'app.exe').resolve()), started='exact-process-start')])
        jobs.atomic_json(root / 'coexistence.json', permission)
        accepted = coordinator.authorized_coexistence(root, self.value['id'] + '_item')
        self.assertIsNotNone(accepted)
        proof = Path(accepted['permission']['path'])
        self.assertIsNone(coordinator.authorized_coexistence(root, 'another_project_item'))
        permission['expires_utc'] = (now - datetime.timedelta(seconds=1)).isoformat()
        jobs.atomic_json(root / 'coexistence.json', permission)
        self.assertEqual(jobs.file_hash(proof), accepted['permission']['sha256'])
        self.assertIsNone(coordinator.authorized_coexistence(root, self.value['id'] + '_item'))
        permission['expires_utc'] = (now + datetime.timedelta(minutes=5)).isoformat()
        jobs.atomic_json(root / 'coexistence.json', permission)
        authority.write_text('changed authority')
        with self.assertRaises(ValueError):
            coordinator.authorized_coexistence(root, self.value['id'] + '_item')

    def test_cli_protocol_is_utf8_independent_of_windows_stream_default(self):
        import os
        title = 'Film café — 球 🎬'
        request = dict(version=1, operation='create', request_id='unicode-cli', payload={'title': title})
        result = subprocess.run([sys.executable, str(Path(service.__file__)), str(self.root)],
            input=json.dumps(request, ensure_ascii=False), encoding='utf-8', capture_output=True,
            env={**os.environ, 'PYTHONIOENCODING': 'cp1252'}, check=True)
        self.assertEqual(json.loads(result.stdout)['result']['title'], title)

    @unittest.skipUnless(sys.platform == 'win32', 'Windows process identity and NVIDIA driver')
    def test_native_coexistence_matches_exact_process_lifetime_and_executable(self):
        import ctypes
        import os
        try:
            driver = ctypes.WinDLL('nvcuda.dll')
        except OSError:
            self.skipTest('NVIDIA driver unavailable')
        process_id = os.getpid()
        started = subprocess.run(['powershell.exe', '-NoProfile', '-Command',
            f'(Get-Process -Id {process_id}).StartTime.ToUniversalTime().ToString("o")'],
            capture_output=True, text=True, check=True).stdout.strip()
        identity = dict(pid=process_id, executable=sys.executable, started=started)
        original = subprocess.run
        def inspect(args, **kwargs):
            if args[0] == 'nvidia-smi':
                return subprocess.CompletedProcess(args, 0, str(process_id) + '\n', '')
            return original(args, **kwargs)
        stats = lambda *args: {'devices': [{'type': 'cuda'}], 'system': {'argv': []}}
        with patch.object(coordinator.shutil, 'which', return_value='nvidia-smi'), \
             patch.object(coordinator.subprocess, 'run', side_effect=inspect):
            self.assertEqual(coordinator.external_gpu_processes('http://127.0.0.1:8193', stats, {'processes': [identity]}), [])
            for changed in ({'started': 'different process lifetime'}, {'executable': str(self.root / 'other.exe')}):
                self.assertEqual(coordinator.external_gpu_processes('http://127.0.0.1:8193', stats,
                    {'processes': [{**identity, **changed}]}), [process_id])

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg/FFprobe unavailable')
    def test_three_shot_native_service_draft_and_decode(self):
        source = self.root / 'source.mp4'
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=blue:s=128x72:r=24',
                        '-frames:v', '24', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(source)], check=True)
        for _ in range(3):
            shot = self.add()
            imported = self.call('asset-import', {'path': str(source), 'role': 'take', 'shot': shot})
            self.assertTrue(imported['ok'], imported)
            asset = self.value['assets'][-1]['id']
            self.call('segment-insert', {'segment': {'asset': asset, 'shot': shot, 'in_frame': 0, 'out_frame': 24}})
        result = self.call('render-draft', {'width': 128, 'height': 72})
        self.assertTrue(result['ok'], result)
        cut = self.value['cuts'][-1]
        self.assertEqual(cut['timeline']['frames'], 72)
        self.assertFalse(cut['incomplete'])
        self.assertTrue(cut['technical']['full_decode'])
        self.assertIn('NOT APPROVED', cut['label'])


if __name__ == '__main__':
    unittest.main()
