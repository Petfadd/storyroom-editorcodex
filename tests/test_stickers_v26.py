"""v26 stickers: catalogue, checks, routes and the FFmpeg steps that draw them."""
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import stickers  # noqa: E402


class Catalogue(unittest.TestCase):
    def test_every_built_in_has_its_pictures(self):
        for s in stickers.CATALOG:
            self.assertTrue(stickers.frame_paths({}, ROOT, s), s['id'])
            if s['animation'] == 'once':
                self.assertEqual(len(s['at']), len(s['frames']))

    def test_new_sticker_defaults_and_film_end(self):
        row = stickers.new_sticker({}, 'subscribe_click', 12.3456, film_s=60)
        self.assertRegex(row['id'], r'^st_[0-9a-f]{12}$')
        self.assertEqual((row['start_s'], row['duration_s'], row['center_x'], row['center_y'], row['opacity']), (12.346, 4.0, .5, .5, 1.0))
        near_end = stickers.new_sticker({}, 'like', 59, film_s=60)
        self.assertEqual(near_end['duration_s'], 1.0)          # never runs past the film
        with self.assertRaises(ValueError):
            stickers.new_sticker({}, 'nope', 0)

    def test_patch_is_checked_and_clamped(self):
        row = stickers.new_sticker({}, 'like', 0)
        out = stickers.apply_patch(row, {'width': 5, 'center_x': -1, 'duration_s': 0})
        self.assertEqual((out['width'], out['center_x'], out['duration_s']), (1.0, 0.0, .2))
        for bad in ({'colour': 1}, {'width': 'x'}, {'width': True}, {'width': float('nan')}, {}):
            with self.assertRaises(ValueError):
                stickers.apply_patch(row, bad)

    def test_animation_windows(self):
        once = stickers.frame_windows(stickers.BY_ID['subscribe_click'], 10, 14)
        self.assertEqual([i for i, _ in once], [0, 1])
        self.assertIn('gte(t,10.000000)*lt(t,12.000000)', once[0][1])
        self.assertIn('gte(t,12.000000)*lt(t,14.000000)', once[1][1])
        loop = stickers.frame_windows(stickers.BY_ID['rec'], 2, 6)
        self.assertEqual(len(loop), 2)
        self.assertIn('mod(t-2.000000,1.000000)', loop[0][1])
        self.assertEqual(stickers.frame_windows(stickers.BY_ID['like'], 1, 2), [(0, 'gte(t,1.000000)*lt(t,2.000000)')])

    def test_render_steps_only_where_due(self):
        project = {'stickers': [dict(stickers.new_sticker({}, 'subscribe_click', 10), width=.4, center_x=.2, center_y=.25)]}
        with tempfile.TemporaryDirectory() as work:
            ins, steps, n = stickers.render_filters(project, ROOT, 1920, 1080, 25, work, 3, between=(0, 100), input_label='cta')
            self.assertEqual((ins, steps, n), ([], [], 0))                 # 0..4 s: not due
            ins, steps, n = stickers.render_filters(project, ROOT, 1920, 1080, 25, work, 3, between=(240, 400), input_label='cta')
            self.assertEqual(n, 2)                                         # two frames of the click animation
            self.assertEqual(ins.count('-i'), 2)
            self.assertTrue(steps[0].startswith('[3:v]') and steps[2].startswith('[4:v]'))
            self.assertTrue(steps[1].startswith('[cta][stki0]overlay=x=') and steps[-1].endswith('[stk]'))
            self.assertIn('x=0:', steps[1])                                # 0.2*1920-384 clamps inside the picture
            self.assertTrue(all(Path(ins[k + 1]).is_file() for k in range(0, len(ins), 2)))


class Routes(unittest.TestCase):
    def setUp(self):
        import app as server
        self.server = server
        self.tmp = Path(tempfile.mkdtemp())
        self.old = server.PROJECTS
        server.PROJECTS = self.tmp
        self.c = server.app.test_client()
        self.c.environ_base['HTTP_HOST'] = '127.0.0.1:8004'
        self.h = {'Origin': 'http://127.0.0.1:8004', 'Host': '127.0.0.1:8004'}
        self.pid = self.c.post('/api/projects', json={'title': 'st', 'edit_mode': 'documentary'}, headers=self.h).get_json()['id']

    def tearDown(self):
        self.server.PROJECTS = self.old
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_add_change_remove(self):
        r = self.c.post(f'/api/projects/{self.pid}/stickers', json={'sticker': 'share', 'start_s': 3}, headers=self.h)
        self.assertEqual(r.status_code, 201)
        sid = r.get_json()['added_sticker']
        r = self.c.patch(f'/api/projects/{self.pid}/stickers/{sid}', json={'width': .5, 'start_s': 7.25}, headers=self.h)
        row = r.get_json()['stickers'][0]
        self.assertEqual((row['width'], row['start_s']), (.5, 7.25))
        self.assertEqual(self.c.patch(f'/api/projects/{self.pid}/stickers/{sid}', json={'x': 1}, headers=self.h).status_code, 400)
        self.assertEqual(self.c.post(f'/api/projects/{self.pid}/stickers', json={'sticker': 'bad'}, headers=self.h).status_code, 400)
        self.assertEqual(self.c.delete(f'/api/projects/{self.pid}/stickers/{sid}', headers=self.h).get_json()['stickers'], [])
        self.assertEqual(self.c.delete(f'/api/projects/{self.pid}/stickers/{sid}', headers=self.h).status_code, 404)

    def test_your_own_sticker(self):
        from PIL import Image
        buf = io.BytesIO(); Image.new('RGBA', (300, 120), (255, 0, 0, 128)).save(buf, 'PNG'); buf.seek(0)
        r = self.c.post(f'/api/projects/{self.pid}/stickers/upload', data={'file': (buf, 'My Logo.png')},
                        headers=self.h, content_type='multipart/form-data')
        self.assertEqual(r.status_code, 201, r.get_data())
        uid = r.get_json()['uploaded_sticker']
        lib = self.c.get(f'/api/projects/{self.pid}/stickers/library', headers=self.h).get_json()['stickers']
        mine = [x for x in lib if x['group'] == 'Yours']
        self.assertEqual([(x['id'], x['name']) for x in mine], [(uid, 'My Logo')])
        self.assertEqual(self.c.get(mine[0]['url'], headers=self.h).status_code, 200)
        self.assertEqual(self.c.get(f'/api/projects/{self.pid}/stickers/file/../project.json', headers=self.h).status_code, 404)
        self.c.post(f'/api/projects/{self.pid}/stickers', json={'sticker': uid, 'start_s': 1}, headers=self.h)
        # removing it from your library removes it from the film too
        d = self.c.delete(f'/api/projects/{self.pid}/stickers/upload/{uid}', headers=self.h).get_json()
        self.assertEqual((d['stickers'], d['sticker_uploads']), ([], []))
        self.assertFalse(any((self.tmp / self.pid / 'assets' / 'stickers').glob('*.png')))
        bad = io.BytesIO(b'not an image')
        self.assertEqual(self.c.post(f'/api/projects/{self.pid}/stickers/upload', data={'file': (bad, 'x.png')},
                                     headers=self.h, content_type='multipart/form-data').status_code, 400)

    def test_tab_icon(self):
        r = self.c.get('/favicon.ico', headers=self.h)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_data().startswith(b'\x00\x00\x01\x00'))


if __name__ == '__main__':
    unittest.main()
