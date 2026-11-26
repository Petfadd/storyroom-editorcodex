"""Channel watermark: the channel's own logo on every frame, end to end.

Two layers, each switched on separately:

* EDGE logo  - bold, always fully opaque, in a corner (or top/bottom centre). Size
               adjustable. This is the visible brand mark.
* MIDDLE logo - the same logo, centred, with adjustable size and opacity (default 12%),
               so a cropped or re-uploaded copy still carries the mark.

Both are drawn over everything in the picture (footage, photos, cutaways, the CTA
card) and under captions/subtitles, from the first frame to the last. They never change
timing, audio or the SRT. Geometry is stored as fractions of the output picture so the
editor preview and the exported MP4 place them identically.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps

FILE = 'watermark.png'
POSITIONS = ('top_left', 'top_right', 'bottom_left', 'bottom_right', 'top_center', 'bottom_center')
DEFAULTS = {
    'edge_enabled': True,
    'edge_position': 'top_right',
    'edge_size': 0.14,        # logo width / picture width
    'edge_margin': 0.025,     # gap from the picture edge, fraction of picture width
    'middle_enabled': False,
    'middle_size': 0.45,
    'middle_opacity': 0.12,
    'middle_y': 0.50,        # vertical position within the space the logo can travel
    'owner': '',              # written into the MP4's information (copyright / artist)
}
LIMITS = {'edge_size': (0.04, 0.40), 'edge_margin': (0.0, 0.10), 'middle_size': (0.10, 0.95),
          'middle_opacity': (0.0, 1.0), 'middle_y': (0.0, 1.0)}


def settings(project):
    raw = project.get('watermark') or {}
    out = dict(DEFAULTS)
    for key in DEFAULTS:
        if key in raw:
            out[key] = raw[key]
    return out


def validate_patch(patch):
    if not isinstance(patch, dict):
        raise ValueError('Watermark settings must be an object.')
    values = {}
    for key, val in patch.items():
        if key not in DEFAULTS:
            raise ValueError('Unknown watermark setting: ' + str(key))
        if key in ('edge_enabled', 'middle_enabled'):
            if not isinstance(val, bool):
                raise ValueError(f'{key} must be true or false.')
        elif key == 'edge_position':
            if val not in POSITIONS:
                raise ValueError('Edge position must be one of: ' + ', '.join(POSITIONS) + '.')
        elif key == 'owner':
            val = ' '.join(str(val or '').split())[:120]
        else:
            if isinstance(val, bool):
                raise ValueError(f'{key} must be a number.')
            try:
                val = float(val)
            except (TypeError, ValueError):
                raise ValueError(f'{key} must be a number.') from None
            lo, hi = LIMITS[key]
            if not lo <= val <= hi:
                raise ValueError(f'{key} must be between {lo} and {hi}.')
        values[key] = val
    return values


def path_for(project, root):
    if (project.get('watermark_asset') or {}).get('file') != FILE:
        return None
    p = (Path(root) / 'assets' / FILE).resolve()
    base = (Path(root) / 'assets').resolve()
    return p if p.is_relative_to(base) and p.is_file() else None


def active(project, root):
    conf = settings(project)
    return bool(path_for(project, root)) and (conf['edge_enabled'] or conf['middle_enabled'])


def layout(conf, logo_w, logo_h, width, height):
    """Pixel boxes for the enabled layers: {'edge': (x, y, w, h), 'middle': (...)}."""
    ratio = logo_w / logo_h if logo_w and logo_h else 1.0
    boxes = {}
    if conf['edge_enabled']:
        w = max(8, round(width * float(conf['edge_size'])))
        h = max(4, round(w / ratio))
        if h > height * 0.45:
            h = round(height * 0.45); w = max(8, round(h * ratio))
        m = round(width * float(conf['edge_margin']))
        pos = conf['edge_position']
        x = m if pos.endswith('left') else width - w - m if pos.endswith('right') else (width - w) // 2
        y = m if pos.startswith('top') else height - h - m
        boxes['edge'] = (max(0, x), max(0, y), w, h)
    if conf['middle_enabled']:
        w = max(8, round(width * float(conf['middle_size'])))
        h = max(4, round(w / ratio))
        if h > height * 0.95:
            h = round(height * 0.95); w = max(8, round(h * ratio))
        boxes['middle'] = ((width - w) // 2, round((height - h) * conf.get('middle_y', .5)), w, h)
    return boxes


def prepared(project, root, width, height, work):
    """Scaled PNG layers for the output size: [(file, x, y)], opacity baked into alpha."""
    source = path_for(project, root)
    if not source:
        return []
    conf = settings(project)
    with Image.open(source) as f:
        im = ImageOps.exif_transpose(f).convert('RGBA')
    boxes = layout(conf, im.width, im.height, width, height)
    out = []
    for name in ('middle', 'edge'):            # middle first, so the edge logo sits on top
        if name not in boxes:
            continue
        x, y, w, h = boxes[name]
        layer = im.resize((w, h), Image.Resampling.LANCZOS)
        if name == 'middle':
            opacity = float(conf['middle_opacity'])
            layer.putalpha(layer.getchannel('A').point(lambda a: round(a * opacity)))
        if name == 'middle' and float(conf['middle_opacity']) <= 0:
            continue
        dest = Path(work) / f'watermark-{name}-{width}x{height}.png'
        layer.save(dest)
        out.append((dest, x, y))
    return out


def render_filters(project, root, width, height, rate, work, first_input, frames, start_frame, input_label, cache=None):
    """FFmpeg inputs and steps drawing the watermark over [input_label] -> [wm].

    `frames` is the length of this piece, `start_frame` where it sits on the film clock
    (the incoming picture is already on that clock). Returns (inputs, steps) or ([], []).
    """
    store = cache if cache is not None else {}
    if 'layers' not in store:
        store['layers'] = prepared(project, root, width, height, work) if active(project, root) else []
    layers = store['layers']
    if not layers:
        return [], []
    # v19: the logo is decoded once and held for the piece (it used to be decoded
    # again for every frame of the film), a few frames longer than the piece.
    from still_layers import hold
    inputs, steps, label = [], [], input_label
    for i, (file, x, y) in enumerate(layers):
        index = first_input + i
        inputs += ['-i', str(file)]
        steps.append(f'[{index}:v]{hold(rate, int(frames) + 15, start_frame)},format=yuva420p[wmi{i}]')
        out = f'wm{i}'
        steps.append(f'[{label}][wmi{i}]overlay=x={x}:y={y}:eof_action=repeat:format=yuv420[{out}]')
        label = out
    steps[-1] = steps[-1][:steps[-1].rindex('[')] + '[wm]'
    return inputs, steps


def metadata_args(project):
    """MP4 information tags naming the owner (invisible; supports the visible marks)."""
    owner = settings(project).get('owner') or ''
    if not owner:
        return []
    import datetime
    year = datetime.date.today().year
    return ['-metadata', f'copyright=© {year} {owner}. All rights reserved.', '-metadata', f'artist={owner}',
            '-metadata', f'comment=Original upload by {owner}. Re-uploading without permission is not allowed.']
