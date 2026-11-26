import tempfile, unittest
from pathlib import Path

import visual_plan as vp
from documentary_beats import read_beats


def cue(n, a, b, text):
    return {'number': n, 'start_ms': a, 'end_ms': b, 'text': text}


GUIDE = '''# Editing guide

## Project setup

- Victim: Ana Ruiz
- Suspect: Ben Cole

## Script-by-script placement

### 1. Narration beat

**At:** "On May 1"
**Show:** The railroad track seen low, no people.
**Preview:** [Report, ~0:10-0:13](https://www.youtube.com/watch?v=AAAAAAAAAA1&t=10s) (`S01`).
**Label:** News 4 | May 2024.
**Care:** The tracks only. No people.
**Source ID:** S01
**Your timing:** `00:00:00,000 --> 00:00:03,000`

### 2. Narration beat

**At:** "Police respond"
**Fill:** C / police
**Show:** No footage exists; base images cover this.
**Your timing:** `00:00:03,000 --> 00:00:06,000`

## Base clips

| Save as | What it shows | Where to get it | Tag |
|---|---|---|---|
| `BASE-C--police--01.jpg` | A police car door. | `S01` https://www.youtube.com/watch?v=AAAAAAAAAA1, frame at 0:40 | police |
| `BASE-S--portrait+2024--02.jpg` | Booking photo of Ben Cole. | `S01` https://www.youtube.com/watch?v=AAAAAAAAAA1, frame at 0:50 | portrait+2024 |
'''


SCRIPT = '''Beat: 001

Type: VOICE OVER

Narration clock: RESUMES at 00:00:00,000 --> 00:00:12,000

Narration state: RESUMING

Full source: S02.mp4

Source in: 00:00:00,000

Source out: 00:00:12,000

Footage audio: MUTED (0%)

Visual direction: Street outside the apartment.

On-screen caption: Houston, 2020

--------------------------------------------------------------------------------

Beat: 002

Type: DOCUMENTARY SOUND BITE

Master timeline: 00:00:12,000 --> 00:00:17,000 (Duration: 5 sec)

Narration clock: PAUSED at 00:00:12,000

Narration state: PAUSED (Suspended for duration of bite)

Speaker: Chief

Full source: S03.mp4

Source in: 00:00:00,000

Source out: 00:00:05,000

Footage audio: UNMUTED (100% Dialogue Level, Clean)

--------------------------------------------------------------------------------

Beat: 003

Type: VOICE OVER

Narration clock: RESUMES at 00:00:12,000 --> 00:00:24,000

Narration state: RESUMING

Full source: S02.mp4

Source in: 00:00:12,000

Source out: 00:00:24,000

Footage audio: MUTED (0%)

Visual direction: Courthouse.
'''

CATALOG = {'sources': {'S01': {'duration': 60.0}, 'S02': {'duration': 60.0}},
           'shots': [
               {'source': 'S01', 'in': 0, 'out': 6, 'what': 'Railroad track and ballast, no people', 'tags': ['track'], 'kind': 'place'},
               {'source': 'S01', 'in': 6, 'out': 12, 'what': 'Police car with lights at the scene', 'tags': ['police'], 'kind': 'place'},
               {'source': 'S01', 'in': 12, 'out': 18, 'what': 'Booking photo mugshot of Ben Cole', 'tags': [], 'kind': 'place'},
               {'source': 'S01', 'in': 18, 'out': 24, 'what': 'Ana Ruiz smiling at the beach, a family photo', 'tags': [], 'kind': 'place'},
               {'source': 'S01', 'in': 24, 'out': 30, 'what': 'Courtroom with the judge on the bench in 2026', 'tags': ['court'], 'kind': 'place'},
               {'source': 'S01', 'in': 30, 'out': 40, 'what': 'Apartment complex street at dusk', 'tags': ['street'], 'kind': 'place'},
           ]}


class FootageAndPhotoRulesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'people').mkdir()
        from PIL import Image
        for n in ('ana', 'ben', 'mom', 'chief'):
            Image.new('RGB', (400, 500), (90, 90, 90)).save(self.root / 'people' / f'{n}.jpg')
        self.people = [{'id': 'v', 'name': 'Ana Ruiz', 'role': 'Victim', 'aliases': [], 'photo': {'path': 'people/ana.jpg'}},
                       {'id': 's', 'name': 'Ben Cole', 'role': 'Suspect', 'aliases': [], 'photo': {'path': 'people/ben.jpg'}},
                       {'id': 'm', 'name': 'Rosa Ruiz', 'role': 'Mother', 'aliases': [], 'photo': {'path': 'people/mom.jpg'}},
                       {'id': 'c', 'name': 'Dan Lee', 'role': 'Police chief', 'aliases': [], 'photo': {'path': 'people/chief.jpg'}}]
        self.assets = [{'id': n, 'name': n, 'original_name': n, 'kind': 'video', 'path': 'sources/' + n, 'duration': 60.0}
                       for n in ('S01.mp4', 'S02.mp4', 'S03.mp4')]

    def tearDown(self):
        self.tmp.cleanup()

    def run_plan(self, blocks, catalog=CATALOG):
        project = {'people': self.people, 'assets': self.assets, 'srt': {'blocks': blocks}, 'voiceover': {'duration': 24.0},
                   'production_script': {'text': SCRIPT}}
        original = vp.build_catalogue
        vp.build_catalogue = lambda p, r, g=None, b=None, broll_catalog=None: original(p, r, g, b, catalog)
        try:
            return vp.plan(project, self.root)
        finally:
            vp.build_catalogue = original

    def test_name_cards_step_aside_when_a_plan_is_applied(self):
        import person_overlays as po
        project = {'people': self.people, 'srt': {'blocks': [cue(1, 0, 3000, 'Ana Ruiz')]}, 'voiceover': {'duration': 3.0},
                   'visual_plan_applied': {'at': 1}}
        self.assertEqual(po.plan(project, self.root)['windows'], [])
        # Portraits require an explicit project enablement AND person's approval.
        # A visual-plan opt-in alone must never show an unapproved photo.
        project['person_overlay_settings'] = {'with_visual_plan': True, 'enabled': True}
        project['people'][0]['show'] = True
        self.assertEqual(len(po.plan(project, self.root)['windows']), 1)


if __name__ == '__main__':
    unittest.main()
