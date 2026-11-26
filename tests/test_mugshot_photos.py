"""A mugshot never pops up before the narration reaches the arrest.

Found on the Maliyah Bass sheet: the only photos of the mother were booking photos,
and the opening names her at 0:36. The editor showed a person's first photo at every
mention in the opening, so her mugshot would have appeared before any arrest was said.
"""
import unittest
from person_overlays import arrest_ms, is_mugshot
import person_overlays as PO
import tests.test_sheet_photos as base
import json
from PIL import Image


class MugshotRulesTest(unittest.TestCase):
    def test_words_that_mark_a_mugshot(self):
        self.assertTrue(is_mugshot('Suspect — mother. Mugshot (Houston Police Department)'))
        self.assertTrue(is_mugshot('booking photo, released by HPD'))
        self.assertFalse(is_mugshot('news-obtained photograph, grey wall'))

    def test_the_arrest_line(self):
        blocks = [{'number': 1, 'start_ms': 0, 'end_ms': 3000, 'text': 'Sahara Ervin called 911'},
                  {'number': 2, 'start_ms': 3000, 'end_ms': 6000, 'text': 'Weeks later, police arrested Sahara Ervin'}]
        self.assertEqual(arrest_ms(blocks), 3000)
        self.assertIsNone(arrest_ms(blocks[:1]))


class MugshotPlanTest(unittest.TestCase):
    def plan(self, mugshot):
        import tempfile
        from pathlib import Path
        root = Path(tempfile.mkdtemp())
        (root / 'people').mkdir()
        Image.new('RGB', (800, 800), (90, 90, 90)).save(root / 'people' / 'sahara.jpg')
        project = {'voiceover': {'duration': 12.0}, 'scenes': [],
                   'person_overlay_settings': {'enabled': True},
                   'srt': {'blocks': [
                       {'number': 1, 'start_ms': 0, 'end_ms': 3000, 'text': 'Sahara Ervin called 911 that morning'},
                       {'number': 2, 'start_ms': 3000, 'end_ms': 6000, 'text': 'She said her daughter had vanished'},
                       {'number': 3, 'start_ms': 6000, 'end_ms': 9000, 'text': 'In October, police arrested Sahara Ervin'},
                       {'number': 4, 'start_ms': 9000, 'end_ms': 12000, 'text': 'Sahara Ervin was booked into the county jail'}]},
                   'people': [{'id': 'm', 'name': 'Sahara Ervin', 'role': 'Mother', 'aliases': [], 'show': True,
                               'photo': {'path': 'people/sahara.jpg', 'mugshot': mugshot}}]}
        return PO.plan(project, root, sound_plan={'bites': []})

    def test_a_mugshot_waits_for_the_arrest(self):
        result = self.plan(True)
        cues = sorted(c for w in result['windows'] for c in w['cues'])
        self.assertNotIn(1, cues)                       # 0:00 "Sahara Ervin called 911": no mugshot
        self.assertTrue(set(cues) & {3, 4})              # shown once the arrest is narrated
        self.assertTrue(any('mugshot' in n for n in result['notes']))

    def test_a_normal_photo_shows_from_the_first_mention(self):
        cues = sorted(c for w in self.plan(False)['windows'] for c in w['cues'])
        self.assertIn(1, cues)


class MugshotSheetTest(base.SheetPhotosTest):
    """Through the real importer: which photo the person gets."""

    def setUp(self):
        super().setUp()
        Image.new('RGB', (800, 800), (90, 90, 90)).save(self.www / 'booking.jpg')
        Image.new('RGB', (800, 800), (150, 60, 60)).save(self.www / 'portrait.jpg')

    def person(self, name):
        p = json.loads((PO.Path(self.tmp) / 'projects' / self.pid / 'project.json').read_text())
        return next(x for x in p['people'] if x['name'] == name)

    def test_a_non_booking_photo_wins_whatever_the_order(self):
        b = self.base
        self.run_sheet(f"""| Photo | Person | Role | Link |
|---|---|---|---|
| P04 | Sahara Ervin | Mother. Mugshot (Houston Police Department) | {b}/booking.jpg |
| P05 | Sahara Ervin | Mother. News photograph | {b}/portrait.jpg |
""")
        photo = self.person('Sahara Ervin')['photo']
        self.assertEqual(photo['name'], 'P05.jpg')
        self.assertFalse(photo['mugshot'])

    def test_photos_are_named_filed_and_matched_to_the_narration(self):
        self.skipTest('runs in test_sheet_photos')

    def test_broll_is_filed_by_what_it_is_and_keeps_its_description(self):
        self.skipTest('runs in test_sheet_photos')

    def test_running_the_sheet_again_downloads_nothing_new(self):
        self.skipTest('runs in test_sheet_photos')

    def test_a_mugshot_alone_is_marked(self):
        b = self.base
        self.run_sheet(f"""| Photo | Person | Role | Link |
|---|---|---|---|
| P04 | Sahara Ervin | Mother. Mugshot | {b}/booking.jpg |
""")
        self.assertTrue(self.person('Sahara Ervin')['photo']['mugshot'])
