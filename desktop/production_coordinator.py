"""Durable cross-workspace GPU admission. Unknown effects retain their slot."""
import copy
import datetime
from pathlib import Path
import shutil
import subprocess
import os
import json
import uuid

import production_acceptance as acceptance
import production_jobs as jobs
import production_project as project


def coordinator_root(studio):
    root = Path(studio) / 'user' / 'gpu-coordinator'
    root.mkdir(parents=True, exist_ok=True)
    return root


def dispatch(studio, request, transport=None):
    """Mutation request IDs have durable receipts, independent of slot lifetime."""
    operation, data = request['operation'], request['payload']
    if operation == 'gpu-status':
        return command(studio, operation, data, transport)
    request_id = project.identity(request['request_id'])
    root = coordinator_root(studio) / 'requests' / request_id
    root.mkdir(parents=True, exist_ok=True)
    fingerprint = jobs.digest(jobs.canonical({'operation': operation, 'payload': data}))
    with jobs.locked(root):
        path = root / 'receipt.json'
        if path.exists():
            saved = jobs.read_json(path)
            if saved['fingerprint'] != fingerprint:
                raise project.ProjectError('conflict', 'GPU request ID was reused with different content')
            if saved.get('error'):
                raise project.ProjectError(saved['error']['code'], saved['error']['message'])
            return saved.get('result', {'phase': 'accepted_unresolved', 'request_id': request_id,
                                       'message': 'Interrupted command retained; reconcile ownership before a new external effect'})
        receipt = {'fingerprint': fingerprint, 'accepted': True, 'operation': operation, 'payload': data}
        jobs.atomic_json(path, receipt)
        try:
            result = command(studio, operation, data, transport)
        except Exception as exc:
            receipt['error'] = {'code': getattr(exc, 'code', 'busy' if isinstance(exc, RuntimeError) else 'unavailable'), 'message': str(exc)}
            jobs.atomic_json(path, receipt)
            raise project.ProjectError(receipt['error']['code'], str(exc)) from exc
        receipt['result'] = result
        jobs.atomic_json(path, receipt)
        return result


