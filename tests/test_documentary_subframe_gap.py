"""Regression tests for the previously blocking Maleah 5ms narration tail."""
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from documentary_beat_plan import proposal
from documentary_beats import read_beats
from documentary_gap_policy import is_subframe_gap
from documentary_storyboard import prepare

SCRIPT = """Beat: 001
Type: VOICE OVER
Narration Clock: 00:00:00,000 --> 00:00:02,000
Narration State: RESUMING
Spoken Narration: First segment.
Full source: S01.mp4
Source IN: 00:00:00,000
Source OUT: 00:00:02,000
Footage Audio: MUTED (0%)
Beat: 002
Type: DOCUMENTARY SOUND BITE
Narration State: PAUSED (Suspended at 00:00:02,000)
Speaker: Interviewee
Full source: S01.mp4
Source IN: 00:00:05,000
Source OUT: 00:00:06,000
Duration: 00:00:01,000
Footage Audio: UNMUTED (100%)
"""

class SubFrameGapRegressions(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory()
  self.root=Path(self.temp.name);(self.root/'sources').mkdir()
  (self.root/'sources'/'S01.mp4').write_bytes(b'synthetic-video')
  (self.root/'voice.wav').write_bytes(b'synthetic-test-audio')
  self.p={'id':'subframe-test','scenes':[],'profile':'documentary','edit_mode':'documentary',
          'production_script':{'text':SCRIPT},
          'voiceover':{'path':'voice.wav','duration':2.005},
          'srt':{'blocks':[{'number':1,'start_ms':0,'end_ms':2000,'text':'First segment.'}]},
          'assets':[{'id':'a1','name':'S01.mp4','original_name':'S01.mp4',
                     'kind':'video','path':'sources/S01.mp4','duration':12}]}
 def tearDown(self):self.temp.cleanup()
 def test_five_milliseconds_not_proposed_as_missing_footage(self):
  report=proposal(self.p,read_beats(SCRIPT))
  self.assertEqual(report['issues'],[])
  self.assertEqual(report['narration_gaps'],[])
 def test_build_succeeds_without_gap_approval_and_keeps_voiceover(self):
  with patch('documentary_storyboard.source_rate',return_value='30'):
   staged,plan=prepare(self.p,self.root,[],[],False,lambda _:True,beats=read_beats(SCRIPT))
  self.assertEqual(len(plan['bites']),1)
  self.assertEqual(self.p['voiceover']['duration'],2.005)
  self.assertEqual(staged['voiceover']['duration'],2.005)
 def test_stale_subframe_gap_proposal_is_ignored(self):
  old=[{'narration_in_ms':2000,'narration_out_ms':2005,'source_file':'S01.mp4',
        'source_in_ms':7000,'source_out_ms':7005}]
  with patch('documentary_storyboard.source_rate',return_value='30'):
   staged,plan=prepare(self.p,self.root,old,[],False,lambda _:True,beats=read_beats(SCRIPT))
  self.assertEqual(len(plan['bites']),1)
 def test_34ms_gap_is_real_and_still_requires_cover(self):
  bad=copy.deepcopy(self.p);bad['voiceover']['duration']=2.034
  report=proposal(bad,read_beats(SCRIPT))
  self.assertEqual(len(report['narration_gaps']),1)
  with patch('documentary_storyboard.source_rate',return_value='30'):
   with self.assertRaisesRegex(ValueError,'Explicit gap decisions'):
    prepare(bad,self.root,[],[],False,lambda _:True,beats=read_beats(SCRIPT))
 def test_consistency_across_30fps_boundary(self):
  self.assertTrue(is_subframe_gap(1990,2000))
  self.assertTrue(is_subframe_gap(2000,2020))
  self.assertFalse(is_subframe_gap(2000,2034))

if __name__=='__main__':unittest.main()
