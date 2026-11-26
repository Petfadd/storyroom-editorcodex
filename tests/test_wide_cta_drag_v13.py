"""V13 CTA geometry: large as default, draggable and resizable without timing edits."""
import tempfile
import unittest
import shutil
import subprocess
from pathlib import Path
from PIL import Image, ImageDraw
from channel_cta import settings, validate_patch, prepared_card, motion_coordinates, render_filters, plan

class WideCTATest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        (self.root/'assets').mkdir()
        Image.new('RGBA',(1280,720),(250,0,0,255)).save(self.root/'assets'/'channel_cta.png')
        self.project={'id':'a', 'channel_cta_asset':{'file':'channel_cta.png'},'channel_cta':{'enabled':True,'mode':'manual','motion_style':'dissolve','fade_s':0, 'manual_in_s':1.,'manual_out_s':5.}}

    def test_default_full_width_and_legacy_upgrade(self):
        self.assertEqual(settings(self.project)['width'],.97)
        old={**self.project,'channel_cta':{**self.project['channel_cta'],'width':.38,'position':'lower_right'}}
        self.assertEqual(settings(old)['width'],.97)
        self.assertEqual((settings(old)['center_x'],settings(old)['center_y']),(.5,.5))
        card,w,h=prepared_card(self.project,self.root,1280,720,self.root)
        self.assertEqual((w,h),(1242,699))   # 97% width; v14 allows the full frame height
        self.assertTrue(card.exists())

    def test_saved_custom_placement_is_used_and_does_not_change_timing(self):
        before=plan(self.project,self.root)
        self.project['channel_cta'].update({'width':.4,'center_x':.75,'center_y':.25})
        self.assertEqual(settings(self.project)['width'],.4)
        self.assertEqual(plan(self.project,self.root),before)
        filename,w,h=prepared_card(self.project,self.root,1280,720,self.root)
        self.assertEqual((w,h),(512,288))
        x,y=motion_coordinates('dissolve',1280,720,w,h,1.,5.,0,0,.75,.25)
        self.assertEqual((x,y),('704','36'))

    def test_geometry_limits_and_manual_save_finite(self):
        self.assertEqual(validate_patch({'width':.55,'center_x':.81,'center_y':.20}),{'width':.55,'center_x':.81,'center_y':.2})
        for bad in ({'width':.1},{'width':1.1},{'center_x':-1},{'center_y':float('nan')},{'position':'lower_right'}):
            with self.subTest(bad=bad),self.assertRaises(ValueError):validate_patch(bad)

    @unittest.skipUnless(shutil.which('ffmpeg'),'needs ffmpeg')
    def test_export_respects_custom_position_and_size(self):
        # Transparent overlay centered at x=.75, y=.25, width .40 over blue video.
        self.project['channel_cta'].update({'width':.4,'center_x':.75,'center_y':.25})
        args,steps,count=render_filters(self.project,self.root,None,640,360,'30',self.root,1,between=(0,180))
        self.assertEqual(count,1)
        graph=['[0:v]setpts=PTS-STARTPTS[base]']+steps+['[cta]format=yuv420p[out]']
        output=self.root/'result.mp4'
        cmd=['ffmpeg','-v','error','-y','-f','lavfi','-i','color=c=blue:s=640x360:r=30:d=6',*args,'-filter_complex',';'.join(graph),'-map','[out]','-an','-c:v','mpeg4','-q:v','4',str(output)]
        subprocess.run(cmd,check=True,timeout=30,capture_output=True)
        png=self.root/'f.png'
        subprocess.run(['ffmpeg','-v','error','-y','-ss','3','-i',str(output),'-frames:v','1',str(png)],check=True,timeout=12,capture_output=True)
        im=Image.open(png).convert('RGB')
        self.assertGreater(im.getpixel((480,90))[0],120) # red card near desired center
        self.assertLess(im.getpixel((30,90))[0],50) # blue background outside overlay
        self.assertLess(im.getpixel((480,320))[0],50) # card is up high
        out=subprocess.run(['ffprobe','-v','error','-count_frames','-select_streams','v:0','-show_entries','stream=nb_read_frames','-of','default=nw=1:nk=1',str(output)],capture_output=True,text=True,check=True)
        self.assertEqual(int(out.stdout.strip()),180)

if __name__=='__main__':unittest.main()
