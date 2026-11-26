"""Cutaway acceptance: picture-only, source validated, no clock/audio changes."""
import tempfile
import unittest
from pathlib import Path
from fractions import Fraction
from unittest.mock import patch
from documentary_cutaways import parse, split_spans, millis


def source_event():
    return {'labels':['028'],'scene_ids':['sb1'],'kind':'sound_bite','asset_id':'speaker','source':'S01.mp4',
            'source_start_frame':300,'source_end_frame':900,'source_fps':'30', 'source_rate_fps':'30',
            'frame_conversion':'none','picture_scale':100,'camera':None,
            'timeline_in_ms':0,'timeline_out_ms':20000,'output_start_frame':0,
            'output_end_frame':600,'source_frame_count':600,'output_frame_count':600,
            'frame_difference':0}


class CutawayTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name);(self.root/'sources').mkdir()
        for file in ('S01.mp4','S02.mp4','B10.jpg'):(self.root/'sources'/file).write_bytes(b'fixture')
        self.project={'documentary_cutaways':[],'scenes':[{'id':'sb1','plan_row':{'script_beat':'028'}}],
            'assets':[{'id':'speaker','kind':'video','original_name':'S01.mp4','path':'sources/S01.mp4','duration':30},
                      {'id':'video','kind':'video','original_name':'S02.mp4','path':'sources/S02.mp4','duration':30},
                      {'id':'image','kind':'image','original_name':'B10.jpg','path':'sources/B10.jpg'}]}
    def tearDown(self):self.temp.cleanup()

    def test_json_and_markdown_parse(self):
        row={'id':'CUTAWAY-001','soundbite_beat':'028','timeline_in':'00:00:05.000',
             'timeline_out':'00:00:10.000','picture_source':'S02.mp4','source_in':'00:00:12.000',
             'source_out':'00:00:17.000','reason':'Confirmed roadway'}
        self.assertFalse(parse([row])[0]['approved'])
        m='| ID | Soundbite Beat | Film IN | Film OUT | Picture File | Picture IN | Picture OUT | Approved | Reason |\n| --- | --- | --- | --- | --- | --- | --- | --- | --- |\n| CUTAWAY-001 | 028 | 00:00:05.000 | 00:00:10.000 | S02.mp4 | 00:00:12.000 | 00:00:17.000 | yes | Verified roadway |'
        self.assertTrue(parse(m)[0]['approved'])
        self.assertEqual(millis('00:01:00.000','time'),60000)

    @patch('strict_cuts.source_rate', return_value=Fraction(30))
    def test_video_split_preserves_speaker_source_clock(self, mock):
        self.project['documentary_cutaways']=parse([{'id':'CUTAWAY-001','soundbite_beat':'028','timeline_in':'00:00:05.000',
          'timeline_out':'00:00:10.000','picture_source':'S02.mp4','source_in':'00:00:12.000','source_out':'00:00:17.000','approved':True}])
        spans,used=split_spans(self.project,self.root,[source_event()],Fraction(30))
        self.assertEqual([s['source'] for s in spans],['S01.mp4','S02.mp4','S01.mp4'])
        self.assertEqual([(s['source_start_frame'],s['source_end_frame']) for s in spans],[(300,450),(360,510),(600,900)])
        self.assertEqual(sum(x['source_frame_count'] for x in spans),600)
        self.assertEqual((spans[0]['output_start_frame'],spans[-1]['output_end_frame']),(0,600))
        self.assertEqual([x['id'] for x in used],['CUTAWAY-001'])

    def test_photo_split_and_return(self):
        self.project['documentary_cutaways']=parse([{'id':'CUTAWAY-002','soundbite_beat':'028',
           'timeline_in':'00:00:05.000','timeline_out':'00:00:10.000',
           'picture_source':'B10.jpg','approved':True}])
        spans,used=split_spans(self.project,self.root,[source_event()],Fraction(30))
        self.assertEqual(spans[1]['kind'],'cutaway')
        self.assertEqual(spans[1]['source'],'B10.jpg')
        self.assertEqual(spans[1]['source_frame_count'],150)
        self.assertEqual(spans[2]['source_start_frame'],600)

    @patch('strict_cuts.source_rate', return_value=Fraction(30))
    def test_rejected_wrong_bite_missing_file_or_short_window(self, mock):
        def row(**changes):
            return dict(id='CUTAWAY-001',soundbite_beat='028',timeline_in='00:00:05.000',
                        timeline_out='00:00:10.000',picture_source='S02.mp4',source_in='00:00:12.000',
                        source_out='00:00:17.000',approved=True, **changes)
        for changes in ({'soundbite_beat':'009'},{'picture_source':'ghost.mp4'},
                        {'timeline_out':'00:00:21.000'},{'source_out':'00:00:14.000'}):
            a={**row(),**changes}
            self.project['documentary_cutaways']=parse([a])
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                split_spans(self.project,self.root,[source_event()],Fraction(30))

    @patch('strict_cuts.source_rate', return_value=Fraction(30))
    def test_render_plan_uses_reviewed_cutaways_without_touching_captions(self, mock):
        from unittest.mock import patch
        from documentary_render_plan import plan
        self.project['documentary_cutaways']=parse([{'id':'CUTAWAY-001','soundbite_beat':'028',
           'timeline_in':'00:00:05.000','timeline_out':'00:00:10.000',
           'picture_source':'S02.mp4','source_in':'00:00:12.000','source_out':'00:00:17.000',
           'approved':True}])
        event={'label':'028','scene_id':'sb1','kind':'sound_bite','asset_id':'speaker','source':'S01.mp4',
           'source_start_frame':300,'source_end_frame':900,'source_fps':'30',
           'timeline_in_ms':0,'timeline_out_ms':20000,'caption':'Officer — verified statement','picture_scale':100}
        with patch('documentary_render_plan.playback_schedule',return_value=[event]):
            result=plan(self.project,self.root,{},None)
        self.assertTrue(result['picture_compatible'],result['errors'])
        self.assertEqual(result['cutaways_applied'],['CUTAWAY-001'])
        self.assertEqual([s['source'] for s in result['spans']],['S01.mp4','S02.mp4','S01.mp4'])
        self.assertEqual(len(result['captions']),0)  # not enabled; nothing invented
        self.assertEqual(sum(x['source_frame_count'] for x in result['spans']),600)

    def test_unapproved_does_not_change_picture(self):
        self.project['documentary_cutaways']=parse([{'id':'CUTAWAY-001','soundbite_beat':'028',
           'timeline_in':'00:00:05.000','timeline_out':'00:00:10.000','picture_source':'B10.jpg'}])
        original=source_event()
        spans,used=split_spans(self.project,self.root,[original],Fraction(30))
        self.assertEqual(spans,[original]);self.assertEqual(used,[])

    def test_overlaps_block_and_no_narration_override(self):
        self.project['documentary_cutaways']=parse([{'id':f'CUTAWAY-{x:03d}','soundbite_beat':'028',
           'timeline_in':i,'timeline_out':j,'picture_source':'B10.jpg','approved':True}
           for x,i,j in ((1,'00:00:05.000','00:00:10.000'),(2,'00:00:09.000','00:00:12.000'))])
        with self.assertRaisesRegex(ValueError,'overlaps'):
            split_spans(self.project,self.root,[source_event()],Fraction(30))

if __name__=='__main__':unittest.main()
