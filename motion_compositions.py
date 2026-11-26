"""Cinematic composition variations for motion graphics.

Each template has multiple layout variations. The analyzer selects the variation
that best fits the content characteristics (text length, density, structure).

Variations are defined as functions that take (content, duration_s) and return
a Sequence with appropriate geometry and animation timing.
"""
from __future__ import annotations

from motion_templates import (
    Element, Sequence, rel,
    anim_mask_wipe, anim_fade, anim_slide_in, anim_rise,
    anim_scale_in, anim_divider_expand, anim_none,
    ease_out_cubic, ease_in_out_cubic, ease_out_quart,
)


# ============================================================ Investigative Findings

def investigative_findings_classic(content, duration_s):
    """Classic: left-aligned, kicker → title → divider → sequential bullets."""
    kicker = content.get('kicker', 'Investigative Findings')
    title = content.get('title', 'Key Findings')
    findings = list(content.get('findings') or [])[:6]
    elements = []
    t = 0.0

    elements.append(Element('kicker', rel(0.06, 0.10, 0.5, 0.04), text=kicker,
                            style={'size_ratio': 0.022, 'color': 'accent', 'uppercase': True,
                                   'letter_spacing_em': 0.18, 'font_kind': 'body'},
                            t_in=t, anim_in='mask_wipe', anim_in_dur=0.45))
    t += 0.25
    elements.append(Element('title', rel(0.06, 0.17, 0.80, 0.14), text=title,
                            style={'size_ratio': 0.075, 'color': 'text', 'font_kind': 'display',
                                   'max_lines': 2},
                            t_in=t, anim_in='mask_wipe', anim_in_dur=0.55))
    t += 0.40
    elements.append(Element('divider', rel(0.06, 0.33, 0.12, 0.0045),
                            style={'color': 'accent'},
                            t_in=t, anim_in='divider_expand', anim_in_dur=0.55))
    t += 0.35

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
                    elements=elements, meta={'findings': len(findings), 'layout': 'classic'})


def investigative_findings_centered(content, duration_s):
    """Centered: title centered, divider centered, bullets stacked center."""
    kicker = content.get('kicker', 'Investigative Findings')
    title = content.get('title', 'Key Findings')
    findings = list(content.get('findings') or [])[:5]
    elements = []
    t = 0.0

    elements.append(Element('kicker', rel(0.25, 0.12, 0.5, 0.04), text=kicker,
                            style={'size_ratio': 0.020, 'color': 'accent', 'uppercase': True,
                                   'letter_spacing_em': 0.25, 'font_kind': 'body', 'center': True},
                            t_in=t, anim_in='fade', anim_in_dur=0.5))
    t += 0.30
    elements.append(Element('title', rel(0.15, 0.20, 0.70, 0.16), text=title,
                            style={'size_ratio': 0.070, 'color': 'text', 'font_kind': 'display',
                                   'max_lines': 2, 'center': True},
                            t_in=t, anim_in='scale_in', anim_in_dur=0.65))
    t += 0.50
    elements.append(Element('divider', rel(0.35, 0.38, 0.30, 0.004),
                            style={'color': 'accent'},
                            t_in=t, anim_in='divider_expand', anim_in_dur=0.60))
    t += 0.40

    if findings:
        bullet_start_y = 0.42
        bullet_step = min(0.11, 0.50 / max(1, len(findings)))
        per_bullet = max(0.5, (duration_s - t - 1.0) / max(1, len(findings)))
        for i, line in enumerate(findings):
            elements.append(Element('bullet', rel(0.20, bullet_start_y + i * bullet_step, 0.60, bullet_step * 0.90),
                                    text=line,
                                    style={'size_ratio': 0.026, 'color': 'muted', 'font_kind': 'body',
                                           'bullet': True, 'max_lines': 2, 'center': True},
                                    t_in=t, anim_in='fade', anim_in_dur=0.55))
            t += per_bullet

    return Sequence('investigative_findings', duration_s, title=title,
                    elements=elements, meta={'findings': len(findings), 'layout': 'centered'})


# ============================================================ Chronological Timeline

