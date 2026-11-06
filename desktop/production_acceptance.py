"""Production acceptance records; validates evidence integrity, not semantic truth."""
import argparse
from contextlib import nullcontext
from fractions import Fraction
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
from production_jobs import atomic_json, canonical, digest, file_hash, immutable_bytes, locked, read_json


FILM_CHECKS = {
    'technical': ('technical', ['decode'], 'Exact encoded artifact decodes with intended media properties.'),
    'identity': ('experience', ['visual', 'audio'], 'Actual content follows the current accepted story and superseded directions are absent.'),
    'story': ('experience', ['motion', 'audio'], 'Connected causes, actions and consequences are understandable to a viewer.'),
    'motion_audio': ('experience', ['motion', 'audio'], 'Connected action, cuts, character persistence and sound work together.'),
    'performance': ('experience', ['motion', 'audio'], 'Speech, movement, pacing and music communicate the intended emotion naturally.'),
}


def film_requirements():
    rules = {key: {'kind': kind, 'modalities': modes, 'outcome': outcome,
                   'stages': ['scale', 'deliver']}
             for key, (kind, modes, outcome) in FILM_CHECKS.items()}
    rules.update(read_json(Path(__file__).with_name('production_requirements.json')))
    return rules


def fingerprint(value):
    return digest(canonical(value))


def reference(path):
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': file_hash(path)}


def verify(ref):
    if not isinstance(ref, dict) or not Path(ref['path']).is_absolute():
        raise ValueError('Evidence must have an absolute path and SHA-256')
    file_hash(ref['path'], ref['sha256'])
    return Path(ref['path'])


def text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(label + ' must be nonempty text')


def validate_task(task):
    for key in ('task', 'revision', 'goal', 'next_action', 'delivery'):
        text(task.get(key), key)
    if not Path(task['delivery']).is_absolute():
        raise ValueError('delivery must be an absolute intended artifact path')
    for key in ('decisions', 'superseded', 'unresolved', 'rejected_artifacts', 'exceptions', 'reuse'):
        if not isinstance(task.get(key), list):
            raise ValueError(key + ' must be an explicit list')
    if not task['decisions']:
        raise ValueError('At least one accepted decision with a source locator is required')
    for decision in task['decisions']:
        text(decision.get('decision'), 'decision')
        text(decision.get('source'), 'decision source locator')
    verify(task['authority'])
    if task.get('profile') not in ('general', 'narrative-film'):
        raise ValueError('Unknown task profile')
    requirements = task['requirements']
    if not isinstance(requirements, dict) or not requirements:
        raise ValueError('Explicit requirements are required')
    for key, rule in requirements.items():
        text(key, 'requirement id')
        text(rule.get('outcome'), 'observable outcome')
        if rule.get('kind') not in ('technical', 'experience'):
            raise ValueError('Separate technical and experience requirements')
        if not rule.get('modalities') or not set(rule.get('stages', [])).issubset({'scale', 'deliver'}) or not rule.get('stages'):
            raise ValueError('Each requirement needs modalities and scale/deliver stages')
    if not any('deliver' in r['stages'] for r in requirements.values()):
        raise ValueError('Delivery needs requirements')
    if task['profile'] == 'narrative-film':
        for key, required in film_requirements().items():
            rule = requirements.get(key, {})
            if rule.get('kind') != required['kind'] or not set(required['modalities']).issubset(rule.get('modalities', [])) or set(rule.get('stages', [])) != {'scale', 'deliver'}:
                raise ValueError('Missing narrative-film requirement: ' + key)


