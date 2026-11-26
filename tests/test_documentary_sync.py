"""The script+SRT intake authority must not guess sources or times."""
from pathlib import Path
import tempfile
import unittest

from documentary_sync import required_source_state, readiness_message, srt_narration_bounds
from documentary_beats import read_beats


class ScriptSourceTruthTests(unittest.TestCase):
    SCRIPT = '''Beat: 001
Type: VOICE OVER
Narration State: PLAYING
Narration Clock: 00:00:00,066 --> 00:00:02,000
Footage Audio: MUTED (0%)
Full Source: S01.mp4
Source IN: 00:00:03,000
Source OUT: 00:00:04,934
Beat: 002
Type: DOCUMENTARY SOUND BITE
Narration State: PAUSED
Narration Clock: PAUSED at 00:00:02,000
Footage Audio: UNMUTED (100%)
Full Source: S02.mp4
Source IN: 00:00:10,000
Source OUT: 00:00:11,000
Duration: 00:00:01,000
Beat: 003
Type: VOICE OVER
Narration State: RESUMING
Narration Clock: 00:00:02,000 --> 00:00:04,000
Footage Audio: MUTED (0%)
Full Source: S01.mp4
Source IN: 00:00:04,934
Source OUT: 00:00:06,934
'''

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'sources').mkdir()
        self.beats = read_beats(self.SCRIPT)

    def asset(self, name, duration=20.0):
        (self.root / 'sources' / name).write_bytes(b'not-a-video: this tests metadata only')
        return {'name': name, 'original_name': name, 'path': 'sources/' + name,
                'kind': 'video', 'duration': duration}

    def test_progress_is_grouped_by_exact_filename(self):
        a1 = self.asset('S01.mp4')
        data = required_source_state(self.beats, [a1], self.root)
        self.assertEqual(data['count'], 2)
        self.assertEqual(data['ready_count'], 1)
        self.assertEqual(data['missing'], ['S02.mp4'])
        self.assertIn('1/2', readiness_message(data))
        self.assertNotIn('Beat', readiness_message(data))
        self.assertTrue(required_source_state(self.beats, [a1, self.asset('S02.mp4')], self.root)['all_ready'])

    def test_does_not_guess_typo_or_equivalent_id(self):
        wrong = self.asset('SO1.mp4')
        data = required_source_state(self.beats, [wrong, self.asset('S02.mp4')], self.root)
        self.assertEqual(data['missing'], ['S01.mp4'])

    def test_missing_bytes_are_not_ready_despite_metadata(self):
        a1 = self.asset('S01.mp4')
        (self.root / 'sources' / 'S01.mp4').unlink()
        data = required_source_state(self.beats, [a1], self.root)
        self.assertEqual(data['missing'], ['S01.mp4', 'S02.mp4'])

    def test_short_video_is_reported_not_clamped_or_substituted(self):
        data = required_source_state(self.beats, [self.asset('S01.mp4', 6.0), self.asset('S02.mp4')], self.root)
        self.assertEqual(data['too_short'][0]['source'], 'S01.mp4')
        self.assertIn('no cut was shortened', readiness_message(data))
        self.assertEqual(self.beats[2]['source_out_ms'], 6934)

    def test_analysis_cache_reuses_unchanged_source(self):
        import local_understanding as lu
        movie = self.root / 'sources' / 'S01.mp4'
        movie.write_bytes(b'original uploaded source')
        lu._write(lu.result_path(self.root, 'source-a'),
                  {'status': 'complete', 'source_signature': lu._signature(movie),
                   'audio_timing_version': 2, 'stages': {}})
        self.assertFalse(lu.enqueue(self.root, 'source-a', movie, 'video', 20))
        self.assertEqual(lu.read_result(self.root, 'source-a', movie)['status'], 'complete')

    def test_multiple_same_name_is_ambiguous(self):
        a1 = self.asset('S01.mp4')
        a2 = dict(a1)
        data = required_source_state(self.beats, [a1, a2], self.root)
        self.assertEqual(data['ambiguous'], ['S01.mp4'])
        self.assertIn('Conflicting', readiness_message(data))

    def test_srt_bounds_do_not_force_per_cue_visual_cuts(self):
        cues = [{'start_ms': 66, 'end_ms': 1200}, {'start_ms': 1400, 'end_ms': 4000}]
        data = srt_narration_bounds(self.beats, cues)
        self.assertEqual(data['status'], 'aligned')
        self.assertEqual(data['srt_out_ms'], 4000)
        self.assertEqual(data['script_out_ms'], 4000)
        mismatched = srt_narration_bounds(self.beats, [{'start_ms': 0, 'end_ms': 10000}])
        self.assertEqual(mismatched['status'], 'review')
        self.assertIn('not retime', mismatched['reason'])


if __name__ == '__main__':
    unittest.main()
