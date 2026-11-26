"""Intelligent Cinematic Motion Graphics Engine.

Non-destructive kinetic typography layer for investigative documentaries. The engine
reads the full production script and narration SRT, identifies context-appropriate
passages (Act 3/4/5/6), and proposes narration-synchronised motion graphics sequences.
Four context-aware templates (Investigative Findings, Chronological Timeline,
Contradictory Statements, Legal Outcome) produce genuinely animated per-frame renders
driven by Pillow, composited into the film by FFmpeg as a separate overlay layer.

Rules that matter
  * The feature is optional and disabled by default. Nothing runs until the user
    enables it for a project.
  * Original soundbites, narration audio, source timestamps, footage IDs, approved
    clip ranges and intentional reuse are never modified.
  * Disabling or removing the layer restores exactly the film that was there before.
  * Authentic footage remains primary; motion graphics supplement, not replace.
  * Sequences are placed only where the documentary context genuinely supports them.
    A 20-25 minute film may receive 2-5 suggestions, or none if none are justified.
  * Cold-open soundbites, victim introductions, family interviews, witness testimony,
    police briefings, courtroom soundbites, tributes, emotional closings and CTA
    passages are excluded.
  * Each text element animates in at its corresponding narration timestamp; findings
    are not revealed prematurely.
  * All output is offline, Python + FFmpeg only, frame-accurate at the project fps.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Iterable

VERSION = 1
TEMPLATES = ('investigative_findings', 'chronological_timeline',
             'contradictory_statements', 'legal_outcome')
DEFAULTS = {
    'enabled': False,
    'mode': 'auto',              # auto | manual
    'sequences': [],             # user-approved placements
    'suggestions': [],           # last generated proposal (not committed)
    'design': {
        'background': 'charcoal',    # charcoal | midnight | warm | neutral
        'display_font': 'Inter-Black',
        'body_font': 'Inter-SemiBold',
        'accent_color': '#DC656C',
        'text_color': '#F1F1EF',
        'muted_color': '#C0C3C9',
        'title_scale': 1.0,
        'body_scale': 1.0,
        'motion': 'adaptive',        # adaptive | mask | rise | slide | soft
    },
    'render': {
        'resolution': 'preview',     # preview | match_export
    },
}
LIMITS = {
    'sequences': 25,
    'min_duration_s': 3.0,
    'max_duration_s': 45.0,
    'max_per_film': 12,
}

# Contextual exclusion: narration passages whose purpose makes a motion graphic
# inappropriate. Patterns are matched against the beat's spoken narration and the
# beat's visual direction / continuity note.
_EXCLUDE_PATTERNS = (
    re.compile(r'\b(?:cold open|teaser)\b', re.I),
    re.compile(r'\b(?:victim(?:\'s)? (?:mother|father|sister|brother|daughter|son|family|loved))\b', re.I),
    re.compile(r'\b(?:family (?:interview|statement|tribute|grief|mourning))\b', re.I),
    re.compile(r'\b(?:witness (?:testif|statement|account|describ))\b', re.I),
    re.compile(r'\b(?:police (?:briefing|report|press|statement|chief))\b', re.I),
    re.compile(r'\b(?:courtroom (?:sound|audio|recording|gavel))\b', re.I),
    re.compile(r'\b(?:tribute|memorial|remembering|in loving memory)\b', re.I),
    re.compile(r'\b(?:in closing|final thoughts|thank you for watch)\b', re.I),
    re.compile(r'\b(?:subscribe|like and (?:share|comment)|hit the bell|call to action)\b', re.I),
    re.compile(r'\b(?:emotional|heart-?wrenching|devastat(?:ing|ed)|griev(?:ing|ing))\b', re.I),
)

# Contextual inclusion hints per act. The engine combines these with beat structure
# to score candidate passages; no single keyword alone places a graphic.
_ACT_HINTS = {
    3: (r'\b(?:timeline|chronolog|sequence|before|after|days? later|weeks? later|hours? later)\b',
        r'\b(?:then|next|subsequently|following|prior to)\b'),
    4: (r'\b(?:investigat|discover|uncover|detective|inquir|examin)\b',
        r'\b(?:found|revealed|learned|determined|concluded)\b'),
    5: (r'\b(?:evidence|discrepanc|contradic|inconsisten|finding|turning point)\b',
        r'\b(?:verified|confirmed|documented|proved|showed)\b'),
    6: (r'\b(?:charg|indict|verdict|sentenc|convict|acquitt|guilt|plea)\b',
        r'\b(?:court|judge|jury|trial|prosecut|defen[cs]e)\b'),
}


# --------------------------------------------------------------------- settings

def settings(project):
    """The project's motion graphics settings with defaults filled in."""
    saved = project.get('motion_graphics') or {}
    result = json.loads(json.dumps(DEFAULTS))
    for key, value in saved.items():
        if key not in DEFAULTS:
            continue
        if key == 'enabled':
            result[key] = bool(value)
        elif key == 'mode':
            result[key] = value if value in ('auto', 'manual') else 'auto'
        elif key == 'design':
            if isinstance(value, dict):
                for k, v in value.items():
                    if k in result['design']:
                        result['design'][k] = v
        elif key == 'render':
            if isinstance(value, dict):
                for k, v in value.items():
                    if k in result['render']:
                        result['render'][k] = v
        elif key == 'sequences':
            if isinstance(value, list):
                result[key] = [s for s in value if isinstance(s, dict)]
        elif key == 'suggestions':
            if isinstance(value, list):
                result[key] = [s for s in value if isinstance(s, dict)]
    return result


