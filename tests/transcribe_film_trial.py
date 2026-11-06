"""Independent CPU recognition of actual audio, with no intended words as input."""
import hashlib
import json
import os
from pathlib import Path
import time

os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['TRANSFORMERS_OFFLINE'] = '1'
from faster_whisper import WhisperModel

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / 'temp/film-implementation/evidence'
BASE = ROOT / 'temp/film-implementation/followup-20261105'
provenance = json.loads((EVIDENCE / 'followup-asr-model.json').read_text(encoding='utf-8'))
controller = json.loads((BASE / 'controller.json').read_text(encoding='utf-8'))
snapshot = Path(provenance['files'][0]['path']).parent
started = time.monotonic()
model = WhisperModel(str(snapshot), device='cpu', compute_type='int8', cpu_threads=6,
                     num_workers=1, local_files_only=True)
results = {}
for key, path in (('source_guide', BASE / 'voice.wav'),
                  ('generated_voice', Path(controller['cases']['voice-guide']['output']['path']))):
    segments, info = model.transcribe(str(path), language='en', beam_size=5,
        condition_on_previous_text=False, word_timestamps=True, vad_filter=False)
    rows = [dict(start=s.start, end=s.end, text=s.text, average_logprob=s.avg_logprob,
        no_speech_probability=s.no_speech_prob,
        words=[dict(start=w.start, end=w.end, word=w.word, probability=w.probability) for w in s.words or []]) for s in segments]
    results[key] = dict(path=str(path), input_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        duration=info.duration, text=' '.join(s['text'].strip() for s in rows), segments=rows)
    print(key, results[key]['text'], flush=True)
record = dict(model=provenance, device='cpu', seconds=time.monotonic()-started,
    supplied_recognition_context='Language en only. No intended words, initial prompt, prefix or hotwords.', results=results,
    limitations='ASR words and timestamps are diagnostic, not by-ear sound, performance, speaker or lip-sync approval.')
(EVIDENCE / 'followup-asr.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
