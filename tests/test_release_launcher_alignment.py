"""Source-only guard: launcher build ID must match the app build endpoint."""
import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

class ReleaseLauncherAlignmentTests(unittest.TestCase):
    def test_launcher_matches_app_build_id(self):
        launcher = ast.parse((ROOT / 'verified_launch.py').read_text(encoding='utf-8'))
        builds = [node.value.value for node in launcher.body
                  if isinstance(node, ast.Assign)
                  for target in node.targets
                  if isinstance(target, ast.Name) and target.id == 'EXPECTED_BUILD'
                  and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)]
        self.assertEqual(len(builds), 1)
        app = (ROOT / 'app.py').read_text(encoding='utf-8')
        match = re.search(r"def build_info\(\):\s*return jsonify\(\{'build':\s*'([^']+)'", app)
        self.assertIsNotNone(match)
        self.assertEqual(builds[0], match.group(1))

if __name__ == '__main__':
    unittest.main()
