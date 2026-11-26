"""Quick, read-only documentary project health check.

This is an intake diagnostic, not an identity/footage validation or an export
approval. It must never alter a project's source-of-truth files, select shots,
or launch processing tasks. Source matches are exact and case-sensitive.
"""
from pathlib import Path


def assess(project, root):
    root = Path(root)
    checks = []
    summary = {'beats': 0, 'soundbites': 0, 'srt_cues': 0, 'sources': 0,
               'sources_ready': 0, 'missing_sources': [], 'short_sources': [],
               'duplicate_sources': []}

    def add(key, state, message):
        checks.append({'key': key, 'state': state, 'message': message})

    script = (project.get('production_script') or {}).get('text') or ''
    blocks = (project.get('srt') or {}).get('blocks') or []
    voice = project.get('voiceover') or {}
    if script.strip():
        add('production_script', 'ok', 'Production script uploaded.')
    else:
        add('production_script', 'waiting', 'Upload the final production script.')

    if blocks:
        summary['srt_cues'] = len(blocks)
        valid = True
        last_start = -1
        for cue in blocks:
            try:
                start, end = int(cue['start_ms']), int(cue['end_ms'])
            except (TypeError, ValueError, KeyError):
                valid = False
                break
            if start < 0 or end <= start or start < last_start:
                valid = False
                break
            last_start = start
        if valid:
            add('srt', 'ok', f'{len(blocks)} original SRT cues loaded; ordering and positive durations checked.')
        else:
            add('srt', 'review', 'SRT contains missing, invalid or out-of-order cue times. Review the original file.')
    else:
        add('srt', 'waiting', 'Upload the original narration SRT.')

    if voice:
        location = voice.get('path')
        if location and (root / str(location)).is_file():
            add('narration_audio', 'ok', 'Narration audio file is present.')
        else:
            add('narration_audio', 'review', 'Narration audio is listed but its file is missing. Relink or re-upload it.')
        if blocks and isinstance(voice.get('duration'), (int, float)):
            # A subtitle may end slightly before or after spoken audio. Diagnose
            # only substantial drift, never trim the original file.
            end_ms = max((int(c['end_ms']) for c in blocks if isinstance(c.get('end_ms'), (int, float))), default=0)
            drift_s = abs(float(voice['duration']) - end_ms / 1000)
            if drift_s > 2.0:
                add('audio_srt_length', 'review', f'Narration audio and SRT end differ by {drift_s:.2f}s; compare them, no retiming was applied.')
    else:
        add('narration_audio', 'waiting', 'Upload the final narration audio.')

    if (root / 'downloads' / 'footage_sheet.md').is_file():
        add('footage_sheet', 'ok', 'YouTube footage sheet is saved in this project.')
    else:
        add('footage_sheet', 'info', 'No footage sheet saved yet; direct video uploads can still be used.')

    if script.strip() and project.get('edit_mode') == 'documentary':
        from documentary_beats import read_beats
        try:
            beats = read_beats(script)
        except (ValueError, TypeError, KeyError) as exc:
            add('script_reader', 'review', f'Production script could not be parsed: {str(exc)[:200]}')
        else:
            summary['beats'] = len(beats)
            summary['soundbites'] = sum(b['kind'] == 'sound_bite' for b in beats)
            add('script_reader', 'ok', f'{len(beats)} Beats and {summary["soundbites"]} soundbites parsed.')
            from documentary_sync import required_source_state, srt_narration_bounds
            state = required_source_state(beats, project.get('assets') or [], root)
            summary.update(sources=state['count'], sources_ready=state['ready_count'],
                           missing_sources=state['missing'], short_sources=state['too_short'],
                           duplicate_sources=state['ambiguous'])
            if state['ambiguous']:
                add('source_files', 'review', 'Duplicate source filenames: ' + ', '.join(state['ambiguous'][:4]) + '.')
            elif state['too_short']:
                # v19: every short file is named (only the first was, hiding the others).
                short = [f'{x["source"]} is {x["available_ms"]/1000:.1f}s long but the script uses it up to '
                         f'{x["required_ms"]/1000:.1f}s' for x in state['too_short']]
                more = len(short) - 6
                add('source_files', 'review', 'Videos shorter than the script needs: ' + '; '.join(short[:6])
                    + (f' (+{more} more)' if more > 0 else '')
                    + '. Upload the full video again with the same file name, or correct the script times.')
            elif state['missing']:
                names = ', '.join(state['missing'][:4]); extra = max(0, len(state['missing'])-4)
                add('source_files', 'waiting', f'{state["ready_count"]}/{state["count"]} script-named videos ready. Missing: {names}' + (f' (+{extra} more)' if extra else '') + '.')
            else:
                add('source_files', 'ok', f'All {state["count"]} exact script-named source files are present with sufficient declared durations.')
            if blocks:
                alignment = srt_narration_bounds(beats, blocks)
                if alignment['status'] == 'review':
                    add('script_srt_alignment', 'review', alignment['reason'])
                elif alignment['status'] == 'aligned':
                    add('script_srt_alignment', 'ok', 'Script narration and SRT start/end bounds agree within 1s.')

    if project.get('scenes'):
        add('timeline', 'ok', f'{len(project["scenes"])} timeline picture slots exist.')
    else:
        add('timeline', 'waiting', 'The picture timeline has not been built yet.')

    # A waiting input is progress, not a fault. Explicit review checks take
    # precedence over waiting, and no health state certifies footage content.
    status = ('review' if any(c['state'] == 'review' for c in checks)
              else 'waiting' if any(c['state'] == 'waiting' for c in checks) else 'ready')
    if status == 'review':
        headline = 'One or more production inputs need review.'
    elif status == 'waiting':
        headline = 'Production inputs are still arriving.'
    else:
        headline = 'All checked project inputs are present.'
    return {'status': status, 'headline': headline, 'checks': checks, 'summary': summary,
            'note': 'Checks are mechanical only: dialogue, people, images, rights, and the finished MP4 are not automatically verified.'}
