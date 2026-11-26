"""Frame-indexed documentary MP4 assembly primitive.

The caller must enforce final editorial, rights and project-version gates.
This module never approves footage.
"""
import timebudget
from fractions import Fraction
from pathlib import Path
import copy
import subprocess
import tempfile

import av
import imageio_ffmpeg
from documentary import annotate_plan, build_timeline
from documentary_audio import build_audio
# `ultrafast` is not just faster, it is far larger: on this project's footage it
# wrote 4.3x the bytes of `veryfast` at the same CRF, because it drops the
# compression tools and falls back to the Constrained Baseline profile. The
# export encodes twice (clips, then captions), so every byte was paid twice.
VIDEO_PRESET = 'veryfast'

def sweep_work_dirs(renders_dir, keep=None):
    """Remove work directories left by a render that was killed, not raised.

    `TemporaryDirectory` cleans up when the job finishes or raises, but a killed
    process leaves its `documentary-final-*` directory behind with hundreds of
    megabytes of intermediate audio. Rendering again is the safe moment to clear
    them, because no other render is running against this project.
    """
    import shutil
    removed = 0
    for old in Path(renders_dir).glob('documentary-final-*'):
        if not old.is_dir() or (keep and old.name == keep):
            continue
        shutil.rmtree(old, ignore_errors=True)
        removed += 1
    return removed


from documentary_render_plan import plan as picture_plan, load_decisions
from strict_cuts import inspect_video


def _low_priority():
    """Below-normal priority: a render uses the spare power, never the PC's attention."""
    import os, sys
    if sys.platform == 'win32':
        return {'creationflags': getattr(subprocess, 'BELOW_NORMAL_PRIORITY_CLASS', 0x4000) | getattr(subprocess, 'CREATE_NO_WINDOW', 0)}
    if hasattr(os, 'nice'):
        return {'preexec_fn': lambda: os.nice(5)}
    return {}


