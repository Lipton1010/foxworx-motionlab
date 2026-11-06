"""Deterministic production checks; no semantic, listening, or lip-sync judgments."""
import argparse
import difflib
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import re
import subprocess
import unicodedata


def _number(value, label, *, positive=False):
    if isinstance(value, bool):
        raise ValueError(f'{label} must be a finite number')
    try:
        result = Fraction(str(value))
    except (ValueError, ZeroDivisionError, TypeError) as exc:
        raise ValueError(f'{label} must be a finite number') from exc
    if result < 0 or (positive and result == 0):
        raise ValueError(f'{label} must be {"positive" if positive else "nonnegative"}')
    return result


def _frames(seconds, fps, label):
    result = _number(seconds, label) * fps
    if result.denominator != 1:
        raise ValueError(f'{label} is not on a frame boundary at {fps} fps')
    return int(result)


def build_timeline(shots, fps=24, cues=None, sample_rate=48000):
    """Shots: id/seconds. Cues: shot_id/offset/seconds, optionally id/text."""
    rate = _number(fps, 'fps', positive=True)
    audio_rate = _number(sample_rate, 'sample_rate', positive=True)
    if audio_rate.denominator != 1:
        raise ValueError('sample_rate must be an integer')
    if not isinstance(shots, list) or not shots:
        raise ValueError('shots must be a nonempty list')
    schedule, by_id, cursor = [], {}, 0
    for shot in shots:
        if not isinstance(shot, dict) or not isinstance(shot.get('id'), str) or not shot['id'].strip():
            raise ValueError('each shot needs a nonempty string id')
        sid = shot['id']
        if sid in by_id:
            raise ValueError(f'duplicate shot id: {sid}')
        count = _frames(shot.get('seconds'), rate, f'{sid} seconds')
        if count == 0:
            raise ValueError(f'{sid} seconds must be positive')
        item = dict(id=sid, start_frame=cursor, end_frame=cursor + count, frames=count)
        schedule.append(item)
        by_id[sid] = item
        cursor += count
    if cues is None:
        cues = []
    if not isinstance(cues, list):
        raise ValueError('cues must be a list')
    resolved = []
    for cue in cues:
        if not isinstance(cue, dict) or not isinstance(cue.get('shot_id'), str) or cue['shot_id'] not in by_id:
            raise ValueError('cue needs a known shot_id')
        shot = by_id[cue['shot_id']]
        offset = _number(cue.get('offset', 0), 'cue offset')
        duration = _number(cue.get('seconds'), 'cue seconds')
        shot_duration = Fraction(shot['frames'], 1) / rate
        if duration <= 0 or offset + duration > shot_duration:
            raise ValueError(f'cue overflows shot {shot["id"]} or has zero duration')
        start = Fraction(shot['start_frame'], 1) / rate + offset
        end = start + duration
        start_sample = _frames(start, audio_rate, 'cue start')
        end_sample = _frames(end, audio_rate, 'cue end')
        resolved.append(dict(cue, start_seconds=str(start), end_seconds=str(end),
                             start_sample=start_sample, end_sample=end_sample))
    return dict(fps=str(rate), frames=cursor, seconds=str(Fraction(cursor, 1) / rate),
                sample_rate=int(audio_rate), shots=schedule, cues=resolved)


def compare_words(intended, transcript):
    """Keep original strings; normalize case, Unicode and punctuation for word diff."""
    if not isinstance(intended, str) or not isinstance(transcript, str):
        raise ValueError('intended and transcript must be strings')
    def words(value):
        value = unicodedata.normalize('NFKC', value).casefold().replace('’', "'")
        return re.findall(r"[^\W_]+(?:'[^\W_]+)*", value, re.UNICODE)
    expected, observed = words(intended), words(transcript)
    changes = [dict(kind=kind, intended=expected[a:b], observed=observed[c:d])
               for kind, a, b, c, d in difflib.SequenceMatcher(None, expected, observed).get_opcodes()
               if kind != 'equal']
    return dict(ok=not changes, intended=intended, transcript=transcript, changes=changes)


