"""Opt-in, local-only media tools setup for Storyroom.

No network or installation occurs on import/status. All install operations use fixed
allowlisted commands, run in background, and report errors to the UI. Installed
binaries live under .cache/storyroom-tools, never in system Program Files/PATH.
"""
from __future__ import annotations

import importlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent
TOOL_DIR = ROOT / '.cache' / 'storyroom-tools'
BIN_DIR = TOOL_DIR / 'bin'
SCENE_DIR = TOOL_DIR / 'scene-detect'
VALID_INSTALLS = {'yt-dlp', 'ffprobe', 'scenedetect', 'faster-whisper', 'whisper-model', 'youtube-runtime'}
# This is the Windows build provider listed by ffmpeg.org. Bundle ffprobe only.
FFPROBE_WINDOWS_ARCHIVE = 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip'
DENO_WINDOWS_ARCHIVE = 'https://github.com/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip'
_LOCK = threading.RLock()
_JOB = {'status': 'idle', 'tool': '', 'detail': '', 'error': '', 'log': [], 'started_at': None, 'finished_at': None}
_CACHE = {'at': 0.0, 'data': None}


def register_private_packages():
    """The existing scenedetect API can find an installed private module."""
    if SCENE_DIR.is_dir() and str(SCENE_DIR) not in sys.path:
        sys.path.append(str(SCENE_DIR))


def _version(binary, timeout=5):
    try:
        for flag in ('--version', '-version'):
            p = subprocess.run([str(binary), flag], capture_output=True, text=True,
                               errors='replace', timeout=timeout)
            if p.returncode == 0:
                return ((p.stdout or p.stderr).splitlines() or ['unknown'])[0][:140]
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def _which(name):
    suffix = '.exe' if os.name == 'nt' else ''
    private = BIN_DIR / (name + suffix)
    if private.is_file() and _version(private):
        return str(private)
    return shutil.which(name)


def ffprobe_executable():
    return _which('ffprobe')


def read_metadata(file_path: Path) -> dict:
    """Read actual codec/duration/fps, without editing or downloading source media."""
    cmd = ffprobe_executable()
    if not cmd:
        raise RuntimeError('FFprobe is missing. Open Media Tools to install it.')
    result = subprocess.run([cmd, '-v', 'error', '-show_format', '-show_streams',
                             '-of', 'json', str(file_path)], capture_output=True, text=True,
                            errors='replace', timeout=40)
    if result.returncode:
        raise RuntimeError((result.stderr or 'FFprobe could not read this file.')[:350])
    return json.loads(result.stdout)


def _module(name, dist=None):
    register_private_packages()
    try:
        if importlib.util.find_spec(name) is None:
            return {'ready': False, 'version': None}
        importlib.import_module(name)
        try:
            version = importlib.metadata.version(dist or name)
        except importlib.metadata.PackageNotFoundError:
            version = 'importable'
        return {'ready': True, 'version': version}
    except (ImportError, OSError, ValueError) as exc:
        return {'ready': False, 'version': None, 'detail': str(exc)[:200]}


def _yt_status():
    from footage_downloader import YtDlpProvider
    return YtDlpProvider.status()


def _speech_status():
    import speech_setup
    s = speech_setup.status()
    s['progress'] = speech_setup.install_progress()
    return s


