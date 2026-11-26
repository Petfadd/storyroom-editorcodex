"""Background music belongs to the narration: silent through every sound bite.

The footage's own sound plays alone during a bite. The bed fades out into the bite,
stays silent for all of it, and fades back in when the narration resumes. (Ducking
under the narrator's voice is applied at mix time; see test_documentary_music.)
"""
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

import imageio_ffmpeg

import documentary_music as music


def mean_db(ff, path, a, b):
    out = subprocess.run([ff, '-hide_banner', '-nostats', '-i', str(path), '-af',
                          f'atrim=start={a}:end={b},volumedetect', '-f', 'null', '-'],
                         capture_output=True, text=True)
    m = re.search(r'mean_volume:\s*(-?[\d.]+|-inf) dB', out.stderr)
    return float(m.group(1)) if m else None


class NoMusicUnderABiteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'inputs').mkdir()
        self.ff = imageio_ffmpeg.get_ffmpeg_exe()
        self.music = self.root / 'inputs' / 'music.wav'
        subprocess.run([self.ff, '-hide_banner', '-loglevel', 'error', '-y', '-f', 'lavfi',
                        '-i', 'sine=frequency=300:duration=12', '-ac', '2', '-ar', '48000',
                        str(self.music)], check=True)
        self.project = {'voiceover': {'duration': 12.0},
                        'documentary_music': {'enabled': True, 'volume_percent': 60}}

    def tearDown(self):
        self.tmp.cleanup()

    def segments(self):
        # picture 0-2, narration 2-5, bite 5-9, picture 9-12 on the finished
        # clock. The picture spans carry no speech at all, so they are the
        # reference level: anything quieter than them is a duck or a cut.
        return [{'kind': 'picture', 'timeline_in_s': 0.0, 'timeline_out_s': 2.0},
                {'kind': 'narration', 'timeline_in_s': 2.0, 'timeline_out_s': 5.0},
                {'kind': 'sound_bite', 'timeline_in_s': 5.0, 'timeline_out_s': 9.0},
                {'kind': 'picture', 'timeline_in_s': 9.0, 'timeline_out_s': 12.0}]

    def spans(self, bed):
        """Measured level of each kind of span, in dB."""
        return {'picture': mean_db(self.ff, bed, 0.3, 1.7),
                'narration': mean_db(self.ff, bed, 2.3, 4.7),
                'bite': mean_db(self.ff, bed, 5.3, 8.7),
                'picture_end': mean_db(self.ff, bed, 9.3, 11.7)}

    def test_the_bite_is_silent_and_narration_keeps_the_bed(self):
        bed = self.root / 'bed.wav'
        result = music.build_bed(self.project, self.music, bed, 12.0, self.segments(), level_percent=60)
        self.assertEqual(result['mute_windows'], [{'start_s': 5.0, 'end_s': 9.0}])
        levels = self.spans(bed)
        self.assertTrue(levels['bite'] is None or levels['bite'] < -80,
                        f"music is audible under the sound bite: {levels['bite']} dB")
        # Ducked under the narrator, full again on speech-free picture after the bite.
        self.assertAlmostEqual(levels['narration'], levels['picture'] - music.DUCK_DEPTH_DB, delta=1.5)
        self.assertAlmostEqual(levels['picture_end'], levels['picture'], delta=1.0)

    def test_fades_around_the_bite(self):
        bed = self.root / 'fade.wav'
        music.build_bed(self.project, self.music, bed, 12.0, self.segments(), level_percent=60)
        under_voice = mean_db(self.ff, bed, 2.6, 4.4)
        going = mean_db(self.ff, bed, 4.8, 4.98)      # last moment before the bite
        coming = mean_db(self.ff, bed, 9.05, 9.25)    # first moment after it
        settled = mean_db(self.ff, bed, 10.0, 11.5)
        self.assertLess(going, under_voice - 3, 'no fade out before the bite')
        self.assertLess(coming, settled - 3, 'no fade in after the bite')

    def test_back_to_back_bites_make_one_silence(self):
        windows = music.bite_windows([
            {'kind': 'sound_bite', 'timeline_in_s': 5.0, 'timeline_out_s': 7.0},
            {'kind': 'sound_bite', 'timeline_in_s': 7.0, 'timeline_out_s': 9.0},
            {'kind': 'narration', 'timeline_in_s': 9.0, 'timeline_out_s': 12.0}])
        self.assertEqual(windows, [(5.0, 9.0)])

    def test_no_bites_means_an_unbroken_bed(self):
        bed = self.root / 'plain.wav'
        result = music.build_bed(self.project, self.music, bed, 12.0,
                                 [{'kind': 'narration', 'timeline_in_s': 0.0, 'timeline_out_s': 12.0}],
                                 level_percent=60)
        self.assertEqual(result['mute_windows'], [])

    def test_the_settings_report_music_under_narration_only(self):
        state = music.settings(self.project)
        self.assertTrue(state['bite_cut'])
        self.assertEqual(state['narration_level'], 'duck')
        self.assertEqual(state['speech_mode'], 'duck')


if __name__ == '__main__':
    unittest.main()
