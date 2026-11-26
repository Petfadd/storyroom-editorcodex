"""The shipped templates must be valid: the guide, the worked example and the footage sheet."""
import unittest
from pathlib import Path

import footage_downloader as fd
from documentary_beats import read_beats

FOLDER = Path(__file__).resolve().parent.parent / 'production-script-templates'
GUIDE = FOLDER / 'documentary-production-script-template.txt'
EXAMPLE = FOLDER / 'Worked_Example_Production_Script.txt'
SHEET = FOLDER / 'Footage_Sheet_Template.md'


class TemplateTest(unittest.TestCase):
    def setUp(self):
        self.guide = GUIDE.read_text(encoding='utf-8')
        self.example = EXAMPLE.read_text(encoding='utf-8')

    def test_the_guide_alone_holds_no_beat(self):
        # The guide explains the fields; uploading it by mistake must not build a film.
        with self.assertRaises(ValueError):
            read_beats(self.guide)

    def test_the_guide_explains_both_beat_kinds_and_photos(self):
        for words in ('VOICE OVER', 'DOCUMENTARY SOUND BITE', 'Treatment: PHOTO', 'Cut Action', 'Spoken Narration'):
            self.assertIn(words, self.guide)

    def test_the_worked_example_reads_without_errors(self):
        beats = read_beats(self.example)
        self.assertEqual([b['kind'] for b in beats],
                         ['narration', 'narration', 'sound_bite', 'narration', 'narration', 'narration'])
        bite = beats[2]
        self.assertEqual(bite['pause_ms'], 8000)
        self.assertEqual(beats[3]['narration_in_ms'], 8000)          # resumes where it paused

    def test_the_narration_clock_never_jumps(self):
        narration = [b for b in read_beats(self.example) if b['kind'] == 'narration']
        for a, b in zip(narration, narration[1:]):
            self.assertEqual(a['narration_out_ms'], b['narration_in_ms'])

    def test_every_source_range_matches_its_beat(self):
        for b in read_beats(self.example):
            length = b['narration_out_ms'] - b['narration_in_ms'] if b['kind'] == 'narration' else b['duration_ms']
            self.assertEqual(b['source_out_ms'] - b['source_in_ms'], length, b['label'])

    def test_the_footage_sheet_names_every_file_the_script_uses(self):
        sheet = fd.parse_manifest(SHEET.read_text(encoding='utf-8'))
        self.assertEqual(sheet['issues'], [])
        named = {e['filename'] for e in sheet['entries']}
        self.assertTrue(set(fd.script_needs(self.example)) <= named)

    def test_the_example_shows_a_cta_and_a_script_transition(self):
        import channel_cta
        beats = read_beats(self.example)
        self.assertTrue(any('subscribe' in (b.get('spoken_narration') or '').lower() for b in beats))
        self.assertTrue(any((b.get('cut_action') or '').upper() == 'DIP TO BLACK' for b in beats))
        self.assertTrue(channel_cta._windows(channel_cta._from_beats(self.example)))


if __name__ == '__main__':
    unittest.main()