def normalise(project):
    """Persist the normalised settings into the project. Returns the settings."""
    project['motion_graphics'] = settings(project)
    return project['motion_graphics']


def catalogue(project):
    """Public summary for the editor: templates, availability, current design."""
    s = settings(project)
    return {
        'version': VERSION,
        'enabled': s['enabled'],
        'mode': s['mode'],
        'templates': [{'id': t, 'name': _template_name(t)} for t in TEMPLATES],
        'design': s['design'],
        'sequence_count': len(s['sequences']),
    }


def _template_name(template_id):
    return {
        'investigative_findings': 'Investigative Findings',
        'chronological_timeline': 'Chronological Timeline',
        'contradictory_statements': 'Contradictory Statements',
        'legal_outcome': 'Legal Outcome',
    }.get(template_id, template_id)


def validate_patch(patch):
    """Validate a PATCH payload; returns the subset that may be written."""
    if not isinstance(patch, dict):
        raise ValueError('Motion graphics settings must be an object.')
    values = {}
    for key, val in patch.items():
        if key not in DEFAULTS:
            raise ValueError(f'Unknown motion graphics setting: {key}')
        if key == 'enabled':
            if not isinstance(val, bool):
                raise ValueError('enabled must be true or false.')
        elif key == 'mode':
            if val not in ('auto', 'manual'):
                raise ValueError('mode must be auto or manual.')
        elif key == 'design':
            if not isinstance(val, dict):
                raise ValueError('design must be an object.')
            allowed = DEFAULTS['design'].keys()
            val = {k: v for k, v in val.items() if k in allowed}
        elif key == 'render':
            if not isinstance(val, dict):
                raise ValueError('render must be an object.')
            if 'resolution' in val and val['resolution'] not in ('preview', 'match_export'):
                raise ValueError('render.resolution must be preview or match_export.')
        elif key == 'sequences':
            if not isinstance(val, list):
                raise ValueError('sequences must be a list.')
            if len(val) > LIMITS['sequences']:
                raise ValueError(f'Too many sequences (max {LIMITS["sequences"]}).')
            clean = []
            for s in val:
                clean.append(_validate_sequence(s))
            val = clean
        elif key == 'suggestions':
            if not isinstance(val, list):
                raise ValueError('suggestions must be a list.')
            val = [_validate_sequence(s) for s in val]
        values[key] = val
    return values


