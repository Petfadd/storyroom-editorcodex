import unittest
from fractions import Fraction
try:
    import documentary_final_renderer as r
except ImportError:              # PyAV missing: the renderer cannot load at all
    r = None


@unittest.skipIf(r is None, 'PyAV is not installed')
class UnknownSeekOffsetTest(unittest.TestCase):
    """A file PyAV cannot probe gives offset None: the shot must still render (seek 0)."""
    span = {'source_start_frame': 30, 'source_frame_count': 60, 'frame_conversion': 'none', 'picture_scale': 100}

    def test_unknown_offset_still_returns_a_pair(self):
        seek, filters = r._span_filters(self.span, 0, 10, 320, 180, Fraction(30), '30/1', False, seek_offset=None)
        self.assertEqual(seek, 0.0)
        self.assertIn('trim=start_frame=30:end_frame=40', filters)

    def test_known_offset_seeks_and_counts_from_zero(self):
        seek, filters = r._span_filters(self.span, 0, 10, 320, 180, Fraction(30), '30/1', False, seek_offset=Fraction(0))
        self.assertAlmostEqual(seek, 29.5 / 30)
        self.assertIn('trim=start_frame=0:end_frame=10', filters)

    def test_no_argument_returns_filters_alone(self):
        self.assertIsInstance(r._span_filters(self.span, 0, 10, 320, 180, Fraction(30), '30/1', False), str)


if __name__ == '__main__':
    unittest.main()
