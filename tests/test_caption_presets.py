import unittest

import captions


def fields(style_line):
    names = ['Name', 'Fontname', 'Fontsize', 'PrimaryColour', 'SecondaryColour', 'OutlineColour', 'BackColour',
             'Bold', 'Italic', 'Underline', 'StrikeOut', 'ScaleX', 'ScaleY', 'Spacing', 'Angle', 'BorderStyle',
             'Outline', 'Shadow', 'Alignment', 'MarginL', 'MarginR', 'MarginV', 'Encoding']
    return dict(zip(names, style_line.split(': ', 1)[1].split(',')))


class PresetShapeTest(unittest.TestCase):
    def test_every_look_has_a_label_detail_font_and_style(self):
        for key, look in captions.LOOKS.items():
            self.assertTrue(look['label'] and look['detail'], key)
            self.assertTrue(captions.font_path(key).is_file(), f'{key}: font must ship with the editor')
            self.assertTrue(captions.css(key), key)
            self.assertIn('FontName=', captions.ass_style(key), key)

    def test_an_unknown_preset_falls_back_to_the_default(self):
        self.assertEqual(captions.get('nonsense'), captions.PRESETS[captions.DEFAULT])
        self.assertEqual(captions.ass_style('nonsense'), captions.ass_style(captions.DEFAULT))

    def test_old_saved_names_still_resolve(self):
        for old in ('clean', 'lower_band', 'kinetic'):
            self.assertIn(old, captions.PRESETS)
            self.assertIn(captions.resolve(old), captions.LOOKS)

    def test_boxed_presets_keep_a_nonzero_outline(self):
        """libass draws the plate only when the outline width is nonzero."""
        for key in ('boxed', 'news', 'lower_band'):
            f = fields(captions.ass_style_line(key))
            self.assertEqual(f['BorderStyle'], '3', key)
            self.assertNotEqual(float(f['Outline']), 0, f'{key} would lose its plate')

    def test_caption_size_follows_the_master_height(self):
        for key in captions.LOOKS:
            hd = fields(captions.ass_style_line(key, 1080))
            uhd = fields(captions.ass_style_line(key, 2160))
            self.assertAlmostEqual(int(uhd['Fontsize']), 2 * int(hd['Fontsize']), delta=1)
            self.assertEqual(int(uhd['MarginV']), 2 * int(hd['MarginV']))

    def test_size_and_position_choices_change_the_style(self):
        small = fields(captions.ass_style_line('cinema', 1080, 'small'))
        large = fields(captions.ass_style_line('cinema', 1080, 'large'))
        self.assertLess(int(small['Fontsize']), int(large['Fontsize']))
        self.assertEqual(fields(captions.ass_style_line('cinema', position='top'))['Alignment'], '8')
        self.assertEqual(fields(captions.ass_style_line('cinema', position='middle'))['Alignment'], '5')

    def test_catalogue_is_complete(self):
        data = captions.catalogue()
        self.assertEqual([p['key'] for p in data['presets']], list(captions.LOOKS))
        for preset in data['presets']:
            self.assertTrue(preset['css'], preset['key'])
        self.assertEqual(data['selected'], captions.DEFAULT)
        self.assertEqual({f['url'].rsplit('/', 1)[1] for f in data['fonts']}, {x for x in captions.FONTS if (captions.FONT_DIR / x).is_file()})


if __name__ == '__main__':
    unittest.main()
