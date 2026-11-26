"""Optional background music for a documentary, kept separate from narration.

The bed belongs to the narration only. While the narrator speaks it sits underneath
the voice (ducked); the moment a sound bite starts it has faded out, and it stays
silent for the whole bite, so the footage's own sound is heard alone. It fades back
in as the narration resumes. The narration, the sound-bite audio and the original SRT
are never altered.
"""
import timebudget
from pathlib import Path
import re, subprocess, tempfile, uuid

import av
import imageio_ffmpeg

MUSIC_VERSION = 'music-bed-narration-only-v3'

# How long the bed takes to leave before a bite and to come back after one.
BITE_FADE_OUT_S = 0.35
BITE_FADE_IN_S = 0.6
ALLOWED_SUFFIXES = {'.mp3', '.wav', '.m4a', '.aac', '.flac', '.ogg', '.opus'}
MAX_BYTES = 200 * 1024 * 1024


def _run(args):
    result = subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=timebudget.seconds())
    if result.returncode:
        raise ValueError('Background music could not be processed: ' + result.stderr[-500:])


def music_path(root):
    """The saved upload, keeping its real extension so it can still be decoded."""
    folder = Path(root) / 'inputs'
    marker = folder / 'background_music.name'
    try:
        name = marker.read_text(encoding='utf-8').strip()
    except OSError:
        name = ''
    if name and re.fullmatch(r'background_music\.[a-z0-9]{1,5}', name) and (folder / name).is_file():
        return folder / name
    for suffix in sorted(ALLOWED_SUFFIXES):
        candidate = folder / ('background_music' + suffix)
        if candidate.is_file():
            return candidate
    return folder / 'background_music'


def probe_duration(path):
    with av.open(str(path)) as media:
        if not media.streams.audio:
            raise ValueError('That file has no audio track.')
        stream = media.streams.audio[0]
        if stream.duration is not None and stream.time_base is not None:
            return float(stream.duration * stream.time_base)
        if media.duration is not None:
            return float(media.duration / av.time_base)
    raise ValueError('The music length could not be read.')


def measure_loudness_lufs(path):
    """Estimate the bed's own loudness once, so the preview can match the export.

    The exporter normalises the bed to a target loudness; the browser can only
    scale the raw file, so it needs this number. Measuring the whole file is
    accurate but takes ~40 s for a long track, and a single sample is wrong by
    several dB on music that changes between sections (this project's bed swings
    13 LU). Six short samples averaged, in loudness terms, is within ~1 dB and
    takes about a second.
    """
    try:
        from documentary_audio import measure_loudness
        import math
        ff = imageio_ffmpeg.get_ffmpeg_exe()
        duration = probe_duration(path)
        spots = [0.1, 0.25, 0.4, 0.55, 0.7, 0.85] if duration > 45 else [0.5]
        energies = []
        for frac in spots:
            sample = Path(tempfile.gettempdir()) / ('music-loud-' + uuid.uuid4().hex + '.wav')
            try:
                _run([ff, '-hide_banner', '-loglevel', 'error', '-y',
                      '-ss', f'{max(0.0, duration * frac - 15):.3f}', '-i', str(path),
                      '-t', f'{min(30.0, max(1.0, duration * 0.4)):.3f}',
                      '-vn', '-ac', '2', '-ar', '48000', str(sample)])
                energies.append(measure_loudness(ff, sample)['integrated_lufs'])
            finally:
                sample.unlink(missing_ok=True)
        if not energies:
            return None
        # Loudness is logarithmic: average in linear power, not in LUFS.
        power = sum(10 ** (v / 10) for v in energies) / len(energies)
        return 10 * math.log10(power)
    except Exception:
        return None


