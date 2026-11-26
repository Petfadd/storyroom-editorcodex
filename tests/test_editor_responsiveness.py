"""The editor's background traffic stays small however large the project is."""
import json
import shutil
import tempfile
import time
import unittest
from pathlib import Path

import app as server


class EditorResponsivenessTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.old = server.PROJECTS
        server.PROJECTS = self.tmp
        self.pid = 'c0ffee00c0ffee00'
        root = self.tmp / self.pid
        (root / 'sources').mkdir(parents=True)
        (root / 'assets').mkdir()
        from PIL import Image
        Image.new('RGB', (64, 36), 'red').save(root / 'assets' / 'p.jpg')
        self.p = {'id': self.pid, 'title': 'T', 'updated': 1.0, 'edit_mode': 'review',
                  'assets': [{'id': 'a1', 'kind': 'image', 'name': 'p.jpg', 'path': 'assets/p.jpg',
                              'revision': 'r1'}],
                  'scenes': [{'id': 's1', 'asset_id': 'a1', 'in_s': 21, 'frame_in': 0,
                              'frame_out': 30}],
                  'voiceover': None, 'srt': None}
        (root / 'project.json').write_text(json.dumps(self.p))
        self.client = server.app.test_client()

    def tearDown(self):
        server.PROJECTS = self.old
        server._SNAPSHOTS.clear()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_heartbeat_reports_version_and_jobs_only(self):
        beat = self.client.get(f'/api/projects/{self.pid}/heartbeat').get_json()
        self.assertEqual(beat['updated'], 1.0)
        self.assertEqual(set(beat), {'updated', 'render', 'preview', 'scene_exports', 'auto'})
        self.assertEqual(beat['render']['status'], 'idle')

    def test_snapshot_follows_saves(self):
        self.assertEqual(server.snapshot(self.pid)['updated'], 1.0)
        self.assertIs(server.snapshot(self.pid), server.snapshot(self.pid))
        time.sleep(0.01)
        self.p['updated'] = 2.0
        server.write(self.tmp / self.pid / 'project.json', self.p)
        self.assertEqual(server.snapshot(self.pid)['updated'], 2.0)
        beat = self.client.get(f'/api/projects/{self.pid}/heartbeat').get_json()
        self.assertEqual(beat['updated'], 2.0)

    def test_versioned_thumbnail_is_kept_by_the_browser(self):
        # A whole-number time is written "21" by the browser and 21.0 by Python.
        r = self.client.get(f'/api/projects/{self.pid}/scenes/s1/thumbnail?v=r1&in=21')
        self.assertEqual(r.status_code, 200)
        self.assertIn('immutable', r.headers['Cache-Control'])
        r.close()

    def test_stale_or_unversioned_thumbnail_is_not_kept(self):
        for query in ('', '?v=old&in=21', '?v=r1&in=5'):
            r = self.client.get(f'/api/projects/{self.pid}/scenes/s1/thumbnail{query}')
            self.assertEqual(r.headers['Cache-Control'], 'no-store', query)
            r.close()


if __name__ == '__main__':
    unittest.main()
