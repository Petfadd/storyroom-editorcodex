"""Focused regressions: four source downloads, authentic clips over unrelated photos."""
import io
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import case_people
import footage_downloader as fd


class RoleTest(unittest.TestCase):
    def test_core_people_only_and_juvenile_protection(self):
        for role in ('Victim', 'Survivor', 'Father', 'Adult family member', 'Mother', 'Suspect', 'Cousin'):
            self.assertTrue(case_people.featured_role(role), role)
        for role in ('', 'Friend', 'Victim\u2019s friend', 'Police officer', 'Detective', 'Lawyer',
                     'Judge', 'Pastor', 'City councilman', 'Witness', 'Protected juvenile suspect'):
            self.assertFalse(case_people.featured_role(role), role)

    def test_case_sheet_people_rows_are_classified_correctly(self):
        sheet = ("| P01 | Marcus May | Adult family member | https://youtu.be/AAAAAAAAAA1 |\n"
                 "| P02 | Santosha Scott | Survivor | https://youtu.be/AAAAAAAAAA2 |\n"
                 "| B10 | B10.jpg (S05) | FOR PEOPLE: Coreen Chatham; victim's friend; interview | "
                 "00:01:35–00:01:36 | https://youtu.be/AAAAAAAAAA5 |\n"
                 "| B04 | B04.jpg (S02) | FOR PEOPLE: Keveon Johnson; neighbor interview | "
                 "00:00:25–00:00:26 | https://youtu.be/AAAAAAAAAA4 |\n")
        entries={e['source_id']:e for e in fd.parse_manifest(sheet)['entries']}
        self.assertEqual(entries['P01']['person'], 'Marcus May')
        self.assertEqual(entries['P01']['role'], 'Family member')
        self.assertEqual(entries['P02']['role'], 'Survivor')
        self.assertEqual(entries['B10']['role'], 'Friend')
        for code in ('B04', 'B10'):
            self.assertFalse(case_people.featured_role(entries[code]['role']), code)

    def test_story_relevance_and_legacy_error_guard(self):
        project={'srt':{'blocks':[{'text':'Marcus May described his mother'}]},
                 'production_script':{'text':'Marcus May spoke as a family member'}}
        self.assertTrue(case_people.in_story('Marcus May', project))
        self.assertFalse(case_people.in_story('Coreen Chatham', project))
        p={'id':'c','name':'Coreen Chatham','role':'Victim','sheet_source':'B10'}
        assets=[{'provenance':{'source_id':'B10','description':"FOR PEOPLE: Coreen Chatham; victim's friend"}}]
        self.assertFalse(case_people.featured_person(p,assets))


class DownloadConcurrencyTest(unittest.TestCase):
    def test_new_sheet_default_is_four(self):
        parsed=fd.parse_manifest('\n'.join(f'| S{i:02} | https://youtu.be/AAAAAAAAA{i:02} |' for i in range(1,6)))
        self.assertEqual(fd.new_state('test.md',parsed,None)['options']['concurrency'],4)

    def test_four_jobs_start_in_parallel_not_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            parsed=fd.parse_manifest('\n'.join(f'| S{i:02} | https://youtu.be/AAAAAAAAA{i:02} |' for i in range(1,6)))
            state=fd.new_state('test.md',parsed,None)
            fd.save_state(tmp,state)
            active=0;high=0;started=threading.Event();allow_finish=threading.Event();lock=threading.Lock()
            def fake_download(self,row,options,work_root):
                nonlocal active,high
                with lock:
                    active+=1;high=max(high,active)
                    if active==4:started.set()
                allow_finish.wait(3)
                row.update(status=fd.COMPLETED,progress=100)
                with lock:active-=1
            job=fd.DownloadJob('four-test',tmp,lambda r,p:None,lambda r:None)
            try:
                with mock.patch.object(fd.DownloadJob,'_download_with_retries',fake_download):
                    job.start()
                    self.assertTrue(started.wait(2),'The initial four transfers did not start together')
                    self.assertEqual(high,4)
                    allow_finish.set()
                    job.thread.join(4)
                    self.assertFalse(job.thread.is_alive())
            finally:
                allow_finish.set()
                job.thread.join(4)
                with fd.JOBS_LOCK:fd.JOBS.pop('four-test',None)

    def test_uploaded_sheet_overrides_old_two_setting_and_autostarts(self):
        try:
            import app as server
        except ImportError:
            self.skipTest('Flask or application dependencies not installed here')
        with tempfile.TemporaryDirectory() as td:
            old=server.PROJECTS
            server.PROJECTS=Path(td)
            pid='abcdefabcdef0987';root=server.PROJECTS /pid;root.mkdir()
            (root/'project.json').write_text(json.dumps({'id':pid,'title':'Test','edit_mode':'documentary','updated':1,
               'brief':'','assets':[],'scenes':[],'people':[],'srt':None,'voiceover':None}))
            saved=fd.new_state('old.md',fd.parse_manifest('| S01 | https://youtu.be/AAAAAAAAAA1 |'),{'concurrency':2,'auto_start':False})
            fd.save_state(root,saved)
            try:
                with mock.patch.object(server,'start_youtube_job') as start:
                    r=server.app.test_client().post(f'/api/projects/{pid}/youtube/sheet',data={
                      'file':(io.BytesIO(b'| S01 | https://youtu.be/AAAAAAAAAA1 |'),'fresh.md')
                    },content_type='multipart/form-data')
                    self.assertEqual(r.status_code,200,r.get_json())
                    d=fd.load_state(root)
                    self.assertEqual(d['options']['concurrency'],4)
                    self.assertTrue(d['options']['auto_start'])
                    start.assert_called_once_with(pid)
            finally:
                server.PROJECTS=old


if __name__=='__main__':unittest.main()
