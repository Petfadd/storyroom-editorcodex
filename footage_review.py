"""Read-only footage research against the project's original narration cues."""
import math
import re

from visual_plan import STOP


def terms(text):
    return {word for word in re.findall(r"[^\W_]+", text.casefold()) if len(word) > 1 and word not in STOP}


def candidates(report, blocks, cue, duration, offset=0):
    """Rank observed transcript intervals. Keep source and narration clocks separate."""
    if cue is not None and not 0 <= cue < len(blocks):
        raise ValueError("Choose a current narration cue.")
    transcript = report.get('stages', {}).get('transcript', {})
    if report.get('timing_warning') or transcript.get('status') != 'complete':
        raise ValueError("Complete local speech analysis with the current source before reviewing soundbites.")
    query = terms(blocks[cue]['text']) if cue is not None else None
    rows = []
    for item in transcript.get('result', {}).get('segments', []):
        start, end = item['start_s'], item['end_s']
        if not (0 <= start < end <= duration) or not item['text'].strip():
            continue
        words = terms(item['text'])
        shared = sorted(query & words) if query is not None else []
        if query is not None and not shared:
            continue
        score = len(shared) / math.sqrt(len(query) * len(words)) if shared else 0
        rows.append((score, {'in_ms': round(start*1000), 'out_ms': round(end*1000),
                             'text': item['text'], 'shared_words': shared}))
    rows.sort(key=lambda row: (-row[0], row[1]['in_ms']))
    return {'total': len(rows), 'offset': offset, 'items': [row for _, row in rows[offset:offset+25]],
            'cue': blocks[cue] if cue is not None else None}