def record(root, proposal, expected, *, project_locked=False):
    """Compare-and-swap: a stale writer cannot silently replace the current task."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    validate_task(proposal)
    parent = root.parent
    project_scope = locked(parent) if (parent / 'project.json').exists() and not project_locked else nullcontext()
    with project_scope, locked(root):
        path = root / 'current-task.json'
        current = fingerprint(read_json(path)) if path.exists() else 'new'
        if expected != current:
            raise ValueError('Stale task writer; reread and reconcile current-task.json')
        token = fingerprint(proposal)
        immutable_bytes(root / 'history' / (token + '.json'), canonical(proposal))
        atomic_json(path, proposal)
        return token


def cut_frames(candidate):
    timeline = read_json(verify(candidate['timeline']))
    fps = Fraction(str(timeline['fps']))
    if fps <= 0 or not timeline['shots']:
        raise ValueError('Positive fps and nonempty timeline required')
    cursor, cuts, ids = 0, [], set()
    for shot in timeline['shots']:
        start = Fraction(str(shot['start'])) * fps
        end = Fraction(str(shot['end'])) * fps
        if start != cursor or end <= start or end.denominator != 1 or shot['id'] in ids:
            raise ValueError('Timeline must have unique shots contiguous on the frame grid')
        if cursor:
            cuts.append(cursor)
        cursor = int(end)
        ids.add(shot['id'])
    if cursor != timeline['frames']:
        raise ValueError('Timeline frame total mismatch')
    return cuts


def authorized(task, key, artifact_hash):
    for exception in task['exceptions']:
        if exception.get('check') == key and exception.get('artifact_sha256') == artifact_hash:
            verify(exception['source'])
            text(exception.get('quote'), 'user authorization quote')
            text(exception.get('reason'), 'scoped exception reason')
            return exception
    return None


def record_review(root, authority, expected, action, candidate, review, *, project_locked=False):
    parent = Path(root).parent
    project_scope = locked(parent) if (parent / 'project.json').exists() and not project_locked else nullcontext()
    with project_scope, locked(root):
        result = check(root, authority, expected, action, candidate, review)
        immutable_bytes(Path(root) / 'reviews' / (fingerprint(review) + '.json'), canonical(review))
        return result


def check(root, authority, expected, action, candidate=None, review=None):
    """A passing response is a record check at this instant, not release authorization."""
    task = read_json(Path(root) / 'current-task.json')
    validate_task(task)
    token = fingerprint(task)
    if token != expected:
        raise ValueError('Stale task reader; reconcile latest relevant decisions')
    if reference(authority) != task['authority']:
        raise ValueError('Current decision source differs from maintained task')
    report = {'task_sha256': token, 'action': action, 'allowed': True,
              'completion': False, 'issues': [], 'checks': {},
              'limit': 'Record/evidence integrity only; judgments and decision capture require honest capable review.'}
    if action in ('resume', 'status', 'handoff'):
        return report
    if action not in ('scale', 'deliver', 'review-cut'):
        raise ValueError('Unknown action')
    if not candidate or candidate.get('task_sha256') != token:
        raise ValueError('Candidate belongs to a different task revision')
    artifact = verify(candidate['artifact'])
    for dependency in candidate.get('dependencies', []):
        verify(dependency)
    artifact_hash = candidate['artifact']['sha256']
    purpose = 'pilot' if action == 'scale' else 'final'
    if candidate.get('purpose') != purpose:
        raise ValueError('Candidate purpose does not match the gate')
    if action != 'scale' and artifact.resolve() != Path(task['delivery']).resolve():
        raise ValueError('Candidate is not the intended delivery artifact')
    reused = artifact_hash in {r['sha256'] for r in task['rejected_artifacts']}
    if reused:
        permission = next((r for r in task['reuse'] if r.get('sha256') == artifact_hash and action in r.get('actions', [])), None)
        if not permission:
            raise ValueError('Rejected/superseded artifact cannot be relabeled as current work')
        verify(permission['source'])
        text(permission.get('quote'), 'reuse authorization quote')
        if candidate.get('label') != 'authorized-reuse':
            raise ValueError('Authorized reuse must be labeled as reuse')
    stage = 'scale' if action == 'scale' else 'deliver'
    requirements = {k: v for k, v in task['requirements'].items() if stage in v['stages']}
    if not requirements:
        raise ValueError('No requirements defined for this stage')
    if task['profile'] == 'narrative-film':
        cuts = cut_frames(candidate)
        if action == 'scale' and len(cuts) < 2:
            raise ValueError('Representative pilot requires at least three connected shots')
        requirements.update({f'cut:{n}': {'kind': 'experience', 'modalities': ['frame-pair', 'motion', 'audio'],
                                        'outcome': 'Both sides and surrounding action agree with intended staging.'} for n in cuts})
    if review is None:
        review = {'checks': {}}
    elif (review.get('task_sha256') != token or review.get('candidate_sha256') != fingerprint(candidate)
          or review.get('artifact_sha256') != artifact_hash):
        raise ValueError('Review/approval belongs to a different task, edit or artifact revision')
    else:
        text(review.get('reviewer'), 'reviewer identity and capability')
    failures = {}
    for path in (Path(root) / 'reviews').glob('*.json'):
        prior = read_json(path)
        if path.stem != fingerprint(prior):
            raise ValueError('Retained review was modified')
        if prior.get('artifact_sha256') == artifact_hash:
            for key, row in prior['checks'].items():
                if row['status'] == 'failed':
                    failures[key] = row['finding']
    for key, rule in requirements.items():
        row = review['checks'].get(key, {'status': 'unverified', 'finding': 'Required review not supplied'})
        status = row.get('status')
        if status not in ('passed', 'failed', 'unverified'):
            raise ValueError('Invalid review status: ' + key)
        text(row.get('finding'), key + ' finding')
        problems = []
        for evidence in row.get('evidence', []):
            verify(evidence)
        if status == 'passed':
            if not row.get('evidence') or not row.get('method'):
                problems.append('missing evidence/method')
            missing = set(rule['modalities']) - set(row.get('inspected', []))
            if missing:
                problems.append('unverified modalities: ' + ', '.join(sorted(missing)))
            if key.startswith('cut:'):
                frame = int(key.split(':')[1])
                if row.get('frames') != [frame - 1, frame] or not row.get('staging'):
                    problems.append('missing exact cut sides or intended staging')
                for side in ('before', 'after'):
                    if not row.get(side):
                        problems.append('missing ' + side + ' frame evidence')
                    else:
                        verify(row[side])
        effective = 'unverified' if problems else status
        if key in failures:
            effective = 'failed'
            problems.append('retained failure: ' + failures[key])
        exception = authorized(task, key, artifact_hash) if effective != 'passed' else None
        report['checks'][key] = {'status': status, 'effective_status': effective, 'kind': rule['kind'],
                                 'inspected': row.get('inspected', []), 'required': rule['modalities'],
                                 'finding': row['finding'], 'problems': problems, 'exception': exception}
        if effective != 'passed' and not exception:
            report['issues'].append(key + ': ' + effective + ('; ' + '; '.join(problems) if problems else ''))
    if task['unresolved']:
        report['issues'].append('Unresolved requirements: ' + '; '.join(task['unresolved']))
    report['allowed'] = not report['issues'] or action == 'review-cut'
    report['completion'] = action == 'deliver' and not report['issues']
    report['label'] = ('INCOMPLETE REVIEW CUT — not accepted or complete' if action == 'review-cut'
                       else 'records satisfy gate' if report['allowed'] else 'blocked')
    # Catch ordinary concurrent task/evidence edits before returning a decision.
    if fingerprint(read_json(Path(root) / 'current-task.json')) != token or reference(authority) != task['authority']:
        raise ValueError('Task changed during check; reconcile and retry')
    verify(candidate['artifact'])
    for dependency in candidate.get('dependencies', []):
        verify(dependency)
    for row in review['checks'].values():
        for evidence in row.get('evidence', []):
            verify(evidence)
        for side in ('before', 'after'):
            if row.get(side):
                verify(row[side])
    if task['profile'] == 'narrative-film':
        verify(candidate['timeline'])
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('ref', help='Hash a local artifact or evidence file')
    p.add_argument('path')
    p = sub.add_parser('record', help='Maintain one current task; preserve previous revisions')
    p.add_argument('root'); p.add_argument('proposal'); p.add_argument('--expected', required=True)
    p = sub.add_parser('check')
    p.add_argument('root'); p.add_argument('--authority', required=True); p.add_argument('--expected', required=True)
    p.add_argument('--action', required=True, choices=['resume', 'status', 'handoff', 'scale', 'deliver', 'review-cut'])
    p.add_argument('--candidate'); p.add_argument('--review'); p.add_argument('--report')
    p = sub.add_parser('review', help='Retain a revision-bound review, including failed/unverified checks')
    p.add_argument('root'); p.add_argument('--authority', required=True); p.add_argument('--expected', required=True)
    p.add_argument('--action', required=True, choices=['scale', 'deliver'])
    p.add_argument('--candidate', required=True); p.add_argument('--review', required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'ref':
            result = reference(args.path)
        elif args.command == 'record':
            result = {'task_sha256': record(args.root, read_json(args.proposal), args.expected)}
        elif args.command == 'review':
            result = record_review(args.root, args.authority, args.expected, args.action,
                                   read_json(args.candidate), read_json(args.review))
        else:
            result = check(args.root, args.authority, args.expected, args.action,
                           read_json(args.candidate) if args.candidate else None,
                           read_json(args.review) if args.review else None)
            if args.report:
                with Path(args.report).open('xb') as stream:
                    stream.write(canonical(result))
        print(json.dumps(result, indent=2))
        return 0 if result.get('allowed', True) else 1
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({'allowed': False, 'completion': False, 'error': str(exc)}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
