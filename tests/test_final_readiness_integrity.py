"""Final Storyroom readiness safeguards (no Flask or PyAV required)."""
import tempfile
import unittest
from pathlib import Path
from PIL import Image
import person_overlays as photos


class FeaturedPhotoSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        (self.root/'people').mkdir()
        Image.new('RGB',(240,360),(125,90,75)).save(self.root/'people'/'p.jpg')
        self.p={'id':'p1','name':'Jordan Taylor','role':'Victim','aliases':['Taylor','Jordon Taylor'],
                'photo':{'path':'people/p.jpg'},'short_names':False,'show':True}
    def tearDown(self): self.tmp.cleanup()
    def project(self, text='Jordan Taylor', scenes=None, options=None):
        return {'people':[self.p], 'assets':[], 'voiceover':{'duration':6},
                'person_overlay_settings':dict({'enabled': True},**(options or {})),
                'srt':{'blocks':[{'number':1,'start_ms':0,'end_ms':5000,'text':text}]},
                'scenes':scenes or []}
    def test_short_alias_not_enabled_without_explicit_opt_in(self):
        names=photos.find_mentions([{'number':1,'start_ms':0,'end_ms':2000,'text':'Taylor said'}],[self.p])
        self.assertEqual(names,[])
        self.assertEqual([x['said'] for x in photos.find_mentions(
            [{'number':1,'start_ms':0,'end_ms':2000,'text':'Jordon Taylor spoke'}],[self.p])],['Jordon Taylor'])
        self.p['short_names']=True
        self.assertEqual([x['said'] for x in photos.find_mentions(
            [{'number':1,'start_ms':0,'end_ms':2000,'text':'Taylor said'}],[self.p])],['Taylor'])
    def test_new_and_legacy_entries_are_both_opt_in(self):
        self.p.pop('short_names')
        self.assertEqual(photos.terms_for(self.p,[self.p]),['Jordan Taylor','Jordon Taylor'])
    def test_cue_window_stops_before_next_scripted_video(self):
        scenes=[{'asset_id':'a','frame_in':0,'frame_out':60,'in_s':0},
                {'asset_id':'b','frame_in':60,'frame_out':180,'in_s':20,
                 'plan_row':{'source_file':'S02.mp4','timeline_in_ms':2000,'timeline_out_ms':6000}}]
        result=photos.plan(self.project(scenes=scenes),self.root,{'version':1,'revision':1,'bites':[]})
        self.assertEqual([(x['start_ms'],x['end_ms']) for x in result['windows']],[(0,2000)])
        self.assertTrue(any('trimmed' in x for x in result['notes']))
    def test_photo_never_covers_a_scripted_video_at_name_start(self):
        scenes=[{'asset_id':'b','frame_in':0,'frame_out':180,'in_s':20,
                 'plan_row':{'source_file':'S02.mp4','timeline_in_ms':0,'timeline_out_ms':6000}}]
        result=photos.plan(self.project(scenes=scenes),self.root,{'version':1,'revision':1,'bites':[]})
        self.assertEqual(result['windows'],[])
    def test_legacy_footage_without_explicit_script_row_can_still_use_photo(self):
        scenes=[{'asset_id':'a','frame_in':0,'frame_out':180,'in_s':0}]
        result=photos.plan(self.project(scenes=scenes),self.root,{'version':1,'revision':1,'bites':[]})
        self.assertEqual([(x['start_ms'],x['end_ms']) for x in result['windows']],[(0,5000)])

if __name__=='__main__':unittest.main()
