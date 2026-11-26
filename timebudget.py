"""How long one ffmpeg step may run, scaled to the length of the film being made.

A fixed ceiling (it used to be 30 minutes) is fine for an 8-minute film and fails a
20-minute one on a slower computer. Each render sets the film's length for its own
thread; every step then gets 30 minutes plus 12 seconds per second of film, which is
generous on any machine and still stops a step that has truly hung.
"""
import threading
from contextlib import contextmanager

_local = threading.local()
BASE_S = 1800
PER_FILM_SECOND = 12


def seconds():
    return getattr(_local, 'budget', BASE_S)


@contextmanager
def film_length(duration_s):
    """Within this block, ffmpeg steps on this thread get a budget for a film this long."""
    previous = getattr(_local, 'budget', None)
    try:
        _local.budget = max(seconds() if previous else BASE_S, BASE_S + PER_FILM_SECOND * max(0.0, float(duration_s or 0)))
        yield
    finally:
        if previous is None:
            del _local.budget
        else:
            _local.budget = previous