def external_gpu_processes(endpoint, transport, coexistence=None):
    """Do not free or admit over another CUDA process. Diagnostic absence fails closed."""
    stats = transport(endpoint, 'GET', '/system_stats')
    devices = stats.get('devices', [])
    if not any(d.get('type') == 'cuda' for d in devices):
        return []
    executable = shutil.which('nvidia-smi')
    if not executable:
        raise project.ProjectError('unavailable', 'Cannot inspect other GPU processes; NVIDIA diagnostic tool is unavailable')
    result = subprocess.run([executable, '--query-compute-apps=pid', '--format=csv,noheader,nounits'],
                            capture_output=True, text=True, timeout=10,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise project.ProjectError('unavailable', 'Cannot inspect other GPU processes; waiting without unloading models')
    argv = stats.get('system', {}).get('argv', [])
    engine_pid = None
    if '--user-directory' in argv:
        marker = Path(argv[argv.index('--user-directory')+1]).parent / 'logs/server.json'
        if marker.is_file():
            record = jobs.read_json(marker)
            if os.name == 'nt':
                import ctypes
                from ctypes import wintypes
                kernel = ctypes.WinDLL('kernel32', use_last_error=True)
                kernel.OpenProcess.restype = wintypes.HANDLE
                handle = kernel.OpenProcess(0x1000, False, record['pid'])
                if handle:
                    try:
                        times = [wintypes.FILETIME() for _ in range(4)]
                        if kernel.GetProcessTimes(wintypes.HANDLE(handle), *(ctypes.byref(t) for t in times)):
                            created = ((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime) / 10000000 - 11644473600
                            expected = datetime.datetime.fromisoformat(record['started'].replace('Z', '+00:00')).timestamp()
                            if abs(created-expected) < .02:
                                engine_pid = record['pid']
                    finally:
                        kernel.CloseHandle(wintypes.HANDLE(handle))
    candidates = [int(row.strip()) for row in result.stdout.splitlines() if row.strip().isdigit() and int(row.strip()) != engine_pid]
    if not candidates or os.name != 'nt':
        return candidates
    # WDDM reports ordinary desktop graphics as C+G as well. Inspect only module
    # names to distinguish those from CUDA/DirectML contexts; unreadable contexts wait.
    script = r'''
$ErrorActionPreference='Stop'
$inspection=ConvertFrom-Json ([Console]::In.ReadToEnd())
$gpuIds=$inspection.pids
$result=@(foreach($gpuId in $gpuIds){
  try {
    $gpuProcess=Get-Process -Id ([int]$gpuId) -ErrorAction Stop
    $allowed=@($inspection.allowed | Where-Object { $_.pid -eq [int]$gpuId -and
      [string]::Equals($_.executable,$gpuProcess.Path,[StringComparison]::OrdinalIgnoreCase) -and
      $_.started -eq $gpuProcess.StartTime.ToUniversalTime().ToString('o') })
    if($allowed.Count){ @{pid=[int]$gpuId;kind='authorized-coexistence'}; continue }
    $modules=@($gpuProcess.Modules | ForEach-Object ModuleName)
    $compute=@($modules | Where-Object {$_ -match '^(nvcuda|cudart|cublas|torch_cuda|ggml-cuda|onnxruntime_providers_cuda|onnxruntime_providers_dml|DirectML)'})
    @{pid=[int]$gpuId;kind=$(if($compute.Count){'compute-context'}else{'graphics-only'})}
  } catch { @{pid=[int]$gpuId;kind=$(if(Get-Process -Id ([int]$gpuId) -ErrorAction SilentlyContinue){'unknown-context'}else{'gone'})} }
})
ConvertTo-Json -InputObject $result -Compress
'''
    inspection = subprocess.run(['powershell.exe', '-NoProfile', '-Command', script],
                                input=json.dumps(dict(pids=candidates, allowed=(coexistence or {}).get('processes', []))),
                                capture_output=True, text=True, timeout=15,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if inspection.returncode:
        raise project.ProjectError('unavailable', 'Cannot classify Windows GPU contexts; waiting without unloading other work')
    classified = json.loads(inspection.stdout)
    return [row['pid'] for row in classified if row['kind'] in ('compute-context', 'unknown-context')]


def authorized_coexistence(root, owner):
    """An explicit, expiring user exception applies only to exact named admission owners."""
    path = root / 'coexistence.json'
    if not path.exists():
        return None
    permission = jobs.read_json(path)
    if permission.get('schema') != 1:
        raise project.ProjectError('invalid-input', 'Unsupported GPU coexistence permission schema')
    owners = [project.identity(p) for p in permission['owners']]
    if len(owners) > 10:
        raise project.ProjectError('invalid-input', 'Bounded verification coexistence allows at most ten exact admission owners')
    if owner not in owners:
        return None
    expiry = datetime.datetime.fromisoformat(permission['expires_utc'])
    if expiry.tzinfo is None or expiry <= datetime.datetime.now(datetime.timezone.utc):
        return None
    acceptance.verify(permission['authority'])
    for process in permission['processes']:
        if type(process['pid']) is not int or process['pid'] <= 0 or not Path(process['executable']).is_absolute() or not process['started']:
            raise project.ProjectError('invalid-input', 'GPU coexistence requires exact PID, executable and process start time')
    snapshot = root / 'permissions' / (jobs.digest(jobs.canonical(permission)) + '.json')
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    jobs.immutable_bytes(snapshot, jobs.canonical(permission))
    return {**permission, 'permission': acceptance.reference(snapshot)}


def command(studio, operation, data, transport=None):
    root = coordinator_root(studio)
    path = root / 'slot.json'
    transport = transport or jobs.http_json
    if operation == 'gpu-claim':
        owner = project.identity(data['owner'])
        endpoint = jobs.endpoint_url(data.get('endpoint', 'http://127.0.0.1:8193'))
        with jobs.locked(root):
            slot = jobs.read_json(path) if path.exists() else None
            if slot:
                if slot['owner'] == owner and slot.get('intent') == data.get('intent'):
                    if slot['phase'] == 'checking':
                        raise project.ProjectError('busy', 'Admission check was interrupted. Reconcile the engine before releasing this reservation.')
                    return slot
                raise project.ProjectError('busy', 'GPU reserved by ' + slot['owner'] + '; reconcile it before new work')
            slot = dict(owner=owner, endpoint=endpoint, phase='checking', intent=data.get('intent'), prompt_id=data.get('prompt_id'))
            jobs.atomic_json(path, slot)
        try:
            queue = transport(endpoint, 'GET', '/queue')
            if queue.get('queue_running') or queue.get('queue_pending'):
                raise project.ProjectError('busy', 'Engine has external work; waiting without unloading or interrupting it')
            coexistence = authorized_coexistence(root, owner)
            foreign = external_gpu_processes(endpoint, transport, coexistence)
            if foreign:
                raise project.ProjectError('busy', 'Another CUDA or unverified compute context is present (' + ', '.join(map(str, foreign)) + '); waiting without unloading or interrupting it')
        except Exception:
            with jobs.locked(root):
                if jobs.read_json(path) == slot:
                    path.unlink()
            raise
        with jobs.locked(root):
            slot['phase'] = 'admitted'
            if coexistence:
                slot['coexistence'] = coexistence
            jobs.atomic_json(path, slot)
        return slot
    with jobs.locked(root):
        slot = jobs.read_json(path) if path.exists() else None
        if operation == 'gpu-status':
            return slot or {'phase': 'idle'}
        if not slot or slot['owner'] != data.get('owner'):
            raise project.ProjectError('conflict', 'GPU ownership changed; no external action taken')
        if operation == 'gpu-release':
            if slot.get('prompt_id') and not data.get('terminal'):
                raise project.ProjectError('conflict', 'A durable prompt requires terminal reconciliation before release')
            path.unlink()
            return {'phase': 'idle'}
        if operation == 'gpu-submitting':
            if slot['phase'] != 'admitted':
                raise project.ProjectError('conflict', 'Submission already started; reconcile the saved UUID, never POST again')
            slot['prompt_id'] = data['prompt_id']
            slot['payload'] = data['payload']
            slot['phase'] = 'unknown_submission'
            jobs.atomic_json(path, slot)
            return slot
        raise project.ProjectError('unknown-operation', operation)


def film_command(studio, root, request, transport=None):
    if request['operation'] != 'drive-one':
        return _film_command(studio, root, request, transport)
    receipt_root = root / 'commands' / project.identity(request['request_id'])
    receipt_root.mkdir(parents=True, exist_ok=True)
    fingerprint = jobs.digest(jobs.canonical({'operation': request['operation'], 'payload': request['payload']}))
    with jobs.locked(receipt_root):
        path = receipt_root / 'receipt.json'
        if path.exists():
            receipt = jobs.read_json(path)
            if receipt['fingerprint'] != fingerprint:
                raise project.ProjectError('conflict', 'Tick request ID reused with a different payload')
            if receipt.get('error'):
                raise project.ProjectError(receipt['error']['code'], receipt['error']['message'])
            return {'project': project.read_model(project.snapshot(root)), 'receipt': receipt,
                    'status': receipt.get('status', 'accepted_unresolved')}
        receipt = {'fingerprint': fingerprint, 'accepted': True, 'request_id': request['request_id']}
        jobs.atomic_json(path, receipt)
        try:
            result = _film_command(studio, root, request, transport)
        except Exception as exc:
            receipt['error'] = {'code': getattr(exc, 'code', 'busy' if isinstance(exc, RuntimeError) else 'unavailable'), 'message': str(exc)}
            jobs.atomic_json(path, receipt)
            raise project.ProjectError(receipt['error']['code'], str(exc)) from exc
        receipt['status'] = result.get('state', {}).get('status', result.get('status', 'reconciled'))
        jobs.atomic_json(path, receipt)
        return {**result, 'receipt': receipt}


def _film_command(studio, root, request, transport=None):
    operation, data = request['operation'], request['payload']
    value = project.snapshot(root)
    if value['revision'] != request['expected_revision']:
        raise project.ProjectError('conflict', 'Film changed before coordinator intent; reload and reconcile')
    if operation == 'enqueue':
        item = copy.deepcopy(data['item'])
        spec_identity = dict(spec=data['spec'], sources=[acceptance.reference(b['path']) for b in data['spec'].get('inputs', [])],
                             dependencies=[acceptance.reference(p) for p in data['spec'].get('dependencies', [])])
        if item.get('spec_sha256') != acceptance.fingerprint(spec_identity):
            raise project.ProjectError('conflict', 'Graph/input identity differs from the allowlisted item')
        item['shot_token'] = project.projection(value, item['shot'])
        item['animatic_token'] = project.projection(value)
        phase = item.get('phase', 'pilot')
        if phase not in ('keyframe', 'pilot', 'scale', 'repair'):
            raise project.ProjectError('invalid-input', 'Unknown production phase')
        task = jobs.read_json(root / 'task' / 'current-task.json')
        token = acceptance.fingerprint(task)
        acceptance.check(root / 'task', task['authority']['path'], data['task_sha256'], 'resume')
        if task['unresolved'] or value['unresolved']:
            raise project.ProjectError('invalid-input', 'Resolve current direction before GPU admission')
        if phase != 'keyframe' and not project.read_model(value)['animatic_current']:
            raise project.ProjectError('invalid-input', 'Approve the current animatic before motion work')
        fingerprint = acceptance.fingerprint(item)
        if phase in ('keyframe', 'pilot'):
            if task['production'].get('pilot_jobs', {}).get(item['name']) != fingerprint:
                raise project.ProjectError('invalid-input', 'Item is outside the exact pilot/keyframe allowlist: ' + fingerprint)
        else:
            pilot_candidate = data.get('pilot_candidate') or value.get('pilot_candidate')
            pilot_review = data.get('pilot_review') or value.get('pilot_review')
            if not pilot_candidate or pilot_candidate.get('pilot_projection') != project.pilot_token(value, jobs.read_json(acceptance.verify(pilot_candidate['timeline']))):
                raise project.ProjectError('conflict', 'The connected pilot is missing or outdated for the current edit')
            report = acceptance.check(root / 'task', task['authority']['path'], token, 'scale',
                                      pilot_candidate, pilot_review)
            if not report['allowed']:
                raise project.ProjectError('invalid-input', '; '.join(report['issues']))
        projection_path = root / 'projections' / (fingerprint + '.json')
        jobs.immutable_bytes(projection_path, jobs.canonical(item))
        spec = copy.deepcopy(data['spec'])
        spec.setdefault('dependencies', []).extend([str(projection_path), str(root / 'task' / 'current-task.json'), task['authority']['path']])
        spec['dependencies'].extend(str(acceptance.verify(ref)) for ref in task['production']['inputs'])
        revision = jobs.prepare(spec, root / 'jobs', data['engine_input'], data['engine_output'])
        owner = 'film_' + jobs.digest(jobs.canonical({'project': value['id'], 'request': request['request_id']}))[:48]
        entry = dict(id=request['request_id'], owner=owner, item=item, task_sha256=token, revision=str(revision), status='queued')
        def change(current):
            if phase == 'repair':
                defect = item.get('defect')
                budget = task['production'].get('repair_limits', {}).get(defect, 0)
                spent = sum(q['item'].get('defect') == defect for q in current['queue'])
                if not defect or spent >= budget:
                    raise project.ProjectError('invalid-input', 'Repair reservation budget exhausted')
            current['queue'].append(entry)
            return entry
        current, receipt = project.transaction(root, request['expected_revision'], request['request_id'],
                                               {'operation': operation, 'payload': data}, change)
        return dict(project=project.read_model(current), receipt=receipt)
    # A separate bounded tick claim does not prevent any editor transaction.
    tick = coordinator_root(studio) / 'tick'
    tick.mkdir(exist_ok=True)
    with jobs.locked(tick):
        if operation == 'cancel' and not data.get('item_id'):
            raise project.ProjectError('invalid-input', 'Targeted cancellation requires the explicit owned queue item ID')
        active = next((q for q in value['queue'] if q['status'] not in ('completed', 'cancelled', 'failed', 'rejected', 'invalid_output')
                       and (operation != 'cancel' or q['id'] == data['item_id'])), None)
        if not active:
            return {'status': 'idle'}
        if operation == 'cancel' and active['status'] == 'queued':
            def cancel_queued(current):
                row = next(q for q in current['queue'] if q['id'] == active['id'])
                if row['status'] != 'queued':
                    raise project.ProjectError('conflict', 'Item was already admitted; reload before targeted cancellation')
                row['status'] = 'cancelled'
                return {'status': 'cancelled', 'item_id': row['id'], 'submitted': False}
            current, receipt = project.transaction(root, request['expected_revision'], request['request_id'],
                {'operation': operation, 'payload': data}, cancel_queued)
            owner = active.get('owner', value['id'] + '_' + active['id'])
            slot = command(studio, 'gpu-status', {})
            if slot.get('owner') == owner and slot.get('phase') in ('checking', 'admitted'):
                command(studio, 'gpu-release', {'owner': owner})
            return {'project': project.read_model(current), 'receipt': receipt}
        if active['status'] == 'queued' and value['paused']:
            return {'status': 'paused', 'message': 'Pause blocks the next persisted admission'}
        owner = active.get('owner', value['id'] + '_' + active['id'])
        slotpath = coordinator_root(studio) / 'slot.json'
        endpoint = data.get('endpoint', 'http://127.0.0.1:8193')
        if active['status'] == 'queued':
            if active['item']['shot_token'] != project.projection(value, active['item']['shot']):
                raise project.ProjectError('conflict', 'Queued shot inputs are outdated')
            if active['item']['phase'] != 'keyframe' and active['item']['animatic_token'] != project.projection(value):
                raise project.ProjectError('conflict', 'Queued animatic is outdated')
            task = jobs.read_json(root / 'task' / 'current-task.json')
            if acceptance.fingerprint(task) != active['task_sha256']:
                raise project.ProjectError('conflict', 'Queued authority is outdated')
            admission = command(studio, 'gpu-claim', dict(owner=owner, endpoint=endpoint, intent=active['revision']), transport)
            with jobs.locked(root):
                current = project.load(root)
                if current['paused']:
                    paused = True
                    stale = False
                else:
                    paused = False
                    row = next(q for q in current['queue'] if q['id'] == active['id'])
                    stale = (current['revision'] != value['revision']
                             or row['item']['shot_token'] != project.projection(current, row['item']['shot'])
                             or row['item']['phase'] != 'keyframe' and row['item']['animatic_token'] != project.projection(current)
                             or row['task_sha256'] != acceptance.fingerprint(jobs.read_json(root / 'task/current-task.json')))
                    if not stale:
                        row['status'] = 'admitted'
                        if admission.get('coexistence'):
                            row['gpu_coexistence'] = admission['coexistence']
                        project.save(root, current)
            if paused or stale:
                command(studio, 'gpu-release', dict(owner=owner))
                if stale:
                    raise project.ProjectError('conflict', 'Shot/animatic changed before the persisted admission point')
                return {'status': 'paused'}
        else:
            with jobs.locked(coordinator_root(studio)):
                slot = jobs.read_json(slotpath) if slotpath.exists() else None
                if not slot or slot['owner'] != owner:
                    raise project.ProjectError('conflict', 'Recover original coordinator ownership before reconciling')
        if operation == 'cancel':
            state_path = Path(active['revision']) / 'state.json'
            if not state_path.exists():
                raise project.ProjectError('busy', 'This admission has not persisted an engine UUID yet. Pause future work and reconcile the admitted item before targeted cancellation.')
            state = jobs.read_json(state_path)
            prompt = state['attempts'][-1]['id']
            endpoint = state['endpoint']
            def cancel_intent(current):
                current['paused'] = True
                current.setdefault('cancel_intents', []).append(dict(request_id=request['request_id'], item_id=active['id'], prompt_id=prompt))
                return {'status': 'cancel-requested', 'item_id': active['id'], 'prompt_id': prompt,
                        'note': 'Accepted targeted intent; final outcome requires queue/history reconciliation'}
            accepted, receipt = project.transaction(root, request['expected_revision'], request['request_id'],
                {'operation': operation, 'payload': data}, cancel_intent)
            try:
                reply = (transport or jobs.http_json)(endpoint, 'POST', '/api/jobs/' + prompt + '/cancel', {})
            except Exception as exc:
                raise project.ProjectError('unsupported', 'Targeted cancellation unavailable; pause future work. ' + str(exc))
            return {'project': project.read_model(accepted), 'receipt': receipt,
                    'status': 'cancel-requested' if reply.get('cancelled') else 'reconciling', 'reply': reply}
        # timeout=0 and one persisted attempt mean a tick admits at most one job.
        state_path = Path(active['revision']) / 'state.json'
        reconcile = state_path.exists() and bool(jobs.read_json(state_path)['attempts'])
        try:
            state = jobs.run(active['revision'], endpoint=endpoint, timeout=0, poll_interval=0, max_attempts=1,
                             transport=transport, reconcile_only=reconcile)
        except Exception:
            # No durable UUID means the runner could not have POSTed. Retain the failed reservation, release only its unused GPU slot.
            if not state_path.exists():
                with jobs.locked(root):
                    current = project.load(root)
                    row = next(q for q in current['queue'] if q['id'] == active['id'])
                    row['status'] = 'rejected'; current['paused'] = True
                    project.save(root, current)
                command(studio, 'gpu-release', dict(owner=owner))
            raise
        with jobs.locked(root):
            current = project.load(root)
            row = next(q for q in current['queue'] if q['id'] == active['id'])
            changed = row['status'] != state['status'] or row.get('state') != state
            if changed:
                row['status'] = state['status']; row['state'] = state
                if state['status'] in ('failed', 'rejected', 'invalid_output', 'lost', 'unknown_submission'):
                    current['paused'] = True
                project.save(root, current, archive=state['status'] in ('completed', 'cancelled', 'failed', 'rejected', 'invalid_output'))
        if state['status'] in ('completed', 'cancelled', 'rejected', 'failed', 'invalid_output'):
            command(studio, 'gpu-release', dict(owner=owner, terminal=True))
        return {'project': project.read_model(current), 'state': state}
