import shutil, subprocess, tempfile, unittest
from pathlib import Path

from PIL import Image

import person_overlays as po


def cue(n, start, end, text):
    return {'number': n, 'start_ms': start, 'end_ms': end, 'text': text}


class PersonOverlayTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'people').mkdir()
        for name in ('victim', 'mother', 'father', 'neighbour'):
            Image.new('RGB', (600, 800), (120, 90, 60)).save(self.root / 'people' / f'{name}.jpg')
        self.people = [
            {'id': 'v', 'name': 'Maliyah Bass', 'role': 'Victim', 'aliases': ['Malia'], 'short_names': True, 'photo': {'path': 'people/victim.jpg'}},
            {'id': 'm', 'name': 'Sahara Ervin', 'role': 'Mother', 'aliases': ['Irvin'], 'short_names': True, 'photo': {'path': 'people/mother.jpg'}},
            {'id': 'f', 'name': 'Octavius Bass', 'role': 'Father', 'aliases': [], 'short_names': True, 'photo': {'path': 'people/father.jpg'}},
            {'id': 'h', 'name': 'Angel Harris', 'role': 'Neighbour', 'aliases': [], 'photo': {'path': 'people/neighbour.jpg'}},
        ]

    def tearDown(self):
        self.tmp.cleanup()

    FIXED = {'style': 'card', 'timing': 'fixed'}

    def project(self, blocks, duration=60.0, settings=None, **extra):
        # Photos are opt-in: the project setting is on and each person approved (show).
        for person in self.people:
            person.setdefault('show', True)
        conf = dict(settings if settings is not None else self.FIXED)
        conf.setdefault('enabled', True)
        return {'people': self.people, 'srt': {'blocks': blocks}, 'voiceover': {'duration': duration},
                'person_overlay_settings': conf, **extra}

    def test_full_names_aliases_and_unshared_short_names_match(self):
        blocks = [cue(1, 0, 4000, 'Malia was gone'), cue(2, 10000, 14000, 'Ervin called 911'),
                  cue(3, 20000, 24000, 'Octavius flew in'), cue(4, 30000, 34000, 'later Sahara Ervin spoke')]
        found = po.find_mentions(blocks, self.people)
        self.assertEqual([m['person_id'] for m in found], ['v', 'm', 'f', 'm'])
        # "Sahara Ervin" is one mention, not "Sahara" and "Ervin" twice.
        self.assertEqual(found[-1]['said'], 'Sahara Ervin')

    def test_shared_surname_place_words_lowercase_and_exclusions_do_not_match(self):
        self.people[3]['exclude'] = ['Angel Harris Park']
        blocks = [cue(1, 0, 4000, 'the Bass family grieved'),          # shared by two people
                  cue(2, 5000, 9000, 'Harris County prosecutors'),     # a place, not Angel Harris
                  cue(3, 10000, 14000, 'an angel watched over'),       # not written as a name
                  cue(4, 15000, 19000, 'we met at Angel Harris Park')]  # user said: not her
        self.assertEqual(po.find_mentions(blocks, self.people), [])

    def test_mention_time_follows_its_position_in_the_cue(self):
        found = po.find_mentions([cue(1, 1000, 5000, 'police said that Malia')], self.people)
        self.assertEqual(len(found), 1)
        self.assertGreater(found[0]['narration_ms'], 3500)
        self.assertLess(found[0]['narration_ms'], 5000)

    def test_card_never_crosses_a_sound_bite_and_moves_with_the_master_clock(self):
        # Narration 0-20 s, a 30 s bite at 10 s, then narration again.
        plan = {'version': 1, 'revision': 1, 'bites': [{'id': 'b', 'asset_id': 'a', 'asset_name': 'S01.mp4', 'pause_s': 10.0,
                                                      'source_in_s': 0.0, 'source_out_s': 30.0, 'created': 1}]}
        blocks = [cue(1, 7000, 9000, 'Malia was two'), cue(2, 12000, 15000, 'Malia loved pink')]
        data = po.plan(self.project(blocks, duration=20.0), self.root, plan)
        first, second = data['windows']
        self.assertLessEqual(first['end_ms'], 10000)            # stops where the bite starts
        self.assertGreaterEqual(second['start_ms'], 40000)      # after the bite, on the master clock
        for w in data['windows']:
            self.assertFalse(10000 < w['start_ms'] < 40000 or 10000 < w['end_ms'] < 40000)

    def test_repeated_name_keeps_card_up_and_new_name_takes_over(self):
        blocks = [cue(1, 0, 2000, 'Malia smiled'), cue(2, 2200, 4000, 'Malia laughed'),
                  cue(3, 9000, 10000, 'Irvin'), cue(4, 11800, 14000, 'Octavius Bass arrived')]
        data = po.plan(self.project(blocks), self.root)
        names = [w['person_id'] for w in data['windows']]
        self.assertEqual(names, ['v', 'm', 'f'])
        self.assertEqual(data['windows'][0]['mentions'], 2)
        self.assertEqual(data['windows'][1]['end_ms'], data['windows'][2]['start_ms'])

    def test_too_short_card_is_left_out_and_reported(self):
        blocks = [cue(1, 0, 2000, 'Irvin and Octavius Bass')]
        data = po.plan(self.project(blocks), self.root)
        self.assertEqual([w['person_id'] for w in data['windows']], ['f'])
        self.assertTrue(any('left out' in n for n in data['notes']))

    def test_people_without_photo_or_switched_off_are_reported_not_shown(self):
        self.people[0].pop('photo')
        self.people[1]['show'] = False
        data = po.plan(self.project([cue(1, 0, 3000, 'Malia'), cue(2, 10000, 13000, 'Irvin')]), self.root)
        self.assertEqual(data['windows'], [])
        self.assertTrue(any('no photo' in n for n in data['notes']))
        self.assertTrue(any('switched off' in n for n in data['notes']))

    def test_settings_are_validated(self):
        self.assertEqual(po.clean_settings({'position': 'left', 'hold_ms': 5000}), {'position': 'left', 'hold_ms': 5000})
        for bad in ({'position': 'top'}, {'size': 'huge'}, {'hold_ms': 10}, {'nonsense': 1}):
            with self.assertRaises(ValueError):
                po.clean_settings(bad)

    # ---- defaults: full screen, for the whole SRT line ----

    def test_defaults_are_full_screen_for_the_whole_line(self):
        self.assertEqual((po.DEFAULTS['style'], po.DEFAULTS['timing']), ('full', 'cue'))

    def test_photo_covers_the_whole_line_and_continues_through_lines_naming_them_again(self):
        blocks = [cue(1, 1000, 4000, 'police said Malia was gone'), cue(2, 4200, 7000, 'Malia loved pink'),
                  cue(3, 7100, 9000, 'neighbours searched'), cue(4, 20000, 23000, 'nobody slept')]
        windows = po.plan(self.project(blocks, settings={}), self.root)['windows']
        self.assertEqual(len(windows), 1)
        # v15: starts at the line start, holds through the pauses and the following line
        # that names nobody, and ends on that line's end (the long silence after it).
        self.assertEqual((windows[0]['start_ms'], windows[0]['end_ms']), (1000, 9000))
        self.assertEqual(windows[0]['cues'], [1, 2, 3])

    def test_two_names_in_one_cue_show_side_by_side_for_the_whole_line(self):
        # v17: a line naming two people with photos shows them side by side.
        blocks = [cue(1, 0, 6000, 'police arrested Sahara Ervin and later Octavius Bass')]
        data = po.plan(self.project(blocks, settings={}), self.root)
        w = data['windows']
        self.assertEqual([(x['person_id'], x.get('partner_id')) for x in w], [('m', 'f')])
        self.assertEqual((w[0]['start_ms'], w[0]['end_ms']), (0, 6000))
        self.assertEqual((w[0]['name_intro'], w[0]['partner_name_intro']), (True, True))
        self.assertIn('side by side', data['window_report'][0]['text'])

    def test_two_names_in_one_cue_one_person_when_pairs_are_off(self):
        # v15 behaviour, kept behind the setting.
        blocks = [cue(1, 0, 6000, 'police arrested Sahara Ervin and later Octavius Bass')]
        data = po.plan(self.project(blocks, settings={'pair_photos': False}), self.root)
        self.assertEqual([w['person_id'] for w in data['windows']], ['m'])
        self.assertEqual((data['windows'][0]['start_ms'], data['windows'][0]['end_ms']), (0, 6000))
        self.assertTrue(any('Octavius Bass (cue 1)' in n and 'skipped' in n for n in data['notes']), data['notes'])

    def test_pair_ends_when_the_next_line_names_one_of_them(self):
        blocks = [cue(1, 0, 3000, 'Sahara Ervin and Octavius Bass arrived'), cue(2, 3300, 6000, 'Octavius Bass spoke first')]
        data = po.plan(self.project(blocks, settings={}), self.root)
        self.assertEqual([(w['person_id'], w.get('partner_id'), w['start_ms'], w['end_ms']) for w in data['windows']],
                         [('m', 'f', 0, 3300), ('f', None, 3300, 6000)])      # handover only on the cue boundary
        # Octavius was introduced in the pair: no second name graphic.
        self.assertEqual([w['name_intro'] for w in data['windows']], [True, False])

    def test_second_person_waits_for_the_next_line_that_names_them(self):
        blocks = [cue(1, 0, 3000, 'Sahara Ervin and Octavius Bass arrived'), cue(2, 3300, 6000, 'Octavius Bass spoke first')]
        data = po.plan(self.project(blocks, settings={'pair_photos': False}), self.root)
        self.assertEqual([(w['person_id'], w['start_ms'], w['end_ms']) for w in data['windows']],
                         [('m', 0, 3300), ('f', 3300, 6000)])          # handover only on the cue boundary
        self.assertTrue(any('waits for cue 2' in n for n in data['notes']), data['notes'])

    def test_max_length_ends_on_a_cue_boundary_never_inside_a_line(self):
        blocks = [cue(n, (n - 1) * 3000, n * 3000 - 100, 'Malia smiled' if n == 1 else 'she played') for n in range(1, 6)]
        data = po.plan(self.project(blocks, settings={'max_ms': 4000}), self.root)
        w = data['windows'][0]
        self.assertIn(w['end_ms'], {b['end_ms'] for b in blocks} | {b['start_ms'] for b in blocks})
        self.assertGreaterEqual(w['end_ms'] - w['start_ms'], 4000)
        self.assertEqual(w['cues'], [1, 2])

    def test_every_boundary_is_on_the_30fps_frame_grid(self):
        blocks = [cue(1, 1013, 4027, 'Malia smiled')]
        w = po.plan(self.project(blocks, settings={}), self.root)['windows'][0]
        for ms in (w['start_ms'], w['end_ms']):
            self.assertEqual(ms, round(round(ms * 30 / 1000) * 1000 / 30))

    def test_notes_list_every_window_with_master_in_and_out(self):
        blocks = [cue(1, 0, 3000, 'Malia smiled'), cue(2, 10000, 13000, 'Sahara Ervin called')]
        data = po.plan(self.project(blocks, settings={}), self.root)
        self.assertEqual([r['text'] for r in data['window_report']],
                         ['Maliyah Bass · cue 1 · 00:00:00.000 → 00:00:03.000 · name shown',
                          'Sahara Ervin · cue 2 · 00:00:10.000 → 00:00:13.000 · name shown'])

    def test_name_shows_at_first_introduction_only(self):
        blocks = [cue(1, 0, 3000, 'Malia smiled'), cue(2, 10000, 13000, 'Malia laughed')]
        first = po.plan(self.project(blocks, settings={}), self.root)['windows']
        self.assertEqual([w['name_intro'] for w in first], [True, False])
        # v17: 'every' was removed; an old save that still says it shows names once.
        every = po.plan(self.project(blocks, settings={'name_display': 'every'}), self.root)['windows']
        self.assertEqual([w['name_intro'] for w in every], [True, False])
        # The legacy label switch no longer puts the name on every photo either.
        legacy = po.plan(self.project(blocks, settings={'show_label': True, 'cinematic_name_intro': False}), self.root)['windows']
        self.assertEqual([w['name_intro'] for w in legacy], [True, False])

    def test_photo_styles_cut_and_dissolve_have_no_slide_or_zoom(self):
        blocks = [cue(1, 0, 3000, 'Malia smiled')]
        for style, enter, ms in (('cut', 'cut', 0), ('dissolve', 'fade', 150)):
            w = po.plan(self.project(blocks, settings={'style': 'full', 'photo_style': style}), self.root)['windows'][0]
            self.assertEqual((w['motion']['entrance'], w['motion']['enter_ms'], w['motion']['camera_preset']), (enter, ms, None))
        w = po.plan(self.project(blocks, settings={'style': 'full', 'photo_style': 'moves'}), self.root)['windows'][0]
        self.assertTrue(w['motion']['camera_preset'])

    def test_name_said_in_passing_gives_the_line_to_the_other_person(self):
        blocks = [cue(1, 0, 3000, "Malia's father Octavius Bass lives in Dallas")]
        data = po.plan(self.project(blocks, settings={}), self.root)
        self.assertEqual([w['person_id'] for w in data['windows']], ['f'])
        self.assertEqual((data['windows'][0]['start_ms'], data['windows'][0]['end_ms']), (0, 3000))
        # "Malia's father" is about the father: the line is his, by the relative rule.

    def test_whole_line_photo_stops_at_a_sound_bite(self):
        plan = {'version': 1, 'revision': 1, 'bites': [{'id': 'b', 'asset_id': 'a', 'asset_name': 'S01.mp4', 'pause_s': 5.0,
                                                      'source_in_s': 0.0, 'source_out_s': 20.0, 'created': 1}]}
        blocks = [cue(1, 2000, 5000, 'here is Sahara Ervin'), cue(2, 5000, 8000, 'Sahara Ervin again')]
        windows = po.plan(self.project(blocks, duration=10.0, settings={}), self.root, plan)['windows']
        self.assertEqual([(w['start_ms'], w['end_ms']) for w in windows], [(2000, 5000), (25000, 28000)])

    def test_full_screen_photo_fills_the_frame_without_stretching(self):
        conf = dict(po.DEFAULTS)
        for width, height in ((1920, 1080), (1080, 1920)):
            image, g = po.draw_card(self.root / 'people' / 'victim.jpg', 'Maliyah Bass', 'Victim', width, height, conf)
            self.assertEqual(image.size, (width, height))
            self.assertEqual((g['x'], g['y']), (0, 0))

    def test_script_captions_are_held_back_under_full_screen_photos(self):
        self.assertEqual(po.caption_enable(10, 20, [(12, 14), (30, 31)]),
                         'gte(t,10.000)*lt(t,20.000)*not(between(t,12.000,14.000))')
        self.assertEqual(po.caption_enable(10, 20, []), 'gte(t,10.000)*lt(t,20.000)')
        project = self.project([cue(1, 0, 3000, 'Malia')], settings={'style': 'card'})
        self.assertEqual(po.covered_spans(project, self.root, None), [])   # a corner card hides nothing

    def test_card_fits_inside_frame_for_every_shape_and_position(self):
        for width, height in ((1920, 1080), (1080, 1920), (1080, 1080)):
            for position in po.POSITIONS:
                conf = dict(po.DEFAULTS, position=position, style='card')
                image, g = po.draw_card(self.root / 'people' / 'victim.jpg', 'Maliyah Bass', 'Victim', width, height, conf)
                self.assertEqual(image.size, (g['canvas_w'], g['canvas_h']))
                self.assertGreaterEqual(g['x'], 0)
                self.assertGreaterEqual(g['y'], 0)
                self.assertLessEqual(g['x'] + g['canvas_w'], width)
                self.assertLessEqual(g['y'] + g['canvas_h'], height)

    @unittest.skipUnless(shutil.which('ffmpeg'), 'ffmpeg is not installed')
    def test_rendered_cards_keep_every_frame_and_appear_only_in_their_window(self):
        work = self.root / 'work'
        work.mkdir()
        base = work / 'base.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=black:s=320x180:r=30', '-t', '6',
                        '-pix_fmt', 'yuv420p', str(base)], check=True)
        project = self.project([cue(1, 2000, 2500, 'Malia')], duration=6.0,
                               settings={'style': 'card', 'timing': 'fixed', 'hold_ms': 2000, 'fade_ms': 0, 'lead_ms': 0})
        inputs, steps, count = po.render_filters(project, self.root, None, 320, 180, '30', work, 1)
        self.assertEqual(count, 1)
        out = work / 'out.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(base)] + inputs +
                       ['-filter_complex', ';'.join(['[0:v]null[base]'] + steps + ['[cards]format=yuv420p[v]']),
                        '-map', '[v]', '-c:v', 'libx264', str(out)], check=True)
        frames = subprocess.run(['ffprobe', '-v', 'error', '-count_frames', '-select_streams', 'v', '-show_entries',
                                 'stream=nb_read_frames', '-of', 'csv=p=0', str(out)], capture_output=True, text=True).stdout.strip()
        self.assertEqual(frames, '180')

        def bright(t):
            raw = subprocess.run(['ffmpeg', '-v', 'error', '-ss', str(t), '-i', str(out), '-frames:v', '1', '-f', 'rawvideo',
                                  '-pix_fmt', 'gray', '-'], capture_output=True).stdout
            return sum(raw) / len(raw)
        self.assertLess(bright(1.0), 5)       # before the name: plain black footage
        self.assertGreater(bright(3.0), 10)   # card is up
        self.assertLess(bright(5.5), 5)       # gone again


if __name__ == '__main__':
    unittest.main()
