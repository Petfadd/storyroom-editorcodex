"""Stage timings for the performance audit, written as JSON lines.

Every stage of the pipeline (yt-dlp extraction and download, import, editing copies,
thumbnails, the Beat build, previews and the final render) records how long it took
here, so the slow stage is measured on the machine that is slow instead of guessed.

The log lives at perf_logs/stages.jsonl beside this file (override the folder with
STORYROOM_PERF_DIR). Writing it can never break the work being timed: every error is
swallowed. Set STORYROOM_PERF=0 to turn it off.
"""
from __future__ import annotations

import json
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path

_LOCK = threading.Lock()


def _path() -> Path:
    folder = os.environ.get('STORYROOM_PERF_DIR') or str(Path(__file__).resolve().parent / 'perf_logs')
    return Path(folder) / 'stages.jsonl'


def enabled() -> bool:
    return os.environ.get('STORYROOM_PERF', '1') != '0'


def record(stage: str, seconds: float, **fields) -> None:
    """Append one finished stage. `fields` must be JSON-serialisable (others are str()ed)."""
    if not enabled():
        return
    try:
        row = {'at': time.strftime('%Y-%m-%dT%H:%M:%S'), 'stage': stage, 'seconds': round(float(seconds), 3)}
        for key, value in fields.items():
            row[key] = value if isinstance(value, (int, float, str, bool, type(None), list, dict)) else str(value)
        line = json.dumps(row, ensure_ascii=False)
        path = _path()
        with _LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, 'a', encoding='utf-8') as fh:
                fh.write(line + '\n')
    except Exception:
        pass


@contextmanager
def timed(stage: str, **fields):
    """Time a block. Adds ok=False and the error type when the block raises."""
    began = time.monotonic()
    try:
        yield fields
    except BaseException as error:
        record(stage, time.monotonic() - began, ok=False, error=type(error).__name__, **fields)
        raise
    record(stage, time.monotonic() - began, ok=True, **fields)


class Steps:
    """Times consecutive named steps of one job: call `step(name)` at each boundary."""

    def __init__(self, prefix: str, **fields):
        self.prefix, self.fields = prefix, fields
        self.name, self.began = None, None

    def step(self, name: str) -> None:
        now = time.monotonic()
        if name == self.name:
            return
        if self.name is not None:
            record(f'{self.prefix}.{self.name}', now - self.began, **self.fields)
        self.name, self.began = name, now

    def close(self, **extra) -> None:
        if self.name is not None:
            record(f'{self.prefix}.{self.name}', time.monotonic() - self.began, **dict(self.fields, **extra))
        self.name = None
