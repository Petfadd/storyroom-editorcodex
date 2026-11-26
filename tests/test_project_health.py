"""Stage 1 regression: health checks never mutate the authoritative inputs."""
import copy
import tempfile
import unittest
from pathlib import Path

from project_health import assess


SCRIPT = '''Beat: 001
Type: VOICE OVER
Narration State: PLAYING
Narration Clock: 00:00:00,000 --> 00:00:02,000
Footage Audio: MUTED (0%)
Full Source: S01.mp4
Source IN: 00:00:00,500
Source OUT: 00:00:02,500
Beat: 002
Type: DOCUMENTARY SOUND BITE
Narration State: PAUSED
Narration Clock: PAUSED at 00:00:02,000
Footage Audio: UNMUTED (100%)
Full Source: S02.mp4
Source IN: 00:00:03,000
Source OUT: 00:00:04,000
Duration: 00:00:01,000
'''


class HealthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root/'sources').mkdir()
        (self.root/'inputs').mkdir()
        (self.root/'inputs'/'narration.wav').write_bytes(b'placeholder')
        self.project = {
            'edit_mode':'documentary', 'production_script':{'text':SCRIPT},
            'voiceover':{'path':'inputs/narration.wav','duration':2.0},
            'srt':{'blocks':[{'number':1,'start_ms':0,'end_ms':2000,'text':'hello'}]},
            'scenes':[], 'assets':[],
        }

    def _asset(self, filename, duration=5.0):
        (self.root/'sources'/filename).write_bytes(b'video-placeholder')
        return {'kind':'video','name':filename,'original_name':filename,
                'path':'sources/'+filename,'duration':duration}

    def test_pending_is_progress_not_review(self):
        original = copy.deepcopy(self.project)
        result = assess(self.project, self.root)
        self.assertEqual(result['status'],'waiting')
        self.assertEqual(result['summary']['beats'],2)
        self.assertEqual(result['summary']['soundbites'],1)
        self.assertEqual(result['summary']['missing_sources'],['S01.mp4','S02.mp4'])
        self.assertEqual(self.project, original)
        self.assertFalse((self.root/'downloads').exists())

    def test_ready_after_exact_uploads_and_timeline(self):
        self.project['assets'] = [self._asset('S01.mp4'),self._asset('S02.mp4')]
        self.project['scenes'] = [{'id':'s'}]
        result = assess(self.project,self.root)
        self.assertEqual(result['status'],'ready')
        self.assertEqual(result['summary']['sources_ready'],2)
        self.assertNotIn('rights verified',result['note'].lower())

    def test_fails_closed_on_short_source_without_retiming(self):
        self.project['assets'] = [self._asset('S01.mp4',1.9),self._asset('S02.mp4')]
        old = copy.deepcopy(self.project)
        result = assess(self.project,self.root)
        self.assertEqual(result['status'],'review')
        self.assertTrue(any('S01.mp4' in c['message'] and c['key']=='source_files' for c in result['checks']))
        self.assertEqual(self.project,old)

    def test_invalid_script_explicit_review(self):
        self.project['production_script']['text']='Beat: 001\nType: VOICE OVER\nFull Source: nofile'
        result = assess(self.project,self.root)
        self.assertEqual(result['status'],'review')
        self.assertTrue(any(c['key']=='script_reader' and c['state']=='review' for c in result['checks']))

    def test_misaligned_srt_and_audio_flags_no_rewrite(self):
        self.project['voiceover']['duration']=11.0
        result = assess(self.project,self.root)
        self.assertEqual(result['status'],'review')
        self.assertTrue(any(c['key']=='audio_srt_length' for c in result['checks']))
        self.assertEqual(self.project['voiceover']['duration'],11.0)

    def test_bad_srt_clock_flags_review(self):
        self.project['srt']['blocks']=[{'start_ms':2000,'end_ms':1000}]
        result=assess(self.project,self.root)
        self.assertEqual(result['status'],'review')
        self.assertTrue(any(c['key']=='srt' and c['state']=='review' for c in result['checks']))


if __name__=='__main__': unittest.main()
