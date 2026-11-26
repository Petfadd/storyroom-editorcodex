"""Legacy fit-and-review path for older documentary Beat scripts.

Every change is mechanical and recorded: a range is only ever trimmed or extended
inside the one video the script names for that beat. No other file is chosen, no
source range is changed without review, and no playback speed is changed. A person still has to review
the result; this is not identity, content or rights verification.

Pipeline v5 scripts marked with ``Full source`` do not use ``fit()``. Their source
assignments and ranges are validate-only through ``documentary_strict``.
"""
import copy
from pathlib import Path
from documentary_gap_policy import is_subframe_gap


_LIMITS = {}


def frame_limits(root, assets, path_of=None):
    """Highest usable exclusive OUT (ms) per asset, from real container metadata.

    ``nb_frames``/stream frame counts are header data, so this stays cheap. When a
    count is unavailable the stored duration is used unchanged and the existing
    frame audit still fails closed.
    """
    import av
    from fractions import Fraction
    limits = {}
    for asset in assets:
        path = (path_of(asset) if path_of else Path(root)/str(asset.get('path') or ''))
        # A file's frame limit is a fact about that exact file; remember it.
        try:
            st = Path(path).stat(); fkey = (str(path), st.st_size, st.st_mtime_ns)
        except OSError:
            fkey = None
        if fkey in _LIMITS:
            if _LIMITS[fkey] is not None:
                limits[asset.get('id')] = _LIMITS[fkey]
            continue
        try:
            with av.open(str(path)) as container:
                stream = container.streams.video[0]
                rate = Fraction(stream.average_rate)
                frames = stream.frames or 0
                value = int(Fraction(frames, 1)*1000/rate) if frames and rate > 0 else None
        except Exception:
            continue
        if fkey is not None:
            _LIMITS[fkey] = value
        if value is not None:
            limits[asset.get('id')] = value
    return limits


def unused_ranges(beats, filename, limit):
    """Intervals of one upload that no scripted Beat uses, longest first.

    A suggestion only: what those seconds show still has to be watched.
    """
    used = sorted((b['source_in_ms'], b['source_out_ms']) for b in beats if b['source_file'] == filename)
    free, cursor = [], 0
    for start, end in used:
        if start > cursor:
            free.append((cursor, min(start, limit)))
        cursor = max(cursor, end)
    if cursor < limit:
        free.append((cursor, limit))
    return sorted(((a, b) for a, b in free if b - a >= 1000), key=lambda r: r[0] - r[1])


def _limit_ms(asset, frame_limit):
    """Highest usable exclusive OUT for one asset: a real frame boundary if known."""
    stored = round(float(asset.get('duration') or 0)*1000)
    snapped = (frame_limit or {}).get(asset.get('id'))
    return min(stored, snapped) if snapped else stored


