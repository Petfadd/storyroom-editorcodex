"""Deterministic validation and review state for Pipeline v5 Beat scripts.

This module never selects footage and never edits Beat ranges. It validates the
script's explicit decisions, binds human review to the exact script and source
files, and reports the frame quantisation required by the renderer.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from documentary_beats import is_strict_pipeline_script, read_beats

OUTPUT_FPS = 30
OUTPUT_FRAME_MS = 1000 / OUTPUT_FPS


def script_hash(project):
    return hashlib.sha256(((project.get('production_script') or {}).get('text') or '').encode()).hexdigest()


def _asset_matches(project, filename):
    return [a for a in project.get('assets') or []
            if (a.get('original_name') or a.get('name')) == filename]


def _is_broll_asset(asset):
    provenance=asset.get('provenance') or {}
    labels=[asset.get('category'), provenance.get('kind'), provenance.get('type'),
            provenance.get('media'), provenance.get('origin'), provenance.get('note')]
    words=' '.join(str(value or '') for value in labels).casefold()
    compact=re.sub(r'[^a-z0-9]+','',words)
    return any(token in compact for token in ('broll','basefootage'))


def _is_derived_broll(asset):
    """B-roll and derived assets can be visuals, but never soundbite audio."""
    return bool(asset.get('derived_from')) or _is_broll_asset(asset)


def _underlying_source_window(asset, beat, origin):
    """Map a trimmed B-roll local range back to its approved source window when known."""
    source_in, source_out = beat['source_in_ms'], beat['source_out_ms']
    provenance = asset.get('provenance') or {}
    if _is_broll_asset(asset):
        window = provenance.get('window')
        if isinstance(window, (list, tuple)) and len(window) == 2:
            try:
                original_in, original_out = (float(value) * 1000 for value in window)
                if original_out > original_in and source_out <= original_out - original_in + 1:
                    return str(origin), original_in + source_in, original_in + source_out
            except (TypeError, ValueError):
                pass
        # Without an explicit source-window map, compare only this exact local file.
        return f"asset:{asset.get('id') or beat['source_file']}", source_in, source_out
    return str(origin), source_in, source_out


def source_signatures(project, root, beats=None):
    root = Path(root).resolve()
    beats = beats if beats is not None else read_beats((project.get('production_script') or {}).get('text', ''), strict=True)
    names = {b['source_file'] for b in beats}
    rows = []
    for name in sorted(names):
        matches = _asset_matches(project, name)
        if len(matches) != 1:
            rows.append({'filename': name, 'missing_or_ambiguous': len(matches)})
            continue
        asset = matches[0]
        path = (root / str(asset.get('path') or '')).resolve()
        try:
            stat = path.stat()
            file_signature = [stat.st_size, stat.st_mtime_ns]
        except OSError:
            file_signature = [None, None]
        rows.append({'filename': name, 'asset_id': asset.get('id'),
                     'revision': asset.get('revision'), 'path': str(path),
                     'file': file_signature})
    return rows


def _frame_details(path, start_ms, end_ms):
    """Return requested and nearest real source frame boundaries when readable."""
    try:
        from fractions import Fraction
        from strict_cuts import source_rate, _nearest_frame
        rate = Fraction(source_rate(path))
        start_frame, end_frame = _nearest_frame(start_ms, rate, half_up=True), _nearest_frame(end_ms, rate, half_up=True)
        actual_in = float(Fraction(start_frame * 1000, 1) / rate)
        actual_out = float(Fraction(end_frame * 1000, 1) / rate)
        return {'source_fps': str(rate), 'requested_in_ms': start_ms,
                'requested_out_ms': end_ms, 'frame_in': start_frame,
                'frame_out_exclusive': end_frame, 'frame_aligned_in_ms': actual_in,
                'frame_aligned_out_ms': actual_out,
                'in_delta_ms': actual_in - start_ms,
                'out_delta_ms': actual_out - end_ms,
                'duration_delta_ms': (actual_out - actual_in) - (end_ms - start_ms)}
    except Exception:
        return {'requested_in_ms': start_ms, 'requested_out_ms': end_ms,
                'frame_quantization_status': 'unavailable'}


def validate(project, root, beats=None, frame_limits=None):
    """Return blocking issues and exact source/frame details for strict Beats."""
    root = Path(root).resolve()
    text = (project.get('production_script') or {}).get('text') or ''
    if not is_strict_pipeline_script(text):
        return {'strict': False, 'issues': [], 'beats': [], 'frame_ranges': {}}
    issues = []
    try:
        beats = beats if beats is not None else read_beats(text, strict=True)
    except ValueError as exc:
        return {'strict': True, 'issues': [str(exc)], 'beats': [], 'frame_ranges': {}}
    if frame_limits is None:
        try:
            from documentary_beat_plan import frame_limits as read_frame_limits
            frame_limits = read_frame_limits(root, project.get('assets') or [])
        except Exception:
            frame_limits = {}
    frame_ranges = {}
    by_filename = {}
    source_windows = {}
    source_uses = {}
    underlying_source_windows = {}
    narration_cursor = 0
    master_cursor = 0
    srt = (project.get('srt') or {}).get('blocks') or []

    for index, beat in enumerate(beats):
        label = beat['label']
        name = beat['source_file']
        requested = f'{beat["source_in_ms"]/1000:.3f}–{beat["source_out_ms"]/1000:.3f}s'
        matches = _asset_matches(project, name)
        if len(matches) != 1:
            issue = 'is missing' if not matches else f'is ambiguous ({len(matches)} exact filename matches)'
            issues.append(f'Beat {label}: exact source {name} {issue}; requested range {requested}. Upload exactly one matching original video; no substitute was selected.')
            continue
        asset = matches[0]
        by_filename[name] = asset
        beat['asset_id'] = asset.get('id')
        path = (root / str(asset.get('path') or '')).resolve()
        invalid_derived_video = bool(asset.get('derived_from')) and not _is_broll_asset(asset)
        if (asset.get('kind') != 'video' or invalid_derived_video
                or not path.is_relative_to(root / 'sources') or not path.is_file()):
            if beat['kind']=='sound_bite' and _is_derived_broll(asset):
                issues.append(f'Beat {label}: {name} is a B-roll or derived asset and cannot supply soundbite audio. Use the exact original uploaded source video.')
            else:
                issues.append(f'Beat {label}: {name} is not an available uploaded video asset; requested range {requested}. Re-upload the exact named source.')
            continue

        if beat['kind']=='sound_bite' and _is_derived_broll(asset):
            issues.append(f'Beat {label}: {name} is a B-roll or derived asset and cannot supply soundbite audio. Use the exact original source video named in the script.')

        available_ms = float(asset.get('duration') or 0) * 1000
        frame_limit = (frame_limits or {}).get(asset.get('id'))
        if frame_limit is not None:
            available_ms = min(available_ms, float(frame_limit))
        if beat['source_in_ms'] < 0 or beat['source_out_ms'] <= beat['source_in_ms']:
            issues.append(f'Beat {label}: invalid source range {requested} in {name}. Correct Source IN/OUT in the production script.')
        if beat['source_out_ms'] > available_ms + 0.001:
            issues.append(f'Beat {label}: {name} provides {available_ms/1000:.3f}s, but the script requests {requested}. Correct Source OUT or upload the full-length named source; Storyroom will not clamp it.')

        source_duration = beat['source_out_ms'] - beat['source_in_ms']
        if beat['kind'] == 'narration':
            narration_duration = beat['narration_out_ms'] - beat['narration_in_ms']
            delta = source_duration - narration_duration
            if abs(delta) > OUTPUT_FRAME_MS:
                issues.append(f'Beat {label}: source range {requested} is {source_duration/1000:.3f}s, but narration clock is {beat["narration_in_ms"]/1000:.3f}–{beat["narration_out_ms"]/1000:.3f}s ({narration_duration/1000:.3f}s); mismatch {delta/1000:+.3f}s exceeds one {OUTPUT_FPS} fps frame. Correct the script range or narration clock.')
            if beat['narration_in_ms'] != narration_cursor:
                relation = 'overlap' if beat['narration_in_ms'] < narration_cursor else 'gap'
                issues.append(f'Beat {label}: narration {relation} from {narration_cursor/1000:.3f}s to {beat["narration_in_ms"]/1000:.3f}s. Add or correct the VO Beat in the production script; no filler was inserted.')
            narration_cursor = beat['narration_out_ms']
        else:
            if beat.get('pause_ms') != narration_cursor:
                issues.append(f'Beat {label}: declared narration pause {beat.get("pause_ms", 0)/1000:.3f}s does not match the current narration clock {narration_cursor/1000:.3f}s.')
            if beat.get('duration_ms') != source_duration:
                issues.append(f'Beat {label}: soundbite duration does not match its exact source range {requested}. Correct Duration or Source IN/OUT in the script.')
            if not beat.get('speaker'):
                issues.append(f'Beat {label}: the soundbite has no declared speaker. Add Speaker to the production script for human review.')
            if beat.get('master_in_ms') is not None and index and beats[index-1]['kind'] == 'sound_bite':
                previous = beats[index-1]
                if previous.get('pause_ms') == beat.get('pause_ms'):
                    # Script order, exact pause, speaker, source and Anchor ID are
                    # retained on each bite. The builder does not merge or reorder.
                    pass

        if beat.get('master_in_ms') is not None:
            duration = beat['master_out_ms'] - beat['master_in_ms']
            if beat['master_in_ms'] != master_cursor:
                relation = 'overlap' if beat['master_in_ms'] < master_cursor else 'gap'
                issues.append(f'Beat {label}: master timeline {relation} from {master_cursor/1000:.3f}s to {beat["master_in_ms"]/1000:.3f}s. Correct the script master timestamps; Storyroom will not shift the Beat.')
            expected_duration = beat.get('duration_ms') if beat['kind'] == 'sound_bite' else beat['narration_out_ms'] - beat['narration_in_ms']
            if duration != expected_duration:
                issues.append(f'Beat {label}: master range is {duration/1000:.3f}s, expected {expected_duration/1000:.3f}s from the exact Beat duration.')
            if (beat.get('master_source_duration_mismatch_ms') is not None
                    and abs(beat['master_source_duration_mismatch_ms']) > OUTPUT_FRAME_MS):
                issues.append(f'Beat {label}: master timeline duration differs from its exact source range by {beat["master_source_duration_mismatch_ms"]/1000:+.3f}s.')
            master_cursor = beat['master_out_ms']

        source_windows.setdefault(name, []).append((beat['source_in_ms'], beat['source_out_ms'], label))
        provenance=asset.get('provenance') or {}
        origin=(provenance.get('video_id') or provenance.get('source_id') or provenance.get('url')
                or (asset.get('derived_from') or {}).get('asset_id') or asset.get('id') or name)
        window_clock, underlying_in, underlying_out = _underlying_source_window(asset, beat, origin)
        underlying_source_windows.setdefault(window_clock, []).append(
            (underlying_in, underlying_out, label, name))
        if beat.get('master_in_ms') is not None:
            source_uses.setdefault(str(origin),[]).append({
                'master_in': beat['master_in_ms'], 'master_out': beat['master_out_ms'],
                'label': label, 'name': name, 'window_clock': window_clock,
                'source_in': underlying_in, 'source_out': underlying_out})
        frame_ranges[label] = _frame_details(path, beat['source_in_ms'], beat['source_out_ms'])

    # Repeating an authentic source interval is allowed in every documentary.
    # Keep a nonblocking ledger for editors who want to review repeated visuals.
    reuse_notes = []
    for name, windows in source_windows.items():
        for i, (start, end, label) in enumerate(windows):
            for old_start, old_end, old_label in windows[:i]:
                if start < old_end and end > old_start:
                    reuse_notes.append(f'Beats {old_label} and {label} reuse {name} (allowed).')
    for windows in underlying_source_windows.values():
        for i, (start, end, label, name) in enumerate(windows):
            for old_start, old_end, old_label, old_name in windows[:i]:
                if name != old_name and start < old_end and end > old_start:
                    reuse_notes.append(f'Beats {old_label} and {label} reuse underlying footage from {old_name} / {name} (allowed).')

    if not srt:
        issues.append('Upload the production narration SRT before strict Beat execution.')
    else:
        final_srt_ms = max(int(b.get('end_ms') or 0) for b in srt)
        if narration_cursor != final_srt_ms:
            issues.append(f'The last narration Beat ends at {narration_cursor/1000:.3f}s, but the SRT ends at {final_srt_ms/1000:.3f}s. Correct the production script; no picture gap was filled.')
        for beat in beats:
            if beat['kind'] != 'narration':
                continue
            beat['srt_cues'] = [dict(number=b.get('number'), start_ms=b.get('start_ms'), end_ms=b.get('end_ms'), text=b.get('text',''))
                                for b in srt if b.get('start_ms', 0) < beat['narration_out_ms'] and b.get('end_ms', 0) > beat['narration_in_ms']]
            beat['srt_text'] = ' '.join(c['text'] for c in beat['srt_cues'])

    voice = project.get('voiceover') or {}
    if not voice:
        issues.append('Upload the original narration before strict Beat execution.')
    elif voice.get('duration') is not None and srt:
        srt_end = max(int(b.get('end_ms') or 0) for b in srt) / 1000
        # A sound container can report a duration a few milliseconds beyond
        # the SRT's last timestamp. Treat one sub-frame remainder as rounding,
        # not as missing narration; keep the real audio intact.
        if abs(float(voice['duration']) - srt_end) > OUTPUT_FRAME_MS / 1000:
            issues.append(f'Uploaded narration is {float(voice["duration"]):.3f}s but the SRT ends at {srt_end:.3f}s. The difference exceeds one output video frame; correct the SRT or upload the matching narration.')

    return {'strict': True, 'issues': list(dict.fromkeys(issues)), 'reuse_notes': list(dict.fromkeys(reuse_notes)), 'beats': beats,
            'frame_ranges': frame_ranges, 'source_signatures': source_signatures(project, root, beats),
            'narration_duration_ms': narration_cursor, 'master_duration_ms': master_cursor}


def review_state(project, root, validation=None):
    """Return current per-Beat review states, invalidating stale attestations."""
    validation = validation or validate(project, root)
    record = project.get('documentary_beat_review') or {}
    current_hash = script_hash(project)
    signature = source_signatures(project, root, validation.get('beats') or []) if validation.get('beats') else []
    stale = record.get('script_sha256') != current_hash or record.get('source_signatures') != signature
    saved = record.get('visual_reviews') or {}
    frame_adjustments = {x.get('beat_label'):x for x in record.get('frame_adjustments') or []}
    result = []
    issues_by_label = {}
    for issue in validation.get('issues') or []:
        found = re.match(r'Beat (\d+)', issue)
        if found:
            issues_by_label.setdefault(found.group(1), []).append(issue)
    for beat in validation.get('beats') or []:
        label = beat['label']
        review = saved.get(label) or {}
        beat_issues=issues_by_label.get(label) or []
        if any('ambiguous' in x.lower() for x in beat_issues):
            validation_status='SOURCE AMBIGUOUS'
        elif any('missing' in x.lower() or 'upload exactly one' in x.lower() for x in beat_issues):
            validation_status='SOURCE MISSING'
        elif any(any(token in x.lower() for token in ('mismatch','narration gap','narration overlap','master timeline gap','master timeline overlap','pause does not match')) for x in beat_issues):
            validation_status='TIMING MISMATCH'
        elif any('source range' in x.lower() or 'source out' in x.lower() or 'source in' in x.lower() or 'original uploaded video' in x.lower() for x in beat_issues):
            validation_status='SOURCE RANGE INVALID'
        elif beat_issues:
            validation_status='TIMING MISMATCH'
        else:
            validation_status='SCRIPT ASSIGNMENT VALID'
        if validation_status!='SCRIPT ASSIGNMENT VALID':
            status=validation_status
        elif stale:
            status = 'VISUAL NOT REVIEWED'
        elif review.get('status') == 'wrong':
            status = 'VISUAL FLAGGED WRONG'
        elif review.get('status') == 'exception':
            status = 'USER-APPROVED EXCEPTION'
        elif review.get('status') == 'reviewed':
            status = 'VISUAL REVIEWED'
        else:
            status = 'VISUAL NOT REVIEWED'
        result.append({**beat, 'status': status,'validation_status':validation_status,
                       'review': None if stale else review,
                       'frame_adjustment': None if stale else frame_adjustments.get(label),
                       'frame_range': (validation.get('frame_ranges') or {}).get(label),
                       'asset_id': next((a.get('id') for a in _asset_matches(project, beat['source_file'])), None)})
    return {'strict': True, 'stale': stale, 'script_sha256': current_hash,
            'source_signatures': signature, 'issues': validation.get('issues') or [],
            'beats': result}


def review_blockers(project, root, validation=None):
    state = review_state(project, root, validation)
    blockers = []
    record = project.get('documentary_beat_review') or {}
    if state['stale']:
        blockers.append('The production script or an approved source file changed after the Beat review; rebuild the storyboard and review every Beat again.')
    blockers.extend(state['issues'])
    if not record.get('strict_execution'):
        blockers.append('Build this script in exact execution mode before approval or export.')
    for beat in state['beats']:
        if beat['status'] == 'VISUAL NOT REVIEWED':
            blockers.append(f'Beat {beat["label"]}: visual has not been reviewed against the exact source interval.')
        elif beat['status'] == 'VISUAL FLAGGED WRONG':
            blockers.append(f'Beat {beat["label"]}: visual is flagged wrong; correct the production script and rebuild, or record an approved exception.')
        elif beat['status'] in ('SOURCE MISSING','SOURCE AMBIGUOUS'):
            blockers.append(f'Beat {beat["label"]}: exact source is missing or ambiguous.')
        elif beat['status'] in ('SOURCE RANGE INVALID', 'TIMING MISMATCH'):
            blockers.append(f'Beat {beat["label"]}: source or timeline validation failed.')
        elif beat['status'] == 'USER-APPROVED EXCEPTION' and not (beat.get('review') or {}).get('detail'):
            blockers.append(f'Beat {beat["label"]}: an exception requires a written approval detail.')
    return list(dict.fromkeys(blockers))


def make_review(project, root, beat_label, status, detail=''):
    """Bind a human review/exception to current source signatures and script hash."""
    validation = validate(project, root)
    if validation['issues']:
        raise ValueError('Resolve strict script/source blockers before visual review: ' + ' '.join(validation['issues']))
    if status not in ('reviewed', 'wrong', 'exception'):
        raise ValueError('Choose reviewed, wrong or exception.')
    if status in ('wrong', 'exception') and not str(detail).strip():
        raise ValueError('Write why this visual is wrong or what exception is being approved.')
    beat = next((b for b in validation['beats'] if b['label'] == str(beat_label)), None)
    if beat is None:
        raise ValueError('That Beat is not in the current strict production script.')
    return {'status': status, 'detail': str(detail).strip(), 'at': __import__('time').time(),
            'beat_label': str(beat_label), 'explicit_approval': status == 'exception',
            'script_sha256': script_hash(project),
            'source_signatures': source_signatures(project, root, validation['beats'])}

