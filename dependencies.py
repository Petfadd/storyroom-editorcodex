"""Required Python libraries: check them, install what is missing, report plainly.

Storyroom used to install its libraries only the first time the launcher created
`.venv`. A library added by a later update, or one removed by accident, then broke the
editor with server errors instead of saying what was wrong. This module is used by:

  * verified_launch.py   - before the editor starts, every time;
  * UPDATE_EXISTING_STORYROOM.py - after new code is copied in;
  * app.py               - GET/POST /api/dependencies, the in-editor "Repair" button,
                            and the friendly error when a missing library is hit.

Installs use the same Python that runs Storyroom (`sys.executable`), with the project's
requirements and constraints files, so they land in Storyroom's own `.venv`.
"""
from __future__ import annotations

import importlib
import importlib.util
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# import name -> (pip distribution, what it is used for)
REQUIRED = {
    'flask': ('Flask', 'the editor web server'),
    'av': ('av (PyAV)', 'exact frame counts, frame timing checks, sound-bite audio, music length and the final MP4 safety check'),
    'cv2': ('opencv-python-headless', 'reading frames for thumbnails and analysis'),
    'PIL': ('Pillow', 'photos, CTA cards and still images'),
    'imageio_ffmpeg': ('imageio-ffmpeg', 'the bundled FFmpeg used for rendering'),
    'psutil': ('psutil', 'CPU, memory and disk readings for the job queue'),
    'numpy': ('numpy', 'audio and image arithmetic'),
}


def missing(names=None):
    """Import names that cannot be found by this interpreter."""
    importlib.invalidate_caches()
    out = []
    for name in (names or REQUIRED):
        try:
            if importlib.util.find_spec(name) is None:
                out.append(name)
        except (ImportError, ValueError):
            out.append(name)
    return out


def describe(names):
    return [{'module': n, 'package': REQUIRED.get(n, (n, ''))[0], 'used_for': REQUIRED.get(n, ('', ''))[1]} for n in names]


def install_command(root=ROOT):
    root = Path(root)
    cmd = [sys.executable, '-m', 'pip', 'install', '--disable-pip-version-check', '-r', str(root / 'requirements.txt')]
    constraints = root / 'requirements-constraints.txt'
    if constraints.is_file():
        cmd += ['-c', str(constraints)]
    return cmd


def install(root=ROOT, log=print, timeout=1800):
    """Run pip for the requirements file. Returns (ok, output tail)."""
    cmd = install_command(root)
    log('Installing required libraries into Storyroom\'s own Python environment...')
    log('  ' + ' '.join(f'"{c}"' if ' ' in c else c for c in cmd))
    try:
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, encoding='utf-8',
                              errors='replace', timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as err:
        return False, str(err)
    tail = '\n'.join((proc.stdout + '\n' + proc.stderr).strip().splitlines()[-25:])
    importlib.invalidate_caches()
    return proc.returncode == 0, tail


def ensure(root=ROOT, log=print, auto_install=True):
    """Check, install if needed, and return what is still missing (empty = all good)."""
    gone = missing()
    if not gone:
        return []
    for item in describe(gone):
        log(f"MISSING: {item['package']} - needed for {item['used_for']}.")
    if not auto_install:
        return gone
    ok, tail = install(root, log)
    if not ok:
        log('The automatic install did not finish. Last messages from pip:')
        log(tail)
    still = missing()
    if still:
        log('STILL MISSING: ' + ', '.join(REQUIRED.get(n, (n,))[0] for n in still))
        log('Check the internet connection, then start Storyroom again (it retries automatically).')
    else:
        log('All required libraries are installed.')
    return still


# ---- In-editor repair job --------------------------------------------------------------
_job = {'status': 'idle', 'started': None, 'finished': None, 'log': ''}
_lock = threading.Lock()


def status():
    gone = missing()
    with _lock:
        job = dict(_job)
    return {'ok': not gone, 'missing': describe(gone), 'repair': job,
            'command': ' '.join(install_command())}


def start_repair(root=ROOT):
    with _lock:
        if _job['status'] == 'running':
            return False
        _job.update(status='running', started=time.time(), finished=None, log='')

    def work():
        lines = []
        ok, tail = install(root, log=lines.append)
        still = missing()
        with _lock:
            _job.update(status='done' if ok and not still else 'error', finished=time.time(),
                        log='\n'.join(lines + [tail])[-6000:])
    threading.Thread(target=work, name='storyroom-dependency-repair', daemon=True).start()
    return True


def friendly_error(err):
    """Plain message for a ModuleNotFoundError raised inside a request."""
    name = (getattr(err, 'name', None) or '').split('.')[0]
    package, used_for = REQUIRED.get(name, (name or 'a library', 'this feature'))
    return (f'Storyroom is missing {package}, which it needs for {used_for}. '
            'Click "Repair now" in the yellow bar at the top, or close Storyroom and start it again '
            'with START_UPDATED_STORYROOM_8004.bat - it installs missing libraries automatically. '
            'Your project is safe on disk.')


if __name__ == '__main__':
    still = ensure()
    raise SystemExit(1 if still else 0)