def fit(beats, assets, focus_beat=None, focus_source=None, frame_limit=None):
    """Return (adjusted beats, adjustment records, blocking issues).

    A beat whose scripted range is longer than its video cannot be fitted inside
    that video. When the caller has explicitly named a replacement, verified
    source for that one beat, the beat is re-pointed there and the change is
    recorded like every other adjustment.
    """
    files = {}
    for asset in assets:
        name = asset.get('original_name') or asset.get('name')
        files.setdefault(name, asset)
    frame_limit = frame_limit or {}
    adjusted, adjustments, issues = [], [], []
    for beat in beats:
        beat = dict(beat)
        if beat['kind'] != 'narration':
            # Sound bites are picture too. Leaving a bite pointing past the end of
            # its file let the review storyboard fail later with a bare "source OUT
            # exceeds video duration" and no explanation of what to change.
            label = beat['label']
            asset = files.get(beat['source_file'])
            if not asset:
                issues.append(f'Beat {label}: script source {beat["source_file"]} is not uploaded.')
                adjusted.append(beat)
                continue
            limit = _limit_ms(asset, frame_limit)
            before = (beat['source_in_ms'], beat['source_out_ms'])
            if before[1] > limit:
                room = max(0, limit - before[0])
                scripted = (before[1]-before[0])/1000
                if room >= 1000:
                    beat['source_out_ms'] = limit
                    beat['duration_ms'] = limit - before[0]
                    adjustments.append(f'Beat {label}: source OUT {before[1]/1000:.3f}s is past the end of '
                                       f'{beat["source_file"]} ({limit/1000:.3f}s); clamped to {limit/1000:.3f}s, '
                                       f'so this bite plays {room/1000:.3f}s instead of {scripted:.3f}s.')
                else:
                    # Shifting the IN back would move the spoken words, which is an
                    # editorial decision. Ask instead of guessing, and name the
                    # seconds of this upload that no other Beat is using yet.
                    left = f'{room/1000:.3f}s left after source IN {before[0]/1000:.3f}s'
                    spare = unused_ranges(beats, beat['source_file'], limit)
                    offer = ''
                    if spare:
                        a, b = spare[0]
                        offer = (f' The longest unused stretch of this upload is {a/1000:.3f}–{b/1000:.3f}s '
                                 f'({(b-a)/1000:.3f}s); check what it shows before using it.')
                    else:
                        offer = (' Every other second of this upload is already claimed by another Beat, '
                                 'so this project needs a longer source file or one more video.')
                    issues.append(f'Beat {label}: {beat["source_file"]} has only {left}, which cannot cover this '
                                  f'{scripted:.3f}s bite. Choose an earlier source IN or a different uploaded file for this Beat; '
                                  f'nothing was moved or shortened.{offer}')
                adjusted.append(beat)
                continue
            adjusted.append(beat)
            continue
        label = beat['label']
        asset = files.get(beat['source_file'])
        if not asset:
            issues.append(f'Beat {label}: script source {beat["source_file"]} is not uploaded.')
            adjusted.append(beat)
            continue
        if focus_beat == label and focus_source:
            replacement = files.get(focus_source)
            if not replacement:
                issues.append(f'Beat {label}: the chosen replacement source {focus_source} is not uploaded.')
                adjusted.append(beat)
                continue
            if float(replacement.get('duration') or 0)*1000+.001 < beat['narration_out_ms']-beat['narration_in_ms']:
                issues.append(f'Beat {label}: {focus_source} is too short for the {((beat["narration_out_ms"]-beat["narration_in_ms"])/1000):.3f}s narration.')
                adjusted.append(beat)
                continue
            adjustments.append(f'Beat {label}: scripted {beat["source_file"]} {beat["source_in_ms"]/1000:.3f}–{beat["source_out_ms"]/1000:.3f}s '
                               f'cannot cover the {(beat["narration_out_ms"]-beat["narration_in_ms"])/1000:.3f}s narration; '
                               f're-pointed to your chosen {focus_source} 0.000s onward instead.')
            beat['source_file'] = focus_source
            beat['source_in_ms'], beat['source_out_ms'] = 0, beat['narration_out_ms']-beat['narration_in_ms']
            adjusted.append(beat)
            continue
        limit = _limit_ms(asset, frame_limit)
        need = beat['narration_out_ms']-beat['narration_in_ms']
        start, end = beat['source_in_ms'], beat['source_out_ms']
        before = (start, end)
        if end > limit:
            end = limit
            adjustments.append(f'Beat {label}: source OUT {before[1]/1000:.3f}s is past the end of {beat["source_file"]} '
                               f'({limit/1000:.3f}s); clamped to {end/1000:.3f}s.')
        # A frame-snapped OUT must still name a frame that exists. One source
        # frame shorter is honest; asking for a missing frame would be a stretch.
        frame_end = frame_limit.get(asset.get('id'))
        if end >= limit and frame_end is not None and frame_end < end:
            adjustments.append(f'Beat {label}: source OUT {end/1000:.3f}s is not a frame boundary in {beat["source_file"]}; '
                               f'using the nearest frame at {frame_end/1000:.3f}s.')
            end = frame_end
        span = end-start
        if span == need:
            pass
        elif span > need:
            end = start+need
            adjustments.append(f'Beat {label}: {span/1000:.3f}s of picture trimmed to the {need/1000:.3f}s narration span '
                               f'({start/1000:.3f}–{end/1000:.3f}s).')
        else:
            # Keep the script's own start where the file allows it; only borrow
            # outside it when the remaining file cannot cover the narration.
            if start+need <= limit:
                end = start+need
                side = 'forward' if end <= before[1] else 'forward, from the scripted IN'
            elif end-need >= 0:
                start = end-need
                side = 'backward, from the scripted OUT'
            else:
                issues.append(f'Beat {label}: {beat["source_file"]} only has {float(asset.get("duration") or 0):.3f}s, '
                              f'which cannot cover the {need/1000:.3f}s narration without repeating or slowing it.')
                adjusted.append(beat)
                continue
            if span > 0:
                lead = f'{span/1000:.3f}s of picture is shorter than the {need/1000:.3f}s narration'
            else:
                # The scripted range begins past the end of the file, so there is
                # no picture inside it at all. Say that instead of a negative number.
                lead = f'the scripted range {before[0]/1000:.3f}–{before[1]/1000:.3f}s is past the end of ' \
                       f'{beat["source_file"]}, so it is shorter than the {need/1000:.3f}s narration'
            adjustments.append(f'Beat {label}: {lead}; extended {side} inside {beat["source_file"]} '
                               f'to {start/1000:.3f}–{end/1000:.3f}s.')
        if end <= start:
            issues.append(f'Beat {label}: the fitted source range is empty.')
        if (start, end) == before and span >= need:
            pass
        beat['source_in_ms'], beat['source_out_ms'] = start, end
        adjusted.append(beat)
    return adjusted, adjustments, issues


