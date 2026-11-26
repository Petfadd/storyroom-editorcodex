"""v20: the Setup cutaway upload works before the Beat timeline is built."""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ROW = {'id': 'CUTAWAY-001', 'soundbite_beat': '028', 'timeline_in': '00:00:05.000', 'timeline_out': '00:00:10.000',
       'picture_source': 'S02.mp4', 'source_in': '00:00:12.000', 'source_out': '00:00:17.000', 'reason': 'Roadway'}


class CutawayBeforeBuild(unittest.TestCase):
    def setUp(self):
        import app as server
        self.server = server
        self.tmp = Path(tempfile.mkdtemp())
        self.old = server.PROJECTS
        server.PROJECTS = self.tmp
        self.client = server.app.test_client()
        self.client.environ_base['HTTP_HOST'] = '127.0.0.1:8004'
        self.h = {'Origin': 'http://127.0.0.1:8004', 'Host': '127.0.0.1:8004'}
        r = self.client.post('/api/projects', json={'title': 'cutaway test', 'edit_mode': 'documentary'}, headers=self.h)
        self.pid = r.get_json()['id']

    def tearDown(self):
        self.server.PROJECTS = self.old
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_file_is_kept_until_the_build_then_applied(self):
        r = self.client.post(f'/api/projects/{self.pid}/documentary-cutaways',
                             json={'ledger': json.dumps({'cutaways': [ROW]}), 'name': 'cutaways.json'}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.get_data())
        self.assertTrue(r.get_json()['pending'])
        p = self.client.get(f'/api/projects/{self.pid}', headers=self.h).get_json()
        self.assertEqual(p['documentary_cutaways_pending']['rows'], 1)
        self.assertNotIn('ledger', p['documentary_cutaways_pending'])          # not sent to the page
        self.assertEqual(p.get('documentary_cutaways') or [], [])
        # A broken file is still refused straight away.
        bad = self.client.post(f'/api/projects/{self.pid}/documentary-cutaways', json={'ledger': '{oops'}, headers=self.h)
        self.assertEqual(bad.status_code, 400)
        # After a build the waiting file is applied (rows unapproved: no picture check needed).
        with self.server.LOCKS[self.pid]:
            stored = self.server.load(self.pid)
            stored['documentary_beat_review'] = {'fitted_beats': [{'label': '028'}]}
            self.server.save(stored)
        self.assertTrue(self.server._apply_pending_cutaways(self.pid))
        after = self.server.load(self.pid)
        self.assertNotIn('documentary_cutaways_pending', after)
        self.assertEqual([x['id'] for x in after['documentary_cutaways']], ['CUTAWAY-001'])

    def test_removing_before_the_build_clears_the_waiting_file(self):
        self.client.post(f'/api/projects/{self.pid}/documentary-cutaways', json={'ledger': json.dumps([ROW])}, headers=self.h)
        r = self.client.post(f'/api/projects/{self.pid}/documentary-cutaways', json={'cutaways': []}, headers=self.h)
        self.assertEqual(r.status_code, 200)
        self.assertNotIn('documentary_cutaways_pending', self.server.load(self.pid))

    def test_setup_upload_is_never_disabled(self):
        js = (ROOT / 'static' / 'documentary.js').read_text(encoding='utf-8')
        start = js.index('function cutawaySetupCardHTML(){'); end = js.index('async function setupUploadCutaways(')
        card = js[start:end]
        self.assertNotIn("'disabled'", card)
        self.assertNotIn('aria-disabled', card)


if __name__ == '__main__':
    unittest.main()
