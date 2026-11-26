import copy
import json
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

from documentary_beats import is_strict_pipeline_script, read_beats
from documentary_storyboard import prepare
from documentary_strict import make_review, review_blockers, review_state, validate


def tc(milliseconds):
    seconds, ms = divmod(milliseconds, 1000)
    minutes, sec = divmod(seconds, 60)
    hours, minute = divmod(minutes, 60)
    return f'{hours:02d}:{minute:02d}:{sec:02d},{ms:03d}'


def narration_beat(number, filename, n_in, n_out, m_in=None, m_out=None,
                   s_in=0, direction='Exterior street, no people.',
                   continuity='Keep the same location orientation.'):
    m_in = n_in if m_in is None else m_in
    m_out = m_in + n_out - n_in if m_out is None else m_out
    state = 'PLAYING' if n_in == 0 else 'RESUMING'
    clock = f'{tc(n_in)} --> {tc(n_out)}' if n_in == 0 else f'RESUMES at {tc(n_in)} --> {tc(n_out)}'
    return f'''Beat: {number:03d}
Type: VOICE OVER
Master timeline: {tc(m_in)} --> {tc(m_out)}
Narration Clock: {clock}
Narration State: {state}
Full source: {filename}
Source IN: {tc(s_in)}
Source OUT: {tc(s_in + n_out - n_in)}
Footage Audio: MUTED (0%)
Visual Direction: VIS-{number:03d} | {direction}
Continuity note: {continuity}
On-screen Caption: Location, 2025'''.replace(
        f'Continuity note: {continuity}',
        f'Continuity note: VIS-{number:03d} | {continuity}')


def bite_beat(number, filename, pause, m_in, duration, s_in, speaker, anchor='ANCHOR-A'):
    return f'''Beat: {number:03d}
Type: DOCUMENTARY SOUND BITE
Master timeline: {tc(m_in)} --> {tc(m_in + duration)} (Duration: {duration / 1000:g} sec)
Narration Clock: PAUSED at {tc(pause)}
Narration State: PAUSED (Suspended at {tc(pause)})
Full source: {filename}
Source IN: {tc(s_in)}
Source OUT: {tc(s_in + duration)}
Footage Audio: UNMUTED (100% Dialogue Level, Clean)
Speaker: {speaker}
Exact Spoken Dialogue: Exact quote from {speaker}.
Continuity note: Anchor ID: {anchor}; preserve speaker turn order.
Visual Direction: VIS-{number:03d} interview close-up.
On-screen Caption: {speaker}'''


def fixture(root, script=None):
    (root / 'sources').mkdir(exist_ok=True)
    assets = []
    for number in range(1, 5):
        name = f'S{number:02d}.mp4'
        path = root / 'sources' / f'source-{number}.mp4'
        path.write_bytes(f'video-{number}'.encode())
        assets.append({'id': f'a{number}', 'name': name, 'original_name': name,
                       'kind': 'video', 'path': path.relative_to(root).as_posix(),
                       'duration': 30.0, 'revision': f'r{number}', 'verified': True,
                       'source': 'Synthetic test footage',
                       'provenance': {'kind': 'original_upload'}})
    beats = [narration_beat(1, 'S01.mp4', 0, 2000, s_in=1000),
             narration_beat(2, 'S02.mp4', 2000, 4000, s_in=5000,
                            direction='bridge from a wide angle.',
                            continuity='Match travel direction.')]
    text = script if script is not None else '\n\n'.join(beats)
    project = {'id': 'fixture', 'edit_mode': 'documentary', 'profile': 'documentary',
               'scenes': [], 'production_script': {'name': 'Pipeline v5', 'text': text},
               'voiceover': {'name': 'narration.wav', 'path': 'inputs/narration.wav', 'duration': 4.0},
               'srt': {'blocks': [{'number': 1, 'start_ms': 0, 'end_ms': 2000, 'text': 'First line.'},
                                  {'number': 2, 'start_ms': 2000, 'end_ms': 4000, 'text': 'Second line.'}]},
               'assets': assets}
    (root / 'inputs').mkdir(exist_ok=True)
    (root / 'inputs' / 'narration.wav').write_bytes(b'audio')
    return project


