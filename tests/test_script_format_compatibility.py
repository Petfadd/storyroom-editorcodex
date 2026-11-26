"""Regression: imported legacy Storyroom beats must not be misread as v5."""
import unittest
from pathlib import Path
from documentary_beats import is_strict_pipeline_script, read_beats


class ScriptFormatCompatibility(unittest.TestCase):
    def test_master_timeline_narration_clock_are_not_v5_markers(self):
        s = '''Beat: 001
Type: VOICE OVER
Master timeline: 00:00:00,000 --> 00:00:02,000
Narration clock: 00:00:00,000 --> 00:00:02,000
Narration state: PLAYING
Full source: S01.mp4
Source IN: 00:00:00,000
Source OUT: 00:00:02,000
Footage Audio: MUTED (0%)
Visual Direction: Actual location context
Continuity Note: B01 source range
'''
        self.assertFalse(is_strict_pipeline_script(s))
        beats = read_beats(s)
        self.assertEqual(beats[0]['source_file'], 'S01.mp4')
        self.assertEqual(beats[0]['narration_out_ms'], 2000)

    def test_former_v5_heading_is_accepted_without_strict_mode(self):
        script = """Documentary Production Pipeline v5
Beat: 001
Type: VOICE OVER
Master timeline: 00:00:00,000 --> 00:00:02,000
Narration clock: 00:00:00,000 --> 00:00:02,000
Narration state: PLAYING
Full source: S01.mp4
Source IN: 00:00:00,000
Source OUT: 00:00:02,000
Footage Audio: MUTED (0%)
Visual Direction: Actual location context
Continuity Note: B01 source range
"""
        self.assertFalse(is_strict_pipeline_script(script))
        self.assertEqual(len(read_beats(script)), 1)

    def test_east_st_louis_original_parser_fixed_script(self):
        path = Path('/mnt/data/EAST_ST_LOUIS_production_script_PARSER_FIXED.txt')
        if not path.exists():
            self.skipTest('Documentary fixture not mounted')
        script = path.read_text(encoding='utf-8')
        self.assertFalse(is_strict_pipeline_script(script))
        beats = read_beats(script)
        self.assertEqual(len(beats), 102)
        self.assertEqual(sum(b['kind'] == 'sound_bite' for b in beats), 30)
