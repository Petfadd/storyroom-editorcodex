"""The editor has no sign-in: it answers only on its own addresses, and only its own page may change things."""
import unittest

import app as server


class NetworkGuardTest(unittest.TestCase):
    def setUp(self):
        self.client = server.app.test_client()

    def test_look_alike_names_are_refused(self):
        self.assertEqual(self.client.get('/api/projects', headers={'Host': 'evil.example:8003'}).status_code, 403)
        self.assertEqual(self.client.get('/api/projects', headers={'Host': 'localhost:8003'}).status_code, 200)
        self.assertEqual(self.client.get('/api/projects', headers={'Host': '192.168.1.20:8003'}).status_code, 200)

    def test_other_websites_cannot_change_anything(self):
        self.assertEqual(self.client.post('/api/queue/clear', headers={'Origin': 'https://evil.example'}).status_code, 403)
        self.assertEqual(self.client.post('/api/queue/clear', headers={'Origin': 'null'}).status_code, 403)
        self.assertEqual(self.client.post('/api/queue/clear', headers={'Origin': 'http://localhost'}).status_code, 200)

    def test_listens_on_this_computer_by_default(self):
        from pathlib import Path
        self.assertIn("os.environ.get('STORYROOM_HOST','127.0.0.1')", Path('app.py').read_text())


if __name__ == '__main__':
    unittest.main()
