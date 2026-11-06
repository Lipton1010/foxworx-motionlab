"""One bounded shared-interface H3 preview. Explicit validation fixture, no film-quality approval."""
import json
from pathlib import Path
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'desktop'))
import production_service as service
import production_project as project
import production_jobs as jobs


def main():
    studio = ROOT / 'temp/film-implementation/published'
    (studio / 'user').mkdir(parents=True, exist_ok=True)
    jobs.atomic_json(studio / 'user/production-tools.json', dict(model_roots=[str(ROOT / 'models')],
                      ffmpeg=str(studio / 'runtime/media/ffmpeg.exe'), ffprobe=str(studio / 'runtime/media/ffprobe.exe')))
    authority = studio / 'user/implementation-validation-authority.txt'
    authority.write_text('User instruction, 2026-11-05: Implement the approved Image Studio film-workflow and UI plan. '
                         'Verify the actual app and packaged builds; report unsupported capabilities honestly. '
                         'This fixture authorizes one 5-second H3 preview and one bounded selected-latent refinement test. '
                         'No film semantic, motion, listening or delivery approval is represented.', encoding='utf-8')
    value = None
    def call(operation, payload=None, request_id=None):
        nonlocal value
        request = dict(version=1, operation=operation, request_id=request_id or uuid.uuid4().hex,
                       project_id=value['id'] if value else None,
                       expected_revision=value['revision'] if value else None, payload=payload or {})
        reply = service.dispatch(studio, request)
        if not reply['ok']:
            raise RuntimeError(reply)
        result = reply['result']
        if operation == 'create':
            value = result
        elif isinstance(result, dict) and result.get('project'):
            value = result['project']
        print(operation, result.get('state', {}).get('status', 'ok') if isinstance(result, dict) else 'ok', flush=True)
        return result
    receipt = ROOT / 'temp/film-implementation/evidence/live-fixture.json'
    if len(sys.argv) > 1 and sys.argv[1] in ('resume', 'finish'):
        saved = jobs.read_json(receipt)
        value = project.read_model(project.snapshot(project.folder(studio, saved['project'])))
        if sys.argv[1] == 'finish':
            proposal = call('propose-finish', dict(preview=value['queue'][0]['id'], width=1280, height=768, interpolate=True))
            task = call('task-open')
            call('authorize-pilot-item', dict(item=proposal['item'], reviewer='Automated bounded finish validation',
                                              source=str(authority), task_sha256=task['task_sha256']))
            task = call('task-open')
            call('enqueue', dict(item=proposal['item'], spec=proposal['spec'], task_sha256=task['task_sha256'],
                                 engine_input=str(ROOT / 'input'), engine_output=str(ROOT / 'output')))
    else:
        call('create', {'title': 'VALIDATION ONLY — H3 persisted preview 2026-11-05'})
        call('plan', {'brief': 'Bounded implementation fixture: a small red wooden ball rolls gently across a plain tabletop, stationary camera, no speech.',
                      'decisions': ['Synthetic validation only; no semantic approval or film delivery'], 'unresolved': []})
        call('shot-add', {'name': 'Validation preview'})
        shot = value['selected_shot']
        call('shot-update', {'shot': shot, 'changes': {'prompt': 'A small red wooden ball rolls slowly across a plain light wooden tabletop. Static camera, soft daylight. Quiet room tone, no speech.', 'mode': 'text'}})
        # A manual still is an explicit test animatic input, never evidence of connected motion.
        import subprocess
        panel = studio / 'user/validation-panel.png'
        if not panel.exists():
            subprocess.run([str(studio / 'runtime/media/ffmpeg.exe'), '-nostdin', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=red:s=768x448', '-frames:v', '1', str(panel)], check=True)
        call('asset-import', {'path': str(panel), 'role': 'keyframe', 'shot': shot})
        call('approve-animatic', {'reviewer': 'Automated implementation fixture', 'finding': 'Synthetic held panel and timing approved solely to exercise the pilot bootstrap. No motion or film quality judgment.'})
        call('direction-record', {'authority': str(authority)})
        request = dict(Prompt=value['shots'][0]['prompt'], Negative='', Seed=5917521, Width=768, Height=448, Seconds=5,
                       Model='minimax_h3_fl2va_pruned_int8_convrot.safetensors', Loras=[dict(Name='pika_h3_flex_fl2va_comfy_bf16.safetensors', Strength=1, Enabled=True)], Profile='pika-flex')
        proposal = call('propose-take', dict(kind='video', name='validation-preview', shot=shot, phase='pilot', request=request))
        task = call('task-open')
        call('authorize-pilot-item', dict(item=proposal['item'], reviewer='Automated bounded implementation validation',
                                          source=str(authority), task_sha256=task['task_sha256']))
        task = call('task-open')
        call('enqueue', dict(item=proposal['item'], spec=proposal['spec'], task_sha256=task['task_sha256'],
                             engine_input=str(ROOT / 'input'), engine_output=str(ROOT / 'output')))
        call('pause', {'paused': False})
        jobs.atomic_json(receipt, dict(project=value['id'], root=str(studio), limit='One preview; separate exact selected-latent finish test only', request=request))
    call('drive-one')
    jobs.atomic_json(ROOT / 'temp/film-implementation/evidence/live-state.json', value['queue'])
    print(json.dumps({'project': value['id'], 'queue': value['queue']}, indent=2), flush=True)


if __name__ == '__main__':
    main()
