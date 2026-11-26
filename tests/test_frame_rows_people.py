import unittest
import footage_downloader as f

LINK = 'https://www.youtube.com/watch?v=x1eVAdMDW5k'


class FrameRowsAddPeople(unittest.TestCase):
    def rows(self, text):
        return {e['named']: e for e in f.parse_manifest(text)['entries']}

    def test_frame_row_with_name_and_role_is_that_persons_photo(self):
        e = self.rows(f'| B15.jpg | Patricia May | Victim - the grandmother, 74 | 1:07-1:08 | {LINK} |')['B15.jpg']
        self.assertEqual((e['person'], e['role'], e['window']), ('Patricia May', 'Victim', (67.0, 68.0)))

    def test_for_people_prefix_names_the_person(self):
        e = self.rows(f'| B03 | B03.jpg | FOR PEOPLE: Santosha Scott — KSDK interview | 0:40-0:41 | {LINK} |')['B03.jpg']
        self.assertEqual(e['person'], 'Santosha Scott')

    def test_place_stills_and_clips_name_nobody(self):
        r = self.rows(f'| B04 | B04.jpg | Gompers Homes front door | 1:00-1:01 | {LINK} |\n'
                      f'| B05 | B05.mp4 | Jones Park, the car | 1:00-1:05 | {LINK} |')
        self.assertEqual(r['B04.jpg']['person'], '')
        self.assertEqual(r['B05.mp4']['person'], '')
