import unittest
import app


class BiteReuseApproval(unittest.TestCase):
    """An approved Beat overlap that involves a sound bite must not block export."""

    def project(self, approved):
        narr = {'plan_row': {'continuity': 'Documentary beat 100', 'script_beat': '100'}}
        bite = {'plan_row': {'continuity': 'Documentary beat sound-bite', 'script_beat': '101'}}
        return {'scenes': [narr, bite],
                'documentary_beat_review': {'approved_overlaps': approved}}

    def test_bite_scene_reads_its_beat(self):
        self.assertEqual(app.scene_beat({'plan_row': {'continuity': 'Documentary beat sound-bite',
                                                      'script_beat': '039'}}), 39)
        self.assertIsNone(app.scene_beat({'plan_row': {'script_beat': 'approved-gap',
                                                       'continuity': 'Documentary beat approved-gap'}}))

    def test_approved_bite_repeat_is_dropped(self):
        err = ['Scene 2: replays source footage from scene 1 inside the 6-slot cooldown (the intervals overlap by 0.40s).']
        self.assertEqual(app._unapproved_repeats(self.project([[100, 101]]), list(err)), [])
        self.assertEqual(app._unapproved_repeats(self.project([]), list(err)), err)


if __name__ == '__main__':
    unittest.main()
