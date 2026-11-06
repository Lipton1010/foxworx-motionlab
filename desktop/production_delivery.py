"""Immutable scratch promotion and a current-editor, current-task delivery commit."""
import copy
from pathlib import Path
import shutil

import production_acceptance as acceptance
import production_jobs as jobs
import production_project as project


def failures(root):
    return {p.name: jobs.file_hash(p) for p in (Path(root) / 'task' / 'reviews').glob('*.json')}


def promote(root, request):
    data = request['payload']
    value = project.snapshot(root)
    cut = next((c for c in value['cuts'] if c['sha256'] == data['sha256']), None)
    if not cut or cut['incomplete'] or cut['projection'] != project.edit_token(value):
        raise project.ProjectError('conflict', 'Only a complete cut of the current picture/mix can be promoted')
    if any(s.get('gap') for s in cut['timeline']['shots']):
        raise project.ProjectError('invalid-input', 'Replace every draft gap before intended-final promotion')
    task_path = root / 'task' / 'current-task.json'
    task = jobs.read_json(task_path)
    old_token = acceptance.fingerprint(task)
    if data['task_sha256'] != old_token:
        raise project.ProjectError('conflict', 'Direction changed; reload the current task')
    if task['unresolved'] or value['unresolved']:
        raise project.ProjectError('invalid-input', 'Resolve current direction before final promotion')
    destination = root / 'finals' / request['request_id'] / 'film.mp4'
    source = Path(cut['path'])
    jobs.file_hash(source, cut['sha256'])
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with source.open('rb') as src, destination.open('xb') as dst:
            shutil.copyfileobj(src, dst)
    except FileExistsError:
        pass
    jobs.file_hash(destination, cut['sha256'])
    dependencies = []
    for ref in cut['dependencies']:
        path = jobs.confined(root, ref['path'])
        jobs.file_hash(path, ref['sha256'])
        dependencies.append(acceptance.reference(path))
    projection = dict(edit=copy.deepcopy(value['edit']), selections=copy.deepcopy(value['selections']),
                      active_projection=project.edit_token(value), criteria=task['requirements'])
    projection_path = destination.parent / 'active-edit.json'
    jobs.immutable_bytes(projection_path, jobs.canonical(projection))
    timeline = destination.parent / 'timeline.json'
    jobs.immutable_bytes(timeline, jobs.canonical(cut['timeline']))
    task = copy.deepcopy(task)
    task['delivery'] = str(destination.resolve())
    task['revision'] = request['request_id']
    task['active_projection'] = projection['active_projection']
    task['next_action'] = 'Review exact intended-final picture and mix'
    task['production'].setdefault('inputs', []).append(acceptance.reference(projection_path))
    def change(current):
        if project.edit_token(current) != projection['active_projection']:
            raise project.ProjectError('conflict', 'Edit changed while promoting; bytes retained, no current candidate')
        token = acceptance.record(root / 'task', task, old_token, project_locked=True)
        candidate = dict(task_sha256=token, purpose='final', label='INCOMPLETE REVIEW CUT',
                         active_projection=projection['active_projection'], artifact=acceptance.reference(destination),
                         timeline=acceptance.reference(timeline), dependencies=dependencies + [acceptance.reference(projection_path)])
        candidate['dependencies'].extend(task['production']['inputs'])
        candidate['dependencies'].append(task['authority'])
        jobs.immutable_bytes(destination.parent / 'candidate.json', jobs.canonical(candidate))
        current['candidate'] = candidate
        return candidate
    return project.transaction(root, request['expected_revision'], request['request_id'],
                               {'operation': 'promote', 'payload': data}, change)


def deliver(root, request):
    data = request['payload']
    before = project.snapshot(root)
    candidate = before.get('candidate')
    if not candidate or candidate['active_projection'] != project.edit_token(before):
        raise project.ProjectError('conflict', 'Current edit differs from the intended final. Promote and review the current cut.')
    review = data['review']
    retained = failures(root)
    task = jobs.read_json(root / 'task' / 'current-task.json')
    result = acceptance.check(root / 'task', task['authority']['path'], candidate['task_sha256'], 'deliver', candidate, review)
    if not result['completion']:
        raise project.ProjectError('unverified', '; '.join(result['issues']))
    # Strong verification/copy occurs outside the editor lock; commit rechecks coordinated writers.
    destination = Path(data['destination']).resolve()
    source = acceptance.verify(candidate['artifact'])
    if destination != source:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with source.open('rb') as src, destination.open('xb') as dst:
            shutil.copyfileobj(src, dst)
        jobs.file_hash(destination, candidate['artifact']['sha256'])
    receipt = dict(candidate=candidate, review=review, artifact=acceptance.reference(destination), result=result)
    def change(current):
        if current.get('candidate') != candidate or project.edit_token(current) != candidate['active_projection']:
            raise project.ProjectError('conflict', 'Edit changed before delivery commit; no completion receipt issued')
        with jobs.locked(root / 'task'):
            if acceptance.fingerprint(jobs.read_json(root / 'task' / 'current-task.json')) != candidate['task_sha256'] or failures(root) != retained:
                raise project.ProjectError('conflict', 'Authority or retained review state changed before commit')
            jobs.immutable_bytes(root / 'deliveries' / (request['request_id'] + '.json'), jobs.canonical(receipt))
        current['delivery'] = receipt
        return receipt
    return project.transaction(root, request['expected_revision'], request['request_id'],
                               {'operation': 'deliver', 'payload': data}, change)
