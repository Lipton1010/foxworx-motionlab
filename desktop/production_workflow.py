"""Shared controls used by the film batch and edit entry points. No model lifecycle code."""
import math
from fractions import Fraction
from pathlib import Path

import production_acceptance as acceptance
import production_jobs as jobs
from production_media import validate_media


def context(project, expected, required=()):
    project = Path(project).resolve()
    root = project / 'production'
    if not expected:
        raise ValueError('A current task token is required; reconcile production/task/current-task.json first')
    task_path = root / 'task/current-task.json'
    task = jobs.read_json(task_path)
    acceptance.check(root / 'task', task['authority']['path'], expected, 'resume')
    if task['profile'] != 'narrative-film':
        raise ValueError('Film production requires the narrative-film profile')
    if task['unresolved']:
        raise ValueError('Resolve the current assignment before production: ' + '; '.join(task['unresolved']))
    refs = task['production']['inputs']
    if not refs:
        raise ValueError('Declare the production brief, plan and material inputs')
    for ref in refs:
        acceptance.verify(ref)
    declared = {Path(ref['path']).resolve() for ref in refs}
    if not {Path(p).resolve() for p in required}.issubset(declared):
        raise ValueError('Current task omits a required production input')
    dependencies = [task_path, Path(task['authority']['path'])]
    dependencies += [Path(ref['path']) for ref in refs]
    dependencies += [Path(__file__), Path(acceptance.__file__), Path(__file__).with_name('production_requirements.json')]
    return root, task, list(dict.fromkeys(dependencies))


def gate(project, expected, action, candidate, review):
    root, task, dependencies = context(project, expected)
    declared = {ref['path']: ref['sha256'] for ref in candidate.get('dependencies', [])}
    for path in dependencies:
        ref = acceptance.reference(path)
        if declared.get(ref['path']) != ref['sha256']:
            raise ValueError('Review candidate omits or has stale production context: ' + str(path))
    # Archive a real supplied review even when it fails. A later pass on the same
    # bytes cannot silently erase that failure.
    check = acceptance.record_review if review is not None else acceptance.check
    result = check(root / 'task', task['authority']['path'], expected, action, candidate, review)
    if not result['allowed']:
        raise ValueError('Production blocked: ' + '; '.join(result['issues']))
    return result


def run_batch(project, plan, prepare, *, expected, phase='scale', defect=None, timeout=1800,
              required=()):
    project, plan = Path(project).resolve(), Path(plan).resolve()
    if phase not in ('pilot', 'scale', 'repair'):
        raise ValueError('Unknown production phase')
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('Use a finite positive polling timeout')
    items = jobs.read_json(plan)
    if not isinstance(items, list) or not items:
        raise ValueError('Plan must contain jobs')
    names = [item['name'] for item in items]
    if len(names) != len(set(names)):
        raise ValueError('Duplicate take names in plan')
    for name in names:
        jobs.confined(project / 'jobs', name)
        if len(Path(name).parts) != 1 or '\\' in name:
            raise ValueError('Take names must be single directory names')
    root, task, dependencies = context(project, expected, required)
    plan_ref = acceptance.reference(plan)
    ledger_path = root / 'runs.json'
    results_path = project / 'plans/results.json'
    with jobs.locked(root):
        ledger = jobs.read_json(ledger_path) if ledger_path.exists() else {'jobs': {}, 'repairs': {}}
        for item in items:
            context(project, expected, required)
            acceptance.verify(plan_ref)
            if phase == 'pilot':
                if task['production'].get('pilot_jobs', {}).get(item['name']) != acceptance.fingerprint(item):
                    raise ValueError('Job is outside the explicitly bounded pilot: ' + item['name'])
            else:
                gate(project, expected, 'scale', jobs.read_json(root / 'pilot-candidate.json'),
                     jobs.read_json(root / 'pilot-review.json') if (root / 'pilot-review.json').exists() else None)
            if phase == 'repair':
                limit = task['production'].get('repair_limits', {}).get(defect)
                if type(limit) is not int or limit < 1:
                    raise ValueError('Repair needs a stable defect ID and an explicit positive total budget')
            name = item['name']
            entry = ledger['jobs'].get(name)
            if entry:
                if entry['item_sha256'] != acceptance.fingerprint(item):
                    raise ValueError('Take names are immutable; use a new name for changed settings')
                if entry['phase'] != phase or entry.get('defect') != defect:
                    raise ValueError('Resume the take with its original phase and defect')
                revision = Path(entry['revision'])
            else:
                if (project / 'jobs' / name / 'selected-revision.json').exists():
                    raise ValueError('Historical take exists; inspect/reconcile its saved revision, never resubmit by name: ' + name)
                spent = ledger['repairs'].get(defect, []) if phase == 'repair' else []
                if phase == 'repair' and len(spent) >= limit:
                    raise ValueError('Repair budget exhausted for ' + defect)
                admission = [] if phase == 'pilot' else [root / 'pilot-candidate.json', root / 'pilot-review.json']
                revision = prepare(name, item['kind'], item['settings'], dependencies=dependencies + [plan, *admission])
                ledger['jobs'][name] = {'revision': str(revision), 'item_sha256': acceptance.fingerprint(item),
                                        'phase': phase, 'defect': defect}
                if phase == 'repair':
                    ledger['repairs'].setdefault(defect, []).append(str(revision))
                # Reserve before submission; interruption never refunds a potentially used attempt.
                jobs.atomic_json(ledger_path, ledger)
            before = jobs.status(revision)
            if not before['current']:
                raise ValueError('Saved take has stale inputs; reconcile pending IDs separately and prepare a new take after review')
            context(project, expected, required)
            if phase != 'pilot':
                gate(project, expected, 'scale', jobs.read_json(root / 'pilot-candidate.json'),
                     jobs.read_json(root / 'pilot-review.json'))
            state = jobs.run(revision, timeout=timeout, poll_interval=2, max_attempts=1)
            context(project, expected, required)
            acceptance.verify(plan_ref)
            if state['status'] != 'completed':
                print(name, state['status'], 'batch stopped; saved output selections preserved', flush=True)
                return {'status': state['status'], 'revision': str(revision), 'completion': False}
            current = jobs.status(revision)
            if not current['current'] or current['status'] != 'completed':
                raise ValueError('Completed take changed during validation')
            outputs = current['result']['outputs']
            if len(outputs) != 1:
                raise ValueError('Expected one explicitly selected output')
            results = jobs.read_json(results_path) if results_path.exists() else {}
            results[name] = outputs[0]['path']
            results_path.parent.mkdir(parents=True, exist_ok=True)
            jobs.atomic_json(results_path, results)
            print(name, 'rendered; creative review pending', results[name], flush=True)
    return {'status': 'completed', 'completion': False, 'label': 'rendered, unreviewed'}


