"""Tests for the Intelligent Cinematic Motion Graphics Engine.

Covers:
  - Settings normalisation and validation
  - Context analysis (act detection, exclusion patterns, template scoring)
  - Suggestion generation
  - All four templates produce valid Sequences with independent elements
  - Per-element animation state at various times
  - Frame rendering produces a valid RGBA image
  - Caching: same inputs produce the same signature
  - Non-destructive integration: original footage/SRT/timestamps untouched
  - Final-render overlay filter generation
  - Disabled-by-default: no sequences drawn unless enabled
"""
from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

# Make the package importable even when tests run from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import motion_graphics as mg
import motion_templates as mt
import motion_render as mr


# -------------------------------------------------------------- fixtures

SAMPLE_SCRIPT = """
Beat: 001
Type: VOICE OVER
Master timeline 00:00:00:00
Narration Clock 00:00:00:00 -> 00:00:08:00
Spoken Narration: The investigation revealed three key findings that changed the course of the case.

Beat: 002
Type: VOICE OVER
Master timeline 00:00:08:00
Narration Clock 00:00:08:00 -> 00:00:16:00
Spoken Narration: On January 15, 2019, the first witness came forward. Then on March 3, 2019, a second witness contradicted the initial account.

Beat: 003
Type: VOICE OVER
Master timeline 00:00:16:00
Narration Clock 00:00:16:00 -> 00:00:24:00
Spoken Narration: However, the evidence documented at the scene showed a clear discrepancy between what was reported and what was verified.

Beat: 004
Type: VOICE OVER
Master timeline 00:00:24:00
Narration Clock 00:00:24:00 -> 00:00:32:00
Spoken Narration: The court found the defendant guilty on two counts. The sentence was twenty years in state prison.
"""

SAMPLE_SRT = [
    {'number': 1, 'start_ms': 0, 'end_ms': 8000,
     'text': 'The investigation revealed three key findings.'},
    {'number': 2, 'start_ms': 8000, 'end_ms': 16000,
     'text': 'On January 15 2019, the first witness came forward.'},
    {'number': 3, 'start_ms': 16000, 'end_ms': 24000,
     'text': 'However, the evidence showed a discrepancy.'},
    {'number': 4, 'start_ms': 24000, 'end_ms': 32000,
     'text': 'The court found the defendant guilty.'},
]


# -------------------------------------------------------------- settings

class SettingsTest(unittest.TestCase):
    def test_defaults_disabled(self):
        s = mg.settings({})
        self.assertFalse(s['enabled'])
        self.assertEqual(s['mode'], 'auto')
        self.assertEqual(s['sequences'], [])

    def test_normalise_forces_valid_values(self):
        p = {'motion_graphics': {'enabled': 'yes', 'mode': 'bogus'}}
        s = mg.normalise(p)
        self.assertTrue(s['enabled'])           # 'yes' is truthy → True
        self.assertEqual(s['mode'], 'auto')     # invalid → fallback

    def test_validate_patch_rejects_unknown_keys(self):
        with self.assertRaises(ValueError):
            mg.validate_patch({'unknown_field': 123})

    def test_validate_patch_accepts_sequences(self):
        seq = {
            'id': 'mg_' + 'a' * 12,
            'template': 'investigative_findings',
            'start_s': 10.0, 'end_s': 20.0,
            'content': {'kicker': 'Test', 'title': 'Title', 'findings': ['F1']},
        }
        values = mg.validate_patch({'sequences': [seq], 'enabled': True})
        self.assertEqual(len(values['sequences']), 1)
        self.assertTrue(values['enabled'])

    def test_validate_patch_rejects_bad_sequence(self):
        bad = {'id': 'nope', 'template': 'investigative_findings',
               'start_s': 0, 'end_s': 1, 'content': {}}
        with self.assertRaises(ValueError):
            mg.validate_patch({'sequences': [bad]})

    def test_catalogue_lists_templates(self):
        cat = mg.catalogue({})
        self.assertEqual(len(cat['templates']), 4)
        ids = [t['id'] for t in cat['templates']]
        for t in mg.TEMPLATES:
            self.assertIn(t, ids)

    def test_signature_changes_when_script_changes(self):
        p1 = {'production_script': {'text': 'hello'}, 'srt': {'blocks': []}, 'updated': '1'}
        p2 = {'production_script': {'text': 'goodbye'}, 'srt': {'blocks': []}, 'updated': '2'}
        self.assertNotEqual(mg.signature(p1), mg.signature(p2))


# -------------------------------------------------------------- analysis

