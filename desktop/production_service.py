"""One JSON request/reply on stdio. Shared native UI / CLI film interface."""
import copy
from fractions import Fraction
import json
from pathlib import Path
import shutil
import sys
import uuid

# Embedded Python uses an isolated ._pth; explicitly load packaged sibling owners.
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.dont_write_bytecode = True
import production_acceptance as acceptance
import production_edit as edit
import production_jobs as jobs
import production_project as project

PROTOCOL = 1


def tools(studio):
    settings = Path(studio) / 'user' / 'production-tools.json'
    configured = jobs.read_json(settings) if settings.exists() else {}
    result = {}
    for name in ('ffmpeg', 'ffprobe'):
        candidates = [configured.get(name), str(Path(studio) / 'runtime' / 'media' / (name + '.exe'))]
        candidates.append(shutil.which(name))
        result[name] = next((p for p in candidates if p and Path(p).is_file()), None)
    return result


def handle(studio, request):
    if request.get('version') != PROTOCOL:
        raise project.ProjectError('unsupported-version', 'Expected production protocol 1')
    operation = request.get('operation')
    data = request.get('payload', {})
    request_id = project.identity(request.get('request_id'))
    if not isinstance(data, dict):
        raise project.ProjectError('invalid-input', 'Payload must be an object')
    studio = Path(studio).resolve()
    if operation == 'readiness':
        return dict(tools=tools(studio), engine='Not contacted', gpu='Not claimed',
                    reference_validation=jobs.read_json(Path(__file__).with_name('production_capabilities.json')),
                    capabilities={'text': 'Requires verified graph/runtime/model',
                                  'first-frame': 'Reference execution/full decode verified; actual shot review required',
                                  'first-last-frame': 'Reference execution/full decode verified; actual shot review required',
                                  'last-frame': 'Reference execution/full decode verified; actual shot review required',
                                  'continue': 'Reference Extend execution/placement verified; seam quality unverified',
                                  'voice': 'Reference guide execution verified; independent wording diagnostic failed; listening required',
                                  'control': 'No verified film-interface graph/conditioning route',
                                  'ref2va': 'Compatible checkpoint not verified',
                                  'finish': 'Reference preview / interpolated two-step AV finish and restart decode verified; current recipe and performance still require inspection'})
    if operation == 'requirements':
        return acceptance.film_requirements()
    if operation == 'list':
        rows = []
        for path in (studio / 'user' / 'films').glob('*/project.json'):
            try:
                value = project.snapshot(path.parent)
                rows.append(dict(id=value['id'], title=value['title'], revision=value['revision'], shots=len(value['shots'])))
            except (ValueError, OSError, KeyError) as exc:
                rows.append(dict(id=path.parent.name, title='Unreadable project — original preserved', error=str(exc)))
        return rows
    if operation == 'create':
        return project.read_model(project.create(studio, request_id, data['title']))
    if operation == 'import-collection':
        manifest_path = Path(data['manifest']).resolve(strict=True)
        manifest = jobs.read_json(manifest_path)
        project_id = project.identity(manifest['project'])
        source_root = manifest_path.parent / 'user' / 'films' / project_id
        target = project.folder(studio, project_id)
        intent = dict(request_id=request_id, manifest_sha256=jobs.file_hash(manifest_path), source=str(source_root))
        if target.exists():
            prior = target / '.import-intent.json'
            if not prior.exists() or jobs.read_json(prior) != intent:
                raise project.ProjectError('conflict', 'A project with this stable ID already exists. It was preserved; import into a different Image Studio installation.')
            if (target / 'project.json').exists():
                existing = jobs.read_json(target / 'project.json')
                if existing.get('import_request') == intent:
                    return project.read_model(project.snapshot(target))
        target.mkdir(parents=True, exist_ok=True)
        jobs.immutable_bytes(target / '.import-intent.json', jobs.canonical(intent))
        # Verify original manifests before rebinding current display paths. Historical receipts stay byte-identical.
        for ref in manifest['files']:
            source = jobs.confined(source_root, ref['path'])
            jobs.file_hash(source, ref['sha256'])
            if ref['path'] == '.import-intent.json':
                continue
            destination = jobs.confined(target, ref['path'])
            destination.parent.mkdir(parents=True, exist_ok=True)
            try:
                with source.open('rb') as src, destination.open('xb') as dst:
                    shutil.copyfileobj(src, dst)
            except FileExistsError:
                pass
            jobs.file_hash(destination, ref['sha256'])
        imported = jobs.read_json(target / 'project.json')
        if imported['revision'] != project.token(imported) or imported['id'] != project_id:
            raise project.ProjectError('invalid-input', 'Collected project metadata is corrupt; partial import retained')
        old_roots = [Path(manifest['original_root']), *[Path(p) for p in manifest.get('bindings', {}).values()]]
        for cut in imported['cuts']:
            for old in old_roots:
                if Path(cut['path']).is_relative_to(old):
                    path = jobs.confined(target, Path(cut['path']).relative_to(old))
                    jobs.file_hash(path, cut['sha256'])
                    cut['original_path'] = cut['path']; cut['path'] = str(path)
                    break
        for row in imported['queue']:
            for old in old_roots:
                if Path(row['revision']).is_relative_to(old):
                    row['original_revision_path'] = row['revision']
                    row['revision'] = str(jobs.confined(target, Path(row['revision']).relative_to(old)))
                    break
        if 'candidate' in imported:
            imported.setdefault('historical_candidates', []).append(imported.pop('candidate'))
        imported['import_request'] = intent
        manifest_copy = target / 'collection-provenance' / (intent['manifest_sha256'] + '.json')
        jobs.immutable_bytes(manifest_copy, jobs.checked_bytes(manifest_path, intent['manifest_sha256']))
        imported['relocation'] = dict(original_root=manifest['original_root'], current_root=str(target),
                                      source_manifest=acceptance.reference(manifest_copy),
                                      note='Managed bytes verified; record current authority and revalidate ranges before production or delivery')
        with jobs.locked(target):
            project.save(target, imported)
        return project.read_model(imported)
    if operation.startswith('gpu-'):
        import production_coordinator as coordinator
        return coordinator.dispatch(studio, request)
    root = project.folder(studio, request.get('project_id'))
    if operation == 'open':
        return project.read_model(project.snapshot(root))
    if operation == 'projection':
        value = project.snapshot(root)
        return edit.flatten(value['edit'])
    if operation == 'media-inspect':
        value = project.snapshot(root)
        asset = next((a for a in value['assets'] if a['id'] == data['asset']), None)
        if not asset:
            raise project.ProjectError('invalid-input', 'Select a managed media asset')
        source = jobs.confined(root, asset['path'])
        jobs.file_hash(source, asset['sha256'])
        paths = tools(studio)
        if not all(paths.values()):
            raise project.ProjectError('unavailable', 'Configure FFmpeg and FFprobe for lazy media inspection')
        cached = root / 'display-cache' / asset['sha256']
        cached.mkdir(parents=True, exist_ok=True)
        info = edit.probe(source, paths['ffprobe'])
        result = {'probe': info, 'asset_sha256': asset['sha256']}
        if data.get('metadata_only'):
            video = next((s for s in info['streams'] if s.get('codec_type') == 'video'), None)
            result['frame_rate'] = video.get('avg_frame_rate') if video else None
            result['duration'] = float((video or {}).get('duration', info.get('format', {}).get('duration', 0)))
            result['frames'] = (int(video['nb_frames']) if video.get('nb_frames', '').isdigit()
                                else edit.validate_cfr(source, Fraction(result['frame_rate']), paths['ffprobe'])) if video else None
            return result
        if any(s.get('codec_type') == 'video' for s in info['streams']):
            strip = cached / 'filmstrip.png'
            if not strip.exists():
                edit.run([paths['ffmpeg'], '-nostdin', '-v', 'error', '-i', source, '-vf',
                          'fps=1,scale=120:68:force_original_aspect_ratio=decrease,pad=120:68:(ow-iw)/2:(oh-ih)/2,tile=8x1',
                          '-frames:v', '1', strip], 60)
            result['filmstrip'] = str(strip)
        if any(s.get('codec_type') == 'audio' for s in info['streams']):
            waveform = cached / 'waveform.png'
            if not waveform.exists():
                edit.run([paths['ffmpeg'], '-nostdin', '-v', 'error', '-i', source, '-filter_complex',
                          'aformat=channel_layouts=mono,showwavespic=s=960x100:colors=0x8ab8ff', '-frames:v', '1', waveform], 60)
            result['waveform'] = str(waveform)
        return result
    if operation == 'requirements':
        return acceptance.film_requirements()
    if operation == 'task-open':
        task = jobs.read_json(root / 'task' / 'current-task.json')
        return {'task': task, 'task_sha256': acceptance.fingerprint(task)}
    if operation == 'review-state':
        value = project.snapshot(root)
        purpose = data.get('purpose', 'final')
        candidate = value.get('pilot_candidate' if purpose == 'pilot' else 'candidate')
        if not candidate:
            raise project.ProjectError('invalid-input', 'Promote a current complete cut before final review')
        task = jobs.read_json(root / 'task/current-task.json')
        rules = copy.deepcopy(task['requirements'])
        for frame in acceptance.cut_frames(candidate):
            rules['cut:' + str(frame)] = dict(kind='experience', modalities=['frame-pair', 'motion', 'audio'],
                                             outcome='Inspect both sides and surrounding action of cut ' + str(frame))
        return {'candidate': candidate, 'requirements': rules, 'review': value.get('pilot_review' if purpose == 'pilot' else 'review')}
    if operation == 'graph-prepare':
        import production_render as render
        return render.graph(studio, data)
    if operation == 'propose-take':
        import production_render as render
        value = project.snapshot(root)
        prepared = copy.deepcopy(data)
        prepared['environment'] = {'status': 'inspection pending'}
        prepared['request']['PersistAV'] = data.get('kind') == 'video'
        prepared['request']['RuntimeIdentity'] = '{"status":"inspection pending"}'
        spec = render.graph(studio, prepared)
        environment = render.inspect_runtime(studio, spec['graph'])
        if data.get('kind') == 'video':
            prepared['request']['PersistAV'] = True
            prepared['request']['RuntimeIdentity'] = json.dumps(environment, sort_keys=True)
        prepared['environment'] = environment
        spec = render.graph(studio, prepared)
        spec['dependencies'].extend(m['path'] for m in environment['models'] + environment['code'])
        identity = dict(spec=spec, sources=[acceptance.reference(b['path']) for b in spec.get('inputs', [])],
                        dependencies=[acceptance.reference(p) for p in spec['dependencies']])
        item = dict(name=data['name'], shot=data['shot'], phase=data['phase'], kind=data['kind'],
                    spec_sha256=acceptance.fingerprint(identity), shot_token=project.projection(value, data['shot']),
                    animatic_token=project.projection(value))
        if data.get('repair'):
            item['repair'] = data['repair']
            item['defect'] = data['defect']
        return {'item': item, 'spec': spec, 'fingerprint': acceptance.fingerprint(item)}
    if operation == 'propose-repair':
        import production_repair as repair
        value = project.snapshot(root)
        paths = tools(studio)
        if not all(paths.values()):
            raise project.ProjectError('unavailable', 'Configure FFmpeg / FFprobe before binding real repair anchors')
        record = repair.prepare(root, value, data, paths)
        locator = root / 'repair-inputs' / record['id'] / 'repair.json'
        proposal = dict(kind='video', request=record['request'], name='repair-' + request_id, shot=data['shot'],
                        phase=data.get('phase', 'pilot'), defect=data['defect'], repair=acceptance.reference(locator),
                        dependencies=[str(locator)])
        return handle(studio, {**request, 'operation': 'propose-take', 'payload': proposal})
    if operation == 'propose-finish':
        value = project.snapshot(root)
        queued = next((q for q in value['queue'] if q['id'] == data['preview']), None)
        if not queued or queued['status'] != 'completed':
            raise project.ProjectError('invalid-input', 'Choose a completed persisted preview')
        state = jobs.status(queued['revision'])
        rebound = queued.get('rebindings', [])
        valid_binding = (bool(rebound) and rebound[-1]['shot_token'] == project.projection(value, queued['item']['shot'])
                         and rebound[-1]['task_sha256'] == acceptance.fingerprint(jobs.read_json(root / 'task/current-task.json')))
        if (not state['current'] and not valid_binding) or state['status'] != 'completed':
            raise project.ProjectError('conflict', 'Preview context is outdated')
        if valid_binding:
            acceptance.verify(rebound[-1]['proof'])
        companion = state['result'].get('auxiliary', [])
        if len(companion) != 1:
            raise project.ProjectError('unavailable', 'Preview has no typed AV companion; it cannot be finished by latent reuse')
        spec = jobs.load_revision(queued['revision'])['spec']
        graph = spec['graph']
        if graph.get('sampler', {}).get('inputs', {}).get('sampler_name') != 'lcm':
            raise project.ProjectError('unsupported', 'Only the installed Pika Flex preview recipe has an explicit refinement schedule')
        inputs = graph['conditioning']['inputs']
        runtime = graph['save_av']['inputs']['runtime_identity']
        request_data = dict(Prompt=inputs['prompt'], Negative='', Seed=graph['noise']['inputs']['noise_seed'],
                            Width=data.get('width', 1280), Height=data.get('height', 768), Seconds=max(1, min(10, (inputs['length']-1)//24)),
                            Model=graph['model']['inputs']['unet_name'],
                            Loras=[dict(Name='pika_h3_flex_fl2va_comfy_bf16.safetensors', Strength=1, Enabled=True)],
                            Profile='refine', LatentFile=companion[0]['path'], LatentSha256=companion[0]['sha256'],
                            LatentRuntimeIdentity=runtime, RuntimeIdentity=runtime, InterpolateFinish=data.get('interpolate', True))
        fields = {('image', 'image'): 'Source', ('last_image', 'image'): 'LastFrame', ('guide_audio', 'audio'): 'AudioGuide'}
        for binding in spec.get('inputs', []):
            field = fields.get((binding['node'], binding['field']))
            if field:
                request_data[field] = binding['path']
        if 'last_guide' in graph:
            request_data['LastFrameAt'] = graph['last_guide']['inputs']['frame_idx']
        prepared = dict(kind='video', shot=queued['item']['shot'], phase='pilot', name='finish-' + request_id,
                        request=request_data, preview_revision=queued['revision'])
        return handle(studio, {**request, 'operation': 'propose-take', 'payload': prepared})
    # Check replay before expensive imports/renders or expected-revision checks.
    current = project.snapshot(root)
    prior = current['requests'].get(request_id)
    payload_digest = jobs.digest(jobs.canonical({'operation': operation, 'payload': data}))
    if prior:
        if prior['digest'] != payload_digest:
            raise project.ProjectError('conflict', 'Request ID reused with different content')
        return {'project': project.read_model(current), 'receipt': prior['receipt']}
    if (root / 'commands' / request_id / 'receipt.json').exists():
        if operation != 'drive-one':
            raise project.ProjectError('conflict', 'Request ID was already used by a coordinator tick')
        import production_coordinator as coordinator
        return coordinator.film_command(studio, root, request)
    if current['revision'] != request.get('expected_revision'):
        raise project.ProjectError('conflict', 'Film changed. Reload and reapply your edits.')
    if operation == 'collect':
        if any(q['status'] not in ('completed', 'cancelled', 'rejected', 'failed') for q in current['queue']):
            raise project.ProjectError('conflict', 'Pending/unknown jobs must reconcile with their original engine before collection')
        destination = Path(data['destination']).resolve()
        if destination.exists():
            raise project.ProjectError('conflict', 'Collect into a fresh directory; existing data is preserved')
        if destination.is_relative_to(root) or root.is_relative_to(destination):
            raise project.ProjectError('invalid-input', 'Collection must be outside the source project')
        target = destination / 'user' / 'films' / current['id']
        files = []
        for source in root.rglob('*'):
            if not source.is_file() or source.name in ('.lock', '.import-intent.json'):
                continue
            relative = source.relative_to(root)
            digest = jobs.file_hash(source)
            copied = jobs.confined(target, relative)
            copied.parent.mkdir(parents=True, exist_ok=True)
            with source.open('rb') as src, copied.open('xb') as dst:
                shutil.copyfileobj(src, dst)
            jobs.file_hash(copied, digest)
            files.append({'path': str(relative), 'sha256': digest})
        if project.snapshot(root)['revision'] != current['revision']:
            raise project.ProjectError('conflict', 'Project changed during collection; partial copy retained, not validated')
        relocated = copy.deepcopy(current)
        for cut in relocated['cuts']:
            old_path = Path(cut['path'])
            if old_path.is_relative_to(root):
                new_path = jobs.confined(target, old_path.relative_to(root))
                jobs.file_hash(new_path, cut['sha256'])
                cut['original_path'] = cut['path']
                cut['path'] = str(new_path)
        relocated['relocation'] = dict(original_root=str(root), source_revision=current['revision'],
                                       note='Historical approvals preserved; current final candidate must be rebound and reviewed')
        if 'candidate' in relocated:
            relocated.setdefault('historical_candidates', []).append(relocated.pop('candidate'))
        project.save(target, relocated)
        files = [f for f in files if Path(f['path']).as_posix() != 'project.json']
        files.append({'path': 'project.json', 'sha256': jobs.file_hash(target / 'project.json')})
        # Original byte manifest is retained separately from the explicit new current binding.
        manifest = {'schema': 1, 'project': current['id'], 'source_revision': current['revision'], 'files': files,
                    'relocated_revision': relocated['revision'],
                    'original_root': str(root), 'bindings': {str(root): str(target)},
                    'approval': 'Historical only. Revalidate current authority and ranges after relocation.'}
        jobs.immutable_bytes(destination / 'collection.json', jobs.canonical(manifest))
        return {'collection': manifest, 'path': str(destination)}
    if operation == 'repair-budget':
        defect = project.identity(data['defect'])
        limit = edit.integer(data['limit'], 'Total repair budget', 1)
        if limit > 5:
            raise project.ProjectError('invalid-input', 'Use an explicit bounded total repair budget of 1–5 items')
        spent = sum(q['item'].get('defect') == defect and q['item']['phase'] == 'repair' for q in current['queue'])
        if limit < spent:
            raise project.ProjectError('conflict', 'Reserved repairs already exceed that total budget; reservations cannot be refunded')
        task = jobs.read_json(root / 'task/current-task.json')
        token = acceptance.fingerprint(task)
        permission = dict(defect=defect, total=limit, reviewer=data['reviewer'], source=acceptance.reference(data['source']),
                          action='User explicitly assigned this total defect budget in Films')
        locator = root / 'authority' / (request_id + '.repair-budget.json')
        jobs.immutable_bytes(locator, jobs.canonical(permission))
        task['production']['repair_limits'][defect] = limit
        task['decisions'].append(dict(decision='Assign total repair budget ' + str(limit) + ' to ' + defect, source=str(locator), kind='bounded-admission'))
        def change(value):
            value['task_sha256'] = acceptance.record(root / 'task', task, token, project_locked=True)
            return permission
    elif operation == 'place-repair':
        import production_repair as repair
        row = next((q for q in current['queue'] if q['id'] == data['item_id']), None)
        if not row or row['status'] != 'completed' or not row['item'].get('repair'):
            raise project.ProjectError('invalid-input', 'Select a completed repair take')
        if row['item']['shot_token'] != project.projection(current, row['item']['shot']):
            raise project.ProjectError('conflict', 'Repair shot inputs changed; preserve this result as historical')
        binding = jobs.read_json(acceptance.verify(row['item']['repair']))
        revision = jobs.load_revision(row['revision'])
        state = jobs.read_json(Path(row['revision']) / 'state.json')
        jobs.validate_result(row['revision'], state['result'], revision, state['attempts'][-1])
        asset = project.adopt(root, state['result']['outputs'][0]['path'], 'take', row)
        info = edit.probe(jobs.confined(root, asset['path']), tools(studio)['ffprobe'])
        video = next((s for s in info['streams'] if s['codec_type'] == 'video'), None)
        if not video or float(video.get('duration', info['format'].get('duration', 0))) * 24 + .01 < binding['source_out_frame']:
            raise project.ProjectError('invalid-input', 'Completed repair is shorter than its declared trimmed source range')
        def change(value):
            result = repair.place(value, binding, asset['id'])
            value['assets'].append(asset)
            return result
    elif operation == 'rebind-take':
        queued = next((q for q in current['queue'] if q['id'] == data['item_id']), None)
        if not queued or queued['status'] != 'completed':
            raise project.ProjectError('invalid-input', 'Select an existing completed take for explicit rebinding')
        if not data.get('reviewer') or not data.get('finding'):
            raise project.ProjectError('invalid-input', 'Current-context rebinding needs reviewer and an explicit finding')
        source = acceptance.reference(data['source'])
        if queued['item']['shot_token'] != project.projection(current, queued['item']['shot']):
            raise project.ProjectError('conflict', 'Shot generation inputs changed; rebinding cannot manufacture currentness')
        record = jobs.load_revision(queued['revision'])
        state = jobs.read_json(Path(queued['revision']) / 'state.json')
        jobs.validate_result(queued['revision'], state['result'], record, state['attempts'][-1])
        if record['implementation_sha256'] != jobs.implementation_hash():
            raise project.ProjectError('conflict', 'Runner changed; inspect and migrate the receipt explicitly')
        for ref in record['sources']:
            if Path(ref['path']).resolve() != (root / 'task/current-task.json').resolve():
                jobs.file_hash(ref['path'], ref['sha256'])
            if ref.get('staged'):
                jobs.file_hash(jobs.confined(record['engine_input'], ref['staged']), ref['sha256'])
        task = jobs.read_json(root / 'task/current-task.json')
        task_token = acceptance.fingerprint(task)
        if data['task_sha256'] != task_token:
            raise project.ProjectError('conflict', 'Task changed before the explicit rebind')
        old_task = jobs.read_json(root / 'task/history' / (queued['task_sha256'] + '.json'))
        if old_task['authority'] != task['authority'] or old_task['requirements'] != task['requirements']:
            raise project.ProjectError('conflict', 'Authority or review criteria changed; a scoped source-context review is required')
        binding = dict(item_id=queued['id'], result=state['result'], original_task_sha256=queued['task_sha256'],
                       task_sha256=task_token, shot_token=queued['item']['shot_token'], reviewer=data['reviewer'], finding=data['finding'], source=source,
                       note='Byte/context revalidation only; historical reviews and retained failures are unchanged')
        proof = root / 'rebindings' / (request_id + '.json')
        jobs.immutable_bytes(proof, jobs.canonical(binding))
        def change(value):
            row = next(q for q in value['queue'] if q['id'] == queued['id'])
            row.setdefault('rebindings', []).append({**binding, 'proof': acceptance.reference(proof)})
            return binding
    elif operation == 'pilot-candidate':
        cut = next((c for c in current['cuts'] if c['sha256'] == data['sha256']), None)
        if not cut or cut['incomplete'] or cut['projection'] != project.edit_token(current):
            raise project.ProjectError('conflict', 'Assemble a complete current connected motion cut first')
        if len(cut['timeline']['shots']) < 3:
            raise project.ProjectError('invalid-input', 'A connected pilot needs at least three shot occurrences')
        task = jobs.read_json(root / 'task/current-task.json')
        timeline = root / 'pilot' / (request_id + '.timeline.json')
        jobs.immutable_bytes(timeline, jobs.canonical(cut['timeline']))
        candidate = dict(task_sha256=acceptance.fingerprint(task), purpose='pilot', label='UNVERIFIED MOTION PILOT',
                         active_projection=project.edit_token(current), artifact=acceptance.reference(cut['path']),
                         pilot_projection=project.pilot_token(current, cut['timeline']),
                         timeline=acceptance.reference(timeline), dependencies=task['production']['inputs'] + [task['authority']])
        for ref in cut['dependencies']:
            path = jobs.confined(root, ref['path'])
            jobs.file_hash(path, ref['sha256'])
            candidate['dependencies'].append(acceptance.reference(path))
        def change(value):
            value['pilot_candidate'] = candidate
            return candidate
    elif operation == 'review-row':
        pilot = data.get('purpose') == 'pilot'
        candidate_key, review_key = ('pilot_candidate', 'pilot_review') if pilot else ('candidate', 'review')
        candidate = current.get(candidate_key)
        if not candidate or candidate['active_projection'] != project.edit_token(current):
            raise project.ProjectError('conflict', 'Promote the current edit before recording final review')
        artifact = acceptance.verify(candidate['artifact'])
        row = copy.deepcopy(data['row'])
        evidence = dict(reviewer=data['reviewer'], artifact_sha256=candidate['artifact']['sha256'],
                        check=data['check'], observation=row)
        locator = root / 'observations' / (request_id + '.json')
        jobs.immutable_bytes(locator, jobs.canonical(evidence))
        row.setdefault('evidence', []).extend([acceptance.reference(locator), candidate['artifact']])
        if data['check'].startswith('cut:'):
            frame = int(data['check'].split(':')[1])
            row['frames'] = [frame-1, frame]
            row['staging'] = data.get('staging', '')
            tool = tools(studio)['ffmpeg']
            if not tool:
                raise project.ProjectError('unavailable', 'Configure FFmpeg for exact cut frame evidence')
            for side, number in (('before', frame-1), ('after', frame)):
                image = root / 'observations' / (request_id + '-' + side + '.png')
                edit.run([tool, '-nostdin', '-v', 'error', '-i', artifact, '-vf', 'select=eq(n\\,' + str(number) + ')', '-frames:v', '1', image], 60)
                row[side] = acceptance.reference(image)
        review = copy.deepcopy(current.get(review_key) or dict(task_sha256=candidate['task_sha256'],
                    candidate_sha256=acceptance.fingerprint(candidate), artifact_sha256=candidate['artifact']['sha256'],
                    reviewer=data['reviewer'], checks={}))
        if review['candidate_sha256'] != acceptance.fingerprint(candidate):
            review = dict(task_sha256=candidate['task_sha256'], candidate_sha256=acceptance.fingerprint(candidate),
                          artifact_sha256=candidate['artifact']['sha256'], reviewer=data['reviewer'], checks={})
        review['reviewer'] = data['reviewer']
        review['checks'][data['check']] = row
        task = jobs.read_json(root / 'task/current-task.json')
        def change(value):
            if value.get(candidate_key) != candidate or project.edit_token(value) != candidate['active_projection']:
                raise project.ProjectError('conflict', 'Edit changed while preparing review evidence')
            report = acceptance.record_review(root / 'task', task['authority']['path'], candidate['task_sha256'],
                                              'scale' if pilot else 'review-cut', candidate, review, project_locked=True)
            value[review_key] = review
            return report
    elif operation == 'authorize-pilot-item':
        item = data['item']
        if item.get('phase') not in ('pilot', 'keyframe') or not data.get('reviewer') or not data.get('source'):
            raise project.ProjectError('invalid-input', 'Pilot authorization requires reviewer, sourced direction and a bounded item')
        source = acceptance.reference(data['source'])
        task = jobs.read_json(root / 'task/current-task.json')
        expected_task = acceptance.fingerprint(task)
        if data['task_sha256'] != expected_task:
            raise project.ProjectError('conflict', 'Reload current task before authorizing an item')
        permission = dict(item=item, reviewer=data['reviewer'], source=source,
                          action='User explicitly authorized this exact pilot item in Films')
        locator = root / 'authority' / (request_id + '.pilot.json')
        jobs.immutable_bytes(locator, jobs.canonical(permission))
        task['production']['pilot_jobs'][item['name']] = acceptance.fingerprint(item)
        task['decisions'].append(dict(decision='Authorize pilot item ' + item['name'] + ' ' + acceptance.fingerprint(item), source=str(locator), kind='bounded-admission'))
        def change(value):
            token = acceptance.record(root / 'task', task, expected_task, project_locked=True)
            value['task_sha256'] = token
            return {'task_sha256': token}
    elif operation == 'direction-record':
        if not current['decisions'] or not current['brief']:
            raise project.ProjectError('invalid-input', 'Save the brief and accepted decisions before recording authority')
        authority = acceptance.reference(data['authority'])
        authority_copy = root / 'authority' / (authority['sha256'] + Path(data['authority']).suffix)
        jobs.immutable_bytes(authority_copy, jobs.checked_bytes(data['authority'], authority['sha256']))
        brief = root / 'authority' / (project.projection(current) + '.json')
        jobs.immutable_bytes(brief, jobs.canonical(dict(brief=current['brief'], decisions=current['decisions'], unresolved=current['unresolved'])))
        task = dict(task=current['id'], revision=request_id, goal=current['brief'], profile='narrative-film',
                    authority=acceptance.reference(authority_copy), decisions=[dict(decision=d, source=str(authority_copy)) for d in current['decisions']],
                    superseded=[], unresolved=current['unresolved'], next_action='Plan and approve animatic; authorize bounded connected pilot',
                    delivery=str((root / 'finals' / 'unpromoted.mp4').resolve()), rejected_artifacts=[], exceptions=[], reuse=[],
                    requirements=acceptance.film_requirements(), production=dict(inputs=[acceptance.reference(brief)], pilot_jobs={}, repair_limits={}))
        previous = root / 'task' / 'current-task.json'
        prior_task = jobs.read_json(previous) if previous.exists() else None
        if prior_task:
            for key in ('rejected_artifacts', 'exceptions', 'reuse', 'superseded'):
                task[key] = prior_task[key]
        def change(value):
            token = acceptance.record(root / 'task', task, acceptance.fingerprint(prior_task) if prior_task else 'new', project_locked=True)
            value['task_sha256'] = token
            return {'task_sha256': token}
    elif operation == 'relink':
        asset = next((a for a in current['assets'] if a['id'] == data['asset']), None)
        if not asset:
            raise project.ProjectError('invalid-input', 'Unknown managed asset')
        jobs.file_hash(data['path'], asset['sha256'])
        adopted = project.adopt(root, data['path'], asset['role'])
        def change(value):
            existing = next(a for a in value['assets'] if a['id'] == asset['id'])
            existing['path'] = adopted['path']
            existing.setdefault('relocations', []).append(adopted['provenance'])
            return existing
    elif operation in ('promote', 'deliver'):
        import production_delivery as delivery
        value, receipt = getattr(delivery, operation)(root, request)
        return {'project': project.read_model(value), 'receipt': receipt}
    elif operation == 'asset-import':
        supplied = data.get('metadata', {})
        if data['role'] == 'take' and supplied.get('item'):
            item = supplied['item']
            if item.get('shot_token') != project.projection(current, item['shot']):
                raise project.ProjectError('conflict', 'Completed generation is outdated for this shot; retain its historical receipt, do not adopt as current')
        asset = project.adopt(root, data['path'], data['role'], data.get('metadata'))
        def change(value):
            value['assets'].append(asset)
            if data.get('shot'):
                project.mutate(value, 'asset-bind', dict(shot=data['shot'], asset=asset['id'],
                                                       role=data['role'], precedence=data.get('precedence', 0)))
            return asset
    elif operation in ('render-draft', 'render-animatic'):
        value = project.snapshot(root)
        if value['revision'] != request.get('expected_revision'):
            raise project.ProjectError('conflict', 'Reload the current edit before rendering')
        tool_paths = tools(studio)
        if not all(tool_paths.values()):
            raise project.ProjectError('unavailable', 'Configure FFmpeg and FFprobe in user/production-tools.json')
        destination = root / 'cuts' / (request_id + '.mp4')
        receipt_path = root / 'cuts' / (request_id + '.receipt.json')
        if receipt_path.exists():
            cut = jobs.read_json(receipt_path)
            if cut['request_sha256'] != jobs.digest(jobs.canonical(request)):
                raise project.ProjectError('conflict', 'Render request reused with different content')
            jobs.file_hash(destination, cut['sha256'])
        else:
            cut = edit.assemble(root, value, destination, tool_paths, animatic=operation == 'render-animatic',
                                width=data.get('width', 1280), height=data.get('height', 720))
            cut['projection'] = project.edit_token(value)
            cut['request_sha256'] = jobs.digest(jobs.canonical(request))
            jobs.atomic_json(receipt_path, cut)
        def change(current):
            if project.edit_token(current) != cut['projection']:
                raise project.ProjectError('conflict', 'Edit changed during render; scratch bytes retained, no adoption')
            current['cuts'].append(cut)
            return cut
    elif operation == 'task-record':
        if data['task'].get('profile') != 'narrative-film':
            raise project.ProjectError('invalid-input', 'Film authority must retain the full narrative-film requirements')
        # Acceptance's own CAS remains authoritative. No fabricated decisions or approval.
        value = project.snapshot(root)
        if value['revision'] != request.get('expected_revision'):
            raise project.ProjectError('conflict', 'Reload current direction')
        def change(current):
            return {'task_sha256': acceptance.record(root / 'task', data['task'], data['expected_task'], project_locked=True)}
    elif operation in ('review-check', 'review-record'):
        function = acceptance.record_review if operation == 'review-record' else acceptance.check
        if operation == 'review-check':
            return function(root / 'task', data['authority'], data['task_sha256'], data['action'], data['candidate'], data.get('review'))
        def change(current):
            return function(root / 'task', data['authority'], data['task_sha256'], data['action'], data['candidate'], data.get('review'), project_locked=True)
    elif operation == 'transcript-import':
        # Observed text is supplied independently. Expected dialogue is never substituted.
        record = copy.deepcopy(data)
        audio = project.adopt(root, record.pop('path'), 'dialogue')
        if record.get('status') not in ('observed', 'failed', 'unverified') or not record.get('method') or not record.get('reviewer'):
            raise project.ProjectError('invalid-input', 'Transcript needs status, independent method and reviewer/version')
        edit.integer(record.get('start_sample'), 'Transcript start')
        edit.integer(record.get('end_sample'), 'Transcript end', record['start_sample'] + 1)
        if not isinstance(record.get('observed'), str):
            raise project.ProjectError('invalid-input', 'Supply independently observed text; leave empty if unavailable')
        record['media_sha256'] = audio['sha256']
        record['audio_sample_rate'] = 48000
        record['audio_channels'] = 2
        tool = tools(studio)['ffmpeg']
        if not tool:
            raise project.ProjectError('unavailable', 'Configure FFmpeg to bind transcript to decoded current audio')
        decoded = root / 'transcripts' / (request_id + '.pcm')
        decoded.parent.mkdir(exist_ok=True)
        edit.run([tool, '-nostdin', '-v', 'error', '-i', jobs.confined(root, audio['path']), '-map', '0:a:0',
                  '-af', f"aresample=48000,atrim=start_sample={record['start_sample']}:end_sample={record['end_sample']},asetpts=PTS-STARTPTS",
                  '-ac', '2', '-f', 's16le', decoded], 120)
        expected_bytes = (record['end_sample']-record['start_sample']) * 2 * 2
        if decoded.stat().st_size != expected_bytes:
            raise project.ProjectError('invalid-input', 'Decoded audio is shorter than the declared transcript interval')
        record['audio_sha256'] = jobs.file_hash(decoded)
        record['decoded_audio'] = str(decoded.relative_to(root))
        expected_words = record.pop('expected', None)
        if expected_words is not None:
            import production_media as media
            record['word_comparison'] = (media.compare_words(expected_words, record['observed']) if record['status'] == 'observed'
                                         else {'ok': None, 'status': 'unverified', 'reason': 'Independent speech observation was unavailable or failed'})
            record['word_comparison_limit'] = 'Ordered wording only; emotional performance, speaker attribution and lip sync remain unverified'
        record['id'] = jobs.digest(jobs.canonical(record))
        jobs.immutable_bytes(root / 'transcripts' / (record['id'] + '.json'), jobs.canonical(record))
        def change(value):
            value['assets'].append(audio)
            value.setdefault('transcripts', []).append(record)
            return record
    elif operation.startswith(('edit-', 'segment-', 'audio-', 'marker-', 'title-')) or operation in ('undo', 'redo'):
        candidates = []
        if operation == 'segment-insert':
            candidates = [data['segment']]
        elif operation == 'edit-replace':
            candidates = data['edit']['segments']
        elif operation == 'segment-update':
            existing = next((s for s in current['edit']['segments'] if s['id'] == data['segment']), None)
            if existing:
                candidates = [{**existing, **data['changes']}]
        checked = {}
        for segment in candidates:
            if not segment.get('asset'):
                continue
            asset = next((a for a in current['assets'] if a['id'] == segment['asset']), None)
            if not asset:
                raise project.ProjectError('invalid-input', 'Timeline source asset does not exist')
            path = jobs.confined(root, asset['path'])
            if path.suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp'):
                continue
            if asset['sha256'] not in checked:
                jobs.file_hash(path, asset['sha256'])
                ffprobe = tools(studio)['ffprobe']
                if not ffprobe:
                    raise project.ProjectError('unavailable', 'Configure FFprobe before editing source frame ranges')
                fps = data['edit']['fps'] if operation == 'edit-replace' else current['edit']['fps']
                checked[asset['sha256']] = edit.validate_cfr(path, fps, ffprobe)
            if segment['out_frame'] > checked[asset['sha256']]:
                raise project.ProjectError('invalid-input', 'Timeline out frame exceeds the actual decoded source')
        change = lambda value: edit.change(value, operation, data)
    elif operation == 'select':
        asset = next((a for a in current['assets'] if a['id'] == data['asset']), None)
        if not asset:
            raise project.ProjectError('invalid-input', 'Select an imported take')
        source = jobs.confined(root, asset['path'])
        jobs.file_hash(source, asset['sha256'])
        ffprobe = tools(studio)['ffprobe']
        if not ffprobe:
            raise project.ProjectError('unavailable', 'Configure FFprobe before selecting an exact source range')
        info = edit.probe(source, ffprobe)
        video = next((s for s in info['streams'] if s['codec_type'] == 'video'), None)
        if not video or data['out_frame'] > float(video.get('duration', info['format'].get('duration', 0))) * float(edit.Fraction(video['avg_frame_rate'])) + .01:
            raise project.ProjectError('invalid-input', 'Take range exceeds the actual source duration')
        edit.validate_cfr(source, current['edit']['fps'], ffprobe)
        change = lambda value: project.mutate(value, operation, data)
    elif operation in ('enqueue', 'drive-one', 'cancel'):
        import production_coordinator as coordinator
        return coordinator.film_command(studio, root, request)
    else:
        change = lambda value: project.mutate(value, operation, data)
    value, receipt = project.transaction(root, request.get('expected_revision'), request_id,
                                          {'operation': operation, 'payload': data}, change)
    return {'project': project.read_model(value), 'receipt': receipt}


def dispatch(studio, request):
    try:
        result = handle(studio, request)
        return {'version': PROTOCOL, 'request_id': request.get('request_id'), 'ok': True, 'code': 'ok', 'result': result}
    except project.ProjectError as exc:
        code, message = exc.code, str(exc)
    except RuntimeError as exc:
        code, message = 'busy', str(exc)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        code, message = 'invalid-input', str(exc)
    except Exception as exc:
        code, message = 'unknown', str(exc)
    return {'version': PROTOCOL, 'request_id': request.get('request_id'), 'ok': False, 'code': code, 'message': message}


def main():
    try:
        request = json.load(sys.stdin)
        if not isinstance(request, dict):
            raise ValueError('Request must be an object')
        reply = dispatch(sys.argv[1], request)
    except Exception as exc:
        reply = dict(version=PROTOCOL, ok=False, code='invalid-input', message=str(exc))
    print(json.dumps(reply, ensure_ascii=False, allow_nan=False))
    return 0 if reply['ok'] else 2


if __name__ == '__main__':
    sys.stdin.reconfigure(encoding='utf-8')
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    raise SystemExit(main())
