import tempfile, unittest
from pathlib import Path
from PIL import Image, ImageDraw
import person_overlays as po


def _img(path, seed):
    im = Image.new('RGB', (200, 200), (20, 20, 20)); d = ImageDraw.Draw(im)
    for k in range(6):
        x = (seed * 37 + k * 53) % 180
        d.rectangle([x, k * 30, x + 20 + seed * 3, k * 30 + 25], fill=(200, 50 + seed * 20, 90))
    im.save(path)


class SharedPhotoTest(unittest.TestCase):
    def test_people_filed_with_one_group_picture_are_flagged(self):
        with tempfile.TemporaryDirectory() as root:
            r = Path(root); (r / 'assets').mkdir()
            _img(r / 'assets' / 'group.jpg', 1); _img(r / 'assets' / 'group2.jpg', 1); _img(r / 'assets' / 'own.jpg', 7)
            people = [{'id': 'a', 'name': 'Patricia May', 'role': 'Victim', 'photo': {'path': 'assets/group.jpg'}},
                      {'id': 'b', 'name': 'Cherie May', 'role': 'Victim', 'photo': {'path': 'assets/group2.jpg'}},
                      {'id': 'c', 'name': 'Devin May', 'role': 'Victim', 'photo': {'path': 'assets/own.jpg'}}]
            got = po.shared_photos(people, root)
            self.assertEqual(got, {'a': ['Cherie May'], 'b': ['Patricia May']})
            plan = po.plan({'people': people, 'srt': {'blocks': [
                {'number': 1, 'start_ms': 0, 'end_ms': 4000, 'text': 'Patricia May, Cherie May, and Devin May'}]}}, root)
            self.assertTrue(any('same photo' in n for n in plan['notes']))
            self.assertEqual({p['id']: p.get('same_photo_as') for p in plan['people']}['c'], None)


if __name__ == '__main__':
    unittest.main()
