"""Motion graphics rendering: Pillow → per-frame PNGs → FFmpeg overlay layer.

Renders each approved motion graphics sequence as an alpha-preserving video
cached by content signature. The final renderer composites the cached videos
over the picture using FFmpeg's overlay filter, exactly like person cards,
stickers, CTA cards and watermarks. Original footage, narration and SRT are
never touched.

Preview rendering uses a low-resolution path for the editor UI. Final render
uses the export resolution; the preview asset is not reused for the final MP4.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import time
from fractions import Fraction
from pathlib import Path

import imageio_ffmpeg

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    Image = ImageDraw = ImageFont = None

from motion_templates import (
    Sequence, Element, build_sequence, resolve_animation,
)

BASE = Path(__file__).resolve().parent
FONT_DIR = BASE / 'static' / 'fonts'
CACHE_DIR_NAME = 'motion-graphics-v1'

# Colour tokens -> RGBA tuples.
_COLOUR_TOKENS = {
    'text': (241, 241, 239, 255),
    'muted': (192, 195, 201, 255),
    'accent': (220, 101, 108, 255),
    'divider': (220, 101, 108, 255),
    'bg': (16, 17, 20, 255),
}


def _colour(value, design=None):
    """Resolve a colour token or hex string to RGBA."""
    if value in _COLOUR_TOKENS:
        return _COLOUR_TOKENS[value]
    if isinstance(value, str) and value.startswith('#') and len(value) in (7, 9):
        hexs = value.lstrip('#')
        if len(hexs) == 6:
            r, g, b = int(hexs[0:2], 16), int(hexs[2:4], 16), int(hexs[4:6], 16)
            return (r, g, b, 255)
        if len(hexs) == 8:
            r, g, b, a = (int(hexs[i:i+2], 16) for i in (0, 2, 4, 6))
            return (r, g, b, a)
    # Fall back to design overrides.
    if design:
        if value == 'accent':
            return _colour(design.get('accent_color', '#DC656C'))
        if value == 'text':
            return _colour(design.get('text_color', '#F1F1EF'))
        if value == 'muted':
            return _colour(design.get('muted_color', '#C0C3C9'))
    return (241, 241, 239, 255)


def _load_font(kind, size_px):
    """Load a Pillow font from the bundled library; fall back to default."""
    if ImageFont is None:
        return None
    candidates = {
        'display': ['Inter-Black.ttf', 'Montserrat-ExtraBold.ttf',
                    'Poppins-Bold.ttf', 'DejaVuSans-Bold.ttf'],
        'body':    ['Inter-SemiBold.ttf', 'Poppins-Medium.ttf',
                    'DejaVuSans.ttf'],
    }
    for name in candidates.get(kind, candidates['body']):
        path = FONT_DIR / name
        if path.is_file():
            try:
                return ImageFont.truetype(str(path), size_px)
            except (OSError, IOError):
                continue
    try:
        return ImageFont.truetype('DejaVuSans.ttf', size_px)
    except (OSError, IOError):
        return ImageFont.load_default()


# -------------------------------------------------------------- frame rendering

def _wrap_text(text, font, max_width, draw):
    """Word-wrap text to fit within max_width pixels."""
    if not text:
        return []
    words = text.split()
    lines = []; cur = ''
    for w in words:
        test = (cur + ' ' + w).strip()
        if not cur:
            cur = w; continue
        bbox = draw.textbbox((0, 0), test, font=font)
        if (bbox[2] - bbox[0]) <= max_width:
            cur = test
        else:
            lines.append(cur); cur = w
    if cur:
        lines.append(cur)
    return lines


def render_frame(sequence: Sequence, t: float, width: int, height: int, design: dict) -> 'Image.Image':
    """Render a single RGBA frame of the sequence at time t seconds."""
    if Image is None:
        raise RuntimeError('Pillow is required for motion graphics rendering.')
    img = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    base_size = min(width, height)

    # Subtle background gradient plate (the motion graphic's own backdrop, not
    # the underlying footage — footage remains the primary visual story).
    bg_kind = (design or {}).get('background', 'charcoal')
    _draw_backdrop(draw, width, height, bg_kind)

    states = sequence.states_at(t)
    for element, state in states:
        if state['opacity'] <= 0.001:
            continue
        # Resolve geometry to pixels.
        x = int(element.geom['x'] * width)
        y = int(element.geom['y'] * height)
        w = int(element.geom['w'] * width)
        h = int(element.geom['h'] * height)
        # Apply animation.
        opacity = state['opacity']
        clip_r = state.get('clip_right', 0.0)
        tx = int(state.get('translate_x', 0.0) * w)
        ty = int(state.get('translate_y', 0.0) * h)
        scale = state.get('scale', 1.0)
        # Clip region: if clip_right > 0, reduce effective width.
        eff_w = max(0, int(w * (1 - clip_r)))
        if eff_w <= 0 or h <= 0:
            continue
        # Apply translation and scale by adjusting origin.
        draw_x = x + tx
        draw_y = y + ty
        # Resolve style.
        style = element.style or {}
        font_kind = style.get('font_kind', 'body')
        size_ratio = style.get('size_ratio', 0.028)
        font_size = max(10, int(base_size * size_ratio * scale))
        font = _load_font(font_kind, font_size)
        color_tok = style.get('color', 'text')
        colour = _colour(color_tok, design)
        colour_with_alpha = (*colour[:3], int(colour[3] * opacity))
        max_lines = style.get('max_lines', 1)
        is_upper = style.get('uppercase', False)
        italic = style.get('italic', False)
        letter_sp = style.get('letter_spacing_em', 0.0)
        # Render based on element kind.
        if element.kind == 'divider':
            _draw_divider(draw, x, y, w, h, eff_w, colour_with_alpha, state)
        elif element.kind == 'marker':
            _draw_marker(draw, x, y, w, h, colour_with_alpha, opacity, style)
        elif element.kind == 'timeline_line':
            _draw_timeline_line(draw, x, y, w, h, t, sequence.duration_s,
                                element.t_in, colour_with_alpha, opacity)
        else:
            text = element.text
            if is_upper:
                text = text.upper()
            lines = _wrap_text(text, font, eff_w, draw)
            lines = lines[:max_lines] if max_lines else lines
            # Accent bar to the left of body/charge elements.
            if style.get('accent_bar'):
                bar_colour = _colour(style.get('accent_color', 'accent'), design)
                bar_colour = (*bar_colour[:3], int(bar_colour[3] * opacity))
                bar_w = max(3, height // 220)
                draw.rectangle((draw_x, draw_y, draw_x + bar_w, draw_y + h), fill=bar_colour)
                draw_x += bar_w + max(8, width // 140)
                eff_w -= bar_w + max(8, width // 140)
            # Bullet marker.
            if style.get('bullet') and lines:
                bullet_y = draw_y + font_size // 2
                r = max(3, font_size // 5)
                bc = _colour('accent', design)
                bc = (*bc[:3], int(bc[3] * opacity))
                draw.ellipse((draw_x, bullet_y - r, draw_x + 2 * r, bullet_y + r), fill=bc)
                draw_x += 2 * r + max(8, width // 140)
                eff_w -= 2 * r + max(8, width // 140)
            # Draw text lines.
            line_y = draw_y
            line_step = int(font_size * 1.25)
            for line in lines:
                if letter_sp > 0:
                    _draw_spaced_text(draw, line, draw_x, line_y, font,
                                      colour_with_alpha, int(font_size * letter_sp))
                else:
                    draw.text((draw_x, line_y), line, font=font, fill=colour_with_alpha)
                line_y += line_step
    return img


def _draw_backdrop(draw, width, height, kind):
    """Draw the subtle background plate for the motion graphic."""
    if kind == 'charcoal':
        c1, c2 = (16, 17, 20, 235), (10, 12, 16, 240)
    elif kind == 'midnight':
        c1, c2 = (16, 29, 49, 235), (7, 16, 30, 240)
    elif kind == 'warm':
        c1, c2 = (45, 29, 25, 235), (20, 16, 15, 240)
    elif kind == 'neutral':
        c1, c2 = (41, 41, 43, 230), (20, 20, 22, 235)
    else:
        c1, c2 = (16, 17, 20, 235), (10, 12, 16, 240)
    # Vertical gradient: sample linearly from c1 (top) to c2 (bottom).
    for row in range(height):
        p = row / max(1, height - 1)
        r = int(c1[0] + (c2[0] - c1[0]) * p)
        g = int(c1[1] + (c2[1] - c1[1]) * p)
        b = int(c1[2] + (c2[2] - c1[2]) * p)
        a = int(c1[3] + (c2[3] - c1[3]) * p)
        draw.line([(0, row), (width - 1, row)], fill=(r, g, b, a))
    # Accent radial glow top-left.
    accent = _colour('accent')
    glow_r = max(width, height) // 2
    cx, cy = width // 6, height // 6
    for dy in range(-glow_r, glow_r + 1, max(2, glow_r // 20)):
        for dx in range(-glow_r, glow_r + 1, max(2, glow_r // 20)):
            d = math.sqrt(dx * dx + dy * dy)
            if d > glow_r:
                continue
            alpha = int(35 * (1 - d / glow_r) ** 2)
            if alpha <= 0:
                continue
            px, py = cx + dx, cy + dy
            if 0 <= px < width and 0 <= py < height:
                try:
                    draw.point((px, py), fill=(*accent[:3], alpha))
                except Exception:
                    pass


def _draw_divider(draw, x, y, w, h, eff_w, colour, state):
    """Horizontal accent divider drawn from its centre outward."""
    cx = x + w // 2
    cy = y + h // 2
    half = eff_w // 2
    draw.rectangle((cx - half, cy - h // 2, cx + half, cy + h // 2), fill=colour)


def _draw_marker(draw, x, y, w, h, colour, opacity, style):
    """Circle marker on the timeline."""
    shape = style.get('shape', 'circle')
    if shape == 'circle':
        draw.ellipse((x, y, x + w, y + h), fill=colour)
        # Inner bright dot.
        inner = (min(255, colour[0] + 40), min(255, colour[1] + 40),
                 min(255, colour[2] + 40), colour[3])
        ix = x + w // 4; iy = y + h // 4
        draw.ellipse((ix, iy, ix + w // 2, iy + h // 2), fill=inner)


def _draw_timeline_line(draw, x, y, w, h, t, total, t_in, colour, opacity):
    """Vertical timeline line that grows from top to bottom as time advances."""
    progress = max(0.0, min(1.0, (t - t_in) / max(0.001, total - t_in)))
    drawn_h = int(h * progress)
    if drawn_h <= 0:
        return
    draw.rectangle((x, y, x + w, y + drawn_h), fill=colour)


def _draw_spaced_text(draw, text, x, y, font, colour, spacing_px):
    cx = x
    for ch in text:
        draw.text((cx, y), ch, font=font, fill=colour)
        try:
            advance = draw.textlength(ch, font=font)
        except AttributeError:
            bbox = draw.textbbox((0, 0), ch, font=font)
            advance = bbox[2] - bbox[0]
        cx += int(advance) + spacing_px


# ------------------------------------------------------------------- encoding

def render_sequence_frames(sequence: Sequence, design: dict, fps: Fraction,
                           width: int, height: int, out_dir: Path,
                           progress=None) -> int:
    """Render every frame of the sequence to out_dir as numbered PNGs."""
    out_dir.mkdir(parents=True, exist_ok=True)
    total_frames = max(1, int(round(float(sequence.duration_s) * float(fps))))
    for i in range(total_frames):
        t = i / float(fps)
        img = render_frame(sequence, t, width, height, design)
        img.save(out_dir / f'{i:06d}.png', format='PNG')
        if progress:
            progress(i + 1, total_frames)
    return total_frames


def encode_sequence_video(frames_dir: Path, fps: Fraction, out_path: Path,
                          total_frames: int) -> Path:
    """Encode a PNG sequence into an alpha-preserving MP4 (yuva420p via ffv1)."""
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [
        ff, '-hide_banner', '-loglevel', 'error', '-y',
        '-framerate', str(fps),
        '-i', str(frames_dir / '%06d.png'),
        '-c:v', 'ffv1', '-pix_fmt', 'yuva420p',
        '-frames:v', str(total_frames),
        str(out_path),
    ]
    result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                            timeout=max(120, total_frames // 10))
    if result.returncode != 0:
        err = result.stderr.decode(errors='replace')[-400:]
        raise ValueError(f'Motion graphics encode failed: {err}')
    return out_path


# --------------------------------------------------------------------- cache

def sequence_signature(sequence: Sequence, design: dict, fps: Fraction,
                       width: int, height: int) -> str:
    """Stable hash identifying one rendered sequence asset."""
    payload = {
        'template': sequence.template_id,
        'duration_s': sequence.duration_s,
        'elements': [
            {
                'kind': el.kind, 'geom': el.geom, 'text': el.text,
                'lines': el.lines, 'style': el.style,
                't_in': el.t_in, 't_out': el.t_out,
                'anim_in': el.anim_in, 'anim_out': el.anim_out,
                'anim_in_dur': el.anim_in_dur, 'anim_out_dur': el.anim_out_dur,
            } for el in sequence.elements
        ],
        'design': design,
        'fps': str(fps), 'width': width, 'height': height,
        'version': 1,
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode('utf-8')
    return hashlib.sha256(blob).hexdigest()[:20]


def cache_path(root, signature: str) -> Path:
    return Path(root) / '.cache' / CACHE_DIR_NAME / f'{signature}.mkv'


def build_asset(root, sequence: Sequence, design: dict, fps: Fraction,
                width: int, height: int, force: bool = False,
                progress=None) -> Path:
    """Render (or reuse cached) alpha video for one sequence. Returns its path."""
    sig = sequence_signature(sequence, design, fps, width, height)
    target = cache_path(root, sig)
    if not force and target.is_file() and target.stat().st_size > 0:
        if progress:
            progress(1, 1)
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_dir = Path(tempfile.mkdtemp(prefix='mg-frames-', dir=target.parent))
    try:
        total = render_sequence_frames(sequence, design, fps, width, height, tmp_dir,
                                       progress=progress)
        encode_sequence_video(tmp_dir, fps, target, total)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    return target


# ---------------------------------------------------- final-render integration

def active_sequences(project):
    """Return the approved, enabled sequences for this project."""
    if Image is None:
        return []
    mg = project.get('motion_graphics') or {}
    if not mg.get('enabled'):
        return []
    return [s for s in (mg.get('sequences') or []) if isinstance(s, dict)]


def render_filters(project, root, width, height, rate, work, first_input,
                   between=None, cache=None, input_label='base'):
    """FFmpeg inputs and steps drawing the active motion graphics over
    [input_label] -> [mg]. Returns (inputs, steps, count).

    Follows the same contract as person_overlays.render_filters, stickers, etc.
    Each approved sequence is cached as an alpha-preserving video; the final
    render reuses the cached asset unchanged.
    """
    store = cache if cache is not None else {}
    seqs = active_sequences(project)
    if not seqs:
        return [], [], 0
    fps = Fraction(str(rate)); f0, f1 = between or (0, 4 * 3600 * fps)
    mg = project.get('motion_graphics') or {}
    design = mg.get('design') or {}
    inputs, steps, label, n = [], [], input_label, 0
    assets = store.setdefault('assets', {})
    for seq_spec in seqs:
        try:
            template = seq_spec['template']
            content = seq_spec['content']
            duration = float(seq_spec['end_s']) - float(seq_spec['start_s'])
            start_s = float(seq_spec['start_s'])
            end_s = float(seq_spec['end_s'])
        except (KeyError, TypeError, ValueError):
            continue
        if not (start_s * fps < f1 and end_s * fps > f0):
            continue
        sequence = build_sequence(template, content, duration)
        # Choose resolution: match the final render.
        sig_key = sequence_signature(sequence, design, fps, width, height)
        if sig_key not in assets:
            # Build the asset into the project cache (not the render temp dir).
            target = cache_path(root, sig_key)
            if not target.is_file():
                try:
                    build_asset(root, sequence, design, fps, width, height)
                except Exception:
                    continue
            assets[sig_key] = target
        video = assets[sig_key]
        if not video.is_file():
            continue
        index = first_input + inputs.count('-i')
        inputs += ['-i', str(video)]
        fade = min(0.4, duration / 6)
        fade_out = f',fade=t=out:st={max(0, duration - fade):.6f}:d={fade:.6f}:alpha=1' if fade > 0 else ''
        fade_in = f',fade=t=in:st=0:d={fade:.6f}:alpha=1' if fade > 0 else ''
        # Offset the video stream to the sequence's start time on the film clock.
        # The video's own PTS starts at 0; we shift it to start_s on the film clock.
        pts_shift = f'setpts=PTS-STARTPTS+{start_s}/TB'
        steps.append(f'[{index}:v]{pts_shift}{fade_in}{fade_out},format=yuva420p[mgv{n}]')
        # Overlay only where the sequence is live.
        enable = f'between(t,{start_s:.6f},{end_s:.6f})'
        out = f'mg{n}'
        steps.append(f"[{label}][mgv{n}]overlay=eof_action=pass:format=yuv420:enable='{enable}'[{out}]")
        label = out; n += 1
    if not steps:
        return [], [], 0
    steps[-1] = steps[-1][:steps[-1].rindex('[')] + '[mg]'
    return inputs, steps, n


# -------------------------------------------------------------- preview frames

def preview_frames(sequence: Sequence, design: dict, fps: float,
                   width: int, height: int, max_frames: int = 300):
    """Yield PNG bytes for a lightweight editor preview (no backdrop audio)."""
    total = min(max_frames, max(1, int(round(float(sequence.duration_s) * float(fps)))))
    for i in range(total):
        t = i / float(fps)
        img = render_frame(sequence, t, width, height, design)
        import io
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        yield buf.getvalue()


def preview_video(sequence: Sequence, design: dict, fps: Fraction,
                  width: int, height: int, out_path: Path) -> Path:
    """Render a standalone MP4 preview of one sequence (no alpha, dark plate)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix='mg-preview-', dir=out_path.parent))
    try:
        total = render_sequence_frames(sequence, design, fps, width, height, tmp)
        # Flatten alpha onto a near-black plate for preview.
        flat_dir = tmp / 'flat'
        flat_dir.mkdir()
        for png in sorted(tmp.glob('*.png')):
            if png.parent == flat_dir:
                continue
            img = Image.open(png).convert('RGBA')
            flat = Image.new('RGB', img.size, (16, 17, 20))
            flat.paste(img, mask=img.split()[3])
            flat.save(flat_dir / png.name)
        ff = imageio_ffmpeg.get_ffmpeg_exe()
        cmd = [
            ff, '-hide_banner', '-loglevel', 'error', '-y',
            '-framerate', str(fps), '-i', str(flat_dir / '%06d.png'),
            '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '24',
            '-pix_fmt', 'yuv420p', '-frames:v', str(total),
            '-movflags', '+faststart', str(out_path),
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                       timeout=max(120, total // 10), check=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return out_path
