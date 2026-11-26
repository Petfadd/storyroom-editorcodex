"""A names-only SRT from Prompt 6 is checked against the exported original at upload."""
import io, unittest
import srt_compare


def b(n, a, e, text):
    return {'number': n, 'start_ms': a, 'end_ms': e, 'text': text}


ORIGINAL = [b(1, 0, 2500, 'On the night of March 14th, Malia Thompson left work.'),
            b(2, 2500, 5100, 'Her mother, Linda Thomson, called police at midnight.'),
            b(3, 5100, 8000, 'Malia never came home.')]


class SrtCompareTest(unittest.TestCase):
    def test_names_only_correction_is_confirmed(self):
        fixed = [b(1, 0, 2500, 'On the night of March 14th, Maliyah Thompson left work.'),
                 b(2, 2500, 5100, 'Her mother, Linda Thompson, called police at midnight.'),
                 b(3, 5100, 8000, 'Maliyah never came home.')]
        c = srt_compare.compare(ORIGINAL, fixed)
        self.assertTrue(c['same_timing']); self.assertEqual(c['timing_changes'], 0)
        self.assertEqual(c['other_changes'], [])
        self.assertEqual(c['name_changes'], [{'before': 'Malia', 'after': 'Maliyah', 'blocks': [1, 3]},
                                             {'before': 'Thomson', 'after': 'Thompson', 'blocks': [2]}])

    def test_a_moved_time_is_caught(self):
        fixed = [dict(x) for x in ORIGINAL]; fixed[1]['end_ms'] = 5000; fixed[2]['start_ms'] = 5000
        c = srt_compare.compare(ORIGINAL, fixed)
        self.assertFalse(c['same_timing']); self.assertEqual(c['timing_changes'], 2)

    def test_other_wording_is_caught(self):
        fixed = [dict(x) for x in ORIGINAL]; fixed[2]['text'] = 'Malia did not come home.'
        c = srt_compare.compare(ORIGINAL, fixed)
        self.assertTrue(c['same_timing']); self.assertEqual(c['name_changes'], [])
        self.assertEqual(c['other_changes'], [{'before': 'never came', 'after': 'did not come', 'blocks': [3]}])

    def test_a_dropped_line_is_a_timing_change(self):
        c = srt_compare.compare(ORIGINAL, ORIGINAL[:2])
        self.assertFalse(c['same_timing']); self.assertEqual(c['timing_changes'], 1)


class SrtReplaceUploadTest(unittest.TestCase):
    """The comparison is stored on the project when an SRT replaces another."""
    def test_upload_route_compares_with_the_previous_srt(self):
        src = open('app.py', encoding='utf-8').read()
        block = src[src.index("if kind=='srt':"):src.index("elif kind=='srt_block_map':")]
        self.assertIn('srt_compare.compare(p[\'srt\'][\'blocks\'],blocks)', block)
        self.assertLess(block.index('srt_compare.compare'), block.index("p['srt']={'blocks':blocks"))
        self.assertIn("p['srt']['compared']=compared", block)


class SrtReplaceThroughTheRouteTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        import app as server
        self.server, self.tmp = server, tempfile.TemporaryDirectory()
        self.original_projects = server.PROJECTS; server.PROJECTS = Path(self.tmp.name)
        self.client = server.app.test_client()
        self.pid = self.client.post('/api/projects', json={'title': 'Names'}).get_json()['id']

    def tearDown(self):
        self.server.PROJECTS = self.original_projects; self.tmp.cleanup()

    def upload(self, text, name):
        return self.client.post(f'/api/projects/{self.pid}/upload', data={
            'kind': 'srt', 'file': (io.BytesIO(text.encode()), name)}, content_type='multipart/form-data')

    def test_names_only_replacement_is_reported_on_the_project(self):
        first = self.upload('1\n00:00:00,000 --> 00:00:02,500\nMalia Thompson left work.\n\n'
                            '2\n00:00:02,500 --> 00:00:05,100\nMalia never came home.\n', 'export.srt')
        self.assertEqual(first.status_code, 200)
        self.assertNotIn('compared', first.get_json()['srt'])            # nothing to compare with yet
        second = self.upload('1\n00:00:00,000 --> 00:00:02,500\nMaliyah Thompson left work.\n\n'
                             '2\n00:00:02,500 --> 00:00:05,100\nMaliyah never came home.\n', 'export_names.srt')
        self.assertEqual(second.status_code, 200)
        c = second.get_json()['srt']['compared']
        self.assertTrue(c['same_timing']); self.assertEqual(c['other_changes'], [])
        self.assertEqual(c['name_changes'], [{'before': 'Malia', 'after': 'Maliyah', 'blocks': [1, 2]}])
        self.assertEqual(c['previous_name'], 'export.srt')
