"""v26 stickers: small graphics placed on the finished film clock.

A sticker is a picture (built-in or uploaded by you) shown from `start_s` for
`duration_s` seconds, at `width` (fraction of the picture width) with its centre at
`center_x`/`center_y` (fractions of the picture). Some built-ins have a short built-in
animation: "once" plays its frames one after another and holds the last (a Subscribe
button being clicked); "loop" repeats them (a blinking REC dot, a ringing bell).

Stickers never change footage, narration, sound bites, SRT timing or the film length.
They are drawn over the picture, cards and CTA, and under the watermark and captions.
"""
from __future__ import annotations
from fractions import Fraction
from pathlib import Path
import hashlib
import math
import re
import uuid

BASE = Path(__file__).resolve().parent
LIBRARY_DIR = BASE / 'static' / 'stickers'
UPLOAD_DIR = 'stickers'            # inside the project's assets folder
MAX_STICKERS = 200
MAX_UPLOADS = 60

# name, frames, animation ('static' | 'once' | 'loop'), frame starts as fractions of the
# sticker's time for 'once' or the loop period in seconds, default width, group
CATALOG = [
    {'id': 'subscribe_click', 'name': 'Subscribe click', 'group': 'Subscribe',
     'frames': ['subscribe_a.png', 'subscribe_b.png'], 'animation': 'once', 'at': [0, .5], 'width': .36},
    {'id': 'like_sub_bell', 'name': 'Like · Subscribe · Bell', 'group': 'Subscribe',
     'frames': ['like_sub_bell_a.png', 'like_sub_bell_b.png'], 'animation': 'once', 'at': [0, .5], 'width': .42},
    {'id': 'subscribed', 'name': 'Subscribed', 'group': 'Subscribe', 'frames': ['subscribed.png'], 'animation': 'static', 'width': .38},
    {'id': 'bell', 'name': 'Bell', 'group': 'Subscribe', 'frames': ['bell_l.png', 'bell_r.png'], 'animation': 'loop', 'period': .5, 'width': .12},
    {'id': 'like', 'name': 'Like', 'group': 'Subscribe', 'frames': ['like.png'], 'animation': 'static', 'width': .12},
    {'id': 'share', 'name': 'Share', 'group': 'Subscribe', 'frames': ['share.png'], 'animation': 'static', 'width': .26},
    {'id': 'comment', 'name': 'Comment', 'group': 'Subscribe', 'frames': ['comment.png'], 'animation': 'static', 'width': .3},
    {'id': 'arrow_right', 'name': 'Arrow ↗', 'group': 'Arrows & shapes', 'frames': ['arrow_right.png'], 'animation': 'static', 'width': .22},
    {'id': 'arrow_left', 'name': 'Arrow ↖', 'group': 'Arrows & shapes', 'frames': ['arrow_left.png'], 'animation': 'static', 'width': .22},
    {'id': 'circle', 'name': 'Circle', 'group': 'Arrows & shapes', 'frames': ['circle.png'], 'animation': 'static', 'width': .3},
    {'id': 'rec', 'name': 'REC frame', 'group': 'Arrows & shapes', 'frames': ['rec_on.png', 'rec_off.png'], 'animation': 'loop', 'period': 1.0, 'width': .9},
    {'id': 'waveform', 'name': 'Waveform', 'group': 'Arrows & shapes', 'frames': ['wave_0.png', 'wave_10.png', 'wave_20.png'], 'animation': 'loop', 'period': .45, 'width': .34},
]
BY_ID = {s['id']: s for s in CATALOG}
DEFAULT_DURATION = 4.0
FADE_S = .2
LIMITS = {'width': (.03, 1.0), 'center_x': (0.0, 1.0), 'center_y': (0.0, 1.0), 'start_s': (0.0, 4 * 3600.0),
          'duration_s': (.2, 600.0), 'opacity': (.05, 1.0)}
