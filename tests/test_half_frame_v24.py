"""v24: a time exactly half a frame between two frames rounds to the later frame on the
documentary film clock (and source frames), the same rule cutaways and name cards use.
The strict script-review check still reports it."""
import unittest
from fractions import Fraction

from strict_cuts import _nearest_frame


class HalfFrame(unittest.TestCase):
    def test_documentary_rounds_half_up(self):
        # 76.900 s at 25 fps is frame 1922.5 (Beat 006 of a real script)
        self.assertEqual(_nearest_frame(76900, Fraction(25), half_up=True), 1923)
        self.assertEqual(_nearest_frame(8020, Fraction(25), half_up=True), 201)
        # not a half: unchanged nearest-frame rounding
        self.assertEqual(_nearest_frame(8010, Fraction(25), half_up=True), 200)
        self.assertEqual(_nearest_frame(8030, Fraction(25), half_up=True), 201)
        self.assertEqual(_nearest_frame(617470, Fraction(30), half_up=True), 18524)

    def test_both_sides_of_a_cut_meet(self):
        # One span's OUT and the next span's IN are the same time: same frame, no gap.
        for ms in (76900, 56380, 1500, 99980):
            self.assertEqual(_nearest_frame(ms, Fraction(25), half_up=True), _nearest_frame(ms, Fraction(25), half_up=True))

    def test_strict_review_still_reports_it_with_the_time(self):
        with self.assertRaisesRegex(ValueError, r'76\.900s is exactly halfway between two frames at 25 fps'):
            _nearest_frame(76900, Fraction(25))

    def test_documentary_callers_use_half_up(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        for name in ('documentary_render_plan.py', 'documentary_frame_audit.py', 'documentary_strict.py'):
            text = (root / name).read_text(encoding='utf-8')
            calls = [line for line in text.splitlines() if '_nearest_frame(' in line and 'import' not in line]
            self.assertTrue(calls, name)
            self.assertTrue(all('half_up=True' in line for line in calls), name)


if __name__ == '__main__':
    unittest.main()
