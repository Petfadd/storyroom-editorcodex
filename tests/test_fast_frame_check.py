"""The Beat build's frame check reads packet times instead of decoding pictures."""
import shutil
import subprocess
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

import strict_cuts

FF = strict_cuts._ffmpeg_exe()


def make(path, *args):
    subprocess.run([FF, '-v', 'error', '-y', *args, str(path)], check=True)


@unittest.skipUnless(FF and shutil.which(FF) or (FF and Path(FF).exists()), 'ffmpeg needed')
class PacketScanTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = Path(tempfile.mkdtemp())
        cls.clip = cls.dir / 'clip.mp4'
        make(cls.clip, '-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=30', '-t', '20',
             '-c:v', 'libx264', '-preset', 'ultrafast', '-bf', '3', '-g', '60')
        # A trimmed copy keeps hidden lead-in frames that the decoder drops.
        cls.cut = cls.dir / 'cut.mp4'
        make(cls.cut, '-ss', '1.3', '-i', str(cls.clip), '-t', '10', '-c', 'copy')
        cls.gap = cls.dir / 'gap.mp4'
        make(cls.gap, '-i', str(cls.clip), '-t', '6', '-vf',
             "setpts='if(gt(N,60),PTS+0.5/TB,PTS)'", '-fps_mode', 'passthrough',
             '-c:v', 'libx264', '-preset', 'ultrafast')

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def decoded_count(self, path):
        out = subprocess.run([FF, '-v', 'error', '-i', str(path), '-map', '0:v:0',
                              '-f', 'framecrc', '-'], capture_output=True, text=True).stdout
        return sum(1 for line in out.splitlines() if line and not line.startswith('#'))

    def test_whole_file_matches_the_decoder(self):
        result = strict_cuts.packet_scan(self.clip, 600, 900)
        self.assertEqual(result, {'frames': 600, 'fps': Fraction(30)})

    def test_hidden_lead_in_frames_are_not_counted(self):
        result = strict_cuts.packet_scan(self.cut, 10, 10_000)
        self.assertEqual(result['frames'], self.decoded_count(self.cut))

    def test_stops_early_once_the_target_is_covered(self):
        result = strict_cuts.packet_scan(self.clip, 100, 400)
        self.assertEqual(result['frames'], 400)

    def test_short_source_goes_to_the_decoder_for_the_exact_error(self):
        self.assertIsNone(strict_cuts.packet_scan(self.clip, 601, 900))

    def test_uneven_timing_goes_to_the_decoder(self):
        self.assertIsNone(strict_cuts.packet_scan(self.gap, 50, 400))

    def test_missing_file_goes_to_the_decoder(self):
        self.assertIsNone(strict_cuts.packet_scan(self.dir / 'nope.mp4', 10, 400))


class BuildBarTest(unittest.TestCase):
    def test_red_fill_is_a_block_so_its_width_shows(self):
        css = Path('static/editor.css').read_text()
        self.assertIn('.build-progress .progress-fill{display:block', css)


if __name__ == '__main__':
    unittest.main()
