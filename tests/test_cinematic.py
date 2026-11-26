import json, random, shutil, subprocess, sys, tempfile, unittest
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import cinematic as C


class CameraModel(unittest.TestCase):
    def test_normalise_rejects_out_of_range(self):
        for bad in ({'zoom_start': 99}, {'zoom_end': 201}, {'x_start': 1.2}, {'easing': 'bounce'},
                    {'zoom_start': True}, {'motion_end': 0}, {'motion_end': 1.1}):
            with self.assertRaises(ValueError):
                C.normalise(bad)
        self.assertIsNone(C.normalise(None))
        cam = C.normalise({'zoom_start': 100, 'zoom_end': 110, 'locked': 1})
        self.assertTrue(cam['locked']); self.assertEqual(cam['origin'], 'manual'); self.assertTrue(C.is_moving(cam))

    def test_window_never_shows_past_the_frame(self):
        rng = random.Random(3)
        for _ in range(500):
            cam = C.normalise({'zoom_start': rng.uniform(100, 200), 'zoom_end': rng.uniform(100, 200),
                               'x_start': rng.random(), 'y_start': rng.random(), 'x_end': rng.random(),
                               'y_end': rng.random(), 'easing': rng.choice(C.EASINGS),
                               'motion_end': rng.uniform(.1, 1)})
            z, cx, cy = C.window(cam, rng.random())
            half = 0.5 / z
            self.assertGreaterEqual(cx - half, -1e-9); self.assertLessEqual(cx + half, 1 + 1e-9)
            self.assertGreaterEqual(cy - half, -1e-9); self.assertLessEqual(cy + half, 1 + 1e-9)

    def test_presets(self):
        self.assertEqual(C.preset('zoom_in', 'medium')['zoom_end'], 110)
        self.assertEqual(C.preset('zoom_out', 'subtle')['zoom_start'], 105)
        pan = C.preset('pan_right', 'medium')
        self.assertLess(pan['x_start'], pan['x_end'])
        z, cx, _ = C.window(C.normalise(pan), 0)
        self.assertAlmostEqual(cx, pan['x_start'], places=6)      # the pan has room: not clamped
        self.assertFalse(C.is_active(C.normalise(C.preset('static'))))

    def test_edited_move_reaches_final_frame_then_holds(self):
        cam = C.normalise({'zoom_start':100,'zoom_end':110,'easing':'linear','motion_end':.25})
        self.assertAlmostEqual(C.window(cam,.25)[0],1.1)
        self.assertAlmostEqual(C.window(cam,.75)[0],1.1)
        self.assertIn('/0.250000',C.ffmpeg_filter(cam,1920,1080,0,300))

    @unittest.skipUnless(shutil.which('node'), 'node is not installed')
    def test_monitor_and_render_use_the_same_arithmetic(self):
        rng = random.Random(11); cases = []
        for _ in range(200):
            cam = C.normalise({'zoom_start': rng.uniform(100, 200), 'zoom_end': rng.uniform(100, 200),
                               'x_start': rng.random(), 'y_start': rng.random(), 'x_end': rng.random(),
                               'y_end': rng.random(), 'easing': rng.choice(C.EASINGS),
                               'motion_end': rng.uniform(.1, 1)})
            cases.append((cam, rng.random()))
        js = ("const C=require(%s);const cases=JSON.parse(require('fs').readFileSync(0,'utf8'));"
              "process.stdout.write(JSON.stringify(cases.map(([c,p])=>C.camWindow(c,p))))") % json.dumps(str(ROOT / 'static' / 'cinematic.js'))
        out = subprocess.run(['node', '-e', js], input=json.dumps(cases), capture_output=True, text=True, check=True).stdout
        for (cam, p), got in zip(cases, json.loads(out)):
            for a, b in zip(C.window(cam, p), got):
                self.assertAlmostEqual(a, b, places=9)


class PresetParity(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'node is not installed')
    def test_presets_match_in_monitor_and_server(self):
        moves = ['zoom_in', 'zoom_out', 'pan_left', 'pan_right', 'pan_up', 'pan_down', 'static']
        cases = [(m, i, [0.3, 0.6], 100) for m in moves for i in ('subtle', 'medium', 'strong')]
        js = ("const C=require(%s);const cases=JSON.parse(require('fs').readFileSync(0,'utf8'));"
              "process.stdout.write(JSON.stringify(cases.map(([m,i,f,b])=>C.camPreset(m,i,f,b))))") % json.dumps(str(ROOT / 'static' / 'cinematic.js'))
        out = json.loads(subprocess.run(['node', '-e', js], input=json.dumps(cases), capture_output=True, text=True, check=True).stdout)
        for (m, i, f, b), got in zip(cases, out):
            want = C.preset(m, i, tuple(f), b)
            for k in C.FIELDS:
                self.assertAlmostEqual(want[k], got[k], places=6, msg=f'{m} {i} {k}')
        self.assertLess(C.preset('pan_right')['x_start'], C.preset('pan_right')['x_end'])
        self.assertGreater(C.preset('pan_up')['y_start'], C.preset('pan_up')['y_end'])


