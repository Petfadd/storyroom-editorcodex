"""v22: the home page's project list (picture, film length, status) and its two small routes."""
import json
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class HomePage(unittest.TestCase):
    def setUp(self):
        import app as server
        self.server = server
        self.tmp = Path(tempfile.mkdtemp())
        self.old = server.PROJECTS
        server.PROJECTS = self.tmp
        self.client = server.app.test_client()
        self.client.environ_base['HTTP_HOST'] = '127.0.0.1:8004'
        self.h = {'Origin': 'http://127.0.0.1:8004', 'Host': '127.0.0.1:8004'}

    def tearDown(self):
        self.server.PROJECTS = self.old
        shutil.rmtree(self.tmp, ignore_errors=True)

    def make(self, title, fmt='landscape'):
        r = self.client.post('/api/projects', json={'title': title, 'edit_mode': 'documentary', 'format': fmt}, headers=self.h)
        self.assertEqual(r.status_code, 201, r.get_data())
        return r.get_json()['id']

    def edit(self, pid, fn):
        f = self.tmp / pid / 'project.json'
        p = json.loads(f.read_text())
        fn(p)
        f.write_text(json.dumps(p))
        return p

    def listing(self):
        return {p['id']: p for p in self.client.get('/api/projects', headers=self.h).get_json()['projects']}

    def add_picture(self, pid, size=(640, 360)):
        from PIL import Image
        Image.new('RGB', size, (200, 40, 60)).save(self.tmp / pid / 'assets' / 'photo.jpg')
        def fn(p):
            p['assets'] = [{'id': 'a1', 'kind': 'image', 'path': 'assets/photo.jpg', 'name': 'photo.jpg', 'original_name': 'photo.jpg', 'revision': 1}]
            p['voiceover'] = {'path': 'inputs/n.wav', 'duration': 899.97, 'name': 'n.wav'}
        return self.edit(pid, fn)

    def test_new_project_needs_setup(self):
        pid = self.make('Blank')
        card = self.listing()[pid]
        self.assertEqual(card['status'], 'setup')
        self.assertIsNone(card['cover_url'])
        self.assertFalse(card['has_export'])
        self.assertEqual(card['length_s'], 0)
        self.assertEqual(self.client.get(f'/api/projects/{pid}/cover.jpg', headers=self.h).status_code, 404)

    def test_picture_length_and_status(self):
        pid = self.make('Story')
        p = self.add_picture(pid)
        card = self.listing()[pid]
        self.assertEqual(card['status'], 'editing')
        self.assertAlmostEqual(card['length_s'], 899.97, places=2)
        self.assertTrue(card['cover_url'].startswith(f'/api/projects/{pid}/cover.jpg?v='))
        r = self.client.get(card['cover_url'], headers=self.h)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.mimetype, 'image/jpeg')
        # An export made from exactly this version of the project -> Exported.
        tok = 'ab' * 16
        (self.tmp / pid / 'renders' / f'documentary_final_{tok}.mp4').write_bytes(b'x')
        (self.tmp / pid / 'reviews' / f'documentary_final_{tok}.json').write_text(json.dumps({'project': {'updated': p['updated']}}))
        card = self.listing()[pid]
        self.assertEqual((card['status'], card['has_export']), ('exported', True))
        # Edited after the export -> back to Editing, the export folder is still there.
        self.edit(pid, lambda q: q.update(updated=time.time() + 5))
        card = self.listing()[pid]
        self.assertEqual((card['status'], card['has_export']), ('editing', True))

    def test_portrait_cover_keeps_its_shape(self):
        pid = self.make('Short', 'portrait')
        self.add_picture(pid, (720, 1280))
        r = self.client.get(self.listing()[pid]['cover_url'], headers=self.h)
        from PIL import Image
        import io
        w, h = Image.open(io.BytesIO(r.get_data())).size
        self.assertEqual((w, h), (270, 480))

    def test_most_recent_first(self):
        a, b = self.make('Older'), self.make('Newer')
        self.edit(a, lambda p: p.update(updated=1000))
        ids = [p['id'] for p in self.client.get('/api/projects', headers=self.h).get_json()['projects']]
        self.assertEqual(ids[0], b)

    def test_open_export_folder(self):
        pid = self.make('Folder')
        with mock.patch.object(self.server.subprocess, 'Popen') as popen, mock.patch.object(self.server.sys, 'platform', 'linux'):
            r = self.client.post(f'/api/projects/{pid}/open-export-folder', json={}, headers=self.h)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()['opened'])
        self.assertEqual(popen.call_args[0][0], ['xdg-open', str(self.tmp / pid / 'renders')])
        self.assertEqual(self.client.post('/api/projects/0123456789abcdef/open-export-folder', json={}, headers=self.h).status_code, 404)


if __name__ == '__main__':
    unittest.main()
