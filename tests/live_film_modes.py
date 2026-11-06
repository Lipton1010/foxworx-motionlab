"""Bounded follow-up through packaged JSON interface. No fabricated perceptual approval."""
import copy
import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'desktop'))
import production_jobs as jobs

BASE = ROOT / 'temp/film-implementation/followup-20261105'
STUDIO = BASE / 'studio'
STATE = BASE / 'controller.json'
AUTHORITY = BASE / 'authority.txt'
MODEL = 'minimax_h3_fl2va_pruned_int8_convrot.safetensors'
TERMINAL = {'completed', 'failed', 'rejected', 'cancelled', 'invalid_output', 'lost'}


class Trial:
    def __init__(self):
        (BASE / 'commands').mkdir(parents=True, exist_ok=True)
        self.state = jobs.read_json(STATE) if STATE.exists() else {'cases': {}, 'assets': {}, 'shots': {}}
        self.value = None
        if self.state.get('project'):
            self.call('open', project_id=self.state['project'])

    def save(self):
        jobs.atomic_json(STATE, self.state)

    def call(self, operation, payload=None, project_id=None):
        request = dict(version=1, operation=operation, request_id=uuid.uuid4().hex, payload=payload or {},
                       project_id=project_id or (self.value['id'] if self.value else None),
                       expected_revision=self.value['revision'] if self.value else None)
        pending = BASE / 'pending-command.json'
        if pending.exists():
            raise RuntimeError('Reconcile saved pending-command.json before issuing a different command')
        jobs.atomic_json(pending, request)
        command = [str(STUDIO / 'runtime/production-python/python.exe'), '-u',
                   str(STUDIO / 'desktop/production_service.py'), str(STUDIO)]
        reply = subprocess.run(command, input=json.dumps(request), text=True, encoding='utf-8',
                               capture_output=True, timeout=600, env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
        try:
            result = json.loads(reply.stdout)
        except Exception:
            raise RuntimeError('Helper wait failed; pending request retained for exact replay: ' + reply.stderr)
        jobs.atomic_json(BASE / 'commands' / (request['request_id'] + '.json'), {'request': request, 'reply': result})
        pending.unlink()
        if not result['ok']:
            raise RuntimeError(operation + ': ' + json.dumps(result))
        value = result['result']
        if operation in ('create', 'open'):
            self.value = value
        elif isinstance(value, dict) and 'project' in value:
            self.value = value['project']
        if self.value:
            self.state['project'] = self.value['id']
        self.save()
        return value

    def refresh(self):
        self.call('open')

    def import_asset(self, path, role='keyframe', shot=None, metadata=None):
        self.call('asset-import', dict(path=str(path), role=role, shot=shot, metadata=metadata or {}))
        return self.value['assets'][-1]['id']

    def setup(self):
        if self.state.get('setup_complete'):
            return
        BASE.mkdir(parents=True, exist_ok=True)
        for part in ('app', 'runtime/production-python', 'runtime/media', 'runtime/custom_nodes/image-studio-av'):
            shutil.copytree(ROOT / part, STUDIO / part, dirs_exist_ok=True)
        (STUDIO / 'desktop').mkdir(parents=True, exist_ok=True)
        (STUDIO / 'user').mkdir(parents=True, exist_ok=True)
        for path in (ROOT / 'desktop').glob('production_*'):
            if path.is_file():
                shutil.copy2(path, STUDIO / 'desktop' / path.name)
        for name in ('launch.py', 'Start Image Studio.ps1', 'extra_model_paths.yaml'):
            shutil.copy2(ROOT / name, STUDIO / name)
        jobs.atomic_json(STUDIO / 'user/production-tools.json', dict(model_roots=[str(ROOT / 'models')],
            ffmpeg=str(STUDIO / 'runtime/media/ffmpeg.exe'), ffprobe=str(STUDIO / 'runtime/media/ffprobe.exe')))
        AUTHORITY.write_text('Paul, 2026-11-05: "Close davinci amd run whatever was not run during implementation that is still outstanding". '
            'Follow-up approval: "Allow these two processes to coexist with verification jobs" (current Parsec and Corsair iCUE only). '
            'Bounded verification: three connected five-second generated shots, one last-frame trial, one voice-guide trial, '
            'one selected-latent finish, and one each Extend/Bridge/Fill/Retake pilot; at most ten jobs, one attempt each. '
            'No subjective, listening, story, seam or delivery approval is represented. No weights or other apps are changed.', encoding='utf-8')
        if not self.value:
            self.call('create', {'title': 'FOLLOW-UP VALIDATION — connected H3 modes, not approved film'})
        self.call('plan', dict(brief='A small red wooden ball rolls gently across a plain light wooden tabletop in soft daylight. Locked camera; quiet room, no music. Three connected short shots.',
                              decisions=['Bounded technical pilot and repair validation only; perceptual review remains explicit'], unresolved=[]))
        preview = jobs.read_json(ROOT / 'temp/film-implementation/evidence/live-state.json')[0]['state']['result']['outputs'][0]
        jobs.file_hash(preview['path'], preview['sha256'])
        self.frame(preview['path'], 0, 'initial.png')
        self.frame(preview['path'], 100, 'target.png')
        for name in ('A', 'B', 'C'):
            self.call('shot-add', {'name': 'Connected shot ' + name})
            shot = self.value['selected_shot']; self.state['shots'][name] = shot
            self.call('shot-update', dict(shot=shot, changes=dict(prompt=self.value['brief'], mode='first-frame', edit_frames=120)))
            self.import_asset(BASE / 'initial.png', shot=shot, metadata={'from_preview': preview, 'source_frame': 0})
        self.call('approve-animatic', dict(reviewer='Bounded implementation test',
            finding='Three explicit held source panels and 120-frame shot timings are authorized to bootstrap the technical motion trial only; no generated motion or seam approval.'))
        self.call('direction-record', {'authority': str(AUTHORITY)})
        self.state['setup_complete'] = True
        self.save()

    def frame(self, source, number, filename):
        path = BASE / filename
        if not path.exists():
            self.ffmpeg('-i', source, '-vf', r'select=eq(n\,' + str(number) + ')', '-frames:v', '1', path)
        return path

    def ffmpeg(self, *args):
        subprocess.run([str(STUDIO / 'runtime/media/ffmpeg.exe'), '-nostdin', '-v', 'error', *map(str, args)], check=True, timeout=120)

    def request(self, **extra):
        return dict(Prompt=self.value['brief'], Negative='', Seed=5917600 + len(self.state['cases']), Width=768, Height=448,
                    Seconds=5, Model=MODEL, Loras=[dict(Name='pika_h3_flex_fl2va_comfy_bf16.safetensors', Strength=1, Enabled=True)],
                    Profile='pika-flex', **extra)

    def run_case(self, name, request=None, repair=None, finish=None, shot='A'):
        existing = self.state['cases'].get(name)
        if existing and existing.get('status') in TERMINAL:
            return existing
        if not existing:
            self.refresh()
            if repair:
                proposal = self.call('propose-repair', {**repair, 'shot': self.state['shots'][shot], 'phase': 'pilot',
                    'prompt': self.value['brief'], 'request': self.request(), 'defect': 'verify_' + name})
                binding = jobs.read_json(proposal['item']['repair']['path'])
                if binding['request'].get('LastFrame'):
                    assert proposal['spec']['graph']['last_guide']['inputs']['frame_idx'] == binding['source_out_frame'] - 1
            elif finish:
                task = self.call('task-open')
                self.call('rebind-take', dict(item_id=finish, reviewer='Bounded current-context byte revalidation',
                    source=str(AUTHORITY), task_sha256=task['task_sha256'],
                    finding='Shot inputs, graph/runtime files and output bytes remain unchanged. Only independent exact pilot allowlist entries were added; no performance approval is inferred.'))
                proposal = self.call('propose-finish', dict(preview=finish, width=1280, height=768, interpolate=True))
            else:
                proposal = self.call('propose-take', dict(kind='video', name='verify-' + name,
                    shot=self.state['shots'][shot], phase='pilot', request=request))
            task = self.call('task-open')
            self.call('authorize-pilot-item', dict(item=proposal['item'], reviewer='Paul-authorized bounded follow-up verification',
                source=str(AUTHORITY), task_sha256=task['task_sha256']))
            task = self.call('task-open')
            self.call('enqueue', dict(item=proposal['item'], spec=proposal['spec'], task_sha256=task['task_sha256'],
                engine_input=str(ROOT / 'input'), engine_output=str(ROOT / 'output')))
            existing = {'item_id': self.value['queue'][-1]['id'], 'status': 'queued'}
            self.state['cases'][name] = existing; self.save()
        self.call('pause', {'paused': False})
        row = next(q for q in self.value['queue'] if q['id'] == existing['item_id'])
        permission_path = STUDIO / 'user/gpu-coordinator/coexistence.json'
        permission = jobs.read_json(permission_path)
        permission.setdefault('owners', [])
        if row['owner'] not in permission['owners']:
            permission['owners'].append(row['owner'])
            jobs.atomic_json(permission_path, permission)
        deadline = time.monotonic() + 300
        print('RUN', name, existing['item_id'], flush=True)
        while time.monotonic() < deadline:
            self.call('drive-one')
            row = next(q for q in self.value['queue'] if q['id'] == existing['item_id'])
            existing.update(status=row['status'], revision=row['revision'])
            if row['status'] in TERMINAL:
                if row['status'] == 'completed':
                    existing['output'] = row['state']['result']['outputs'][0]
                    path = existing['output']['path']
                    self.ffmpeg('-i', path, '-f', 'null', '-')
                    existing['full_decode'] = True
                    metadata = row
                    asset = self.import_asset(path, role='take', metadata=metadata)
                    existing['asset'] = asset
                else:
                    existing['state'] = row.get('state')
                self.save(); print('RESULT', name, existing['status'], flush=True)
                return existing
            self.save()
            time.sleep(2)
        self.call('pause', {'paused': True})
        existing['wait_budget_exhausted'] = True; self.save()
        raise RuntimeError('Bounded wait expired; UUID/reservation retained, reconcile before further work')

    def connected(self):
        cases = self.state['cases']
        a = self.run_case('first-frame', self.request(Source=str(BASE / 'initial.png')))
        if a['status'] != 'completed':
            raise RuntimeError('Connected first shot failed; later endpoint inputs cannot be fabricated')
        start_b = self.frame(a['output']['path'], 119, 'start-b.png')
        b = self.run_case('first-last-frame', self.request(Source=str(start_b), LastFrame=str(BASE / 'target.png')), shot='B')
        if b['status'] != 'completed':
            raise RuntimeError('Connected second shot failed')
        start_c = self.frame(b['output']['path'], 119, 'start-c.png')
        c = self.run_case('connected-third', self.request(Source=str(start_c)), shot='C')
        if c['status'] != 'completed':
            raise RuntimeError('Connected third shot failed')
        if not self.state.get('connected_cut'):
            for label, name in (('A', 'first-frame'), ('B', 'first-last-frame'), ('C', 'connected-third')):
                self.call('select', dict(shot=self.state['shots'][label], asset=cases[name]['asset'], in_frame=0, out_frame=120,
                    reason='Exact generated five-second occurrence for technical pilot; quality unverified'))
                self.call('segment-insert', {'segment': dict(asset=cases[name]['asset'], shot=self.state['shots'][label], in_frame=0, out_frame=120)})
            self.call('render-draft', dict(width=768, height=448))
            cut = self.value['cuts'][-1]
            self.call('pilot-candidate', {'sha256': cut['sha256']})
            self.state['connected_cut'] = cut; self.save()
            print('CONNECTED CUT', cut['path'], flush=True)
        self.run_case('last-frame', self.request(LastFrame=str(BASE / 'target.png')))
        self.run_case('voice-guide', self.request(Source=str(BASE / 'initial.png'), AudioGuide=str(BASE / 'voice.wav')))
        self.run_case('finish', finish=b['item_id'], shot='B')

    def repairs(self):
        # Each operation uses its own persisted edit revision and exact real-media anchors.
        for name in ('Extend', 'Bridge', 'Fill', 'Retake'):
            key = 'repair-' + name.lower()
            if self.state['cases'].get(key, {}).get('status') in TERMINAL:
                continue
            assets = self.state['cases']
            edit = copy.deepcopy(self.value['edit'])
            edit['segments'] = [dict(id=uuid.uuid4().hex, asset=assets['first-frame']['asset'], shot=self.state['shots']['A'], in_frame=0, out_frame=120)]
            if name in ('Bridge', 'Fill'):
                edit['segments'] += [dict(id=uuid.uuid4().hex, asset=None, shot=self.state['shots']['B'], in_frame=0, out_frame=24),
                    dict(id=uuid.uuid4().hex, asset=assets['connected-third']['asset'], shot=self.state['shots']['C'], in_frame=0, out_frame=120)]
            self.call('edit-replace', {'edit': edit})
            segment = self.value['edit']['segments'][1 if name in ('Bridge', 'Fill') else 0]
            repair = dict(repair=name, segment=segment['id'], frames=24, modality='both', in_frame=48, out_frame=72)
            result = self.run_case(key, repair=repair)
            if result['status'] == 'completed':
                self.call('place-repair', {'item_id': result['item_id']})
                self.call('render-draft', dict(width=768, height=448))
                result['placed_cut'] = self.value['cuts'][-1]; self.save()


if __name__ == '__main__':
    trial = Trial()
    if sys.argv[1] == 'setup':
        trial.setup()
    elif sys.argv[1] == 'run':
        trial.connected()
        trial.repairs()
        print('All bounded modes attempted; semantic/listening/seam acceptance remains unverified.', flush=True)
    else:
        raise SystemExit('Use setup or run; reconcile pending-command.json before resuming an interrupted helper.')