def _piece_workers(width=1920, height=1080):
    """How many pieces to encode at once: bounded by cores and by free memory.

    Every piece is its own two-thread encode, so half the logical cores keeps the
    whole processor busy (v18 stopped at 4, leaving half of a 16-thread PC idle).
    Memory per piece grows with the frame size: about 0.6 GB at 1080p, 1.6 GB at 4K.
    STORYROOM_RENDER_WORKERS overrides (1-8).
    """
    import os
    try:
        override=int(os.environ.get('STORYROOM_RENDER_WORKERS','0'))
    except ValueError: override=0
    if override:return max(1,min(8,override))
    cpus=os.cpu_count() or 2
    core_limit=max(1,min(8,cpus//2))
    per_piece=max(400,min(1600,round(1600*(width*height)/(3840*2160))))*1024*1024
    try:
        import psutil
        mem_limit=max(1,int(psutil.virtual_memory().available/per_piece))
        return min(core_limit,mem_limit)
    except ImportError:
        return core_limit


_HW = {}


def _gpu_encoders(ff, quality):
    """Working graphics-card H.264 encoders at this quality (lower is better)."""
    import os
    choices = []
    q = str(quality)
    if os.environ.get('STORYROOM_ENCODER', '').lower() not in ('cpu', 'x264', 'libx264'):
        for name, args in (
            ('h264_nvenc', ['-c:v', 'h264_nvenc', '-preset', 'p4', '-rc', 'vbr', '-cq', q, '-b:v', '0', '-bf', '0']),
            ('h264_qsv', ['-c:v', 'h264_qsv', '-preset', 'faster', '-global_quality', str(quality + 1), '-bf', '0']),
            ('h264_amf', ['-c:v', 'h264_amf', '-quality', 'speed', '-rc', 'cqp', '-qp_i', str(quality - 1), '-qp_p', str(quality + 1), '-bf', '0']),
        ):
            if name not in _HW:
                try:
                    probe = subprocess.run([ff, '-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i',
                                            'testsrc2=s=640x360:r=30:d=0.4', '-vf', 'format=yuv420p', *args, '-f', 'null', '-'],
                                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20, **_low_priority())
                    _HW[name] = probe.returncode == 0
                except (OSError, subprocess.SubprocessError):
                    _HW[name] = False
            if _HW[name]:
                choices.append(args)
    return choices[:1]


def _run(args):
    run = subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                         text=True, timeout=timebudget.seconds(), **_low_priority())
    if run.returncode:
        raise ValueError('Documentary assembly failed: ' + run.stderr[-800:])


def _video_info(path):
    with av.open(str(path)) as media:
        if not media.streams.video:
            raise ValueError('Assembled documentary has no video stream.')
        stream = media.streams.video[0]
        # base_rate is the container timebase and is exactly 30000/1001 for an NTSC
        # frame rate. average_rate is frames/duration, which only equals the
        # nominal rate when the duration divides exactly -- a clip trimmed to its
        # own frame count is short by one frame, so average_rate drifts to
        # 29.9849 and every comparison against 30000/1001 failed on a clip that
        # was in fact correct. Fall back to average_rate only if no timebase.
        rate = stream.base_rate or stream.average_rate
        return stream.frames, Fraction(rate) if rate else None


FONT_DIR = Path(__file__).resolve().parent / 'static' / 'fonts'


# A soundtrack overhang past the last frame (under half a frame) is dropped only when it
# is at or below this peak level: digital silence or the noise floor of a recording.
SILENT_TAIL_DB = -50.0


def _tail_peak_db(ff, audio, start_s):
    """Peak level in dBFS of `audio` from `start_s` to its end, or None if unmeasurable."""
    import re as _re
    try:
        run = subprocess.run([ff, '-hide_banner', '-nostats', '-ss', f'{float(start_s):.9f}', '-i', str(audio),
                              '-af', 'volumedetect', '-f', 'null', '-'], stdout=subprocess.DEVNULL,
                             stderr=subprocess.PIPE, text=True, timeout=120, **_low_priority())
    except (OSError, subprocess.SubprocessError):
        return None
    found = _re.search(r'max_volume:\s*(-?inf|-?[\d.]+) dB', run.stderr or '')
    if not found:
        return None
    return float('-inf') if 'inf' in found.group(1) else float(found.group(1))


def _ffpath(path):
    """A file path as a quoted ffmpeg filter value, safe on Windows.

    `C:\\Users\\...` broke the filter graph on its drive colon and backslashes. Forward
    slashes work for ffmpeg on every platform; the colon and quote are escaped.
    """
    text = str(path).replace('\\', '/').replace(':', '\\:').replace("'", "\\'")
    return "'" + text + "'"


def _boundary_transitions(project, spans):
    """{span index: (transition, frames)} for the cut INTO that span.

    The transition is stored on the last scene before the cut. It is shortened so it
    never swallows the incoming shot, and dropped (a hard cut) when the shot is tiny.
    """
    import transitions
    scenes = {s.get('id'): s for s in project.get('scenes') or []}
    out = {}
    for i in range(1, len(spans)):
        # A cutaway is an editorial switch inside ONE uninterrupted audio beat.
        # Do not inherit a scene-level dissolve across its entry or return.
        if spans[i - 1].get('cutaway_id') or spans[i].get('cutaway_id'):
            continue
        scene = scenes.get((spans[i - 1].get('scene_ids') or [None])[-1]) or {}
        key = scene.get('transition') or 'cut'
        if not transitions.is_transition(key):
            continue
        n = int(scene.get('transition_handle_frames') or transitions.frames_for(key))
        n = min(n, spans[i]['source_frame_count'] - 1, 60)
        if n >= 2:
            out[i] = (key, n)
    return out


_NO_SEEK = object()


def _span_filters(span, first, count, width, height, fps, rate, enhance_picture, tail=False, seek_offset=_NO_SEEK, still=False):
    """Filters for `count` output frames of a span, starting `first` frames into it.

    `first` may run past the span's own end (the outgoing side of a transition); the
    source's following frames are used, and its last frame is held if it ends first.

    With `seek_offset` (the video stream's start relative to the file's, in seconds)
    returns `(seek_seconds, filters)`: the caller puts `-ss seek_seconds` before `-i`.
    An unknown offset (None: the file could not be probed) still returns the pair, with
    a seek of 0, so the shot decodes from the first frame. Without the argument at all,
    returns the filters alone.
    """
    halve = span.get('frame_conversion') == 'halve'
    conform = span.get('frame_conversion') == 'conform'
    begin = span['source_start_frame']
    if conform:
        src_rate = Fraction(span.get('source_rate_fps') or span.get('source_fps') or fps)
        ratio = src_rate / fps
        a = begin + int(first * ratio); b = begin + int(-(-(first + count) * ratio // 1)) + 2
    elif halve:
        src_rate = Fraction(span.get('source_rate_fps') or span.get('source_fps') or fps * 2)
        a = begin + 2 * first; b = a + 2 * count
    else:
        src_rate = fps
        a = begin + first; b = a + count
    # Jump straight to the shot instead of decoding the source from its first frame
    # (a shot 4 minutes into a clip used to decode 4 minutes of video and throw it
    # away; 188 shots made that most of the render). The input seek lands half a
    # frame before frame `a`, ffmpeg's accurate seek drops everything earlier, so the
    # first frame out is exactly frame `a` and the trim below counts from there.
    seek = 0.0
    if a > 0 and seek_offset is not None and seek_offset is not _NO_SEEK:
        seek = float(seek_offset) + float((Fraction(a) - Fraction(1, 2)) / src_rate)
        if seek > 0:
            b -= a; a = 0
        else:
            seek = 0.0
    # A narrow output (a 9:16 reel from a 16:9 source) is filled and cropped from the
    # centre; a wide output keeps the whole frame.
    fill = width / height < 16 / 9
    fit = ('increase,crop=' + str(width) + ':' + str(height)) if fill else (
        'decrease,pad=' + str(width) + ':' + str(height) + ':(ow-iw)/2:(oh-ih)/2:black')
    select = 'select=not(mod(n' + chr(92) + ',2)),' if halve else ''
    # v19: a still picture is decoded once and repeated (it used to be re-read and
    # decoded for every frame), and it now has frames to blend in a transition too.
    from still_layers import held_source
    held = held_source(rate) if still else ''
    if conform:
        filters = (f"trim=start_frame={a}:end_frame={b},setpts=PTS-STARTPTS,fps={rate}:round=near,"
                   f"tpad=stop_mode=clone:stop=4,setpts=N/({rate}*TB),"
                   f"scale={width}:{height}:force_original_aspect_ratio={fit},setsar=1")
    else:
        filters = (f"{held}trim=start_frame={a}:end_frame={b},{select}setpts=N/({rate}*TB),"
                   f"scale={width}:{height}:force_original_aspect_ratio={fit},setsar=1")
    if tail:
        # Past the end of the source there may be nothing left: hold the last frame.
        filters += f',fps={rate},tpad=stop_mode=clone:stop={count}'
    scale = span['picture_scale']
    camera = span.get('camera')
    if camera:
        # Animated zoom/pan replaces the slot's static scale. `first` is where this
        # encode starts inside the slot; past the slot's end the last framing holds.
        from cinematic import ffmpeg_filter
        total = span.get('output_frame_count') or span['source_frame_count']
        filters += ',' + ffmpeg_filter(camera, width, height, first, total) + ',setsar=1'
    elif scale != 100:
        sw = round(width * scale / 200) * 2; sh = round(height * scale / 200) * 2
        # Reset the pixel aspect after the zoom's crop, or the file plays stretched.
        filters += f',scale={sw}:{sh},crop={width}:{height},setsar=1'
    if enhance_picture:
        filters += ',hqdn3d=1:1:0:0,unsharp=5:5:0.35:5:5:0'
    # Work in an exact frame time base before compositing. A 60 fps input
    # cannot represent successive 1001/30000-second frames in its own ticks.
    from still_layers import frame_tb
    filters += f',settb={frame_tb(rate)},setpts=N,format=yuv420p'
    if seek_offset is _NO_SEEK:
        return filters
    return seek, filters


_OFFSETS = {}


def _seek_offset(source):
    """How far the video stream starts after the file's own start, in seconds.

    An input seek is measured from the file's start; frame numbers count from the
    video's first frame. They differ when audio starts first (some downloads)."""
    st = source.stat(); key = (str(source), st.st_size, st.st_mtime_ns)
    if key not in _OFFSETS:
        offset = Fraction(0)
        try:
            with av.open(str(source)) as media:
                v = media.streams.video[0]
                vs = Fraction(v.start_time) * v.time_base if getattr(v, 'start_time', None) is not None and v.time_base else Fraction(0)
                fs = Fraction(media.start_time, 1000000) if getattr(media, 'start_time', None) else Fraction(0)
                offset = max(Fraction(0), vs - fs)
        except Exception:
            offset = None          # unknown: decode from the start, as before
        _OFFSETS[key] = offset
    return _OFFSETS[key]


def _ass_ranges(text, fps):
    """(first frame, end frame) of every subtitle event, a frame wider on each side."""
    import re
    out = []
    def secs(v):
        h, m, sec = v.split(':'); return int(h) * 3600 + int(m) * 60 + float(sec)
    for line in text.splitlines():
        m = re.match(r'Dialogue:\s*[^,]*,([^,]+),([^,]+),', line)
        if m:
            out.append((int(secs(m.group(1)) * fps) - 1, int(secs(m.group(2)) * fps) + 2))
    return out


def _ss(seek):
    return ['-ss', f'{seek:.6f}'] if seek > 0 else []


def _make_blend(ff, out_span, out_source, in_span, in_source, key, n, width, height, fps, rate,
                enhance_picture, encoders, target, post=None, x264=None, stills=(False, False)):
    """Encode the n-frame transition from the end of one span into the start of the next."""
    import transitions
    tb = f'settb=1/{fps.numerator},fps={rate}'
    sa, a = _span_filters(out_span, out_span['source_frame_count'], n, width, height, fps, rate, enhance_picture, tail=True,
                          seek_offset=0 if stills[0] else _seek_offset(out_source), still=stills[0])
    sb, b = _span_filters(in_span, 0, n, width, height, fps, rate, enhance_picture,
                          seek_offset=0 if stills[1] else _seek_offset(in_source), still=stills[1])
    seconds = f'{float(Fraction(n, 1) / fps):.6f}'
    names = [transitions.LIBRARY.get(key, transitions.LIBRARY['fade'])[0] or 'fade']
    if names[0] != 'fade':
        names.append('fade')            # an older ffmpeg without this one still blends
    last = None
    if encoders and isinstance(encoders[0], str):
        encoders = [encoders]           # a single encoder's arguments
    extra, label = [], 'v'
    for name in names:
        graph = (f'[0:v]{a},{tb}[a];[1:v]{b},{tb}[b];'
                 f'[a][b]xfade=transition={name}:duration={seconds}:offset=0,format=yuv420p[v]')
        if post:
            extra, more, label = post
            graph = graph.replace('format=yuv420p[v]', 'format=yuv420p[p]') + ';' + ';'.join(more)
        for encoder in encoders:
            try:
                _run([ff, '-hide_banner', '-loglevel', 'error', '-y', *_ss(sa), '-i', str(out_source), *_ss(sb), '-i', str(in_source),
                      *extra, '-filter_complex', graph, '-map', f'[{label}]', '-an', '-r', rate, '-fps_mode', 'cfr', *encoder,
                      '-frames:v', str(n), str(target)])
                got, actual = _video_info(target)
                if got == n and actual == fps:
                    return
                last = ValueError('The transition changed the frame count.')
            except ValueError as e:
                last = e
    raise last or ValueError('The transition could not be made.')


def render(root, project, sound_plan, destination, width, height, progress=lambda *_: None, enhance_picture=False, subtitle_ass=None, cancel_check=lambda: None, music=False, on_step=None):
    """Assemble the final MP4. Every ffmpeg step gets a time budget scaled to the film."""
    bites = sum(float(b.get('source_out_s', 0)) - float(b.get('source_in_s', 0)) for b in (sound_plan or {}).get('bites') or [])
    with timebudget.film_length(float((project.get('voiceover') or {}).get('duration') or 0) + bites):
        return _render(root, project, sound_plan, destination, width, height, progress, enhance_picture, subtitle_ass,
                       cancel_check, music, on_step)


def _render(root, project, sound_plan, destination, width, height, progress=lambda *_: None, enhance_picture=False, subtitle_ass=None, cancel_check=lambda: None, music=False, on_step=None):
    """Render compatible, verified picture ranges and script captions, non-destructively.

    This is only an assembly primitive, NOT authorization to export. Caller must
    apply editorial/rights checks and check for changes before publishing output.
    Original source files and original SRT are never changed.
    """
    root = Path(root).resolve(); destination = Path(destination).resolve()
    if width < 64 or height < 64 or width % 2 or height % 2 or width > 7680 or height > 7680:
        raise ValueError('Output size must have even dimensions from 64 to 7680 pixels.')
    if destination.exists():
        raise ValueError('The destination already exists; existing files are never overwritten.')
    if not destination.is_relative_to(root / 'renders') or destination.suffix.lower() != '.mp4':
        raise ValueError('Destination must be a new MP4 in this project’s renders folder.')
    step = on_step or (lambda *_: cancel_check())
    import perflog
    phases = perflog.Steps('render', size=f'{width}x{height}', enhance_picture=bool(enhance_picture))
    phases.step('plan_and_frame_check')
    annotated = annotate_plan(project, root, copy.deepcopy(sound_plan))
    step('Checking picture', 'Matching every shot to its source frames.', 2)
    picture = picture_plan(project, root, annotated, load_decisions(root))
    if not picture['picture_compatible']:
        raise ValueError('Picture frame check failed: ' + '; '.join(picture['errors']))
    assets = {a['id']: a for a in project.get('assets', [])}
    # A photograph may arrive as an image file, a P##_..._video carrier, or an
    # explicitly mapped static interval from footage.  Mark only those verified
    # still roles; interviews and ordinary moving clips retain native playback.
    from truecrime_camera import still_visual_kind
    scenes_by_id = {s.get('id'): s for s in project.get('scenes') or []}
    for span in picture['spans']:
        shot = [scenes_by_id[sid] for sid in span.get('scene_ids') or [] if sid in scenes_by_id]
        asset = assets.get(span.get('asset_id')) or {}
        still_kind = still_visual_kind(asset, shot)
        if still_kind and span.get('kind') == 'narration':
            span['photo_frame_kind'] = still_kind
    fps = Fraction(picture['output_fps']); rate = f'{fps.numerator}/{fps.denominator}'
    total_frames = sum(s['source_frame_count'] for s in picture['spans'])
    if not total_frames:
        raise ValueError('The documentary has no picture frames.')
    video_duration = Fraction(total_frames, 1) / fps
    ff = imageio_ffmpeg.get_ffmpeg_exe(); destination.parent.mkdir(parents=True, exist_ok=True)
    sweep_work_dirs(destination.parent)
    with tempfile.TemporaryDirectory(prefix='documentary-final-', dir=destination.parent) as temp:
        work = Path(temp); audio = work / 'audio.wav'
        phases.step('soundtrack')
        step('Preparing soundtrack', 'Narration, sound bites and music.', 3)
        levels = build_audio(root, project, annotated, audio, strict_handoffs=True, music=music,
                             progress=lambda i, n: step('Preparing soundtrack', f'Audio piece {min(i+1, n)} of {n}.', round(3 + 2 * i / max(1, n), 1)))
        cancel_check()
        audio_duration = Fraction(round(levels['duration_s'] * 48000), 48000)
        difference = video_duration - audio_duration
        # A last output frame naturally rounds the end of the original narration.
        # Any larger silent picture tail requires an explicit saved authorization.
        allowed_tail = Fraction(1, 2) / fps
        # The decoded last narration segment may end before its container's
        # reported duration. No spoken samples are invented; this is silence
        # already implied by the declared end. Non-final handoffs were checked
        # to within two samples by strict_handoffs above.
        last = build_timeline(project, annotated)['segments'][-1]
        expected_last = Fraction(round((last['source_out_s']-last['source_in_s'])*48000),48000)
        decoded_last = Fraction(round(levels['segment_lengths_s'][-1]*48000),48000)
        missing_last = max(Fraction(0),expected_last-decoded_last)
        if missing_last > Fraction(1,2):raise ValueError('Decoded narration ends too far before the declared duration.')
        allowed_tail += missing_last
        record = project.get('documentary_beat_review') or {}
        if record.get('silent_tail_authorized'):
            voice_ms = round(float(project['voiceover']['duration']) * 1000)
            for g in record.get('approved_gaps', []):
                if g['narration_out_ms'] == voice_ms:
                    allowed_tail += Fraction(max(0, (g['source_out_ms']-g['source_in_ms'])-(g['narration_out_ms']-g['narration_in_ms'])), 1000)
        overhang_s = 0.0
        closing_hold = 0
        if -Fraction(1, 2) / fps < difference < -Fraction(1, 48000):
            # The picture ends on a whole output frame; the soundtrack is the exact
            # sum of its pieces in samples. They can land a fraction of a frame
            # apart, and the soundtrack being those few samples longer used to stop
            # the render outright (one real film: 0.000162 s, 8 samples). The mux
            # below already ends the file at the picture's last frame, so accept the
            # overhang only when it is silent: nothing audible is ever cut.
            peak_db = _tail_peak_db(ff, audio, video_duration)
            if peak_db is None or peak_db > SILENT_TAIL_DB:
                # Keep every audible sample. Only the final picture gains a frame.
                closing_hold = 1
                total_frames += closing_hold
                video_duration = Fraction(total_frames, 1) / fps
                difference = video_duration - audio_duration
            else:
                overhang_s = -float(difference)
        elif difference < -Fraction(1, 48000) or difference > allowed_tail:
            raise ValueError(f'Picture/audio end differs by {float(difference):.6f}s; no unapproved trim or silence was applied.')
        spans = picture['spans']
        import time as _t0; render_began = _t0.monotonic()
        incoming = _boundary_transitions(project, spans)
        # ---- What is drawn over the picture, all timed on the film's own clock -------
        caption_items = []          # (first frame, end frame, filter); end None = check per piece
        if picture['captions'] and picture.get('burn_captions', True) is not False:
            # A Windows installation has system fonts even when optional bundled
            # font assets are absent; do not block an otherwise valid export.
            from captions import font_path
            font = font_path('documentary')
            if not font.is_file():
                raise ValueError('No usable caption font found. Install a system font (e.g. Arial) before exporting captions.')
            from person_overlays import covered_spans, caption_enable, frame_of
            covered = covered_spans(project, root, annotated)
            for i, caption in enumerate(picture['captions']):
                text = work / f'caption-{i:03}.txt'; text.write_text(caption['text'], encoding='utf-8')
                enable = caption_enable(caption['timeline_in_ms']/1000, caption['timeline_out_ms']/1000, covered, fps)
                # A locator/name caption: clean semibold on a soft dark plate, top centre.
                caption_items.append((frame_of(caption['timeline_in_ms']/1000, fps) - 1, frame_of(caption['timeline_out_ms']/1000, fps) + 1,
                                      f"drawtext=fontfile={_ffpath(font)}:textfile={_ffpath(text)}:expansion=none:"
                                      f"fontsize={max(16,height//26)}:fontcolor=white:shadowcolor=black@0.6:shadowx=0:shadowy={max(1,height//540)}:"
                                      f"box=1:boxcolor=black@0.45:boxborderw={max(6,height//80)}:"
                                      f"x=(w-text_w)/2:y=h*0.07:enable='{enable}'"))
        subtitle_ranges = []
        if subtitle_ass is not None:
            if not isinstance(subtitle_ass, str) or not subtitle_ass.startswith('[Script Info]'):
                raise ValueError('Adjusted subtitle data is invalid; no subtitles were omitted.')
            ass_file=work/'adjusted-subtitles.ass';ass_file.write_text(subtitle_ass,encoding='utf-8')
            ass_filter = f'ass=filename={_ffpath(ass_file)}:fontsdir={_ffpath(FONT_DIR)}'
            subtitle_ranges = _ass_ranges(subtitle_ass, fps)
        cancel_check()
        # The script opens with `Cut Action: FADE IN FROM BLACK`. A fade is a
        # brightness ramp on existing frames, not a dissolve: the frame count, the
        # timing and every cut stay exactly as reviewed. `fade_out` is the closing
        # ramp to black, also frame-neutral.
        fade_in_s = float(picture.get('fade_in_s') or 0)
        fade_out_s = float(picture.get('fade_out_s') or 0)
        fade_items = []
        if fade_in_s:
            fade_items.append((0, int(fade_in_s * fps) + 2, f'fade=t=in:st=0:d={fade_in_s:.3f}'))
        if fade_out_s:
            start = max(0.0, float(video_duration) - fade_out_s)
            fade_items.append((int(start * fps) - 2, total_frames + 1, f'fade=t=out:st={start:.3f}:d={fade_out_s:.3f}'))
        # Person photo cards go over the footage, which keeps playing under them; the
        # captions are drawn after the cards so text always stays on top.
        from person_overlays import render_filters
        card_data = {}
        _, _, card_count = render_filters(project, root, annotated, width, height, rate, work, 1, cache=card_data)
        cta_cache = {}
        watermark_cache = {}
        sticker_cache = {}
        def overlays(first_input, f0, count):
            """(extra inputs, graph, output label) drawing everything due in frames
            f0 .. f0+count-1 over [p], or None when nothing falls there. The piece is
            moved onto the film's clock for the drawing, then back to start at zero."""
            f1 = f0 + count
            def live(items):
                return [f for a, b, f in items if a < f1 and b > f0]
            fades = live(fade_items); captions = live(caption_items)
            if any(a < f1 and b > f0 for a, b in subtitle_ranges):
                captions.append(ass_filter)
            inputs, steps, cards = render_filters(project, root, annotated, width, height, rate, work, first_input,
                                                  between=(f0, f1), cache=card_data)
            from channel_cta import render_filters as cta_render_filters
            # Person-card inputs are numbered from first_input. CTA image inputs
            # follow them. Both draw over the film's master clock, without changing
            # scene lengths or any audio.
            next_input = first_input + inputs.count('-i')
            cta_inputs, cta_steps, cta_count = cta_render_filters(
                project, root, annotated, width, height, rate, work, next_input,
                between=(f0, f1), cache=cta_cache,
                input_label='cards' if steps else 'base')
            # v26 stickers: over the picture, cards and CTA; under the watermark and captions.
            from stickers import render_filters as sticker_render_filters
            current = 'cta' if cta_steps else ('cards' if steps else 'base')
            stk_first = next_input + cta_inputs.count('-i')
            stk_inputs, stk_steps, stk_count = sticker_render_filters(
                project, root, width, height, rate, work, stk_first, between=(f0, f1), cache=sticker_cache,
                input_label=current)
            if stk_steps:
                current = 'stk'
            # Motion graphics: non-destructive kinetic typography layer over the
            # picture, cards, CTA and stickers. Disabled by default; nothing is
            # drawn unless the user enables the feature for this project.
            from motion_render import render_filters as mg_render_filters
            mg_cache = {}
            mg_first = stk_first + stk_inputs.count('-i') + cta_inputs.count('-i')
            mg_inputs, mg_steps, mg_count = mg_render_filters(
                project, root, width, height, rate, work, mg_first, between=(f0, f1),
                cache=mg_cache, input_label=current)
            if mg_steps:
                current = 'mg'
            # The channel watermark is on every frame of the film, end to end: over the
            # picture, cards, CTA, stickers and motion graphics, under captions.
            from watermark import render_filters as wm_render_filters
            wm_first = mg_first + mg_inputs.count('-i')
            wm_inputs, wm_steps = wm_render_filters(
                project, root, width, height, rate, work, wm_first, count, f0,
                current, cache=watermark_cache)
            if not (fades or captions or cards or cta_count or stk_count or mg_steps or wm_steps):
                return None
            shift = f'setpts=PTS+{f0}/({rate}*TB)'
            graph = ['[p]' + ','.join([shift] + fades + ['null']) + '[base]']
            if steps: graph += steps
            if cta_steps: graph += cta_steps
            if stk_steps: graph += stk_steps
            if mg_steps: graph += mg_steps
            if wm_steps:
                graph += wm_steps
                current = 'wm'
            graph += ['[' + current + ']' + ','.join(captions + ['setpts=PTS-STARTPTS', 'format=yuv420p']) + '[out]']
            return inputs + cta_inputs + stk_inputs + mg_inputs + wm_inputs, graph, 'out'
        # ---- The pieces: each encoded once, at delivery quality, side by side --------
        x264 = ['-c:v', 'libx264', '-preset', VIDEO_PRESET, '-bf', '0', '-crf', '20', '-threads', '2',
                '-video_track_timescale', str(fps.numerator)]
        # A graphics card encodes when there is one; any piece it gets wrong is redone
        # on the processor.
        piece_encoders = [g + ['-video_track_timescale', str(fps.numerator)] for g in _gpu_encoders(ff, 21)] + [x264]
        starts = []; at = 0
        for span in spans:
            starts.append(at); at += span['source_frame_count']
        clean_still_cache = {}
        import threading
        clean_still_lock = threading.Lock()
        def source_of(span):
            asset = assets.get(span['asset_id']) or {}; source = (root / asset.get('path', '')).resolve()
            allowed = asset.get('kind') == 'video' or (span.get('cutaway_id') and asset.get('kind') == 'image')
            valid_dir = (root / 'sources') if asset.get('kind') == 'video' else (root / 'assets')
            if not allowed or not source.is_relative_to(valid_dir) or not source.is_file():
                raise ValueError('An assigned source video or approved cutaway photograph is missing.')
            if asset.get('kind') == 'image':
                # v17: news panels, logos and black bars are cut away (never painted
                # over), then the clean photo is centred over a blur of itself at the
                # output size. The source file is never modified.
                aid = str(span['asset_id'])
                if aid not in clean_still_cache:
                    from clean_photo_framing import framed_still_file
                    prepared = work / ('still-'+aid.replace('/', '_').replace('\\', '_')+'.jpg')
                    framed_still_file(source, prepared, width, height, asset.get('crop'))
                    clean_still_cache[aid] = prepared
                return clean_still_cache[aid]
            if span.get('photo_frame_kind'):
                # Decode the declared still interval once, then use the exact same
                # deterministic frame treatment as a directly uploaded photograph.
                # The source video and its script timestamps remain untouched.
                native_rate = Fraction(span.get('source_rate_fps') or span.get('source_fps') or fps)
                at = float(Fraction(int(span.get('source_start_frame') or 0), 1) / native_rate)
                key = f"{span['asset_id']}-{int(span.get('source_start_frame') or 0)}-{width}x{height}"
                with clean_still_lock:
                    if key not in clean_still_cache:
                        from conform import capture
                        import cv2
                        from PIL import Image
                        from clean_photo_framing import framed_image_file
                        prepared = work / ('video-still-' + key.replace('/', '_').replace('\\', '_') + '.jpg')
                        cap = capture(source)
                        try:
                            cap.set(cv2.CAP_PROP_POS_MSEC, at * 1000); ok, bgr = cap.read()
                        finally:
                            cap.release()
                        if not ok:
                            raise ValueError(f"{span['labels'][0]}: still-picture frame could not be decoded.")
                        framed_image_file(Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)),
                                          prepared, width, height)
                        clean_still_cache[key] = prepared
                return clean_still_cache[key]
            return source
        # A graphics-card encoder that gets one piece wrong is dropped for the rest of
        # this render. Before, every one of several hundred pieces was encoded on the
        # card, rejected by the frame check, and then encoded again on the processor,
        # silently doubling (or worse) the render time.
        import time as _time
        gpu_lock = threading.Lock(); gpu_failed = []
        timing = {'gpu': 0, 'cpu': 0, 'fallbacks': 0, 'seconds': 0.0, 'reasons': []}
        def encode(make_cmd, frames, target, label):
            for encoder in piece_encoders:
                if encoder is not x264 and gpu_failed:
                    continue
                began = _time.monotonic(); reason = ''
                try:
                    _run(make_cmd(encoder))
                    got, actual_rate = _video_info(target)
                except ValueError as error:
                    if encoder is x264:
                        raise
                    got, actual_rate, reason = None, None, str(error)[:200]
                if got == frames and actual_rate == fps:
                    with gpu_lock:
                        timing['cpu' if encoder is x264 else 'gpu'] += 1
                        timing['seconds'] += _time.monotonic() - began
                    return
                if encoder is not x264:
                    with gpu_lock:
                        timing['fallbacks'] += 1
                        if not gpu_failed:
                            gpu_failed.append(encoder[1])
                            timing['reasons'].append(f'{label}: {encoder[1]} rejected '
                                                     f'(frames {got}/{frames}, rate {actual_rate} vs {fps}) {reason}'.strip())
            raise ValueError(f'{label}: encoded picture has {got} frames at {actual_rate} fps; expected {frames} at {fps} fps.')
        def is_still(span):
            return bool(span.get('photo_frame_kind') or
                        (span.get('cutaway_id') and (assets.get(span['asset_id']) or {}).get('kind') == 'image'))
        def render_span(span):
            """A video-carried still becomes a one-frame source without changing clocks."""
            if not span.get('photo_frame_kind'):
                return span
            copy_span = dict(span)
            copy_span.update(source_start_frame=0,
                             source_end_frame=span['source_frame_count'],
                             frame_conversion='none',
                             source_rate_fps=str(fps), source_fps=str(fps))
            return copy_span
        def piece(i):
            cancel_check()
            span = spans[i]; source = source_of(span); out = []
            count = span['source_frame_count']
            key, n = incoming.get(i, ('cut', 0))
            if n:
                # The blend fills this shot's first n frames: the previous shot runs on
                # past its cut and mixes into this one. Nothing moves; if the blend
                # cannot be made, this cut simply stays a hard cut.
                blend = work / f'{i:04}-blend.mp4'
                try:
                    _make_blend(ff, render_span(spans[i - 1]), source_of(spans[i - 1]), render_span(span), source, key, n,
                                width, height, fps, rate, enhance_picture, [e for e in piece_encoders if e is x264 or not gpu_failed], blend,
                                post=overlays(2, starts[i], n), x264=x264, stills=(is_still(spans[i - 1]), is_still(span)))
                except ValueError:
                    n = 0
                else:
                    out.append(blend)
            clip = work / f'{i:04}.mp4'
            still = is_still(span)
            seek, filters = _span_filters(render_span(span), n, count - n, width, height, fps, rate, enhance_picture,
                                          seek_offset=0 if still else _seek_offset(source), still=still)
            extra_frame = closing_hold if i == len(spans) - 1 else 0
            if extra_frame:
                filters += f',trim=end_frame={count - n},tpad=stop_mode=clone:stop=1'
            piece_frames = count - n + extra_frame
            post = overlays(1, starts[i] + n, piece_frames)
            def make_cmd(encoder):
                opening = [] if still else _ss(seek)
                cmd = [ff, '-hide_banner', '-loglevel', 'error', '-y', *opening, '-i', str(source), '-an']
                if post:
                    inputs, graph, label = post
                    cmd += inputs + ['-filter_complex', ';'.join([f'[0:v]{filters}[p]'] + graph), '-map', f'[{label}]']
                else:
                    cmd += ['-vf', filters]
                return cmd + ['-r', rate, '-fps_mode', 'cfr', *encoder, '-frames:v', str(piece_frames), str(clip)]
            encode(make_cmd, piece_frames, clip, span['labels'][0])
            out.append(clip)
            return out
        # Several pieces at once (each on two cores, at low priority so the PC stays
        # usable) instead of one after another; each source is read from its shot.
        from concurrent.futures import ThreadPoolExecutor, as_completed
        phases.step('encode_pieces')
        pieces = [None] * len(spans); done = 0
        progress(0, len(spans))
        workers = _piece_workers(width, height)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(piece, i): i for i in range(len(spans))}
            try:
                for future in as_completed(futures):
                    pieces[futures[future]] = future.result()
                    done += 1
                    progress(done, len(spans))
            except BaseException:
                for f in futures:
                    f.cancel()
                raise
        try:
            import os as _os
            log = destination.parent / 'render_timing.log'
            with open(log, 'a', encoding='utf-8') as fh:
                fh.write(f"{_time.strftime('%Y-%m-%d %H:%M:%S')} {destination.name}: {len(spans)} pieces, "
                         f"{total_frames} frames, {width}x{height}, workers={workers}, cpus={_os.cpu_count()}, "
                         f"enhance_picture={bool(enhance_picture)}, encoders={[e[1] for e in piece_encoders]}, "
                         f"gpu_pieces={timing['gpu']}, cpu_pieces={timing['cpu']}, gpu_fallbacks={timing['fallbacks']}, "
                         f"encode_seconds_summed={timing['seconds']:.0f}, wall_seconds={_time.monotonic()-render_began:.0f}\n")
                for line in timing['reasons']:
                    fh.write('  ' + line + '\n')
        except OSError:
            pass
        clips = [c for group in pieces for c in group]
        listing = work / 'clips.txt'
        listing.write_text(''.join("file '" + str(p).replace("'", "'\\''") + "'\n" for p in clips), encoding='utf-8')
        joined = work / 'joined.mp4'
        # Timestamps are rewritten from the frame index instead of trusted. Clips
        # cut from a 59.94 fps source do not land on exactly `source_frame_count`
        # output frames, so the join inherits a sub-frame deficit at every such cut
        # and every timestamp after it slides. Concatenating pulls frames out of
        # order for the same reason. Rebuilding each PTS as N * numerator over a
        # 30000 timescale is exact for the whole timeline, and `-c copy` means not
        # one pixel is encoded again.
        # A 1/numerator timescale makes one frame exactly `denominator` ticks long,
        # so N frames is N * denominator with no rounding anywhere.
        phases.step('join_copy')
        step('Joining the film', 'Putting the finished pieces together.', 92)
        timescale = fps.numerator
        tick = fps.denominator
        _run([ff, '-hide_banner', '-loglevel', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', str(listing),
              '-c', 'copy', '-bsf:v', f'setts=pts=N*{tick}:dts=N*{tick}',
              '-video_track_timescale', str(timescale), str(joined)])
        count, actual_rate = _video_info(joined)
        if count != total_frames or actual_rate != fps:
            raise ValueError('Concatenated picture has unexpected frame count or frame rate.')
        # The picture is already final, captions, cards and fades included: the sound
        # goes in beside it and not one frame is encoded again.
        result = work / 'result.mp4'
        phases.step('mux_audio')
        step('Adding the sound', 'Mixing in narration, sound bites and music.', 95)
        cmd = [ff, '-hide_banner', '-loglevel', 'error', '-y', '-i', str(joined), '-i', str(audio),
               '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy']
        if difference > 0:
            cmd += ['-af', f'apad=pad_dur={float(difference):.9f}']
        from watermark import metadata_args
        cmd += ['-c:a', 'aac', '-b:a', '192k', '-t', f'{float(video_duration):.9f}', *metadata_args(project),
                '-movflags', '+faststart', str(result)]
        cancel_check()
        _run(cmd)
        count, actual_rate = _video_info(result)
        if count != total_frames or actual_rate != fps:
            raise ValueError('Final MP4 frame count or rate changed; no result was published.')
        # Decode every output frame to check timestamps rather than trusting only
        # container metadata. Audio must be present and cover the picture clock.
        phases.step('verify_output')
        inspect_video(result, total_frames)
        with av.open(str(result)) as finished:
            if not finished.streams.audio:
                raise ValueError('Final MP4 has no audio stream; no result was published.')
            stream = finished.streams.audio[0]
            if stream.duration is None or stream.time_base is None:
                raise ValueError('Final MP4 audio duration could not be verified.')
            encoded_audio_duration = Fraction(stream.duration) * stream.time_base
            if abs(encoded_audio_duration-video_duration) > Fraction(1, 25):
                raise ValueError('Final MP4 audio duration does not match the picture.')
        cancel_check()
        result.replace(destination)
    phases.close(pieces=len(picture['spans']), frames=total_frames, gpu_pieces=timing['gpu'],
                 cpu_pieces=timing['cpu'], gpu_fallbacks=timing['fallbacks'])
    progress(len(picture['spans']), len(picture['spans']))
    return {'frames': total_frames, 'fps': str(fps), 'duration_s': float(video_duration),
            'audio_duration_s': float(audio_duration), 'silent_tail_s': max(0, float(difference)), 'silent_audio_overhang_s': overhang_s, 'decoded_narration_short_s': float(missing_last),
            'closing_hold_frames': closing_hold,
            'captions': len(picture['captions']) if picture.get('burn_captions', True) is not False else 0,
            'captions_written': len(picture['captions']), 'sound_bite_levels': levels['sound_bite_levels'],
            'person_overlays': card_count, 'cutaways_applied': picture.get('cutaways_applied', [])}