def chronological_timeline_vertical(content, duration_s):
    """Vertical timeline on left, events to right."""
    events = list(content.get('events') or [])[:8]
    title = content.get('title', 'Chronology')
    elements = []
    t = 0.0

    elements.append(Element('kicker', rel(0.06, 0.08, 0.5, 0.04), text=title,
                            style={'size_ratio': 0.022, 'color': 'accent', 'uppercase': True,
                                   'letter_spacing_em': 0.18, 'font_kind': 'body'},
                            t_in=t, anim_in='mask_wipe', anim_in_dur=0.45))
    t += 0.30

    line_top = 0.16; line_bottom = 0.88
    elements.append(Element('timeline_line', rel(0.08, line_top, 0.0025, line_bottom - line_top),
                            style={'color': 'accent'},
                            t_in=t, anim_in='timeline_grow', anim_in_dur=duration_s * 0.75))

    if events:
        per_event = max(0.6, (duration_s - t - 1.0) / max(1, len(events)))
        step = (line_bottom - line_top) / max(1, len(events))
        for i, ev in enumerate(events):
            y = line_top + i * step
            elements.append(Element('marker', rel(0.074, y + step * 0.2, 0.012, 0.012),
                                    style={'color': 'accent', 'shape': 'circle'},
                                    t_in=t + 0.05, anim_in='scale_in', anim_in_dur=0.4))
            date_text = (ev.get('date') or '').strip() or 'Date'
            elements.append(Element('date', rel(0.10, y, 0.18, step * 0.5),
                                    text=date_text,
                                    style={'size_ratio': 0.026, 'color': 'accent',
                                           'font_kind': 'display'},
                                    t_in=t + 0.10, anim_in='fade', anim_in_dur=0.4))
            event_text = (ev.get('event') or '').strip() or ''
            elements.append(Element('event', rel(0.10, y + step * 0.32, 0.78, step * 0.65),
                                    text=event_text,
                                    style={'size_ratio': 0.022, 'color': 'text', 'font_kind': 'body',
                                           'max_lines': 2},
                                    t_in=t + 0.25, anim_in='rise', anim_in_dur=0.5))
            t += per_event

    return Sequence('chronological_timeline', duration_s, title=title, elements=elements,
                    meta={'events': len(events), 'layout': 'vertical'})


def chronological_timeline_horizontal(content, duration_s):
    """Horizontal timeline: events across the width, date on top, description below."""
    events = list(content.get('events') or [])[:6]
    title = content.get('title', 'Chronology')
    elements = []
    t = 0.0

    elements.append(Element('kicker', rel(0.06, 0.08, 0.5, 0.04), text=title,
                            style={'size_ratio': 0.022, 'color': 'accent', 'uppercase': True,
                                   'letter_spacing_em': 0.18, 'font_kind': 'body'},
                            t_in=t, anim_in='mask_wipe', anim_in_dur=0.45))
    t += 0.30

    line_left = 0.10; line_right = 0.90; line_y = 0.45
    elements.append(Element('timeline_line_h', rel(line_left, line_y, line_right - line_left, 0.003),
                            style={'color': 'accent'},
                            t_in=t, anim_in='timeline_grow_h', anim_in_dur=duration_s * 0.70))

    if events:
        per_event = max(0.8, (duration_s - t - 1.5) / max(1, len(events)))
        step = (line_right - line_left) / max(1, len(events))
        for i, ev in enumerate(events):
            x = line_left + i * step
            date_text = (ev.get('date') or '').strip() or 'Date'
            event_text = (ev.get('event') or '').strip() or ''

            elements.append(Element('marker', rel(x - 0.006, line_y - 0.006, 0.012, 0.012),
                                    style={'color': 'accent', 'shape': 'circle'},
                                    t_in=t + 0.05, anim_in='scale_in', anim_in_dur=0.4))
            elements.append(Element('date', rel(x - 0.08, line_y - 0.12, 0.18, 0.08),
                                    text=date_text,
                                    style={'size_ratio': 0.024, 'color': 'accent',
                                           'font_kind': 'display', 'center': True},
                                    t_in=t + 0.10, anim_in='fade', anim_in_dur=0.4))
            elements.append(Element('event', rel(x - 0.08, line_y + 0.05, 0.18, 0.12),
                                    text=event_text,
                                    style={'size_ratio': 0.020, 'color': 'muted', 'font_kind': 'body',
                                           'max_lines': 3, 'center': True},
                                    t_in=t + 0.30, anim_in='rise', anim_in_dur=0.5))
            t += per_event

    return Sequence('chronological_timeline', duration_s, title=title, elements=elements,
                    meta={'events': len(events), 'layout': 'horizontal'})


# ============================================================ Contradictory Statements