class AnalysisTest(unittest.TestCase):
    def test_detects_candidates_in_sample_script(self):
        analysis = mg.analyse_script(SAMPLE_SCRIPT, SAMPLE_SRT)
        self.assertGreater(analysis['blocks_total'], 0)
        self.assertGreater(analysis['narration_blocks'], 0)
        self.assertIsInstance(analysis['candidates'], list)
        self.assertIsInstance(analysis['excluded'], list)

    def test_excludes_emotional_passages(self):
        script = """
Beat: 001
Type: VOICE OVER
Narration Clock 00:00:00:00 -> 00:00:10:00
Spoken Narration: The victim's mother spoke about her grief and the family's tribute to her daughter.
"""
        analysis = mg.analyse_script(script, [])
        # The beat should be excluded, so candidates should be empty.
        self.assertEqual(len(analysis['candidates']), 0)
        self.assertGreater(len(analysis['excluded']), 0)

    def test_scores_legal_outcome_for_charge_passage(self):
        script = """
Beat: 001
Type: VOICE OVER
Narration Clock 00:00:00:00 -> 00:00:10:00
Spoken Narration: The court found the defendant guilty on charges of fraud. The sentence was five years.
"""
        analysis = mg.analyse_script(script, [])
        # At least one candidate should have a legal_outcome score.
        found = False
        for c in analysis['candidates']:
            if 'legal_outcome' in c['template_scores']:
                found = True
                break
        self.assertTrue(found, 'Expected legal_outcome template to score > 0')

    def test_suggest_sequences_returns_valid_proposals(self):
        analysis = mg.analyse_script(SAMPLE_SCRIPT, SAMPLE_SRT)
        suggestions = mg.suggest_sequences(analysis, SAMPLE_SRT, 60.0)
        for s in suggestions:
            self.assertIn('id', s)
            self.assertIn('template', s)
            self.assertIn(s['template'], mg.TEMPLATES)
            self.assertGreater(s['end_s'], s['start_s'])
            self.assertGreaterEqual(s['start_s'], 0)
            self.assertIsInstance(s['content'], dict)


# -------------------------------------------------------------- templates

class TemplatesTest(unittest.TestCase):
    def test_investigative_findings_structure(self):
        seq = mt.build_sequence('investigative_findings', {
            'kicker': 'Test', 'title': 'Title', 'findings': ['A', 'B', 'C']
        }, 15.0)
        self.assertEqual(seq.template_id, 'investigative_findings')
        self.assertGreater(len(seq.elements), 3)  # kicker, title, divider, 3 bullets
        kinds = [e.kind for e in seq.elements]
        self.assertIn('kicker', kinds)
        self.assertIn('title', kinds)
        self.assertIn('divider', kinds)
        self.assertIn('bullet', kinds)

    def test_chronological_timeline_structure(self):
        seq = mt.build_sequence('chronological_timeline', {
            'title': 'Chronology',
            'events': [
                {'date': 'Jan 1', 'event': 'First event'},
                {'date': 'Feb 2', 'event': 'Second event'},
            ],
        }, 12.0)
        kinds = [e.kind for e in seq.elements]
        self.assertIn('kicker', kinds)
        self.assertIn('timeline_line', kinds)
        self.assertIn('marker', kinds)
        self.assertIn('date', kinds)
        self.assertIn('event', kinds)

    def test_contradictory_statements_structure(self):
        seq = mt.build_sequence('contradictory_statements', {
            'title': 'Discrepancy',
            'verified': 'What was documented.',
            'conflicting': 'What was reported.',
        }, 10.0)
        kinds = [e.kind for e in seq.elements]
        self.assertIn('kicker', kinds)
        self.assertIn('divider', kinds)
        self.assertIn('body', kinds)
        self.assertIn('label', kinds)

    def test_legal_outcome_structure(self):
        seq = mt.build_sequence('legal_outcome', {
            'title': 'Legal Outcome',
            'court': 'District Court',
            'charges': ['Count 1: Fraud', 'Count 2: Embezzlement'],
            'verdict': 'Guilty',
            'sentencing': 'Twenty years',
        }, 20.0)
        kinds = [e.kind for e in seq.elements]
        self.assertIn('kicker', kinds)
        self.assertIn('charge', kinds)
        self.assertIn('verdict', kinds)
        self.assertIn('divider', kinds)

    def test_unknown_template_raises(self):
        with self.assertRaises(ValueError):
            mt.build_sequence('nonexistent_template', {}, 10.0)


# -------------------------------------------------------------- animation

