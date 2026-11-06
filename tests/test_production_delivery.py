"""Final-commit integrity tests. Supplied reviewer judgments are explicitly synthetic."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'desktop'))
import production_acceptance as acceptance
import production_delivery as delivery
import production_jobs as jobs
import production_project as project
import production_service as service


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.studio = Path(self.temp.name)
        self.value = project.create(self.studio, uuid.uuid4().hex, 'Synthetic gate fixture')
        self.root = project.folder(self.studio, self.value['id'])
        self.authority = self.root / 'fixture-authority.txt'
        self.authority.write_text('Synthetic integrity fixture only, not real approval')
        self.call('plan', dict(brief='Synthetic final-commit tests', decisions=['Exercise exact byte gates'], unresolved=[]))
        self.call('direction-record', {'authority': str(self.authority)})
        self.artifact = self.root / 'draft.mp4'
        self.artifact.write_bytes(b'Synthetic encoded bytes, no media quality claim')
        with jobs.locked(self.root):
            value = project.load(self.root)
            timeline = dict(fps=24, frames=72, shots=[dict(id=str(i), start=str(i), end=str(i+1)) for i in range(3)])
            value['cuts'].append(dict(path=str(self.artifact), sha256=jobs.file_hash(self.artifact), projection=project.edit_token(value),
                                      incomplete=False, timeline=timeline, dependencies=[]))
            self.value = project.save(self.root, value)
        task = jobs.read_json(self.root / 'task/current-task.json')
        result = self.call('promote', {'sha256': jobs.file_hash(self.artifact), 'task_sha256': acceptance.fingerprint(task)})
        self.assertTrue(result['ok'], result)

    def call(self, operation, payload):
        result = service.dispatch(self.studio, dict(version=1, operation=operation, request_id=uuid.uuid4().hex,
                     project_id=self.value['id'], expected_revision=self.value['revision'], payload=payload))
        if result['ok'] and isinstance(result['result'], dict) and result['result'].get('project'):
            self.value = result['result']['project']
        return result

    def review(self):
        candidate = self.value['candidate']
        task = jobs.read_json(self.root / 'task/current-task.json')
        review = dict(task_sha256=candidate['task_sha256'], candidate_sha256=acceptance.fingerprint(candidate),
                      artifact_sha256=candidate['artifact']['sha256'], reviewer='Synthetic test reviewer', checks={})
        for key, rule in task['requirements'].items():
            review['checks'][key] = dict(status='passed', finding='Synthetic assertion, not real viewing',
                                        inspected=rule['modalities'], method='Synthetic gate fixture', evidence=[candidate['artifact']])
        for frame in acceptance.cut_frames(candidate):
            review['checks']['cut:' + str(frame)] = dict(status='passed', finding='Synthetic boundary assertion',
                inspected=['frame-pair', 'motion', 'audio'], method='Synthetic fixture', evidence=[candidate['artifact']],
                frames=[frame-1, frame], staging='Synthetic intended staging', before=candidate['artifact'], after=candidate['artifact'])
        return review

    def test_promoted_bytes_are_exact_and_delivery_requires_review(self):
        candidate = self.value['candidate']
        self.assertEqual(jobs.file_hash(candidate['artifact']['path']), jobs.file_hash(self.artifact))
        missing = self.call('deliver', {'review': {**self.review(), 'checks': {}}, 'destination': str(self.root / 'missing.mp4')})
        self.assertFalse(missing['ok'])
        passed = self.call('deliver', {'review': self.review(), 'destination': str(self.root / 'delivered.mp4')})
        self.assertTrue(passed['ok'], passed)
        self.assertEqual(jobs.file_hash(self.root / 'delivered.mp4'), jobs.file_hash(self.artifact))

    def test_old_intact_candidate_cannot_deliver_after_edit_change(self):
        review = self.review()
        self.call('segment-insert', {'segment': {'asset': None, 'in_frame': 0, 'out_frame': 24}})
        result = self.call('deliver', {'review': review, 'destination': str(self.root / 'stale.mp4')})
        self.assertEqual(result['code'], 'conflict')
        self.assertFalse(list((self.root / 'deliveries').glob('*.json')))

    def test_retained_failed_bytes_cannot_be_relabelled_passed(self):
        candidate = self.value['candidate']
        task = jobs.read_json(self.root / 'task/current-task.json')
        failed = self.review()
        failed['checks']['story']['status'] = 'failed'
        failed['checks']['story']['finding'] = 'Synthetic retained failure'
        acceptance.record_review(self.root / 'task', task['authority']['path'], candidate['task_sha256'], 'review-cut', candidate, failed)
        result = self.call('deliver', {'review': self.review(), 'destination': str(self.root / 'failed.mp4')})
        self.assertFalse(result['ok'])
        self.assertIn('retained failure', result['message'])

    def test_concurrent_review_change_before_commit_fails_currentness(self):
        review = self.review()
        original = project.transaction
        def racing(root, expected, request_id, payload, change):
            retained = self.root / 'task/reviews'
            retained.mkdir(exist_ok=True)
            row = {**review, 'reviewer': 'Synthetic concurrent reviewer'}
            jobs.immutable_bytes(retained / (acceptance.fingerprint(row) + '.json'), jobs.canonical(row))
            return original(root, expected, request_id, payload, change)
        with patch.object(project, 'transaction', side_effect=racing):
            result = self.call('deliver', {'review': review, 'destination': str(self.root / 'race.mp4')})
        self.assertEqual(result['code'], 'conflict')
        self.assertFalse(list((self.root / 'deliveries').glob('*.json')))


if __name__ == '__main__':
    unittest.main()
