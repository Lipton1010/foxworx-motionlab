"""Post-GPU sound/edit/transcript checks through the same packaged film interface."""
import copy
from pathlib import Path
import sys
import uuid
import wave

sys.path.insert(0, str(Path(__file__).resolve().parent))
from live_film_modes import Trial, BASE, STUDIO, ROOT, jobs
import production_project as project


def sound(trial):
    if trial.state.get('multi_scene_sound_cut'):
        return
    if trial.value['cuts'] and len(trial.value['edit']['audio']) == 3 and any(t['text'] == 'TECHNICAL VALIDATION - NOT APPROVED' for t in trial.value['edit']['titles']):
        cut = trial.value['cuts'][-1]
        if cut['projection'] == project.edit_token(trial.value):
            verify_sound(trial, cut)
            return
    original = trial.state['connected_cut']['timeline']
    edit = dict(fps=original['fps'], sample_rate=48000, audio=[], markers=[], titles=[],
        segments=[{key: value for key, value in item.items() if key in
            ('id', 'shot', 'asset', 'in_frame', 'out_frame', 'volume', 'mute', 'fade_in', 'fade_out')}
            for item in original['shots']])
    trial.call('edit-replace', {'edit': edit})
    trial.call('scene-add', {'name': 'Follow-up scene 2'})
    scene = trial.value['scenes'][-1]['id']
    for label in ('B', 'C'):
        trial.call('shot-update', dict(shot=trial.state['shots'][label], changes={'scene': scene}))
    dialogue, music, effects = [BASE / name for name in ('dialogue-48k.wav', 'music-test.wav', 'effects-test.wav')]
    if not dialogue.exists():
        trial.ffmpeg('-i', BASE / 'voice.wav', '-ar', '48000', '-ac', '2', '-c:a', 'pcm_s16le', dialogue)
    if not music.exists():
        trial.ffmpeg('-f', 'lavfi', '-i', 'sine=frequency=220:sample_rate=48000:duration=5', '-ac', '2', music)
    if not effects.exists():
        trial.ffmpeg('-f', 'lavfi', '-i', 'anoisesrc=color=pink:sample_rate=48000:duration=0.5:seed=5917', '-ac', '2', effects)
    with wave.open(str(dialogue), 'rb') as source:
        samples = source.getnframes()
    for path, role, start, length, volume in ((dialogue, 'dialogue', 48000, samples, 1),
        (music, 'music', 24000, 240000, .12), (effects, 'effects', 468000, 24000, .08)):
        asset = trial.import_asset(path, role=role, metadata={'purpose': 'Explicit synthetic technical sound fixture; no artistic approval'})
        trial.call('audio-add', {'item': dict(asset=asset, track=role, start_sample=start, in_sample=0,
            samples=length, volume=volume, mute=False, fade_in=0, fade_out=0)})
    trial.call('marker-add', {'item': dict(text='Independent effects cue crosses the cut at frame 240', frame=240)})
    trial.call('title-add', {'item': dict(text='TECHNICAL VALIDATION - NOT APPROVED', start_frame=0, end_frame=360)})
    trial.call('render-draft', dict(width=768, height=448))
    cut = trial.value['cuts'][-1]
    trial.call('pilot-candidate', {'sha256': cut['sha256']})
    verify_sound(trial, cut)


def verify_sound(trial, cut):
    independent = trial.value['edit']['audio']
    assert cut['timeline']['frames'] == 360 and len(independent) == 3
    assert {cue['id'] for cue in independent}.issubset({cue['id'] for cue in cut['timeline']['audio']})
    jobs.file_hash(cut['path'], cut['sha256'])
    raw = BASE / 'sound-cut-full.pcm'
    interval = BASE / 'sound-cut-reviewed-interval.pcm'
    trial.ffmpeg('-i', cut['path'], '-map', '0:a:0', '-ar', 48000, '-ac', 2, '-f', 's16le', raw)
    trial.ffmpeg('-i', cut['path'], '-map', '0:a:0', '-af', 'aresample=48000,atrim=end_sample=720000', '-ac', 2, '-f', 's16le', interval)
    assert interval.stat().st_size == 720000 * 4
    evidence = dict(cut=cut, scenes=len(trial.value['scenes']), independent_cues=independent,
        linked_source_audio_cues=3, cue_positions=[24000,48000,468000],
        exact_review_interval_samples=720000, decoded_full_samples=raw.stat().st_size//4,
        decoded_interval_sha256=jobs.file_hash(interval),
        limits='Sample-grid interval verified; AAC decoder padding is reported separately. No by-ear or artistic approval.')
    jobs.atomic_json(ROOT / 'temp/film-implementation/evidence/followup-sound.json', evidence)
    trial.state['multi_scene_sound_cut'] = cut; trial.save()
    print('Multi-scene 3-track cut, exact 720000-sample interval and full decode passed', flush=True)


def transcript(trial):
    asr = jobs.read_json(ROOT / 'temp/film-implementation/evidence/followup-asr.json')
    expected = jobs.read_json(BASE / 'voice-source.json')['intended_guide_words']
    generated = asr['results']['generated_voice']
    source = trial.state['cases']['voice-guide']['output']
    jobs.file_hash(source['path'], source['sha256'])
    assert generated['input_sha256'] == source['sha256']
    result = trial.call('transcript-import', dict(path=source['path'], start_sample=0, end_sample=248000,
        observed=generated['text'], expected=expected, status='observed' if generated['text'].strip() else 'failed',
        method='faster-whisper 1.2.1 / CTranslate2 4.7.2 / large-v3 / CPU INT8; no expected words, prompt or hotwords supplied to recognizer',
        reviewer='Independent local ASR diagnostic; not human listening', recognizer=asr['model'],
        recognition_evidence=dict(path=str((ROOT / 'temp/film-implementation/evidence/followup-asr.json').resolve()),
                                  sha256=jobs.file_hash(ROOT / 'temp/film-implementation/evidence/followup-asr.json'))))
    evidence = trial.value['transcripts'][-1]
    jobs.atomic_json(ROOT / 'temp/film-implementation/evidence/followup-transcript-import.json', evidence)
    print('Imported independently recognized current-audio words:', generated['text'], flush=True)
    print('Ordered-word comparison:', evidence.get('word_comparison'), flush=True)


if __name__ == '__main__':
    trial = Trial()
    if sys.argv[1] == 'sound':
        sound(trial)
    elif sys.argv[1] == 'transcript':
        transcript(trial)
    else:
        raise SystemExit('Use sound or transcript after all GPU trials have stopped')
