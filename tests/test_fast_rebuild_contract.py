"""Regression checks for replacing an existing Beat timeline after new uploads.

These checks run without media codecs or Flask. Integration/export tests still
require the application dependencies and actual video files on Windows.
"""
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import ast
import sys

import strict_cuts


class _FakeContainer:
    def __init__(self, observed):
        self.observed = observed
        self.seeks = []
        self.streams = SimpleNamespace(video=[SimpleNamespace(
            base_rate=Fraction(30), average_rate=Fraction(30),
            time_base=Fraction(1, 90000))])

    def __enter__(self): return self
    def __exit__(self, *args): return False
    def seek(self, point, stream=None, backward=True):
        self.seeks.append((point, backward))

    def decode(self, stream):
        for msec in self.observed:
            yield SimpleNamespace(pts=int(msec * 90),time_base=Fraction(1,90000))


def test_fast_endpoint_seek_and_cache(tmp_path):
    clip=tmp_path/'S01.mp4';clip.write_bytes(b'pretend video for mocked decoder')
    fake=_FakeContainer([4800, 4933, 4970])
    opens=[]
    def open_fake(path):
        opens.append(str(path));return fake
    strict_cuts._ENDPOINTS.clear()
    with patch.dict(sys.modules, {'av':SimpleNamespace(open=open_fake)}),patch.object(strict_cuts,'inspect_video',side_effect=AssertionError('full scan must not happen')):
        result=strict_cuts.verify_source_endpoint(clip, 5000, source_name='S01.mp4')
        again=strict_cuts.verify_source_endpoint(clip, 5000, source_name='S01.mp4')
    assert opens==[str(clip)]
    assert result==again
    assert fake.seeks, 'must seek near the required source interval'
    assert result['out_ms']==5000


def test_fast_endpoint_rechecks_changed_source(tmp_path):
    clip=tmp_path/'S02.mp4';clip.write_bytes(b'old')
    opens=[]
    def open_fake(path):
        opens.append(str(path));return _FakeContainer([4970])
    strict_cuts._ENDPOINTS.clear()
    with patch.dict(sys.modules, {'av':SimpleNamespace(open=open_fake)}):
        strict_cuts.verify_source_endpoint(clip, 5000)
        clip.write_bytes(b'new-bigger-video-contents')
        strict_cuts.verify_source_endpoint(clip, 5000)
    assert len(opens)==2, 'replaced footage must not reuse an old file check'


def test_missing_media_does_not_get_silently_replaced(tmp_path):
    clip=tmp_path/'missing.mp4'
    try:strict_cuts.verify_source_endpoint(clip, 5000)
    except FileNotFoundError:pass
    else:raise AssertionError('missing footage must remain a blocking error')


def test_builder_uses_fast_source_checks_and_refreshes_plan_revision():
    file=Path(__file__).resolve().parents[1]/'app.py'
    module=ast.parse(file.read_text(encoding='utf8'))
    funcs={f.name:ast.get_source_segment(file.read_text(encoding='utf8'),f)
           for f in module.body if isinstance(f,ast.FunctionDef)}
    build=funcs['_documentary_beat_build_work']
    assert 'verify_source_endpoint(path,last_ms' in build
    assert 'inspect_video(path,required' not in build
    assert "plan['revision']=int(current.get('revision') or 0)+1" in build
    assert "staged['timeline_needs_rebuild']=False" in build
    auto=funcs['_auto_fingerprint']
    assert "a.get('kind')=='image'" in auto
    assert "p.get('people',[])" in auto


def test_real_rebuild_button_routes_to_beat_builder():
    static=Path(__file__).resolve().parents[1]/'static'
    setup=(static/'studio.js').read_text(encoding='utf8')
    monitor=(static/'documentary_timeline.js').read_text(encoding='utf8')
    documentary=(static/'documentary.js').read_text(encoding='utf8')
    assert 'Rebuild timeline from latest script' in setup
    assert "if(P?.edit_mode==='documentary'&&P?.production_script" in setup
    assert 'return openBeatProposal()' in monitor
    assert 'Rebuild timeline from latest script' in monitor
    assert 'P=await api(`/api/projects/${pid}`)' in documentary
    assert 'resetDocTimeline()' in documentary
