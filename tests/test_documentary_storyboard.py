import copy,tempfile,unittest
from pathlib import Path
from documentary_storyboard import prepare,verified_source_interval
from tests.test_documentary_beats import SCRIPT

class StoryboardPreparationTest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);(self.root/'sources').mkdir();(self.root/'inputs').mkdir();(self.root/'sources'/'video.mp4').write_bytes(b'video');(self.root/'inputs'/'voice.wav').write_bytes(b'voice')
  self.p={'profile':'documentary','scenes':[],'production_script':{'text':SCRIPT},'voiceover':{'path':'inputs/voice.wav','name':'voice.wav','duration':4},'srt':{'blocks':[{'number':1,'start_ms':0,'end_ms':2000,'text':'Original one'},{'number':2,'start_ms':2000,'end_ms':4000,'text':'Original two'}]},'assets':[{'id':'a','name':'S01.mp4','original_name':'S01.mp4','kind':'video','path':'sources/video.mp4','duration':20,'revision':'v1'}]}
 def tearDown(self):self.tmp.cleanup()
 def test_places_original_narration_and_bite_without_mutating_inputs(self):
  before=copy.deepcopy(self.p);p,plan=prepare(self.p,self.root,[],[],False,lambda _:True)
  # Three slots: the narration before the bite, the bite, and the narration after
  # it. The bite is real picture, so it occupies its own frames on the edit clock.
  self.assertEqual(self.p,before);self.assertEqual(len(p['scenes']),3);self.assertEqual([(s['frame_in'],s['frame_out']) for s in p['scenes']],[(0,60),(60,120),(120,180)]);self.assertTrue(all(not s['approved'] for s in p['scenes']));self.assertEqual([(b['pause_s'],b['source_in_s'],b['source_out_s']) for b in plan['bites']],[(2,10,12)]);self.assertTrue(p['review_only_draft']);self.assertEqual((self.root/'inputs'/'voice.wav').read_bytes(),b'voice')
 def test_only_unmodified_script_or_approved_gap_uses_exact_interval(self):
  p,_=prepare(self.p,self.root,[],[],False,lambda _:True);a=self.p['assets'][0];scene=p['scenes'][0]
  self.assertEqual(verified_source_interval(p,scene,a),(0.0,2.0))
  changed=copy.deepcopy(scene);changed['in_s']=0.1;self.assertIsNone(verified_source_interval(p,changed,a))
  changed=copy.deepcopy(scene);changed['plan_row']['source_out_ms']=1900;self.assertIsNone(verified_source_interval(p,changed,a))
  changed=copy.deepcopy(scene);changed['plan_row']['source_file']='other.mp4';self.assertIsNone(verified_source_interval(p,changed,a))
 # The slot is verified against the ranges recorded when the storyboard was built,
 # not against the current text of the production script. Requiring the script's
 # hash to still match meant one edit anywhere invalidated all 151 slots at once,
 # so a single storyboard could only ever serve the one script it was born from.
 # The integrity checks above still fail closed on a slot that really was altered.
 def test_editing_the_script_does_not_invalidate_a_built_storyboard(self):
  p,_=prepare(self.p,self.root,[],[],False,lambda _:True);a=self.p['assets'][0];scene=p['scenes'][0]
  changed=copy.deepcopy(p);changed['production_script']['text']+=' edit'
  self.assertEqual(verified_source_interval(changed,scene,a),(0.0,2.0))
  # ...and the reader is told the script moved on, with the beat named.
  from documentary_frame_audit import stale_script_message
  self.assertIn('production script has changed',stale_script_message(changed,changed['documentary_beat_review'],changed['production_script']['text']))

 def test_reuse_allowed_but_missing_files_or_existing_work_still_fail(self):
  self.p['production_script']['text']=SCRIPT.replace('00:00:10,000','00:00:01,000').replace('00:00:12,000','00:00:03,000')
  allowed,_=prepare(self.p,self.root,[],[],False,lambda _:True)
  self.assertEqual(allowed['documentary_beat_review']['approved_overlaps'],[[1,2],[2,3]])
  self.p['production_script']['text']=SCRIPT;self.p['assets'][0]['name']='SO1.mp4';self.p['assets'][0]['original_name']='SO1.mp4'
  with self.assertRaisesRegex(ValueError,'missing'):prepare(self.p,self.root,[],[],False,lambda _:True)
  self.p['scenes']=[{'existing':True}]
  with self.assertRaisesRegex(ValueError,'existing'):prepare(self.p,self.root,[],[],False,lambda _:True)
 def test_gap_requires_explicit_matching_approval(self):
  self.p['production_script']['text']=SCRIPT.replace('00:00:00,000 --> 00:00:02,000','00:00:00,100 --> 00:00:02,000').replace('Source OUT: 00:00:02,000','Source OUT: 00:00:01,900',1)
  with self.assertRaisesRegex(ValueError,'gap'):prepare(self.p,self.root,[],[],False,lambda _:True)
  gap={'narration_in_ms':0,'narration_out_ms':100,'source_in_ms':15000,'source_out_ms':15100,'source_file':'S01.mp4'}
  p,_=prepare(self.p,self.root,[gap],[],False,lambda _:True);self.assertEqual((p['scenes'][0]['frame_in'],p['scenes'][0]['frame_out']),(0,3));self.assertEqual(p['scenes'][0]['in_s'],15)

 # -- narration no longer has to bookend the programme ----------------------
 # The user's note: "is not compulsory it start with narration, it can shuffle
 # and use anything the production script produce".
 OPENING_BITE_SCRIPT = """Beat: 001
Type: DOCUMENTARY SOUND BITE
Narration State: PAUSED (Suspended at 00:00:00,000)
Footage Audio: UNMUTED (100% Live Speech)
Video File: S01.mp4
Source IN: 00:00:05,000
Source OUT: 00:00:07,000
Duration: 00:00:02,000
Speaker: Not verified
On-screen Caption: None
Beat: 002
Type: NARRATION (VOICE OVER)
Narration State: PLAYING
Narration Clock: 00:00:00,000 --> 00:00:04,000
Footage Audio: MUTED (0%)
Video File: S01.mp4
Source IN: 00:00:00,000
Source OUT: 00:00:04,000
On-screen Caption: None
Beat: 003
Type: DOCUMENTARY SOUND BITE
Narration State: PAUSED (Suspended at 00:00:04,000)
Footage Audio: UNMUTED (100% Live Speech)
Video File: S01.mp4
Source IN: 00:00:14,000
Source OUT: 00:00:16,000
Duration: 00:00:02,000
Speaker: Not verified
On-screen Caption: None
"""

 def test_a_script_may_open_and_close_on_a_sound_bite(self):
  """This used to fail outright: "The script must begin and end with narration."

  Nothing in the timeline needed it. build_timeline places a bite at its own pause
  point, so a bite at 0.0 simply opens the programme, and one at the end of the
  narration closes it. The rule was a writing convention enforced as a hard error.
  """
  self.p['production_script']['text'] = self.OPENING_BITE_SCRIPT
  p, plan = prepare(self.p, self.root, [], [], False, lambda _: True)
  self.assertEqual([(b['pause_s'], b['source_in_s'], b['source_out_s']) for b in plan['bites']],
                   [(0.0, 5.0, 7.0), (4.0, 14.0, 16.0)])
  # The bites are picture too: the opening bite, one slot per narration line (two SRT
  # lines, cut exactly where line 2 starts), the closing bite -- and the film ends on
  # the bite, not on narration.
  self.assertEqual(len(p['scenes']), 4)
  self.assertEqual([s['plan_row']['srt_blocks'] for s in p['scenes'][1:3]], [[1], [2]])
  self.assertEqual(p['scenes'][2]['frame_in'], round(4.0 * 30))   # line 2: narration 2 s + the 2 s opening bite
  self.assertEqual(p['scenes'][0]['frame_in'], 0)
  self.assertEqual(p['scenes'][0]['plan_row']['continuity'], 'Documentary beat sound-bite')
  self.assertEqual(p['scenes'][-1]['plan_row']['continuity'], 'Documentary beat sound-bite')
  # 4.000s of narration plus the two 2.000s bites = 8.000s of programme.
  self.assertEqual(p['scenes'][-1]['frame_out'], round(8.0 * 30))

 def test_a_line_starting_a_few_ms_after_a_beat_edge_still_gets_its_slot(self):
  """Found on a made-up 10-minute film: a line began 11 ms after a narration beat
  started. Its own cut was (rightly) dropped as shorter than a frame, but the slot was
  then labelled with the previous line, and the render page said "Original SRT cue N
  has no picture slot". The slot whose first frame holds the line now carries it."""
  self.p['production_script']['text'] = self.OPENING_BITE_SCRIPT
  self.p['srt']['blocks'] = [{'number': 1, 'start_ms': 0, 'end_ms': 2011, 'text': 'one'},
                             {'number': 2, 'start_ms': 2011, 'end_ms': 4000, 'text': 'two'}]
  self.p['production_script']['text'] = self.OPENING_BITE_SCRIPT.replace(
   'Narration Clock: 00:00:00,000 --> 00:00:04,000', 'Narration Clock: 00:00:00,000 --> 00:00:02,000').replace(
   'Source OUT: 00:00:04,000', 'Source OUT: 00:00:02,000').replace(
   'Beat: 003', 'Beat: 003\nType: NARRATION (VOICE OVER)\nNarration State: PLAYING\nNarration Clock: 00:00:02,000 --> 00:00:04,000\n'
   'Footage Audio: MUTED (0%)\nVideo File: S01.mp4\nSource IN: 00:00:08,000\nSource OUT: 00:00:10,000\nOn-screen Caption: None\nBeat: 004')
  p, _ = prepare(self.p, self.root, [], [], False, lambda _: True)
  labelled = {n for s in p['scenes'] if not s['plan_row'].get('bite_id') for n in s['plan_row']['srt_blocks']}
  self.assertEqual(labelled, {1, 2})
  import documentary_cue_groups
  documentary_cue_groups.groups(p)   # raises if a line has no picture slot

 def test_a_bite_before_any_narration_must_start_at_zero(self):
  """The edge case that replaces the blanket rule.

  With no narration before it, a leading bite's pause is the only thing placing it.
  A script that asks for 00:00:01,000 has no narration ending there, so it is
  rejected rather than silently moved to zero -- this planner never retimes.
  """
  self.p['production_script']['text'] = self.OPENING_BITE_SCRIPT.replace(
      'Suspended at 00:00:00,000', 'Suspended at 00:00:01,000')
  with self.assertRaisesRegex(ValueError, 'must start at 00:00:00,000'):
   prepare(self.p, self.root, [], [], False, lambda _: True)

 def test_a_mid_script_bite_must_still_follow_narration(self):
  """The original intent of the rule, kept for bites in the middle.

  Two bites in a row are only allowed with an explicit approval, so a bite whose
  predecessor is another bite is rejected here without one.
  """
  twice = self.OPENING_BITE_SCRIPT.replace(
      'Beat: 002\nType: NARRATION (VOICE OVER)', 'Beat: 002\nType: DOCUMENTARY SOUND BITE', 1)
  twice = twice.replace('Narration State: PLAYING', 'Narration State: PAUSED (Suspended at 00:00:00,000)', 1)
  twice = twice.replace('Narration Clock: 00:00:00,000 --> 00:00:04,000', '', 1)
  twice = twice.replace('Footage Audio: MUTED (0%)', 'Footage Audio: UNMUTED (100% Live Speech)', 1)
  twice = twice.replace('Source IN: 00:00:00,000\nSource OUT: 00:00:04,000',
                        'Source IN: 00:00:08,000\nSource OUT: 00:00:10,000\nDuration: 00:00:02,000', 1)
  self.p['production_script']['text'] = twice
  # Removing that narration leaves an uncovered narration interval, and the gap
  # check reports it first: silent audio must be an explicit, approved decision.
  with self.assertRaises(ValueError) as caught:
   prepare(self.p, self.root, [], [], False, lambda _: True)
  self.assertRegex(str(caught.exception), 'gap|consecutive')

 def test_narration_a_few_milliseconds_over_the_audio_is_not_a_failure(self):
  """Measured on a real production: audio 368.93s, script ending 368.933s.

  The uploaded file's duration is rounded to the millisecond by its container, so a
  script written to a third decimal can land a few milliseconds past it. That is the
  same audio, not longer narration, and it refused the whole build. Anything past one
  output frame is still a genuine mismatch and must still fail.
  """
  # 4.000s of audio, script written to 4.003s: inside one frame, so it builds.
  script = SCRIPT.replace('00:00:02,000 --> 00:00:04,000',
                          '00:00:02,000 --> 00:00:04,003', 1)
  script = script.replace('Source OUT: 00:00:04,000', 'Source OUT: 00:00:04,003', 1)
  self.p['production_script']['text'] = script
  p, _plan = prepare(self.p, self.root, [], [], False, lambda _: True)
  # The last narration slot ends at the scripted mark; the bite's own slot follows it.
  narration = [x for x in p['scenes'] if x['plan_row']['continuity'].startswith('Documentary beat 00')]
  # The narration slot's own length is the scripted 2.003s; the slot before it was
  # the 2.000s bite, so the edit-clock mark is 2.000 + 2.003 = 4.003s.
  self.assertEqual(narration[-1]['plan_row']['timeline_out_ms'], 6000)

 def test_narration_beyond_one_frame_of_the_audio_still_fails(self):
  """A subtitle held a moment past the audio builds (tests/test_srt_voice_end.py);
  END_SLACK_S is not a licence to overrun the narration by a whole passage."""
  script = SCRIPT.replace('00:00:02,000 --> 00:00:04,000',
                          '00:00:02,000 --> 00:00:08,000', 1)
  script = script.replace('Source OUT: 00:00:04,000', 'Source OUT: 00:00:08,000', 1)
  self.p['production_script']['text'] = script
  with self.assertRaisesRegex(ValueError, 'narration runs to|longer than the audio|only 4.000s'):
   prepare(self.p, self.root, [], [], False, lambda _: True)
