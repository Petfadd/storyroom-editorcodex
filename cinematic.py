"""Per-slot camera motion: animated zoom and pan over a picture slot.

One definition serves every place a slot is drawn:

* the final documentary render and the review preview, as an ffmpeg `perspective`
  filter (`ffmpeg_filter`), which resamples each frame at sub-pixel precision, so a
  slow zoom does not step or jitter, and costs about 11% of encode speed in testing;
* the editor's monitor, which repeats exactly the same arithmetic in JavaScript
  (`static/cinematic.js`, kept in step with `window()` below by a test).

A slot's camera is stored on the scene as `scene['camera']`:

    {'zoom_start': 100..200, 'zoom_end': 100..200,          # percent of the fitted frame
     'x_start': 0..1, 'y_start': 0..1, 'x_end': 0..1, 'y_end': 0..1,   # focal point
     'easing': 'linear'|'ease-in'|'ease-out'|'ease-in-out',
     'origin': 'manual'|'auto'|'ai', 'locked': bool}

The focal point is where the camera looks, as a fraction of the frame (0.5, 0.5 is the
centre). It is clamped so the picture never shows past its own edge: at 100% zoom the
whole frame is always shown whatever the focal point says. When a slot has a camera it
replaces that slot's static `picture_scale`; without one the slot renders exactly as
before. Motion never changes a slot's frames, timing, narration or sound.
"""
from __future__ import annotations

import math

EASINGS = ('linear', 'ease-in', 'ease-out', 'ease-in-out')
ZOOM_MIN, ZOOM_MAX = 100, 200
FIELDS = ('zoom_start', 'zoom_end', 'x_start', 'y_start', 'x_end', 'y_end')

# Direction x intensity presets for the inspector and the Phase 2 director. Values are
# what an editor would reach for on documentary footage: subtle is barely felt.
# Pans travel a small fraction of the frame: each one needs that much extra zoom to have
# room to move (subtle 107%, medium 112%, strong 120%), and on 1080p footage every
# extra percent of zoom is a little resolution given up.
INTENSITY = {'subtle': (5, 0.03), 'medium': (10, 0.05), 'strong': (18, 0.08)}   # zoom points, pan distance


def preset(direction: str, intensity: str = 'medium', focus=(0.5, 0.5), base_zoom: int = 100) -> dict:
    """A camera for one of the named moves, starting from `base_zoom` percent."""
    dz, dp = INTENSITY.get(intensity, INTENSITY['medium'])
    fx, fy = focus
    base = max(ZOOM_MIN, min(ZOOM_MAX, int(base_zoom)))
    cam = {'zoom_start': base, 'zoom_end': base, 'x_start': fx, 'y_start': fy, 'x_end': fx, 'y_end': fy,
           'easing': 'ease-in-out'}
    if direction == 'portrait_reveal':
        # Reference-style portrait move: start tight, show the whole portrait at
        # mid-point, then push closer again. Every phase is a continuous curve,
        # never a separate still/restarted zoom on a subtitle boundary.
        cam['zoom_start'] = min(ZOOM_MAX, max(base + 2 * dz, 120))
        cam['zoom_mid'] = max(base, 102)
        cam['zoom_end'] = min(ZOOM_MAX, max(base + dz + 3, 113))
        cam['x_start'] = fx - dp * 0.35
        cam['x_end'] = fx + dp * 0.55
        cam['y_start'] = fy + dp * 0.15
        cam['y_end'] = fy - dp * 0.25
    elif direction == 'zoom_in':
        cam['zoom_end'] = min(ZOOM_MAX, base + dz)
    elif direction == 'zoom_out':
        cam['zoom_start'] = min(ZOOM_MAX, base + dz)
    elif direction in ('pan_left', 'pan_right', 'pan_up', 'pan_down'):
        # A pan needs room to move: enlarge enough that the move stays inside the frame.
        need = 100 / (1 - 2 * dp) if dp < 0.45 else ZOOM_MAX
        z = max(base, min(ZOOM_MAX, math.ceil(need)))
        cam['zoom_start'] = cam['zoom_end'] = z
        sign = {'pan_left': (1, 0), 'pan_right': (-1, 0), 'pan_up': (0, 1), 'pan_down': (0, -1)}[direction]
        # "Pan left" moves the camera left: the view starts right of the focus and ends left.
        cam['x_start'], cam['x_end'] = fx + sign[0] * dp, fx - sign[0] * dp
        cam['y_start'], cam['y_end'] = fy + sign[1] * dp, fy - sign[1] * dp
        cam['easing'] = 'linear'
    elif direction in ('push_left', 'push_right', 'push_up', 'push_down',
                       'reveal_left', 'reveal_right', 'drift_up_right', 'drift_down_left'):
        # Composite dolly/drift: one continuous curve, not a canned zoom reset on
        # each subtitle. A small framing margin keeps the subject inside the frame.
        diagonal = direction in ('drift_up_right', 'drift_down_left')
        dz = max(3, min(dz, 12))
        margin = dp * (0.55 if diagonal else 0.75)
        if direction.startswith('reveal'):
            cam['zoom_start'] = min(ZOOM_MAX, base + dz)
            cam['zoom_end'] = base
        else:
            cam['zoom_start'] = max(base, math.ceil(100 / (1 - 2 * margin)))
            cam['zoom_end'] = min(ZOOM_MAX, cam['zoom_start'] + dz)
        signs = {
            'push_left': (-1, 0), 'push_right': (1, 0),
            'push_up': (0, -1), 'push_down': (0, 1),
            'reveal_left': (-1, 0), 'reveal_right': (1, 0),
            'drift_up_right': (0.75, -0.75), 'drift_down_left': (-0.75, 0.75),
        }
        sx, sy = signs[direction]
        cam['x_start'], cam['x_end'] = fx - sx * margin, fx + sx * margin
        cam['y_start'], cam['y_end'] = fy - sy * margin, fy + sy * margin
        cam['easing'] = 'ease-in-out'
    elif direction != 'static':
        raise ValueError('Unknown camera move.')
    cam['preset'] = direction
    for k in ('x_start', 'x_end', 'y_start', 'y_end'):
        cam[k] = round(min(1.0, max(0.0, cam[k])), 4)
    return cam


