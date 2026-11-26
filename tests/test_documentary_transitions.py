"""Transitions on Beat-built documentaries: where they go and that they never move a cut."""
import json
import shutil
import subprocess
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

import transitions as tr


def scene(sid, asset, src_in, src_out, f_in, f_out, beat='5', bite=False):
    row = {'source_in_ms': src_in, 'source_out_ms': src_out, 'script_beat': beat,
           'continuity': 'Documentary beat sound-bite' if bite else f'Documentary beat {beat}'}
    if bite:
        row['bite_id'] = 'b' + sid
    return {'id': sid, 'asset_id': asset, 'frame_in': f_in, 'frame_out': f_out, 'transition': 'cut', 'plan_row': row}


def timeline():
    return [scene('a', 'A', 0, 2000, 0, 60, '5'),
            scene('b', 'A', 2000, 4000, 60, 120, '5'),          # same footage, split at a subtitle
            scene('c', 'B', 9000, 12000, 120, 210, '6'),        # new file: a real cut
            scene('d', 'C', 0, 5000, 210, 360, '7', bite=True),  # into a sound bite
            scene('e', 'B', 20000, 23000, 360, 450, '8')]


class CutActionTest(unittest.TestCase):
    def test_script_words(self):
        self.assertIsNone(tr.from_cut_action('CUT TO PICTURE'))
        self.assertIsNone(tr.from_cut_action('HARD CUT TO SPEAKER'))
        self.assertIsNone(tr.from_cut_action('FADE IN FROM BLACK'))
        self.assertEqual(tr.from_cut_action('DIP TO BLACK'), 'fadeblack')
        self.assertEqual(tr.from_cut_action('Cross Fade'), 'fade')
        self.assertEqual(tr.from_cut_action('SLOW FADE'), 'fadeslow')
        self.assertEqual(tr.from_cut_action('Zoom Through'), 'zoomin')
        self.assertEqual(tr.from_cut_action('AUTO'), 'auto')


class RealCutTest(unittest.TestCase):
    def test_only_picture_changes_are_cuts(self):
        self.assertEqual(tr.documentary_cuts(timeline()), [1, 2, 3])

    def test_auto_gives_neighbouring_cuts_different_transitions(self):
        chosen = tr.auto_documentary(timeline(), 'expressive')
        keys = [chosen[c][0] for c in sorted(chosen)]
        self.assertEqual(len(keys), 3)
        self.assertTrue(all(a != b for a, b in zip(keys, keys[1:])))

    def test_cuts_into_or_out_of_a_speaker_stay_soft(self):
        chosen = tr.auto_documentary(timeline(), 'expressive')
        self.assertIn(chosen[2][0], tr.SPEAKER_SAFE)   # into the bite
        self.assertIn(chosen[3][0], tr.SPEAKER_SAFE)   # out of the bite

    def test_a_tiny_shot_gets_a_hard_cut(self):
        self.assertEqual(tr.fit_frames('fade', 15, 100, 4), ('cut', 0))
        key, frames = tr.fit_frames('fade', 30, 100, 20)
        self.assertEqual(key, 'fade'); self.assertLess(frames, 20)

    def test_script_cut_action_goes_on_the_cut_before_its_beat(self):
        from documentary_storyboard import _script_transitions
        scenes = timeline()
        _script_transitions(scenes, [{'label': '6', 'cut_action': 'DIP TO BLACK'},
                                     {'label': '8', 'cut_action': 'CUT TO PICTURE'}])
        self.assertEqual(scenes[1]['transition'], 'fadeblack')    # into Beat 6
        self.assertEqual(scenes[3]['transition'], 'cut')          # into Beat 8 stays a cut
        self.assertEqual(scenes[0]['transition'], 'cut')          # not a real cut


FF = shutil.which('ffmpeg')


@unittest.skipUnless(FF, 'ffmpeg needed')
class RenderLengthTest(unittest.TestCase):
    """Blends replace frames inside the incoming shot, so the film keeps its length."""

    def test_transitions_keep_every_frame_count(self):
        import sys, types
        sys.modules.setdefault('av', types.ModuleType('av'))
        import documentary_final_renderer as r
        work = Path(tempfile.mkdtemp())
        try:
            def info(path):
                o = json.loads(subprocess.run(['ffprobe', '-v', 'error', '-count_frames', '-select_streams', 'v:0',
                                               '-show_entries', 'stream=nb_read_frames,r_frame_rate', '-of', 'json',
                                               str(path)], capture_output=True, text=True).stdout)['streams'][0]
                return int(o['nb_read_frames']), Fraction(o['r_frame_rate'])
            saved = r._video_info; r._video_info = info
            a, b = work / 'A.mp4', work / 'B.mp4'
            subprocess.run([FF, '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=30', '-t', '8',
                            '-c:v', 'libx264', '-preset', 'ultrafast', str(a)], check=True)
            subprocess.run([FF, '-v', 'error', '-y', '-f', 'lavfi', '-i', 'smptebars=size=320x180:rate=30', '-t', '8',
                            '-c:v', 'libx264', '-preset', 'ultrafast', str(b)], check=True)
            spans = [{'labels': ['1'], 'scene_ids': ['s1'], 'source_start_frame': 0, 'source_end_frame': 60,
                      'source_frame_count': 60, 'frame_conversion': 'none', 'picture_scale': 100},
                     {'labels': ['2'], 'scene_ids': ['s2'], 'source_start_frame': 30, 'source_end_frame': 90,
                      'source_frame_count': 60, 'frame_conversion': 'none', 'picture_scale': 110}]
            project = {'scenes': [{'id': 's1', 'transition': 'fadeblack', 'transition_handle_frames': 20}, {'id': 's2'}]}
            incoming = r._boundary_transitions(project, spans)
            self.assertEqual(incoming, {1: ('fadeblack', 20)})
            fps = Fraction(30); x264 = ['-c:v', 'libx264', '-preset', 'ultrafast', '-bf', '0', '-video_track_timescale', '30']
            blend = work / 'blend.mp4'
            r._make_blend(FF, spans[0], a, spans[1], b, 'fadeblack', 20, 320, 180, fps, '30/1', False, x264, blend)
            body = work / 'body.mp4'
            r._run([FF, '-v', 'error', '-y', '-i', str(b), '-an', '-vf', r._span_filters(spans[1], 20, 40, 320, 180, fps, '30/1', False),
                    '-fps_mode', 'passthrough', *x264, '-frames:v', '40', str(body)])
            self.assertEqual(info(blend)[0] + info(body)[0], 60)
            r._video_info = saved
        finally:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
