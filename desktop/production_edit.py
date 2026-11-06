"""Frame-grid picture edits, independent sample-grid sound, streamed local FFmpeg cuts."""
import copy
from fractions import Fraction
import json
from pathlib import Path
import subprocess
import tempfile
import uuid

import production_jobs as jobs
import production_media as media
from production_project import ProjectError

RUN_METRICS = {'peak_child_working_set_bytes': 0, 'processes': 0}


def measure_process(process):
    """Windows retains peak working-set counters on the process handle after exit."""
    import os
    if os.name != 'nt':
        return
    import ctypes
    from ctypes import wintypes
    class Counters(ctypes.Structure):
        _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD)] + [(name, ctypes.c_size_t) for name in
                    ('PeakWorkingSetSize', 'WorkingSetSize', 'QuotaPeakPagedPoolUsage', 'QuotaPagedPoolUsage',
                     'QuotaPeakNonPagedPoolUsage', 'QuotaNonPagedPoolUsage', 'PagefileUsage', 'PeakPagefileUsage')]
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    if ctypes.windll.psapi.GetProcessMemoryInfo(wintypes.HANDLE(int(process._handle)), ctypes.byref(counters), counters.cb):
        RUN_METRICS['peak_child_working_set_bytes'] = max(RUN_METRICS['peak_child_working_set_bytes'], counters.PeakWorkingSetSize)


def integer(value, label, minimum=0):
    if type(value) is not int or value < minimum:
        raise ProjectError('invalid-input', label + ' must be an integer >= ' + str(minimum))
    return value


def flatten(edit):
    fps = Fraction(str(edit['fps']))
    if fps <= 0 or fps > 120:
        raise ProjectError('invalid-input', 'Frame rate must be positive and at most 120')
    rate = integer(edit['sample_rate'], 'Sample rate', 8000)
    cursor, shots, ids = 0, [], set()
    for segment in edit['segments']:
        occurrence = segment['id']
        if occurrence in ids:
            raise ProjectError('invalid-input', 'Segment occurrences must have unique IDs')
        ids.add(occurrence)
        start = integer(segment['in_frame'], 'Source in')
        end = integer(segment['out_frame'], 'Source out', start + 1)
        length = end - start
        if segment.get('transition', 'cut') != 'cut':
            raise ProjectError('unsupported', 'Only declared hard cuts are currently composited')
        shots.append(dict(id=occurrence, shot=segment.get('shot'), asset=segment.get('asset'),
                          track='picture', in_frame=start, out_frame=end, start_frame=cursor,
                          end_frame=cursor + length, start=str(Fraction(cursor, 1) / fps),
                          end=str(Fraction(cursor + length, 1) / fps), gap=not segment.get('asset'),
                          transition='cut', volume=float(segment.get('volume', 1)),
                          mute=bool(segment.get('mute', False)), fade_in=segment.get('fade_in', 0),
                          fade_out=segment.get('fade_out', 0)))
        cursor += length
    for cue in edit['audio']:
        integer(cue['start_sample'], 'Audio cue')
        integer(cue.get('in_sample', 0), 'Audio source in')
        integer(cue['samples'], 'Audio duration', 1)
        if cue.get('track') not in ('dialogue', 'music', 'effects'):
            raise ProjectError('invalid-input', 'Audio needs a dialogue, music or effects track')
        volume = cue.get('volume', 1)
        if not isinstance(volume, (int, float)) or not 0 <= volume <= 8:
            raise ProjectError('invalid-input', 'Audio volume must be 0–8')
    for marker in edit.get('markers', []):
        integer(marker['frame'], 'Marker frame')
    return dict(version=2, fps=str(fps), frames=cursor, shots=shots, audio=edit['audio'], sample_rate=rate,
                boundaries=[{'frame': s['start_frame'], 'kind': 'hard-cut',
                             'before': shots[i-1]['id'], 'after': s['id']}
                            for i, s in enumerate(shots) if i])


