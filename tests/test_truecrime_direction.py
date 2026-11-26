"""Documentary editorial auto must be predictable, non-invasive and caption-safe."""
import unittest
from pathlib import Path
import transitions
from truecrime_camera import suggest_still_cameras

ROOT = Path(__file__).resolve().parents[1]


def scene(i, text, asset, t, kind='narration'):
    row = {'script_beat': str(i), 'visual_direction':text,'source_in_ms':0,
           'source_out_ms':5000, 'source_file':asset, 'continuity':kind}
    if kind == 'sound_bite': row['bite_id']=str(i)
    return {'id':f's{i}', 'asset_id':asset, 'frame_in':t, 'frame_out':t+150,
            'plan_row':row, 'transition':'cut', 'motion':'auto'}


class TrueCrimeDirection(unittest.TestCase):
    def test_same_story_same_transitions_no_random_shuffle(self):
        scenes=[scene(1,'Memorial church prayer','A',0),scene(2,'Later at church funeral tribute','B',150),
                scene(3,'Family remembrance','C',300),scene(4,'Police investigation briefing','D',450)]
        choices=[transitions.auto_documentary(scenes,'truecrime',seed=i) for i in range(5)]
        self.assertTrue(all(x==choices[0] for x in choices))
        self.assertTrue(set(k for v in choices[0].values() for k in v[0:1]) <= set(transitions.TRUE_CRIME_KEYS))

    def test_soundbite_boundaries_remain_hard_cuts(self):
        xs=[scene(1,'Police said investigation','a',0),scene(2,'Survivor interview','b',150,'sound_bite'),
            scene(3,'Family memorial prayer','c',300)]
        self.assertEqual([v['key'] for v in transitions.documentary_auto_details(xs).values()],['cut','cut'])

    def test_emotional_shift_justifies_only_one_soft_transition(self):
        xs=[scene(1,'Family remembers','a',0),scene(2,'Later at the church memorial','b',150),
            scene(3,'Flowers at the memorial','c',300)]
        d=transitions.documentary_auto_details(xs)
        self.assertIn(d[0]['key'],('fade','dissolve','fadefast'))
        self.assertIn('memorial',d[0]['reason'].lower())
        self.assertEqual(d[1]['key'],'cut')

    def test_does_not_add_whips_pixelization_or_zoom_transition(self):
        xs=[scene(i,'Family investigation testimony','source'+str(i),i*150) for i in range(6)]
        keys={x['key'] for x in transitions.documentary_auto_details(xs).values()}
        self.assertTrue(keys <= set(transitions.TRUE_CRIME_KEYS))
        self.assertFalse(keys & {'whip','pixelize','zoomin','fadewhite'})

    def test_still_camera_only_suitable_standalone_photo(self):
        xs=[scene(1,'Quiet portrait of adult relative','a',0),scene(2,'Police interview','b',150),
            scene(3,'Court document photo panel','c',300)]
        assets=[{'id':'a','kind':'image'},{'id':'b','kind':'video'},{'id':'c','kind':'image'}]
        d=suggest_still_cameras({'assets':assets,'scenes':xs})
        self.assertEqual(set(d), {'s1'})
        # Photos move, but stay restrained at the default "subtle" strength.
        self.assertLessEqual(max(d['s1']['zoom_start'],d['s1']['zoom_end']),112)
        self.assertEqual(d['s1']['origin'], 'auto')

    def test_still_camera_cannot_jump_between_subtitle_splits(self):
        xs=[scene(1,'Portrait','a',0),scene(2,'Portrait','a',150)]
        xs[1]['plan_row']['source_in_ms']=5000
        cams=suggest_still_cameras({'assets':[{'id':'a','kind':'image'}],'scenes':xs})
        # One photo held across a subtitle split is ONE move: the second part starts
        # exactly where the first ended, so the picture never jumps at the split.
        if cams:
            self.assertEqual(set(cams),{'s1','s2'})
            for key in ('zoom','x','y'):
                self.assertAlmostEqual(cams['s1'][key+'_end'],cams['s2'][key+'_start'],delta=0.6 if key=='zoom' else 0.01)

    def test_ui_separates_preview_and_burn_in(self):
        editor=(ROOT/'static/editor.js').read_text()
        render=(ROOT/'documentary_render_plan.py').read_text()
        self.assertIn('burnSrtOnExport=false',editor)
        self.assertIn('srt_subtitles:burnSrtOnExport',editor)
        self.assertIn('const captionOn=!!editorCC;', (ROOT/'static/documentary_timeline.js').read_text())
        self.assertNotIn('<section class="card"><h3>Audio</h3>',editor)
        self.assertIn('burn_captions = (project.get(\'burn_captions\') is True)',render)
        self.assertIn('Burn SRT subtitles permanently',editor)

    def test_ui_auto_is_not_random(self):
        js=(ROOT/'static/documentary_transitions.js').read_text()
        self.assertNotIn('Math.random',js)
        self.assertIn('suggested_reason',js)
        # Transitions never secretly change per-slot camera moves.
        self.assertIn('camera_auto:false',js)
        self.assertNotIn('a different transition per cut',js.lower())


if __name__=='__main__': unittest.main()
