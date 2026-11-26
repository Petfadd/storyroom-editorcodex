"""Visual and editorial quality control for motion graphics recommendations.

Each candidate undergoes automated checks before being surfaced as a recommendation:
  1. Editorial QC — is the passage factually grounded, non-sensational, appropriate?
  2. Visual QC — will the proposed layout actually render well? (text length, density)
  3. Timing QC — is the duration long enough for readable animation?

QC is purely heuristic; no network, no AI inference. Every decision is explainable.
"""
from __future__ import annotations

import re


# ---------------------------------------------------------------- editorial QC

# Patterns that suggest a passage is too thin for a motion graphic.
_TOO_THIN = re.compile(r'^(?:yes|no|okay|right|exactly|sure|uh|um|hmm|well|so|and|but|then|or)$', re.I)

# Patterns suggesting unverified/sensational claims (editorial risk).
_UNVERIFIED = [
    re.compile(r'\b(?:allegedly|supposedly|reportedly|rumor(?:ed|s)?)\b', re.I),
    re.compile(r'\b(?:clearly|obviously|undoubtedly|absolutely)\s+(?:guilty|innocent|lying)', re.I),
]

# Patterns suggesting the passage is filler with no concrete information.
_FILLER = [
    re.compile(r'^(?:and|but|so|well|now|then|also)\s*$', re.I),
    re.compile(r'^(?:the end|that is all|thank you|thanks for watching)$', re.I),
]


def editorial_qc(text, context=''):
    """Return (pass: bool, reason: str).

    A passage fails editorial QC when it is too thin, unverified, or filler.
    Context is checked only for strong emotional content that would make
    a motion graphic inappropriate even if the block itself looks fine.
    """
    text = (text or '').strip()

    if not text:
        return False, 'No text content.'

    if len(text) < 8:
        return False, f'Too short ({len(text)} chars).'

    if _TOO_THIN.match(text):
        return False, 'Single conversational word; no visual value.'

    if any(p.search(text) for p in _FILLER):
        return False, 'Filler phrase; no informational content.'

    # Unverified claims are editorial risk — a motion graphic would imply
    # endorsement of the claim. Surface them only if the passage ALSO
    # contains concrete evidence terms.
    if any(p.search(text) for p in _UNVERIFIED):
        has_evidence = re.search(
            r'\b(?:evidence|document|record|verified|confirmed|proved|found)\b',
            text, re.I)
        if not has_evidence:
            return False, 'Unverified claim without corroborating evidence language.'

    # Context check: emotional surrounding content suggests this is not the
    # right moment for a graphic even if the block itself looks OK.
    emotional = re.search(
        r'\b(?:grief|mourning|weeping|devastated|heartbroken|tragic|funeral|memorial)\b',
        context, re.I)
    if emotional:
        return False, 'Surrounded by emotional content; preserve authentic footage.'

    return True, 'Passes editorial review.'


# ---------------------------------------------------------------- visual QC

def visual_qc(content, template_id, duration_s):
    """Return (pass: bool, reason: str).

    Checks whether the proposed content will render as a readable, well-composed
    graphic at the given duration.
    """
    if not isinstance(content, dict):
        return False, 'No content payload.'

    if duration_s < 3.0:
        return False, f'Duration too short ({duration_s:.1f}s) for readable animation.'

    # Check text volume against template capacity.
    if template_id == 'investigative_findings':
        findings = content.get('findings') or []
        if not findings:
            return False, 'No findings to display.'
        if len(findings) > 6:
            return False, f'Too many findings ({len(findings)}); truncate to 6.'
        long_findings = [f for f in findings if len(str(f)) > 200]
        if long_findings:
            return False, f'{len(long_findings)} finding(s) exceed 200 chars; will not render legibly.'

    elif template_id == 'chronological_timeline':
        events = content.get('events') or []
        if not events:
            return False, 'No events to display.'
        if len(events) > 8:
            return False, f'Too many events ({len(events)}); truncate to 8.'
        for ev in events:
            date = str(ev.get('date', '')).strip()
            event = str(ev.get('event', '')).strip()
            if not date and not event:
                return False, 'Empty date/event pair detected.'

    elif template_id == 'contradictory_statements':
        verified = (content.get('verified') or '').strip()
        conflicting = (content.get('conflicting') or '').strip()
        if not verified and not conflicting:
            return False, 'No content for either panel.'
        if len(verified) > 400:
            return False, f'Verified text too long ({len(verified)} chars).'
        if len(conflicting) > 400:
            return False, f'Conflicting text too long ({len(conflicting)} chars).'

    elif template_id == 'legal_outcome':
        charges = content.get('charges') or []
        verdict = (content.get('verdict') or '').strip()
        if not charges and not verdict:
            return False, 'No charges or verdict to display.'

    return True, 'Passes visual review.'


# ---------------------------------------------------------------- timing QC

def timing_qc(start_s, end_s, film_duration_s):
    """Return (pass: bool, reason: str).

    Checks that the proposed time range is within bounds and leaves
    enough room for the full animation to complete.
    """
    if start_s < 0:
        return False, f'Start before film begin ({start_s:.1f}s).'
    if end_s <= start_s:
        return False, f'End ({end_s:.1f}s) not after start ({start_s:.1f}s).'
    if end_s > film_duration_s + 1.0:
        return False, f'End ({end_s:.1f}s) exceeds film duration ({film_duration_s:.1f}s).'
    duration = end_s - start_s
    if duration < 3.0:
        return False, f'Duration too short ({duration:.1f}s).'
    if duration > 45.0:
        return False, f'Duration too long ({duration:.1f}s).'
    return True, 'Passes timing review.'


# ---------------------------------------------------------------- combined

def full_qc(text, content, template_id, start_s, end_s, film_duration_s, context=''):
    """Run all three QC checks. Return dict with pass/fail per check and overall."""
    editorial_pass, editorial_reason = editorial_qc(text, context)
    visual_pass, visual_reason = visual_qc(content, template_id, end_s - start_s)
    timing_pass, timing_reason = timing_qc(start_s, end_s, film_duration_s)

    overall = editorial_pass and visual_pass and timing_pass
    reasons = []
    if not editorial_pass:
        reasons.append(f'Editorial: {editorial_reason}')
    if not visual_pass:
        reasons.append(f'Visual: {visual_reason}')
    if not timing_pass:
        reasons.append(f'Timing: {timing_reason}')

    return {
        'pass': overall,
        'editorial': editorial_pass,
        'editorial_reason': editorial_reason,
        'visual': visual_pass,
        'visual_reason': visual_reason,
        'timing': timing_pass,
        'timing_reason': timing_reason,
        'reasons': reasons,
    }
