"""People rows in a footage sheet: a timestamp per photo, titles, middle initials."""
import unittest
from unittest.mock import patch

import footage_downloader as fd

SHEET = """## People (photos)
| Photo | Person | Role | Link | Timestamp | Verification Method |
|---|---|---|---|---|---|
| P01 | Patricia May | Victim (Grandmother, Age 74) | https://www.youtube.com/watch?v=SdnGCOwwn2c | 00:00:38 | Name and portrait graphic |
| P02 | Cherie L. May | Victim (Aunt, Age 49) | https://www.youtube.com/watch?v=SdnGCOwwn2c | 00:00:35 | Name graphic |
| P06 | Tiffany Thompson | Victim / Survivor | MISSING | — | No clean portrait |
| P14 | Director Brendan Kelly | Illinois State Police Director | https://www.youtube.com/watch?v=H8RDIchA3bI | 00:00:15 | Podium |
| P20 | Jane Roe | Witness | https://www.youtube.com/watch?v=SdnGCOwwn2c | 1:05 | Interview |
| P21 | John Roe | Witness | https://www.youtube.com/watch?v=SdnGCOwwn2c | Age 52 | no time given |

## B-roll
| ID | File | What it shows | Window | Link |
|---|---|---|---|---|
| B04 | B04.jpg | FOR PEOPLE: Patricia May — portrait | 00:00:38–00:00:39 | https://www.youtube.com/watch?v=SdnGCOwwn2c |
| B12 | B12.jpg | FOR PEOPLE: Director Brendan Kelly — at podium | 00:00:15–00:00:16 | https://www.youtube.com/watch?v=H8RDIchA3bI |
| B08 | B08.mp4 | Wide pan of the complex | 00:00:50–00:00:55 | https://www.youtube.com/watch?v=SdnGCOwwn2c |
"""


class SheetPeople(unittest.TestCase):
    def setUp(self):
        self.r = fd.parse_manifest(SHEET)
        self.by = {e['source_id']: e for e in self.r['entries']}

    def test_each_photo_row_takes_its_own_frame(self):
        self.assertEqual(self.by['P01']['window'], (38.0, 39.0))
        self.assertEqual(self.by['P02']['window'], (35.0, 36.0))
        self.assertEqual(self.by['P20']['window'], (65.0, 66.0))
        # Same video, different times: two downloads, not one picture saved twice.
        self.assertFalse([i for i in self.r['issues'] if i['kind'] == 'duplicate_link'])

    def test_an_age_is_not_a_time(self):
        self.assertIsNone(self.by['P21']['window'])

    def test_a_video_row_keeps_its_range(self):
        self.assertEqual(self.by['B08']['window'], (50.0, 55.0))

    def test_title_moves_to_the_role(self):
        self.assertEqual((self.by['P14']['person'], self.by['P14']['role']), ('Brendan Kelly', 'Director'))
        self.assertEqual(self.by['B12']['person'], 'Brendan Kelly')
        self.assertEqual(fd._split_title('Chief Art Acevedo', ''), ('Art Acevedo', 'Chief'))
        self.assertEqual(fd._split_title('Chief Keef', ''), ('Chief Keef', ''))      # two words: kept as a name

    def test_missing_link_is_reported_not_downloaded(self):
        self.assertNotIn('P06', self.by)
        self.assertTrue(any(i['kind'] == 'missing_link' and 'P06' in i['text'] for i in self.r['issues']))

    def test_photo_with_a_time_takes_the_frame_not_the_thumbnail(self):
        with patch.object(fd, '_frame_at', return_value='frame.jpg') as frame:
            out = fd.fetch_photo(self.by['P01'], '/tmp/sheet-test', {}, lambda **k: None, None)
        self.assertEqual(out, 'frame.jpg'); self.assertEqual(frame.call_args[0][2], 38.0)


class MiddleInitials(unittest.TestCase):
    def test_name_without_initial_is_an_alias(self):
        import tempfile
        from pathlib import Path
        from PIL import Image
        import app as server
        with tempfile.TemporaryDirectory() as tmp, patch.object(server, 'PROJECTS', Path(tmp)):
            c = server.app.test_client()
            pid = c.post('/api/projects', json={'title': 'Alias test'}).get_json()['id']
            img = Path(tmp) / 'p.jpg'; Image.new('RGB', (400, 400), 'teal').save(img)
            row = {'filename': 'P02.jpg', 'person': 'Cherie L. May', 'role': 'Victim', 'source_id': 'P02',
                   'url': 'https://www.youtube.com/watch?v=SdnGCOwwn2c', 'line': 4, 'description': ''}
            server.register_downloaded_photo(pid, row, img)
            person = server.load(pid)['people'][0]
            self.assertEqual(person['name'], 'Cherie L. May')
            self.assertIn('Cherie May', person['aliases'])


if __name__ == '__main__':
    unittest.main()
