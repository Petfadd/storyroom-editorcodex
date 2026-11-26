"""The review preview audio is quick to build and starts by itself."""
import shutil
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path

try:
    import documentary_audio as da
except Exception:                                    # pragma: no cover
    da = None

FF = shutil.which('ffmpeg')
if da is not None:
    try:
        import imageio_ffmpeg
        FF = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass


@unittest.skipUnless(da is not None and FF, 'ffmpeg and documentary_audio needed')
class FastPreviewAudioTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / 'inputs').mkdir(); (self.root / 'sources').mkdir()
        subprocess.run([FF, '-v', 'error', '-y', '-f', 'lavfi', '-i', 'sine=f=300:d=40',
                        '-ar', '44100', str(self.root / 'inputs/narr.wav')], check=True)
        subprocess.run([FF, '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=gray:s=160x90:r=30',
                        '-f', 'lavfi', '-i', 'sine=f=900:d=60', '-t', '60', '-c:v', 'libx264',
                        '-preset', 'ultrafast', '-c:a', 'aac', '-shortest',
                        str(self.root / 'sources/S01.mp4')], check=True)
        segs = [{'kind': 'narration', 'source_in_s': 0.0, 'source_out_s': 10.0},
                {'kind': 'sound_bite', 'asset_id': 'a1', 'asset_name': 'S01.mp4',
                 'source_in_s': 45.0, 'source_out_s': 52.5},
                {'kind': 'narration', 'source_in_s': 10.0, 'source_out_s': 40.3}]
        t = 0.0
        for s in segs:
            s['timeline_in_s'] = t; t += s['source_out_s'] - s['source_in_s']; s['timeline_out_s'] = t
        self.timeline = {'segments': segs, 'narration_duration_s': 40.3,
                         'narration_file_s': 40.0, 'duration_s': t}
        self.saved = (da.build_timeline, da.annotate_plan)
        da.build_timeline = lambda p, plan: self.timeline
        da.annotate_plan = lambda p, r, plan: plan
        self.project = {'id': 'x', 'voiceover': {'path': 'inputs/narr.wav'},
                        'assets': [{'id': 'a1', 'kind': 'video', 'path': 'sources/S01.mp4'}]}

    def tearDown(self):
        da.build_timeline, da.annotate_plan = self.saved
        shutil.rmtree(self.root, ignore_errors=True)

    def build(self, name):
        out = self.root / 'renders' / name
        result = da._build_audio(self.root, self.project, {'bites': [], 'revision': 1}, out,
                                 compact_preview=True)
        return out, result

    def test_length_matches_the_plan_including_the_srt_hold(self):
        out, result = self.build('a.m4a')
        self.assertTrue(out.is_file())
        self.assertAlmostEqual(result['duration_s'], self.timeline['duration_s'], places=3)
        self.assertEqual(len(result['sound_bite_levels']), 1)
        self.assertEqual(len(result['segment_lengths_s']), 3)

    def test_second_build_reuses_the_prepared_pieces(self):
        self.build('a.m4a')
        cache = self.root / 'cache' / da._PREVIEW_CACHE
        before = {p.name: p.stat().st_mtime_ns for p in cache.iterdir()}
        self.build('b.m4a')
        after = {p.name: p.stat().st_mtime_ns for p in cache.iterdir()}
        self.assertEqual(before, after)

    def test_the_bite_is_cut_from_its_own_second(self):
        # 45.0-52.5 s is 7.5 s of the source; seeking must not shift or shorten it.
        self.build('a.m4a')
        cache = self.root / 'cache' / da._PREVIEW_CACHE
        bite = next(p for p in cache.iterdir() if p.name.startswith('bite-') and p.suffix == '.wav')
        with wave.open(str(bite)) as w:
            self.assertAlmostEqual(w.getnframes() / w.getframerate(), 7.5, delta=0.025)


class AutomaticPreviewTest(unittest.TestCase):
    def test_the_beat_build_starts_the_preview(self):
        source = Path('app.py').read_text()
        body = source[source.index('def _documentary_beat_build_work'):]
        body = body[:body.index('\n@app.')]
        self.assertIn('_start_documentary_audio(pid)', body)

    def test_the_timeline_prepares_a_missing_preview_itself(self):
        js = Path('static/documentary_timeline.js').read_text()
        self.assertIn("['idle','stale'].includes(state.status)&&scenes().length)docAutoPrepare", js)


if __name__ == '__main__':
    unittest.main()