def overlaps(beats):
    """Every repeated interval pair, so the caller can record an explicit decision.

    Includes exact and partial source-range reuse, for informational display.
    A documentary can deliberately return to the same source pictures or play
    cold-open testimony again in its original context. Reuse never blocks a build.
    """
    pairs = []
    for i, b in enumerate(beats):
        for a in beats[:i]:
            if a['source_file'] == b['source_file'] and b['source_in_ms'] < a['source_out_ms'] and b['source_out_ms'] > a['source_in_ms']:
                pairs.append([a['number'], b['number']])
    return pairs




def consecutive_bites(beats):
    """True when two sound bites share a pause point with no narration between."""
    found = []
    for a, b in zip(beats, beats[1:]):
        if a['kind'] == 'sound_bite' and b['kind'] == 'sound_bite':
            found.append([a['number'], b['number']])
    return found


# v21: the narration's last few seconds after the final scripted Beat. Up to this long it
# is closed automatically (never with footage the script did not name); longer, the
# script must be corrected.
END_TAIL_MAX_MS = 10000


def end_tail(project, beats):
    """The uncovered end of the narration, if it can be closed automatically.

    {'kind': 'speech'|'silence', 'from_ms', 'to_ms', 'label', 'source_file'} or None.
    'speech' when a subtitle runs into the tail (the narrator is still talking), else
    'silence'. Only the very end qualifies, only up to END_TAIL_MAX_MS, only when the
    last narration Beat is what ends there and no sound bite is placed after it.
    """
    from documentary_beats import is_strict_pipeline_script
    if is_strict_pipeline_script((project.get('production_script') or {}).get('text', '')):
        return None                            # exact-execution scripts are never adjusted
    narratives = [b for b in beats if b['kind'] == 'narration']
    voice_ms = round(float((project.get('voiceover') or {}).get('duration') or 0) * 1000)
    if not narratives or not voice_ms:
        return None
    last = max(narratives, key=lambda b: b['narration_out_ms'])
    start = last['narration_out_ms']
    if not 0 < voice_ms - start <= END_TAIL_MAX_MS or is_subframe_gap(start, voice_ms):
        return None
    if any(b['kind'] != 'narration' and (b.get('pause_ms') or 0) >= start for b in beats):
        return None
    blocks = (project.get('srt') or {}).get('blocks') or []
    speech = any(float(c.get('end_ms') or 0) > start + 150 and float(c.get('start_ms') or 0) < voice_ms for c in blocks)
    return {'kind': 'speech' if speech else 'silence', 'from_ms': start, 'to_ms': voice_ms,
            'label': last['label'], 'source_file': last['source_file']}


def close_end_tail(project, beats):
    """(beats, note): the last narration Beat runs to the end of spoken narration.

    Speech after the last Beat: that Beat's narration and its picture continue, in the
    same video, to the end (fit() then keeps the picture inside the file). Silence
    after it: nothing changes here; the film ends on the last word (see narration
    trim in the storyboard build). No other footage is ever chosen.
    """
    tail = end_tail(project, beats)
    if not tail:
        return beats, None
    extra = tail['to_ms'] - tail['from_ms']
    if tail['kind'] == 'silence':
        return beats, (f"Narration {tail['from_ms']/1000:.3f}–{tail['to_ms']/1000:.3f}s is silence after the last "
                       f"word (no subtitle there). The film ends at {tail['from_ms']/1000:.3f}s, on the narrator's last word.")
    out = copy.deepcopy(beats)
    for b in out:
        if b['kind'] == 'narration' and b['label'] == tail['label'] and b['narration_out_ms'] == tail['from_ms']:
            b['narration_out_ms'] = tail['to_ms']
            b['source_out_ms'] += extra
            if 'duration_ms' in b:
                b['duration_ms'] = b.get('duration_ms', 0) + extra
            break
    return out, (f"Beat {tail['label']}: the narrator keeps talking for {extra/1000:.3f}s after this Beat's scripted end "
                 f"({tail['from_ms']/1000:.3f}s). Its shot in {tail['source_file']} continues to the end of the narration "
                 f"({tail['to_ms']/1000:.3f}s).")


