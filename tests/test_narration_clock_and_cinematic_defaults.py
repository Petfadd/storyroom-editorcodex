"""Regression tests for mixed-clock documentaries and real cinematic treatment."""
import copy
import unittest

import cinematic
import documentary_beats
import transitions
from truecrime_camera import suggest_story_cameras, suggest_still_cameras


def narr(label, a, b, master):
    return dict(label=label, number=int(label), kind='narration', narration_in_ms=a,
                narration_out_ms=b, master_in_ms=master, master_out_ms=master+b-a,
                source_in_ms=0, source_out_ms=b-a, source_file='S01.mp4')


def bite(label, pause, master, duration=2000):
    return dict(label=label, number=int(label), kind='sound_bite', pause_ms=pause,
                master_in_ms=master, master_out_ms=master+duration,
                source_in_ms=0, source_out_ms=duration, duration_ms=duration,
                source_file='S02.mp4')


class FourClocks(unittest.TestCase):
    def test_proven_master_pause_reconciled_without_moving_picture(self):
        beats=[narr('001',0,5000,0),bite('002',5000,5000,4000),
               narr('003',5000,10000,9000),bite('004',14000,14000,3000),
               narr('005',10000,15000,17000)]
        original=copy.deepcopy(beats)
        out,notes=documentary_beats.reconcile_pause_clocks(beats)
        self.assertEqual(out[3]['pause_ms'],10000)
        self.assertEqual(out[3]['pause_declared_ms'],14000)
        self.assertEqual(out[3]['master_in_ms'],original[3]['master_in_ms'])
        self.assertEqual(out[3]['source_out_ms'],original[3]['source_out_ms'])
        self.assertEqual(out[4]['narration_in_ms'],10000)
        self.assertEqual(len(notes),1)
        self.assertIn('Beat 004',notes[0])
        # Repeated processing must never normalize twice.
        self.assertEqual(documentary_beats.reconcile_pause_clocks(out)[1],[])

    def test_leading_and_back_to_back_bites_use_narrator_clock(self):
        beats=[bite('001',0,0,3000),bite('002',3000,3000,4000),
               narr('003',0,5000,7000),bite('004',12000,12000,6000)]
        out,notes=documentary_beats.reconcile_pause_clocks(beats)
        self.assertEqual([out[i]['pause_ms'] for i in (0,1,3)],[0,0,5000])
        self.assertEqual(len(notes),2)

    def test_half_hour_film_with_ten_minute_narrator_clock(self):
        """Regression for the user's 29.598 min film / 10.364 min voiceover."""
        from documentary import build_timeline
        # 621.840s narrator; 1154.040s of authentic sources = 1775.880s film.
        beats=[narr('001',0,200000,0),
               bite('002',200000,200000,300000),
               narr('003',200000,410000,500000),
               bite('004',710000,710000,400000),
               bite('005',1110000,1110000,154040),
               narr('006',410000,621840,1264040),
               bite('007',1475880,1475880,300000)]
        # Last bite is at the end and must not count as narrator audio.
        corrected, notes = documentary_beats.reconcile_pause_clocks(beats)
        self.assertEqual([corrected[i]['pause_ms'] for i in (1,3,4,6)],
                         [200000,410000,410000,621840])
        self.assertEqual(len(notes),3)
        for b in corrected:
            if b['kind']=='sound_bite':
                b.update(id=b['label'],asset_id=b['source_file'],asset_name=b['source_file'],
                         pause_s=b['pause_ms']/1000,source_in_s=b['source_in_ms']/1000,
                         source_out_s=b['source_out_ms']/1000)
        project={'voiceover':{'duration':621.840}}
        total=build_timeline(project,{'bites':[b for b in corrected if b['kind']=='sound_bite']})
        self.assertEqual(total['narration_duration_s'],621.840)
        self.assertAlmostEqual(total['duration_s'],1775.880,places=3)
        self.assertEqual(total['segments'][-1]['kind'],'sound_bite')

    def test_unproven_wrong_pause_remains_wrong(self):
        beats=[narr('001',0,5000,0),bite('002',8500,5000,2000)]
        out,notes=documentary_beats.reconcile_pause_clocks(beats)
        self.assertEqual(out[1]['pause_ms'],8500)
        self.assertFalse(notes)