def begin_edit(project, destination, expected, timeline, sources, dependencies):
    """Validate exact source ranges before encoding; reserve a new output directory."""
    _, _, required = context(project, expected)
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError('Use a fresh edit directory; existing media is preserved')
    # Validate timeline through the same frame-grid rules used at delivery.
    cursor = 0
    for shot in timeline['shots']:
        if Fraction(str(shot['start'])) * Fraction(str(timeline['fps'])) != cursor:
            raise ValueError('Edit timeline is not contiguous')
        end = Fraction(str(shot['end'])) * Fraction(str(timeline['fps']))
        if end.denominator != 1 or end <= cursor:
            raise ValueError('Edit boundaries must be positive whole frames')
        cursor = int(end)
    if cursor != timeline['frames'] or len(sources) != len(timeline['shots']):
        raise ValueError('Edit sources and timeline disagree')
    refs = [acceptance.reference(path) for path in dict.fromkeys([*required, *map(Path, dependencies)])]
    for shot, source in zip(timeline['shots'], sources):
        start, end = source['in_frame'], source['out_frame_exclusive']
        if type(start) is not int or type(end) is not int or not 0 <= start < end:
            raise ValueError('Invalid source frame interval')
        needed = (Fraction(str(shot['end'])) - Fraction(str(shot['start']))) * Fraction(str(timeline['fps']))
        if end - start != needed:
            raise ValueError('Source range does not match the edit duration')
        media = validate_media(source['path'], {'fps': timeline['fps']})
        video = next((s for s in media['probe']['streams'] if s['codec_type'] == 'video'), {})
        if not media['ok'] or end > int(video.get('nb_read_frames', 0)):
            raise ValueError('Source too short or invalid for ' + shot['id'])
        refs.append({'path': str(Path(source['path']).resolve()), 'sha256': media['sha256']})
    for ref in refs:
        acceptance.verify(ref)
    destination.mkdir(parents=True, exist_ok=False)
    jobs.immutable_bytes(destination / 'timeline.json', jobs.canonical(timeline))
    inputs = {'task_sha256': expected, 'dependencies': refs, 'sources': sources,
              'timeline': acceptance.reference(destination / 'timeline.json')}
    jobs.immutable_bytes(destination / 'edit-inputs.json', jobs.canonical(inputs))
    return inputs


def finish_edit(project, artifact, expected, inputs, media_expected, evidence=()):
    context(project, expected)
    if inputs['task_sha256'] != expected:
        raise ValueError('Edit was started for a different task')
    for ref in inputs['dependencies'] + [inputs['timeline']]:
        acceptance.verify(ref)
    report = validate_media(artifact, media_expected, full_decode=True)
    if not report['ok']:
        raise ValueError('Encoded master failed validation: ' + '; '.join(report['errors']))
    for ref in inputs['dependencies'] + [inputs['timeline']]:
        acceptance.verify(ref)
    folder = Path(artifact).parent
    jobs.immutable_bytes(folder / 'technical-validation.json', jobs.canonical(report))
    candidate = {'task_sha256': expected, 'purpose': 'final', 'label': 'INCOMPLETE REVIEW CUT',
                 'artifact': acceptance.reference(artifact), 'timeline': inputs['timeline'],
                 'dependencies': inputs['dependencies'] + [acceptance.reference(folder / 'edit-inputs.json'),
                                                          acceptance.reference(folder / 'technical-validation.json')]
                                 + [acceptance.reference(p) for p in evidence]}
    jobs.immutable_bytes(folder / 'candidate.json', jobs.canonical(candidate))
    return candidate


def deliver(project, expected, candidate_path, review_path):
    candidate_ref, review_ref = acceptance.reference(candidate_path), acceptance.reference(review_path)
    candidate, review = jobs.read_json(candidate_path), jobs.read_json(review_path)
    result = gate(project, expected, 'deliver', candidate, review)
    acceptance.verify(candidate_ref)
    acceptance.verify(review_ref)
    # Completion is an explicit action over already-reviewed bytes, never an encoding side effect.
    receipt = {'candidate': candidate_ref, 'review': review_ref,
               'artifact': candidate['artifact'], 'result': result}
    root = Path(project) / 'production/deliveries'
    jobs.immutable_bytes(root / (acceptance.fingerprint(receipt) + '.json'), jobs.canonical(receipt))
    return receipt