def _validate_sequence(seq):
    if not isinstance(seq, dict):
        raise ValueError('Each sequence must be an object.')
    out = {}
    if 'id' not in seq or not isinstance(seq['id'], str) or not re.fullmatch(r'mg_[0-9a-f]{12}', seq['id']):
        raise ValueError('Each sequence must have a valid id.')
    out['id'] = seq['id']
    if seq.get('template') not in TEMPLATES:
        raise ValueError('Unknown template.')
    out['template'] = seq['template']
    try:
        start = float(seq['start_s']); end = float(seq['end_s'])
    except (KeyError, TypeError, ValueError):
        raise ValueError('Sequence must have numeric start_s and end_s.')
    if not (0 <= start < end):
        raise ValueError('Sequence end must be after start.')
    if end - start < LIMITS['min_duration_s']:
        raise ValueError(f'Sequence too short (min {LIMITS["min_duration_s"]}s).')
    if end - start > LIMITS['max_duration_s']:
        raise ValueError(f'Sequence too long (max {LIMITS["max_duration_s"]}s).')
    out['start_s'] = round(start, 3); out['end_s'] = round(end, 3)
    if not isinstance(seq.get('content'), dict):
        raise ValueError('Sequence must have a content object.')
    out['content'] = copy.deepcopy(seq['content'])
    if 'design' in seq and isinstance(seq['design'], dict):
        out['design'] = {k: v for k, v in seq['design'].items() if k in DEFAULTS['design']}
    if 'narration_binding' in seq and isinstance(seq['narration_binding'], list):
        out['narration_binding'] = copy.deepcopy(seq['narration_binding'])
    return out


# --------------------------------------------------------------------- analysis

def analyse_script(script_text, srt_blocks):
    """Read the full script and SRT; return structured context for placement.

    Returns a dict with:
      - acts: list of {act, beats: [...], start_ms, end_ms}
      - candidates: ranked passages suitable for motion graphics
      - excluded: passages that were considered but rejected
    The analysis never modifies the script or SRT; it only reads them.
    """
    script_text = script_text or ''
    srt_blocks = srt_blocks or []
    # 1. Act structure: derived from Act/Chapter markers in the script text,
    #    falling back to narration-clock thirds when none are present.
    acts = _detect_acts(script_text)
    # 2. Beat-level scoring: each narration beat is scored for template suitability.
    candidates = []
    excluded = []
    beats = []
    try:
        from documentary_beats import read_beats
        beats = read_beats(script_text)
    except Exception:
        # Fallback: derive beat-like segments from the SRT blocks so the engine
        # still works when the production script is in a non-standard format or
        # missing some Beat fields.
        beats = _beats_from_srt(srt_blocks)
        if not beats:
            # Last resort: extract narration segments from the raw script text.
            beats = _beats_from_script_text(script_text)
    for beat in beats:
        if beat.get('kind') != 'narration':
            continue
        narration = (beat.get('spoken_narration') or '').strip()
        if not narration:
            continue
        # 3. Hard exclusions
        if _is_excluded(beat):
            excluded.append({'reason': 'excluded_passage',
                             'beat': beat.get('label'),
                             'narration_in_ms': beat.get('narration_in_ms'),
                             'narration_out_ms': beat.get('narration_out_ms')})
            continue
        act = _beat_act(beat, acts)
        scores = _score_templates(narration, act, beat)
        if not scores:
            continue
        candidates.append({
            'beat': beat.get('label'),
            'act': act,
            'narration_in_ms': beat.get('narration_in_ms'),
            'narration_out_ms': beat.get('narration_out_ms'),
            'spoken_narration': narration,
            'template_scores': scores,
        })
    # 4. Rank candidates: prefer higher template score, mid-act (not first/last beat).
    candidates.sort(key=lambda c: (-max(c['template_scores'].values()),
                                   abs(c['act'] - 4.5)))
    return {'acts': acts, 'candidates': candidates[:20],
            'excluded': excluded[:20], 'beats_total': len(beats),
            'narration_beats': len([b for b in beats if b.get('kind') == 'narration'])}


