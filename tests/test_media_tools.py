"""No-network verification of Storyroom's optional installer and status API core."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import zipfile

import media_tools as m


class MediaToolsTests(unittest.TestCase):
    def test_allowlist_rejects_arbitrary_commands(self):
        for bad in ('', 'pip install everything', '../foo', '--help', 'whisperx', 'yt-dlp; rm -rf /'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                m.install(bad)

    def test_status_never_triggers_install(self):
        speech = {'package': {'installed': False, 'detail': 'missing'},
                  'model': {'installed': False, 'detail': 'missing'},
                  'progress': {'status': 'idle'}}
        with patch.object(m, '_yt_status', return_value={'available': False}), \
             patch.object(m, '_speech_status', return_value=speech), \
             patch.object(m, '_module', return_value={'ready': False, 'version': None}), \
             patch.object(m, '_which', return_value=None), \
             patch.object(m, '_version', return_value='FFmpeg version'), \
             patch.object(m, '_do_install', side_effect=AssertionError('status must not install')):
            d = m.status(refresh=True)
        self.assertTrue(d['tools']['python']['ready'])
        self.assertFalse(d['tools']['yt-dlp']['ready'])
        self.assertFalse(d['tools']['scenedetect']['ready'])
        self.assertFalse(d['tools']['whisperx']['ready'])
        self.assertIn('install', d)

    def test_archive_extract_rejects_duplicates(self):
        with tempfile.TemporaryDirectory() as td:
            z = Path(td) / 'two.zip'
            with zipfile.ZipFile(z, 'w') as f:
                f.writestr('a/bin/ffprobe.exe', b'a')
                f.writestr('b/bin/ffprobe.exe', b'b')
            with self.assertRaisesRegex(RuntimeError, 'exactly one'):
                m.extract_named_binary(z, 'ffprobe.exe', Path(td) / 'ffprobe.exe')

    def test_archive_does_not_follow_traversal_paths(self):
        with tempfile.TemporaryDirectory() as td:
            z = Path(td) / 'one.zip'
            with zipfile.ZipFile(z, 'w') as f:
                f.writestr('../../foo/ffprobe.exe', b'bin')
            dest = Path(td) / 'output.exe'
            m.extract_named_binary(z, 'ffprobe.exe', dest)
            self.assertEqual(dest.read_bytes(), b'bin')
            self.assertFalse((Path(td) / 'foo').exists())

    def test_ffprobe_metadata_parsing(self):
        fake = type('R', (), {'returncode': 0, 'stdout': json.dumps({'format': {'duration': '2.5'},
                                                                     'streams': [{'codec_name': 'h264'}]}),
                              'stderr': ''})()
        with patch.object(m, 'ffprobe_executable', return_value='/bin/fakeprobe'), \
             patch.object(m.subprocess, 'run', return_value=fake) as run:
            result = m.read_metadata(Path('/tmp/source.mp4'))
            self.assertEqual(result['streams'][0]['codec_name'], 'h264')
            self.assertEqual(run.call_args.args[0][-1], '/tmp/source.mp4')

    def test_binary_not_found_refuses_probe(self):
        with patch.object(m, 'ffprobe_executable', return_value=None):
            with self.assertRaisesRegex(RuntimeError, 'FFprobe'):
                m.read_metadata(Path('/tmp/source.mp4'))

    def test_private_package_path_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)
            with patch.object(m, 'SCENE_DIR', p):
                m.register_private_packages();m.register_private_packages()
                self.assertEqual(m.sys.path.count(str(p)),1)
                m.sys.path.remove(str(p))


if __name__ == '__main__':
    unittest.main()