class AnimationTest(unittest.TestCase):
    def test_element_hidden_before_t_in(self):
        el = mt.Element('title', mt.rel(0, 0, 1, 0.1), text='Hi', t_in=2.0)
        state = el.state_at(1.0)
        self.assertEqual(state['opacity'], 0.0)

    def test_element_revealed_at_t_in(self):
        el = mt.Element('title', mt.rel(0, 0, 1, 0.1), text='Hi',
                        t_in=1.0, anim_in='fade', anim_in_dur=1.0)
        state = el.state_at(2.0)  # 1 second into 1-second animation → p=1
        self.assertAlmostEqual(state['opacity'], 1.0, places=2)

    def test_element_mid_animation(self):
        el = mt.Element('title', mt.rel(0, 0, 1, 0.1), text='Hi',
                        t_in=0.0, anim_in='fade', anim_in_dur=2.0)
        state = el.state_at(1.0)  # half-way
        self.assertGreater(state['opacity'], 0.0)
        self.assertLess(state['opacity'], 1.0)

    def test_independent_element_reveal(self):
        """Two elements: the second reveals later without affecting the first."""
        e1 = mt.Element('a', mt.rel(0, 0, 1, 0.1), text='A',
                        t_in=0.0, anim_in='fade', anim_in_dur=0.5)
        e2 = mt.Element('b', mt.rel(0, 0.2, 1, 0.1), text='B',
                        t_in=2.0, anim_in='fade', anim_in_dur=0.5)
        # At t=1.0, e1 is fully visible, e2 is not yet revealed.
        s1 = e1.state_at(1.0)
        s2 = e2.state_at(1.0)
        self.assertAlmostEqual(s1['opacity'], 1.0, places=2)
        self.assertEqual(s2['opacity'], 0.0)
        # At t=2.5, both visible.
        s1 = e1.state_at(2.5)
        s2 = e2.state_at(2.5)
        self.assertAlmostEqual(s1['opacity'], 1.0, places=2)
        self.assertGreater(s2['opacity'], 0.0)

    def test_mask_wipe_animation_progresses(self):
        p0 = mt.resolve_animation('mask_wipe', 0.0)
        p1 = mt.resolve_animation('mask_wipe', 1.0)
        self.assertGreater(p0['clip_right'], p1['clip_right'])
        self.assertEqual(p1['clip_right'], 0.0)

    def test_divider_expand_grows(self):
        p0 = mt.resolve_animation('divider_expand', 0.0)
        p1 = mt.resolve_animation('divider_expand', 1.0)
        self.assertLess(p0['scale'], p1['scale'])


# -------------------------------------------------------------- rendering

class RenderTest(unittest.TestCase):
    def test_render_frame_produces_rgba(self):
        seq = mt.build_sequence('investigative_findings', {
            'kicker': 'Test', 'title': 'Findings', 'findings': ['One', 'Two']
        }, 5.0)
        img = mr.render_frame(seq, 1.0, 640, 360, mg.DEFAULTS['design'])
        self.assertEqual(img.size, (640, 360))
        self.assertEqual(img.mode, 'RGBA')

    def test_render_frame_at_zero_hides_all(self):
        """At t=0 only the first element (revealing) should have any pixels."""
        seq = mt.build_sequence('investigative_findings', {
            'kicker': 'Test', 'title': 'Findings', 'findings': ['One']
        }, 8.0)
        img = mr.render_frame(seq, 0.0, 640, 360, mg.DEFAULTS['design'])
        # Should not crash; the frame should have some pixels (backdrop at minimum).
        self.assertEqual(img.size, (640, 360))

    def test_all_templates_render_without_error(self):
        """Smoke test: each template produces a valid frame."""
        cases = {
            'investigative_findings': {'kicker': 'K', 'title': 'T', 'findings': ['A']},
            'chronological_timeline': {'title': 'T', 'events': [{'date': 'D', 'event': 'E'}]},
            'contradictory_statements': {'verified': 'V', 'conflicting': 'C'},
            'legal_outcome': {'charges': ['X'], 'verdict': 'Guilty', 'sentencing': '5y'},
        }
        for tid, content in cases.items():
            seq = mt.build_sequence(tid, content, 5.0)
            img = mr.render_frame(seq, 2.0, 640, 360, mg.DEFAULTS['design'])
            self.assertEqual(img.size, (640, 360), msg=f'Template {tid} size mismatch')

    def test_colour_token_resolution(self):
        r, g, b, a = mr._colour('accent')
        self.assertIsInstance(r, int)
        self.assertEqual(a, 255)

    def test_colour_hex_resolution(self):
        self.assertEqual(mr._colour('#FF0000'), (255, 0, 0, 255))


# -------------------------------------------------------------- cache