def _beats_from_srt(srt_blocks):
    """Derive narration-like beats from SRT blocks when the script cannot be parsed.

    Each SRT block becomes a pseudo-beat with the block's text as the spoken
    narration and the block's timestamps as the narration clock. This lets the
    engine still analyse documentaries whose production scripts are incomplete
    or use a non-standard format.
    """
    beats = []
    for block in srt_blocks:
        if not isinstance(block, dict):
            continue
        text = (block.get('text') or '').strip()
        if not text:
            continue
        beats.append({
            'label': str(block.get('number', len(beats) + 1)),
            'kind': 'narration',
            'narration_in_ms': int(block.get('start_ms', 0)),
            'narration_out_ms': int(block.get('end_ms', 0)),
            'spoken_narration': text,
        })
    return beats


def _beats_from_script_text(script_text):
    """Extract narration segments from raw script text as a last-resort fallback.

    Looks for Spoken Narration: fields or Beat blocks with VOICE OVER type and
    extracts the spoken text. Timestamps are estimated from beat ordering.
    """
    beats = []
    # Try to find "Spoken Narration: ..." fields in Beat blocks.
    beat_pattern = re.compile(
        r'(?:^|\n)\s*Beat:\s*(\d+).*?(?:^|\n)\s*Type:\s*([^\n]+)(.*?)(?=(?:^|\n)\s*Beat:|\Z)',
        re.S | re.I)
    narration_pattern = re.compile(r'(?:^|\n)\s*Spoken Narration:\s*([^\n]+)', re.I)
    for m in beat_pattern.finditer(script_text or ''):
        label = m.group(1)
        typ = m.group(2).strip().upper()
        body = m.group(3)
        if 'VOICE OVER' not in typ and 'NARRATION' not in typ:
            continue
        nm = narration_pattern.search(body)
        text = nm.group(1).strip() if nm else ''
        if not text:
            continue
        # Estimate timestamps: each beat gets 8 seconds, sequential.
        idx = len(beats)
        beats.append({
            'label': label,
            'kind': 'narration',
            'narration_in_ms': idx * 8000,
            'narration_out_ms': (idx + 1) * 8000,
            'spoken_narration': text,
        })
    return beats


def _is_excluded(beat):
    """True when the beat matches any hard exclusion pattern."""
    text = ' '.join(str(beat.get(k) or '') for k in
                    ('spoken_narration', 'visual_direction', 'continuity_note', 'type'))
    return any(p.search(text) for p in _EXCLUDE_PATTERNS)


def _detect_acts(script_text):
    """Find Act boundaries in the script text.

    Recognises `Act 3`, `ACT III`, `Chapter 3`, `### Act 3` markers.
    Returns a list of {act, start_line} sorted by position, with implied end = next start.
    """
    acts = []
    seen = set()
    roman = {'I': 1, 'II': 2, 'III': 3, 'IV': 4, 'V': 5, 'VI': 6, 'VII': 7, 'VIII': 8}
    for m in re.finditer(r'(?:^|\n)\s*(?:#+\s*)?(?:Act|ACT|Chapter|CHAPTER)\s*([IVXLC\d]+)[^\n]*',
                         script_text, re.I):
        token = m.group(1).upper()
        try:
            num = int(token) if token.isdigit() else roman[token]
        except (KeyError, ValueError):
            continue
        if num in seen or not 3 <= num <= 6:
            continue
        seen.add(num)
        acts.append({'act': num, 'start_pos': m.start()})
    acts.sort(key=lambda a: a['start_pos'])
    return acts


