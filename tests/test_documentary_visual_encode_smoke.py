"""Encoded FFmpeg smoke tests: rendered still motion and genuine transition frames.

These tests need FFmpeg and Pillow but do not require PyAV, a running Flask server,
case media, or network access. They are short synthetic tests, NOT a Windows pilot.
"""
import hashlib
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import cinematic
from person_overlays import settings as person_settings, motion_camera

try:
    from PIL import Image, ImageDraw
except ImportError:
    Image = None


@unittest.skipUnless(shutil.which('ffmpeg') and Image is not None, 'FFmpeg and Pillow are required')
class RenderedVisualSmoke(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def ff(self,*args):
        p=subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y',*map(str,args)],capture_output=True,text=True)
        if p.returncode:
            self.fail('FFmpeg failed: '+p.stderr[-1200:])

    def rgb(self,file,when):
        result=subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-ss',str(when),'-i',str(file),
                              '-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','pipe:1'],capture_output=True)
        self.assertEqual(result.returncode,0)
        return result.stdout

    def test_auto_fullscreen_photo_actually_changes_rendered_frames(self):
        image=self.root/'photo.png'
        im=Image.new('RGB',(320,180),'#f1d9b8');draw=ImageDraw.Draw(im)
        draw.rectangle((0,0,125,180),fill='#cf6b4a');draw.rectangle((190,15,300,165),fill='#286b8c')
        draw.ellipse((123,40,205,120),fill='yellow')
        im.save(image)
        conf=person_settings({'person_overlay_settings':{'enabled':True,'style':'full',
                              'photo_motion':'auto_story','photo_motion_intensity':'medium'}})
        cam=motion_camera({'id':'test-person','name':'Sample','focus_y':0.4},conf)
        self.assertTrue(cam and cinematic.is_moving(cam))
        filt=cinematic.ffmpeg_filter(cam,320,180,0,90)
        target=self.root/'photo_camera.mp4'
        self.ff('-loop','1','-framerate','30','-i',image,'-vf',f'{filt},format=yuv420p',
                '-frames:v','90','-c:v','libx264',target)
        first,last=self.rgb(target,0.1),self.rgb(target,2.85)
        self.assertNotEqual(hashlib.sha256(first).digest(),hashlib.sha256(last).digest())

    def test_two_actual_cuts_encode_blended_transition(self):
        target=self.root/'fade.mp4'
        self.ff('-f','lavfi','-i','color=c=red:s=320x180:r=30:d=2',
                '-f','lavfi','-i','color=c=blue:s=320x180:r=30:d=2',
                '-filter_complex','[0:v][1:v]xfade=transition=fade:duration=0.5:offset=1.5,format=yuv420p[v]',
                '-map','[v]','-frames:v','105','-c:v','libx264',target)
        left,mid,right=self.rgb(target,1.20),self.rgb(target,1.75),self.rgb(target,2.25)
        def mean(c):return tuple(sum(c[i::3])//(len(c)//3) for i in range(3))
        a,b,z=mean(left),mean(mid),mean(right)
        self.assertGreater(a[0],a[2]+80)
        self.assertGreater(z[2],z[0]+80)
        self.assertGreater(b[0],z[0]+20)
        self.assertGreater(b[2],a[2]+20)


if __name__=='__main__':
    unittest.main()
