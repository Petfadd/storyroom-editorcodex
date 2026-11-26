"""The editor is not tied to one production: any case, any length."""
import json
import tempfile
import unittest
from pathlib import Path

import timebudget
import visual_plan as vp


class NotTiedToOneCaseTest(unittest.TestCase):
    def test_the_bundled_catalogue_needs_most_of_its_own_files(self):
        data = json.loads(Path('data/broll_catalog.json').read_text(encoding='utf-8'))
        name, first = next(iter(data['sources'].items()))
        with tempfile.TemporaryDirectory() as tmp:
            # A new production that happens to have one file of the same name and length.
            project = {'assets': [{'id': 'a', 'kind': 'video', 'name': name + '.mp4', 'original_name': name + '.mp4',
                                   'duration': first['duration'], 'path': 'sources/a.mp4'}], 'people': []}
            items, _ = vp.build_catalogue(project, Path(tmp), None, None)
            self.assertEqual([i for i in items if i['source'] == 'catalog'], [])

    def test_a_production_can_bring_its_own_catalogue(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'broll_catalog.json').write_text(json.dumps({'sources': {'V01': {'duration': 60.0, 'what': 'x'}},
                'shots': [{'id': 'X1', 'source': 'V01', 'in': 1, 'out': 6, 'what': 'Pine Street at night',
                           'tags': ['street'], 'kind': 'place', 'verified': True}]}))
            project = {'assets': [{'id': 'a', 'kind': 'video', 'name': 'V01.mp4', 'original_name': 'V01.mp4',
                                   'duration': 60.0, 'path': 'sources/a.mp4'}], 'people': []}
            items, _ = vp.build_catalogue(project, root, None, None)
            self.assertEqual([i['text'] for i in items if i['source'] == 'catalog'], ['Pine Street at night street'])

    def test_place_names_are_not_people_in_any_city(self):
        for text in ('Oak Ridge Mall parking garage', 'Harris County deputies', 'Tampa Bay Times',
                     'Miami Police Department', 'Lagos State Police', 'Pine Street corner'):
            self.assertEqual(vp.surnames(text), set(), text)
        self.assertEqual(vp.surnames('Chief Ana Ruiz at the podium'), {'Ruiz'})


class AnyLengthTest(unittest.TestCase):
    def test_time_budget_grows_with_the_film(self):
        self.assertEqual(timebudget.seconds(), 1800)
        with timebudget.film_length(8 * 60):
            short = timebudget.seconds()
        with timebudget.film_length(20 * 60):
            long_ = timebudget.seconds()
            with timebudget.film_length(10):          # a nested short step keeps the film's budget
                self.assertEqual(timebudget.seconds(), long_)
        self.assertGreater(long_, short)
        self.assertGreaterEqual(long_, 20 * 60 * 12)
        self.assertEqual(timebudget.seconds(), 1800)


if __name__ == '__main__':
    unittest.main()
