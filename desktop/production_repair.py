"""Immutable repair anchors and range replacement; accepted prefixes are never re-encoded."""
import copy
from fractions import Fraction
from pathlib import Path
import uuid

import production_edit as edit
import production_jobs as jobs
import production_project as project


def source(root, value, segment):
    asset = next((a for a in value['assets'] if a['id'] == segment.get('asset')), None)
    if not asset:
        raise project.ProjectError('invalid-input', 'This repair anchor has no managed source media')
    path = jobs.confined(root, asset['path'])
    jobs.file_hash(path, asset['sha256'])
    return asset, path


def prepare(root, value, data, tools):
    operation = data['repair']
    if operation not in ('Extend', 'Bridge', 'Fill', 'Retake'):
        raise project.ProjectError('invalid-input', 'Unknown repair operation')
    if data.get('modality', 'both') not in ('picture', 'audio', 'both'):
        raise project.ProjectError('invalid-input', 'Choose picture, audio or both')
    if operation == 'Extend' and data.get('modality') == 'audio':
        raise project.ProjectError('unsupported', 'Audio-only extension needs an explicit picture hold policy. Add an independent audio cue instead.')
    segments = value['edit']['segments']
    index = next((i for i, s in enumerate(segments) if s['id'] == data['segment']), None)
    if index is None:
        raise project.ProjectError('invalid-input', 'Select the exact timeline occurrence to repair')
    segment = copy.deepcopy(segments[index])
    frames = edit.integer(data['frames'], 'Repair frames', 1)
    if frames > 240:
        raise project.ProjectError('unsupported', 'Repair one short section of at most 240 edit frames at a time')
    fps = Fraction(value['edit']['fps'])
    if fps != 24:
        raise project.ProjectError('unsupported', 'The H3 repair profile requires an explicitly normalized 24 fps edit')
    anchors = dict(segment=segment, left=copy.deepcopy(segments[index-1]) if index else None,
                   right=copy.deepcopy(segments[index+1]) if index+1 < len(segments) else None)
    request = copy.deepcopy(data['request'])
    request['Prompt'] = data['prompt']
    request['Profile'] = 'pika-flex'
    request['Source'] = request['LastFrame'] = request['AudioGuide'] = request['GuideVideo'] = None
    request['LastFrameAt'] = None
    fingerprint = jobs.digest(jobs.canonical(dict(binding_version=2, operation=operation, anchors=anchors, frames=frames,
                    modality=data.get('modality', 'both'), prompt=data['prompt'], request=request, active=project.edit_token(value))))
    directory = root / 'repair-inputs' / fingerprint
    directory.mkdir(parents=True, exist_ok=True)
    overlap = 0
    def still(anchor, frame, name):
        asset, media = source(root, value, anchor)
        if edit.validate_cfr(media, fps, tools['ffprobe']) <= frame:
            raise project.ProjectError('invalid-input', 'Repair endpoint is outside the actual source frames')
        destination = directory / (name + '.png')
        if not destination.exists():
            edit.run([tools['ffmpeg'], '-nostdin', '-v', 'error', '-i', media, '-vf',
                      'select=eq(n\\,' + str(frame) + ')', '-frames:v', '1', destination], 60)
        jobs.file_hash(destination)
        return str(destination)
    if operation == 'Extend':
        asset, media = source(root, value, segment)
        if edit.validate_cfr(media, fps, tools['ffprobe']) < segment['out_frame']:
            raise project.ProjectError('invalid-input', 'Continuation tail exceeds the actual source frames')
        overlap = 22
        if segment['out_frame'] - segment['in_frame'] < overlap:
            raise project.ProjectError('invalid-input', 'Continuation needs at least 22 accepted tail frames')
        guide = directory / 'tail.mkv'
        if not guide.exists():
            edit.run([tools['ffmpeg'], '-nostdin', '-v', 'error', '-i', media, '-vf',
                      f"trim=start_frame={segment['out_frame']-overlap}:end_frame={segment['out_frame']},setpts=PTS-STARTPTS",
                      '-frames:v', str(overlap), '-an', '-c:v', 'ffv1', guide], 60)
        request['GuideVideo'] = str(guide)
        request['GuideAudio'] = False
    elif operation in ('Fill', 'Bridge'):
        if segment.get('asset') is not None:
            raise project.ProjectError('invalid-input', 'Bridge / Fill replace an explicit gap occurrence; leave a gap first')
        frames = segment['out_frame']-segment['in_frame']
        if frames > 240:
            raise project.ProjectError('unsupported', 'Split a long gap into short repair sections first')
        if anchors['left']:
            request['Source'] = still(anchors['left'], anchors['left']['out_frame']-1, 'left')
        if anchors['right']:
            request['LastFrame'] = still(anchors['right'], anchors['right']['in_frame'], 'right')
        if operation == 'Bridge' and (not request['Source'] or not request['LastFrame']):
            raise project.ProjectError('invalid-input', 'A bridge requires both real footage endpoint anchors')
    else:
        start = edit.integer(data['in_frame'], 'Retake source in')
        end = edit.integer(data['out_frame'], 'Retake source out', start+1)
        if not segment['in_frame'] <= start < end <= segment['out_frame']:
            raise project.ProjectError('invalid-input', 'Retake range must be inside this source occurrence')
        frames = end-start
        if frames > 240:
            raise project.ProjectError('unsupported', 'Retake one short section of at most 240 frames')
        request['Source'] = still(segment, start, 'start')
        request['LastFrame'] = still(segment, end-1, 'end')
    request['Seconds'] = max(5, (frames + overlap + 23)//24)
    if request['LastFrame']:
        request['LastFrameAt'] = overlap + frames - 1
    if request['Seconds'] > 10:
        raise project.ProjectError('unsupported', 'This guide plus repair exceeds the supported ten-second graph profile')
    record = dict(id=fingerprint, binding_version=2, operation=operation, anchors=anchors, edit_projection=project.edit_token(value),
                  frames=frames, overlap_frames=overlap, source_in_frame=overlap, source_out_frame=overlap+frames,
                  retake_in=data.get('in_frame'), retake_out=data.get('out_frame'), modality=data.get('modality', 'both'),
                  defect=data['defect'], request=request, status='UNVERIFIED CONDITIONING / SEAM — bounded pilot required',
                  audio_policy='Detached cues keep explicit sample positions; linked source audio follows picture occurrences')
    jobs.immutable_bytes(directory / 'repair.json', jobs.canonical(record))
    return record


def place(value, repair, asset_id):
    if project.edit_token(value) != repair['edit_projection']:
        raise project.ProjectError('conflict', 'Picture, neighbours or mix changed while this repair ran. Replan against current anchors.')
    segments = value['edit']['segments']
    original = repair['anchors']['segment']
    index = next((i for i, s in enumerate(segments) if s['id'] == original['id']), None)
    if index is None or segments[index] != original:
        raise project.ProjectError('conflict', 'Repair occurrence changed; no replacement was applied')
    replacement = dict(id=uuid.uuid4().hex, shot=original.get('shot'), asset=asset_id,
                       in_frame=repair['source_in_frame'], out_frame=repair['source_out_frame'],
                       repair=repair['id'], mute=repair['modality'] == 'picture')
    value['undo'].append(copy.deepcopy(value['edit'])); value['redo'] = []
    if repair['operation'] == 'Extend':
        segments.insert(index+1, replacement)
    elif repair['operation'] in ('Bridge', 'Fill'):
        if repair['modality'] == 'audio':
            start = sum(s['out_frame']-s['in_frame'] for s in segments[:index])
            rate = value['edit']['sample_rate']
            value['edit']['audio'].append(dict(id=uuid.uuid4().hex, asset=asset_id, track='effects',
                start_sample=start*rate//24, in_sample=repair['source_in_frame']*rate//24,
                samples=repair['frames']*rate//24, volume=1, mute=False))
        else:
            segments[index:index+1] = [replacement]
    else:
        left, right = repair['retake_in'], repair['retake_out']
        parts = []
        if left > original['in_frame']:
            parts.append({**original, 'out_frame': left})
        start_frame = sum(s['out_frame']-s['in_frame'] for s in segments[:index]) + left-original['in_frame']
        rate = value['edit']['sample_rate']
        if repair['modality'] == 'audio':
            parts.append({**original, 'id': uuid.uuid4().hex, 'in_frame': left, 'out_frame': right, 'mute': True})
            sound_asset, sound_in = asset_id, repair['source_in_frame']
        else:
            parts.append(replacement)
            sound_asset, sound_in = original['asset'], left
        if repair['modality'] in ('audio', 'picture'):
            value['edit']['audio'].append(dict(id=uuid.uuid4().hex, asset=sound_asset, track='effects',
                start_sample=start_frame*rate//24, in_sample=sound_in*rate//24,
                samples=repair['frames']*rate//24, volume=original.get('volume', 1), mute=original.get('mute', False)))
        if right < original['out_frame']:
            parts.append({**original, 'id': uuid.uuid4().hex, 'in_frame': right})
        segments[index:index+1] = parts
    edit.flatten(value['edit'])
    return {'repair': repair['id'], 'status': 'placed; exact seam and final performance remain unverified'}
