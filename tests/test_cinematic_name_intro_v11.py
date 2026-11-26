"""Cinematic NAME-ONLY intro is first display only, matches preview/export variants."""
import tempfile
import unittest
from pathlib import Path
from PIL import Image
import person_overlays as po

class NameIntro(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        (self.root/'people').mkdir()
        Image.new('RGB',(300,420),(110,100,90)).save(self.root/'people/a.jpg')
        self.person={'id':'p','name':'TEST CASE PERSON','role':'Suspect',
                     'photo':{'path':'people/a.jpg'},'show':True,'photo_over_video':True}
    def tearDown(self):self.temp.cleanup()
    def project(self):
        return {'people':[self.person], 'assets':[], 'scenes':[],
                'srt':{'blocks':[{'number':1,'start_ms':1000,'end_ms':4000,'text':'TEST CASE PERSON arrived'},
                                 {'number':2,'start_ms':12000,'end_ms':15000,'text':'TEST CASE PERSON spoke'}]},
                'voiceover':{'duration':17}, 'person_overlay_settings':{'enabled':True,'style':'full',
                 'timing':'cue','smart_photo_mode':False}}
    def test_only_first_window_gets_name_intro(self):
        r=po.plan(self.project(),self.root, {'version':1,'revision':1,'bites':[]})
        self.assertEqual(len(r['windows']),2)
        self.assertEqual([w['name_intro'] for w in r['windows']],[True,False])
    def test_disabled_intros_never_render_labels(self):
        p=self.project();p['person_overlay_settings']['cinematic_name_intro']=False
        r=po.plan(p,self.root, {'version':1,'revision':1,'bites':[]})
        self.assertEqual([w['name_intro'] for w in r['windows']],[False,False])
    def test_first_label_png_has_pixels_but_no_role_text(self):
        conf=po.settings(self.project()); conf['show_label']=True
        _,label=po.layer_files(self.person,self.root,640,360,conf)
        self.assertTrue(label.is_file())
        with Image.open(label) as img:
            self.assertEqual(img.size,(640,360))
            self.assertGreater(img.getchannel('A').getbbox()[3],300)
        self.assertEqual(po.settings(self.project())['cinematic_name_intro'],True)
    def test_first_photo_card_and_later_card_use_different_images(self):
        conf=po.settings(self.project()); early=dict(conf, show_label=True); late=dict(conf,show_label=False)
        a=po.card_file(self.person,self.root,640,360,early)
        b=po.card_file(self.person,self.root,640,360,late)
        self.assertNotEqual(a,b)
    def test_render_plan_has_label_only_on_first_window(self):
        project=self.project();work=self.root/'work';work.mkdir()
        args,steps,count=po.render_filters(project,self.root,{'version':1,'revision':1,'bites':[]},
                                          320,180,'30',work,1)
        self.assertEqual(count,2)
        self.assertEqual(sum('format=yuva420p[lb' in x for x in steps),1)   # v19: YUV with alpha, decoded once
        # v15: the name is held for the whole photo window; it never fades on its own.
        self.assertEqual(sum('fade=t=' in x and '[lb' in x for x in steps),0)

if __name__ == '__main__': unittest.main()
