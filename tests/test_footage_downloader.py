import os, shutil, sys, tempfile, time, unittest
from pathlib import Path

import footage_downloader as fd

FAKE = Path(__file__).resolve().parent / 'fixtures' / 'fake_ytdlp.py'


class ManifestTest(unittest.TestCase):
    def test_table_list_and_heading_layouts_in_sheet_order(self):
        text = '\n'.join([
            '| Source | Title | Link |', '|---|---|---|',
            '| SRC-02 | Package | https://youtu.be/AAAAAAAAAA2?si=x |',
            '| SRC-01 | Bayou | https://www.youtube.com/watch?v=AAAAAAAAAA1&t=40s |',
            '- Source 03: [link](https://www.youtube.com/live/AAAAAAAAAA3)',
            '## SRC-04 Arrest', 'Link: https://m.youtube.com/watch?v=AAAAAAAAAA4',
            '- S05 https://www.youtube.com/shorts/AAAAAAAAAA5'])
        r = fd.parse_manifest(text)
        self.assertEqual([e['source_id'] for e in r['entries']], ['SRC-02', 'SRC-01', 'SRC-03', 'SRC-04', 'SRC-05'])
        self.assertEqual([e['filename'] for e in r['entries']], ['S02.mp4', 'S01.mp4', 'S03.mp4', 'S04.mp4', 'S05.mp4'])
        self.assertTrue(all(e['valid'] for e in r['entries']))
        self.assertEqual(r['entries'][1]['url'], 'https://www.youtube.com/watch?v=AAAAAAAAAA1')   # cleaned

    def test_problems_are_reported_never_guessed(self):
        text = '\n'.join(['- SRC-01: https://youtu.be/AAAAAAAAAA1', '- SRC-02 (to find)',
                          '- SRC-03: https://vimeo.com/1', '- SRC-01: https://youtu.be/AAAAAAAAAA9',
                          '- SRC-05: https://youtu.be/AAAAAAAAAA1', 'https://youtu.be/AAAAAAAAAAX'])
        r = fd.parse_manifest(text)
        kinds = sorted(i['kind'] for i in r['issues'])
        # Any web link is accepted now (yt-dlp reads Vimeo and most video sites).
        self.assertEqual(kinds, ['duplicate_link', 'duplicate_source', 'gap', 'missing_link', 'no_source_id'])
        self.assertEqual([e['source_id'] for e in r['entries'] if e['valid']], ['SRC-01', 'SRC-03', 'SRC-05'])

    def test_photo_rows_carry_the_person(self):
        text = '\n'.join([
            '| SRC-01 | S01.mp4 | Bayou | https://youtu.be/AAAAAAAAAA1 |',
            '| P01 | Maliyah Bass | Victim | https://example.com/a.jpg |',
            '| P02 | Mother.png | Sahara Ervin | Mother | https://example.com/story |',
            '- Brother — Jaylen Bass: https://example.com/j.webp',
            '| P04 | Travion Thompson | Suspect | https://youtu.be/AAAAAAAAAA1 |'])
        r = fd.parse_manifest(text)
        got = [(e['source_id'], e['media'], e['filename'], e['person'], e['role'], e['fix_ext']) for e in r['entries']]
        self.assertEqual(got, [('SRC-01', 'video', 'S01.mp4', '', '', False),
                               ('P01', 'photo', 'P01.jpg', 'Maliyah Bass', 'Victim', True),
                               ('P02', 'photo', 'Mother.png', 'Sahara Ervin', 'Mother', False),
                               ('Jaylen_Bass', 'photo', 'Jaylen_Bass.jpg', 'Jaylen Bass', 'Brother', True),
                               ('P04', 'photo', 'P04.jpg', 'Travion Thompson', 'Suspect', True)])
        # A photo row never leaves a gap in the S-numbering, and a video and a photo
        # from the same YouTube link are two different downloads.
        self.assertEqual([i['kind'] for i in r['issues']], [])
        self.assertEqual(r['counts']['photos'], 4)

    def test_broll_rows_keep_what_they_show(self):
        text = '\n'.join([
            '| SRC-01 | S01.mp4 | Police at the bayou | https://youtu.be/AAAAAAAAAA1 |',
            '| B01 | Sunset Crossing Apartments exterior | 0:43-0:52 | https://www.youtube.com/watch?v=AAAAAAAAAB1&t=43s |',
            '| B02 | Police cars at Brays Bayou | | https://example.com/police.jpg |',
            '| BASE-01 | Beechnut Street sign | | https://example.com/b.png |',
            '| B04 | Beechnut_frame.jpg | Beechnut at night | https://youtu.be/AAAAAAAAAB4?t=12 |',
            '- Drone shot of Brays Bayou: https://youtu.be/AAAAAAAAAB5',
            '| P07 | Sunset_door.jpg | Apartment door | https://example.com/door.jpg |'])
        r = fd.parse_manifest(text)
        got = [(e['source_id'], e['media'], e['filename'], e.get('window')) for e in r['entries']]
        self.assertEqual(got, [('SRC-01', 'video', 'S01.mp4', None),
                               ('B01', 'broll', 'B01.mp4', (43.0, 52.0)),
                               ('B02', 'broll', 'B02.mp4', None),
                               ('BASE-01', 'broll', 'BASE-01.mp4', None),
                               ('B04', 'broll', 'Beechnut_frame.jpg', None),
                               ('Drone_shot_of_Brays_Bayou', 'broll', 'Drone_shot_of_Brays_Bayou.mp4', None),
                               ('P07', 'photo', 'Sunset_door.jpg', None)])
        desc = {e['source_id']: e['description'] for e in r['entries']}
        self.assertEqual(desc['B01'], 'Sunset Crossing Apartments exterior')
        self.assertEqual(desc['P07'], 'Apartment door')
        self.assertEqual(r['entries'][-1]['person'], '')          # "Apartment door" is not a person
        self.assertEqual(r['issues'], [])                          # b-roll never leaves an S-number gap
        self.assertEqual(fd._url_time('https://youtu.be/AAAAAAAAAB4?t=12'), 12)
        self.assertEqual(fd._url_time('https://www.youtube.com/watch?v=x&t=1m5s'), 65)

    def test_share_links_point_at_the_file(self):
        self.assertEqual(fd.direct_link('https://drive.google.com/file/d/1AbCdEfGhIjK/view?usp=sharing'),
                         'https://drive.google.com/uc?export=download&id=1AbCdEfGhIjK')
        self.assertEqual(fd.direct_link('https://www.dropbox.com/s/x/p.jpg?dl=0'), 'https://www.dropbox.com/s/x/p.jpg?dl=1')

    def test_a_page_gives_its_sharing_photo(self):
        html = '<html><head><meta content="/img/m.jpg" property="og:image"></head></html>'
        self.assertEqual(fd._page_image(html, 'https://news.example/story/1'), 'https://news.example/img/m.jpg')

    def test_numbering_is_the_sheets_own(self):
        r = fd.parse_manifest('SRC-07 https://youtu.be/AAAAAAAAAA7\nSRC-12 https://youtu.be/AAAAAAAAA12')
        self.assertEqual([e['filename'] for e in r['entries']], ['S07.mp4', 'S12.mp4'])

    def test_filename_written_in_the_sheet_is_used_exactly(self):
        r = fd.parse_manifest('| SRC-01 | S01.mp4 | https://youtu.be/AAAAAAAAAA1 |\n'
                              '| SRC-02 | Bayou_drone.mp4 | https://youtu.be/AAAAAAAAAA2 |\n'
                              '| | S03.mp4 | https://youtu.be/AAAAAAAAAA3 |\n'
                              '## Vigil_wide.mp4\nhttps://youtu.be/AAAAAAAAAA4')
        self.assertEqual([e['filename'] for e in r['entries']], ['S01.mp4', 'Bayou_drone.mp4', 'S03.mp4', 'Vigil_wide.mp4'])
        self.assertEqual([e['source_id'] for e in r['entries']], ['SRC-01', 'SRC-02', 'SRC-03', 'Vigil_wide'])

    def test_script_check_reports_missing_short_and_unused(self):
        script = '\n'.join(['Beat: 001', 'Type: VOICE OVER', 'Narration clock: 00:00:00,000 --> 00:00:10,000',
                             'Narration state: PLAYING', 'Full source: S01.mp4', 'Source in: 00:00:00,000',
                             'Source out: 00:00:10,000', 'Footage audio: MUTED (0%)', '',
                             'Beat: 002', 'Type: VOICE OVER', 'Narration clock: 00:00:10,000 --> 00:00:15,000',
                             'Narration state: PLAYING', 'Full source: S02.mp4', 'Source in: 00:01:00,000',
                             'Source out: 00:01:05,000', 'Footage audio: MUTED (0%)'])
        state = fd.new_state('s', fd.parse_manifest('SRC-01 https://youtu.be/AAAAAAAAAA1\nSRC-03 https://youtu.be/AAAAAAAAAA3'), {})
        assets = [{'kind': 'video', 'original_name': 'S01.mp4', 'duration': 8.0}]
        check = fd.script_check(state, script, assets)
        self.assertEqual(check['missing'], ['S02.mp4'])
        self.assertEqual(check['short'], [{'filename': 'S01.mp4', 'duration_s': 8.0, 'needs_s': 10.0}])
        self.assertEqual(check['unused'], ['S03.mp4'])

    def test_youtube_id(self):
        for url in ('https://youtu.be/AAAAAAAAAA1', 'https://www.youtube.com/watch?v=AAAAAAAAAA1&list=x',
                    'https://www.youtube.com/embed/AAAAAAAAAA1', 'https://youtube.com/shorts/AAAAAAAAAA1'):
            self.assertEqual(fd.youtube_id(url), 'AAAAAAAAAA1')
        for url in ('https://vimeo.com/1', 'https://www.youtube.com/@channel', 'https://youtu.be/short'):
            self.assertIsNone(fd.youtube_id(url))

    def test_errors_are_explained(self):
        self.assertEqual(fd.explain('ERROR: Private video. Sign in')[1], False)
        self.assertEqual(fd.explain('Unable to download webpage: timed out')[1], True)
        self.assertIn('sign-in', fd.explain("Sign in to confirm you're not a bot")[0])