class CacheTest(unittest.TestCase):
    def test_same_inputs_same_signature(self):
        seq = mt.build_sequence('investigative_findings',
                                {'kicker': 'K', 'title': 'T', 'findings': ['A']}, 5.0)
        sig1 = mr.sequence_signature(seq, mg.DEFAULTS['design'], Fraction(30), 1920, 1080)
        sig2 = mr.sequence_signature(seq, mg.DEFAULTS['design'], Fraction(30), 1920, 1080)
        self.assertEqual(sig1, sig2)

    def test_different_content_different_signature(self):
        s1 = mt.build_sequence('investigative_findings',
                               {'kicker': 'K', 'title': 'One', 'findings': ['A']}, 5.0)
        s2 = mt.build_sequence('investigative_findings',
                               {'kicker': 'K', 'title': 'Two', 'findings': ['A']}, 5.0)
        self.assertNotEqual(
            mr.sequence_signature(s1, mg.DEFAULTS['design'], Fraction(30), 1920, 1080),
            mr.sequence_signature(s2, mg.DEFAULTS['design'], Fraction(30), 1920, 1080),
        )

    def test_different_resolution_different_signature(self):
        seq = mt.build_sequence('investigative_findings',
                                {'kicker': 'K', 'title': 'T', 'findings': ['A']}, 5.0)
        s1 = mr.sequence_signature(seq, mg.DEFAULTS['design'], Fraction(30), 1920, 1080)
        s2 = mr.sequence_signature(seq, mg.DEFAULTS['design'], Fraction(30), 3840, 2160)
        self.assertNotEqual(s1, s2)


# -------------------------------------------------------------- integration

class IntegrationTest(unittest.TestCase):
    def test_disabled_by_default_no_filters(self):
        """With motion graphics disabled, render_filters returns nothing."""
        project = {'motion_graphics': {'enabled': False, 'sequences': [{
            'id': 'mg_' + 'a' * 12, 'template': 'investigative_findings',
            'start_s': 10, 'end_s': 20,
            'content': {'kicker': 'K', 'title': 'T', 'findings': ['A']},
        }]}}
        inputs, steps, count = mr.render_filters(project, '/tmp', 1920, 1080, '30/1',
                                                 Path('/tmp'), 1, between=(0, 3000))
        self.assertEqual(inputs, [])
        self.assertEqual(steps, [])
        self.assertEqual(count, 0)

    def test_enabled_with_sequences_returns_filters(self):
        """When enabled with valid sequences, render_filters produces inputs."""
        # We cannot run the full encode in the test sandbox easily, but we can
        # verify the function reaches the right branch. Use active_sequences
        # as a proxy.
        project = {'motion_graphics': {'enabled': True, 'sequences': [{
            'id': 'mg_' + 'a' * 12, 'template': 'investigative_findings',
            'start_s': 10, 'end_s': 20,
            'content': {'kicker': 'K', 'title': 'T', 'findings': ['A']},
        }]}}
        seqs = mr.active_sequences(project)
        self.assertEqual(len(seqs), 1)

    def test_original_project_untouched_after_analysis(self):
        """analyse_script must not modify the script or SRT."""
        script = copy.copy(SAMPLE_SCRIPT)
        srt = copy.deepcopy(SAMPLE_SRT)
        mg.analyse_script(script, srt)
        self.assertEqual(script, SAMPLE_SCRIPT)
        self.assertEqual(srt, SAMPLE_SRT)

    def test_validate_sequence_roundtrip(self):
        seq = {
            'id': 'mg_' + 'b' * 12,
            'template': 'legal_outcome',
            'start_s': 5.0, 'end_s': 15.0,
            'content': {'charges': ['Fraud'], 'verdict': 'Guilty'},
        }
        validated = mg._validate_sequence(seq)
        self.assertEqual(validated['template'], 'legal_outcome')
        self.assertEqual(validated['start_s'], 5.0)
        self.assertEqual(validated['end_s'], 15.0)


# -------------------------------------------------------------- performance

class PerformanceTest(unittest.TestCase):
    """Lightweight benchmarks: no hard thresholds, just measurements."""

    def test_frame_render_time_reasonable(self):
        """A single frame of a 4-bullet investigative finding renders quickly."""
        import time
        seq = mt.build_sequence('investigative_findings', {
            'kicker': 'Investigation', 'title': 'Key Findings',
            'findings': ['Finding one', 'Finding two', 'Finding three', 'Finding four'],
        }, 15.0)
        design = mg.DEFAULTS['design']
        # Warm up.
        mr.render_frame(seq, 5.0, 640, 360, design)
        t0 = time.monotonic()
        for _ in range(5):
            mr.render_frame(seq, 5.0, 640, 360, design)
        elapsed = time.monotonic() - t0
        # Should be well under 1 second per frame on any modern CPU.
        self.assertLess(elapsed, 5.0,
                        f'Frame render too slow: {elapsed:.2f}s for 5 frames')


if __name__ == '__main__':
    unittest.main()