def status(refresh=False):
    now = time.monotonic()
    with _LOCK:
        if not refresh and _CACHE['data'] is not None and now - _CACHE['at'] < 12:
            return {**_CACHE['data'], 'install': dict(_JOB)}
    import imageio_ffmpeg
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    ffprobe = ffprobe_executable()
    yt = _yt_status()
    speech = _speech_status()
    scene = _module('scenedetect')
    # A JS runtime is needed for many current YouTube challenge responses.
    deno = _which('deno')
    result = {'tools': {
        'python': {'ready': True, 'version': sys.version.split()[0], 'detail': sys.executable},
        'ffmpeg': {'ready': bool(ffmpeg and Path(ffmpeg).is_file()), 'version': _version(ffmpeg), 'detail': 'Bundled by imageio-ffmpeg'},
        'ffprobe': {'ready': bool(ffprobe), 'version': _version(ffprobe) if ffprobe else None,
                    'detail': str(ffprobe) if ffprobe else ('Windows: install into Storyroom.' if os.name == 'nt' else 'Install FFprobe through your operating system.')},
        'yt-dlp': {'ready': bool(yt.get('available')), 'version': yt.get('version'), 'detail': yt.get('detail') or ''},
        'scenedetect': {**scene, 'detail': 'PySceneDetect scene boundaries for local footage.'},
        'faster-whisper': {'ready': bool(speech['package']['installed']), 'version': speech['package']['detail'],
                          'detail': 'CPU speech recognition package'},
        'whisper-model': {'ready': bool(speech['model']['installed']), 'version': speech['model']['detail'],
                          'detail': 'Local Whisper small model (about 484 MB)'},
        'youtube-runtime': {'ready': bool(deno), 'version': _version(deno) if deno else None,
                            'detail': 'Optional Deno runtime for reliable YouTube JavaScript challenge support'},
        'whisperx': {'ready': False, 'version': None, 'detail': 'Advanced module intentionally deferred; not installed.'},
    }, 'speech': speech, 'platform': sys.platform, 'offline_after_setup': True}
    with _LOCK:
        _CACHE.update(data=result, at=time.monotonic())
        return {**result, 'install': dict(_JOB)}


def _log(text):
    with _LOCK:
        _JOB['detail'] = str(text)[-280:]
        _JOB['log'] = (_JOB['log'] + [str(text)[-350:]])[-18:]


def _install_pip_scene():
    """No OpenCV GUI wheels: reuse Storyroom's existing headless OpenCV install."""
    SCENE_DIR.parent.mkdir(parents=True, exist_ok=True)
    if importlib.util.find_spec('cv2') is None:
        raise RuntimeError('OpenCV is missing. Repair the main Storyroom requirements first.')
    dependencies = [('click', 'click'), ('platformdirs', 'platformdirs'), ('tqdm', 'tqdm')]
    extras = [pkg for module, pkg in dependencies if importlib.util.find_spec(module) is None]
    with tempfile.TemporaryDirectory(prefix='storyroom-scenedetect-', dir=SCENE_DIR.parent) as tmp:
        target = Path(tmp) / 'package'
        _log('Installing PySceneDetect without altering OpenCV')
        cmd = [sys.executable, '-m', 'pip', 'install', '--disable-pip-version-check', '--no-deps',
               '--target', str(target), 'scenedetect>=0.6,<0.8', *extras]
        p = subprocess.run(cmd, capture_output=True, text=True, errors='replace', timeout=900)
        if p.returncode:
            raise RuntimeError('PySceneDetect pip install failed: ' + (p.stderr or p.stdout)[-650:])
        # Check in a fresh process, not the running Flask process's module cache.
        code = 'import sys;sys.path.append(sys.argv[1]);from scenedetect import ContentDetector;print("ready")'
        check = subprocess.run([sys.executable, '-c', code, str(target)], capture_output=True,
                               text=True, errors='replace', timeout=20, cwd=str(ROOT))
        if check.returncode:
            raise RuntimeError('PySceneDetect missing prerequisite: ' + (check.stderr or check.stdout)[-550:])
        old = SCENE_DIR.with_name('scene-detect.previous')
        shutil.rmtree(old, ignore_errors=True)
        if SCENE_DIR.exists():
            SCENE_DIR.replace(old)
        target.replace(SCENE_DIR)
        shutil.rmtree(old, ignore_errors=True)
        register_private_packages()