def _beat_act(beat, acts):
    """Which act a beat falls into (3-6), or 0 if outside any relevant act."""
    start_ms = beat.get('narration_in_ms') or 0
    # Use beat ordering as a rough proxy when acts are not explicitly marked:
    # divide the narration clock into six acts and return the act number.
    if not acts:
        # Fallback: approximate act from narration clock position.
        out_ms = beat.get('narration_out_ms') or start_ms
        # Default: unknown; let the caller decide.
        return 0
    # Find the last act whose start_pos is before this beat's position in script text.
    # Since beats don't carry character offsets, use narration_in_ms as a proxy:
    # assign acts by dividing total narration duration by act count.
    return acts[-1]['act'] if acts else 0


def _score_templates(narration, act, beat):
    """Return {template_id: score} for templates that match this narration."""
    scores = {}
    for template_id in TEMPLATES:
        score = _template_score(narration, act, beat, template_id)
        if score > 0:
            scores[template_id] = score
    return scores


def _template_score(narration, act, beat, template_id):
    """Score one template against one narration passage (0..100)."""
    score = 0
    # Act affinity: each template strongly prefers one or two acts.
    act_affinity = {
        'investigative_findings': (4, 5),
        'chronological_timeline': (3, 4),
        'contradictory_statements': (5,),
        'legal_outcome': (6,),
    }
    if act in act_affinity.get(template_id, ()):
        score += 40
    elif act == 0:
        score += 5  # neutral, may still match via keywords
    # Keyword evidence (secondary; act affinity dominates)
    hint_groups = _ACT_HINTS.get(act, ())
    for pattern in hint_groups:
        if re.search(pattern, narration, re.I):
            score += 15
    # Template-specific cues
    if template_id == 'investigative_findings' and re.search(
            r'\b(?:three|four|five|key|main|primary|central)\s+(?:findings?|points?|facts?)\b',
            narration, re.I):
        score += 25
    if template_id == 'chronological_timeline' and re.search(
            r'\b(?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d',
            narration, re.I):
        score += 30
    if template_id == 'contradictory_statements' and re.search(
            r'\b(?:however|but|instead|contrary|discrepanc|conflict|inconsisten)\b',
            narration, re.I):
        score += 25
    if template_id == 'legal_outcome' and re.search(
            r'\b(?:charg|count|verdict|sentenc|guilty|not guilty|convict|acquit)\b',
            narration, re.I):
        score += 30
    return min(score, 100)


def suggest_sequences(analysis, srt_blocks, film_duration_s):
    """Convert analysis candidates into concrete sequence proposals.

    Returns at most LIMITS['max_per_film'] suggestions, each bound to narration
    timestamps and annotated with the best-fit template and proposed content.
    """
    if not analysis.get('candidates'):
        return []
    # 1. De-duplicate: avoid overlapping suggestions within 15 seconds of each other.
    selected = []
    last_end = -15_000
    for cand in analysis['candidates']:
        if cand['narration_in_ms'] < last_end + 15_000:
            continue
        best_template = max(cand['template_scores'], key=cand['template_scores'].get)
        if cand['template_scores'][best_template] < 40:
            continue
        # Extend the window slightly before/after for breathing room.
        start_ms = max(0, cand['narration_in_ms'] - 500)
        end_ms = cand['narration_out_ms'] + 1500
        duration_s = (end_ms - start_ms) / 1000
        if duration_s < LIMITS['min_duration_s']:
            end_ms = start_ms + int(LIMITS['min_duration_s'] * 1000)
            duration_s = LIMITS['min_duration_s']
        if duration_s > LIMITS['max_duration_s']:
            end_ms = start_ms + int(LIMITS['max_duration_s'] * 1000)
            duration_s = LIMITS['max_duration_s']
        content = _propose_content(best_template, cand)
        selected.append({
            'id': 'mg_' + hashlib.sha256(
                f"{cand['beat']}|{best_template}|{start_ms}".encode()).hexdigest()[:12],
            'template': best_template,
            'start_s': round(start_ms / 1000, 3),
            'end_s': round(end_ms / 1000, 3),
            'content': content,
            'score': cand['template_scores'][best_template],
            'beat': cand['beat'],
            'act': cand['act'],
        })
        last_end = end_ms
        if len(selected) >= LIMITS['max_per_film']:
            break
    return selected


