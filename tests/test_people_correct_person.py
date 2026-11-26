"""The right person on screen: every line listed, wrong ones switchable, relatives redirected."""
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from PIL import Image

import app as server
from person_overlays import find_mentions

# Short (one-word) names are opt-in per person since v11; these people opt in.
PEOPLE = [{'id': 'v', 'name': 'Maliyah Bass', 'role': 'Victim', 'aliases': ['Malia', 'Malia Bass'], 'short_names': True},
          {'id': 'm', 'name': 'Sahara Ervin', 'role': 'Mother', 'aliases': ['Sahara Irvin', 'Irvin'], 'short_names': True},
          {'id': 's', 'name': 'Travion Thompson', 'role': 'Suspect', 'aliases': [], 'skip_cues': [4], 'short_names': True}]
BLOCKS = [{'number': 1, 'start_ms': 0, 'end_ms': 3000, 'text': 'Malia Bass had vanished'},
          {'number': 2, 'start_ms': 3000, 'end_ms': 6000, 'text': "Malia's mother called 911"},
          {'number': 3, 'start_ms': 6000, 'end_ms': 9000, 'text': "Thompson's lawyer said nothing"},
          {'number': 4, 'start_ms': 9000, 'end_ms': 12000, 'text': 'Travion Thompson spoke to cameras'},
          {'number': 5, 'start_ms': 12000, 'end_ms': 15000, 'text': 'Sahara stepped inside'}]


class MentionTest(unittest.TestCase):
    def test_a_relative_line_shows_the_relative(self):
        shown = {(m['cue'], m['person_id']) for m in find_mentions(BLOCKS, PEOPLE)}
        self.assertIn((2, 'm'), shown)            # "Malia's mother" -> the mother
        self.assertNotIn((2, 'v'), shown)         # ... never Maliyah

    def test_a_relative_nobody_added_shows_nobody(self):
        shown = {(m['cue'], m['person_id']) for m in find_mentions(BLOCKS, PEOPLE)}
        self.assertNotIn((3, 's'), shown)         # "Thompson's lawyer" is not Thompson
        blocked = {m['cue']: m['blocked'] for m in find_mentions(BLOCKS, PEOPLE, keep_blocked=True) if m.get('blocked')}
        self.assertIn('lawyer', blocked[3])

    def test_another_persons_mother_is_not_the_victims_mother(self):
        people = PEOPLE + [{'id': 'a', 'name': 'Angel Harris', 'role': "Suspect's mother", 'aliases': []}]
        blocks = [{'number': 9, 'start_ms': 0, 'end_ms': 3000, 'text': "Thompson's mother spoke"}]
        self.assertEqual([m['person_id'] for m in find_mentions(blocks, people)], ['a'])
        self.assertEqual([m['person_id'] for m in find_mentions(blocks, PEOPLE)], [])   # never Sahara

    def test_a_line_can_be_switched_off(self):
        shown = {(m['cue'], m['person_id']) for m in find_mentions(BLOCKS, PEOPLE)}
        self.assertNotIn((4, 's'), shown)
        blocked = {m['cue']: m['blocked'] for m in find_mentions(BLOCKS, PEOPLE, keep_blocked=True) if m.get('blocked')}
        self.assertEqual(blocked[4], 'turned off for this line')

    def test_short_name_matches_are_flagged(self):
        sahara = [m for m in find_mentions(BLOCKS, PEOPLE) if m['cue'] == 5][0]
        self.assertTrue(sahara['short'])
        full = [m for m in find_mentions(BLOCKS, PEOPLE) if m['cue'] == 1][0]
        self.assertFalse(full['short'])


class PeopleEndpointTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.old = server.PROJECTS
        server.PROJECTS = self.tmp
        self.pid = 'abcdefabcdef0042'
        (self.tmp / self.pid).mkdir()
        (self.tmp / self.pid / 'project.json').write_text(json.dumps({
            'id': self.pid, 'title': 'T', 'edit_mode': 'documentary', 'updated': 1.0, 'brief': '',
            'assets': [], 'scenes': [], 'people': [], 'voiceover': None, 'srt': {'blocks': BLOCKS}}))
        self.client = server.app.test_client()

    def tearDown(self):
        server.PROJECTS = self.old
        shutil.rmtree(self.tmp, ignore_errors=True)

    def photo(self, fmt):
        buf = io.BytesIO()
        Image.new('RGB', (400, 500), (120, 80, 60)).save(buf, fmt)
        buf.seek(0)
        return buf

    def test_any_photo_type_and_srt_spellings(self):
        r = self.client.post(f'/api/projects/{self.pid}/people', content_type='multipart/form-data',
                             data={'name': 'Maliyah Bass', 'role': 'Victim', 'find_spellings': '1',
                                   'photo': (self.photo('GIF'), 'm.gif')})
        self.assertEqual(r.status_code, 200, r.get_json())
        person = r.get_json()['people'][0]
        self.assertTrue(person['photo']['path'].endswith('.jpg'))      # GIF converted
        # SRT spellings are suggestions to approve, never silently trusted as aliases.
        self.assertIn('Malia Bass', person['suggested_aliases'])
        r = self.client.post(f'/api/projects/{self.pid}/people', content_type='multipart/form-data',
                             data={'name': 'Sahara Ervin', 'role': 'Mother', 'photo': (self.photo('BMP'), 's.bmp')})
        self.assertEqual(r.status_code, 200, r.get_json())

    def test_switching_a_line_off_and_on(self):
        self.client.post(f'/api/projects/{self.pid}/people', content_type='multipart/form-data',
                         data={'name': 'Maliyah Bass', 'role': 'Victim', 'aliases': 'Malia Bass',
                               'photo': (self.photo('PNG'), 'm.png')})
        pid_person = json.loads((self.tmp / self.pid / 'project.json').read_text())['people'][0]['id']
        r = self.client.post(f'/api/projects/{self.pid}/people', content_type='multipart/form-data',
                             data={'id': pid_person, 'name': 'Maliyah Bass', 'skip_cues': '1'})
        moments = r.get_json()['person_overlays']['moments'][pid_person]
        self.assertEqual([m['blocked'] for m in moments if m['cue'] == 1], ['turned off for this line'])
        r = self.client.post(f'/api/projects/{self.pid}/people', content_type='multipart/form-data',
                             data={'id': pid_person, 'name': 'Maliyah Bass', 'skip_cues': ''})
        moments = r.get_json()['person_overlays']['moments'][pid_person]
        self.assertEqual([m['blocked'] for m in moments if m['cue'] == 1], [''])

    def test_a_file_that_is_not_a_photo_is_refused(self):
        r = self.client.post(f'/api/projects/{self.pid}/people', content_type='multipart/form-data',
                             data={'name': 'X Y', 'photo': (io.BytesIO(b'not a picture at all' * 20), 'x.jpg')})
        self.assertEqual(r.status_code, 400)


if __name__ == '__main__':
    unittest.main()


class OpeningRuleTest(unittest.TestCase):
    def test_opening_ends_after_the_chosen_scenes(self):
        from person_overlays import opening_end_ms
        bites = {'bites': [{'pause_s': 0}, {'pause_s': 33.5}, {'pause_s': 57.2}, {'pause_s': 90}]}
        self.assertEqual(opening_end_ms('scene1', bites, 300000), 33500)     # a bite at 0 is not a scene end
        self.assertEqual(opening_end_ms('scene2', bites, 300000), 57200)
        self.assertEqual(opening_end_ms('half', bites, 300000), 150000)
        self.assertEqual(opening_end_ms('always', bites, 300000), float('inf'))
        self.assertEqual(opening_end_ms('scene2', {'bites': []}, 300000), 150000)  # no bites: first half

    def test_the_setting_is_validated(self):
        from person_overlays import clean_settings, settings
        self.assertEqual(clean_settings({'photo_opening': 'scene1'}), {'photo_opening': 'scene1'})
        with self.assertRaises(ValueError):
            clean_settings({'photo_opening': 'sometimes'})
        self.assertEqual(settings({})['photo_opening'], 'scene2')