def change(value, operation, data):
    if operation in ('undo', 'redo'):
        source, target = ('undo', 'redo') if operation == 'undo' else ('redo', 'undo')
        if not value[source]:
            raise ProjectError('invalid-input', 'No edit to ' + operation)
        value[target].append(copy.deepcopy(value['edit']))
        value['edit'] = value[source].pop()
        return {'edit': operation}
    old = copy.deepcopy(value['edit'])
    edit = value['edit']
    segments = edit['segments']
    if operation == 'edit-replace':
        value['edit'] = copy.deepcopy(data['edit'])
    elif operation == 'segment-insert':
        segment = copy.deepcopy(data['segment'])
        segment['id'] = uuid.uuid4().hex
        segments.insert(integer(data.get('index', len(segments)), 'Insert index'), segment)
    elif operation == 'segment-update':
        segment = next((s for s in segments if s['id'] == data['segment']), None)
        if segment is None:
            raise ProjectError('invalid-input', 'Select a timeline segment')
        changes = data['changes']
        if set(changes) - {'in_frame', 'out_frame', 'volume', 'mute', 'fade_in', 'fade_out'}:
            raise ProjectError('invalid-input', 'Unknown trim/mix field')
        segment.update(changes)
    elif operation == 'segment-split':
        index = next((i for i, s in enumerate(segments) if s['id'] == data['segment']), None)
        if index is None:
            raise ProjectError('invalid-input', 'Select a timeline segment')
        segment = segments[index]
        at = integer(data['source_frame'], 'Split frame')
        if not segment['in_frame'] < at < segment['out_frame']:
            raise ProjectError('invalid-input', 'Split must be inside the source interval')
        right = {**segment, 'id': uuid.uuid4().hex, 'in_frame': at}
        segment['out_frame'] = at
        segments.insert(index + 1, right)
    elif operation == 'segment-move':
        index = next((i for i, s in enumerate(segments) if s['id'] == data['segment']), None)
        if index is None:
            raise ProjectError('invalid-input', 'Select a timeline segment')
        segments.insert(integer(data['index'], 'Move index'), segments.pop(index))
    elif operation == 'segment-remove':
        index = next((i for i, s in enumerate(segments) if s['id'] == data['segment']), None)
        if index is None:
            raise ProjectError('invalid-input', 'Select a timeline segment')
        segment = segments[index]
        if data.get('ripple', False):
            segments.pop(index)
        else:
            segment['asset'] = None
    elif operation in ('audio-add', 'marker-add', 'title-add'):
        key = {'audio-add': 'audio', 'marker-add': 'markers', 'title-add': 'titles'}[operation]
        edit[key].append({**data['item'], 'id': uuid.uuid4().hex})
    elif operation == 'audio-update':
        cue = next((a for a in edit['audio'] if a['id'] == data['cue']), None)
        if cue is None:
            raise ProjectError('invalid-input', 'Select an audio cue')
        if set(data['changes']) - {'start_sample', 'in_sample', 'samples', 'volume', 'mute', 'fade_in', 'fade_out'}:
            raise ProjectError('invalid-input', 'Unknown audio field')
        cue.update(data['changes'])
    elif operation in ('audio-remove', 'marker-remove', 'title-remove'):
        key = {'audio-remove': 'audio', 'marker-remove': 'markers', 'title-remove': 'titles'}[operation]
        existing = next((row for row in edit[key] if row['id'] == data['id']), None)
        if not existing:
            raise ProjectError('invalid-input', 'Select an existing timeline item')
        edit[key].remove(existing)
    else:
        raise ProjectError('unknown-operation', operation)
    flatten(value['edit'])
    value['undo'].append(old)
    value['redo'] = []
    return {'edit': operation}


def run(args, timeout, cancel=None):
    import time
    flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
    with subprocess.Popen([str(a) for a in args], stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=flags) as process:
        RUN_METRICS['processes'] += 1
        deadline = time.monotonic() + timeout
        try:
            while True:
                try:
                    stdout, stderr = process.communicate(timeout=max(.001, min(.1, deadline-time.monotonic())))
                    break
                except subprocess.TimeoutExpired:
                    measure_process(process)
                    if time.monotonic() >= deadline:
                        raise
        except (subprocess.TimeoutExpired, BaseException):
            process.kill()
            process.communicate()
            raise
        if process.returncode:
            raise ProjectError('media-error', stderr.decode('utf-8', 'replace')[-4000:])
        measure_process(process)
        return stdout


def probe(path, ffprobe):
    return json.loads(run([ffprobe, '-v', 'error', '-show_streams', '-show_format', '-of', 'json', path], 30))