_ID = re.compile(r'^st_[0-9a-f]{12}$')
_UPLOAD = re.compile(r'^up_[0-9a-f]{12}$')


def uploads(project):
    return [u for u in (project.get('sticker_uploads') or []) if _UPLOAD.match(str(u.get('id', '')))]


def kind_of(project, key):
    """The catalogue entry (built-in or uploaded) for a sticker key, or None."""
    if key in BY_ID:
        return BY_ID[key]
    if isinstance(key, str) and key.startswith('up_'):
        for u in uploads(project):
            if u['id'] == key:
                return {'id': key, 'name': u.get('name') or 'My sticker', 'group': 'Yours', 'frames': [u['file']],
                        'animation': 'static', 'width': .25, 'upload': True}
    return None


def frame_paths(project, root, kind):
    if kind.get('upload'):
        folder = (Path(root) / 'assets' / UPLOAD_DIR).resolve()
        out = [(folder / f).resolve() for f in kind['frames']]
        if not all(p.is_relative_to(folder) for p in out):
            return []
    else:
        out = [LIBRARY_DIR / f for f in kind['frames']]
    return out if all(p.is_file() for p in out) else []


def library(project, pid):
    rows = []
    for s in CATALOG:
        rows.append({'id': s['id'], 'name': s['name'], 'group': s['group'], 'animation': s['animation'],
                     'url': f"/static/stickers/{s['frames'][0]}", 'frames': [f"/static/stickers/{f}" for f in s['frames']],
                     'at': s.get('at'), 'period': s.get('period'), 'width': s['width']})
    for u in uploads(project):
        url = f"/api/projects/{pid}/stickers/file/{u['file']}"
        rows.append({'id': u['id'], 'name': u.get('name') or 'My sticker', 'group': 'Yours', 'animation': 'static',
                     'url': url, 'frames': [url], 'at': None, 'period': None, 'width': .25})
    return rows


def _num(key, value):
    if isinstance(value, bool):
        raise ValueError(f'{key} must be a number.')
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise ValueError(f'{key} must be a number.')
    if not math.isfinite(v):
        raise ValueError(f'{key} must be a number.')
    lo, hi = LIMITS[key]
    return round(min(hi, max(lo, v)), 4)


def new_sticker(project, key, start_s, film_s=None):
    kind = kind_of(project, key)
    if not kind:
        raise ValueError('Unknown sticker.')
    if len(project.get('stickers') or []) >= MAX_STICKERS:
        raise ValueError(f'A film can hold up to {MAX_STICKERS} stickers.')
    start = _num('start_s', start_s or 0)
    duration = DEFAULT_DURATION
    if film_s and film_s > 0:
        start = min(start, max(0.0, film_s - .2))
        duration = max(.2, min(DEFAULT_DURATION, film_s - start))
    return {'id': 'st_' + uuid.uuid4().hex[:12], 'sticker': key, 'start_s': round(start, 3), 'duration_s': round(duration, 3),
            'width': kind['width'], 'center_x': .5, 'center_y': .5, 'opacity': 1.0}


def apply_patch(sticker, patch):
    if not isinstance(patch, dict) or not patch:
        raise ValueError('Nothing to change.')
    out = dict(sticker)
    for k, v in patch.items():
        if k not in LIMITS:
            raise ValueError('Unknown sticker setting: ' + str(k))
        out[k] = _num(k, v)
    return out


def active(project, root):
    rows = []
    for s in project.get('stickers') or []:
        if not _ID.match(str(s.get('id', ''))):
            continue
        kind = kind_of(project, s.get('sticker'))
        if not kind or not frame_paths(project, root, kind):
            continue
        rows.append((s, kind))
    return rows


