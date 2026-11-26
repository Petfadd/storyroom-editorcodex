"""Read explicit documentary Beat blocks without creating or altering a timeline.

This is a preflight reader, not an editor or renderer. No source, timing, speaker or
rights are inferred from text or filenames; callers must not regard output as approval.
"""
import re
from pathlib import Path

HEAD = re.compile(r'^Beat:\s*(\d+)\s*$', re.M | re.I)
CLOCK = r'\d{2}:\d{2}:\d{2}[,.]\d{3}'


def is_strict_pipeline_script(text):
    """Legacy compatibility hook: all production scripts use one Beat workflow.

    Explicit older format headings or visual IDs are accepted as metadata;
    they must not activate a separate strict script parser or export mode.
    """
    return False


def _visual_id(direction, continuity):
    text = f'{direction or ""}\n{continuity or ""}'
    found = re.search(r'\bVisual\s*ID\s*[:#-]?\s*([A-Za-z0-9][A-Za-z0-9_-]*)', text, re.I)
    if found:
        return found.group(1).strip()
    found = re.search(r'\b(VID(?:[-_][A-Z0-9][A-Z0-9_-]*|[0-9][A-Z0-9_-]*)|VIS(?:[-_][A-Z0-9][A-Z0-9_-]*|[0-9][A-Z0-9_-]*))\b', text, re.I)
    return found.group(1) if found else ''


def _anchor_id(continuity):
    found = re.search(r'\bAnchor(?:\s+ID)?\s*[:#-]\s*([A-Za-z0-9][A-Za-z0-9_-]*)', continuity or '', re.I)
    return found.group(1).strip() if found else ''

def time_ms(value):
    if not re.fullmatch(CLOCK, value.strip()):
        raise ValueError('Expected HH:MM:SS,mmm timecode.')
    h, m, s, ms = map(int, re.split(r'[:,.]', value.strip()))
    if m >= 60 or s >= 60:
        raise ValueError('Invalid timecode.')
    return ((h * 60 + m) * 60 + s) * 1000 + ms

