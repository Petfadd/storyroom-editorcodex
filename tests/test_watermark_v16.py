"""v16 channel watermark: edge logo (solid) + middle logo (opacity), every frame."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

import watermark as wm


class WatermarkTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'assets').mkdir()
        logo = Image.new('RGBA', (400, 200), (0, 0, 0, 0))
        ImageDraw.Draw(logo).rectangle((0, 0, 399, 199), fill=(255, 0, 0, 255))
        logo.save(self.root / 'assets' / wm.FILE)
        self.project = {'id': 'p', 'watermark_asset': {'file': wm.FILE}, 'watermark': {}}

    def tearDown(self):
        self.tmp.cleanup()

    def test_defaults_edge_on_middle_off(self):
        s = wm.settings(self.project)
        self.assertTrue(s['edge_enabled'])
        self.assertFalse(s['middle_enabled'])
        self.assertTrue(wm.active(self.project, self.root))

    def test_each_corner_and_size(self):
        for pos, expect in (('top_left', (32, 32)), ('top_right', (1280 - 32 - 256, 32)),
                            ('bottom_left', (32, 720 - 32 - 128)), ('bottom_right', (1280 - 32 - 256, 720 - 32 - 128))):
            conf = dict(wm.DEFAULTS, edge_position=pos, edge_size=0.2, edge_margin=0.025)
            x, y, w, h = wm.layout(conf, 400, 200, 1280, 720)['edge']
            self.assertEqual((x, y, w, h), (*expect, 256, 128), pos)

    def test_edge_is_solid_and_middle_uses_its_opacity(self):
        self.project['watermark'] = {'middle_enabled': True, 'middle_opacity': 0.25, 'middle_size': 0.5}
        layers = wm.prepared(self.project, self.root, 1280, 720, self.root)
        alpha = {f.stem.split('-')[1]: Image.open(f).getchannel('A').getextrema()[1] for f, _, _ in layers}
        self.assertEqual(alpha['edge'], 255)
        self.assertEqual(alpha['middle'], round(255 * 0.25))
        self.assertEqual([f.stem.split('-')[1] for f, _, _ in layers], ['middle', 'edge'])   # edge drawn on top

    def test_validation(self):
        self.assertEqual(wm.validate_patch({'edge_position': 'bottom_left'}), {'edge_position': 'bottom_left'})
        for bad in ({'edge_position': 'middle'}, {'edge_size': 0.9}, {'middle_opacity': 2}, {'colour': 1},
                    {'edge_enabled': 'yes'}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                wm.validate_patch(bad)
        self.assertNotIn('edge_opacity', wm.DEFAULTS)                     # the edge logo has no opacity

    def test_metadata_names_the_owner(self):
        self.assertEqual(wm.metadata_args(self.project), [])
        self.project['watermark']['owner'] = 'Homicide Recap'
        args = wm.metadata_args(self.project)
        self.assertIn('artist=Homicide Recap', args)
        self.assertTrue(any(a.startswith('copyright=') for a in args))

    @unittest.skipUnless(shutil.which('ffmpeg'), 'needs ffmpeg')
    def test_renders_on_every_frame_of_a_piece_with_the_film_clock(self):
        self.project['watermark'] = {'edge_position': 'top_left', 'edge_size': 0.25, 'edge_margin': 0.0,
                                     'middle_enabled': True, 'middle_size': 0.5, 'middle_opacity': 0.5}
        inputs, steps = wm.render_filters(self.project, self.root, 640, 360, '30', self.root, 1, 90, 300, 'base')
        out = self.root / 'o.mp4'
        graph = ['[0:v]setpts=PTS+300/(30*TB)[base]'] + steps + ['[wm]setpts=PTS-STARTPTS,format=yuv420p[v]']
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=blue:s=640x360:r=30:d=3', *inputs,
                        '-filter_complex', ';'.join(graph), '-map', '[v]', '-frames:v', '90', '-c:v', 'libx264',
                        '-pix_fmt', 'yuv420p', str(out)], check=True, timeout=60)
        for t in ('0', '1.5', '2.95'):
            png = self.root / f'f{t}.png'
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', t, '-i', str(out), '-frames:v', '1', str(png)], check=True)
            im = Image.open(png).convert('RGB')
            edge, middle, plain = im.getpixel((60, 30)), im.getpixel((320, 180)), im.getpixel((600, 340))
            self.assertGreater(edge[0], 200, t); self.assertLess(edge[2], 60, t)          # solid red edge logo
            self.assertTrue(90 < middle[0] < 170 and 90 < middle[2] < 170, (t, middle))   # half-faded middle
            self.assertLess(plain[0], 40, t)                                               # footage elsewhere


if __name__ == '__main__':
    unittest.main()
