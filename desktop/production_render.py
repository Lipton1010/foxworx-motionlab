"""Graph-host adapter. Recipes remain in the shared C# generation builders."""
import copy
import json
from pathlib import Path
import subprocess

import production_jobs as jobs
import production_project as project


def graph(studio, data):
    host = Path(studio) / 'app' / 'graph-host' / 'ImageStudio.GraphHost.exe'
    if not host.is_file():
        raise project.ProjectError('unavailable', 'Packaged graph host is missing. Rebuild the desktop package.')
    request = copy.deepcopy(data['request'])
    kind = data['kind']
    envelope = dict(root=str(Path(studio).resolve()), kind=kind, request=request)
    inputs = []
    dependencies = list(data.get('dependencies', []))
    lineage = None
    if kind == 'video':
        for field, socket, node, argument in (('Source', 'image', 'image', 'source_name'),
                                             ('LastFrame', 'image', 'last_image', 'last_frame'),
                                             ('AudioGuide', 'audio', 'guide_audio', 'audio_guide'),
                                             ('GuideVideo', 'file', 'guide_video', 'guide_video'),
                                             ('LatentFile', 'file', 'saved_av', None)):
            if request.get(field):
                source = Path(request[field]).resolve(strict=True)
                inputs.append(dict(node=node, field=socket, path=str(source)))
                if argument:
                    envelope[argument] = source.name
        if request.get('LatentFile'):
            preview = Path(data['preview_revision'])
            preview_record = jobs.load_revision(preview)
            status = jobs.read_json(preview / 'state.json')
            if status['status'] != 'completed':
                raise project.ProjectError('conflict', 'Select a current completed preview before finishing')
            jobs.validate_result(preview, status['result'], preview_record, status['attempts'][-1])
            companions = status['result'].get('auxiliary', [])
            if len(companions) != 1:
                raise project.ProjectError('unsupported', 'This preview has no typed AV companion')
            companion = companions[0]
            if Path(companion['path']).resolve() != Path(request['LatentFile']).resolve() or companion['sha256'] != request.get('LatentSha256'):
                raise project.ProjectError('conflict', 'Latent is not the selected preview attempt companion')
            attempt = status['attempts'][-1]
            dependencies.extend([str(preview / 'revision.json'), str(preview / (attempt['id'] + '.history.json'))])
            lineage = dict(preview_revision=str(preview), prompt_id=attempt['id'],
                           executed_graph_sha256=attempt['graph_sha256'], result=status['result'])
    elif kind == 'image':
        references = request.get('References') or ([{'Path': request['Source']}] if request.get('Source') else [])
        envelope['source_names'] = [Path(r['Path']).name for r in references]
        inputs = [dict(node=str(9+i), field='image', path=r['Path']) for i, r in enumerate(references)]
    else:
        raise project.ProjectError('invalid-input', 'Expected image or video graph kind')
    result = subprocess.run([str(host)], input=json.dumps(envelope), text=True, encoding='utf-8',
                            capture_output=True, timeout=30)
    reply = json.loads(result.stdout)
    if result.returncode or not reply.get('ok'):
        raise project.ProjectError('invalid-input', reply.get('message', result.stderr))
    graph = reply['graph']
    savers = [(node, value) for node, value in graph.items() if value.get('class_type') in ('SaveVideo', 'SaveImage')]
    if len(savers) != 1:
        raise project.ProjectError('unsupported', 'Expected exactly one selected primary media saver')
    node, saver = savers[0]
    auxiliary = [dict(node=n, key='studio_av', type='output', extension='.safetensors', kind='h3-av-safetensors-v1')
                 for n, v in graph.items() if v.get('class_type') == 'SaveStudioAV']
    return dict(graph=graph, inputs=inputs, dependencies=dependencies, environment=data['environment'], lineage=lineage,
                output=dict(node=node, key='images', type='output', extension='.mp4' if saver['class_type'] == 'SaveVideo' else '.png'),
                auxiliary=auxiliary)


def content_key(graph, input_hashes, environment):
    """Only explicitly observational output nodes are omitted; sampler ancestry is retained."""
    observational = {n for n, v in graph.items() if v.get('class_type') in ('PreviewImage', 'SaveVideo', 'SaveImage', 'SaveStudioAV')}
    referenced = {v[0] for n, node in graph.items() if n not in observational
                  for v in node.get('inputs', {}).values() if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str)}
    observational -= referenced
    semantic = {n: copy.deepcopy(v) for n, v in graph.items() if n not in observational}
    return jobs.digest(jobs.canonical(dict(graph=semantic, inputs=input_hashes, environment=environment)))


def inspect_runtime(studio, graph, endpoint='http://127.0.0.1:8193'):
    endpoint = jobs.endpoint_url(endpoint)
    stats = jobs.http_json(endpoint, 'GET', '/system_stats')['system']
    info = jobs.http_json(endpoint, 'GET', '/object_info')
    types = sorted({n['class_type'] for n in graph.values()})
    missing = [name for name in types if name not in info]
    if missing:
        raise project.ProjectError('unavailable', 'Engine nodes missing: ' + ', '.join(missing))
    roots = [Path(studio) / 'models']
    settings = Path(studio) / 'user' / 'production-tools.json'
    if settings.exists():
        roots.extend(Path(p) for p in jobs.read_json(settings).get('model_roots', []))
    models = []
    fields = {'UNETLoader': ('unet_name', 'diffusion_models'), 'CLIPLoader': ('clip_name', 'text_encoders'),
              'VAELoader': ('vae_name', 'vae'), 'LoraLoader': ('lora_name', 'loras')}
    for node in graph.values():
        if node['class_type'] not in fields:
            continue
        field, category = fields[node['class_type']]
        relative = node['inputs'][field]
        path = next((jobs.confined(r / category, relative) for r in roots if jobs.confined(r / category, relative).is_file()), None)
        if not path:
            raise project.ProjectError('unavailable', 'Exact model file is not available in configured production model roots: ' + relative)
        models.append({'path': str(path), 'sha256': jobs.file_hash(path)})
    source = Path(stats['argv'][0]).parent
    code = [source / 'comfy_extras' / 'nodes_minimax_h3.py', source / 'comfy' / 'nested_tensor.py',
            source / 'comfy' / 'supported_models.py', source / 'comfy' / 'model_sampling.py', source / 'comfy' / 'model_base.py',
            Path(studio) / 'runtime/custom_nodes/image-studio-av/__init__.py',
            Path(studio) / 'runtime/custom_nodes/image-studio-av/av_codec.py']
    evidence = [dict(path=str(p), sha256=jobs.file_hash(p)) for p in code]
    return dict(engine={k: stats[k] for k in ('comfyui_version', 'python_version', 'pytorch_version')},
                node_definitions_sha256=jobs.digest(jobs.canonical({k: info[k] for k in types})),
                models=models, code=evidence, endpoint=endpoint)