def save_upload(root, stream, filename):
    """Store the uploaded music privately, checking it really is audio."""
    suffix = Path(filename or '').suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise ValueError('Upload an audio file: ' + ', '.join(sorted(ALLOWED_SUFFIXES)) + '.')
    target_dir = Path(root) / 'inputs'
    target_dir.mkdir(parents=True, exist_ok=True)
    temp = target_dir / ('music-' + uuid.uuid4().hex + suffix)
    # Werkzeug's FileStorage saves in chunks; a raw stream is copied instead.
    if hasattr(stream, 'save'):
        stream.save(str(temp))
    else:
        with temp.open('wb') as handle:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
                if handle.tell() > MAX_BYTES:
                    handle.close()
                    temp.unlink(missing_ok=True)
                    raise ValueError('The music file is larger than 200 MB.')
    size = temp.stat().st_size
    if not size:
        temp.unlink(missing_ok=True)
        raise ValueError('The uploaded music file is empty.')
    if size > MAX_BYTES:
        temp.unlink(missing_ok=True)
        raise ValueError('The music file is larger than 200 MB.')
    try:
        duration = probe_duration(temp)
    except ValueError:
        temp.unlink(missing_ok=True)
        raise
    if duration < 1:
        temp.unlink(missing_ok=True)
        raise ValueError('The music is shorter than one second.')
    final = music_path(root)
    final.parent.mkdir(parents=True, exist_ok=True)
    keep = target_dir / ('background_music' + suffix)
    # One bed per project, always. A new upload replaces the previous track
    # outright, including when the extension changes, so no older file can be
    # picked up by the extension fallback in `music_path`.
    temp.replace(keep)
    # Sweep after the replacement, and never touch the file just written: the
    # staging name also lives in this folder while the upload is in flight.
    for stale in target_dir.glob('background_music.*'):
        if stale.name not in (keep.name, 'background_music.name'):
            stale.unlink(missing_ok=True)
    for leftover in target_dir.glob('music-*'):
        if leftover != keep:
            leftover.unlink(missing_ok=True)
    if final != keep and final.exists():
        final.unlink()
    (target_dir / 'background_music.name').write_text(keep.name, encoding='utf-8')
    # Measured once, here, because the browser cannot: the preview has to lift a
    # quiet bed by the same amount the export does, or the two levels disagree.
    loudness = measure_loudness_lufs(keep)
    return {'name': Path(filename).name, 'size': size, 'duration_s': round(duration, 3),
            'path': str(keep.relative_to(Path(root))), 'version': MUSIC_VERSION,
            'loudness_lufs': round(loudness, 2) if loudness is not None else None}


def settings(project):
    music = (project.get('documentary_music') or {})
    # Under narration only: ducked under the voice, silent through every sound bite.
    return {'enabled': bool(music.get('enabled')), 'volume_percent': int(music.get('volume_percent') or 35),
            'narration_level': 'duck', 'speech_mode': 'duck',
            'bite_cut': True,
            'bite_fade_out_s': BITE_FADE_OUT_S, 'bite_fade_in_s': BITE_FADE_IN_S,
            'present': bool(music.get('name'))}


def target_lufs(level_percent):
    """Map the volume percentage to the bed's own loudness.

    100% is an assertive -24 LUFS bed, 35% sits around -32 LUFS, and the floor is
    -42 LUFS. This is the level the bed plays at for the whole film.
    """
    percent = max(1, min(100, int(level_percent)))
    return round(max(-42.0, min(-18.0, -42.0 + percent * 0.18)), 2)


def bite_windows(segments):
    """Sound-bite spans on the programme clock, adjacent bites joined into one."""
    spans = []
    for seg in segments or []:
        if seg.get('kind') != 'sound_bite':
            continue
        a, b = float(seg['timeline_in_s']), float(seg['timeline_out_s'])
        if spans and a - spans[-1][1] < 0.05:
            spans[-1][1] = max(spans[-1][1], b)
        else:
            spans.append([a, b])
    return [tuple(x) for x in spans]


def narration_windows(segments):
    """Narration spans on the programme clock, adjacent ones joined."""
    spans = []
    for seg in segments or []:
        if seg.get('kind') != 'narration':
            continue
        a, b = float(seg['timeline_in_s']), float(seg['timeline_out_s'])
        if spans and a - spans[-1][1] < 0.05:
            spans[-1][1] = max(spans[-1][1], b)
        else:
            spans.append([a, b])
    return [tuple(x) for x in spans]


DUCK_RAMP_S = 0.4


def bite_gain_expression(windows, fade_out=BITE_FADE_OUT_S, fade_in=BITE_FADE_IN_S, narration=None, duck_db=None):
    """An ffmpeg `volume` expression for the bed's shape over the film.

    * 0 through every sound bite: silence is reached exactly as the bite starts
      (fading over the last `fade_out` of narration) and the bed rises again over
      `fade_in` after the bite ends.
    * Ducked by `duck_db` while the narration runs, easing in and out over DUCK_RAMP_S.
    * Full level anywhere else (a silent picture tail, for example).
    """
    terms = []
    for a, b in windows or []:
        # 0 inside [a, b]; ramps to 1 over fade_out before a and fade_in after b.
        terms.append(f"clip(max(({a:.4f}-t)/{fade_out:.4f},(t-{b:.4f})/{fade_in:.4f}),0,1)")
    if narration and duck_db:
        floor = 10 ** (-abs(duck_db) / 20)
        r = DUCK_RAMP_S
        # n(t): 1 inside any narration span, easing to 0 over r outside it.
        inside = '+'.join(f"clip(min((t-{a:.4f})/{r:.4f}+1,({b:.4f}-t)/{r:.4f}+1),0,1)" for a, b in narration)
        terms.append(f"(1-{1-floor:.6f}*clip({inside},0,1))")
    return '*'.join(terms) if terms else '1'


