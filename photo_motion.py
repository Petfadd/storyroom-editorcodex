"""Professional, varied motion for photographs: how each photo arrives and how it moves.

Every photo appearance gets a *move*: an entrance (fade in, or slide in from the left,
right, top or bottom and settle) plus an edited camera move (push in, pull out, drift,
reveal, portrait reveal). Moves rotate through a designed sequence so two
photos in a row never arrive the same way or move the same way, and the narration can
steer the choice (grief pulls out slowly, an arrest drops in from the top, a first
introduction gets a portrait reveal). The choice is stable: the same project gives the
same edit in the preview and the export, every time.

Used by person_overlays (featured-person photos over footage) and truecrime_camera
(still images placed on the timeline). Nothing here changes timing, audio or the SRT.
"""
from __future__ import annotations

import hashlib
import re

# name -> (entrance, camera preset, plain description)
MOVES = {
    'fade_push_in':     ('fade',   'zoom_in',          'Clean push in, then settle'),
    'slide_left':       ('left',   'push_right',       'Left reveal with a composed diagonal push'),
    'drop_top':         ('top',    'reveal_right',     'Top reveal, then settle on the subject'),
    'fade_pull_out':    ('fade',   'zoom_out',         'Controlled pull back, then hold'),
    'slide_right':      ('right',  'push_left',        'Right reveal with a composed diagonal push'),
    'portrait_reveal':  ('fade',   'portrait_reveal',  'Portrait reveal: close, full portrait, final emphasis'),
    'rise_bottom':      ('bottom', 'drift_up_right',   'Rises into a short diagonal reveal'),
    'slide_left_pan':   ('left',   'reveal_left',      'Left entrance with a clean reveal, not a continuous pan'),
    'fade_reveal_left': ('fade',   'reveal_left',      'Clean reveal toward the left, then hold'),
    'drop_top_push':    ('top',    'push_down',        'Top entrance with a firm push, then hold'),
}
# The order photos cycle through. Neighbours differ in entrance AND camera move,
# including the wrap-around from the last back to the first.
SEQUENCE = ['fade_push_in', 'slide_left', 'drop_top', 'fade_pull_out', 'slide_right',
            'portrait_reveal', 'rise_bottom', 'slide_left_pan', 'fade_reveal_left', 'drop_top_push']

_GRIEF = ('memorial', 'funeral', 'vigil', 'mourning', 'mourned', 'grief', 'tribute', 'remembered', 'loss',
          'died', 'death', 'passed away', 'buried', 'heartbroken', 'missed', 'loved')
_ARREST = ('arrested', 'arrest', 'charged', 'booked', 'custody', 'mugshot', 'booking', 'suspect', 'warrant',
           'indicted', 'convicted', 'sentenced')
_MEMORY = ('childhood', 'grew up', 'as a child', 'young', 'born', 'smile', 'family', 'remember')

ENTRANCE_MS = {'fade': 280, 'left': 380, 'right': 380, 'top': 340, 'bottom': 340, 'cut': 0}
EXIT_FADE_MS = 220
MOVE_SECONDS = {'subtle': 3.0, 'medium': 2.25, 'strong': 1.6}


def active_frames(total_frames, intensity='medium', fps=30):
    """Frames used for the move before the final composition holds steady."""
    total = max(1, int(total_frames or 1))
    seconds = MOVE_SECONDS.get(intensity, MOVE_SECONDS['medium'])
    return min(total, max(2, round(seconds * fps)))


def _has(text, words):
    return any(re.search(r'\b' + re.escape(w) + r'\b', text) for w in words)


def _start(seed_text):
    return hashlib.sha256(seed_text.encode('utf-8')).digest()[0] % len(SEQUENCE)


