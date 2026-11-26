"""The music strip shows a gap under every sound bite, because the bed is silent there."""
import json
import subprocess
import unittest
from pathlib import Path


def strip_function():
    source = Path('static/documentary_timeline.js').read_text()
    start = source.index('function docMusicCuts(duration)')
    end = source.index('window.docMusicSpans=docMusicSpans;')
    return source[start:end]


def run(segments, duration, music, script):
    harness = f"""
const assert=require('assert');
global.window={{docTimelineData:{{segments:{json.dumps(segments)}}}}};
let docMusic={json.dumps(music)};
{strip_function()}
{script}
"""
    return subprocess.run(['node', '-e', harness], capture_output=True, text=True)


class MusicTrackShowsTheCutTest(unittest.TestCase):
    def test_the_strip_has_a_gap_at_every_bite(self):
        segments = [
            {'kind': 'narration', 'timeline_in_s': 0.0, 'timeline_out_s': 19.366},
            {'kind': 'sound_bite', 'timeline_in_s': 19.366, 'timeline_out_s': 36.866},
            {'kind': 'narration', 'timeline_in_s': 36.866, 'timeline_out_s': 53.400},
            {'kind': 'sound_bite', 'timeline_in_s': 53.400, 'timeline_out_s': 95.900},
        ]
        script = """
const spans=docMusicSpans(95.9);
assert.deepStrictEqual(spans.map(s=>[+s.start.toFixed(3),+s.end.toFixed(3)]),[[0,19.366],[36.866,53.4]]);
assert.strictEqual(docMusicCuts(95.9).length,2);
console.log('ok');
"""
        result = run(segments, 95.9, {}, script)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_no_bites_is_one_bar(self):
        segments = [{'kind': 'narration', 'timeline_in_s': 0.0, 'timeline_out_s': 12.0}]
        script = """
const spans=docMusicSpans(12);
assert.deepStrictEqual(spans,[{start:0,end:12}]);
console.log('ok');
"""
        result = run(segments, 12.0, {}, script)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_the_live_preview_follows_the_same_rule(self):
        source = Path('static/documentary_timeline.js').read_text()
        start = source.index('function docMusicShapeAt(')
        harness = f"""
const assert=require('assert');
const DOC_MUSIC_DUCK=Math.pow(10,-11/20),DOC_MUSIC_FADE_OUT=.35,DOC_MUSIC_FADE_IN=.6;
global.window={{docTimelineData:{{segments:[
 {{kind:'narration',timeline_in_s:0,timeline_out_s:5}},
 {{kind:'sound_bite',timeline_in_s:5,timeline_out_s:9}},
 {{kind:'narration',timeline_in_s:9,timeline_out_s:12}}]}}}};
{source[start:source.index('function docSyncMusic(')]}
assert.strictEqual(docMusicShapeAt(7),0,'silent under the bite');
assert.ok(Math.abs(docMusicShapeAt(2)-DOC_MUSIC_DUCK)<1e-9,'ducked under narration');
assert.ok(docMusicShapeAt(4.9)<DOC_MUSIC_DUCK,'fading out before the bite');
assert.ok(Math.abs(docMusicShapeAt(11)-DOC_MUSIC_DUCK)<1e-9,'back after the bite');
console.log('ok');
"""
        result = subprocess.run(['node', '-e', harness], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