class CinematicDefaults(unittest.TestCase):
    def photo_shots(self):
        scenes=[]
        for index in range(3):
            scenes.append(dict(id=f's{index}',asset_id='photo',frame_in=index*90,
                               frame_out=(index+1)*90,plan_row={'source_in_ms':index*3000,
                               'source_out_ms':(index+1)*3000,'spoken_narration':'A verified family photograph'},
                               motion='auto'))
        return {'scenes':scenes,'assets':[{'id':'photo','kind':'image'}]}

    def test_still_photo_motion_spans_multiple_srt_slots(self):
        project=self.photo_shots()
        planned=suggest_still_cameras(project)
        self.assertEqual(len(planned),3)
        self.assertTrue(any(cinematic.is_moving(v) for v in planned.values()))
        # No zoom resets on a cue split. Adjacent zoom endpoints may differ by
        # only one input-frame step of the continuous, shot-wide curve.
        for a,b in zip(project['scenes'],project['scenes'][1:]):
            v0,v1=planned[a['id']],planned[b['id']]
            self.assertLess(abs(v0['zoom_end']-v1['zoom_start']),0.5)

    def test_photo_carrier_video_receives_the_same_motion(self):
        project=self.photo_shots()
        project['assets']=[{'id':'photo','kind':'video','original_name':'P01_Nola_video.mp4'}]
        planned=suggest_still_cameras(project)
        self.assertEqual(len(planned),3)
        self.assertTrue(any(cinematic.is_moving(v) for v in planned.values()))

    def test_motion_panel_direction_and_energy_control_main_stills(self):
        project=self.photo_shots()
        project['person_overlay_settings']={'photo_motion':'push_left','photo_motion_intensity':'strong'}
        planned=suggest_still_cameras(project)
        self.assertEqual({camera.get('preset') for camera in planned.values()},{'push_left'})
        self.assertTrue(all('Strong move settles in 1.60s' in camera.get('reason','') for camera in planned.values()))

    def test_automatic_motion_settles_instead_of_dragging_through_long_shot(self):
        project=self.photo_shots()
        project['scenes']=[dict(id='long',asset_id='photo',frame_in=0,frame_out=30*12,
                                plan_row={'source_in_ms':0,'source_out_ms':12000,
                                          'spoken_narration':'A verified family photograph'},motion='auto')]
        project['person_overlay_settings']={'photo_motion':'zoom_in','photo_motion_intensity':'medium'}
        camera=suggest_still_cameras(project)['long']
        self.assertIn('settles in 2.27s',camera['reason'])
        # The slot stores the exact local finish point. Rendering reaches the
        # final composition early and holds it; it is not a 12-second crawl.
        self.assertLess(camera['motion_end'],.2)
        self.assertGreater(camera['zoom_end'],camera['zoom_start'])

    def test_verified_native_static_interval_inside_video_receives_motion(self):
        project=self.photo_shots()
        project['assets']=[{'id':'photo','kind':'video','original_name':'S02.mp4'}]
        for scene in project['scenes']:
            scene['plan_row']['native_static_interval']=True
        planned=suggest_still_cameras(project)
        self.assertEqual(len(planned),3)
        self.assertTrue(any(cinematic.is_moving(v) for v in planned.values()))

    def test_ordinary_moving_video_is_not_treated_as_a_still(self):
        project=self.photo_shots()
        project['assets']=[{'id':'photo','kind':'video','original_name':'S02.mp4'}]
        self.assertEqual(suggest_still_cameras(project),{})

    def test_documentary_renderer_accepts_only_smart_still_motion(self):
        from documentary_frame_audit import _camera
        smart=cinematic.preset('zoom_in','subtle')
        smart.update(origin='auto',reason='Smart still: Photo move: slow push.')
        self.assertTrue(cinematic.is_moving(_camera({'camera':smart})))
        manual=cinematic.preset('zoom_in','subtle')
        manual.update(origin='manual',reason='Legacy Shot Inspector move')
        self.assertIsNone(_camera({'camera':manual}))

    def test_editor_motion_plan_uses_saved_still_camera(self):
        from app import motion
        camera=cinematic.preset('pan_right','subtle')
        camera.update(origin='auto',reason='Smart still: Photo move: pan.')
        planned=motion({'id':'still','frame_in':0,'frame_out':150,'camera':camera,
                        'emotion':'calm','purpose':'identify','focus':'Nola'},0)
        self.assertEqual(planned['mode'],'photo_camera')
        self.assertNotEqual(planned['x_start'],planned['x_end'])

    def test_dialogue_and_protected_documents_get_no_auto_motion(self):
        p=self.photo_shots()
        p['scenes'][1]['plan_row']['bite_id']='bite-1'
        self.assertNotIn('s1',suggest_story_cameras(p,'cinematic'))
        p=self.photo_shots()
        p['scenes'][0]['plan_row']['spoken_narration']='Read this court document'
        self.assertNotIn('s0',suggest_story_cameras(p,'dynamic'))

    def test_real_cuts_get_restrained_blends_but_not_every_cue(self):
        scenes=[]
        for index in range(7):
            scenes.append(dict(id=f's{index}',asset_id=f'video-{index}',
                               frame_in=index*180,frame_out=(index+1)*180,
                               plan_row={'source_file':f'S{index}.mp4',
                               'source_in_ms':0,'source_out_ms':6000,
                               'spoken_narration':'A camera captured the crowd as it gathered.'}))
        details=transitions.documentary_auto_details(scenes,'cinematic')
        self.assertTrue(any(row['key']!='cut' for row in details.values()),details)
        self.assertTrue(any(row['key']=='cut' for row in details.values()),details)
        scenes[1]['plan_row']['bite_id']='soundbite'
        details=transitions.documentary_auto_details(scenes,'cinematic')
        # Into and out of a person speaking: only clean, soft changes -- never a slide,
        # wipe or zoom across a face -- and short enough not to cover first words.
        safe={'cut','fadefast','fade','dissolve','hblur','fadeblack','fadegrays','fadeslow'}
        for cut in (0,1):
            self.assertIn(details[cut]['key'],safe,details[cut])
            self.assertLessEqual(details[cut]['frames'],18,details[cut])

if __name__=='__main__':
    unittest.main()
