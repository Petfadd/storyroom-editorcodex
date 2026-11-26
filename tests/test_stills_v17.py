"""v17 stills: news screen grabs cleaned, photos always centred, names once, pairs."""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _v17_grabs as grabs                                     # noqa: E402
import clean_photo_framing as cpf                              # noqa: E402
import person_overlays as po                                   # noqa: E402


def iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0])); iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - ix * iy
    return ix * iy / u


class NewsGrabCleanup(unittest.TestCase):
    def test_every_grab_is_cut_to_the_photo_and_plain_photos_stay_whole(self):
        for name, image, want in grabs.cases() + grabs.more_cases():
            with self.subTest(name):
                got = cpf.detect_box(image)
                if want is None:
                    self.assertIsNone(got)
                    continue
                self.assertIsNotNone(got)
                self.assertGreater(iou(got, want), .93, (got, want))
                # Never reaches into the panels (where the logos are).
                self.assertGreaterEqual(got[0], want[0] - 2); self.assertLessEqual(got[2], want[2] + 2)
                self.assertGreaterEqual(got[1], want[1] - 2); self.assertLessEqual(got[3], want[3] + 2)

    def test_logos_are_gone_from_the_framed_still_and_its_blur(self):
        image, box = dict((n, (i, b)) for n, i, b in grabs.cases())['blur_sides_logos']
        clean, meta = cpf.clean_portrait(image)
        self.assertTrue(meta['cropped'])
        frame, rect = cpf.frame_still(clean, 1920, 1080)
        x, y, w, h = rect
        self.assertEqual(x, (1920 - w) // 2)                       # centred
        self.assertEqual(h, 1080)
        # The FOX 26 badge was purple (120,40,170) at the lower left; nothing like it remains.
        px = frame.convert('RGB').load()
        purple = sum(1 for xx in range(40, 400, 4) for yy in range(900, 1010, 4)
                     if abs(px[xx, yy][0] - 120) < 25 and abs(px[xx, yy][1] - 40) < 25 and abs(px[xx, yy][2] - 170) < 25)
        self.assertEqual(purple, 0)

    def test_manual_and_whole_crop_settings(self):
        image = Image.new('RGB', (1000, 500), (90, 90, 90))
        clean, meta = cpf.clean_portrait(image, {'mode': 'manual', 'box': [.25, .1, .75, .9]})
        self.assertEqual(clean.size, (500, 400)); self.assertEqual(meta['mode'], 'manual')
        clean, meta = cpf.clean_portrait(image, {'mode': 'none'})
        self.assertEqual(clean.size, (1000, 500)); self.assertFalse(meta['cropped'])
        self.assertIsNone(cpf.normalise_crop({'mode': 'manual', 'box': [.5, .5, .51, .9]}))   # too small
        self.assertIsNone(cpf.normalise_crop({'mode': 'manual', 'box': 'x'}))
        self.assertNotEqual(cpf.crop_token(None), cpf.crop_token({'mode': 'none'}))

    def test_original_file_is_never_modified(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            image, _ = dict((n, (i, b)) for n, i, b in grabs.cases())['black_sides_logo']
            src = tmp / 'grab.jpg'; image.save(src)
            before = src.read_bytes()
            cpf.framed_still_file(src, tmp / 'out.jpg', 1280, 720)
            self.assertEqual(src.read_bytes(), before)
            self.assertEqual(Image.open(tmp / 'out.jpg').size, (1280, 720))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class CentredPhotosAndNames(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / 'people').mkdir()
        cases = dict((n, i) for n, i, _ in grabs.cases())
        cases['blur_sides_logos'].save(self.tmp / 'people' / 'a.jpg')
        cases['black_sides_logo'].save(self.tmp / 'people' / 'b.jpg')
        self.a = {'id': 'a', 'name': 'Person One', 'photo': {'path': 'people/a.jpg'}, 'focus_y': .3}
        self.b = {'id': 'b', 'name': 'Person Two', 'photo': {'path': 'people/b.jpg'}, 'focus_y': .3}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_settings_force_centre_and_first_introduction(self):
        conf = po.settings({'person_overlay_settings': {'position': 'right', 'name_display': 'every'}})
        self.assertEqual((conf['position'], conf['name_display']), ('center', 'first'))
        self.assertTrue(conf['pair_photos'])
        with self.assertRaises(ValueError):
            po.clean_settings({'name_display': 'every'})

    def test_photo_is_centred_and_label_sits_under_it(self):
        conf = po.settings({'person_overlay_settings': {'enabled': True}})
        photo, label = po.layer_files(self.a, self.tmp, 1920, 1080, dict(conf, show_label=True), self.tmp / 'cards')
        img = Image.open(photo).convert('RGB')
        clean, _ = po.clean_photo(self.tmp / 'people' / 'a.jpg')
        x, y, w, h = cpf.photo_rect(clean.size, 1920, 1080)
        self.assertAlmostEqual(x + w / 2, 960, delta=2)
        lab = Image.open(label)
        self.assertEqual(lab.size, (1920, 1080))
        alpha = lab.getchannel('A')
        self.assertEqual(alpha.crop((0, 0, 1920, 500)).getextrema()[1], 0)     # nothing over the face area
        bar_x, _ = po._name_place((x, y, w, h), 1920, 1080)
        r, g, b, a = lab.getpixel((bar_x + 4, 1080 - 205 + 30))
        self.assertGreater(r, 180); self.assertLess(g, 90); self.assertGreater(a, 200)          # the red bar
        # A later appearance has no label layer at all.
        self.assertIsNone(po.layer_files(self.a, self.tmp, 1920, 1080, dict(conf, show_label=False), self.tmp / 'cards')[1])
        del img

    def test_pair_layers_and_shared_name_size(self):
        conf = po.settings({'person_overlay_settings': {'enabled': True}})
        photo, label = po.pair_layer_files([self.a, self.b], self.tmp, 1920, 1080, conf, (True, True), self.tmp / 'cards')
        self.assertEqual(Image.open(photo).size, (1920, 1080))
        rects = po.pair_rects(1920, 1080)
        self.assertEqual(rects[0][0], 1920 - rects[1][0] - rects[1][2])                 # symmetric, centred
        lab = Image.open(label).getchannel('A')
        for x, y, w, h in rects:
            bar_x, _ = po._name_place((x, y, w, h), 1920, 1080)
            self.assertGreater(lab.getpixel((bar_x + 4, 1080 - 205 + 30)), 200)
        # Only the new person gets a name.
        _, one = po.pair_layer_files([self.a, self.b], self.tmp, 1920, 1080, conf, (False, True), self.tmp / 'cards')
        lab = Image.open(one).getchannel('A')
        bar0, _ = po._name_place(rects[0], 1920, 1080)
        bar1, _ = po._name_place(rects[1], 1920, 1080)
        self.assertLess(lab.getpixel((bar0 + 4, 1080 - 205 + 30)), 250)
        self.assertGreater(lab.getpixel((bar1 + 4, 1080 - 205 + 30)), 200)
        self.assertIsNone(po.pair_layer_files([self.a, self.b], self.tmp, 1920, 1080, conf, (False, False), self.tmp / 'cards')[1])

    def test_pair_window_renders_one_overlay_with_both_people(self):
        import imageio_ffmpeg
        project = {'people': [self.a, self.b], 'person_overlay_settings': {'enabled': True, 'photo_style': 'cut'}}
        cache = {'plan': {'windows': [{'person_id': 'a', 'partner_id': 'b', 'partner_name': 'Person Two',
                                       'start_ms': 0, 'end_ms': 1000, 'name_intro': True, 'partner_name_intro': True,
                                       'photo_index': 0, 'partner_index': 0,
                                       'motion': {'entrance': 'cut', 'exit': 'none', 'camera_preset': None}}]}}
        inputs, steps, n = po.render_filters(project, self.tmp, None, 640, 360, '30', self.tmp, 1, cache=cache)
        self.assertEqual((n, inputs.count('-i')), (1, 2))          # one pair photo layer + one name layer
        out = self.tmp / 'f.png'
        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-v', 'error', '-y', '-f', 'lavfi', '-i',
                        'color=c=black:s=640x360:r=30:d=1', *inputs, '-filter_complex',
                        '[0:v]null[base];' + ';'.join(steps), '-map', '[cards]', '-frames:v', '1', str(out)], check=True)
        frame = Image.open(out).convert('RGB')
        self.assertGreater(sum(frame.getpixel((160, 120))), 30)        # left person
        self.assertGreater(sum(frame.getpixel((480, 120))), 30)        # right person


if __name__ == '__main__':
    unittest.main()
