"""Exercise source-clock review through the Flask routes with a real two-cut video."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
import app as server
import local_understanding as lu


class FootageReviewTest(unittest.TestCase):
    def test_review_still_candidates_and_replacement(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(server, 'PROJECTS', Path(tmp)):
            pid, aid = 'a'*16, 'b'*16
            root = Path(tmp)/pid
            root.mkdir()
            src = root/'source.mp4'
            subprocess.run([server.FFMPEG, '-v','error','-f','lavfi','-i','color=red:s=96x64:r=25:d=2',
                            '-f','lavfi','-i','color=blue:s=96x64:r=25:d=2','-filter_complex',
                            '[0:v][1:v]concat=n=2:v=1:a=0','-c:v','mpeg4',str(src)],check=True)
            cuts = lu._scenes(src,4)
            self.assertEqual([x['start_s'] for x in cuts], [0,2])
            p = {'id':pid,'assets':[{'id':aid,'path':src.name,'duration':4,'kind':'video'}],
                 'srt':{'blocks':[{'number':7,'start_ms':10000,'end_ms':12000,'text':'Blue bicycle'}]},
                 'production_script':{'text':'Approved script'},'scenes':[{'id':'approved'}]}
            saved = root/'project.json'
            saved.write_text(json.dumps(p),encoding='utf-8')
            before = saved.read_bytes()
            report = {'status':'complete','source_signature':lu._signature(src),'audio_timing_version':2,
                      'stages':{'transcript':{'status':'complete','result':{'segments':[
                          {'start_s':0.25,'end_s':1.125,'text':'Red paint.'},
                          {'start_s':2.125,'end_s':3.875,'text':'Blue bicycle.'}]}}}}
            lu._write(lu.result_path(root,aid),report)
            base = f'/api/projects/{pid}/understanding/{aid}'
            client = server.app.test_client()
            result = client.get(base+'/soundbites?cue=0').get_json()
            self.assertEqual(result['cue']['start_ms'],10000)
            self.assertEqual([(x['in_ms'],x['out_ms']) for x in result['items']],[(2125,3875)])
            self.assertEqual(client.get(base+'/soundbites?cue=99').status_code,400)
            for ms, channel in [(0,2),(2125,0)]:
                response = client.get(base+f'/frame.png?ms={ms}')
                self.assertEqual(response.status_code,200)
                img=cv2.imdecode(np.frombuffer(response.data,np.uint8),cv2.IMREAD_COLOR)
                self.assertEqual(img.shape,(64,96,3))
                self.assertGreater(img[32,48,channel],235)
            self.assertEqual(client.get(base+'/frame.png?ms=4000').status_code,400)
            with src.open('ab') as out:
                out.write(b'x')
            self.assertEqual(client.get(base+'/soundbites').status_code,400)
            self.assertEqual(saved.read_bytes(),before)