def extract_named_binary(archive, exe_name, destination):
    """Extract one expected executable, never using archive paths as filesystem paths."""
    with zipfile.ZipFile(archive) as package:
        entries = [item for item in package.infolist()
                   if not item.is_dir() and Path(item.filename).name.lower() == exe_name.lower()]
        if len(entries) != 1:
            raise RuntimeError(f'Archive did not contain exactly one {exe_name}.')
        item = entries[0]
        if item.file_size > 240 * 1024 * 1024:
            raise RuntimeError('Binary exceeds safety size limit.')
        destination = Path(destination)
        with package.open(item) as src, destination.open('wb') as out:
            shutil.copyfileobj(src, out)


def _install_zip_binary(url, exe_name, limit_bytes):
    if os.name != 'nt':
        raise RuntimeError('Bundled binary installation is Windows-only. Use your OS package manager otherwise.')
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='storyroom-tool-', dir=TOOL_DIR) as tmp:
        temp = Path(tmp)
        archive = temp / 'package.zip'
        req = urllib.request.Request(url, headers={'User-Agent': 'Storyroom-Media-Tools/1.0'})
        _log('Downloading verified-source archive over HTTPS')
        with urllib.request.urlopen(req, timeout=90) as response, archive.open('wb') as out:
            total = 0
            while True:
                buf = response.read(1024 * 1024)
                if not buf:
                    break
                total += len(buf)
                if total > limit_bytes:
                    raise RuntimeError('Archive exceeds safety size limit.')
                out.write(buf)
        candidate = temp / exe_name
        extract_named_binary(archive, exe_name, candidate)
        # Validate by executing the downloaded binary before making it available.
        version = _version(candidate, timeout=15)
        if not version:
            raise RuntimeError('Downloaded executable failed its version check.')
        _log(version)
        final = BIN_DIR / exe_name
        candidate.replace(final)


def _do_install(tool):
    try:
        if tool == 'yt-dlp':
            from footage_downloader import install_ytdlp
            _log('Installing yt-dlp and its YouTube challenge support')
            install_ytdlp(True, _log)
        elif tool == 'ffprobe':
            _install_zip_binary(FFPROBE_WINDOWS_ARCHIVE, 'ffprobe.exe', 350 * 1024 * 1024)
        elif tool == 'youtube-runtime':
            _install_zip_binary(DENO_WINDOWS_ARCHIVE, 'deno.exe', 150 * 1024 * 1024)
        elif tool == 'scenedetect':
            _install_pip_scene()
        elif tool in ('faster-whisper', 'whisper-model'):
            import speech_setup
            kind = 'package' if tool == 'faster-whisper' else 'model'
            _log('Starting speech installer')
            result = speech_setup.start(kind)
            if not result.get('started'):
                if not speech_setup.status()['ready']:
                    raise RuntimeError(result.get('reason') or 'Speech setup could not start')
            else:
                while True:
                    progress = speech_setup.install_progress()
                    _log(progress.get('detail') or 'Installing local speech component')
                    if progress.get('status') not in ('running', 'queued'):
                        if progress.get('status') != 'done':
                            raise RuntimeError(progress.get('detail') or 'Speech install failed')
                        break
                    time.sleep(1)
        else:
            raise ValueError('Unsupported tool installation.')
        with _LOCK:
            _JOB.update(status='done', detail=f'{tool} setup completed', error='')
    except BaseException as exc:
        with _LOCK:
            _JOB.update(status='failed', detail='Setup failed', error=str(exc)[-650:])
    finally:
        with _LOCK:
            _JOB['finished_at'] = time.time()
            _CACHE.update(at=0.0, data=None)


def install(tool):
    if tool not in VALID_INSTALLS:
        raise ValueError('Unsupported tool; only allowlisted Storyroom tools can be installed.')
    with _LOCK:
        if _JOB['status'] == 'running':
            raise RuntimeError(f"{_JOB['tool']} installation is already running.")
        _JOB.update(status='running', tool=tool, detail='Starting', error='', log=[],
                    started_at=time.time(), finished_at=None)
    threading.Thread(target=_do_install, args=(tool,), daemon=True, name='storyroom-install-' + tool).start()
    return {'started': True, 'tool': tool}
