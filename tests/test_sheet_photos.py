"""Photos of people come from the footage sheet: downloaded, named, filed with the person.

A local web server stands in for the internet; yt-dlp is the test stand-in.
"""
import functools
import http.server
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from io import BytesIO
from pathlib import Path

from PIL import Image

import app as server


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


class SheetPhotosTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        www = self.www = self.tmp / 'www'
        www.mkdir()
        Image.new('RGB', (900, 1200), (200, 120, 140)).save(www / 'maliyah.jpg')
        Image.new('RGB', (800, 800), (60, 90, 160)).save(www / 'sahara.png')
        Image.new('RGB', (500, 600), (220, 200, 40)).save(www / 'dad.gif')
        Image.new('RGB', (80, 80), (10, 10, 10)).save(www / 'tiny.jpg')
        (www / 'story.html').write_text('<!doctype html><html><head><title>Mother speaks</title>'
                                        '<meta property="og:image" content="/sahara.png"></head></html>')
        (www / 'empty.html').write_text('<!doctype html><html><head><title>x</title></head></html>')
        self.httpd = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(_Quiet, directory=str(www)))
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = f'http://127.0.0.1:{self.httpd.server_port}'
        self.env = {k: os.environ.get(k) for k in ('NO_PROXY', 'no_proxy', 'STORYROOM_YTDLP_CMD')}
        os.environ['NO_PROXY'] = os.environ['no_proxy'] = '127.0.0.1,localhost'
        os.environ['STORYROOM_YTDLP_CMD'] = f'{sys.executable} tests/fixtures/fake_ytdlp.py'
        self.old_projects = server.PROJECTS
        server.PROJECTS = self.tmp / 'projects'
        self.pid = 'feedfacefeedface'
        root = server.PROJECTS / self.pid
        root.mkdir(parents=True)
        srt = [{'number': 1, 'start_ms': 0, 'end_ms': 3000, 'text': 'Malia Bass was two'},
               {'number': 2, 'start_ms': 3000, 'end_ms': 6000, 'text': 'her mother Sahara Irvin called 911'}]
        (root / 'project.json').write_text(json.dumps({
            'id': self.pid, 'title': 'T', 'edit_mode': 'documentary', 'updated': 1.0, 'brief': '',
            'assets': [], 'scenes': [], 'people': [], 'voiceover': None, 'srt': {'blocks': srt}}))
        self.client = server.app.test_client()

    def tearDown(self):
        self.httpd.shutdown()
        server.PROJECTS = self.old_projects
        for k, v in self.env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_sheet(self, sheet):
        r = self.client.post(f'/api/projects/{self.pid}/youtube/sheet',
                             data={'file': (BytesIO(sheet.encode()), 'sheet.md')}, content_type='multipart/form-data')
        self.assertEqual(r.status_code, 200, r.get_json())
        if not self.client.get(f'/api/projects/{self.pid}/youtube').get_json()['running']:
            self.client.post(f'/api/projects/{self.pid}/youtube/start')
        for _ in range(120):
            d = self.client.get(f'/api/projects/{self.pid}/youtube').get_json()
            if not d['running'] and d['state']['job']['status'] not in ('running', 'ready'):
                return d
            time.sleep(0.5)
        self.fail('downloads did not finish')

    def test_photos_are_named_filed_and_matched_to_the_narration(self):
        b = self.base
        d = self.run_sheet(f"""| Photo | Person | Role | Link |
|---|---|---|---|
| P01 | Maliyah Bass | Victim | {b}/maliyah.jpg |
| P02 | Sahara Ervin | Mother | {b}/story.html |
| P03 | Brandon Bass | Father | {b}/dad.gif |
| P04 | Jaylen Bass | Brother | {b}/tiny.jpg |
| P05 | Someone Else | Witness | {b}/empty.html |
| P06 | Maliyah Bass | Victim | https://www.youtube.com/watch?v=GOODthumb06 |
""")
        rows = {r['source_id']: r for r in d['state']['rows']}
        self.assertEqual({k: r['status'] for k, r in rows.items()},
                         {'P01': 'completed', 'P02': 'completed', 'P03': 'completed', 'P04': 'completed',
                          'P05': 'failed', 'P06': 'completed'})
        self.assertIn('Copy image address', rows['P05']['error'])
        p = json.loads((server.PROJECTS / self.pid / 'project.json').read_text())
        names = sorted(a['name'] for a in p['assets'] if a['kind'] == 'image')
        # The real file type is kept (PNG from the page); a GIF is converted to JPG.
        self.assertEqual(names, ['P01.jpg', 'P02.png', 'P03.jpg', 'P04.jpg', 'P06.jpg'])
        people = {x['name']: x for x in p['people']}
        self.assertEqual(people['Maliyah Bass']['role'], 'Victim')
        self.assertIn('Malia Bass', people['Maliyah Bass']['suggested_aliases'])  # SRT spelling, to approve
        self.assertIn('Sahara Irvin', people['Sahara Ervin']['suggested_aliases'])
        self.assertEqual(people['Maliyah Bass']['photo']['name'], 'P01.jpg')  # first in the sheet wins
        self.assertEqual(people['Sahara Ervin']['photo']['name'], 'P02.png')
        self.assertNotIn('photo', people['Jaylen Bass'])                      # too small for full screen
        self.assertIn('too small', rows['P04']['note'])
        for person in people.values():
            if person.get('photo'):
                self.assertTrue((server.PROJECTS / self.pid / person['photo']['path']).is_file())

    def test_broll_is_filed_by_what_it_is_and_keeps_its_description(self):
        Image.new('RGB', (1280, 720), (30, 40, 120)).save(self.www / 'police.jpg')
        b = self.base
        d = self.run_sheet(f"""| B01 | Sunset Crossing Apartments exterior | 0:43-0:52 | https://www.youtube.com/watch?v=GOODbroll01&t=43s |
| B02 | Police cars at Brays Bayou | | {b}/police.jpg |
| B03 | Beechnut_frame.jpg | Beechnut at night | https://www.youtube.com/watch?v=GOODbroll03&t=12s |
""")
        rows = {r['source_id']: r for r in d['state']['rows']}
        self.assertEqual({k: r['status'] for k, r in rows.items()}, {'B01': 'completed', 'B02': 'completed', 'B03': 'completed'})
        p = json.loads((server.PROJECTS / self.pid / 'project.json').read_text())
        assets = {a['name']: a for a in p['assets']}
        self.assertEqual(assets['B01.mp4']['kind'], 'video')                    # a clip goes to Footage
        self.assertEqual(assets['B02.jpg']['kind'], 'image')                    # a picture goes to Photos
        self.assertEqual(assets['Beechnut_frame.jpg']['kind'], 'image')         # a frame at &t=12s
        self.assertEqual(assets['B01.mp4']['provenance']['description'], 'Sunset Crossing Apartments exterior')
        self.assertEqual(assets['B01.mp4']['provenance']['window'], [43.0, 52.0])
        self.assertEqual(p['people'], [])                                       # b-roll is nobody's photo
        self.assertIn('b-roll', rows['B01']['note'])

    def test_running_the_sheet_again_downloads_nothing_new(self):
        sheet = f'| P01 | Maliyah Bass | Victim | {self.base}/maliyah.jpg |\n'
        self.run_sheet(sheet)
        d = self.run_sheet(sheet)
        self.assertEqual(d['state']['rows'][0]['status'], 'completed')
        p = json.loads((server.PROJECTS / self.pid / 'project.json').read_text())
        self.assertEqual([a['name'] for a in p['assets']], ['P01.jpg'])
        self.assertEqual(len(p['people']), 1)


if __name__ == '__main__':
    unittest.main()
