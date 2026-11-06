"""Decode an existing owned AV companion after engine restart; no sampler/model reroll."""
import json
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'desktop'))
import production_jobs as jobs
import production_render as render
import production_service as service

saved = jobs.read_json(ROOT / 'temp/film-implementation/evidence/live-state.json')[0]
record = jobs.load_revision(saved['revision'])
state = jobs.read_json(Path(saved['revision']) / 'state.json')
companion = state['result']['auxiliary'][0]
runtime = record['spec']['graph']['save_av']['inputs']['runtime_identity']
studio = ROOT / 'temp/film-implementation/published'
request = dict(Prompt='Decode persisted validation preview only, no sampling.', Negative='', Seed=0, Width=768, Height=448, Seconds=5,
               Model='minimax_h3_fl2va_pruned_int8_convrot.safetensors', Profile='decode-preview',
               RuntimeIdentity=runtime, LatentRuntimeIdentity=runtime, LatentFile=companion['path'], LatentSha256=companion['sha256'])
spec = render.graph(studio, dict(kind='video', request=request, preview_revision=saved['revision'], environment={'purpose': 'post-restart exact AV decode', 'original': json.loads(runtime)}))
assert not any(n['class_type'] in ('SamplerCustomAdvanced', 'UNETLoader', 'KSampler') for n in spec['graph'].values())
root = jobs.prepare(spec, ROOT / 'temp/film-implementation/restart-jobs', ROOT / 'input', ROOT / 'output')
receipt = ROOT / 'temp/film-implementation/evidence/restart-job.json'
if receipt.exists():
    root = Path(jobs.read_json(receipt)['revision'])
else:
    jobs.atomic_json(receipt, {'revision': str(root)})
claim = service.dispatch(studio, dict(version=1, operation='gpu-claim', request_id=uuid.uuid4().hex,
                         payload=dict(owner='restart_av_decode', intent=str(root))))
if not claim['ok']:
    raise RuntimeError(claim)
result = jobs.run(root, timeout=0, max_attempts=1)
if result['status'] in ('completed', 'failed', 'rejected', 'cancelled', 'invalid_output'):
    service.handle(studio, dict(version=1, operation='gpu-release', request_id=uuid.uuid4().hex,
                    payload=dict(owner='restart_av_decode', terminal=True)))
jobs.atomic_json(ROOT / 'temp/film-implementation/evidence/restart-state.json', result)
print(json.dumps({'revision': str(root), 'status': result['status'], 'result': result.get('result'), 'sampling': False}, indent=2))
