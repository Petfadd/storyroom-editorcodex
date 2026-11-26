"""The saved music choice must reach the rendered bed.

The bed is built by the exporter, so a setting the user reviewed in Setup has to
be read from the project when no explicit mode is passed. A hardcoded default
here would silently ignore that choice.
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


class SavedNarrationChoiceTest(unittest.TestCase):
    """Whatever an older project saved, the music follows one rule: ducked under
    the narration, silent through every sound bite, full elsewhere."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'inputs').mkdir()
        self.ff = imageio_ffmpeg.get_ffmpeg_exe()
        self.file = self.root / 'inputs' / 'music.wav'
        subprocess.run([self.ff, '-hide_banner', '-loglevel', 'error', '-y', '-f', 'lavfi',
                        '-i', 'sine=frequency=300:duration=10', '-ac', '2', '-ar', '48000',
                        str(self.file)], check=True)
        # A speech-free picture span at each end is the reference level.
        self.segments = [{'kind': 'picture', 'timeline_in_s': 0.0, 'timeline_out_s': 1.0},
                         {'kind': 'narration', 'timeline_in_s': 1.0, 'timeline_out_s': 4.0},
                         {'kind': 'sound_bite', 'timeline_in_s': 4.0, 'timeline_out_s': 7.0},
                         {'kind': 'narration', 'timeline_in_s': 7.0, 'timeline_out_s': 9.0},
                         {'kind': 'picture', 'timeline_in_s': 9.0, 'timeline_out_s': 10.0}]

    def tearDown(self):
        self.tmp.cleanup()

    def bed(self, project, name):
        out = self.root / name
        music.build_bed(project, self.file, out, 10.0, self.segments, level_percent=70, duck=True)
        return out

    def check_shape(self, bed):
        reference = mean_db(self.ff, bed, 0.1, 0.6)          # picture only: full level
        narration = mean_db(self.ff, bed, 1.6, 3.5)
        after = mean_db(self.ff, bed, 7.8, 8.7)
        bite = mean_db(self.ff, bed, 4.1, 6.9)
        self.assertAlmostEqual(narration, reference - music.DUCK_DEPTH_DB, delta=1.5,
                               msg=f'narration {narration} dB vs full {reference} dB')
        self.assertAlmostEqual(after, reference - music.DUCK_DEPTH_DB, delta=1.5)
        self.assertTrue(bite is None or bite < -80, f'music audible under the bite: {bite} dB')

    def test_a_project_saved_as_ducking_gets_narration_only_music(self):
        self.check_shape(self.bed({'documentary_music': {'enabled': True, 'volume_percent': 70,
                                                         'narration_level': 'duck'}}, 'duck.wav'))

    def test_a_project_saved_as_stopping_under_narration_gets_the_same_shape(self):
        self.check_shape(self.bed({'documentary_music': {'enabled': True, 'volume_percent': 70,
                                                         'narration_level': 'mute'}}, 'mute.wav'))

    def test_the_bed_is_built_the_same_way_whether_or_not_a_mode_is_passed(self):
        from inspect import signature
        # `duck` must default to off: a caller that passes nothing still gets the
        # continuous bed, rather than the old ducked one.
        self.assertIs(signature(music.build_bed).parameters['duck'].default, False)


if __name__ == '__main__':
    unittest.main()
