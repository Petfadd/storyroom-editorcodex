"""The SRT and the voiceover rarely end on the same millisecond, and neither file may be edited.

* The voiceover usually carries a breath of silence after the last word: the picture
  keeps running over it, and a closing sound bite comes in when the file really ends.
* A subtitle tool often holds the last line a moment past the audio: the film runs to
  the end of the SRT, every recorded sample is kept, and silence follows the last word.
* A difference of more than END_SLACK_S is a different recording and is still refused.

These run on real audio and video so the sound itself is checked, not just the plan.
"""
import subprocess, tempfile, unittest
from pathlib import Path
import numpy as np
import av
import imageio_ffmpeg
from documentary import END_SLACK_S, build_timeline, narration_clock_s
from documentary_audio import build_audio
from documentary_beats import read_beats
from documentary_beat_plan import narration_gaps
from documentary_storyboard import prepare

RATE = 48000


def clock(ms):
    h, rem = divmod(int(ms), 3600000); m, rem = divmod(rem, 60000); s, ms = divmod(rem, 1000)
    return f'{h:02}:{m:02}:{s:02},{ms:03}'


def script(narration_end_ms, closing_at_ms):
    return f"""Beat: 001
Type: NARRATION (VOICE OVER)
Narration State: PLAYING
Narration Clock: 00:00:00,000 --> {clock(narration_end_ms)}
Footage Audio: MUTED (0%)
Video File: S01.mp4
Source IN: 00:00:00,000
Source OUT: {clock(narration_end_ms)}
On-screen Caption: None
Beat: 002
Type: DOCUMENTARY SOUND BITE
Narration State: PAUSED (Suspended at {clock(closing_at_ms)})
Footage Audio: UNMUTED (100% Live Speech)
Video File: S01.mp4
Source IN: 00:00:15,000
Source OUT: 00:00:16,000
Duration: 00:00:01,000
Speaker: Not verified
On-screen Caption: None
"""


class SrtAndVoiceoverEndTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        for d in ('sources', 'inputs', 'renders'):
            (self.root / d).mkdir()
        self.ff = imageio_ffmpeg.get_ffmpeg_exe()
        self.voice = self.root / 'inputs' / 'voice.wav'
        # 4.000 s of narration: 440 Hz then 660 Hz, so any cut or shift is audible.
        subprocess.run([self.ff, '-v', 'error', '-y', '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=2',
                        '-f', 'lavfi', '-i', 'sine=frequency=660:sample_rate=48000:duration=2',
                        '-filter_complex', '[0:a][1:a]concat=n=2:v=0:a=1[out]', '-map', '[out]', '-c:a', 'pcm_s16le',
                        str(self.voice)], check=True)
        # 20 s of footage whose live sound is 880 Hz: the closing bite.
        subprocess.run([self.ff, '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=blue:s=128x72:r=30:d=20',
                        '-f', 'lavfi', '-i', 'sine=frequency=880:sample_rate=48000:duration=20', '-c:v', 'libx264',
                        '-c:a', 'aac', '-shortest', str(self.root / 'sources' / 'S01.mp4')], check=True)

    def tearDown(self):
        self.tmp.cleanup()

    def project(self, srt_end_ms, text):
        return {'profile': 'documentary', 'scenes': [], 'production_script': {'text': text},
                'voiceover': {'path': 'inputs/voice.wav', 'name': 'voice.wav', 'duration': 4.0},
                'srt': {'blocks': [{'number': 1, 'start_ms': 0, 'end_ms': srt_end_ms // 2, 'text': 'one'},
                                   {'number': 2, 'start_ms': srt_end_ms // 2, 'end_ms': srt_end_ms, 'text': 'two'}]},
                'assets': [{'id': 'a', 'name': 'S01.mp4', 'original_name': 'S01.mp4', 'kind': 'video',
                            'path': 'sources/S01.mp4', 'duration': 20, 'revision': 'v1'}]}

    def build(self, p):
        beats = read_beats(p['production_script']['text'])
        gaps, issues = narration_gaps(p, beats)
        self.assertEqual(issues, [])
        return prepare(p, self.root, gaps, [], False, lambda _: True, beats=beats)

    def pcm(self, path):
        with av.open(str(path)) as f:
            frames = [x.to_ndarray() for x in f.decode(audio=0)]
        return np.concatenate(frames, axis=1).reshape(-1, 2).astype(float)[:, 0]

    def original(self):
        raw = subprocess.run([self.ff, '-v', 'error', '-i', str(self.voice), '-ac', '2', '-ar', '48000', '-f', 's16le', '-'],
                             stdout=subprocess.PIPE, check=True).stdout
        return np.frombuffer(raw, dtype='<i2').reshape(-1, 2)[:, 0].astype(float)

    def peak(self, pcm, at):
        values = pcm[int(at * RATE):int((at + .2) * RATE)]
        return np.fft.rfftfreq(len(values), 1 / RATE)[np.abs(np.fft.rfft(values)).argmax()]

    def test_srt_held_past_the_audio_keeps_every_sample_and_runs_to_the_srt_end(self):
        # The SRT's last line ends at 4.400 s; the voiceover file is 4.000 s.
        p = self.project(4400, script(4400, 4400))
        before = self.voice.read_bytes()
        staged, plan = self.build(p)
        self.assertNotIn('clock_s', p['voiceover'])                 # the input is untouched
        self.assertEqual(staged['voiceover']['duration'], 4.0)      # the file's length is not rewritten
        self.assertEqual(narration_clock_s(staged), 4.4)
        self.assertEqual(staged['scenes'][-1]['frame_out'], round(5.4 * 30))   # 4.4 s narration + 1 s bite
        self.assertEqual(staged['srt']['blocks'][-1]['end_ms'], 4400)          # the SRT is unchanged
        result = build_audio(self.root, staged, plan, self.root / 'renders' / 'a.wav')
        self.assertAlmostEqual(result['duration_s'], 5.4, delta=.025)
        pcm, original = self.pcm(self.root / 'renders' / 'a.wav'), self.original()
        np.testing.assert_array_equal(pcm[:4 * RATE], original[:4 * RATE])   # every recorded sample, in place
        self.assertLess(np.abs(pcm[int(4.02 * RATE):int(4.38 * RATE)]).max(), 1)   # then silence to the SRT end
        self.assertAlmostEqual(self.peak(pcm, 4.6), 880, delta=5)            # then the closing bite
        self.assertEqual(self.voice.read_bytes(), before)

    def test_silence_after_the_last_word_is_kept_and_the_closing_bite_follows_it(self):
        # The SRT and script end at 3.000 s; the voiceover file runs to 4.000 s.
        p = self.project(3000, script(3000, 3000))
        staged, plan = self.build(p)
        self.assertEqual([b['pause_s'] for b in plan['bites']], [4.0])       # the bite waits for the file's end
        self.assertNotIn('clock_s', staged['voiceover'])
        self.assertEqual(staged['scenes'][-1]['frame_out'], round(5.0 * 30))
        timeline = build_timeline(staged, plan)
        self.assertEqual(timeline['segments'][0]['source_out_s'], 4.0)       # none of the voiceover is cut
        result = build_audio(self.root, staged, plan, self.root / 'renders' / 'b.wav')
        self.assertAlmostEqual(result['duration_s'], 5.0, delta=.025)
        pcm, original = self.pcm(self.root / 'renders' / 'b.wav'), self.original()
        np.testing.assert_array_equal(pcm[:4 * RATE], original[:4 * RATE])
        self.assertAlmostEqual(self.peak(pcm, 4.3), 880, delta=5)

    def test_a_real_mismatch_is_still_refused(self):
        far = 4000 + int(END_SLACK_S * 1000) + 500
        p = self.project(far, script(far, far))
        with self.assertRaisesRegex(ValueError, 'narration is only 4.000s long'):
            self.build(p)

    def test_the_script_check_explains_instead_of_blocking(self):
        from documentary import narration_end_note
        self.assertIsNone(narration_end_note(4000, 4.1))
        blocking, text = narration_end_note(3000, 4.0)
        self.assertFalse(blocking); self.assertIn('Nothing is cut', text)
        blocking, text = narration_end_note(4400, 4.0)
        self.assertFalse(blocking); self.assertIn('runs to the end of the SRT', text)
        self.assertTrue(narration_end_note(9000, 4.0)[0])


if __name__ == '__main__':
    unittest.main()
