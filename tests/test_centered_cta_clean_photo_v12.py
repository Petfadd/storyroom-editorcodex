"""Source-level regression for Storyroom v12 CTA placement and TV-still crop."""
import hashlib
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw, ImageChops
from clean_photo_framing import clean_portrait
from channel_cta import motion_for, prepared_card, plan, render_filters, settings
from person_overlays import draw_full


class CinematicCTAAndPhotoV12(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'assets').mkdir()
        self.card = Image.new('RGBA', (640, 360), (0, 0, 0, 0))
        ImageDraw.Draw(self.card).rectangle((50, 50, 590, 310), fill=(250, 50, 30, 200))
        self.card.save(self.root / 'assets' / 'channel_cta.png')

    def project(self, motion='auto_varied'):
        return {'id': 'new-storyroom-video', 'title': 'Homicide Recap',
                'channel_cta_asset': {'file': 'channel_cta.png'},
                'channel_cta': {'enabled': True, 'mode': 'manual',
                                'manual_in_s': 1., 'manual_out_s': 4.,
                                'motion_style': motion}}

    def test_legacy_corner_settings_force_the_new_centered_layout(self):
        p = self.project()
        p['channel_cta'].update(position='lower_right', width=.38)
        s = settings(p)
        self.assertEqual(s['position'], 'center')
        self.assertEqual(s['width'], .97)
        card, w, h = prepared_card(p, self.root, 640, 360, self.root)
        self.assertEqual((w, h), (621, 349))
        self.assertEqual(card.exists(), True)

    def test_auto_motion_is_stable_and_varies_between_projects(self):
        p = self.project()
        self.assertEqual(motion_for(p), motion_for(p))
        self.assertEqual(len({motion_for(dict(p, id=f'video-{n}')) for n in range(30)}), 3)
        self.assertEqual(plan(p, self.root)[0]['motion_style'], motion_for(p))
        self.assertEqual(motion_for(self.project('top_down')), 'top_down')

    def test_nested_photo_crop_excludes_tv_bug_panel_preserving_original(self):
        image = Image.new('RGB', (1000, 562), '#777879')
        d = ImageDraw.Draw(image)
        for y in range(0, 562, 15):
            d.rectangle((0, y, 999, y + 4), fill='#5f615d')
        d.rectangle((290, 0, 710, 561), fill='#d9b7a2')
        d.ellipse((365, 80, 635, 440), fill='#685346')
        d.rectangle((5, 480, 160, 555), fill='#ff0000')
        d.rectangle((820, 475, 995, 555), fill='#ff0000')
        before = hashlib.sha256(image.tobytes()).hexdigest()
        result, details = clean_portrait(image)
        self.assertTrue(details['cropped'], details)
        self.assertLess(result.width, image.width * .6)
        self.assertEqual(result.height, 562)
        self.assertEqual(hashlib.sha256(image.tobytes()).hexdigest(), before)
        self.assertNotIn((255, 0, 0), result.get_flattened_data() if hasattr(result, 'get_flattened_data') else result.getdata())
        path = self.root / 'tv-portrait.jpg'
        image.save(path)
        frame, _ = draw_full(path, '', '', 640, 360, {'style': 'full', 'show_label': False})
        # TV logo red would remain obvious in blurred sidelines if the background
        # reused the source instead of the cropped inset.
        self.assertLess(frame.getpixel((20, 320))[0], 240)

    def test_original_natural_photo_is_not_arbitrarily_cut(self):
        image = Image.new('RGB', (960, 540), '#ababaa')
        ImageDraw.Draw(image).ellipse((280, 30, 660, 525), fill='#493827')
        framed, details = clean_portrait(image)
        self.assertFalse(details['cropped'])
        self.assertEqual(framed.size, image.size)

    @unittest.skipUnless(shutil.which('ffmpeg'), 'FFmpeg unavailable')
    def test_four_cta_motion_modes_render_without_changing_picture_clock(self):
        for direction in ('top_down', 'left_right', 'right_left', 'dissolve'):
            with self.subTest(direction=direction):
                p = self.project(direction)
                args, steps, count = render_filters(p, self.root, None, 640, 360, '30', self.root, 1, between=(0, 180), cache={})
                self.assertEqual(count, 1)
                graph = ['[0:v]setpts=PTS-STARTPTS[base]'] + steps + ['[cta]format=yuv420p[out]']
                output = self.root / (direction + '.mp4')
                cmd = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-f', 'lavfi',
                       '-i', 'color=c=blue:s=640x360:r=30:d=6', *args,
                       '-filter_complex', ';'.join(graph), '-map', '[out]', '-an',
                       '-c:v', 'mpeg4', '-q:v', '5', str(output)]
                subprocess.run(cmd, check=True, capture_output=True, timeout=35)
                result = subprocess.run(['ffprobe', '-v', 'error', '-count_frames', '-select_streams', 'v:0',
                    '-show_entries', 'stream=nb_read_frames', '-of', 'default=nw=1:nk=1', str(output)],
                    check=True, capture_output=True, text=True, timeout=15)
                self.assertEqual(int(result.stdout.strip()), 180)
                frames=[]
                for t in (.5, 2.5, 4.5):
                    output_frame = self.root / f'{direction}-{t}.png'
                    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', str(t), '-i', str(output),
                                    '-frames:v', '1', str(output_frame)], check=True, capture_output=True, timeout=15)
                    frames.append(Image.open(output_frame).convert('RGB'))
                self.assertIsNotNone(ImageChops.difference(frames[0], frames[1]).getbbox())
                self.assertIsNone(ImageChops.difference(frames[0], frames[2]).getbbox())


if __name__ == '__main__':
    unittest.main()
