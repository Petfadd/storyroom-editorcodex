"""Regression: authentic documentary source windows may be deliberately replayed.

Uses synthetic, unverified source files and a mocked frame rate. No actual person,
source identity, rights or export quality is certified by these tests.
"""
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from documentary_beat_plan import proposal
from documentary_beats import read_beats
from documentary_storyboard import prepare
from documentary_strict import validate as strict_validate
from automatic import repetition_errors, source_capacity_errors


SCRIPT = '''Beat: 001
Type: DOCUMENTARY SOUND BITE
Master timeline: 00:00:00,000 --> 00:00:01,000
Narration Clock: PAUSED at 00:00:00,000
Narration State: PAUSED (Suspended at 00:00:00,000)
Speaker: Interviewee
Full source: S01.mp4
Source in: 00:00:05,000
Source out: 00:00:06,000
Duration: 00:00:01,000
Footage audio: UNMUTED (100%)
Continuity note: Intentional hook/main replay.
Beat: 002
Type: VOICE OVER
Master timeline: 00:00:01,000 --> 00:00:03,000
Narration Clock: RESUMES at 00:00:00,000 --> 00:00:02,000
Narration state: RESUMING
Spoken narration: First narration passage.
Full source: S02.mp4
Source in: 00:00:00,000
Source out: 00:00:02,000
Footage audio: MUTED (0%)
Beat: 003
Type: DOCUMENTARY SOUND BITE
Master timeline: 00:00:03,000 --> 00:00:04,000
Narration Clock: PAUSED at 00:00:02,000
Narration State: PAUSED (Suspended at 00:00:02,000)
Speaker: Interviewee
Full source: S01.mp4
Source in: 00:00:05,000
Source out: 00:00:06,000
Duration: 00:00:01,000
Footage audio: UNMUTED (100%)
Continuity note: Intentional hook/main replay.
Beat: 004
Type: VOICE OVER
Master timeline: 00:00:04,000 --> 00:00:06,000
Narration Clock: RESUMES at 00:00:02,000 --> 00:00:04,000
Narration State: RESUMING
Spoken narration: Second narration passage.
Full source: S02.mp4
Source in: 00:00:02,000
Source out: 00:00:04,000
Footage audio: MUTED (0%)
'''


class SourceReuseRegressions(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        (self.root/'sources').mkdir()
        (self.root/'inputs').mkdir()
        (self.root/'inputs'/'voice.wav').write_bytes(b'not-real-audio')
        assets=[]
        for i in (1, 2):
            name=f'S{i:02d}.mp4'
            (self.root/'sources'/name).write_bytes(b'not-real-video')
            assets.append({'id':f'a{i}','name':name,'original_name':name,
                           'kind':'video','path':f'sources/{name}','duration':12,
                           'verified':True,'source':'synthetic-test-source', 'people':[]})
        self.project={'id':'regression','edit_mode':'documentary','profile':'documentary',
                      'scenes':[],'production_script':{'text':SCRIPT},
                      'voiceover':{'path':'inputs/voice.wav','duration':4},
                      'srt':{'blocks':[{'number':1,'start_ms':0,'end_ms':2000,'text':'First'},
                                       {'number':2,'start_ms':2000,'end_ms':4000,'text':'Second'}]},
                      'assets':assets}

    def tearDown(self):
        self.temp.cleanup()

    def test_identical_soundbite_replay_is_nonblocking_and_visible(self):
        beats=read_beats(SCRIPT)
        report=proposal(self.project,beats)
        self.assertEqual(report['issues'],[])
        self.assertEqual(report['narration_gaps'],[])
        self.assertEqual(report['repeated_ranges'],[[1,3]])

    def test_legacy_approval_list_can_be_empty_and_replay_still_builds(self):
        beats=read_beats(SCRIPT)
        with patch('documentary_storyboard.source_rate',return_value='30'):
            built,plan=prepare(self.project,self.root,[],[],False,lambda _:True,
                               beats=beats,strict=False)
        pairs=built['documentary_beat_review']['approved_overlaps']
        self.assertEqual(pairs,[[1,3]])
        bites=built['documentary_beat_review']['sound_bites']
        self.assertEqual(len(bites),2)
        self.assertEqual([(b['source_file'],b['source_in_ms'],b['source_out_ms']) for b in bites],
                         [('S01.mp4',5000,6000),('S01.mp4',5000,6000)])
        self.assertEqual([b['timeline_in_ms'] for b in bites],[0,3000])
        self.assertEqual(plan['bites'][0]['asset_name'],plan['bites'][1]['asset_name'])

    def test_previous_project_cooldown_does_not_reject_documentary_replay(self):
        p=copy.deepcopy(self.project)
        p['repetition_policy']={'cooldown_slots':6,'source_interval_overlap_forbidden_within_window':True}
        p['scenes']=[{'asset_id':'a1','frame_in':0,'frame_out':30,'in_s':5.0,'plan_row':{}},
                     {'asset_id':'a1','frame_in':30,'frame_out':60,'in_s':5.0,'plan_row':{}}]
        self.assertEqual(repetition_errors(p),[])
        self.assertEqual(source_capacity_errors(p),[])

    def test_bad_source_still_blocks_instead_of_fabricating_footage(self):
        bad=copy.deepcopy(self.project)
        bad['assets'][0]['duration']=5.5
        with self.assertRaisesRegex(ValueError,'past the end'):
            prepare(bad,self.root,[],[],False,lambda _:True,beats=read_beats(SCRIPT))
        bad=copy.deepcopy(self.project)
        bad['assets'][0]['original_name']='S99.mp4'
        with self.assertRaisesRegex(ValueError,'missing or ambiguous'):
            prepare(bad,self.root,[],[],False,lambda _:True,beats=read_beats(SCRIPT))

    def test_optional_strict_validator_does_not_block_replay(self):
        with patch('documentary_strict.is_strict_pipeline_script',return_value=True):
            result=strict_validate(self.project,self.root,beats=read_beats(SCRIPT),
                                   frame_limits={'a1':12000,'a2':12000})
        self.assertEqual(result['issues'],[],result['issues'])
        self.assertTrue(any('001 and 003' in note for note in result['reuse_notes']))


if __name__=='__main__':
    unittest.main()