def validate_cfr(path, fps, ffprobe):
    frames = json.loads(run([ffprobe, '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                             'frame=best_effort_timestamp_time', '-of', 'json', path], 120)).get('frames', [])
    if not frames:
        raise ProjectError('invalid-input', 'Source has no decodable picture frames')
    times = [Fraction(f['best_effort_timestamp_time']) for f in frames]
    step = 1 / Fraction(fps)
    if any(abs((b-a)-step) > Fraction(1, 500000) for a, b in zip(times, times[1:])):
        raise ProjectError('unsupported', 'Variable-rate or differing-rate source must be explicitly normalized before editing')
    return len(times)


def assemble(root, value, destination, tools, *, animatic=False, width=1280, height=720):
    """Decode one picture segment at a time; concat streams without re-encoding the prefix."""
    edit = copy.deepcopy(value['edit'])
    assets = {a['id']: a for a in value['assets']}
    if animatic:
        edit['segments'] = []
        for shot in value['shots']:
            keyframe = next((r['asset'] for r in shot['references'] if r['role'] == 'keyframe'), None)
            edit['segments'].append(dict(id=uuid.uuid4().hex, shot=shot['id'], asset=keyframe,
                                         in_frame=0, out_frame=shot['edit_frames']))
    timeline = flatten(edit)
    if not timeline['frames']:
        raise ProjectError('invalid-input', 'Add picture segments before rendering a cut')
    fps = Fraction(timeline['fps'])
    duration = float(Fraction(timeline['frames'], 1) / fps)
    timeout = max(60, duration * 6)
    ffmpeg, ffprobe = tools['ffmpeg'], tools['ffprobe']
    destination = Path(destination)
    if destination.exists():
        raise ProjectError('conflict', 'Cut path already exists; choose a new immutable path')
    destination.parent.mkdir(parents=True, exist_ok=True)
    incomplete = False
    dependencies = []
    source_frames = {}
    with tempfile.TemporaryDirectory(prefix='edit-', dir=destination.parent) as temporary:
        temp = Path(temporary)
        chunks = []
        for index, segment in enumerate(timeline['shots']):
            frames = segment['end_frame'] - segment['start_frame']
            asset = assets.get(segment['asset'])
            args = [ffmpeg, '-nostdin', '-v', 'error', '-y']
            filters = []
            if asset:
                source = jobs.confined(root, asset['path'])
                jobs.file_hash(source, asset['sha256'])
                dependencies.append({'path': asset['path'], 'sha256': asset['sha256']})
                still = source.suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp')
                if still:
                    args += ['-loop', '1', '-framerate', str(fps), '-i', source]
                else:
                    info = probe(source, ffprobe)
                    video = next((s for s in info['streams'] if s['codec_type'] == 'video'), None)
                    if not video or Fraction(video['avg_frame_rate']) != fps or Fraction(video['r_frame_rate']) != fps:
                        raise ProjectError('unsupported', 'Normalize source to constant ' + str(fps) + ' fps before editing')
                    if asset['sha256'] not in source_frames:
                        source_frames[asset['sha256']] = validate_cfr(source, fps, ffprobe)
                    if source_frames[asset['sha256']] < segment['out_frame']:
                        raise ProjectError('invalid-input', 'Source is shorter than its selected out frame')
                    args += ['-i', source]
                    filters += [f"trim=start_frame={segment['in_frame']}:end_frame={segment['out_frame']}", 'setpts=PTS-STARTPTS']
            else:
                incomplete = True
                args += ['-f', 'lavfi', '-i', f'color=c=0x403020:s={width}x{height}:r={fps}']
                filters.append("drawtext=text='MISSING SHOT - DRAFT':fontcolor=white:fontsize=24:x=(w-tw)/2:y=(h-th)/2")
            filters += [f'scale={width}:{height}:force_original_aspect_ratio=decrease',
                        f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2', 'setsar=1', f'fps={fps}']
            for direction in ('in', 'out'):
                fade = integer(segment.get('fade_' + direction, 0), 'Fade frames')
                if fade > frames:
                    raise ProjectError('invalid-input', 'Fade exceeds segment length')
                if fade:
                    filters.append(f'fade=t={direction}:s={0 if direction == "in" else frames-fade}:n={fade}')
            chunk = temp / (str(index) + '.mp4')
            run(args + ['-vf', ','.join(filters), '-frames:v', frames, '-an', '-c:v', 'libx264',
                        '-preset', 'veryfast', '-crf', '18', '-pix_fmt', 'yuv420p', chunk], timeout)
            chunks.append(chunk)
            if asset and not still and not segment['mute']:
                stream = next((s for s in info['streams'] if s['codec_type'] == 'audio'), None)
                if stream:
                    rate = edit['sample_rate']
                    start_sample = Fraction(segment['start_frame'] * rate, 1) / fps
                    source_sample = Fraction(segment['in_frame'] * rate, 1) / fps
                    samples = Fraction(frames * rate, 1) / fps
                    if any(n.denominator != 1 for n in (start_sample, source_sample, samples)):
                        raise ProjectError('invalid-input', 'Linked source sound does not fall on the sample grid')
                    edit['audio'].append(dict(id='linked-' + segment['id'], asset=asset['id'], track='effects',
                                              start_sample=int(start_sample), in_sample=int(source_sample),
                                              samples=int(samples), volume=segment['volume']))
        listing = temp / 'concat.txt'
        listing.write_text(''.join("file '" + c.name + "'\n" for c in chunks), encoding='utf-8')
        picture = temp / 'picture.mp4'
        run([ffmpeg, '-nostdin', '-v', 'error', '-f', 'concat', '-safe', '1', '-i', listing,
             '-c', 'copy', picture], timeout)
        args = [ffmpeg, '-nostdin', '-v', 'error', '-i', picture]
        audio_filters, audio_labels, audio_inputs = [], [], {}
        for index, cue in enumerate(edit['audio']):
            asset = assets.get(cue['asset'])
            if not asset:
                raise ProjectError('invalid-input', 'Audio cue has a missing asset')
            source = jobs.confined(root, asset['path'])
            jobs.file_hash(source, asset['sha256'])
            info = probe(source, ffprobe)
            stream = next((s for s in info['streams'] if s['codec_type'] == 'audio'), None)
            rate = edit['sample_rate']
            end = cue.get('in_sample', 0) + cue['samples']
            if not stream or float(stream.get('duration', info['format'].get('duration', 0))) * rate + 1 < end:
                raise ProjectError('invalid-input', 'Audio source is shorter than its selected interval')
            source_key = str(source)
            if source_key not in audio_inputs:
                audio_inputs[source_key] = len(audio_inputs) + 1
                args += ['-i', source]
            input_index = audio_inputs[source_key]
            label = f'a{index}'
            chain = [f'aresample={rate}', f"atrim=start_sample={cue.get('in_sample', 0)}:end_sample={end}",
                     'asetpts=PTS-STARTPTS', 'volume=' + str(0 if cue.get('mute') else cue.get('volume', 1))]
            for direction in ('in', 'out'):
                fade = integer(cue.get('fade_' + direction, 0), 'Audio fade samples')
                if fade:
                    chain.append(f"afade=t={direction}:ss={0 if direction == 'in' else max(0, cue['samples']-fade)}:ns={fade}")
            chain.append(f"adelay={cue['start_sample']}S:all=1")
            audio_filters.append(f'[{input_index}:a]' + ','.join(chain) + f'[{label}]')
            audio_labels.append(f'[{label}]')
            dependencies.append({'path': asset['path'], 'sha256': asset['sha256']})
        if audio_labels:
            samples = Fraction(timeline['frames'] * rate, 1) / fps
            if samples.denominator != 1:
                raise ProjectError('invalid-input', 'Edit duration does not end on the audio sample grid')
            audio_filters.append(''.join(audio_labels) + f'amix=inputs={len(audio_labels)}:normalize=0,apad,atrim=end_sample={int(samples)}[mix]')
            filter_file = temp / 'audio-filters.txt'
            filter_file.write_text(';'.join(audio_filters), encoding='utf-8')
            args += ['-filter_complex_script', filter_file, '-map', '0:v', '-map', '[mix]', '-c:a', 'aac', '-ar', rate, '-ac', 2]
        else:
            args += ['-f', 'lavfi', '-i', f'anullsrc=r={edit["sample_rate"]}:cl=stereo', '-map', '0:v', '-map', '1:a', '-c:a', 'aac']
        if edit.get('titles'):
            filters = []
            for index, title in enumerate(edit['titles']):
                text = str(title['text'])
                textfile = temp / f'title{index}.txt'
                textfile.write_text(text, encoding='utf-8')
                start = integer(title['start_frame'], 'Title start')
                end = integer(title['end_frame'], 'Title end', start+1)
                # Relative filename avoids drive-colon/filter escaping and command interpolation.
                filters.append(f"drawtext=textfile=title{index}.txt:expansion=none:fontcolor=white:fontsize=36:x=(w-tw)/2:y=h-th-40:enable='between(n,{start},{end-1})'")
            args += ['-vf', ','.join(filters), '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18']
        else:
            args += ['-c:v', 'copy']
        partial = temp / 'encoded.mp4'
        # FFmpeg drawtext paths are relative to this private working directory.
        previous = Path.cwd()
        try:
            import os
            os.chdir(temp)
            run(args + ['-t', f'{duration:.12f}', '-movflags', '+faststart', partial], timeout)
        finally:
            os.chdir(previous)
        expected = dict(frames=timeline['frames'], fps=str(fps), width=width, height=height,
                        duration=str(Fraction(timeline['frames'], 1) / fps), duration_tolerance='0.05',
                        audio_rate=edit['sample_rate'], channels=2)
        validation = media.validate_media(partial, expected, full_decode=True, ffmpeg=ffmpeg, ffprobe=ffprobe)
        if not validation['ok']:
            raise ProjectError('media-error', '; '.join(validation['errors']))
        with partial.open('rb') as src, destination.open('xb') as dst:
            import shutil
            shutil.copyfileobj(src, dst)
        jobs.file_hash(destination, validation['sha256'])
    return dict(path=str(destination), sha256=validation['sha256'], timeline=timeline,
                incomplete=incomplete, dependencies=dependencies, technical=validation,
                label='INCOMPLETE DRAFT' if incomplete else ('ANIMATIC — NOT A MOTION PILOT' if animatic else 'DRAFT — NOT APPROVED FOR DELIVERY'))