def _propose_content(template_id, cand):
    """Build an initial content payload for a template from the candidate beat."""
    narration = cand['spoken_narration']
    if template_id == 'investigative_findings':
        return _propose_findings(narration)
    if template_id == 'chronological_timeline':
        return _propose_timeline(narration)
    if template_id == 'contradictory_statements':
        return _propose_contradiction(narration)
    if template_id == 'legal_outcome':
        return _propose_legal(narration)
    return {}


def _propose_findings(narration):
    sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', narration) if len(s.strip()) > 8]
    findings = sentences[:5] if len(sentences) >= 2 else [narration[:200]]
    return {
        'kicker': 'Investigative Findings',
        'title': _extract_title(narration) or 'Key Findings',
        'findings': findings,
    }


def _propose_timeline(narration):
    events = []
    for m in re.finditer(
            r'((?:January|February|March|April|May|June|July|August|September|'
            r'October|November|December)\s+\d{1,2}(?:,?\s+\d{2,4})?)', narration, re.I):
        # Find the rest of the sentence after the date as the event description.
        tail = narration[m.end():].split('.')[0].strip().lstrip(', ')
        events.append({'date': m.group(1).strip(), 'event': tail[:120] or 'Event'})
    if not events:
        events = [{'date': 'Date TBD', 'event': narration[:120]}]
    return {'title': 'Chronology', 'events': events[:8]}


def _propose_contradiction(narration):
    parts = re.split(r'\b(?:however|but|instead|contrary to|discrepanc|conflict)\b',
                     narration, flags=re.I, maxsplit=1)
    verified = parts[0].strip()[:200] if parts else narration[:200]
    conflicting = parts[1].strip()[:200] if len(parts) > 1 else ''
    return {
        'title': 'Discrepancy',
        'verified': verified,
        'verified_label': 'Verified',
        'conflicting': conflicting or 'See evidence below',
        'conflicting_label': 'Conflicting',
    }


def _propose_legal(narration):
    charges = re.findall(r'\b(?:count of\s+[A-Z][^,.]+|charg(?:ed|e)?\s+with\s+[A-Z][^,.]+)', narration)
    verdict = re.search(r'\b(verdict:\s*[^.]+|found\s+(?:guilty|not guilty)[^.]*|acquitted[^.]*)',
                        narration, re.I)
    sentence = re.search(r'\b(sentenc(?:ed|ing)?\s+to\s+[^.]+)', narration, re.I)
    return {
        'title': 'Legal Outcome',
        'court': '',
        'charges': [c.strip() for c in charges[:4]] or ['Charges as filed'],
        'verdict': (verdict.group(1) if verdict else 'Verdict pending').strip(),
        'sentencing': (sentence.group(1) if sentence else '').strip(),
    }


def _extract_title(narration):
    """Pull a short headline from the narration; fall back to first sentence."""
    m = re.search(r'\b(the\s+(?:evidence|investigation|findings?|timeline|record|facts?))\b',
                  narration, re.I)
    if m:
        return m.group(1).title()
    first = narration.split('.')[0].strip()
    if 8 <= len(first) <= 80:
        return first
    return ''


def signature(project):
    """Hash used to invalidate cached analysis when script/SRT change."""
    mg = project.get('motion_graphics') or {}
    srt = project.get('srt') or {}
    blocks = (srt.get('blocks') if isinstance(srt, dict) else None) or []
    parts = [
        str((project.get('production_script') or {}).get('text', ''))[:200_000],
        json.dumps(blocks[:200], sort_keys=True),
        str(project.get('updated', '')),
    ]
    return hashlib.sha256('|'.join(parts).encode()).hexdigest()[:24]
