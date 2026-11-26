"""Regression checks for authoritative production scripts and footage sheets.

Uses synthetic source examples, never stores documentary private/source content.
"""
import unittest
from documentary_beats import read_beats
from footage_downloader import parse_manifest

SOUND_BITE = '''Beat: 001
Type: DOCUMENTARY SOUND BITE
Master timeline: 00:00:00,000 --> 00:00:03,200
Narration Clock: PAUSED at 00:00:00,000
Narration state: PAUSED
Spoken source dialogue: [Requires original-source listening]
Full source: S15.mp4
Source in: 00:01:12,300
Source out: 00:01:15,500
Footage audio: UNMUTED (100%)
'''

class UnifiedIntakeRegression(unittest.TestCase):
    def test_matching_clocks_allow_missing_duration(self):
        b = read_beats(SOUND_BITE)[0]
        self.assertEqual((b['source_file'], b['duration_ms'], b['master_out_ms']),
                         ('S15.mp4', 3200, 3200))

    def test_conflicting_source_and_master_clocks_block_import(self):
        wrong = SOUND_BITE.replace('00:00:03,200', '00:00:03,400')
        with self.assertRaisesRegex(ValueError, 'disagree'):
            read_beats(wrong)

    def test_missing_duration_and_master_is_unambiguous_error(self):
        no_master = '\n'.join(line for line in SOUND_BITE.splitlines()
                              if not line.startswith('Master timeline:'))
        with self.assertRaisesRegex(ValueError, 'matching Source IN'):
            read_beats(no_master)

    def test_explicit_duration_still_checked_against_two_clocks(self):
        wrong = SOUND_BITE.replace('00:00:03,200', '00:00:03,400') + 'Duration: 00:00:03,200\n'
        with self.assertRaisesRegex(ValueError, 'Master timeline duration'):
            read_beats(wrong)

    def test_exclusion_notes_are_not_download_requests(self):
        sheet = '''# Approved downloads
| Source | File | Link |
|---|---|---|
| SRC-01 | S01.mp4 | https://youtu.be/AAAAAAAAAA1 |
| SRC-02 | S02.mp4 | https://youtu.be/AAAAAAAAAA2 |
## People (photos)
| Photo | Person | Link |
|---|---|---|
| P01 | Adult Speaker | https://youtu.be/AAAAAAAAAA1 |
## B-roll and base pictures
| B12 | B12.mp4 (S02) | Street view [USED] | 00:00:15–00:00:19 | https://youtu.be/AAAAAAAAAA2 |
## Deliberately excluded / restricted
- S03 must never be downloaded.
- Do not use B38 memorial group image.
## Intake controls
- S04 is not a valid file yet; never guess it.
'''
        r = parse_manifest(sheet)
        self.assertEqual([e['filename'] for e in r['entries']],
                         ['S01.mp4', 'S02.mp4', 'P01.jpg', 'B12.mp4'])
        self.assertEqual([e['media'] for e in r['entries']],
                         ['video', 'video', 'photo', 'broll'])
        self.assertEqual(r['issues'], [])

    def test_parent_video_not_mistaken_for_photo_or_broll(self):
        sheet = '''| B12 | B12.jpg (S15) | FOR PEOPLE: Adult Speaker | 00:00:15–00:00:16 | https://youtu.be/AAAAAAAAAA1 |
| P02 | Adult Speaker | Single-person thumbnail from S15 | https://youtu.be/AAAAAAAAAA1 |'''
        r = parse_manifest(sheet)
        self.assertEqual([(e['filename'], e['media']) for e in r['entries']],
                         [('B12.jpg', 'broll'), ('P02.jpg', 'photo')])

if __name__ == '__main__':
    unittest.main()
