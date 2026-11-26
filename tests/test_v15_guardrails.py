"""v15 guardrails: things the V8.10 workflow depends on exactly.

* The interview picture-cutaway format and checks are unchanged.
* Films that END ON THE NARRATOR (final soundbite -> closing narration -> CTA-02) build,
  and nothing assumes a soundbite is last.
* Name graphics use the person's name exactly as written.
* The Setup cutaway upload uses the same import (rows arrive unapproved).
"""
import json
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

from PIL import Image

import app as server
import person_overlays as po
from documentary_cutaways import parse, split_spans
from documentary_storyboard import prepare
from tests.test_documentary_cutaways import source_event


def tc(ms):
    s, ms = divmod(ms, 1000); m, s = divmod(s, 60); h, m = divmod(m, 60)
    return f'{h:02d}:{m:02d}:{s:02d},{ms:03d}'


class CutawayFormatUnchanged(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name); (self.root / 'sources').mkdir()
        for f in ('S01.mp4', 'S02.mp4', 'B10.jpg'):
            (self.root / 'sources' / f).write_bytes(b'fixture')
        self.project = {'documentary_cutaways': [], 'scenes': [{'id': 'sb1', 'plan_row': {'script_beat': '028'}}],
                        'assets': [{'id': 'speaker', 'kind': 'video', 'original_name': 'S01.mp4', 'path': 'sources/S01.mp4', 'duration': 30, 'revision': 'r1'},
                                   {'id': 'video', 'kind': 'video', 'original_name': 'S02.mp4', 'path': 'sources/S02.mp4', 'duration': 30, 'revision': 'r2'},
                                   {'id': 'image', 'kind': 'image', 'original_name': 'B10.jpg', 'path': 'sources/B10.jpg', 'revision': 'r3'}]}

    def tearDown(self):
        self.temp.cleanup()

    def handoff(self, **changes):
        row = {'id': 'CUTAWAY-001', 'soundbite_beat': '028', 'speaker_source': 'S01.mp4',
               'timeline_in': '00:00:05.000', 'timeline_out': '00:00:10.000', 'picture_source': 'S02.mp4',
               'source_in': '00:00:12.000', 'source_out': '00:00:17.000', 'reason': 'Verified roadway'}
        row.update(changes)
        return json.dumps({'version': 1, 'cutaways': [row]})

    def test_handoff_json_rows_arrive_unapproved(self):
        rows = parse(self.handoff())
        self.assertEqual((rows[0]['id'], rows[0]['soundbite_beat'], rows[0]['approved']), ('CUTAWAY-001', '028', False))
        self.assertEqual((rows[0]['timeline_in_ms'], rows[0]['timeline_out_ms']), (5000, 10000))

    @patch('strict_cuts.source_rate', return_value=Fraction(30))
    def test_identity_checks_still_fail_closed(self, _):
        for changes in ({'soundbite_beat': '009'}, {'speaker_source': 'S09.mp4'}, {'picture_source': 'ghost.mp4'},
                        {'timeline_out': '00:00:21.000'}):
            rows = parse(self.handoff(**changes))
            rows[0]['approved'] = True
            self.project['documentary_cutaways'] = rows
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                split_spans(self.project, self.root, [source_event()], Fraction(30))

    @patch('strict_cuts.source_rate', return_value=Fraction(30))
    def test_approval_is_tied_to_the_script_hash(self, _):
        rows = parse(self.handoff())
        rows[0].update(approved=True, approved_script_sha256='0' * 64)
        self.project['documentary_cutaways'] = rows
        self.project['production_script'] = {'text': 'a different script'}
        with self.assertRaises(ValueError):
            split_spans(self.project, self.root, [source_event()], Fraction(30))

    def test_stills_use_na_picture_in_and_out(self):
        rows = parse(self.handoff(picture_source='B10.jpg', source_in='N/A', source_out='N/A'))
        self.assertEqual((rows[0]['source_in_ms'], rows[0]['source_out_ms']), (None, None))