def read_beats(text, strict=None):
    strict = is_strict_pipeline_script(text) if strict is None else bool(strict)
    heads = list(HEAD.finditer(text or ''))
    if not heads:
        raise ValueError('No numbered Beat blocks found.')
    beats, seen = [], set()
    for i, head in enumerate(heads):
        label = head.group(1)
        number = int(label)
        if number in seen:
            raise ValueError(f'Beat {label}: duplicate beat number.')
        if beats and number <= beats[-1]['number']:
            raise ValueError(f'Beat {label}: beat numbers must be in order.')
        seen.add(number)
        body = text[head.end():heads[i + 1].start() if i + 1 < len(heads) else len(text)]
        def field(name, required=True):
            found = re.findall(r'^' + re.escape(name) + r':\s*([^\r\n]*)$', body, re.I | re.M)
            if len(found) > 1 or (required and (not found or not found[0].strip())):
                raise ValueError(f'Beat {label}: provide exactly one {name} field.')
            return found[0].strip() if found else ''
        typ = field('Type').upper()
        if typ in ('NARRATION (VOICE OVER)', 'VOICE OVER'): kind = 'narration'
        elif typ == 'DOCUMENTARY SOUND BITE': kind = 'sound_bite'
        else: raise ValueError(f'Beat {label}: unsupported beat Type {typ!r}.')
        # Full source is authoritative in v5. Video File remains legacy-only.
        if strict:
            filename = field('Full Source')
            if field('Video File', False):
                raise ValueError(f'Beat {label}: Beat-based documentary scripts use Full source only; remove Video File.')
        else:
            filename = field('Video File') if field('Video File', False) else field('Full Source')
        allowed_suffix = r'\.mp4' if strict else r'\.(mp4|mov)'
        if Path(filename).name != filename or '\\' in filename or not re.search(allowed_suffix + r'$', filename, re.I):
            raise ValueError(f'Beat {label}: use an exact video filename, not a path.')
        try:
            si_text, so_text = field('Source IN'), field('Source OUT')
            si, so = time_ms(si_text), time_ms(so_text)
            if so <= si: raise ValueError('Source OUT must be after IN.')
            direction = field('Visual Direction', False)
            continuity = field('Continuity Note', False)
            caption = field('On-screen Caption', False)
            explicit_visual_id = field('Visual ID', False)
            has_explicit_visual_field = bool(re.search(r'^Visual ID\s*:', body, re.I | re.M))
            if strict and has_explicit_visual_field:
                raise ValueError('Beat scripts carry Visual ID in Visual Direction and Continuity Note; remove the standalone Visual ID field.')
            visual_id = _visual_id(direction, continuity)
            if strict and kind == 'narration':
                direction_visual_id = _visual_id(direction, '')
                continuity_visual_id = _visual_id('', continuity)
                if not direction_visual_id or not continuity_visual_id:
                    raise ValueError('Every VO Beat must put its Visual ID in both Visual Direction and Continuity Note.')
                if direction_visual_id != continuity_visual_id:
                    raise ValueError('The VO Beat Visual ID in Visual Direction must match the ID in Continuity Note.')
                visual_id = direction_visual_id
            beat = {'number': number, 'label': label, 'kind': kind, 'source_file': filename,
                    'source_in_ms': si, 'source_out_ms': so,
                    'source_in_tc': si_text, 'source_out_tc': so_text,
                    'caption': caption, 'direction': direction,
                    'visual_id': explicit_visual_id or visual_id,
                    'continuity_note': continuity, 'anchor_id': _anchor_id(continuity),
                    'spoken_narration': field('Spoken Narration', False),
                    'exact_dialogue': field('Exact Spoken Dialogue', False) or field('Spoken Dialogue', False),
                    # How the film enters this Beat (CUT TO PICTURE, CROSS FADE, DIP TO
                    # BLACK, ...). Read into a transition when the timeline is built.
                    'cut_action': field('Cut Action', False)}
            master = field('Master timeline', strict)
            if master:
                span = re.search(r'(' + CLOCK + r')\s*(?:-->|→|->)\s*(' + CLOCK + r')', master)
                if not span:
                    raise ValueError('Master timeline must give IN and OUT.')
                master_in, master_out = map(time_ms, span.groups())
                if master_out <= master_in:
                    raise ValueError('Master timeline OUT must be after IN.')
                beat.update(master_in_ms=master_in, master_out_ms=master_out,
                            master_in_tc=span.group(1), master_out_tc=span.group(2))
                if master_out-master_in != so-si:
                    beat['master_source_duration_mismatch_ms'] = (master_out-master_in)-(so-si)
            # Same fact under either label used by the supplied scripts.
            state = field('Narration State') if field('Narration State', False) else field('VO State')
            audio = field('Footage Audio')
            if kind == 'narration':
                clock = field('Narration Clock') if field('Narration Clock', False) else field('VO Clock')
                clock = re.sub(r'^\s*(?:RESUMES|RESUMING|PLAYING|CONTINUES)\s+(?:at\s+)?', '', clock, flags=re.I)
                span = re.fullmatch(r'\s*('+CLOCK+r')\s*(?:-->|→|->)\s*('+CLOCK+r')\s*', clock)
                if not span: raise ValueError('Narration Clock must have IN and OUT.')
                ni, no = map(time_ms, span.groups())
                if no <= ni: raise ValueError('Narration Clock must have a positive duration.')
                beat.update(narration_in_tc=span.group(1), narration_out_tc=span.group(2))
                if no-ni != so-si:
                    # Preserve the exact request. Strict mode blocks this mismatch;
                    # legacy callers retain their explicit fit-and-review behavior.
                    beat['duration_mismatch_ms'] = (so-si)-(no-ni)
                if not re.match(r'^(PLAYING|RESUMING)\b',state,re.I) or not re.match(r'^MUTED\b',audio,re.I):
                    raise ValueError('Narration must be playing and ordinary footage muted.')
                beat.update(narration_in_ms=ni, narration_out_ms=no)
                if 'master_in_ms' in beat and beat['master_out_ms']-beat['master_in_ms'] != no-ni:
                    beat['master_narration_duration_mismatch_ms'] = (beat['master_out_ms']-beat['master_in_ms'])-(no-ni)
            else:
                match = re.search(r'PAUSED\s*\(\s*Suspended at\s+('+CLOCK+r')\s*\)', state, re.I)
                if match: pause = match.group(1)
                else:
                    # Other scripts keep the pause on the voice-over clock instead.
                    found = re.search(r'PAUSED\s+at\s+('+CLOCK+r')', field('Narration Clock') if field('Narration Clock', False) else field('VO Clock'), re.I)
                    if not found: raise ValueError('Sound bite must give PAUSED (Suspended at <timecode>) or a paused VO Clock.')
                    pause = found.group(1)
                if not re.match(r'^UNMUTED\b',audio,re.I): raise ValueError('Sound-bite source audio must be explicitly unmuted.')
                if field('Duration', False): duration = time_ms(field('Duration'))
                else:
                    # Duration may be written on the master timeline line instead.
                    # The timecode has to be its own capture group. Without the
                    # parentheses group(1) raised IndexError on every script that
                    # wrote the duration this way instead of in a Duration field.
                    found = re.search(r'\(\s*Duration:\s*('+CLOCK+r')\s*\)', field('Master Timeline', False))
                    if found: duration = time_ms(found.group(1))
                    else:
                        secs = re.search(r'\(\s*Duration:\s*(?:([\d.]+)\s*sec|(\d+)\s*min\s*(\d+)\s*sec)\s*\)', field('Master Timeline', False), re.I)
                        if secs:
                            duration = (round(float(secs.group(1))*1000) if secs.group(1)
                                        else (int(secs.group(2))*60+int(secs.group(3)))*1000)
                        elif 'master_in_ms' in beat:
                            # A missing Duration is not an error when the two independent
                            # source/master clocks agree exactly. Do not infer from just
                            # one clock, and never silently retime a discrepant beat.
                            master_duration = beat['master_out_ms'] - beat['master_in_ms']
                            if master_duration != so-si:
                                raise ValueError('Sound-bite source IN–OUT and Master timeline disagree; '
                                                 'provide corrected timecodes before importing.')
                            duration = master_duration
                        else:
                            raise ValueError('Sound bite needs Duration or matching Source IN–OUT and Master timeline.')
                if duration != so-si: raise ValueError('Sound-bite Duration does not match source IN–OUT.')
                if 'master_in_ms' in beat and beat['master_out_ms']-beat['master_in_ms'] != duration:
                    raise ValueError('Sound-bite Master timeline duration disagrees with Source IN–OUT; '
                                     'correct the timecodes instead of silently shifting narration.')
                # Either label names the declared speaker; it is a claim to review,
                # never a verified identity.
                pause_ms = time_ms(pause)
                beat.update(pause_ms=pause_ms, pause_tc=pause, duration_ms=duration,
                            speaker=field('Speaker',False) or field('Speaker & Role',False),
                            speaker_role=field('Speaker & Role',False))
                if strict and duration != so-si:
                    raise ValueError('Sound-bite Duration does not match exact source IN–OUT.')
                if strict and 'master_in_ms' in beat and beat['master_out_ms']-beat['master_in_ms'] != duration:
                    raise ValueError('Master timeline duration does not match sound-bite Duration.')
                if strict and not beat['exact_dialogue']:
                    beat['exact_dialogue'] = beat['spoken_narration']
        except ValueError as e:
            raise ValueError(f'Beat {label}: {e}') from e
        beats.append(beat)
    return beats

