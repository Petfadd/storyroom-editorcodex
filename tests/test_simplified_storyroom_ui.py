"""Regression checks for the simplified documentary editor shell."""
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]

class SimplifiedStoryroomUITest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html=(ROOT/"templates/index.html").read_text(encoding="utf-8")
        cls.setup=(ROOT/"static/studio.js").read_text(encoding="utf-8")
        cls.editor=(ROOT/"static/editor.js").read_text(encoding="utf-8")

    def test_new_projects_use_documentary_workflow(self):
        self.assertIn('name="edit_mode" value="documentary"',self.html)
        self.assertNotIn('Choose a workspace',self.html)
        self.assertNotIn('Script review · current editor',self.html)

    def test_output_resolution_is_chosen_at_render(self):
        self.assertNotIn('<label>Export size<select',self.html)
        self.assertIn('Choose 1080p, 2K or 4K when you click Render MP4',self.html)

    def test_one_transition_library_entry_in_header_and_monitor(self):
        self.assertNotIn('class="head-tool" onclick="openTransitionLibrary()"',self.html)
        self.assertIn('id="transition-library-button"',self.html)

    def test_frame_check_is_available_without_separate_setup_step(self):
        self.assertIn('id="frame-qc-button"',self.html)
        self.assertIn("$('#frame-qc-button').hidden=!ss.length",self.editor)
        self.assertNotIn('Frame check</h3>',self.setup)

    def test_visual_plan_cannot_override_documentary(self):
        self.assertNotIn('/static/visual_plan.js',self.html)
        self.assertNotIn('visualPlanCardHTML()',self.setup)
        app=(ROOT/'app.py').read_text(encoding='utf-8')
        # v19: the visual-plan routes (no longer reachable from the editor) were removed.
        self.assertNotIn("/visual-plan",app)

    def test_research_kit_not_shipped(self):
        self.assertFalse((ROOT/'storyroom_kit.py').exists())
        self.assertFalse((ROOT/'RUN_RESEARCH_KIT.bat').exists())

    def test_source_integrity_features_still_present(self):
        self.assertIn('youtubeCardHTML()',self.setup)
        self.assertIn('openMediaTools()',self.setup)
        self.assertIn('peopleCardHTML()',self.setup)
        self.assertIn('Remove from project',self.setup)
        self.assertIn('id="render-button"',self.html)
        self.assertIn('id="caption-toggle"',self.html)

if __name__=='__main__':unittest.main()