class FilmsEndOnTheNarrator(unittest.TestCase):
    """final soundbite -> narrator closing reflection -> CTA-02 (no trigger words)."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        (self.root / 'sources').mkdir(); (self.root / 'inputs').mkdir()
        (self.root / 'sources' / 'video.mp4').write_bytes(b'video'); (self.root / 'inputs' / 'voice.wav').write_bytes(b'voice')

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_script_that_ends_on_voice_over_builds(self):
        beats = [f'''Beat: 001
Type: VOICE OVER
Narration Clock: 00:00:00,000 --> 00:00:04,000
Narration State: PLAYING
Full source: S01.mp4
Source IN: 00:00:00,000
Source OUT: 00:00:04,000
Footage Audio: MUTED (0%)''', f'''Beat: 002
Type: DOCUMENTARY SOUND BITE
Narration Clock: PAUSED at 00:00:04,000
Narration State: PAUSED (Suspended at 00:00:04,000)
Full source: S01.mp4
Source IN: 00:00:10,000
Source OUT: 00:00:12,000
Footage Audio: UNMUTED (100% Dialogue Level, Clean)
Master timeline: 00:00:04,000 --> 00:00:06,000 (Duration: 2 sec)''', f'''Beat: 003
Type: VOICE OVER
Narration Clock: RESUMES at 00:00:04,000 --> 00:00:08,000
Narration State: RESUMING
Full source: S01.mp4
Source IN: 00:00:04,000
Source OUT: 00:00:08,000
Footage Audio: MUTED (0%)
Spoken Narration: What do you think really happened that night?''']
        project = {'profile': 'documentary', 'scenes': [], 'production_script': {'text': '\n\n'.join(beats)},
                   'voiceover': {'path': 'inputs/voice.wav', 'name': 'voice.wav', 'duration': 8},
                   'srt': {'blocks': [{'number': 1, 'start_ms': 0, 'end_ms': 4000, 'text': 'Opening'},
                                      {'number': 2, 'start_ms': 4000, 'end_ms': 8000, 'text': 'What do you think really happened that night?'}]},
                   'assets': [{'id': 'a', 'name': 'S01.mp4', 'original_name': 'S01.mp4', 'kind': 'video',
                               'path': 'sources/video.mp4', 'duration': 20, 'revision': 'v1'}]}
        staged, plan = prepare(project, self.root, [], [], False, lambda _: True)
        self.assertEqual(len(plan['bites']), 1)
        last = staged['scenes'][-1]
        self.assertNotIn('bite_id', last['plan_row'])                    # the film ends on narration
        self.assertEqual(last['frame_out'], 300)                          # 8 s narration + 2 s bite


class NamesAsWritten(unittest.TestCase):
    def test_name_card_uses_the_person_name_exactly(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'people').mkdir()
            Image.new('RGB', (300, 420), (110, 100, 90)).save(root / 'people' / 'a.jpg')
            person = {'id': 'p', 'name': "Ja'Nya D. McKenzie-Ruiz", 'role': 'Victim', 'photo': {'path': 'people/a.jpg'},
                      'show': True, 'photo_over_video': True}
            project = {'people': [person], 'assets': [], 'scenes': [], 'voiceover': {'duration': 6},
                       'srt': {'blocks': [{'number': 1, 'start_ms': 0, 'end_ms': 3000, 'text': "Ja'Nya D. McKenzie-Ruiz was nine"}]},
                       'person_overlay_settings': {'enabled': True, 'style': 'full'}}
            w = po.plan(project, root, {'version': 1, 'revision': 1, 'bites': []})['windows'][0]
            self.assertEqual(w['name'], "Ja'Nya D. McKenzie-Ruiz")
            self.assertTrue(w['name_intro'])


class SetupCutawayUpload(unittest.TestCase):
    def test_setup_card_posts_to_the_same_import(self):
        js = (Path(__file__).resolve().parents[1] / 'static' / 'documentary.js').read_text(encoding='utf-8')
        start = js.index('async function setupUploadCutaways')
        body = js[start:js.index('\n}', start)]
        self.assertIn('/documentary-cutaways', body)
        self.assertIn('{ledger,', body)                # the file text goes through parse() unchanged
        self.assertNotIn('approved:true', body.replace(' ', ''))   # Setup never approves rows itself
        studio = (Path(__file__).resolve().parents[1] / 'static' / 'studio.js').read_text(encoding='utf-8')
        self.assertIn('cutawaySetupCardHTML()', studio)


class PreviewEqualsExportWindows(unittest.TestCase):
    def test_client_report_and_renderer_use_the_same_windows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'people').mkdir()
            Image.new('RGB', (300, 420), (110, 100, 90)).save(root / 'people' / 'a.jpg')
            person = {'id': 'p', 'name': 'Test Person', 'role': 'Victim', 'photo': {'path': 'people/a.jpg'},
                      'show': True, 'photo_over_video': True}
            project = {'id': 'x', 'people': [person], 'assets': [], 'scenes': [], 'voiceover': {'duration': 20},
                       'srt': {'blocks': [{'number': 1, 'start_ms': 0, 'end_ms': 3000, 'text': 'Test Person smiled'},
                                          {'number': 2, 'start_ms': 3300, 'end_ms': 6000, 'text': 'she waved'},
                                          {'number': 3, 'start_ms': 12000, 'end_ms': 15000, 'text': 'Test Person left'}]},
                       'person_overlay_settings': {'enabled': True, 'style': 'full'}}
            sound = {'version': 1, 'revision': 1, 'bites': []}
            report = po.plan(project, root, sound)['windows']
            cache = {}
            po.render_filters(project, root, sound, 320, 180, '30', root, 1, cache=cache)
            self.assertEqual([(w['start_ms'], w['end_ms'], w['cues']) for w in report],
                             [(w['start_ms'], w['end_ms'], w['cues']) for w in cache['plan']['windows']])
            self.assertEqual([(w['start_ms'], w['end_ms']) for w in report], [(0, 6000), (12000, 15000)])


if __name__ == '__main__':
    unittest.main()
