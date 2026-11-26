"""Windows: retry a file replace that hits a momentary lock.

The editor saves files safely by writing a temporary copy and swapping it into place.
On Windows that swap fails with "Access is denied" (WinError 5/32) if anything has
the target open at that instant -- antivirus scanning it, an indexer, or the browser's
progress poll reading it. The lock lasts milliseconds, so the swap is retried for up to
about three seconds before the error is reported. Other systems are unaffected.
"""
import os
import sys
import time

# Keep the real function even if this module is loaded twice.
_original = getattr(os, '_storyroom_original_replace', os.replace)
os._storyroom_original_replace = _original


def _replace_with_retry(src, dst, *args, **kwargs):
    delay = 0.02
    deadline = time.monotonic() + 3.0
    while True:
        try:
            return _original(src, dst, *args, **kwargs)
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(delay)
            delay = min(0.25, delay * 2)


def install():
    if sys.platform == 'win32' and getattr(os.replace, '__name__', '') != '_replace_with_retry':
        os.replace = _replace_with_retry


install()