def build_bed(project, music_file, destination, duration_s, segments, level_percent=None, duck=False, work_dir=None, narration_level=None):
    with timebudget.film_length(duration_s):
        return _build_bed(project, music_file, destination, duration_s, segments, level_percent, duck, work_dir, narration_level)


def _build_bed(project, music_file, destination, duration_s, segments, level_percent=None, duck=False, work_dir=None, narration_level=None):
    """Loop and level the music, then cut it to an exact-length WAV bed.

    The bed plays only under the narration. It fades out into every sound bite, stays
    silent while the footage speaks, and fades back in as the narrator resumes. While
    the narrator talks it sits DUCK_DEPTH_DB under its set level.
    """
    music_file = Path(music_file).resolve()
    destination = Path(destination).resolve()
    if not music_file.is_file():
        raise ValueError('The background music file is missing.')
    level_percent = int(level_percent if level_percent is not None else settings(project)['volume_percent'])
    if not 1 <= level_percent <= 100:
        raise ValueError('Music volume must be a whole percentage from 1 to 100.')
    if duration_s <= 0:
        raise ValueError('The documentary has no duration for music.')
    narration_level = narration_level if narration_level in ('mute', 'duck') else settings(project)['narration_level']
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    work = Path(work_dir) if work_dir else destination.parent
    work.mkdir(parents=True, exist_ok=True)
    looped = work / ('music-loop-' + uuid.uuid4().hex + '.wav')
    try:
        # `aloop` loops in the filter graph and `atrim` cuts an exact length;
        # `-stream_loop` with `-t` can end several frames short of the target.
        _run([ff, '-hide_banner', '-loglevel', 'error', '-y', '-i', str(music_file),
              '-vn', '-filter_complex',
              f'[0:a]aloop=loop=-1:size=2e9,atrim=0:{duration_s:.3f},asetpts=PTS-STARTPTS,aresample=48000,'
              f'aformat=sample_fmts=s16:sample_rates=48000:channel_layouts=stereo[a]',
              '-map', '[a]', '-c:a', 'pcm_s16le', str(looped)])
        from documentary_audio import measure_loudness
        measured = measure_loudness(ff, looped)['integrated_lufs']
        want = target_lufs(level_percent)
        gain_db = max(-30.0, min(30.0, want - measured))
        windows = bite_windows(segments)
        spoken = narration_windows(segments)
        filters = [f'volume={gain_db:.3f}dB']
        # Ducked under the narration, silent under every sound bite, short fades
        # between; see bite_gain_expression. The editor preview applies the same shape.
        if windows or spoken:
            filters.append(f"volume='{bite_gain_expression(windows, narration=spoken, duck_db=DUCK_DEPTH_DB)}':eval=frame")
        filters.append(f'atrim=0:{duration_s:.3f}')
        filters.append('alimiter=limit=0.891251:level=0:latency=1')
        filters.append('aresample=48000')
        filters.append('aformat=sample_fmts=s16:sample_rates=48000:channel_layouts=stereo')
        _run([ff, '-hide_banner', '-loglevel', 'error', '-y', '-i', str(looped), '-af', ','.join(filters),
              '-c:a', 'pcm_s16le', str(destination)])
    finally:
        looped.unlink(missing_ok=True)
    with av.open(str(destination)) as media:
        stream = media.streams.audio[0]
        length = float(stream.duration * stream.time_base) if stream.duration is not None else 0
    if abs(length - duration_s) > 0.05:
        destination.unlink(missing_ok=True)
        raise ValueError('The music bed length does not match the timeline.')
    return {'duration_s': length, 'level_percent': level_percent, 'nominal_lufs': target_lufs(level_percent),
            'measured_source_lufs': round(measured, 2), 'gain_db': round(gain_db, 2),
            'ducked_under_speech': True,
            'duck_depth_db': DUCK_DEPTH_DB,
            'narration_level': 'duck',
            'speech_mode': 'duck',
            'narration_windows': [{'start_s': round(a, 3), 'end_s': round(b, 3)} for a, b in spoken],
            'mute_windows': [{'start_s': round(a, 3), 'end_s': round(b, 3)} for a, b in windows],
            'music_version': MUSIC_VERSION}


# How far the bed drops while speech is present. 11 dB keeps the score audible as a
# bed while leaving the words clearly on top; deeper starts to sound like the music
# is being switched off and on.
DUCK_DEPTH_DB = 11.0



