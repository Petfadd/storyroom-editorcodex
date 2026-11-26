"""v15 CTA safeguards: matched lines listed, first moment only by default, bites never trigger."""
import tempfile
import unittest
from pathlib import Path

from PIL import Image

import channel_cta as cta


def tc(ms):
    s, ms = divmod(ms, 1000); m, s = divmod(s, 60); h, m = divmod(m, 60)
    return f'{h:02d}:{m:02d}:{s:02d},{ms:03d}'


BITE = '''Beat: 002
Type: DOCUMENTARY SOUND BITE
Narration Clock: PAUSED at 00:00:04,000
Narration State: PAUSED (Suspended at 00:00:04,000)
Full source: S01.mp4
Source IN: 00:00:10,000
Source OUT: 00:00:13,000
Footage Audio: UNMUTED (100% Dialogue Level, Clean)
Master timeline: 00:00:04,000 --> 00:00:07,000 (Duration: 3 sec)
Speaker: Witness
Exact Spoken Dialogue: Please subscribe and hit the bell, he told me.'''


def vo(n, n_in, n_out, m_in, words, first=False):
    clock = f'{tc(n_in)} --> {tc(n_out)}' if first else f'RESUMES at {tc(n_in)} --> {tc(n_out)}'
    return f'''Beat: {n:03d}
Type: VOICE OVER
Master timeline: {tc(m_in)} --> {tc(m_in + n_out - n_in)}
Narration Clock: {clock}
Narration State: {"PLAYING" if first else "RESUMING"}
Full source: S01.mp4
Source IN: {tc(n_in)}
Source OUT: {tc(n_out)}
Footage Audio: MUTED (0%)
Spoken Narration: {words}'''


class CTASafeguardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'assets').mkdir()
        Image.new('RGBA', (640, 360), (200, 0, 0, 255)).save(self.root / 'assets' / 'channel_cta.png')

    def tearDown(self):
        self.tmp.cleanup()

    def project(self, beats, settings=None):
        return {'id': 'p', 'channel_cta_asset': {'file': 'channel_cta.png'}, 'channel_cta': dict(settings or {}),
                'production_script': {'text': '\n\n'.join(beats)}}

    def test_sound_bite_dialogue_never_triggers_the_card(self):
        beats = [vo(1, 0, 4000, 0, 'Malia was two.', first=True), BITE,
                 vo(3, 4000, 8000, 7000, 'Police searched the river.')]
        self.assertEqual(cta.detect(self.project(beats), self.root), [])

    def test_matched_narration_lines_are_listed_with_film_times(self):
        beats = [vo(1, 0, 4000, 0, 'If you value these stories, subscribe.', first=True),
                 vo(2, 4000, 8000, 4000, 'Police searched the river.')]
        found = cta.detect(self.project(beats), self.root)
        self.assertEqual(len(found), 1)
        hit = [m for m in found[0]['matches'] if m['trigger']]
        self.assertEqual([(m['beat'], m['start_ms'], m['end_ms']) for m in hit], [('001', 0, 4000)])

    def test_two_moments_show_only_the_first_unless_all_is_chosen(self):
        beats = [vo(1, 0, 4000, 0, 'Subscribe and turn on notifications.', first=True),
                 vo(2, 4000, 8000, 4000, 'Police searched the river.'),
                 vo(3, 8000, 12000, 8000, 'Like this video if you want more.')]
        project = self.project(beats)
        self.assertEqual(len(cta.detect(project, self.root)), 2)
        self.assertEqual([(w['start_ms'], w['end_ms']) for w in cta.plan(project, self.root)], [(0, 4000)])
        project['channel_cta']['occurrences'] = 'all'
        self.assertEqual(len(cta.plan(project, self.root)), 2)

    def test_closing_question_without_trigger_words_does_not_trigger(self):
        beats = [vo(1, 0, 4000, 0, 'Subscribe for more cases.', first=True),
                 vo(2, 4000, 8000, 4000, 'What do you think really happened that night?')]
        self.assertEqual(len(cta.detect(self.project(beats), self.root)), 1)

    def test_occurrences_setting_is_validated(self):
        self.assertEqual(cta.validate_patch({'occurrences': 'all'}), {'occurrences': 'all'})
        with self.assertRaises(ValueError):
            cta.validate_patch({'occurrences': 'some'})


if __name__ == '__main__':
    unittest.main()