def contradictory_statements_split(content, duration_s):
    """Split: verified top, conflicting bottom, divider between."""
    verified = content.get('verified', '') or ''
    conflicting = content.get('conflicting', '') or ''
    verified_label = content.get('verified_label', 'Verified')
    conflicting_label = content.get('conflicting_label', 'Conflicting')
    title = content.get('title', 'Discrepancy')
    elements = []
    t = 0.0

    elements.append(Element('kicker', rel(0.06, 0.10, 0.5, 0.04), text=title,
                            style={'size_ratio': 0.022, 'color': 'accent', 'uppercase': True,
                                   'letter_spacing_em': 0.18, 'font_kind': 'body'},
                            t_in=t, anim_in='mask_wipe', anim_in_dur=0.45))
    t += 0.35

    elements.append(Element('label', rel(0.06, 0.20, 0.30, 0.035), text=verified_label.upper(),
                            style={'size_ratio': 0.020, 'color': 'text', 'uppercase': True,
                                   'letter_spacing_em': 0.18, 'font_kind': 'body'},
                            t_in=t, anim_in='fade', anim_in_dur=0.4))
    elements.append(Element('body', rel(0.06, 0.25, 0.85, 0.20), text=verified,
                            style={'size_ratio': 0.032, 'color': 'text', 'font_kind': 'display',
                                   'max_lines': 3, 'accent_bar': True, 'accent_color': 'text'},
                            t_in=t + 0.15, anim_in='mask_wipe', anim_in_dur=0.6))
    t += 1.0

    elements.append(Element('divider', rel(0.06, 0.49, 0.85, 0.0035),
                            style={'color': 'accent'},
                            t_in=t, anim_in='divider_expand', anim_in_dur=0.55))
    t += 0.40

    elements.append(Element('label', rel(0.06, 0.53, 0.30, 0.035), text=conflicting_label.upper(),
                            style={'size_ratio': 0.020, 'color': 'accent', 'uppercase': True,
                                   'letter_spacing_em': 0.18, 'font_kind': 'body'},
                            t_in=t, anim_in='fade', anim_in_dur=0.4))
    elements.append(Element('body', rel(0.06, 0.58, 0.85, 0.20), text=conflicting,
                            style={'size_ratio': 0.032, 'color': 'muted', 'font_kind': 'display',
                                   'max_lines': 3, 'accent_bar': True, 'accent_color': 'accent',
                                   'italic': True},
                            t_in=t + 0.15, anim_in='mask_wipe', anim_in_dur=0.6))

    return Sequence('contradictory_statements', duration_s, title=title, elements=elements,
                    meta={'has_verified': bool(verified), 'has_conflicting': bool(conflicting), 'layout': 'split'})


def contradictory_statements_side_by_side(content, duration_s):
    """Side-by-side: verified left column, conflicting right column."""
    verified = content.get('verified', '') or ''
    conflicting = content.get('conflicting', '') or ''
    title = content.get('title', 'Discrepancy')
    elements = []
    t = 0.0

    elements.append(Element('kicker', rel(0.06, 0.08, 0.5, 0.04), text=title,
                            style={'size_ratio': 0.022, 'color': 'accent', 'uppercase': True,
                                   'letter_spacing_em': 0.18, 'font_kind': 'body'},
                            t_in=t, anim_in='mask_wipe', anim_in_dur=0.45))
    t += 0.35

    mid_x = 0.50
    elements.append(Element('divider_v', rel(mid_x - 0.0015, 0.16, 0.003, 0.65),
                            style={'color': 'accent'},
                            t_in=t, anim_in='timeline_grow', anim_in_dur=0.60))
    t += 0.30

    elements.append(Element('label', rel(0.06, 0.18, 0.40, 0.035), text='VERIFIED',
                            style={'size_ratio': 0.018, 'color': 'text', 'uppercase': True,
                                   'letter_spacing_em': 0.18, 'font_kind': 'body'},
                            t_in=t, anim_in='fade', anim_in_dur=0.4))
    elements.append(Element('body', rel(0.06, 0.24, 0.42, 0.50), text=verified,
                            style={'size_ratio': 0.028, 'color': 'text', 'font_kind': 'display',
                                   'max_lines': 5, 'accent_bar': True, 'accent_color': 'text'},
                            t_in=t + 0.15, anim_in='mask_wipe', anim_in_dur=0.60))

    elements.append(Element('label', rel(mid_x + 0.02, 0.18, 0.40, 0.035), text='CONFLICTING',
                            style={'size_ratio': 0.018, 'color': 'accent', 'uppercase': True,
                                   'letter_spacing_em': 0.18, 'font_kind': 'body'},
                            t_in=t + 0.30, anim_in='fade', anim_in_dur=0.4))
    elements.append(Element('body', rel(mid_x + 0.02, 0.24, 0.42, 0.50), text=conflicting,
                            style={'size_ratio': 0.028, 'color': 'muted', 'font_kind': 'display',
                                   'max_lines': 5, 'accent_bar': True, 'accent_color': 'accent',
                                   'italic': True},
                            t_in=t + 0.45, anim_in='mask_wipe', anim_in_dur=0.60))

    return Sequence('contradictory_statements', duration_s, title=title, elements=elements,
                    meta={'has_verified': bool(verified), 'has_conflicting': bool(conflicting), 'layout': 'side_by_side'})


