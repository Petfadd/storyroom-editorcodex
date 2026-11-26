"""Case-neutral source/release regression for the audited in-place update."""
import unittest
from pathlib import Path

import captions
import documentary
import person_overlays as po
import proxy
import timebudget


class FutureProductionReadiness(unittest.TestCase):
    def test_one_hour_is_not_capped_at_thirty_minutes(self):
        # Three hundred seconds of narrator in several intervals with fifty
        # minutes of genuine interviews at valid narrator pause points.
        voice=600.0
        bites=[dict(id=f'b{i}',pause_s=i*60.0,asset_id='S02',asset_name='S02.mp4',
                    source_in_s=0,source_out_s=300.0)
               for i in range(10)]
        plan=documentary.build_timeline({'voiceover':{'duration':voice}}, {'bites':bites})
        self.assertEqual(plan['duration_s'],3600.0)
        self.assertEqual(plan['narration_duration_s'],600.0)
        self.assertEqual(sum(x['kind']=='sound_bite' for x in plan['segments']),10)
        self.assertEqual(plan['segments'][-1]['kind'],'narration')
        self.assertEqual(plan['segments'][-1]['timeline_out_s'],3600.0)

    def test_exact_back_to_back_soundbites_and_repeated_source_are_allowed(self):
        voice={'voiceover': {'duration': 60.0}}
        bites=[dict(id='A',pause_s=0,asset_id='S01',asset_name='S01.mp4',source_in_s=3,source_out_s=8),
               dict(id='B',pause_s=0,asset_id='S01',asset_name='S01.mp4',source_in_s=3,source_out_s=8)]
        out=documentary.build_timeline(voice,{'bites':bites})
        self.assertEqual([s['kind'] for s in out['segments'][:3]],['sound_bite','sound_bite','narration'])
        self.assertEqual(out['duration_s'],70.0)

    def test_no_short_proxy_timeout_on_long_media(self):
        self.assertEqual(proxy.timeout_for_duration(30),3600)
        self.assertGreater(proxy.timeout_for_duration(3600),3600)
        self.assertLessEqual(proxy.timeout_for_duration(36000),21600)

    def test_caption_fallback_uses_existing_font_without_shipping_binaries(self):
        self.assertTrue(captions.font_path('documentary').is_file())
        self.assertTrue(captions.font_family('documentary'))
        self.assertTrue(all((captions.FONT_DIR / f['url'].rsplit('/',1)[-1]).is_file()
                            for f in captions.catalogue()['fonts']))

    def test_full_source_resources_exist(self):
        root=Path(__file__).resolve().parents[1]
        for rel in ['tools/install_local_whisper.py','tools/install_local_yamnet.py',
                    'data/broll_catalog.json','RUN_STORYROOM_PREFLIGHT.cmd',
                    'tools/storyroom_release_preflight.py']:
            self.assertTrue((root/rel).is_file(),rel)


if __name__ == '__main__': unittest.main()

class NoCrossProjectEvidenceLeak(unittest.TestCase):
    def test_old_bundled_case_catalogue_is_never_used_by_a_new_project(self):
        import json, tempfile, visual_plan
        data=json.loads((Path(__file__).resolve().parents[1]/'data/broll_catalog.json').read_text())
        # Deliberately mimic ALL source names and lengths: the old heuristic would
        # treat this as evidence from another case. A filename is NOT an identity.
        assets=[dict(id=f'id{i}',kind='video',name=f'{k}.mp4',original_name=f'{k}.mp4',
                     duration=v['duration'],path=f'sources/{k}.mp4')
                for i,(k,v) in enumerate(data['sources'].items())]
        with tempfile.TemporaryDirectory() as tmp:
            shots,_=visual_plan.build_catalogue({'assets':assets,'people':[]},Path(tmp),None,None)
            self.assertEqual([x for x in shots if x.get('source')=='catalog'],[])