def plan_moves(items, seed='', fixed_camera=None, intensity='subtle'):
    """Choose a move for each item, in order.

    `items` are dicts with: text (narration around the photo), duration_ms, name_intro,
    handover (True when it replaces another photo directly), mugshot. Returns a list of
    dicts {move, entrance, camera_preset, enter_ms, exit, exit_ms, reason, label}.
    `fixed_camera` (a cinematic preset name) applies one camera to every photo, as the
    user chose, while entrances still vary.
    """
    out = []
    turn = _start(seed)
    prev_enter, prev_cam = None, None
    recent = []
    for item in items:
        text = str(item.get('text') or '').lower()
        dur = max(0, int(item.get('duration_ms') or 0))
        preferred, reason = [], None
        if item.get('mugshot') or _has(text, _ARREST):
            preferred, reason = ['drop_top_push', 'drop_top'], 'Arrest or charge: the photo drops in, then a firm push in.'
        elif _has(text, _GRIEF):
            preferred, reason = ['fade_pull_out', 'portrait_reveal'], 'Grief or remembrance: a controlled pull back and respectful hold.'
        elif item.get('name_intro'):
            preferred, reason = ['portrait_reveal', 'fade_push_in', 'slide_left'], 'First time we meet this person: a portrait reveal with their name.'
        elif _has(text, _MEMORY):
            preferred, reason = ['fade_reveal_left', 'fade_pull_out'], 'Memory or family moment: a soft fade and reveal.'
        # Then the designed rotation, starting where the film's sequence currently is.
        rotation = [SEQUENCE[(turn + k) % len(SEQUENCE)] for k in range(len(SEQUENCE))]
        candidates = preferred + [m for m in rotation if m not in preferred]
        chosen = None
        for name in candidates:
            enter, cam, _ = MOVES[name]
            if item.get('handover') and enter == 'fade':
                # A photo replacing a photo slides over it; a fade would show a flash of footage.
                continue
            if enter == prev_enter or (fixed_camera is None and cam == prev_cam) or name in recent[-3:]:
                continue
            chosen = name
            break
        chosen = chosen or candidates[0]
        if chosen not in preferred:
            # Continue the designed sequence from the move just used.
            turn = SEQUENCE.index(chosen) + 1
            reason = None
        recent.append(chosen)
        enter, cam, label = MOVES[chosen]
        if fixed_camera:
            cam = None if fixed_camera == 'none' else fixed_camera
        # Short appearances get shorter entrances so the photo is still for most of it.
        enter_ms = min(ENTRANCE_MS.get(enter, 450), dur // 4) if dur else ENTRANCE_MS.get(enter, 450)
        out.append({'move': chosen, 'entrance': enter, 'camera_preset': cam, 'enter_ms': int(enter_ms),
                    'exit': 'none' if item.get('handed_over') else 'fade',
                    'exit_ms': 0 if item.get('handed_over') else int(min(EXIT_FADE_MS, dur // 5)),
                    'reason': reason or 'Varied sequence: different from the photo before it.', 'label': label,
                    'intensity': intensity})
        prev_enter, prev_cam = enter, cam
    return out


def camera_for(move, focus=(0.5, 0.5)):
    """The cinematic camera dict for a planned move, or None."""
    preset_name = move.get('camera_preset')
    if not preset_name or preset_name == 'static':
        return None
    from cinematic import preset, normalise, is_active
    try:
        cam = normalise(preset(preset_name, move.get('intensity') or 'subtle', focus))
    except ValueError:
        return None
    return cam if is_active(cam) else None


def entrance_offset(entrance, x, y, w, h, width, height):
    """(dx, dy) in pixels at the START of the entrance: the photo is fully off-picture."""
    if entrance == 'left':
        return -(x + w), 0
    if entrance == 'right':
        return width - x, 0
    if entrance == 'top':
        return 0, -(y + h)
    if entrance == 'bottom':
        return 0, height - y
    return 0, 0


def overlay_position(move, x, y, w, h, width, height, start_s):
    """FFmpeg overlay x/y expressions: slide from off-picture and settle (ease-out cubic)."""
    enter = move.get('entrance')
    d = (move.get('enter_ms') or 0) / 1000
    dx, dy = entrance_offset(enter, x, y, w, h, width, height)
    if not d or (dx == 0 and dy == 0):
        return str(x), str(y)
    p = f'min(1\\,max(0\\,(t-{start_s:.6f})/{d:.6f}))'
    settle = f'(1-pow(1-{p}\\,3))'
    ex = f'({x}+({dx})*(1-{settle}))' if dx else str(x)
    ey = f'({y}+({dy})*(1-{settle}))' if dy else str(y)
    return ex, ey
