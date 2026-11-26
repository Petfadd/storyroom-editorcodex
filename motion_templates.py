"""Motion graphics templates: element layout and per-frame animation.

Each template produces a list of *elements*. An element is a drawable unit
(heading, title, divider, bullet, date, event, statement, charge, etc.) with:

  - geometry (x, y, w, h) in *relative* coordinates of the frame (0..1)
  - a text payload
  - a reveal time `t_in` (seconds from sequence start) and optional `t_out`
  - an animation type (mask_wipe | slide_in | fade | rise | scale_in)
  - a style preset (font kind, size ratio, colour token)

The renderer (`motion_render`) walks frames, resolves relative geometry to
absolute pixels, and applies the animation for each element at each frame.
Templates never touch Pillow directly; they describe the composition.

Animation definitions are intentionally simple and deterministic. Easing is a
pure function of normalised time; no state is carried between frames.
"""
from __future__ import annotations

import math
from fractions import Fraction
from typing import Iterable


# --------------------------------------------------------------------- easing

def ease_out_cubic(t: float) -> float:
    t = max(0.0, min(1.0, t)); return 1 - (1 - t) ** 3


def ease_in_out_cubic(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 4 * t * t * t if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


def ease_out_quart(t: float) -> float:
    t = max(0.0, min(1.0, t)); return 1 - (1 - t) ** 4


# ------------------------------------------------------------------ primitives

# Geometry helpers: every element uses relative (0..1) coordinates of the frame,
# resolved to pixels in the renderer. This keeps the templates resolution-
# independent; 1080p, 2K and 4K exports share the same element list.

def rel(x, y, w, h):
    return {'x': float(x), 'y': float(y), 'w': float(w), 'h': float(h)}


# ---------------------------------------------------------------- animations

# Each animation function takes normalised time p in [0,1] (0 = hidden, 1 = final)
# and returns a dict describing how to draw the element at that instant. Fields:
#   - opacity (0..1)
#   - translate_x, translate_y (in *element* width/height units)
#   - scale (1 = final size)
#   - clip_right (0 = fully visible, 1 = fully clipped from the right)
#   - clip_bottom (same from the bottom)
# All default to the fully-revealed state.

def _default_state():
    return {'opacity': 1.0, 'translate_x': 0.0, 'translate_y': 0.0,
            'scale': 1.0, 'clip_right': 0.0, 'clip_bottom': 0.0}


def anim_none(_p):
    return _default_state()


def anim_mask_wipe(p):
    """Reveal by horizontal wipe: clip recedes from right to left."""
    s = _default_state()
    s['opacity'] = 1.0
    s['clip_right'] = 1 - ease_out_cubic(p)
    return s


def anim_fade(p):
    s = _default_state()
    s['opacity'] = ease_out_cubic(p)
    return s


def anim_slide_in(p, direction='left'):
    """Slide from outside the frame into final position."""
    s = _default_state()
    s['opacity'] = ease_out_cubic(p)
    amt = 1.0 - ease_out_quart(p)
    if direction == 'left':
        s['translate_x'] = -amt
    elif direction == 'right':
        s['translate_x'] = amt
    elif direction == 'up':
        s['translate_y'] = amt
    elif direction == 'down':
        s['translate_y'] = -amt
    return s


def anim_rise(p):
    s = _default_state()
    s['opacity'] = ease_out_cubic(p)
    s['translate_y'] = (1 - ease_out_quart(p)) * 0.4
    return s


def anim_scale_in(p):
    s = _default_state()
    s['opacity'] = ease_out_cubic(p)
    s['scale'] = 0.85 + 0.15 * ease_out_cubic(p)
    return s


def anim_divider_expand(p):
    """Horizontal divider growing from centre outward."""
    s = _default_state()
    s['scale'] = ease_out_quart(p)   # used as horizontal scale for the divider
    s['opacity'] = min(1.0, p * 3)
    return s


ANIMATIONS = {
    'none': anim_none,
    'mask_wipe': anim_mask_wipe,
    'fade': anim_fade,
    'slide_left': lambda p: anim_slide_in(p, 'left'),
    'slide_right': lambda p: anim_slide_in(p, 'right'),
    'slide_up': lambda p: anim_slide_in(p, 'up'),
    'slide_down': lambda p: anim_slide_in(p, 'down'),
    'rise': anim_rise,
    'scale_in': anim_scale_in,
    'divider_expand': anim_divider_expand,
}


def resolve_animation(name, p):
    fn = ANIMATIONS.get(name, anim_none)
    return fn(p)


# ---------------------------------------------------------------- element dataclass

class Element:
    """One drawable unit within a motion graphics sequence."""

    __slots__ = ('kind', 'geom', 'text', 'lines', 'style', 't_in', 't_out',
                 'anim_in', 'anim_out', 'anim_in_dur', 'anim_out_dur')

    def __init__(self, kind, geom, text='', lines=None, style=None,
                 t_in=0.0, t_out=None,
                 anim_in='mask_wipe', anim_out=None,
                 anim_in_dur=0.5, anim_out_dur=0.4):
        self.kind = kind          # heading | title | kicker | divider | bullet | date | event | label | body | accent
        self.geom = geom          # rel(x,y,w,h)
        self.text = text
        self.lines = lines        # list[str]; if set, drawn as multiple lines
        self.style = style or {}
        self.t_in = float(t_in)
        self.t_out = float(t_out) if t_out is not None else None
        self.anim_in = anim_in
        self.anim_out = anim_out
        self.anim_in_dur = float(anim_in_dur)
        self.anim_out_dur = float(anim_out_dur)

    def state_at(self, t):
        """Return the animation state for this element at absolute time t (s)."""
        if t < self.t_in:
            # Not yet revealed: fully hidden.
            return {'opacity': 0.0, 'translate_x': 0.0, 'translate_y': 0.0,
                    'scale': 1.0, 'clip_right': 1.0, 'clip_bottom': 0.0}
        if self.t_out is not None and t >= self.t_out:
            if not self.anim_out:
                # Once the element leaves, it is done.
                return {'opacity': 0.0, 'translate_x': 0.0, 'translate_y': 0.0,
                        'scale': 1.0, 'clip_right': 1.0, 'clip_bottom': 0.0}
            p = min(1.0, (t - self.t_out) / max(0.001, self.anim_out_dur))
            state = resolve_animation(self.anim_out, p)
            state['opacity'] = 1 - state['opacity']
            return state
        # Revealed: compute entrance progress and hold.
        p = min(1.0, (t - self.t_in) / max(0.001, self.anim_in_dur))
        return resolve_animation(self.anim_in, p)


# ---------------------------------------------------------------- templates

class Sequence:
    """A complete motion graphics composition: ordered list of Elements."""

    def __init__(self, template_id, duration_s, title='', elements=None, meta=None):
        self.template_id = template_id
        self.duration_s = float(duration_s)
        self.title = title
        self.elements = list(elements or [])
        self.meta = meta or {}

    def states_at(self, t):
        return [(el, el.state_at(t)) for el in self.elements]


# -------- Template A: Investigative Findings --------
# Small kicker heading, bold cinematic title, animated divider, sequential bullets.
# Previously revealed bullets remain visible as new ones appear.

def investigative_findings(content, duration_s):
    kicker = content.get('kicker', 'Investigative Findings')
    title = content.get('title', 'Key Findings')
    findings = list(content.get('findings') or [])[:6]
    elements = []
    t = 0.0
    # Kicker: top-left, small caps.
    elements.append(Element('kicker', rel(0.06, 0.10, 0.5, 0.04), text=kicker,
                            style={'size_ratio': 0.022, 'color': 'accent', 'uppercase': True,
                                   'letter_spacing_em': 0.18, 'font_kind': 'body'},
                            t_in=t, anim_in='mask_wipe', anim_in_dur=0.45))
    t += 0.25
    # Title: large, bold.
    elements.append(Element('title', rel(0.06, 0.17, 0.80, 0.14), text=title,
                            style={'size_ratio': 0.075, 'color': 'text', 'font_kind': 'display',
                                   'max_lines': 2},
                            t_in=t, anim_in='mask_wipe', anim_in_dur=0.55))
    t += 0.40
    # Divider: 60 px wide, grows horizontally from left.
    elements.append(Element('divider', rel(0.06, 0.33, 0.12, 0.0045),
                            style={'color': 'accent'},
                            t_in=t, anim_in='divider_expand', anim_in_dur=0.55))
    t += 0.35
    # Findings: sequential bullets, spaced vertically; each appears as narration
    # mentions it, and previous ones stay visible.
    if findings:
        bullet_start_y = 0.37
        bullet_step = min(0.10, 0.55 / max(1, len(findings)))
        per_bullet = max(0.4, (duration_s - t - 1.5) / max(1, len(findings)))
        for i, line in enumerate(findings):
            elements.append(Element('bullet', rel(0.06, bullet_start_y + i * bullet_step, 0.82, bullet_step * 0.95),
                                    text=line,
                                    style={'size_ratio': 0.028, 'color': 'muted', 'font_kind': 'body',
                                           'bullet': True, 'max_lines': 2},
                                    t_in=t, anim_in='rise', anim_in_dur=0.55))
            t += per_bullet
    return Sequence('investigative_findings', duration_s, title=title,
                    elements=elements, meta={'findings': len(findings)})


# -------- Template B: Chronological Timeline --------
# Vertical timeline on the left with date labels; events to the right. Animated
# connecting line grows between entries; markers appear at each date.

def chronological_timeline(content, duration_s):
    events = list(content.get('events') or [])[:8]
    title = content.get('title', 'Chronology')
    elements = []
    t = 0.0
    # Title (top).
    elements.append(Element('kicker', rel(0.06, 0.08, 0.5, 0.04), text=title,
                            style={'size_ratio': 0.022, 'color': 'accent', 'uppercase': True,
                                   'letter_spacing_em': 0.18, 'font_kind': 'body'},
                            t_in=t, anim_in='mask_wipe', anim_in_dur=0.45))
    t += 0.30
    # Connecting line: full-height vertical stroke on the left of the content area.
    line_top = 0.16; line_bottom = 0.88
    elements.append(Element('timeline_line', rel(0.08, line_top, 0.0025, line_bottom - line_top),
                            style={'color': 'accent'},
                            t_in=t, anim_in='timeline_grow', anim_in_dur=duration_s * 0.75))
    # Events: sequentially revealed date + description pairs.
    if events:
        per_event = max(0.6, (duration_s - t - 1.0) / max(1, len(events)))
        step = (line_bottom - line_top) / max(1, len(events))
        for i, ev in enumerate(events):
            y = line_top + i * step
            # Marker dot.
            elements.append(Element('marker', rel(0.074, y + step * 0.2, 0.012, 0.012),
                                    style={'color': 'accent', 'shape': 'circle'},
                                    t_in=t + 0.05, anim_in='scale_in', anim_in_dur=0.4))
            # Date label.
            date_text = (ev.get('date') or '').strip() or 'Date'
            elements.append(Element('date', rel(0.10, y, 0.18, step * 0.5),
                                    text=date_text,
                                    style={'size_ratio': 0.026, 'color': 'accent',
                                           'font_kind': 'display'},
                                    t_in=t + 0.10, anim_in='fade', anim_in_dur=0.4))
            # Event description.
            event_text = (ev.get('event') or '').strip() or ''
            elements.append(Element('event', rel(0.10, y + step * 0.32, 0.78, step * 0.65),
                                    text=event_text,
                                    style={'size_ratio': 0.022, 'color': 'text', 'font_kind': 'body',
                                           'max_lines': 2},
                                    t_in=t + 0.25, anim_in='rise', anim_in_dur=0.5))
            t += per_event
    return Sequence('chronological_timeline', duration_s, title=title, elements=elements,
                    meta={'events': len(events)})


# -------- Template C: Contradictory Statements --------
# Two panels stacked vertically: verified (left accent) and conflicting (red
# accent). An animated separator appears between them.

def contradictory_statements(content, duration_s):
    verified = content.get('verified', '') or ''
    conflicting = content.get('conflicting', '') or ''
    verified_label = content.get('verified_label', 'Verified')
    conflicting_label = content.get('conflicting_label', 'Conflicting')
    title = content.get('title', 'Discrepancy')
    elements = []
    t = 0.0
    # Title.
    elements.append(Element('kicker', rel(0.06, 0.10, 0.5, 0.04), text=title,
                            style={'size_ratio': 0.022, 'color': 'accent', 'uppercase': True,
                                   'letter_spacing_em': 0.18, 'font_kind': 'body'},
                            t_in=t, anim_in='mask_wipe', anim_in_dur=0.45))
    t += 0.35
    # Verified panel label.
    elements.append(Element('label', rel(0.06, 0.20, 0.30, 0.035), text=verified_label.upper(),
                            style={'size_ratio': 0.020, 'color': 'text', 'uppercase': True,
                                   'letter_spacing_em': 0.18, 'font_kind': 'body'},
                            t_in=t, anim_in='fade', anim_in_dur=0.4))
    # Verified body.
    elements.append(Element('body', rel(0.06, 0.25, 0.85, 0.20), text=verified,
                            style={'size_ratio': 0.032, 'color': 'text', 'font_kind': 'display',
                                   'max_lines': 3, 'accent_bar': True, 'accent_color': 'text'},
                            t_in=t + 0.15, anim_in='mask_wipe', anim_in_dur=0.6))
    t += 1.0
    # Separator line (animated).
    elements.append(Element('divider', rel(0.06, 0.49, 0.85, 0.0035),
                            style={'color': 'accent'},
                            t_in=t, anim_in='divider_expand', anim_in_dur=0.55))
    t += 0.40
    # Conflicting panel label.
    elements.append(Element('label', rel(0.06, 0.53, 0.30, 0.035), text=conflicting_label.upper(),
                            style={'size_ratio': 0.020, 'color': 'accent', 'uppercase': True,
                                   'letter_spacing_em': 0.18, 'font_kind': 'body'},
                            t_in=t, anim_in='fade', anim_in_dur=0.4))
    # Conflicting body.
    elements.append(Element('body', rel(0.06, 0.58, 0.85, 0.20), text=conflicting,
                            style={'size_ratio': 0.032, 'color': 'muted', 'font_kind': 'display',
                                   'max_lines': 3, 'accent_bar': True, 'accent_color': 'accent',
                                   'italic': True},
                            t_in=t + 0.15, anim_in='mask_wipe', anim_in_dur=0.6))
    return Sequence('contradictory_statements', duration_s, title=title, elements=elements,
                    meta={'has_verified': bool(verified), 'has_conflicting': bool(conflicting)})


# -------- Template D: Legal Outcome --------
# Charges, verdict and sentencing revealed sequentially, with a formal layout.

def legal_outcome(content, duration_s):
    court = content.get('court', '')
    charges = list(content.get('charges') or [])[:5]
    verdict = content.get('verdict', '') or ''
    sentencing = content.get('sentencing', '') or ''
    elements = []
    t = 0.0
    # Heading.
    elements.append(Element('kicker', rel(0.06, 0.10, 0.5, 0.04), text='Legal Outcome',
                            style={'size_ratio': 0.022, 'color': 'accent', 'uppercase': True,
                                   'letter_spacing_em': 0.18, 'font_kind': 'body'},
                            t_in=t, anim_in='mask_wipe', anim_in_dur=0.45))
    t += 0.25
    # Court (if any).
    if court:
        elements.append(Element('label', rel(0.06, 0.16, 0.8, 0.035), text=court.upper(),
                                style={'size_ratio': 0.018, 'color': 'muted', 'uppercase': True,
                                       'letter_spacing_em': 0.14, 'font_kind': 'body'},
                                t_in=t, anim_in='fade', anim_in_dur=0.4))
        t += 0.30
    # Charges.
    if charges:
        per_charge = max(0.35, (duration_s - t - 2.0) / max(1, len(charges) + 2))
        y = 0.22
        step = 0.05
        elements.append(Element('label', rel(0.06, y, 0.30, 0.035), text='CHARGES',
                                style={'size_ratio': 0.020, 'color': 'text', 'uppercase': True,
                                       'letter_spacing_em': 0.18, 'font_kind': 'body'},
                                t_in=t, anim_in='fade', anim_in_dur=0.4))
        t += 0.30
        for i, charge in enumerate(charges):
            elements.append(Element('charge', rel(0.08, y + 0.05 + i * step, 0.82, step),
                                    text=charge,
                                    style={'size_ratio': 0.024, 'color': 'text', 'font_kind': 'body',
                                           'bullet': True},
                                    t_in=t, anim_in='rise', anim_in_dur=0.45))
            t += per_charge
    # Verdict.
    if verdict:
        elements.append(Element('divider', rel(0.06, 0.60, 0.12, 0.0045),
                                style={'color': 'accent'},
                                t_in=t, anim_in='divider_expand', anim_in_dur=0.5))
        t += 0.35
        elements.append(Element('label', rel(0.06, 0.63, 0.30, 0.035), text='VERDICT',
                                style={'size_ratio': 0.020, 'color': 'muted', 'uppercase': True,
                                       'letter_spacing_em': 0.18, 'font_kind': 'body'},
                                t_in=t, anim_in='fade', anim_in_dur=0.4))
        elements.append(Element('verdict', rel(0.06, 0.68, 0.85, 0.08), text=verdict,
                                style={'size_ratio': 0.040, 'color': 'text', 'font_kind': 'display',
                                       'max_lines': 2},
                                t_in=t + 0.15, anim_in='scale_in', anim_in_dur=0.55))
        t += 0.60
    # Sentencing.
    if sentencing:
        elements.append(Element('label', rel(0.06, 0.80, 0.30, 0.035), text='SENTENCING',
                                style={'size_ratio': 0.020, 'color': 'muted', 'uppercase': True,
                                       'letter_spacing_em': 0.18, 'font_kind': 'body'},
                                t_in=t, anim_in='fade', anim_in_dur=0.4))
        elements.append(Element('sentence', rel(0.06, 0.84, 0.85, 0.06), text=sentencing,
                                style={'size_ratio': 0.028, 'color': 'muted', 'font_kind': 'body',
                                       'max_lines': 2},
                                t_in=t + 0.15, anim_in='rise', anim_in_dur=0.5))
    return Sequence('legal_outcome', duration_s, title='Legal Outcome', elements=elements,
                    meta={'charges': len(charges), 'has_verdict': bool(verdict),
                          'has_sentencing': bool(sentencing)})


# -------- Registry --------

BUILDERS = {
    'investigative_findings': investigative_findings,
    'chronological_timeline': chronological_timeline,
    'contradictory_statements': contradictory_statements,
    'legal_outcome': legal_outcome,
}


def build_sequence(template_id, content, duration_s):
    builder = BUILDERS.get(template_id)
    if not builder:
        raise ValueError(f'Unknown motion graphics template: {template_id}')
    return builder(content, duration_s)
