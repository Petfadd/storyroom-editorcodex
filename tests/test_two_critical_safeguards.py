"""Regression tests for strict picture mapping and optimistic commit protection.

No Flask or PyAV required: these prove the fail-closed policy and that the
production code invokes it under the lock immediately before saving.
"""
import ast
from pathlib import Path
import unittest
import hashlib
import json
import tempfile

from documentary_rebuild_guards import assert_rebuild_is_current
from documentary_beat_plan import proposal


class ProjectCommitGuardTests(unittest.TestCase):
    def test_no_changes_allows_commit(self):
        assert_rebuild_is_current(12.5, 12.5, 4, 4, 'media-hash', 'media-hash')

    def test_manual_edit_during_build_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'newer edits are preserved'):
            assert_rebuild_is_current(12.5, 12.6, 4, 4, 'media-hash', 'media-hash')

    def test_soundbite_plan_edit_during_build_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'No timeline was saved'):
            assert_rebuild_is_current(12.5, 12.5, 4, 5, 'media-hash', 'media-hash')

    def test_replace_footage_without_project_save_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'source inputs changed'):
            assert_rebuild_is_current(12.5, 12.5, 4, 4, 'old-source', 'new-source')

    def test_all_three_checks_must_be_unchanged(self):
        for changed in [(6,5,'same'),(5,6,'same'),(5,5,'different')]:
            with self.assertRaises(ValueError):
                assert_rebuild_is_current(5,changed[0],5,changed[1],'same',changed[2])


class ActualInputFingerprintTests(unittest.TestCase):
    def test_real_source_change_and_photo_role_change_update_fingerprint(self):
        # Compile the unmodified app function alone so this test does not require
        # Flask/PyAV to import all of app.py on a lightweight build machine.
        text=(Path(__file__).resolve().parents[1]/'app.py').read_text()
        node=next(n for n in ast.parse(text).body
                  if isinstance(n,ast.FunctionDef) and n.name=='_auto_fingerprint')
        module=ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[]))
        scope={'hashlib':hashlib,'json':json}
        exec(compile(module,'app.py','exec'),scope)
        fingerprint=scope['_auto_fingerprint']
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'voice.wav').write_bytes(b'voice')
            (root/'S01.mp4').write_bytes(b'first video')
            project={'production_script':{'text':'video'},
                     'srt':{'blocks':[{'number':1,'start_ms':0,'end_ms':1000}]},
                     'voiceover':{'path':'voice.wav'},
                     'assets':[{'name':'S01.mp4','original_name':'S01.mp4',
                                'path':'S01.mp4','id':'src1','kind':'video'}],
                     'people':[]}
            beats=[{'source_file':'S01.mp4'}]
            initial=fingerprint(project,root,beats)
            (root/'S01.mp4').write_bytes(b'replacement video of new size')
            changed=fingerprint(project,root,beats)
            self.assertNotEqual(initial,changed)
            project['people']=[{'name':'Witness','role':'witness',
                               'photo':{'asset_id':'pic9'}}]
            self.assertNotEqual(changed,fingerprint(project,root,beats))


class BackendCallSiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root=Path(__file__).resolve().parents[1]
        cls.app=(root/'app.py').read_text(encoding='utf-8')
        cls.js=(root/'static'/'documentary.js').read_text(encoding='utf-8')
        mod=ast.parse(cls.app)
        cls.functions={n.name:ast.get_source_segment(cls.app,n)
                       for n in mod.body if isinstance(n,ast.FunctionDef)}

    def test_guard_is_under_lock_and_before_both_saves(self):
        body=self.functions['_documentary_beat_build_work']
        guard=body.index('assert_rebuild_is_current(')
        with_lock=body.rfind('with LOCKS[pid]:',0,guard)
        assert with_lock>=0
        assert guard<body.index('write(oldpath,plan)')<body.index('save(staged)')
        assert 'starting_inputs_fingerprint=_auto_fingerprint(p,root,beats)' in body
        assert '_auto_fingerprint(latest,root,beats)' in body
        assert "current['revision'],latest_plan['revision']" in body

    def test_stale_gap_payload_cannot_override_script(self):
        body=self.functions['_documentary_beat_build_work']
        assert 'uncovered, gap_issues=narration_gaps(p,beats)' in body
        assert "raise ValueError(' '.join(gap_issues))" in body
        assert body.index('uncovered, gap_issues=narration_gaps') < body.index('staged,plan=prepare(')
        assert 'Unscripted gap footage is not allowed' in body

    def test_automatic_build_never_approves_unassigned_gaps(self):
        auto=self.functions['_auto_build']
        assert "'approved_gaps':[]" in auto
        assert '500]' not in auto
        assert 'approved_gaps:[]' in self.js
        assert 'UNASSIGNED' in self.js


if __name__ == '__main__':
    unittest.main()
