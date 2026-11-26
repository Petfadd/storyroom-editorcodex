"""Read-only documentary intake state.

The authored Beat production script determines source filenames/IN/OUT and soundbite
placement. The SRT determines narration text and its original clock. This module
never invents a clip, changes a timecode, substitutes a source or approves media.
It groups predictable partial-upload conditions into one actionable waiting status.
"""
from pathlib import Path


def required_source_state(beats, assets, project_root):
    """Return authoritative source readiness, in first-use order.

    Only exact source filenames are accepted; same-number or case-insensitive
    guesses must never silently resolve to another video.
    """
    requested = {}
    for beat in beats:
        filename = beat['source_file']
        requested[filename] = max(requested.get(filename, 0), int(beat['source_out_ms']))
    names = list(requested)
    by_name = {}
    for asset in assets or []:
        if asset.get('kind') == 'video':
            name = asset.get('original_name') or asset.get('name')
            by_name.setdefault(name, []).append(asset)
    root = Path(project_root)
    ready, missing, ambiguous, too_short = [], [], [], []
    for filename, out_ms in requested.items():
        matches = by_name.get(filename, [])
        if not matches:
            missing.append(filename)
            continue
        if len(matches) != 1:
            ambiguous.append(filename)
            continue
        asset = matches[0]
        relative = asset.get('path')
        if not relative or not (root / relative).is_file():
            missing.append(filename)
            continue
        available_ms = round(float(asset.get('duration') or 0) * 1000)
        if available_ms < out_ms:
            too_short.append({'source': filename, 'available_ms': available_ms, 'required_ms': out_ms})
        else:
            ready.append(filename)
    return {'expected': names, 'ready': ready, 'missing': missing,
            'ambiguous': ambiguous, 'too_short': too_short,
            'count': len(names), 'ready_count': len(ready),
            'all_ready': len(ready) == len(names)}


def readiness_message(state):
    """One concise status per root cause, never a wall of per-Beat errors."""
    count, ready = state['count'], state['ready_count']
    if state['ambiguous']:
        names = ', '.join(state['ambiguous'][:4])
        return 'Conflicting source filenames: ' + names + '. Keep one video for each exact script filename.'
    if state['too_short']:
        first = state['too_short'][0]
        extra = len(state['too_short']) - 1
        return (f'{first["source"]} has {first["available_ms"]/1000:.3f}s but the production script needs '
                f'{first["required_ms"]/1000:.3f}s. Upload the complete source; no cut was shortened.'
                + (f' {extra} other source(s) are too short.' if extra else ''))
    if state['missing']:
        names = ', '.join(state['missing'][:5])
        other = len(state['missing']) - 5
        return (f'Footage ready: {ready}/{count}. Waiting for: {names}'
                + (f' (+{other} more)' if other > 0 else '')
                + '. Storyroom will continue when they arrive.')
    return f'All {count} production-script sources are present. Preparing timeline.'


def srt_narration_bounds(beats, srt_blocks):
    """Non-mutating script/SRT narration bounds for diagnostics, not fact claims.

    SRT has pauses and narration Beats may cover more than one cue. Never force
    per-cue cuts or modify SRT to make the clocks superficially identical.
    """
    voiced = [b for b in beats if b['kind'] == 'narration']
    if not voiced or not srt_blocks:
        return {'status': 'pending', 'reason': 'Waiting for narration beats and SRT.'}
    srt_first = min(c['start_ms'] for c in srt_blocks)
    srt_last = max(c['end_ms'] for c in srt_blocks)
    beat_first = min(b['narration_in_ms'] for b in voiced)
    beat_last = max(b['narration_out_ms'] for b in voiced)
    # A cue can end inside a longer beat, and short SRT gaps are natural. Only a
    # boundary beyond 1000 ms needs a review; no silent offset is introduced.
    discrepancy = max(abs(srt_first - beat_first), abs(srt_last - beat_last))
    return {'status': 'aligned' if discrepancy <= 1000 else 'review',
            'srt_in_ms': srt_first, 'srt_out_ms': srt_last,
            'script_in_ms': beat_first, 'script_out_ms': beat_last,
            'boundary_difference_ms': discrepancy,
            'reason': '' if discrepancy <= 1000 else 'Script narration bounds differ from the SRT by more than one second. Compare the imported files; Storyroom will not retime them.'}