def frame_windows(kind, a, b):
    """[(frame_index, enable_expression)] on the film clock for a sticker shown a..b."""
    n = len(kind['frames'])
    on = f'gte(t,{a:.6f})*lt(t,{b:.6f})'
    if n == 1 or kind['animation'] == 'static':
        return [(0, on)]
    if kind['animation'] == 'once':
        at = list(kind.get('at') or [k / n for k in range(n)]) + [1.0]
        out = []
        for i in range(n):
            s = a + (b - a) * at[i]; e = a + (b - a) * at[i + 1] if i + 1 < n else b
            out.append((i, f'gte(t,{s:.6f})*lt(t,{e:.6f})'))
        return out
    period = float(kind.get('period') or 1.0); step = period / n
    return [(i, f"{on}*gte(mod(t-{a:.6f},{period:.6f}),{i * step:.6f})*lt(mod(t-{a:.6f},{period:.6f}),{(i + 1) * step:.6f})")
            for i in range(n)]


def _scaled(path, width_px, work, cache):
    from PIL import Image
    key = (str(path), width_px)
    if key in cache:
        return cache[key]
    with Image.open(path) as im:
        im = im.convert('RGBA')
        w = max(2, int(width_px) // 2 * 2); h = max(2, round(im.height * w / im.width) // 2 * 2)
        im = im.resize((w, h), Image.LANCZOS)
        digest = hashlib.sha256(f'{path}|{path.stat().st_mtime_ns}|{w}x{h}'.encode()).hexdigest()[:16]
        out = Path(work) / f'sticker-{digest}.png'
        if not out.exists():
            im.save(out)
    cache[key] = (out, w, h)
    return cache[key]


def placement(sticker, width, height, w, h):
    x = min(max(0, round(sticker['center_x'] * width - w / 2)), max(0, width - w))
    y = min(max(0, round(sticker['center_y'] * height - h / 2)), max(0, height - h))
    return x, y


def render_filters(project, root, width, height, rate, work, first_input, between=None, cache=None, input_label='base'):
    """FFmpeg inputs and steps drawing the stickers due in frames between[0]..between[1]
    over [input_label] -> [stk]. Returns (inputs, steps, count)."""
    store = cache if cache is not None else {}
    if 'rows' not in store:
        store['rows'] = active(project, root)
        store['png'] = {}
    rows = store['rows']
    if not rows:
        return [], [], 0
    fps = Fraction(str(rate)); f0, f1 = between or (0, 4 * 3600 * fps)
    from still_layers import hold
    inputs, steps, label, n = [], [], input_label, 0
    for s, kind in rows:
        a = float(s['start_s']); b = a + float(s['duration_s'])
        if not (a * fps < f1 and b * fps > f0):
            continue
        paths = frame_paths(project, root, kind)
        width_px = max(8, round(float(s['width']) * width))
        fade = min(FADE_S, (b - a) / 4)
        alpha = float(s.get('opacity', 1.0))
        for i, enable in frame_windows(kind, a, b):
            png, w, h = _scaled(paths[i], width_px, work, store['png'])
            if h > height:  # never taller than the picture
                png, w, h = _scaled(paths[i], max(8, round(width_px * height / h)), work, store['png'])
            x, y = placement(s, width, height, w, h)
            index = first_input + inputs.count('-i')
            inputs += ['-i', str(png)]
            mix = f',format=rgba,colorchannelmixer=aa={alpha:.3f}' if alpha < .999 else ''
            fades = (f',fade=t=in:st={a:.6f}:d={fade:.6f}:alpha=1,fade=t=out:st={b - fade:.6f}:d={fade:.6f}:alpha=1') if fade > 0 else ''
            steps.append(f'[{index}:v]{hold(rate, int(f1 - f0) + 1, int(f0))}{mix},format=yuva420p{fades}[stki{n}]')
            out = f'stk{n}'
            steps.append(f"[{label}][stki{n}]overlay=x={x}:y={y}:eof_action=pass:format=yuv420:enable='{enable}'[{out}]")
            label = out; n += 1
    if not steps:
        return [], [], 0
    steps[-1] = steps[-1][:steps[-1].rindex('[')] + '[stk]'
    return inputs, steps, n