class RenderedMotion(unittest.TestCase):
    """The renderer's own _span_filters draws the camera: first frame 100%, last 110%."""

    @classmethod
    def setUpClass(cls):
        import imageio_ffmpeg
        cls.ff = imageio_ffmpeg.get_ffmpeg_exe()
        cls.tmp = Path(tempfile.mkdtemp())
        cls.src = cls.tmp / 'src.mp4'
        subprocess.run([cls.ff, '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=s=640x360:r=30:d=3',
                        '-c:v', 'libx264', '-crf', '10', '-pix_fmt', 'yuv420p', str(cls.src)], check=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def frame(self, vf, n, name):
        out = self.tmp / name
        subprocess.run([self.ff, '-v', 'error', '-y', '-i', str(self.src), '-vf', vf, '-frames:v', str(n),
                        '-update', '1', str(out)], check=True)
        return out

    def ssim(self, a, b):
        import re
        err = subprocess.run([self.ff, '-i', str(a), '-i', str(b), '-lavfi', 'ssim', '-f', 'null', '-'],
                             capture_output=True, text=True).stderr
        return float(re.search(r'All:([0-9.]+)', err).group(1))

    def test_zoom_runs_from_start_to_end_over_the_slot(self):
        import documentary_final_renderer as R
        cam = C.normalise({'zoom_start': 100, 'zoom_end': 110, 'easing': 'linear'})
        span = {'source_start_frame': 0, 'source_frame_count': 60, 'output_frame_count': 60,
                'frame_conversion': None, 'picture_scale': 100, 'camera': cam}
        vf = R._span_filters(span, 0, 60, 640, 360, Fraction(30), '30', False)
        first = self.frame(vf, 1, 'first.png'); last = self.frame(vf, 60, 'last.png')
        ref100 = self.frame('trim=start_frame=0:end_frame=1', 1, 'r100.png')
        ref110 = self.frame('trim=start_frame=59:end_frame=60,scale=704:396:flags=bilinear,crop=640:360', 1, 'r110.png')
        self.assertGreater(self.ssim(first, ref100), 0.97)
        self.assertGreater(self.ssim(last, ref110), 0.97)
        self.assertLess(self.ssim(last, ref100), self.ssim(last, ref110))

    def test_first_frame_is_the_start_framing_exactly(self):
        # ffmpeg counts perspective's `in` from 1; an off-by-one put every move a frame early.
        import documentary_final_renderer as R
        cam = C.normalise({'zoom_start': 100, 'zoom_end': 200, 'easing': 'linear'})
        span = {'source_start_frame': 0, 'source_frame_count': 11, 'output_frame_count': 11,
                'frame_conversion': None, 'picture_scale': 100, 'camera': cam}
        vf = R._span_filters(span, 0, 11, 640, 360, Fraction(30), '30', False)
        first = self.frame(vf, 1, 'f0.png'); plain = self.frame('scale=640:360', 1, 'p0.png')
        self.assertGreater(self.ssim(first, plain), 0.995)
        # A piece that starts inside the slot (after a blend) picks up the move where it is.
        vf5 = R._span_filters(span, 5, 6, 640, 360, Fraction(30), '30', False)
        self.assertIn('(4+in)', vf5)

    def test_no_camera_renders_exactly_as_before(self):
        import documentary_final_renderer as R
        span = {'source_start_frame': 0, 'source_frame_count': 30, 'frame_conversion': None, 'picture_scale': 120}
        vf = R._span_filters(span, 0, 30, 640, 360, Fraction(30), '30', False)
        self.assertNotIn('perspective', vf); self.assertIn('crop=640:360', vf)


if __name__ == '__main__':
    unittest.main()


class PhotoCardMotion(unittest.TestCase):
    """A full-screen photo moves under a label that stays still."""

    def test_photo_moves_and_label_holds(self):
        import imageio_ffmpeg, numpy as np
        from PIL import Image
        import person_overlays as po
        ff = imageio_ffmpeg.get_ffmpeg_exe()
        tmp = Path(tempfile.mkdtemp())
        try:
            (tmp / 'people').mkdir()
            Image.effect_noise((400, 300), 60).convert('RGB').save(tmp / 'people' / 'p.jpg')
            person = {'id': 'p1', 'name': 'Jane Doe', 'role': 'Victim', 'photo': {'path': 'people/p.jpg'}, 'focus_y': 0.3}
            project = {'people': [person], 'person_overlay_settings': {'style': 'full', 'photo_motion': 'zoom_in',
                                                                         'photo_motion_intensity': 'strong', 'enabled': True, 'show_label': True}}
            conf = po.settings(project)
            self.assertIsNotNone(po.motion_camera(person, conf))
            self.assertIsNotNone(po.motion_camera(person, po.settings({'person_overlay_settings': {'style': 'full'}})))
            self.assertIsNone(po.motion_camera(person, po.settings({'person_overlay_settings': {'style': 'full', 'photo_motion': 'none'}})))
            cache = {'plan': {'windows': [{'person_id': 'p1', 'start_ms': 0, 'end_ms': 2000, 'name_intro': True}]}}
            inputs, steps, n = po.render_filters(project, tmp, None, 320, 180, '30', tmp, 1, cache=cache)
            self.assertEqual(n, 1); self.assertEqual(inputs.count('-i'), 2)        # photo + label layers
            out = tmp / 'o_%02d.png'
            subprocess.run([ff, '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=gray:s=320x180:r=30:d=2', *inputs,
                            '-filter_complex', '[0:v]null[base];' + ';'.join(steps), '-map', '[cards]',
                            '-frames:v', '60', str(out)], check=True)
            a = np.asarray(Image.open(tmp / 'o_01.png').convert('L'), dtype=float)
            b = np.asarray(Image.open(tmp / 'o_60.png').convert('L'), dtype=float)
            # v17: the photo is centred and the name's red bar sits under its left edge.
            from clean_photo_framing import photo_rect
            bar_x, _ = po._name_place(photo_rect((400, 300), 320, 180), 320, 180)
            label = (slice(int(180 * 0.86), int(180 * 0.92)), slice(bar_x, bar_x + 1))
            photo = (slice(20, 100), slice(110, 210))
            self.assertLess(np.abs(a[label] - b[label]).mean(), 2.0)            # the label does not move
            self.assertGreater(np.abs(a[photo] - b[photo]).mean(), 10.0)        # the photo does
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