def narration_gaps(project, beats, frame_limit=None):
    """Report uncovered narration intervals without inventing a picture source.

    Real footage can only be scheduled by an explicit source and range in the
    production script.  Unused seconds of an uploaded clip cannot establish
    case relevance.  Small sub-frame rounding tails still follow the shared
    Storyroom tolerance; every material hole blocks the Beat build until the
    script supplies the missing picture assignment.

    ``frame_limit`` is retained for callers of the existing proposal API.
    """
    narratives = [b for b in beats if b['kind'] == 'narration']
    cursor, holes = 0, []
    for beat in narratives:
        start, end = beat['narration_in_ms'], beat['narration_out_ms']
        if start > cursor:
            holes.append((cursor, start))
        cursor = max(cursor, end)
    voice_ms = round(float((project.get('voiceover') or {}).get('duration') or 0) * 1000)
    tail = end_tail(project, beats)
    if tail and tail['kind'] == 'silence' and tail['from_ms'] == cursor:
        voice_ms = cursor                      # v21: the film ends on the last word
    if voice_ms > cursor:
        holes.append((cursor, voice_ms))
    holes = [(a, b) for a, b in holes if not is_subframe_gap(a, b)]
    gaps = [{'narration_in_ms': a, 'narration_out_ms': b, 'status': 'unassigned'}
            for a, b in holes]
    issues = [
        f'Narration {a/1000:.3f}–{b/1000:.3f}s ({(b-a)/1000:.3f}s) has no scripted picture Beat. '
        f'Add an explicit real source file and source IN/OUT to the production script, '
        f'or correct the narration clock. No spare footage was selected.'
        for a, b in holes
    ]
    return gaps, issues


def _narration_used_ms(project, beats):
    tail = end_tail(project, beats)
    if tail and tail['kind'] == 'silence':
        return tail['from_ms']
    return round(float((project.get('voiceover') or {}).get('duration') or 0) * 1000)


def proposal(project, beats, focus_beat=None, focus_source=None, frame_limit=None):
    """Everything a person needs to see before a Beat storyboard is built.

    ``frame_limit`` maps asset id to the highest decodable exclusive OUT in ms.
    """
    beats, tail_note = close_end_tail(project, beats)
    adjusted, adjustments, issues = fit(beats, project.get('assets') or [], focus_beat, focus_source, frame_limit)
    if tail_note:
        adjustments.insert(0, tail_note)
    # Exact and partial reuse are valid editorial decisions. Do not pretend that
    # reusing a soundbite means the source file is too short: each playback is a
    # separate timeline occurrence from the same valid source interval.
    from documentary_beats import pause_clock_issues
    issues.extend(pause_clock_issues(adjusted, (project.get('voiceover') or {}).get('duration')))
    gaps, gap_issues = narration_gaps(project, adjusted, frame_limit)
    issues.extend(gap_issues)
    pairs = overlaps(adjusted)
    runs = consecutive_bites(adjusted)
    total_ms = sum(b['source_out_ms']-b['source_in_ms'] for b in adjusted)
    # v19: the film is the narration plus every sound bite (the narration pauses for each);
    # the sum of all scripted ranges was shown as "planned picture" and read like the length.
    bites_ms = sum(b['source_out_ms']-b['source_in_ms'] for b in adjusted if b['kind'] != 'narration')
    return {'beats': adjusted, 'adjustments': adjustments, 'issues': issues, 'narration_gaps': gaps,
            'repeated_ranges': pairs, 'consecutive_bites': runs,
            'planned_ms': total_ms, 'bites_ms': bites_ms, 'narration_ms': _narration_used_ms(project, adjusted),
            'source_files': sorted({b['source_file'] for b in adjusted})}
