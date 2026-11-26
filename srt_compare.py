"""Compare a replacement SRT with the one it replaces.

The production-script prompt delivers a second SRT with only the names and their
spelling corrected. Nothing else may change: the block numbers, every start and end
time, and every other word must be exactly as exported from the narration. This module
shows what really changed, so a timing or wording change made by the AI is caught at
upload instead of in the finished film.
"""
from __future__ import annotations

import difflib
import re
from collections import OrderedDict

_TOKEN = re.compile(r"[\w'’\-]+|[^\w\s]", re.UNICODE)
_WORD = re.compile(r"[\w'’\-]+", re.UNICODE)


def _tokens(text):
    return _TOKEN.findall(text or '')


def _is_name(words):
    """A changed phrase that is a name: every word starts with a capital letter."""
    ws = [w for w in words if _WORD.fullmatch(w)]
    return bool(ws) and all(w[:1].isupper() for w in ws)


def compare(old_blocks, new_blocks):
    """What changed from `old_blocks` to `new_blocks` (both parsed SRT block lists).

    Returns {
      'same_timing': True when the numbers and every start/end time are identical,
      'timing_changes': number of blocks whose number or times differ (or were added/removed),
      'name_changes': [{'before', 'after', 'blocks': [...]}]   -- capitalised words only,
      'other_changes': [{'before', 'after', 'blocks': [...]}]  -- any other wording,
    }
    """
    old_blocks, new_blocks = list(old_blocks or []), list(new_blocks or [])
    timing = abs(len(old_blocks) - len(new_blocks))
    names, other = OrderedDict(), OrderedDict()
    for a, b in zip(old_blocks, new_blocks):
        if (a['number'], a['start_ms'], a['end_ms']) != (b['number'], b['start_ms'], b['end_ms']):
            timing += 1
        if a['text'] == b['text']:
            continue
        ta, tb = _tokens(a['text']), _tokens(b['text'])
        matcher = difflib.SequenceMatcher(a=ta, b=tb, autojunk=False)
        for op, i1, i2, j1, j2 in matcher.get_opcodes():
            if op == 'equal':
                continue
            before, after = ' '.join(ta[i1:i2]), ' '.join(tb[j1:j2])
            if not before and not after:
                continue
            bucket = names if op == 'replace' and _is_name(ta[i1:i2]) and _is_name(tb[j1:j2]) else other
            entry = bucket.setdefault((before, after), [])
            if b['number'] not in entry:
                entry.append(b['number'])
        if not matcher.get_opcodes() or all(op == 'equal' for op, *_ in matcher.get_opcodes()):
            # Only spacing or line breaks differ.
            other.setdefault(('(line breaks or spacing)', '(changed)'), []).append(b['number'])

    def listed(bucket):
        return [{'before': k[0], 'after': k[1], 'blocks': v} for k, v in bucket.items()]

    return {'same_timing': timing == 0, 'timing_changes': timing,
            'name_changes': listed(names), 'other_changes': listed(other)}
