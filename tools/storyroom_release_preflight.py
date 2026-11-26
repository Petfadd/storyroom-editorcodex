"""Read-only, offline Storyroom startup and release check for the local Windows PC.

No project files are changed. Media duration/identity and full exports require the
project-specific preflight and an actual sample render.
"""
from __future__ import annotations

import ast
import importlib.util
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ERRORS = []
WARNINGS = []


def result(condition, description, *, necessary=True):
    mark = 'PASS' if condition else ('FAIL' if necessary else 'WARN')
    print(f'[{mark}] {description}')
    if not condition:
        (ERRORS if necessary else WARNINGS).append(description)


def check_build():
    try:
        tree = ast.parse((ROOT / 'verified_launch.py').read_text(encoding='utf-8'))
        builds = [node.value.value for node in tree.body if isinstance(node, ast.Assign)
                  for tgt in node.targets if isinstance(tgt, ast.Name) and tgt.id == 'EXPECTED_BUILD'
                  and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)]
        server = (ROOT / 'app.py').read_text(encoding='utf-8')
        match = re.search(r"def build_info\(\):\s*return jsonify\(\{'build':\s*'([^']+)'", server)
        result(len(builds) == 1 and bool(match) and builds[0] == match.group(1),
               'Windows launcher matches the installed Storyroom application build')
        if match:
            print('Build:', match.group(1))
    except Exception as exc:
        result(False, f'Cannot inspect build identifiers: {exc}')


def check_files():
    required = ['app.py', 'verified_launch.py', 'START_UPDATED_STORYROOM_8004.bat',
                'templates/index.html', 'static/editor.js', 'static/person_overlays.js',
                'blueprints/style_profiles.json', 'data/broll_catalog.json',
                'tools/install_local_whisper.py', 'requirements.txt', 'requirements-constraints.txt']
    result(all((ROOT / name).is_file() for name in required), 'Application and support resources are present')
    result((ROOT / 'projects').is_dir(), 'Project storage folder exists', necessary=False)
    for rel in ('app.py', 'person_overlays.py', 'documentary.py', 'documentary_beats.py',
                'documentary_final_renderer.py', 'channel_cta.py', 'captions.py', 'proxy.py'):
        try:
            compile((ROOT / rel).read_bytes(), str(ROOT / rel), 'exec')
        except Exception as exc:
            result(False, f'Python syntax error in {rel}: {exc}')
    if shutil.which('node'):
        scripts = ['static/editor.js', 'static/person_overlays.js',
                   'static/documentary.js', 'static/documentary_timeline.js']
        result(all(subprocess.run(['node', '--check', str(ROOT / rel)],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
                   for rel in scripts), 'JavaScript syntax checks')
    else:
        print('[INFO] Node.js unavailable: browser JavaScript cannot be checked here (not required to run Storyroom).')


def check_runtime():
    needed = ['flask', 'av', 'cv2', 'PIL', 'imageio_ffmpeg', 'psutil']
    missing = [module for module in needed if importlib.util.find_spec(module) is None]
    result(not missing, 'Required Python libraries available' + (f' (missing: {", ".join(missing)})' if missing else ''))
    ffmpeg = None
    if importlib.util.find_spec('imageio_ffmpeg'):
        try:
            import imageio_ffmpeg
            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        except (OSError, RuntimeError):
            pass
    ffmpeg = ffmpeg or shutil.which('ffmpeg')
    result(bool(ffmpeg and Path(ffmpeg).is_file()), 'FFmpeg executable is available')
    try:
        sys.path.insert(0, str(ROOT))
        import captions
        result(captions.font_path('documentary').is_file(),
               'A usable local caption font is available (bundled or operating-system font)')
    except Exception as exc:
        result(False, f'Caption font fallback could not be inspected: {exc}', necessary=False)
    try:
        space = shutil.disk_usage(ROOT).free / (1024 ** 3)
        print(f'[INFO] Free disk space: {space:.1f} GB')
        result(space >= 10, 'At least 10 GB of free space for intermediate media', necessary=False)
    except OSError:
        result(False, 'Could not determine available disk space', necessary=False)


def main():
    print('STORYROOM - OFFLINE PRE-VIDEO STARTUP CHECK')
    print('Folder:', ROOT)
    print('This check does not edit projects and is not a 60-minute export test.\n')
    check_build()
    check_files()
    check_runtime()
    print(f'\nRESULT: {len(ERRORS)} blocking issue(s); {len(WARNINGS)} warning(s).')
    if ERRORS:
        print('Do NOT start the next large export until the blocking issues are resolved.')
    else:
        print('Startup prerequisites checked. Test one short real project preview before a long export.')
    return int(bool(ERRORS))


if __name__ == '__main__':
    raise SystemExit(main())