def normalise(value) -> dict | None:
    """A validated copy of a camera, or None for "no camera". Raises ValueError."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError('The camera must be an object, or null to remove it.')
    out = {}
    for key in ('zoom_start', 'zoom_end'):
        v = value.get(key, 100)
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not ZOOM_MIN <= v <= ZOOM_MAX:
            raise ValueError(f'{key} must be a percentage from {ZOOM_MIN} to {ZOOM_MAX}.')
        out[key] = round(float(v), 2)
    for key in ('x_start', 'y_start', 'x_end', 'y_end'):
        v = value.get(key, 0.5)
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= 1:
            raise ValueError(f'{key} must be a fraction of the frame from 0 to 1.')
        out[key] = round(float(v), 4)
    if value.get('preset') == 'portrait_reveal':
        middle = value.get('zoom_mid', 102)
        if isinstance(middle, bool) or not isinstance(middle, (int, float)) or not ZOOM_MIN <= middle <= ZOOM_MAX:
            raise ValueError('zoom_mid must be between 100 and 200 percent.')
        out['zoom_mid'] = round(float(middle), 2)
    easing = value.get('easing', 'ease-in-out')
    if easing not in EASINGS:
        raise ValueError('easing must be one of: ' + ', '.join(EASINGS) + '.')
    out['easing'] = easing
    origin = value.get('origin', 'manual')
    out['origin'] = origin if origin in ('manual', 'auto', 'ai') else 'manual'
    out['locked'] = bool(value.get('locked', False))
    if value.get('preset') in ('portrait_reveal', 'static', 'zoom_in', 'zoom_out', 'pan_left', 'pan_right', 'pan_up',
                              'pan_down', 'push_left', 'push_right', 'push_up', 'push_down',
                              'reveal_left', 'reveal_right', 'drift_up_right', 'drift_down_left'):
        out['preset'] = value['preset']
    if value.get('reason'):
        out['reason'] = str(value['reason'])[:400]
    if 'motion_end' in value:
        motion_end = value.get('motion_end')
        if isinstance(motion_end, bool) or not isinstance(motion_end, (int, float)) or not 0.05 <= motion_end <= 1:
            raise ValueError('motion_end must be a fraction from 0.05 to 1.')
        out['motion_end'] = round(float(motion_end), 6)
    return out


def is_moving(cam) -> bool:
    return bool(cam) and (cam.get('preset') == 'portrait_reveal' or (cam['zoom_start'] != cam['zoom_end'] or cam['x_start'] != cam['x_end']
                          or cam['y_start'] != cam['y_end']))


def is_active(cam) -> bool:
    """True when the camera changes the picture at all (moves, or holds a zoom)."""
    return bool(cam) and (is_moving(cam) or cam['zoom_start'] != 100)


def ease(p: float, easing: str) -> float:
    p = min(1.0, max(0.0, p))
    if easing == 'ease-in':
        return p * p
    if easing == 'ease-out':
        return 1 - (1 - p) * (1 - p)
    if easing == 'ease-in-out':
        return 0.5 - 0.5 * math.cos(math.pi * p)
    return p


def progress(frame: int, total: int) -> float:
    """Where frame `frame` (0-based) of a `total`-frame slot sits: 0 on its first frame, 1 on its last."""
    return 0.0 if total <= 1 else min(1.0, max(0.0, frame / (total - 1)))


def window(cam, p: float) -> tuple[float, float, float]:
    """(zoom, centre_x, centre_y) at progress p; centre as a fraction of the frame, clamped."""
    p = min(1.0, p / float(cam.get('motion_end') or 1))
    e = ease(p, cam['easing'])
    if cam.get('preset') == 'portrait_reveal':
        turn = 0.58
        if p <= turn:
            phase = ease(p / turn, 'ease-in-out')
            z = (cam['zoom_start'] + (cam['zoom_mid'] - cam['zoom_start']) * phase) / 100
        else:
            phase = ease((p - turn) / (1 - turn), 'ease-in-out')
            z = (cam['zoom_mid'] + (cam['zoom_end'] - cam['zoom_mid']) * phase) / 100
    else:
        z = (cam['zoom_start'] + (cam['zoom_end'] - cam['zoom_start']) * e) / 100
    cx = cam['x_start'] + (cam['x_end'] - cam['x_start']) * e
    cy = cam['y_start'] + (cam['y_end'] - cam['y_start']) * e
    half = 0.5 / z
    return z, min(1 - half, max(half, cx)), min(1 - half, max(half, cy))


def _ease_expr(p: str, easing: str) -> str:
    if easing == 'ease-in':
        return f'({p})*({p})'
    if easing == 'ease-out':
        return f'(1-(1-({p}))*(1-({p})))'
    if easing == 'ease-in-out':
        return f'(0.5-0.5*cos(PI*({p})))'
    return f'({p})'


def ffmpeg_filter(cam, width: int, height: int, first: int, total: int) -> str:
    """`perspective` filter drawing this camera on a `width`x`height` picture.

    `first` is the slot frame this encode starts at (a piece may start inside its slot,
    or run past its end for a blend; past the end the last framing is held), `total`
    the slot's frame count. The expressions are `window()` written for ffmpeg.
    """
    # perspective's `in` counts input frames from 1, so the slot frame is first + in - 1.
    k = f'({int(first) - 1}+in)'
    p = '0' if total <= 1 else f'min(1,max(0,{k}/{int(total) - 1}))'
    motion_end = float(cam.get('motion_end') or 1)
    if motion_end < 1:
        p = f'min(1,max(0,({p})/{motion_end:.6f}))'
    e = _ease_expr(p, cam['easing'])
    zs, ze = cam['zoom_start'] / 100, cam['zoom_end'] / 100
    if cam.get('preset') == 'portrait_reveal':
        zm = cam['zoom_mid'] / 100
        phase_a = f'(0.5-0.5*cos(PI*min(1,max(0,({p})/0.58))))'
        phase_b = f'(0.5-0.5*cos(PI*min(1,max(0,(({p})-0.58)/0.42))))'
        z = (f'if(lt({p},0.58),'
             f'({zs:.6f}+({zm - zs:.6f})*{phase_a}),'
             f'({zm:.6f}+({ze - zm:.6f})*{phase_b}))')
    else:
        z = f'({zs:.6f}+({ze - zs:.6f})*{e})'
    half = f'(0.5/{z})'
    cx = f"min(1-{half},max({half},{cam['x_start']:.6f}+({cam['x_end'] - cam['x_start']:.6f})*{e}))"
    cy = f"min(1-{half},max({half},{cam['y_start']:.6f}+({cam['y_end'] - cam['y_start']:.6f})*{e}))"
    left, right = f'(({cx}-{half})*{width})', f'(({cx}+{half})*{width})'
    top, bottom = f'(({cy}-{half})*{height})', f'(({cy}+{half})*{height})'
    # Commas inside an expression must be escaped in a filtergraph.
    esc = lambda s: s.replace(',', r'\,')
    return (f"perspective=x0='{esc(left)}':y0='{esc(top)}':x1='{esc(right)}':y1='{esc(top)}':"
            f"x2='{esc(left)}':y2='{esc(bottom)}':x3='{esc(right)}':y3='{esc(bottom)}':"
            f"interpolation=linear:sense=source:eval=frame")
