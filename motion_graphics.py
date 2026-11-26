"""Intelligent Cinematic Motion Graphics Engine.

Non-destructive kinetic typography layer for investigative documentaries. The engine
reads the narration SRT and production script, understands narrative context, and
proposes narration-synchronised motion graphics sequences where they genuinely
improve storytelling.

Four context-aware templates (Investigative Findings, Chronological Timeline,
Contradictory Statements, Legal Outcome) produce genuinely animated per-frame
renders driven by Pillow, composited into the film by FFmpeg as a separate
overlay layer.

No Acts or chapters are required. The engine analyses the narration itself.

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
import math
import re
from pathlib import Path
from typing import Iterable

VERSION = 2
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
    'min_spacing_s': 20.0,         # minimum gap between recommendations
}

# -------------------------------------------------------------------- exclusions
# Passages whose purpose makes a motion graphic inappropriate. Only the block's
# OWN text is checked (not surrounding context). Patterns are specific enough
# to avoid excluding ordinary documentary narration.

_EXCLUSION_PATTERNS = [
    # Cold opens / teasers
    re.compile(r'\b(?:cold open|teaser)\b', re.I),
    # Victim / family emotional content (specific phrases)
    re.compile(r'\b(?:victim(?:\'s)? (?:mother|father|sister|brother|daughter|son|family|loved))\b', re.I),
    re.compile(r'\b(?:family (?:interview|statement|tribute|grief|mourning))\b', re.I),
    re.compile(r'\b(?:in loving memory|remembering|tribute|memorial)\b', re.I),
    # Strong emotional language (specific words only)
    re.compile(r'\b(?:heart-?wrenching|devastat(?:ing|ed)|griev(?:ing|ed))\b', re.I),
    # Witness testimony (authentic footage should remain)
    re.compile(r'\b(?:witness (?:testif|statement|account|describ))\b', re.I),
    # Police / official briefings
    re.compile(r'\b(?:police (?:briefing|report|press|statement|chief))\b', re.I),
    # Courtroom soundbites
    re.compile(r'\b(?:courtroom (?:sound|audio|recording|gavel))\b', re.I),
    # CTA sequences
    re.compile(r'\b(?:subscribe|like and (?:share|comment)|hit the bell|call to action)\b', re.I),
    # Emotional closings (specific phrases)
    re.compile(r'\b(?:in closing|final thoughts|thank you for watch)\b', re.I),
]


# -------------------------------------------------------------------- settings

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
    if 'reason' in seq and isinstance(seq['reason'], str):
        out['reason'] = seq['reason']
    if 'reveal_timings' in seq and isinstance(seq['reveal_timings'], dict):
        out['reveal_timings'] = seq['reveal_timings']
    return out


# ---------------------------------------------------------------- text analysis

# Each function below returns a score 0..100. The total is the weighted sum.

_MONTHS = ('january|february|march|april|may|june|july|august|september|'
           'october|november|december')

def _is_excluded(text, context=''):
    """True when the block's OWN text matches an exclusion pattern.

    Context is NOT checked here: a block about a contradiction that happens to
    sit next to emotional content should still be eligible for a graphic. The
    surrounding context is used only for scoring, never for exclusion.
    """
    return any(p.search(text) for p in _EXCLUSION_PATTERNS)


def _count_dates(text):
    """Count distinct date references (month + year, or full date)."""
    return len(re.findall(
        rf'(?:{_MONTHS})\s+\d{{1,2}}(?:,?\s+\d{{2,4}})?', text, re.I))


def _count_facts(text):
    """Count distinct factual statements (sentences with concrete content)."""
    sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', text) if s.strip()]
    concrete = [s for s in sentences
                if re.search(r'\b(?:was|were|is|are|had|has|found|showed|revealed|'
                             r'uncovered|identified|reported|stated|charged|testified)\b',
                             s, re.I)]
    return len(concrete)


def _count_names(text):
    """Count capitalised multi-word names (people, places, organisations)."""
    return len(re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b', text))


def _count_legal_terms(text):
    """Count legal-domain terms."""
    return len(re.findall(
        r'\b(?:court|judge|jury|verdict|guilty|not guilty|charges?|indict(?:ment|ed)|'
        r'sentenc(?:e|ed|ing)?|convict(?:ion|ed)?|acquit(?:ted|tal)?|plea(?:d|s)?|'
        r'trial|prosecut(?:ion|or)?|defen[cs]e|defendant|attorney|lawyer|'
        r'warrant|arrest|bail|parole|probation|appeal)\b', text, re.I))


def _count_evidence_terms(text):
    """Count investigation / evidence terms."""
    return len(re.findall(
        r'\b(?:evidence|finding|clue|fact|proof|forensic|dna|fingerprint|'
        r'witness|suspect|detective|investigat(?:ion|or|ed)?|uncover(?:ed|s)?|'
        r'reveal(?:ed|s)?|discover(?:ed|y)?|examined|analys(?:ed|is)|'
        r'phone (?:records?|data|calls?)|surveillance|footage|video|audio|'
        r'document(?:ed|s)?|records?|statements?|reports?)\b', text, re.I))


def _count_timeline_terms(text):
    """Count time-sequence markers."""
    return len(re.findall(
        r'\b(?:then|after(?:wards)?|before|following|subsequently|later|'
        r'earlier|prior to|next|meanwhile|in the (?:meantime|aftermath)|'
        r'days? later|weeks? later|months? later|years? later|'
        r'(?:morning|afternoon|evening|night|midnight))\b', text, re.I))


def _count_contrast_terms(text):
    """Count contrast / contradiction markers."""
    return len(re.findall(
        r'\b(?:however|but|yet|nevertheless|instead|on the other hand|'
        r'contrary (?:to|)|discrepanc(?:y|ies)?|conflict(?:ing)?|'
        r'inconsisten(?:t|cy|cies)?|did.?not match|did not agree|'
        r'although|despite|even though|nonetheless|whereas)\b', text, re.I))


def _count_enumeration(text):
    """Count enumerated items (first/second/third..., 'several pieces')."""
    enumerations = len(re.findall(
        r'\b(?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|'
        r'one|two|three|four|five|six|seven|eight|nine|ten)\s+'
        r'(?:finding|piece|fact|evidence|item|clue|statement|count|charge|'
        r'witness|person|element|detail|point)\b', text, re.I))
    # Also detect "several", "multiple" + noun
    enumerations += len(re.findall(
        r'\b(?:several|multiple|a number of|many)\s+'
        r'(?:pieces?|items?|facts?|findings?|evidence|elements?|clues?)\b',
        text, re.I))
    return enumerations


def _information_density(text):
    """How information-rich is this block? 0..1 normalised."""
    dates = _count_dates(text)
    facts = _count_facts(text)
    names = _count_names(text)
    nums = len(re.findall(r'\b\d+(?:st|nd|rd|th)?\b', text))
    clauses = text.count(',') + text.count(';') + len(re.findall(r'\band\b|\bor\b', text, re.I))
    words = len(text.split())
    if words < 5:
        return 0.0
    raw = dates * 3 + facts * 2 + names * 2 + nums * 1.5 + clauses * 0.5
    return min(1.0, raw / max(10, words * 0.25))


def _is_emotional_or_generic(text):
    """True when a block reads as filler or pure emotion with no concrete facts."""
    emotional = re.search(
        r'\b(?:sad|happy|angry|upset|crying|tears|joy|sorrow|grief|'
        r'difficult|hard|tough|challenging|beautiful|wonderful|amazing|'
        r'incredible|unbelievable|shocking|surprising)\b', text, re.I)
    generic = re.search(
        r'^(?:the (?:story|case|investigation) (?:of|about|began|continues|'
        r'went on|unfolded|developed)|it was (?:a|the)|this is (?:the|a)|'
        r'(?:everyone|people|they) (?:know|knew|said|felt|thought))\b',
        text, re.I)
    return bool(emotional or generic)


# ------------------------------------------------------- per-template scoring

def _score_findings(text, context):
    """Score Investigative Findings template fit."""
    score = 0
    enumerations = _count_enumeration(text)
    evidence_terms = _count_evidence_terms(text)
    facts = _count_facts(text)
    info_density = _information_density(text)

    # Strong signal: enumerated findings (3+ items listed)
    if enumerations >= 3:
        score += 60
    elif enumerations == 2:
        score += 40
    elif enumerations == 1:
        score += 20

    # Medium signal: multiple concrete facts in one block
    if facts >= 3:
        score += 25
    elif facts >= 2:
        score += 15

    # Context signal: surrounded by investigation content
    if re.search(
        r'\b(?:investigation|detective|evidence|finding|clue|suspect|'
        r'uncovered|discovered|revealed|examined)\b', context, re.I):
        score += 15

    # Information density boost
    if info_density >= 0.6:
        score += 10

    # Penalty: emotional or generic language
    if _is_emotional_or_generic(text):
        score = score // 3

    return min(score, 100)


def _score_timeline(text, context):
    """Score Chronological Timeline template fit."""
    score = 0
    dates = _count_dates(text)
    timeline_markers = _count_timeline_terms(text)

    # Strong signal: multiple dates in one block
    if dates >= 3:
        score += 70
    elif dates == 2:
        score += 55
    elif dates == 1:
        score += 25

    # Medium signal: time-sequence markers
    if timeline_markers >= 3:
        score += 25
    elif timeline_markers >= 2:
        score += 15
    elif timeline_markers == 1:
        score += 5

    # Context: surrounded by chronological content
    if re.search(
        r'\b(?:timeline|chronolog|sequence|progression|series of events|'
        r'(?:january|february|march|april|may|june|july|august|september|'
        r'october|november|december))\b', context, re.I):
        score += 10

    # Penalty: emotional or generic language
    if _is_emotional_or_generic(text):
        score = score // 3

    return min(score, 100)


def _score_contradiction(text, context):
    """Score Contradictory Statements template fit."""
    score = 0
    contrast_markers = _count_contrast_terms(text)

    # Strong signal: contrast marker present
    if contrast_markers >= 1:
        score += 40

    # Medium signal: both a claim and a counter-claim present
    claim = re.search(
        r'\b(?:report(?:ed|s)?|stated?|claimed?|testified|said|alleged|'
        r'asserted|declared|official|officials?)\b', text, re.I)
    counter = re.search(
        r'\b(?:however|but|instead|contrary|discrepanc|conflict|inconsisten|'
        r'otherwise|did not|didn\'t|failed to|not|no)\b', text, re.I)
    if claim and counter:
        score += 30

    # Context: previous blocks make claims that this block refutes
    if re.search(
        r'\b(?:report(?:ed|s)?|stated?|claimed?|testified|said)\b',
        context, re.I):
        score += 15

    # Information density boost (complex contradiction)
    if _information_density(text) >= 0.5:
        score += 10

    # Penalty: emotional or generic language
    if _is_emotional_or_generic(text):
        score = score // 3

    return min(score, 100)


def _score_legal(text, context):
    """Score Legal Outcome template fit."""
    score = 0
    legal_terms = _count_legal_terms(text)

    # Strong signal: multiple legal terms (full legal passage)
    if legal_terms >= 4:
        score += 60
    elif legal_terms >= 3:
        score += 45
    elif legal_terms >= 2:
        score += 30
    elif legal_terms == 1:
        score += 15

    # Specific legal concepts carry extra weight
    if re.search(r'\b(?:verdict|guilty|not guilty|acquitted?|convict(?:ed|ion))\b', text, re.I):
        score += 15
    if re.search(r'\b(?:sentenc(?:e|ed|ing)?|years? (?:in|of)|prison|jail|'
                 r'life (?:in|sentence)|death (?:penalty|sentence))\b', text, re.I):
        score += 15
    if re.search(r'\b(?:charg(?:es?|ed|ing)|indict(?:ment|ed)|count (?:of|one|two|three))\b', text, re.I):
        score += 10

    # Context: surrounded by legal content
    if re.search(
        r'\b(?:court|judge|jury|verdict|trial|prosecut|defen[cs]e|'
        r'attorney|lawyer|charges?|sentenc)\b', context, re.I):
        score += 10

    # Penalty: emotional or generic language
    if _is_emotional_or_generic(text):
        score = score // 3

    return min(score, 100)


_SCORERS = {
    'investigative_findings': _score_findings,
    'chronological_timeline': _score_timeline,
    'contradictory_statements': _score_contradiction,
    'legal_outcome': _score_legal,
}


def _build_context(blocks, index, window=2):
    """Return the text of up to `window` blocks on each side of index."""
    start = max(0, index - window)
    end = min(len(blocks), index + window + 1)
    return ' '.join(
        (blocks[i].get('text') or blocks[i].get('spoken_narration') or '')
        for i in range(start, end)
        if i != index
    )


# ------------------------------------------------------------- main analysis

def analyse_script(script_text, srt_blocks):
    """Read the full SRT and script; return structured context for placement.

    No Acts or chapters required. The engine analyses narration context directly.
    """
    script_text = script_text or ''
    blocks = list(srt_blocks or [])

    # Also try to extract narration from a script text when no SRT is provided.
    if not blocks:
        blocks = _beats_from_script_text(script_text)

    candidates = []
    excluded = []

    for i, block in enumerate(blocks):
        text = (block.get('text') or block.get('spoken_narration') or '').strip()
        if not text:
            continue
        context = _build_context(blocks, i, window=2)
        combined = text + ' ' + context

        # Hard exclusions
        if _is_excluded(text, context):
            excluded.append({
                'reason': 'excluded_passage',
                'index': i,
                'start_ms': int(block.get('start_ms', 0)),
                'end_ms': int(block.get('end_ms', 0)),
                'text': text[:80],
            })
            continue

        # Per-template scoring
        scores = {}
        for template_id, scorer in _SCORERS.items():
            s = scorer(text, context)
            if s > 0:
                scores[template_id] = s

        if not scores:
            continue

        best_template = max(scores, key=scores.get)
        candidates.append({
            'index': i,
            'text': text,
            'start_ms': int(block.get('start_ms', 0)),
            'end_ms': int(block.get('end_ms', 0)),
            'template_scores': scores,
            'best_template': best_template,
            'best_score': scores[best_template],
            'information_density': _information_density(text),
        })

    # Sort by best score descending, breaking ties by information density.
    candidates.sort(key=lambda c: (-c['best_score'], -c['information_density']))

    return {
        'candidates': candidates[:30],
        'excluded': excluded[:20],
        'blocks_total': len(blocks),
        'narration_blocks': len([b for b in blocks if (b.get('text') or b.get('spoken_narration') or '').strip()]),
    }


def _beats_from_script_text(script_text):
    """Extract narration segments from raw script text as a last-resort fallback."""
    blocks = []
    beat_pattern = re.compile(
        r'(?:^|\n)\s*Beat:\s*(\d+).*?(?:^|\n)\s*Type:\s*([^\n]+)(.*?)(?=(?:^|\n)\s*Beat:|\Z)',
        re.S | re.I)
    narration_pattern = re.compile(r'(?:^|\n)\s*(?:Spoken Narration|Narration):\s*([^\n]+)', re.I)
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
        idx = len(blocks)
        blocks.append({
            'number': int(label),
            'start_ms': idx * 8000,
            'end_ms': (idx + 1) * 8000,
            'text': text,
        })
    return blocks


# --------------------------------------------------------- proposal generation

def _extract_findings(text):
    """Pull individual findings from a block of text."""
    findings = []
    # Pattern: "The Nth was..." or "N: ..." or short declarative sentences
    for m in re.finditer(
            r'(?:the\s+(?:first|second|third|fourth|fifth|sixth)\s+(?:was|is|showed|revealed|found)\s+)?'
            r'((?:a|an|the|one)\s+[^.]{8,120})', text, re.I):
        findings.append(m.group(1).strip().rstrip('.'))
    # Fallback: split by sentences, keep concrete ones
    if not findings:
        sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', text)
                     if len(s.strip()) > 8
                     and re.search(r'\b(?:was|were|found|showed|revealed|had|has)\b', s, re.I)]
        findings = sentences[:5]
    return findings[:6] or [text[:200]]


def _extract_events(text):
    """Pull date+event pairs from a block of text."""
    events = []
    for m in re.finditer(
            rf'(({_MONTHS})\s+\d{{1,2}}(?:,?\s+\d{{2,4}})?)\s*[,.]?\s*(.*?)(?=(?:{_MONTHS})\s+\d|\.|;|$)',
            text, re.I):
        date_part = m.group(1).strip()
        event_part = m.group(3).strip().rstrip('.,')
        if event_part and len(event_part) > 5:
            events.append({'date': date_part, 'event': event_part[:140]})
    if not events:
        events = [{'date': 'Date TBD', 'event': text[:120]}]
    return events[:8]


def _extract_contradiction(text):
    """Split a contradiction block into verified vs conflicting parts."""
    contrast_markers = re.compile(
        r'\b(?:however|but|yet|nevertheless|instead|contrary to|'
        r'although|despite|on the other hand)\b', re.I)
    parts = contrast_markers.split(text, maxsplit=1)
    verified = parts[0].strip()[:240] if parts else text[:240]
    conflicting = parts[1].strip()[:240] if len(parts) > 1 else ''
    return verified, conflicting


def _extract_legal(text):
    """Pull charges, verdict, sentencing from a block of text."""
    charges = re.findall(
        r'\b(?:count (?:of|one|two|three|four|five)\s+[^.]{5,80}|'
        r'charg(?:ed|e)?\s+(?:with\s+)?[^.]{5,80})', text, re.I)
    verdict_m = re.search(
        r'\b(?:verdict:\s*[^.]+|found\s+(?:guilty|not guilty)[^.]*|'
        r'acquitted[^.]*)', text, re.I)
    sentence_m = re.search(
        r'\b(sentenc(?:ed|ing)?\s+(?:to\s+)?[^.]+)', text, re.I)
    court_m = re.search(
        r'\b((?:[A-Z][a-z]+\s+)?(?:County|District|Circuit|Supreme|Federal|'
        r'Appellate|Superior)\s+(?:Court|Tribunal))\b', text)
    return {
        'court': (court_m.group(1) if court_m else ''),
        'charges': [c.strip().rstrip('.') for c in charges[:5]] or ['Charges as filed'],
        'verdict': (verdict_m.group(1) if verdict_m else '').strip(),
        'sentencing': (sentence_m.group(1) if sentence_m else '').strip(),
    }


def _compute_reveal_timings(template_id, content, duration_s):
    """Generate per-element reveal timings for a sequence."""
    timings = {'elements': []}
    t = 0.0
    if template_id == 'investigative_findings':
        timings['elements'].append({'id': 'kicker', 'at_s': 0.0, 'dur_s': 0.45})
        t = 0.45
        timings['elements'].append({'id': 'title', 'at_s': t, 'dur_s': 0.55})
        t += 0.45
        timings['elements'].append({'id': 'divider', 'at_s': t, 'dur_s': 0.55})
        t += 0.35
        findings = content.get('findings') or []
        per = max(0.6, (duration_s - t - 1.0) / max(1, len(findings)))
        for i in range(len(findings)):
            timings['elements'].append({'id': f'finding_{i}', 'at_s': t, 'dur_s': per})
            t += per
    elif template_id == 'chronological_timeline':
        timings['elements'].append({'id': 'kicker', 'at_s': 0.0, 'dur_s': 0.45})
        t = 0.40
        timings['elements'].append({'id': 'timeline_line', 'at_s': t, 'dur_s': duration_s * 0.75})
        events = content.get('events') or []
        per = max(0.8, (duration_s - t - 1.0) / max(1, len(events)))
        for i in range(len(events)):
            timings['elements'].append({'id': f'event_{i}_date', 'at_s': t + 0.1, 'dur_s': 0.4})
            timings['elements'].append({'id': f'event_{i}_desc', 'at_s': t + 0.35, 'dur_s': 0.5})
            t += per
    elif template_id == 'contradictory_statements':
        timings['elements'].append({'id': 'kicker', 'at_s': 0.0, 'dur_s': 0.45})
        t = 0.35
        timings['elements'].append({'id': 'verified_label', 'at_s': t, 'dur_s': 0.4})
        timings['elements'].append({'id': 'verified_body', 'at_s': t + 0.15, 'dur_s': 0.6})
        t += 1.0
        timings['elements'].append({'id': 'divider', 'at_s': t, 'dur_s': 0.55})
        t += 0.40
        timings['elements'].append({'id': 'conflicting_label', 'at_s': t, 'dur_s': 0.4})
        timings['elements'].append({'id': 'conflicting_body', 'at_s': t + 0.15, 'dur_s': 0.6})
    elif template_id == 'legal_outcome':
        timings['elements'].append({'id': 'kicker', 'at_s': 0.0, 'dur_s': 0.45})
        t = 0.30
        timings['elements'].append({'id': 'charges_label', 'at_s': t, 'dur_s': 0.4})
        t += 0.30
        charges = content.get('charges') or []
        per = max(0.4, (duration_s - t - 3.0) / max(1, len(charges) + 2))
        for i in range(len(charges)):
            timings['elements'].append({'id': f'charge_{i}', 'at_s': t, 'dur_s': per})
            t += per
        timings['elements'].append({'id': 'verdict_divider', 'at_s': t, 'dur_s': 0.5})
        t += 0.35
        timings['elements'].append({'id': 'verdict', 'at_s': t + 0.15, 'dur_s': 0.55})
        t += 0.60
        if content.get('sentencing'):
            timings['elements'].append({'id': 'sentencing', 'at_s': t + 0.15, 'dur_s': 0.5})
    return timings


def _build_reason(template_id, cand):
    """Human-readable reason why this block was recommended."""
    text = cand['text']
    density = cand.get('information_density', 0)
    scores = cand['template_scores']
    reasons = []
    if template_id == 'investigative_findings':
        if _count_enumeration(text) >= 2:
            reasons.append(f'block enumerates {_count_enumeration(text)} evidence items that benefit from structured visual presentation')
        if _count_facts(text) >= 3:
            reasons.append(f'contains {_count_facts(text)} concrete factual statements')
        if density >= 0.5:
            reasons.append('high information density rewards visual organisation')
    elif template_id == 'chronological_timeline':
        dates = _count_dates(text)
        if dates >= 2:
            reasons.append(f'presents {dates} distinct dates that a timeline clarifies for the viewer')
        if _count_timeline_terms(text) >= 2:
            reasons.append('sequential time markers benefit from a visual chronology')
    elif template_id == 'contradictory_statements':
        if _count_contrast_terms(text) >= 1:
            reasons.append('explicit contrast marker signals two competing claims')
        claim = bool(re.search(r'\b(?:report|stated|claimed|testified|said)\b', text, re.I))
        counter = bool(re.search(r'\b(?:however|but|instead|contrary|discrepanc)\b', text, re.I))
        if claim and counter:
            reasons.append('contains both a claim and a counter-claim, ideal for side-by-side display')
    elif template_id == 'legal_outcome':
        lt = _count_legal_terms(text)
        if lt >= 3:
            reasons.append(f'legal passage with {lt} legal-domain terms warrants structured presentation')
        if re.search(r'\b(?:verdict|guilty|not guilty)\b', text, re.I):
            reasons.append('verdict language carries high documentary significance')
    if not reasons:
        reasons.append('narration passage fits the selected template context')
    return '. '.join(reasons).capitalize() + '.'


def _propose_content(template_id, text):
    """Build content payload for a template from the block text."""
    if template_id == 'investigative_findings':
        findings = _extract_findings(text)
        title = 'Key Findings'
        m = re.search(r'(?:the|a)\s+([a-z ]{4,30})\s+(?:was|were|is|are|showed)', text, re.I)
        if m:
            title = m.group(1).strip().title()[:60] or 'Key Findings'
        return {
            'kicker': 'Investigative Findings',
            'title': title,
            'findings': findings,
        }
    if template_id == 'chronological_timeline':
        return {'title': 'Chronology', 'events': _extract_events(text)}
    if template_id == 'contradictory_statements':
        v, c = _extract_contradiction(text)
        return {
            'title': 'Discrepancy',
            'verified': v,
            'verified_label': 'Verified',
            'conflicting': c or 'See evidence below',
            'conflicting_label': 'Conflicting',
        }
    if template_id == 'legal_outcome':
        return {'title': 'Legal Outcome', **_extract_legal(text)}
    return {}


# ----------------------------------------------------------- suggestions

def suggest_sequences(analysis, srt_blocks, film_duration_s):
    """Convert analysis candidates into concrete recommendations.

    For each template, picks the BEST candidate (highest per-template score),
    not the first one that happens to have a non-zero score. Templates whose
    best candidate scores below MIN_TEMPLATE_SCORE are skipped.
    """
    candidates = analysis.get('candidates') or []
    if not candidates:
        return []

    # Minimum per-template score to warrant a recommendation. Lower than this
    # means the block has only weak keyword matches and does not genuinely
    # benefit from a motion graphic.
    MIN_TEMPLATE_SCORE = 30

    # Pass 1: pick the BEST candidate for each template independently.
    picked = []
    seen_indices = set()
    for template_id in TEMPLATES:
        best_for_t = None
        best_score = 0
        for cand in candidates:
            s = cand['template_scores'].get(template_id, 0)
            if s > best_score and cand['index'] not in seen_indices:
                best_score = s
                best_for_t = cand
        if best_for_t and best_score >= MIN_TEMPLATE_SCORE:
            picked.append((template_id, best_for_t, best_score))
            seen_indices.add(best_for_t['index'])

    # Pass 2: fill remaining slots with the best-of-rest (any template).
    # Ensures we get 2-5 diverse recommendations even when one template has
    # no strong candidates.
    for cand in candidates:
        if len(picked) >= LIMITS['max_per_film']:
            break
        if cand['index'] in seen_indices:
            continue
        best_t = cand.get('best_template')
        best_s = cand.get('best_score', 0)
        if not best_t or best_s < MIN_TEMPLATE_SCORE:
            continue
        picked.append((best_t, cand, best_s))
        seen_indices.add(cand['index'])

    # Sort picked chronologically, then space them out by min_spacing_s.
    picked.sort(key=lambda x: x[1]['start_ms'])
    selected = []
    last_end = -LIMITS['min_spacing_s']
    for template_id, cand, score in picked:
        start_ms = cand['start_ms']
        end_ms = cand['end_ms']
        if start_ms < last_end + LIMITS['min_spacing_s'] * 1000:
            continue
        duration_s = max(LIMITS['min_duration_s'],
                         min(LIMITS['max_duration_s'], (end_ms - start_ms) / 1000 + 2.0))
        start_s = max(0.0, start_ms / 1000 - 0.5)
        end_s = start_s + duration_s
        content = _propose_content(template_id, cand['text'])
        reveal_timings = _compute_reveal_timings(template_id, content, duration_s)
        reason = _build_reason(template_id, cand)
        selected.append({
            'id': 'mg_' + hashlib.sha256(
                f"{cand['index']}|{template_id}|{start_ms}".encode()).hexdigest()[:12],
            'template': template_id,
            'start_s': round(start_s, 3),
            'end_s': round(end_s, 3),
            'content': content,
            'score': score,
            'information_density': cand.get('information_density', 0),
            'reason': reason,
            'narration_passage': cand['text'],
            'reveal_timings': reveal_timings,
        })
        last_end = end_s * 1000

    return selected


# ---------------------------------------------------------------- signature

def signature(project):
    """Hash used to invalidate cached analysis when script/SRT change."""
    srt = project.get('srt') or {}
    blocks = (srt.get('blocks') if isinstance(srt, dict) else None) or []
    parts = [
        str((project.get('production_script') or {}).get('text', ''))[:200_000],
        json.dumps(blocks[:200], sort_keys=True, default=str),
        str(project.get('updated', '')),
    ]
    return hashlib.sha256('|'.join(parts).encode()).hexdigest()[:24]