def reconcile_pause_clocks(beats):
    """Return (beats, notes), correcting ONLY unambiguous master-clock pause labels.

    Production scripts contain both a film-master timeline and a narrator-only clock.
    A soundbite on the master timeline advances the film while the narrator stays
    paused. When a script accidentally uses the master time for PAUSED at, an exact
    Master timeline match and continuous Beat sequence proves the intended VO time.
    No source ranges, master positions, transcript text or source audio are changed.
    Ambiguous/inconsistent pauses still fail with the precise Beat and clocks.
    """
    movie = 0
    narration = 0
    adjustments = []
    for beat in beats:
        label = beat['label']
        master_in = beat.get('master_in_ms')
        master_out = beat.get('master_out_ms')
        if beat['kind'] == 'narration':
            narration = beat['narration_out_ms']
        else:
            pause = beat['pause_ms']
            # This is safe only if the source/master clock is explicit, current and
            # continuous; do not infer an offset from the total film duration.
            if pause != narration and master_in is not None and master_in == movie and pause == master_in:
                beat['pause_declared_ms'] = pause
                beat['pause_ms'] = narration
                beat['pause_tc'] = f'{narration//3600000:02d}:{narration//60000%60:02d}:{narration//1000%60:02d},{narration%1000:03d}'
                beat['pause_clock_reconciled'] = True
                adjustments.append(f'Beat {label}: PAUSED at {pause/1000:.3f}s used the film-master clock; '
                                   f'the continuous scripted master range proves the narration-only pause is '
                                   f'{narration/1000:.3f}s. Original script unchanged; no source audio or picture moved.')
        if master_in is not None and master_out is not None:
            movie = master_out
        else:
            movie += ((beat['narration_out_ms'] - beat['narration_in_ms'])
                      if beat['kind'] == 'narration' else beat['duration_ms'])
    return beats, adjustments


def pause_clock_issues(beats, voiceover_seconds):
    """Find clock errors *before* the Beat picture plan claims everything fits."""
    from documentary import END_SLACK_S
    narration = 0
    issues = []
    duration_ms = round(float(voiceover_seconds or 0)*1000)
    for beat in beats:
        if beat['kind'] == 'narration':
            narration = beat['narration_out_ms']
            continue
        pause = beat['pause_ms']
        label = beat['label']
        if pause != narration:
            # At the very end an older script may anchor to the SRT end while the
            # narrator file carries a small final silence. The builder handles it.
            if beat is beats[-1] and abs(pause-narration) <= round(END_SLACK_S*1000):
                continue
            issues.append(f'Beat {label}: soundbite PAUSED at {pause/1000:.3f}s does not match '
                          f'the narrator-only clock {narration/1000:.3f}s. '
                          f'Master-film IN is {beat.get("master_in_ms",0)/1000:.3f}s. '
                          f'Correct the PAUSED clock in the script; no source was retimed.')
        if pause > duration_ms + round(END_SLACK_S*1000):
            issues.append(f'Beat {label}: narration pause {pause/1000:.3f}s is outside the '
                          f'{duration_ms/1000:.3f}s narrator audio. This is a clock mismatch, '
                          f'not a reason to shorten the documentary.')
    if narration > duration_ms + round(END_SLACK_S*1000):
        issues.append(f'Script narrator clock ends at {narration/1000:.3f}s, but the uploaded '
                      f'narrator-only file is {duration_ms/1000:.3f}s. Check the actual '
                      f'narration/SRT file; the film-master runtime can be much longer.')
    return issues


