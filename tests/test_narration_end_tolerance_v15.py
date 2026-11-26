"""v15: a pause at the narration's end is judged against the real (decoded) end.

A 0.012 s MP3 encoder offset used to block a whole build with a message that did not
name the Beat. Within one output frame the pause is clamped and listed; beyond it the
message names the Beat, the script value, the narration length and the difference,
and a reviewed "clamp to narration end" is offered.
"""
import subprocess
import tempfile
import unittest
from pathlib import Path

import imageio_ffmpeg

from documentary import decoded_narration
from documentary_storyboard import prepare

FF = imageio_ffmpeg.get_ffmpeg_exe()


def tc(ms):
    s, ms = divmod(ms, 1000); m, s = divmod(s, 60); h, m = divmod(m, 60)
    return f'{h:02d}:{m:02d}:{s:02d},{ms:03d}'


def script(narration_out_ms, pause_ms):
    return f'''Beat: 001
Type: VOICE OVER
Narration Clock: 00:00:00,000 --> {tc(narration_out_ms)}
Narration State: PLAYING
Full source: S01.mp4
Source IN: 00:00:00,000
Source OUT: {tc(narration_out_ms)}
Footage Audio: MUTED (0%)

Beat: 002
Type: DOCUMENTARY SOUND BITE
Narration Clock: PAUSED at {tc(pause_ms)}
Narration State: PAUSED (Suspended at {tc(pause_ms)})
Full source: S01.mp4
Source IN: 00:00:10,000
Source OUT: 00:00:12,000
Footage Audio: UNMUTED (100% Dialogue Level, Clean)
Master timeline: {tc(narration_out_ms)} --> {tc(narration_out_ms + 2000)} (Duration: 2 sec)
Speaker: Witness
'''


class NarrationEndToleranceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'sources').mkdir(); (self.root / 'inputs').mkdir()
        (self.root / 'sources' / 'video.mp4').write_bytes(b'video')
        subprocess.run([FF, '-v', 'error', '-y', '-f', 'lavfi', '-i', 'sine=frequency=300:duration=4:sample_rate=48000',
                        '-c:a', 'libmp3lame', '-b:a', '128k', str(self.root / 'inputs' / 'voice.mp3')], check=True)

    def tearDown(self):
        self.tmp.cleanup()

    def project(self, narration_out_ms, pause_ms, duration=4.0):
        return {'profile': 'documentary', 'scenes': [], 'production_script': {'text': script(narration_out_ms, pause_ms)},
                'voiceover': {'path': 'inputs/voice.mp3', 'name': 'voice.mp3', 'duration': duration},
                'srt': {'blocks': [{'number': 1, 'start_ms': 0, 'end_ms': narration_out_ms, 'text': 'Words'}]},
                'assets': [{'id': 'a', 'name': 'S01.mp4', 'original_name': 'S01.mp4', 'kind': 'video',
                            'path': 'sources/video.mp4', 'duration': 20, 'revision': 'v1'}]}

    def test_mp3_with_an_encoder_start_offset_is_measured_from_decoded_audio(self):
        info = decoded_narration(self.root, {'path': 'inputs/voice.mp3'})
        self.assertAlmostEqual(info['decoded_s'], 4.0, delta=0.03)
        self.assertGreater(info['start_offset_s'], 0)                 # LAME adds a start offset
        self.assertNotEqual(info['container_s'], info['decoded_s'])    # the file's own figure differs

    def test_a_pause_twelve_ms_past_the_end_is_clamped_and_listed(self):
        staged, plan = prepare(self.project(4012, 4012), self.root, [], [], False, lambda _: True)
        clamps = staged['documentary_beat_review']['pause_clamps']
        self.assertEqual([(c['beat'], c['script_pause_ms'], c['clamped_to_ms']) for c in clamps], [('002', 4012, 4000)])
        self.assertEqual(plan['bites'][0]['pause_s'], 4.0)

    def test_a_pause_exactly_at_the_end_needs_no_clamp(self):
        staged, plan = prepare(self.project(4000, 4000), self.root, [], [], False, lambda _: True)
        self.assertEqual(staged['documentary_beat_review']['pause_clamps'], [])
        self.assertEqual(plan['bites'][0]['pause_s'], 4.0)

    def test_a_pause_beyond_one_frame_names_the_beat_and_offers_the_clamp(self):
        with self.assertRaises(ValueError) as caught:
            prepare(self.project(4000, 4200), self.root, [], [], False, lambda _: True)
        message = str(caught.exception)
        for words in ('Beat 002', '4.200s', '4.000s', '+0.200s', 'decoded audio', 'Clamp to narration end'):
            self.assertIn(words, message)

    def test_the_reviewed_clamp_fixes_it_and_records_it(self):
        staged, plan = prepare(self.project(4000, 4200), self.root, [], [], False, lambda _: True, clamp_pauses=True)
        clamp = staged['documentary_beat_review']['pause_clamps'][0]
        self.assertEqual((clamp['beat'], clamp['script_pause_ms'], clamp['clamped_to_ms'], clamp['reviewed']), ('002', 4200, 4000, True))
        self.assertEqual(plan['bites'][0]['pause_s'], 4.0)


if __name__ == '__main__':
    unittest.main()