def _run(args):
    try:
        result = subprocess.run(args, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=300)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError(f'cannot execute {args[0]}: {exc}') from exc
    if result.returncode:
        raise ValueError(f'{args[0]} failed: {result.stderr[-3000:]}')
    return result


def validate_media(path, expected, full_decode=False, ffprobe='ffprobe', ffmpeg='ffmpeg'):
    """Expected keys: duration, frames, fps, width, height, audio_rate, channels.

    Duration tolerance defaults to 0.001 seconds; frames/fps are checked exactly.
    Omit audio expectations for video-only media. No guessed defaults are applied.
    """
    if not isinstance(expected, dict):
        raise ValueError('expected must be an object')
    allowed = {'duration', 'duration_tolerance', 'frames', 'fps', 'width', 'height', 'audio_rate', 'channels'}
    if set(expected) - allowed:
        raise ValueError(f'unknown media expectations: {sorted(set(expected) - allowed)}')
    numeric = {key: _number(value, key, positive=key != 'duration_tolerance') for key, value in expected.items()}
    for key in ('frames', 'width', 'height', 'audio_rate', 'channels'):
        if key in numeric and numeric[key].denominator != 1:
            raise ValueError(f'{key} must be an integer')
    source = Path(path)
    if not source.is_file():
        raise ValueError(f'media file not found: {source}')
    digest = _sha256(source)
    probe = json.loads(_run([ffprobe, '-v', 'error', '-count_frames', '-show_streams', '-show_format', '-of', 'json', str(source)]).stdout)
    videos = [s for s in probe.get('streams', []) if s.get('codec_type') == 'video']
    audio = [s for s in probe.get('streams', []) if s.get('codec_type') == 'audio']
    errors = []
    if not videos and not audio:
        errors.append('no usable video or audio streams')
    def check(key, actual):
        try:
            actual = Fraction(str(actual))
        except (ValueError, ZeroDivisionError):
            errors.append(f'{key}: unavailable ({actual})')
            return
        tolerance = numeric.get('duration_tolerance', Fraction(1, 1000)) if key == 'duration' else 0
        if abs(actual - numeric[key]) > tolerance:
            errors.append(f'{key}: expected {numeric[key]}, got {actual}')
    if 'duration' in numeric:
        check('duration', probe.get('format', {}).get('duration'))
        for stream in videos + audio:
            if stream.get('duration') is not None:
                check('duration', stream['duration'])
    for key, field in [('frames', 'nb_read_frames'), ('fps', 'avg_frame_rate'), ('width', 'width'), ('height', 'height')]:
        if key in numeric:
            if len(videos) != 1:
                errors.append(f'{key}: expected one video stream, got {len(videos)}')
            else:
                check(key, videos[0].get(field))
    for key, field in [('audio_rate', 'sample_rate'), ('channels', 'channels')]:
        if key in numeric:
            if len(audio) != 1:
                errors.append(f'{key}: expected one audio stream, got {len(audio)}')
            else:
                check(key, audio[0].get(field))
    if full_decode:
        try:
            _run([ffmpeg, '-v', 'error', '-xerror', '-i', str(source), '-map', '0:v?', '-map', '0:a?', '-f', 'null', '-'])
        except ValueError as exc:
            errors.append(str(exc))
    if _sha256(source) != digest:
        errors.append('media changed during validation; retry on an immutable asset')
    return dict(ok=not errors, errors=errors, path=str(source.resolve()), sha256=digest, probe=probe, full_decode=full_decode)


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def detect_audio_gaps(path, allowed_quiet=None, noise_db=-50, min_duration=0.5, ffmpeg='ffmpeg'):
    """Detect all-channel quiet; subtract declared intervals before flagging gaps.

    allowed_quiet entries are [start_seconds, end_seconds]. A remaining interval
    at least min_duration is unplanned. This cannot establish missing speech/music.
    """
    minimum = float(_number(min_duration, 'min_duration', positive=True))
    if isinstance(noise_db, bool):
        raise ValueError('noise_db must be finite')
    try:
        noise = float(Fraction(str(noise_db)))
    except (ValueError, ZeroDivisionError) as exc:
        raise ValueError('noise_db must be finite') from exc
    if noise >= 0:
        raise ValueError('noise_db must be negative')
    if allowed_quiet is not None and not isinstance(allowed_quiet, list):
        raise ValueError('allowed_quiet must be a list of intervals')
    intervals = []
    for interval in allowed_quiet or []:
        if not isinstance(interval, (list, tuple)) or len(interval) != 2:
            raise ValueError('allowed quiet interval must be [start, end]')
        start, end = (float(_number(x, 'quiet interval')) for x in interval)
        if end <= start:
            raise ValueError('quiet interval end must exceed start')
        intervals.append((start, end))
    digest = _sha256(path)
    result = _run([ffmpeg, '-hide_banner', '-nostats', '-i', str(path), '-map', '0:a:0',
                   '-af', f'silencedetect=noise={noise}dB:d={minimum}', '-f', 'null', '-'])
    starts, gaps = [], []
    for kind, value in re.findall(r'silence_(start|end):\s*([0-9.eE+-]+)', result.stderr):
        if kind == 'start':
            starts.append(float(value))
        elif starts:
            gaps.append([starts.pop(0), float(value)])
    # FFmpeg emits silence_end at EOF, including a wholly silent track.
    unplanned = []
    for start, end in gaps:
        fragments = [(start, end)]
        for left, right in intervals:
            remaining = []
            for a, b in fragments:
                if right <= a or left >= b:
                    remaining.append((a, b))
                else:
                    if a < left:
                        remaining.append((a, left))
                    if right < b:
                        remaining.append((right, b))
            fragments = remaining
        unplanned.extend([a, b] for a, b in fragments if b - a >= minimum - 1e-6)
    unchanged = _sha256(path) == digest
    return dict(ok=not unplanned and unchanged, sha256=digest, source_unchanged=unchanged,
                gaps=gaps, allowed_quiet=intervals, unplanned=unplanned,
                noise_db=noise, min_duration=minimum, limitation='Signal silence only; no listening or semantic assessment.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('spec', type=Path)
    parser.add_argument('--report', type=Path, required=True, help='new report path; existing files are never overwritten')
    parser.add_argument('--full-decode', action='store_true')
    args = parser.parse_args(argv)
    try:
        spec_bytes = args.spec.read_bytes()
        spec = json.loads(spec_bytes.decode('utf-8-sig'))
        report = {}
        if 'shots' in spec:
            report['timeline'] = build_timeline(spec['shots'], spec.get('fps', 24), spec.get('cues'), spec.get('sample_rate', 48000))
        if 'word_checks' in spec:
            if not isinstance(spec['word_checks'], list) or not spec['word_checks']:
                raise ValueError('word_checks must be a nonempty list')
            report['words'] = [compare_words(item['intended'], item['transcript']) for item in spec['word_checks']]
        if 'media' in spec:
            report['media'] = validate_media(spec['media'], spec.get('expected', {}), args.full_decode)
            if 'allowed_quiet' in spec or spec.get('check_audio_gaps'):
                report['audio_gaps'] = detect_audio_gaps(spec['media'], spec.get('allowed_quiet'), spec.get('noise_db', -50), spec.get('min_silence', 0.5))
        if not report:
            raise ValueError('spec must request timeline, word_checks, or media validation')
        report['ok'] = all(value.get('ok', True) if isinstance(value, dict) else all(x['ok'] for x in value) for value in report.values())
        report['spec_sha256'] = hashlib.sha256(spec_bytes).hexdigest()
        with args.report.open('x', encoding='utf-8') as handle:
            json.dump(report, handle, indent=2)
        print(json.dumps(dict(ok=report['ok'], report=str(args.report.resolve()))))
        return 0 if report['ok'] else 1
    except (ValueError, KeyError, TypeError, OSError) as exc:
        parser.exit(2, f'validation error: {exc}\n')


if __name__ == '__main__':
    raise SystemExit(main())