@unittest.skipUnless(shutil.which('ffmpeg'), 'ffmpeg is not installed')
class DownloadJobTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        os.environ['STORYROOM_YTDLP_CMD'] = f'"{sys.executable}" "{FAKE}"'
        self.registered = []

    def tearDown(self):
        os.environ.pop('STORYROOM_YTDLP_CMD', None)
        self.tmp.cleanup()

    def run_sheet(self, text, existing=lambda row: None):
        state = fd.new_state('sheet.md', fd.parse_manifest(text), {'concurrency': 2})
        fd.save_state(self.root, state)

        def register(row, path):
            target = self.root / 'sources' / row['filename']
            target.parent.mkdir(exist_ok=True)
            shutil.move(str(path), target)
            self.registered.append(row['filename'])
            return 'asset-' + row['source_id']
        job = fd.DownloadJob('p', self.root, register, existing, retry_delays=(0.1,))
        job.start()
        return job

    def test_downloads_retries_and_fails_clearly(self):
        job = self.run_sheet('SRC-01 https://youtu.be/GOODvideo01\nSRC-02 https://youtu.be/FLAKYvideo2\n'
                             'SRC-03 https://youtu.be/PRIVATEvid3')
        job.thread.join(60)
        rows = {r['source_id']: r for r in fd.load_state(self.root)['rows']}
        self.assertEqual(rows['SRC-01']['status'], fd.COMPLETED)
        self.assertEqual(rows['SRC-01']['title'], 'Test video GOODvideo01')
        self.assertEqual(rows['SRC-02']['status'], fd.COMPLETED)     # network error, then retried
        self.assertGreaterEqual(rows['SRC-02']['attempts'], 2)
        self.assertEqual(rows['SRC-03']['status'], fd.FAILED)
        self.assertEqual(rows['SRC-03']['attempts'], 1)               # permanent: not retried
        self.assertEqual(rows['SRC-03']['error'], 'This video is private.')
        self.assertEqual(sorted(self.registered), ['S01.mp4', 'S02.mp4'])
        self.assertEqual(fd.load_state(self.root)['job']['status'], 'finished_with_failures')

    def test_cancel_stops_quickly_and_resume_finishes(self):
        job = self.run_sheet('SRC-01 https://youtu.be/SLOWvideo01\nSRC-02 https://youtu.be/SLOWvideo02')
        time.sleep(2)
        started = time.time()
        job.stop()
        job.thread.join(20)
        self.assertLess(time.time() - started, 5)
        state = fd.load_state(self.root)
        self.assertEqual(state['job']['status'], 'cancelled')
        self.assertTrue(all(r['status'] == fd.CANCELLED for r in state['rows']))
        self.assertEqual(self.registered, [])
        for row in state['rows']:
            row['status'] = fd.WAITING
        fd.save_state(self.root, state)
        again = fd.DownloadJob('p', self.root, lambda row, path: self.registered.append(row['filename']) or 'a',
                               lambda row: None, retry_delays=(0.1,))
        again.start()
        again.thread.join(60)
        self.assertEqual(sorted(self.registered), ['S01.mp4', 'S02.mp4'])

    def test_existing_files_are_never_overwritten_unasked(self):
        job = self.run_sheet('SRC-01 https://youtu.be/GOODvideo01\nSRC-02 https://youtu.be/GOODvideo02',
                             existing=lambda row: {'S01.mp4': 'same', 'S02.mp4': 'other'}.get(row['filename']))
        job.thread.join(30)
        rows = {r['source_id']: r for r in fd.load_state(self.root)['rows']}
        self.assertEqual(rows['SRC-01']['status'], fd.COMPLETED)     # already imported: not downloaded again
        self.assertEqual(rows['SRC-02']['status'], fd.EXISTS)        # someone else's S02.mp4: kept
        self.assertEqual(self.registered, [])

    def test_same_video_for_two_sources_is_downloaded_once(self):
        log = self.root / 'calls.txt'
        os.environ['FAKE_YTDLP_LOG'] = str(log)
        try:
            job = self.run_sheet('SRC-01 https://youtu.be/GOODvideo01\nSRC-02 https://youtu.be/GOODvideo02\n'
                                 'SRC-03 https://youtu.be/GOODvideo01')
            job.thread.join(60)
        finally:
            os.environ.pop('FAKE_YTDLP_LOG', None)
        self.assertEqual(sorted(log.read_text().split()), ['GOODvideo01', 'GOODvideo02'])
        rows = {r['source_id']: r for r in fd.load_state(self.root)['rows']}
        self.assertTrue(all(r['status'] == fd.COMPLETED for r in rows.values()))
        self.assertEqual(sorted(self.registered), ['S01.mp4', 'S02.mp4', 'S03.mp4'])
        self.assertTrue((self.root / 'sources' / 'S03.mp4').stat().st_size > 1000)

    def test_b_roll_windows_from_one_news_video_are_separate_downloads(self):
        """Found on the Maliyah Bass sheet: clean stretches of a news package listed as
        their own B rows (B01 0:12-0:24, B02 1:16-1:20 of the same video) were merged into
        one download, so B02 got a copy of B01's picture. Each window is its own file now;
        the whole video (SRC row) and a repeated window are still shared."""
        log = self.root / 'sections.txt'
        os.environ['FAKE_YTDLP_SECTIONS'] = str(log)
        try:
            job = self.run_sheet('| SRC-03 | S03.mp4 | news package | https://youtu.be/GOODvideo03 |\n'
                                 '| B01 | Aerial of the bayou and the bank | 0:12-0:24 | https://youtu.be/GOODvideo03 |\n'
                                 '| B02 | The playground, empty swings | 1:16-1:20 | https://youtu.be/GOODvideo03 |\n'
                                 '| B03 | Aerial of the bayou, again | 0:12-0:24 | https://youtu.be/GOODvideo03 |\n')
            job.thread.join(60)
        finally:
            os.environ.pop('FAKE_YTDLP_SECTIONS', None)
        calls = sorted(log.read_text().splitlines())
        self.assertEqual(len(calls), 3, calls)                       # whole video + two distinct windows
        self.assertEqual(sum(1 for c in calls if c.endswith('whole')), 1)
        self.assertEqual(len({c for c in calls if not c.endswith('whole')}), 2)
        rows = {r['source_id']: r for r in fd.load_state(self.root)['rows']}
        self.assertTrue(all(r['status'] == fd.COMPLETED for r in rows.values()), rows)
        self.assertIn('copied', rows['B03'].get('note', ''))          # the repeated window is shared
        self.assertNotIn('copied', rows['B02'].get('note', ''))

    def test_video_already_in_project_is_copied_not_downloaded(self):
        log = self.root / 'calls.txt'
        os.environ['FAKE_YTDLP_LOG'] = str(log)
        existing = self.root / 'existing.mp4'
        shutil.copyfile(FAKE.parent / 'fake_ytdlp.py', existing)    # any file stands in for the earlier download
        try:
            state = fd.new_state('s', fd.parse_manifest('SRC-04 https://youtu.be/GOODvideo01'), {})
            fd.save_state(self.root, state)
            job = fd.DownloadJob('p', self.root, lambda row, path: self.registered.append(row['filename']) or 'a',
                                 lambda row: None, local_copy=lambda row: (existing, 'Earlier title'))
            job.start()
            job.thread.join(30)
        finally:
            os.environ.pop('FAKE_YTDLP_LOG', None)
        self.assertFalse(log.exists())
        row = fd.load_state(self.root)['rows'][0]
        self.assertEqual((row['status'], row['title']), (fd.COMPLETED, 'Earlier title'))
        self.assertEqual(self.registered, ['S04.mp4'])

    def test_restart_marks_unfinished_downloads_interrupted(self):
        state = fd.new_state('s.md', fd.parse_manifest('SRC-01 https://youtu.be/GOODvideo01'), {})
        state['rows'][0]['status'] = fd.DOWNLOADING
        state['job']['status'] = 'running'
        self.assertTrue(fd.recover(state))
        self.assertEqual(state['rows'][0]['status'], fd.INTERRUPTED)
        self.assertEqual(state['job']['status'], 'interrupted')


if __name__ == '__main__':
    unittest.main()
