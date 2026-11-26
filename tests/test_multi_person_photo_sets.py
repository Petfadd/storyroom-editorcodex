"""Approved 1–5 person photo sets: rotate only rendered mentions and keep legacy projects."""
import subprocess
import tempfile
import unittest
from pathlib import Path
from PIL import Image
import person_overlays as po


def cue(n, t, name='Maleah Davis'):
    return {'number': n, 'start_ms': t, 'end_ms': t+4000, 'text': f'{name} was remembered'}


class MultiPersonPhotoTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        (self.root/'people').mkdir()
        self.gallery=[]
        for n in range(5):
            name=f'people/photo-{n}.jpg'
            Image.new('RGB',(320,480),(20+40*n,80+n*15,140-n*20)).save(self.root/name)
            self.gallery.append({'path':name,'uploaded':n})
        self.person={'id':'victim01','name':'Maleah Davis','role':'Victim',
                     'photo':self.gallery[0],'photos':list(self.gallery),'show':True,
                     'photo_over_video':True}

    def tearDown(self):self.tmp.cleanup()

    def proj(self, times, **settings):
        return {'people':[self.person], 'srt':{'blocks':[cue(k+1,t) for k,t in enumerate(times)]},
                'assets':[], 'scenes':[], 'voiceover':{'duration':600},
                'person_overlay_settings':{'enabled':True,'style':'full','timing':'cue',**settings}}

    def test_legacy_single_photo_projects_still_work(self):
        legacy={'photo':self.gallery[0]}
        self.assertEqual(po.person_photos(legacy),[self.gallery[0]])
        self.assertTrue(po.has_photo(legacy,self.root))
        self.assertEqual(po.photo_at(legacy,0),self.gallery[0])
        self.assertIsNone(po.photo_at(legacy,1))

    def test_5_photos_rotate_in_order_then_cycle(self):
        data=po.plan(self.proj([0,12000,24000,36000,48000,60000,72000]),self.root,
                     {'version':1,'revision':1,'bites':[]})
        self.assertEqual([w['photo_index'] for w in data['windows']],[0,1,2,3,4,0,1])
        self.assertEqual(data['people'][0]['windows'],7)

    def test_two_photos_alternate_without_immediate_repeat(self):
        self.person['photos']=self.gallery[:2]
        data=po.plan(self.proj([0,12000,24000,36000,48000]),self.root,
                     {'version':1,'revision':1,'bites':[]})
        self.assertEqual([w['photo_index'] for w in data['windows']],[0,1,0,1,0])

    def test_automatic_mode_prioritizes_people_but_fewer_placements_than_mentions(self):
        self.person['photo_over_video']=False
        self.person['photos']=self.gallery[:1]
        times=[k*30000 for k in range(11)]
        data=po.plan(self.proj(times,smart_photo_mode=True),self.root,
                     {'version':1,'revision':1,'bites':[]})
        indexes=[w['photo_index'] for w in data['windows']]
        self.assertEqual(indexes,[0]*len(indexes))
        self.assertLess(len(indexes),len(times))

    def test_5_photos_smart_mode_respects_checked_mentions(self):
        self.person['photo_over_video']=False
        times=[k*30000 for k in range(11)]
        data=po.plan(self.proj(times,smart_photo_mode=True),self.root,
                     {'version':1,'revision':1,'bites':[]})
        indexes=[w['photo_index'] for w in data['windows']]
        self.assertEqual(indexes,[i%5 for i in range(len(times))])

    def test_suspect_mugshot_is_not_shown_before_arrest(self):
        self.person['role']='Suspect'
        self.person['photos']=[dict(self.gallery[0],mugshot=True),self.gallery[1]]
        self.person['photo']=self.person['photos'][0]
        blocks=[cue(1,0),cue(2,12000),{'number':3,'start_ms':24000,'end_ms':28000,'text':'He was arrested'},cue(4,36000)]
        project=self.proj([]);project['srt']={'blocks':blocks}
        data=po.plan(project,self.root,{'version':1,'revision':1,'bites':[]})
        self.assertEqual([w['photo_index'] for w in data['windows']],[1,1,0])

    def test_cards_use_distinct_cached_photo_assets(self):
        p0=po.photo_person(self.person,0)
        p1=po.photo_person(self.person,1)
        first=po.card_file(p0,self.root,320,180,po.settings(self.proj([])))
        second=po.card_file(p1,self.root,320,180,po.settings(self.proj([])))
        self.assertNotEqual(first,second)
        self.assertTrue(first.is_file() and second.is_file())

    def test_soundbite_window_protected(self):
        project=self.proj([0,18000]);project['voiceover']['duration']=30
        bite={'id':'a','asset_id':'s1','asset_name':'S01.mp4','pause_s':10,'source_in_s':0,'source_out_s':20}
        data=po.plan(project,self.root,{'version':1,'revision':1,'bites':[bite]})
        self.assertEqual(len(data['windows']),2)
        self.assertLessEqual(data['windows'][0]['end_ms'],10000)
        self.assertGreaterEqual(data['windows'][1]['start_ms'],30000)


if __name__=='__main__':unittest.main()
