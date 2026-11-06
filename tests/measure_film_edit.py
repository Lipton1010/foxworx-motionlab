"""Bounded 10-minute synthetic scale probe through the public film service."""
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'desktop'))
import production_service as service
import production_project as project
import production_jobs as jobs
import production_edit as edit_owner


def main():
    root = ROOT / 'temp' / 'film-implementation' / ('scale-' + uuid.uuid4().hex)
    root.mkdir(parents=True)
    (root / 'user').mkdir()
    jobs.atomic_json(root / 'user/production-tools.json', dict(
        ffmpeg='C:/ProgramData/chocolatey/lib/ffmpeg/tools/ffmpeg/bin/ffmpeg.exe',
        ffprobe='C:/ProgramData/chocolatey/lib/ffmpeg/tools/ffmpeg/bin/ffprobe.exe'))
    budgets = {'export_seconds': 300, 'document_save_seconds': 1, 'active_decoders': 1,
               'seek_budget_ms': 250, 'peak_memory_mib': 2048, 'cancel_seconds': 5}
    source = root / 'six-seconds.mp4'
    subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=s=640x360:r=24',
                    '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000', '-t', '6', '-c:v', 'libx264',
                    '-preset', 'veryfast', '-crf', '24', '-c:a', 'aac', '-pix_fmt', 'yuv420p', str(source)], check=True)
    counter = 0
    value = None
    def call(operation, payload=None):
        nonlocal counter, value
        counter += 1
        result = service.dispatch(root, dict(version=1, operation=operation, request_id='scale' + str(counter),
                                             project_id=value['id'] if value else None,
                                             expected_revision=value['revision'] if value else None, payload=payload or {}))
        if not result['ok']:
            raise RuntimeError(result)
        if operation == 'create':
            value = result['result']
        elif result['result'].get('project'):
            value = result['result']['project']
        return result
    call('create', {'title': 'SYNTHETIC 10-minute scale fixture'})
    call('asset-import', {'path': str(source), 'role': 'take'})
    asset = value['assets'][0]['id']
    segments = [dict(id=uuid.uuid4().hex, asset=asset, in_frame=0, out_frame=144) for _ in range(100)]
    edit = {**value['edit'], 'segments': segments}
    start = time.perf_counter()
    call('edit-replace', {'edit': edit})
    save_seconds = time.perf_counter() - start
    start = time.perf_counter()
    result = call('render-draft', {'width': 640, 'height': 360})
    export_seconds = time.perf_counter() - start
    cut = value['cuts'][-1]
    probe = cut['technical']['probe']
    report = dict(label='SYNTHETIC MEDIA — not generated-film quality', budgets=budgets,
                  hardware={'gpu': 'CPU FFmpeg export; no GPU inference', 'ram': '32 GB host'},
                  fps=24, dimensions=[640, 360], codec='H.264/AAC', clips=100, frames=14400,
                  source=str(source),
                  save_seconds=save_seconds, export_seconds=export_seconds, artifact=cut['path'],
                  sha256=cut['sha256'], bytes=Path(cut['path']).stat().st_size, full_decode=cut['technical']['ok'],
                  active_picture_decoder_design=1,
                  measured_peak_child_memory_mib=edit_owner.RUN_METRICS['peak_child_working_set_bytes'] / 1048576,
                  measured_seek_latency_ms=None,
                  measured_cancel_seconds=None,
                  limitations=['Memory is the largest measured FFmpeg/FFprobe child working set; it excludes the parent UI and driver.',
                               'Actual decoded-frame seek latency requires separate UI instrumentation; cancellation is measured in FilmUiChecks.'],
                  passed_measured_budgets=save_seconds < budgets['document_save_seconds'] and export_seconds < budgets['export_seconds'])
    jobs.atomic_json(ROOT / 'temp/film-implementation/evidence/scale-result.json', report)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
