"""Versioned film documents. Editor transactions never perform engine or media I/O."""
import copy
import json
from pathlib import Path
import re
import shutil
import uuid

import production_jobs as jobs

SCHEMA = 1
STAGES = ('Plan', 'References', 'Storyboard', 'Takes', 'Edit', 'Review')
ROLES = ('identity', 'wardrobe', 'place', 'prop', 'composition', 'keyframe', 'take',
         'dialogue', 'music', 'effects', 'control', 'last-frame')


class ProjectError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def identity(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', value):
        raise ProjectError('invalid-input', 'Invalid stable ID')
    return value


def folder(studio, project):
    return Path(studio).resolve() / 'user' / 'films' / identity(project)


def load(root):
    value = jobs.read_json(Path(root) / 'project.json')
    if value.get('schema') != SCHEMA:
        raise ProjectError('unsupported-version', 'Unsupported project schema; original preserved')
    if value.get('revision') != token(value):
        raise ProjectError('invalid-input', 'Project fingerprint mismatch; original preserved')
    if identity(value.get('id')) != Path(root).name:
        raise ProjectError('invalid-input', 'Project ID differs from its folder; original preserved')
    marker = Path(root) / '.import-intent.json'
    if marker.exists() and value.get('import_request') != jobs.read_json(marker):
        raise ProjectError('busy', 'Collection import is incomplete; retry the original import command before opening')
    return value


def token(value):
    return jobs.digest(jobs.canonical({k: v for k, v in value.items() if k != 'revision'}))


def save(root, value, *, archive=True):
    value['serial'] = value.get('serial', 0) + 1
    value['revision'] = token(value)
    if archive:
        jobs.immutable_bytes(Path(root) / 'history' / (value['revision'] + '.json'), jobs.canonical(value))
    jobs.atomic_json(Path(root) / 'project.json', value)
    return value


def create(studio, request_id, title):
    if not isinstance(title, str) or not title.strip():
        raise ProjectError('invalid-input', 'Give the film a title')
    project = uuid.uuid5(uuid.NAMESPACE_URL, request_id).hex
    root = folder(studio, project)
    root.mkdir(parents=True, exist_ok=True)
    with jobs.locked(root):
        if (root / 'project.json').exists():
            value = load(root)
            if value['creation'] != {'request': request_id, 'title': title}:
                raise ProjectError('conflict', 'Creation request was reused with different content')
            return value
        return save(root, dict(schema=SCHEMA, id=project, title=title, brief='', decisions=[],
                               unresolved=[], creation={'request': request_id, 'title': title},
                               scenes=[], shots=[], assets=[], edit={'fps': '24', 'sample_rate': 48000,
                               'segments': [], 'audio': [], 'markers': [], 'titles': []},
                               undo=[], redo=[], approvals={}, queue=[], cuts=[], selections={},
                               requests={}, stage='Plan', selected_shot=None, paused=True))


def snapshot(root):
    with jobs.locked(root):
        return load(root)


def transaction(root, expected, request_id, payload, change):
    """Intent and result are committed together. Replay precedes revision comparison."""
    identity(request_id)
    digest = jobs.digest(jobs.canonical(payload))
    with jobs.locked(root):
        value = load(root)
        old = value['requests'].get(request_id)
        if old:
            if old['digest'] != digest:
                raise ProjectError('conflict', 'Request ID reused with a different payload')
            return value, old['receipt']
        if value['revision'] != expected:
            raise ProjectError('conflict', 'Film changed in another window or script. Reload and reapply.')
        result = change(value)
        receipt = {'request_id': request_id, 'result': result}
        value['requests'][request_id] = {'digest': digest, 'receipt': receipt}
        save(root, value)
        return value, receipt


def shot(value, shot_id):
    return next((s for s in value['shots'] if s['id'] == shot_id), None) or _missing('shot')


def _missing(label):
    raise ProjectError('invalid-input', 'Select an existing ' + label)


def projection(value, shot_id=None):
    """Library names/order are intentionally outside generation identity."""
    selected = [shot(value, shot_id)] if shot_id else value['shots']
    assets = {a['id']: a for a in value['assets']}
    shots = []
    for item in selected:
        inputs = [{k: v for k, v in item.items() if k not in ('name', 'scene')}]
        for binding in item['references']:
            asset = assets.get(binding['asset']) or _missing('asset')
            inputs.append({'role': binding['role'], 'precedence': binding['precedence'],
                           'sha256': asset['sha256'], 'range': binding.get('range')})
        shots.append(inputs)
    return jobs.digest(jobs.canonical(dict(brief=value['brief'], decisions=value['decisions'],
                                         unresolved=value['unresolved'], shots=shots)))


def edit_token(value):
    return jobs.digest(jobs.canonical(dict(plan=projection(value), edit=value['edit'],
                                         selections=value['selections'])))


def pilot_token(value, timeline):
    ids = {s['id'] for s in timeline['shots']}
    shots = {s.get('shot') for s in timeline['shots'] if s.get('shot')}
    return jobs.digest(jobs.canonical(dict(brief=value['brief'], decisions=value['decisions'], unresolved=value['unresolved'],
                  generations={s: projection(value, s) for s in sorted(shots)},
                  selections={s: value['selections'].get(s) for s in sorted(shots)},
                  segments=[s for s in value['edit']['segments'] if s['id'] in ids],
                  audio=value['edit']['audio'])))


def mutate(value, operation, data):
    if operation == 'plan':
        for key in ('title', 'brief', 'decisions', 'unresolved'):
            if key in data:
                if not isinstance(data[key], list if key in ('decisions', 'unresolved') else str):
                    raise ProjectError('invalid-input', 'Invalid ' + key)
                value[key] = data[key]
    elif operation == 'view':
        if data.get('stage', value['stage']) not in STAGES:
            raise ProjectError('invalid-input', 'Unknown film stage')
        value['stage'] = data.get('stage', value['stage'])
        value['selected_shot'] = data.get('shot', value['selected_shot'])
    elif operation == 'scene-add':
        value['scenes'].append({'id': uuid.uuid4().hex, 'name': data.get('name', 'New scene')})
    elif operation == 'shot-add':
        scene = data.get('scene') or (value['scenes'][0]['id'] if value['scenes'] else None)
        if scene is None:
            scene = uuid.uuid4().hex
            value['scenes'].append({'id': scene, 'name': 'Scene 1'})
        item = dict(id=uuid.uuid4().hex, name=data.get('name', 'New shot'), scene=scene,
                    purpose='', action='', staging='', camera='', start_state='', end_state='',
                    cast=[], place=[], props=[], dialogue='', mode='text', prompt='',
                    edit_frames=120, generation_frames=124, references=[], recipe={})
        value['shots'].append(item)
        value['selected_shot'] = item['id']
        return item['id']
    elif operation in ('shot-update', 'shot-duplicate'):
        item = shot(value, data['shot'])
        if operation == 'shot-duplicate':
            item = copy.deepcopy(item)
            item['id'] = uuid.uuid4().hex
            item['name'] += ' copy'
            value['shots'].insert(value['shots'].index(shot(value, data['shot'])) + 1, item)
            value['selected_shot'] = item['id']
            return item['id']
        allowed = set(item) - {'id'}
        changes = data['changes']
        if set(changes) - allowed:
            raise ProjectError('invalid-input', 'Unknown shot field')
        for key, field in changes.items():
            if type(field) is not type(item[key]):
                raise ProjectError('invalid-input', 'Invalid shot field: ' + key)
        item.update(changes)
        if not 1 <= item['edit_frames'] <= 86400 or item['generation_frames'] < item['edit_frames']:
            raise ProjectError('invalid-input', 'Use positive edit frames within the generated range')
        if item['mode'] not in ('text', 'first-frame', 'last-frame', 'first-last-frame', 'continue', 'voice', 'control'):
            raise ProjectError('invalid-input', 'Unknown generation mode')
        if not any(scene['id'] == item['scene'] for scene in value['scenes']):
            raise ProjectError('invalid-input', 'Shot must belong to an existing scene')
    elif operation in ('shots-reorder', 'scenes-reorder'):
        key = operation.split('-')[0]
        if sorted(data['ids']) != sorted(s['id'] for s in value[key]):
            raise ProjectError('invalid-input', 'Reorder must contain every ID exactly once')
        mapping = {s['id']: s for s in value[key]}
        value[key] = [mapping[i] for i in data['ids']]
    elif operation == 'asset-bind':
        item = shot(value, data['shot'])
        if data['role'] not in ROLES or not any(a['id'] == data['asset'] for a in value['assets']):
            raise ProjectError('invalid-input', 'Unknown reference role or asset')
        binding = {k: data[k] for k in ('asset', 'role', 'precedence')}
        if type(binding['precedence']) is not int or binding['precedence'] < 0:
            raise ProjectError('invalid-input', 'Reference precedence must be a nonnegative integer')
        if 'range' in data:
            binding['range'] = data['range']
        if data['role'] == 'keyframe':
            item['references'] = [r for r in item['references'] if r['role'] != 'keyframe']
        item['references'].append(binding)
        item['references'].sort(key=lambda b: b['precedence'])
    elif operation == 'approve-animatic':
        if not value['shots'] or any(not any(r['role'] == 'keyframe' for r in s['references']) for s in value['shots']):
            raise ProjectError('invalid-input', 'Every shot needs a keyframe before animatic approval')
        if not data.get('reviewer') or not data.get('finding'):
            raise ProjectError('invalid-input', 'Record who inspected the animatic and their finding')
        value['approvals']['animatic'] = dict(token=projection(value), reviewer=data['reviewer'], finding=data['finding'])
    elif operation == 'select':
        item = shot(value, data['shot'])
        asset = next((a for a in value['assets'] if a['id'] == data['asset']), None) or _missing('take')
        start, end = data['in_frame'], data['out_frame']
        if type(start) is not int or type(end) is not int or not 0 <= start < end:
            raise ProjectError('invalid-input', 'Take range must be half-open positive frames')
        if not data.get('reason'):
            raise ProjectError('invalid-input', 'Record the selection reason')
        value['selections'][item['id']] = dict(asset=asset['id'], in_frame=start, out_frame=end,
                                               reason=data['reason'], generation=projection(value, item['id']))
    elif operation == 'pause':
        value['paused'] = bool(data['paused'])
    else:
        raise ProjectError('unknown-operation', operation)
    return {'saved': operation}


def adopt(root, path, role, metadata=None):
    """Copy before the short editor commit. Original receipt/sidecar is never rewritten."""
    source = Path(path).resolve(strict=True)
    if role not in ROLES:
        raise ProjectError('invalid-input', 'Choose an explicit asset role')
    digest = jobs.file_hash(source)
    relative = 'assets/' + digest + source.suffix.lower()
    destination = jobs.confined(root, relative)
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with source.open('rb') as src, destination.open('xb') as dst:
            shutil.copyfileobj(src, dst)
    except FileExistsError:
        pass
    jobs.file_hash(destination, digest)
    jobs.file_hash(source, digest)
    provenance = {'original_path': str(source), 'sha256': digest}
    sidecar = Path(str(source) + '.json')
    if sidecar.exists():
        raw = jobs.checked_bytes(sidecar)
        saved = 'assets/' + jobs.digest(raw) + '.metadata.json'
        jobs.immutable_bytes(jobs.confined(root, saved), raw)
        provenance['sidecar'] = saved
        try:
            settings = json.loads(raw)
        except (ValueError, TypeError):
            settings = None
        if isinstance(settings, dict):
            material = [settings.get(k) for k in ('Source', 'LastFrame', 'AudioGuide', 'GuideVideo')]
            material.extend(r.get('Path') for r in settings.get('References', []) or [] if isinstance(r, dict))
            dependencies = []
            supported = {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tif', '.tiff', '.mp4', '.mov', '.mkv', '.wav', '.flac', '.mp3', '.m4a'}
            for declared in dict.fromkeys(p for p in material if isinstance(p, str) and p):
                dependency = Path(declared)
                if not dependency.is_absolute() or declared.startswith('\\\\') or dependency.suffix.lower() not in supported:
                    dependencies.append({'original_path': declared, 'status': 'unverified unsupported dependency locator'})
                    continue
                if not dependency.is_file():
                    dependencies.append({'original_path': declared, 'status': 'missing source proof; imported media remains unverified'})
                    continue
                content_hash = jobs.file_hash(dependency)
                bound = 'assets/' + content_hash + dependency.suffix.lower()
                target = jobs.confined(root, bound)
                try:
                    with dependency.open('rb') as src, target.open('xb') as dst:
                        shutil.copyfileobj(src, dst)
                except FileExistsError:
                    pass
                jobs.file_hash(target, content_hash)
                jobs.file_hash(dependency, content_hash)
                dependencies.append(dict(original_path=declared, sha256=content_hash, path=bound, status='verified managed copy'))
            provenance['material_bindings'] = dependencies
    return dict(id=uuid.uuid4().hex, name=source.name, role=role, path=relative,
                sha256=digest, provenance=provenance, metadata=metadata or {})


def read_model(value):
    current = projection(value)
    return {**value, 'animatic_current': value['approvals'].get('animatic', {}).get('token') == current,
            'active_projection': edit_token(value),
            'outdated_shots': [s for s, selection in value['selections'].items()
                               if selection['generation'] != projection(value, s)]}