# The separate "strict Pipeline v5" execution mode was retired: every production script
# now runs through the one Beat workflow (documentary_beats.is_strict_pipeline_script
# always returns False). These tests describe that retired mode.
RETIRED = unittest.skip('strict Pipeline v5 execution mode is retired; all scripts use the Beat workflow')


class StrictProductionExecutionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project = fixture(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def check(self, project=None):
        p = project or self.project
        beats = read_beats(p['production_script']['text'])
        return validate(p, self.root, beats, {a['id']: 30_000 for a in p['assets']})

    @RETIRED
    def test_exact_filename_range_visual_metadata_persist_through_storyboard(self):
        beats = read_beats(self.project['production_script']['text'])
        self.assertEqual((beats[0]['source_file'], beats[0]['source_in_ms'], beats[0]['source_out_ms']),
                         ('S01.mp4', 1000, 3000))
        self.assertEqual(beats[0]['visual_id'], 'VIS-001')
        with patch('documentary_storyboard.source_rate', return_value='30'):
            staged, sound_plan = prepare(self.project, self.root, [], [], False,
                                         lambda _: True, beats=beats, strict=True)
        record = staged['documentary_beat_review']
        self.assertEqual(record['execution_mode'], 'pipeline_v5_strict')
        self.assertEqual([(b['source_file'], b['source_in_ms'], b['source_out_ms'])
                          for b in record['scripted_beats']], [('S01.mp4', 1000, 3000), ('S02.mp4', 5000, 7000)])
        self.assertEqual([(s['plan_row']['source_file'], s['plan_row']['source_in_ms'], s['plan_row']['source_out_ms'])
                          for s in staged['scenes']], [('S01.mp4', 1000, 3000), ('S02.mp4', 5000, 7000)])
        self.assertEqual(staged['scenes'][0]['plan_row']['visual_id'], 'VIS-001')
        self.assertEqual(staged['scenes'][1]['plan_row']['continuity_note'],
                         'VIS-002 | Match travel direction.')
        self.assertEqual(sound_plan['bites'], [])
        persisted = self.root / 'project.json'
        persisted.write_text(json.dumps(staged), encoding='utf-8')
        reloaded = json.loads(persisted.read_text(encoding='utf-8'))
        self.assertEqual(reloaded['documentary_beat_review']['scripted_beats'][0]['source_in_ms'], 1000)
        self.assertEqual(reloaded['scenes'][0]['plan_row']['source_out_ms'], 3000)

        from documentary_render_plan import plan as render_plan
        events = []
        for scene in staged['scenes']:
            row = scene['plan_row']
            events.append({'label': row['script_beat'], 'kind': 'narration',
                           'asset_id': scene['asset_id'], 'source': row['source_file'],
                           'source_start_frame': round(row['source_in_ms'] * .03),
                           'source_end_frame': round(row['source_out_ms'] * .03),
                           'source_fps': '30', 'output_fps': '30',
                           'timeline_in_ms': row['timeline_in_ms'], 'timeline_out_ms': row['timeline_out_ms'],
                           'caption': row['required_caption'], 'picture_scale': 100})
        with patch('documentary_render_plan.playback_schedule', return_value=events):
            planned = render_plan(staged, self.root, sound_plan)
        self.assertTrue(planned['picture_compatible'], planned['errors'])
        self.assertEqual([(s['source'], s['source_start_frame'], s['source_end_frame'])
                          for s in planned['spans']], [('S01.mp4', 30, 90), ('S02.mp4', 150, 210)])

    @RETIRED
    def test_pipeline_detection_keeps_older_full_source_vo_clock_scripts_legacy(self):
        legacy = '''Beat: 001
Type: VOICE OVER
VO Clock: 00:00:00,000 --> 00:00:02,000
Narration State: PLAYING
Full source: S01.mp4
Source IN: 00:00:00,000
Source OUT: 00:00:02,000
Footage Audio: MUTED (0%)
On-screen Caption: None'''
        self.assertFalse(is_strict_pipeline_script(legacy))
        self.assertTrue(is_strict_pipeline_script(self.project['production_script']['text']))
        incomplete_v5 = self.project['production_script']['text'].replace(
            'Master timeline: 00:00:00,000 --> 00:00:02,000\n', '', 1)
        self.assertTrue(is_strict_pipeline_script(incomplete_v5))

    @RETIRED
    def test_v5_visual_ids_live_in_direction_and_continuity_not_a_new_field(self):
        text = self.project['production_script']['text']
        self.assertNotIn('\nVisual ID:', text)
        self.assertEqual(read_beats(text)[0]['visual_id'], 'VIS-001')
        with self.assertRaisesRegex(ValueError, 'standalone Visual ID field'):
            read_beats(text.replace('Visual Direction:', 'Visual ID: VIS-001\nVisual Direction:', 1))
        with self.assertRaisesRegex(ValueError, 'standalone Visual ID field'):
            read_beats(text.replace('Visual Direction:', 'Visual ID:\nVisual Direction:', 1))
        with self.assertRaisesRegex(ValueError, 'must match'):
            read_beats(text.replace('Continuity note: VIS-001', 'Continuity note: VIS-999', 1))
        with self.assertRaisesRegex(ValueError, 'both Visual Direction and Continuity Note'):
            read_beats(text.replace('Continuity note: VIS-001 |', 'Continuity note: Keep this shot consistent;'))

    @RETIRED
    def test_imported_broll_is_allowed_as_exact_vo_picture_and_keeps_local_range(self):
        p = copy.deepcopy(self.project)
        script = p['production_script']['text'].replace('Full source: S01.mp4', 'Full source: B01.mp4', 1)
        p['production_script']['text'] = script
        broll_path = self.root / 'sources' / 'broll-local.mp4'
        broll_path.write_bytes(b'local-broll')
        p['assets'].append({'id': 'broll-1', 'name': 'B01.mp4', 'original_name': 'B01.mp4',
                            'kind': 'video', 'path': broll_path.relative_to(self.root).as_posix(),
                            'duration': 15.0, 'revision': 'broll-r1', 'category': 'broll',
                            'derived_from': {'asset_id': 'youtube-original'},
                            'provenance': {'kind': 'youtube', 'media': 'broll', 'window': [43.0, 58.0],
                                           'video_id': 'youtube-clip'}})
        result = self.check(p)
        self.assertEqual(result['issues'], [], result['issues'])
        self.assertEqual((result['beats'][0]['source_file'], result['beats'][0]['source_in_ms'],
                          result['beats'][0]['source_out_ms']), ('B01.mp4', 1000, 3000))
        with patch('documentary_storyboard.source_rate', return_value='30'):
            built, _ = prepare(p, self.root, [], [], False, lambda _: True, strict=True)
        first = built['scenes'][0]
        self.assertEqual((first['plan_row']['source_file'], first['plan_row']['source_in_ms'],
                          first['plan_row']['source_out_ms']), ('B01.mp4', 1000, 3000))

    def test_contiguous_source_ranges_are_not_flagged_as_reused_footage(self):
        p = copy.deepcopy(self.project)
        p['production_script']['text'] = '\n\n'.join([
            narration_beat(1, 'S01.mp4', 0, 2000, s_in=0),
            narration_beat(2, 'S01.mp4', 2000, 4000, s_in=2000)])
        report = self.check(p)
        self.assertEqual(report['issues'], [], report['issues'])

    @RETIRED
    def test_same_underlying_broll_interval_cannot_be_reused_as_full_source(self):
        p = copy.deepcopy(self.project)
        p['production_script']['text'] = '\n\n'.join([
            narration_beat(1, 'S01.mp4', 0, 2000, s_in=1000),
            narration_beat(2, 'B01.mp4', 2000, 4000, s_in=1000)])
        broll_path = self.root / 'sources' / 'broll-repeat.mp4'
        broll_path.write_bytes(b'local-broll')
        p['assets'].append({'id': 'broll-repeat', 'name': 'B01.mp4', 'original_name': 'B01.mp4',
                            'kind': 'video', 'path': broll_path.relative_to(self.root).as_posix(),
                            'duration': 15.0, 'revision': 'broll-r1', 'category': 'broll',
                            'derived_from': {'asset_id': 'a1'},
                            'provenance': {'kind': 'youtube', 'media': 'broll', 'window': [0.0, 15.0]}})
        report = self.check(p)
        self.assertTrue(any('same underlying source window' in issue for issue in report['issues']),
                        report['issues'])

    @RETIRED
    def test_timing_range_longer_or_shorter_than_narration_is_blocked_without_mutation(self):
        for edited, expected in ((self.project['production_script']['text'].replace(
                                    'Source OUT: 00:00:03,000', 'Source OUT: 00:00:03,100', 1), 'mismatch'),
                                 (self.project['production_script']['text'].replace(
                                    'Source OUT: 00:00:03,000', 'Source OUT: 00:00:02,900', 1), 'mismatch')):
            p = copy.deepcopy(self.project)
            p['production_script']['text'] = edited
            report = self.check(p)
            self.assertTrue(any(expected in issue for issue in report['issues']), report['issues'])
            state = review_state(p, self.root, report)
            self.assertEqual(state['beats'][0]['validation_status'], 'TIMING MISMATCH')
            parsed = read_beats(edited)[0]
            self.assertEqual(parsed['source_out_ms'], 3100 if '03,100' in edited else 2900)
            self.assertNotEqual(parsed['source_out_ms'], parsed['source_in_ms'] + parsed['narration_out_ms'] - parsed['narration_in_ms'])

    @RETIRED
    def test_one_output_frame_source_duration_tolerance_is_allowed_but_not_fitted(self):
        text = self.project['production_script']['text'].replace(
            'Source OUT: 00:00:03,000', 'Source OUT: 00:00:03,033', 1)
        p = copy.deepcopy(self.project)
        p['production_script']['text'] = text
        result = self.check(p)
        self.assertEqual(result['issues'], [])
        self.assertEqual(result['beats'][0]['source_out_ms'], 3033)

    def test_frame_quantisation_is_reported_and_only_applied_by_explicit_decision(self):
        import hashlib
        from types import SimpleNamespace
        from documentary_render_plan import plan as render_plan
        source = self.root / 'sources' / 'quantized.mp4'
        source.write_bytes(b'exact-source')
        project = {'production_script': {'text': 'Full source: S01.mp4'},
                   'documentary_beat_review': {'strict_execution': True},
                   'assets': [{'id': 'quantized', 'name': 'S01.mp4', 'original_name': 'S01.mp4',
                               'kind': 'video', 'path': 'sources/quantized.mp4',
                               'revision': 'r1'}]}
        sound = {'revision': 7}
        event = {'label': '001', 'kind': 'narration', 'asset_id': 'quantized',
                 'source': 'S01.mp4', 'source_start_frame': 0, 'source_end_frame': 61,
                 'source_fps': '30', 'output_fps': '30', 'timeline_in_ms': 0,
                 'timeline_out_ms': 2000, 'caption': '', 'picture_scale': 100}

        class VideoContainer:
            duration = None
            streams = SimpleNamespace(video=[SimpleNamespace(frames=61, average_rate=Fraction(30))])
            def __enter__(self): return self
            def __exit__(self, *_args): return False

        with patch('documentary_render_plan.playback_schedule', return_value=[event]), \
             patch('av.open', return_value=VideoContainer()):
            blocked = render_plan(project, self.root, sound)
        self.assertFalse(blocked['picture_compatible'])
        self.assertEqual(blocked['quantization'][0]['difference_frames'], -1)
        self.assertEqual(blocked['quantization'][0]['status'], 'explicit decision required')
        self.assertIn('no frame was added, dropped or repeated', blocked['errors'][0].lower())

        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        decisions = {'version': 1,
                     'script_sha256': hashlib.sha256(project['production_script']['text'].encode()).hexdigest(),
                     'plan_revision': 7, 'source_fps': '30',
                     'changes': [{'label': '001', 'asset_id': 'quantized', 'asset_revision': 'r1',
                                  'source': 'S01.mp4', 'source_sha256': digest,
                                  'source_start_frame': 0, 'source_end_frame': 61,
                                  'timeline_in_ms': 0, 'timeline_out_ms': 2000, 'delta': -1}]}
        with patch('documentary_render_plan.playback_schedule', return_value=[event]), \
             patch('av.open', return_value=VideoContainer()):
            approved = render_plan(project, self.root, sound, decisions)
        self.assertTrue(approved['picture_compatible'], approved['errors'])
        self.assertEqual(approved['spans'][0]['source_end_frame'], 60)
        self.assertEqual(approved['quantization'][0]['status'], 'user approved')

    @RETIRED
    def test_out_after_real_duration_blocks_instead_of_clamping(self):
        p = copy.deepcopy(self.project)
        p['assets'][0]['duration'] = 2.5
        report = self.check(p)
        self.assertTrue(any('provides 2.500s' in issue and 'requests 1.000–3.000s' in issue
                            for issue in report['issues']), report['issues'])

    @RETIRED
    def test_missing_and_ambiguous_exact_source_do_not_substitute(self):
        p = copy.deepcopy(self.project)
        p['assets'] = [a for a in p['assets'] if a['original_name'] != 'S01.mp4']
        missing = self.check(p)
        self.assertTrue(any('S01.mp4 is missing' in issue for issue in missing['issues']), missing['issues'])
        self.assertNotEqual(missing['beats'][0].get('asset_id'), 'a2')
        p = copy.deepcopy(self.project)
        p['assets'].append({**copy.deepcopy(self.project['assets'][0]), 'id': 'duplicate'})
        ambiguous = self.check(p)
        self.assertTrue(any('S01.mp4 is ambiguous (2 exact filename matches)' in issue for issue in ambiguous['issues']), ambiguous['issues'])

    @RETIRED
    def test_narration_gap_and_overlap_block_with_exact_interval(self):
        original = self.project['production_script']['text']
        for changed, word, interval in (
            (original.replace('Narration Clock: RESUMES at 00:00:02,000 --> 00:00:04,000',
                              'Narration Clock: RESUMES at 00:00:02,500 --> 00:00:04,000'), 'gap', '2.000s to 2.500s'),
            (original.replace('Narration Clock: RESUMES at 00:00:02,000 --> 00:00:04,000',
                              'Narration Clock: RESUMES at 00:00:01,500 --> 00:00:04,000'), 'overlap', '2.000s to 1.500s')):
            p = copy.deepcopy(self.project)
            p['production_script']['text'] = changed
            issues = self.check(p)['issues']
            self.assertTrue(any(word in issue and interval in issue for issue in issues), issues)

    @RETIRED
    def test_source_script_changes_stale_the_review_and_blockers(self):
        beats = read_beats(self.project['production_script']['text'])
        validation = self.check()
        record = {'strict_execution': True,
                  'script_sha256': __import__('hashlib').sha256(self.project['production_script']['text'].encode()).hexdigest(),
                  'source_signatures': validation['source_signatures'],
                  'visual_reviews': {b['label']: {'status': 'reviewed'} for b in beats}}
        self.project['documentary_beat_review'] = record
        self.assertFalse(review_state(self.project, self.root)['stale'])
        self.project['production_script']['text'] += '\n# corrected'
        self.assertTrue(review_state(self.project, self.root)['stale'])
        self.assertTrue(any('changed after the Beat review' in x for x in review_blockers(self.project, self.root)))
        self.project['production_script']['text'] = self.project['production_script']['text'].removesuffix('\n# corrected')
        (self.root / 'sources' / 'source-1.mp4').write_bytes(b'replaced-source-content')
        self.assertTrue(review_state(self.project, self.root)['stale'])

    @RETIRED
    def test_human_visual_wrong_and_exception_states_are_explicit(self):
        built, _ = prepare(self.project, self.root, [], [], False, lambda _: True,
                           strict=True)
        p = built
        p['documentary_beat_review']['source_signatures'] = self.check()['source_signatures']
        self.assertTrue(any('visual has not been reviewed' in x.lower() for x in review_blockers(p, self.root)))
        review = make_review(p, self.root, '001', 'wrong', 'The source interval shows an unrelated location.')
        self.assertEqual(review['status'], 'wrong')
        p['documentary_beat_review']['visual_reviews']['001'] = review
        self.assertTrue(any('flagged wrong' in x for x in review_blockers(p, self.root)),
                        review_blockers(p, self.root))
        exception = make_review(p, self.root, '001', 'exception', 'Editor approved the contextual archive shot.')
        self.assertTrue(exception['explicit_approval'])

    @RETIRED
    def test_bite_exact_speaker_range_and_derived_broll_rejection(self):
        text = '\n\n'.join([
            narration_beat(1, 'S01.mp4', 0, 2000, s_in=0),
            bite_beat(2, 'S02.mp4', 2000, 2000, 1000, 4000, 'Reporter A'),
            narration_beat(3, 'S03.mp4', 2000, 4000, 3000, 5000)])
        p = fixture(self.root, text)
        # The last narration line occupies master time 3–5 seconds because the bite adds one second.
        p['assets'][2]['duration'] = 30
        result = self.check(p)
        self.assertEqual(result['issues'], [])
        bite = result['beats'][1]
        self.assertEqual((bite['source_file'], bite['source_in_ms'], bite['source_out_ms'], bite['speaker']),
                         ('S02.mp4', 4000, 5000, 'Reporter A'))
        p['assets'][1]['category'] = 'broll'
        p['assets'][1]['provenance'] = {'kind': 'youtube', 'media': 'broll'}
        result = self.check(p)
        self.assertTrue(any('B-roll or derived asset' in x for x in result['issues']), result['issues'])

    @RETIRED
    def test_consecutive_bites_keep_order_pause_anchor_and_exact_ranges(self):
        text = '\n\n'.join([
            narration_beat(1, 'S01.mp4', 0, 2000, s_in=0),
            bite_beat(2, 'S02.mp4', 2000, 2000, 1000, 4000, 'Reporter A', 'ANCHOR-77'),
            bite_beat(3, 'S03.mp4', 2000, 3000, 1000, 7000, 'Reporter B', 'ANCHOR-77'),
            narration_beat(4, 'S04.mp4', 2000, 4000, 4000, 6000)])
        p = fixture(self.root, text)
        result = self.check(p)
        self.assertEqual(result['issues'], [])
        self.assertEqual([(b['label'], b['pause_ms'], b['anchor_id']) for b in result['beats'][1:3]],
                         [('002', 2000, 'ANCHOR-77'), ('003', 2000, 'ANCHOR-77')])
        with patch('documentary_storyboard.source_rate', return_value='30'):
            built, plan = prepare(p, self.root, [], [], False, lambda _: True,
                                  allow_consecutive_bites=True, strict=True)
        ordered = [b['script_beat'] for b in plan['bites']]
        self.assertEqual(ordered, ['002', '003'])
        master = built['documentary_beat_review']['sound_bites']
        self.assertEqual([(b['timeline_in_ms'], b['timeline_out_ms']) for b in master], [(2000, 3000), (3000, 4000)])
        scripted = built['documentary_beat_review']['scripted_beats']
        self.assertEqual([b['anchor_id'] for b in scripted[1:3]], ['ANCHOR-77', 'ANCHOR-77'])


class StrictProductionRoutesTest(unittest.TestCase):
    @RETIRED
    def test_proposal_uses_validate_only_and_visual_plan_cannot_replace_script(self):
        import app as server
        with tempfile.TemporaryDirectory() as tmp, patch.object(server, 'PROJECTS', Path(tmp)):
            client = server.app.test_client()
            created = client.post('/api/projects', json={'title': 'Strict fixture',
                                                          'edit_mode': 'documentary'}).get_json()
            pid = created['id']
            root = Path(tmp) / pid
            p = server.load(pid)
            p['production_script'] = {'name': 'approved-v5.md', 'text': '\n\n'.join([
                narration_beat(1, 'S01.mp4', 0, 2000, s_in=1000),
                narration_beat(2, 'S02.mp4', 2000, 4000, s_in=5000)])}
            p['voiceover'] = {'path': 'inputs/narration.wav', 'name': 'narration.wav', 'duration': 4.0}
            p['srt'] = {'blocks': [{'number': 1, 'start_ms': 0, 'end_ms': 2000, 'text': 'First.'},
                                   {'number': 2, 'start_ms': 2000, 'end_ms': 4000, 'text': 'Second.'}]}
            p['assets'] = []
            for number in (1, 2):
                source = root / 'sources' / f'source-{number}.mp4'
                source.write_bytes(b'video')
                p['assets'].append({'id': f'a{number}', 'name': f'S{number:02d}.mp4',
                                    'original_name': f'S{number:02d}.mp4', 'kind': 'video',
                                    'path': source.relative_to(root).as_posix(), 'duration': 30,
                                    'revision': f'r{number}', 'verified': True,
                                    'source': 'Synthetic test footage'})
            broll = p['assets'][0]
            broll.update(name='B01.mp4', original_name='B01.mp4', category='broll',
                         provenance={'kind': 'youtube', 'media': 'broll', 'window': [43.0, 58.0]},
                         derived_from={'asset_id': 'youtube-original'})
            p['production_script']['text'] = p['production_script']['text'].replace(
                'Full source: S01.mp4', 'Full source: B01.mp4', 1)
            (root / 'inputs' / 'narration.wav').write_bytes(b'audio')
            server.save(p)
            proposal = client.get(f'/api/projects/{pid}/documentary-beat-proposal')
            self.assertEqual(proposal.status_code, 200, proposal.get_data(as_text=True))
            self.assertTrue(proposal.get_json()['strict_execution'])
            self.assertEqual(proposal.get_json()['adjustments'], [])
            self.assertEqual([(b['source_file'], b['source_in_ms'], b['source_out_ms'])
                              for b in proposal.get_json()['beats']], [('B01.mp4', 1000, 3000), ('S02.mp4', 5000, 7000)])
            preview = client.get(f'/api/projects/{pid}/assets/a1/source-file')
            self.assertEqual(preview.status_code, 200, preview.get_data(as_text=True))
            self.assertEqual(preview.data, b'video')
            preview.close()

            approved_text = p['production_script']['text']
            visual_path = root / 'reviews' / 'visual_plan.json'
            visual_path.write_text('{}', encoding='utf-8')
            with patch.object(server, '_visual_plan_path', return_value=visual_path):
                denied = client.post(f'/api/projects/{pid}/visual-plan/apply', json={})
            self.assertEqual(denied.status_code, 400)
            self.assertIn('cannot replace or modify', denied.get_json()['error'])
            self.assertEqual(server.load(pid)['production_script']['text'], approved_text)

    @RETIRED
    def test_successful_strict_rebuild_archives_old_frame_approvals(self):
        import app as server
        with tempfile.TemporaryDirectory() as tmp, patch.object(server, 'PROJECTS', Path(tmp)):
            client = server.app.test_client()
            pid = client.post('/api/projects', json={'title': 'Rebuild fixture',
                                                      'edit_mode': 'documentary'}).get_json()['id']
            root = Path(tmp) / pid
            p = server.load(pid)
            p['production_script'] = {'name': 'approved-v5.md', 'text': '\n\n'.join([
                narration_beat(1, 'S01.mp4', 0, 2000, s_in=1000),
                narration_beat(2, 'S02.mp4', 2000, 4000, s_in=5000)])}
            p['voiceover'] = {'path': 'inputs/narration.wav', 'name': 'narration.wav', 'duration': 4.0}
            p['srt'] = {'blocks': [{'number': 1, 'start_ms': 0, 'end_ms': 2000, 'text': 'First.'},
                                   {'number': 2, 'start_ms': 2000, 'end_ms': 4000, 'text': 'Second.'}]}
            p['assets'] = []
            for number in (1, 2):
                source = root / 'sources' / f'source-{number}.mp4'
                source.write_bytes(b'video')
                p['assets'].append({'id': f'a{number}', 'name': f'S{number:02d}.mp4',
                                    'original_name': f'S{number:02d}.mp4', 'kind': 'video',
                                    'path': source.relative_to(root).as_posix(), 'duration': 30,
                                    'revision': f'r{number}', 'verified': True,
                                    'source': 'Synthetic test footage'})
            (root / 'inputs' / 'narration.wav').write_bytes(b'audio')
            p['updated'] = 123.0
            p['documentary_beat_review'] = {'strict_execution': True,
                'frame_adjustments': [{'beat_label': '001', 'detail': 'previous approval',
                                       'explicit_approval': True, 'approved_at': 100.0}]}
            server.write(root / 'project.json', p)
            from documentary import load_plan
            plan = load_plan(root)
            decisions = {'version': 1, 'script_sha256': 'old-script',
                         'plan_revision': plan['revision'], 'source_fps': '30',
                         'changes': [{'label': '001', 'delta': 1, 'detail': 'old frame approval'}]}
            decision_path = root / 'reviews' / 'documentary_frame_decisions.json'
            decision_path.write_text(json.dumps(decisions), encoding='utf-8')
            data = {'confirmed': True, 'project_version': p['updated'],
                    'plan_revision': plan['revision'],
                    'script_sha256': __import__('hashlib').sha256(p['production_script']['text'].encode()).hexdigest()}
            with patch.object(server, 'probe', return_value={'has_audio': True}), \
                 patch.object(server, 'schedule_auto_build', lambda _: None), \
                 patch.object(server, '_start_documentary_audio', lambda _: None), \
                 patch('documentary_beat_plan.frame_limits', side_effect=lambda _r, assets: {a['id']: 30_000 for a in assets}), \
                 patch('documentary_storyboard.source_rate', return_value=Fraction(30)), \
                 patch('strict_cuts.source_rate', return_value=Fraction(30)), \
                 patch('strict_cuts.inspect_video'):
                built = server._documentary_beat_build_work(pid, root, data, lambda *_args, **_kwargs: None)
            self.assertFalse(decision_path.exists())
            archived = list((root / 'reviews').glob('documentary_frame_decisions_invalidated_*.json'))
            self.assertEqual(len(archived), 1)
            invalidated = built['documentary_beat_review']['invalidated_frame_decisions']
            self.assertEqual(invalidated['changes'][0]['detail'], 'old frame approval')
            self.assertEqual(invalidated['previous_approvals'][0]['detail'], 'previous approval')


if __name__ == '__main__':
    unittest.main()