# ============================================================ Legal Outcome

def legal_outcome_formal(content, duration_s):
    """Formal: court header, charges list, verdict, sentencing — top to bottom."""
    court = content.get('court', '')
    charges = list(content.get('charges') or [])[:5]
    verdict = content.get('verdict', '') or ''
    sentencing = content.get('sentencing', '') or ''
    elements = []
    t = 0.0

    elements.append(Element('kicker', rel(0.06, 0.10, 0.5, 0.04), text='Legal Outcome',
                            style={'size_ratio': 0.022, 'color': 'accent', 'uppercase': True,
                                   'letter_spacing_em': 0.18, 'font_kind': 'body'},
                            t_in=t, anim_in='mask_wipe', anim_in_dur=0.45))
    t += 0.25

    if court:
        elements.append(Element('label', rel(0.06, 0.16, 0.8, 0.035), text=court.upper(),
                                style={'size_ratio': 0.018, 'color': 'muted', 'uppercase': True,
                                       'letter_spacing_em': 0.14, 'font_kind': 'body'},
                                t_in=t, anim_in='fade', anim_in_dur=0.4))
        t += 0.30

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
                          'has_sentencing': bool(sentencing), 'layout': 'formal'})


# ============================================================ Registry

TEMPLATE_BUILDERS = {
    'investigative_findings': {
        'classic': investigative_findings_classic,
        'centered': investigative_findings_centered,
    },
    'chronological_timeline': {
        'vertical': chronological_timeline_vertical,
        'horizontal': chronological_timeline_horizontal,
    },
    'contradictory_statements': {
        'split': contradictory_statements_split,
        'side_by_side': contradictory_statements_side_by_side,
    },
    'legal_outcome': {
        'formal': legal_outcome_formal,
    },
}


def build_sequence_with_layout(template_id, content, duration_s, layout=None):
    """Build a sequence with an optional specific layout.

    If layout is None, selects the best layout based on content characteristics.
    """
    builders = TEMPLATE_BUILDERS.get(template_id)
    if not builders:
        raise ValueError(f'Unknown template: {template_id}')

    if layout and layout in builders:
        return builders[layout](content, duration_s)

    # Auto-select layout based on content characteristics.
    if template_id == 'investigative_findings':
        findings = content.get('findings') or []
        title_len = len(content.get('title', ''))
        # Long findings → centered (more breathing room), short → classic
        if len(findings) >= 4 and title_len > 30:
            return builders['centered'](content, duration_s)
        return builders['classic'](content, duration_s)

    if template_id == 'chronological_timeline':
        events = content.get('events') or []
        # Many events with short descriptions → horizontal (compact)
        if len(events) >= 5 and all(len(e.get('event', '')) < 60 for e in events):
            return builders['horizontal'](content, duration_s)
        return builders['vertical'](content, duration_s)

    if template_id == 'contradictory_statements':
        verified_len = len(content.get('verified', ''))
        conflicting_len = len(content.get('conflicting', ''))
        # Long text on both sides → side-by-side (better use of width)
        if verified_len > 80 and conflicting_len > 80:
            return builders['side_by_side'](content, duration_s)
        return builders['split'](content, duration_s)

    if template_id == 'legal_outcome':
        return builders['formal'](content, duration_s)

    # Fallback: first available
    first_builder = next(iter(builders.values()))
    return first_builder(content, duration_s)


def get_available_layouts(template_id):
    """Return list of available layout IDs for a template."""
    builders = TEMPLATE_BUILDERS.get(template_id, {})
    return list(builders.keys())
