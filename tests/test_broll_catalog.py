"""The b-roll catalogue data (data/broll_catalog.json): every window real and checked.

The visual plan uses this hand-checked shot list when a project's sources match it by
name and length. These tests hold the data honest: a window must lie inside its
source, never overlap another, and say what is on screen.
"""
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / 'data' / 'broll_catalog.json'


class CatalogTest(unittest.TestCase):
    def setUp(self):
        self.catalog = json.loads(CATALOG.read_text(encoding='utf-8'))

    def test_every_window_is_inside_its_source_and_positive(self):
        sources = self.catalog['sources']
        for shot in self.catalog['shots']:
            duration = sources[shot['source']]['duration']
            self.assertGreater(shot['out'], shot['in'], shot['id'])
            self.assertGreaterEqual(shot['in'], 0, shot['id'])
            self.assertLessEqual(shot['out'], duration + 0.001, shot['id'])

    def test_windows_in_one_source_do_not_overlap(self):
        # Two catalog entries over the same frames would let the planner put the same
        # picture on screen twice while believing it had found two shots.
        by_source = {}
        for shot in self.catalog['shots']:
            by_source.setdefault(shot['source'], []).append(shot)
        for source, shots in by_source.items():
            shots = sorted(shots, key=lambda s: s['in'])
            for a, b in zip(shots, shots[1:]):
                self.assertLessEqual(a['out'], b['in'] + 0.001,
                                     f'{source}: {a["id"]} and {b["id"]} overlap')

    def test_every_shot_says_what_is_on_screen(self):
        for shot in self.catalog['shots']:
            self.assertTrue(shot['what'].strip(), shot['id'])
            self.assertTrue(shot['tags'], shot['id'])
            self.assertTrue(shot.get('verified', True), shot['id'])

    def test_sources_describe_the_file_honestly(self):
        # Each source must record a duration, so a window cannot be checked against
        # a number nobody wrote down.
        for name, source in self.catalog['sources'].items():
            self.assertGreater(source['duration'], 0, name)
            self.assertTrue(source['what'].strip(), name)


if __name__ == '__main__':
    unittest.main()
