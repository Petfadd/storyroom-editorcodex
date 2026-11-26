"""Story-aware camera/transition regressions without Flask or PyAV dependency."""
import json
import subprocess
import unittest
from pathlib import Path
import cinematic
import person_overlays
import transitions
from truecrime_camera import suggest_story_cameras

ROOT = Path(__file__).resolve().parents[1]


def scene(i, aid, fin, fout, sin, sout, narration='', soundbite=False):
    row={'source_file':aid+'.mp4','source_in_ms':sin,'source_out_ms':sout,
         'spoken_narration':narration, 'continuity':'sound-bite' if soundbite else 'narration'}
    if soundbite:row['bite_id']=f'b{i}'
    return {'id':f's{i}', 'asset_id':aid, 'frame_in':fin, 'frame_out':fout,
            'plan_row':row,'motion':'auto','transition':'cut'}


class MotionDirectorTests(unittest.TestCase):
    def test_catalogue_contains_renderable_cinematic_transitions(self):
        keys={r['key'] for r in transitions.documentary_catalogue()['transitions']}
        self.assertTrue({'cut','fadefast','fade','dissolve','hblur','zoomin'}<=keys)
        self.assertFalse({'pixelize','radial','squeezeh','circleclose'} & keys)
        # Old manual effects still render in existing projects; only the default menu is curated.
        self.assertIn('pixelize', transitions.LIBRARY)
        self.assertTrue(keys <= set(transitions.LIBRARY))
        self.assertEqual(set(transitions.LIBRARY),set(__import__('engine').XFADE_NAMES))

    def test_per_srt_motion_is_one_continuous_shot(self):
        # Three subtitle slots cover ONE continuous source shot: no visual cuts.
        xs=[scene(1,'source',0,75,0,2500,'The family drove to the park.'),
            scene(2,'source',75,150,2500,5000,'The search continued that night.'),
            scene(3,'source',150,225,5000,7500,'Investigators followed the road.')]
        p={'scenes':xs,'assets':[{'id':'source','kind':'video'}]}
        self.assertEqual(transitions.documentary_cuts(xs),[])
        cameras=suggest_story_cameras(p,'cinematic')
        self.assertEqual(set(cameras),{'s1','s2','s3'})
        for cam in cameras.values():
            self.assertEqual(cam['origin'],'auto')
            self.assertIn(cam['easing'], cinematic.EASINGS)
        for prev,nxt in zip(xs,xs[1:]):
            ca,cb=cameras[prev['id']],cameras[nxt['id']]
            self.assertLess(abs(ca['zoom_end']-cb['zoom_start']),.06)
            self.assertLess(abs(ca['x_end']-cb['x_start']),.002)
            self.assertLess(abs(ca['y_end']-cb['y_start']),.002)

    def test_preserve_manual_camera_and_protect_speaker(self):
        xs=[scene(1,'a',0,90,0,3000,'The road'),
            scene(2,'b',90,180,0,3000,'Witness interview',True),
            scene(3,'c',180,270,0,3000,'The road')]
        manual=cinematic.preset('push_left')
        xs[2]['camera']=dict(manual,origin='manual',locked=True)
        p={'scenes':xs,'assets':[{'id':i,'kind':'video'} for i in 'abc']}
        cameras=suggest_story_cameras(p,'dynamic')
        self.assertEqual(set(cameras),{'s1'})
        choices=transitions.documentary_auto_details(xs,'dynamic')
        # Around a speaker only clean, soft changes: never slide/wipe/zoom across a face.
        safe={'cut','fadefast','fade','dissolve','hblur','fadeblack','fadegrays','fadeslow'}
        self.assertTrue(all(v['key'] in safe for v in choices.values()),choices)

    def test_sensitive_picture_is_not_dramatized(self):
        p={'scenes':[scene(1,'a',0,150,0,5000,'Court document and screenshot of a text message')],
           'assets':[{'id':'a','kind':'video'}]}
        self.assertEqual(suggest_story_cameras(p,'dynamic'),{})

    def test_cinematic_cut_decisions_are_stable_and_restricted_to_real_cuts(self):
        xs=[scene(1,'a',0,120,0,4000,'Family gathered'),
            scene(2,'b',120,240,0,4000,'The next day at the home'),
            scene(3,'b',240,300,4000,6000,'The search continued'),
            scene(4,'c',300,420,0,4000,'However evidence was discovered')]
        out=transitions.documentary_auto_details(xs,'dynamic')
        self.assertEqual(set(out),{0,2})
        self.assertEqual(out,transitions.documentary_auto_details(xs,'dynamic'))
        # "The next day": a time change gets a smooth move; "However ... discovered": a reveal.
        self.assertIn(out[0]['key'],('smoothleft','smoothup','fade','slideleft'))
        self.assertEqual(out[0]['moment'],'small_jump')
        self.assertIn(out[2]['key'],('zoomin','whip','hblur','distance'))
        self.assertEqual(out[2]['moment'],'reveal')
        self.assertEqual(transitions.documentary_cuts(xs),[0,2])

    def test_person_photo_auto_is_stable_and_role_does_not_change_identity(self):
        import photo_motion
        person={'id':'person-1','name':'Sample Adult','role':'Relative','focus_y':.3}
        items=[{'text':'line','duration_ms':4000} for _ in range(6)]
        moves=photo_motion.plan_moves(items,'film')
        self.assertEqual(moves,photo_motion.plan_moves(items,'film'))      # stable
        for a,b in zip(moves,moves[1:]):                                   # never the same twice running
            self.assertNotEqual(a['entrance'],b['entrance'])
            self.assertNotEqual(a['camera_preset'],b['camera_preset'])
        window={'motion':moves[0]}
        cam=person_overlays.window_camera(window,person)
        self.assertEqual(cam,person_overlays.window_camera(window,dict(person,role='Suspect')))
        self.assertTrue(cinematic.is_active(cam))

    def test_python_javascript_match_for_compound_presets(self):
        js=r"""const c=require('./static/cinematic.js');
          let x={};for(const m of ['push_left','push_right','push_up','push_down','reveal_left','reveal_right','drift_up_right','drift_down_left'])
           x[m]=c.camPreset(m,'medium',[.5,.5],100);process.stdout.write(JSON.stringify(x));"""
        output=subprocess.check_output(['node','-e',js],cwd=ROOT,text=True)
        js_cameras=json.loads(output)
        for name,camera in js_cameras.items():
            with self.subTest(name=name):
                from_python=cinematic.preset(name,'medium')
                for key in ('zoom_start','zoom_end','x_start','x_end','y_start','y_end','easing'):
                    self.assertEqual(camera[key],from_python[key])

if __name__=='__main__':unittest.main()
