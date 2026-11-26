"""Beat-built storyboards: render checks honour what the build already settled."""
import unittest

import documentary_cue_groups as cg


def scene(cue, beat):
    return {'id': f's{cue}{beat}', 'asset_id': 'a',
            'plan_row': {'srt_blocks': [cue], 'continuity': f'Documentary beat {beat}'}}


def project(beat_built, scenes):
    p = {'srt': {'blocks': [{'number': n, 'text': f'line {n}', 'start_ms': n * 1000,
                             'end_ms': n * 1000 + 900} for n in (1, 2, 3)]},
         'scenes': scenes}
    if beat_built:
        p['documentary_beat_review'] = {'approved_overlaps': [[3, 7]], 'repeated_ranges': []}
    return p


class CueGroupsTest(unittest.TestCase):
    def test_a_line_sharing_its_neighbours_picture_is_covered(self):
        result = cg.groups(project(True, [scene(1, 5), scene(3, 6)]))
        self.assertEqual(result[1]['shares_picture_with_cue'], 1)
        self.assertEqual(result[1]['slots'], [])

    def test_other_storyboards_still_need_a_slot_per_line(self):
        with self.assertRaisesRegex(ValueError, 'cue 2 has no picture slot'):
            cg.groups(project(False, [scene(1, 5), scene(3, 6)]))


class ApprovedRepeatTest(unittest.TestCase):
    def setUp(self):
        import app
        self.app = app

    def errors(self, beat_built):
        scenes = [scene(1, 3), scene(1, 4), scene(2, 7), scene(3, 8)]
        msgs = ['Scene 3: replays source footage from scene 1 inside the 6-slot cooldown (the intervals overlap by 5.20s).',
                'Scene 4: replays source footage from scene 2 inside the 6-slot cooldown (the intervals overlap by 1.00s).']
        return self.app._unapproved_repeats(project(beat_built, scenes), msgs)

    def test_a_repeat_approved_at_build_time_is_not_raised_again(self):
        kept = self.errors(True)
        self.assertEqual(len(kept), 1)
        self.assertTrue(kept[0].startswith('Scene 4:'))   # beats 4 and 8 were never approved

    def test_non_beat_projects_are_unchanged(self):
        self.assertEqual(len(self.errors(False)), 2)


if __name__ == '__main__':
    unittest.main()


class CleanCutTest(unittest.TestCase):
    """A cut to another file must never blank the monitor."""

    def setUp(self):
        from pathlib import Path
        self.js = Path('static/documentary_timeline.js').read_text()
        self.css = Path('static/editor.css').read_text()

    def test_standby_is_laid_out_so_chrome_decodes_it(self):
        self.assertIn('.monitor video.doc-standby{display:block!important;opacity:0', self.css)
        self.assertIn("node.classList.add('doc-standby')", self.js)

    def test_a_missed_preroll_loads_into_the_standby_not_the_live_picture(self):
        self.assertIn('await docSwapInto(part,asset,t,playing,d);return', self.js)

    def test_a_late_preroll_holds_the_outgoing_picture(self):
        self.assertIn('performance.now()-docWaitSince<1500', self.js)
