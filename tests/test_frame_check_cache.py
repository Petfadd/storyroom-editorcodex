import sys, tempfile, types, unittest
from fractions import Fraction
from pathlib import Path

import cache
import strict_cuts


class _Frame:
    def __init__(self, n):
        self.pts = n
        self.time_base = Fraction(1, 30)


class _Stream:
    def __init__(self):
        self.base_rate = Fraction(30)
        self.average_rate = Fraction(30)
        self.time_base = Fraction(1, 30)
        self.codec_context = types.SimpleNamespace(thread_type='SLICE', thread_count=1)


class _Container:
    def __init__(self, counter):
        self.counter = counter
        self.streams = types.SimpleNamespace(video=[_Stream()])

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def decode(self, stream):
        self.counter['opened'] += 1
        self.counter['thread_type'] = stream.codec_context.thread_type
        self.counter['threads'] = stream.codec_context.thread_count
        for n in range(300):
            self.counter['decoded'] += 1
            yield _Frame(n)


class FrameCheckCacheTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.video = Path(self.tmp.name) / 'S01.mp4'
        self.video.write_bytes(b'not really a video')
        self.counter = {'opened': 0, 'decoded': 0, 'thread_type': None}
        fake = types.ModuleType('av')
        fake.open = lambda path: _Container(self.counter)
        self.saved_av = sys.modules.get('av')
        sys.modules['av'] = fake
        store = cache.Store(Path(self.tmp.name) / 'cache')
        self.saved_store = strict_cuts.disk_store
        strict_cuts.disk_store = lambda: store
        strict_cuts._cache.clear()

    def tearDown(self):
        if self.saved_av is not None:
            sys.modules['av'] = self.saved_av
        else:
            sys.modules.pop('av', None)
        strict_cuts.disk_store = self.saved_store
        strict_cuts._cache.clear()
        self.tmp.cleanup()

    def test_result_survives_a_restart_and_decoding_uses_all_cores(self):
        first = strict_cuts.inspect_video(self.video, 200)
        self.assertEqual(first['frames'], 300)          # a margin past what was asked (file ends at 300)
        self.assertEqual(self.counter['thread_type'], 'AUTO')
        import os
        self.assertLessEqual(self.counter['threads'], max(1, (os.cpu_count() or 2) // 2))   # never every core
        self.assertLessEqual(self.counter['threads'], 4)
        strict_cuts._cache.clear()                       # what an app restart does
        again = strict_cuts.inspect_video(self.video, 150)
        self.assertEqual((again['frames'], again['fps']), (300, Fraction(30)))
        self.assertEqual(self.counter['opened'], 1)      # not decoded a second time

    def test_a_changed_file_or_a_longer_check_decodes_again(self):
        strict_cuts.inspect_video(self.video, 100)       # checks to 400 or the end (300)
        strict_cuts._cache.clear()
        strict_cuts.inspect_video(self.video, 101)       # one frame more: answered from the margin
        self.assertEqual(self.counter['opened'], 1)
        with self.assertRaises(ValueError):
            strict_cuts.inspect_video(self.video, 350)   # past the end of the file: still refused
        self.video.write_bytes(b'replaced with another file')
        strict_cuts._cache.clear()
        strict_cuts.inspect_video(self.video, 50)
        self.assertEqual(self.counter['opened'], 3)


if __name__ == '__main__':
    unittest.main()
