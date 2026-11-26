"""v23: photo cutaways can be approved, and ticked rows are approved one by one with reasons."""
import copy
import json
import shutil
import sys
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))

from documentary_cutaways import parse, split_spans  # noqa: E402
from test_documentary_cutaways import source_event  # noqa: E402


class PhotoInAssetsFolder(unittest.TestCase):
    """Imported photographs live in assets/, not sources/. They were always refused."""
    def test_photo_from_assets_folder_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'sources').mkdir()
            (root / 'assets').mkdir()
            (root / 'sources' / 'S01.mp4').write_bytes(b'x')
            (root / 'assets' / '0a1b2c.jpg').write_bytes(b'x')
            project = {'scenes': [{'id': 'sb1', 'plan_row': {'script_beat': '028'}}],
                       'assets': [{'id': 'speaker', 'kind': 'video', 'original_name': 'S01.mp4', 'path': 'sources/S01.mp4', 'duration': 30},
                                  {'id': 'photo', 'kind': 'image', 'original_name': 'B03.jpg', 'path': 'assets/0a1b2c.jpg'}],
                       'documentary_cutaways': parse([{'id': 'CUTAWAY-004', 'soundbite_beat': '028', 'timeline_in': '00:00:05.000',
                                                       'timeline_out': '00:00:08.000', 'picture_source': 'B03.jpg', 'approved': True}])}
            spans, used = split_spans(project, root, [source_event()], Fraction(30))
            self.assertEqual([x['id'] for x in used], ['CUTAWAY-004'])
            self.assertEqual(spans[1]['source'], 'B03.jpg')
            self.assertEqual(sum(s['source_frame_count'] for s in spans), 600)      # clock unchanged
            # A file outside the project folders is still refused.
            project['assets'][1]['path'] = '../elsewhere.jpg'
            with self.assertRaisesRegex(ValueError, 'genuinely uploaded'):
                split_spans(project, root, [source_event()], Fraction(30))


def row(n, approved=False):
    return {'id': f'CUTAWAY-00{n}', 'soundbite_beat': '060', 'timeline_in': f'00:00:{10 * n:02d}.000',
            'timeline_out': f'00:00:{10 * n + 3:02d}.000', 'picture_source': f'B0{n}.jpg', 'approved': approved}


class ApproveSelected(unittest.TestCase):
    def setUp(self):
        import app as server
        self.server = server
        self.tmp = Path(tempfile.mkdtemp())
        self.old = server.PROJECTS
        server.PROJECTS = self.tmp
        self.client = server.app.test_client()
        self.client.environ_base['HTTP_HOST'] = '127.0.0.1:8004'
        self.h = {'Origin': 'http://127.0.0.1:8004', 'Host': '127.0.0.1:8004'}
        self.pid = self.client.post('/api/projects', json={'title': 'cut', 'edit_mode': 'documentary'}, headers=self.h).get_json()['id']
        f = self.tmp / self.pid / 'project.json'
        p = json.loads(f.read_text())
        p['documentary_beat_review'] = {'fitted_beats': [{'beat': '060'}]}
        p['documentary_cutaways'] = parse([row(1), row(2), row(3)])
        f.write_text(json.dumps(p))
        self.calls = 0

        def fake_validate(p, root, cutaways, sound=None):
            # CUTAWAY-002 can never be approved; everything else passes.
            self.calls += 1
            for r in cutaways:
                if r['approved'] and r['id'] == 'CUTAWAY-002':
                    raise ValueError('CUTAWAY-002: must fit inside one uninterrupted original soundbite; check film clock.')
            return copy.deepcopy(cutaways)
        self.patches = [mock.patch.object(server, '_validated_cutaways', side_effect=fake_validate),
                        mock.patch('documentary.load_plan', return_value={}),
                        mock.patch('documentary.annotate_plan', return_value={}),
                        mock.patch('documentary_render_plan.plan', side_effect=lambda *a, **k: dict(self.base_picture))]
        self.base_picture = {'picture_compatible': True, 'errors': []}
        for x in self.patches:
            x.start()

    def tearDown(self):
        for x in self.patches:
            x.stop()
        self.server.PROJECTS = self.old
        shutil.rmtree(self.tmp, ignore_errors=True)

    def approve(self, ids, approved=True):
        return self.client.post(f'/api/projects/{self.pid}/documentary-cutaways/approve',
                                json={'ids': ids, 'approved': approved}, headers=self.h)

    def test_one_bad_row_does_not_block_the_others(self):
        r = self.approve(['CUTAWAY-001', 'CUTAWAY-002', 'CUTAWAY-003'])
        self.assertEqual(r.status_code, 200, r.get_data())
        d = r.get_json()
        self.assertEqual(d['active'], 2)
        self.assertEqual({x['id']: x['approved'] for x in d['cutaways']},
                         {'CUTAWAY-001': True, 'CUTAWAY-002': False, 'CUTAWAY-003': True})
        self.assertEqual(d['rejected'], {'CUTAWAY-002': 'must fit inside one uninterrupted original soundbite; check film clock.'})
        saved = json.loads((self.tmp / self.pid / 'project.json').read_text())['documentary_cutaways']
        self.assertEqual([x['approved'] for x in saved], [True, False, True])

    def test_all_good_rows_approved_in_one_check(self):
        r = self.approve(['CUTAWAY-001', 'CUTAWAY-003'])
        self.assertEqual(r.get_json()['active'], 2)
        self.assertEqual(r.get_json()['rejected'], {})
        self.assertEqual(self.calls, 1)

    def test_turn_off_selected(self):
        self.approve(['CUTAWAY-001', 'CUTAWAY-003'])
        d = self.approve(['CUTAWAY-001'], approved=False).get_json()
        self.assertEqual([x['approved'] for x in d['cutaways']], [False, False, True])

    def test_bad_requests(self):
        self.assertEqual(self.approve([]).status_code, 400)
        self.assertEqual(self.approve(['CUTAWAY-099']).status_code, 400)
        self.assertEqual(self.client.post(f'/api/projects/{self.pid}/documentary-cutaways/approve', json={'ids': 'x'}, headers=self.h).status_code, 400)

    def test_a_picture_plan_problem_is_reported_once_not_per_row(self):
        # v24: one row fails, and the plan without any cutaway is broken too: say so once.
        self.base_picture = {'picture_compatible': False, 'errors': ['Beat 012: source interval has no verified frames.']}
        r = self.approve(['CUTAWAY-001', 'CUTAWAY-002'])
        self.assertEqual(r.status_code, 400)
        self.assertIn('until the picture plan is fixed', r.get_json()['error'])
        self.assertIn('Beat 012', r.get_json()['error'])

    def test_a_general_picture_problem_is_reported_once(self):
        with mock.patch.object(self.server, '_validated_cutaways', side_effect=ValueError('Beat 012: 4 approved source frames do not fit 5 output frames')):
            r = self.approve(['CUTAWAY-001'])
        self.assertEqual(r.status_code, 400)
        self.assertIn('No cutaway can be approved until this is fixed', r.get_json()['error'])


if __name__ == '__main__':
    unittest.main()
