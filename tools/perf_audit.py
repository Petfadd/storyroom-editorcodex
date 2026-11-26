"""Performance audit for the Storyroom editor: measure every stage on THIS machine.

Run from the editor folder (the one with app.py), with the editor's own Python:

    python tools/perf_audit.py machine
        What the PC has: cores, RAM, GPU, which ffmpeg hardware encoders really work,
        and whether the final renderer's graphics-card output passes its frame check
        (if it does not, every shot used to be encoded twice).

    python tools/perf_audit.py stages --project <id> [--sources 4]
        Times the per-file stages on real project sources without changing them:
        probe, packet-index frame check, full decode speed, thumbnail and poster seeks,
        a proxy (old and new encoder options), and one final-render shot with
        "Enhance" off and on.

    python tools/perf_audit.py ytdlp <url> [<url> ...]
        Times extraction/metadata, then downloads the same video with several fragment
        and chunk settings, and several videos at once, and reports the throughput of
        each. Nothing is changed in any project; files go to a temporary folder.

    python tools/perf_audit.py render --project <id> --label before [--enhance] [--srt]
        Starts a final render through the editor's own API (the editor must be running),
        samples CPU, GPU, RAM, VRAM, disk and network once a second until it finishes,
        and writes perf_logs/render-<label>.json and .md with per-phase times.

    python tools/perf_audit.py compare perf_logs/render-before.json perf_logs/render-after.json

    python tools/perf_audit.py report
        Summarises perf_logs/stages.jsonl (written by the app during normal use:
        downloads, imports, proxies, thumbnails, Beat builds, previews, renders).

For a before/after comparison of the same project: run `render --label before` on the
original editor, install the patched files, restart the editor, run `render --label
after` with the same options, then `compare`.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
LOGS = ROOT / 'perf_logs'
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def _ffmpeg():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def _run(cmd, timeout=3600):
    t = time.monotonic()
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, creationflags=NO_WINDOW)
    return time.monotonic() - t, r


# ----------------------------------------------------------------------------- monitor

class Monitor:
    """Samples the machine once a second in a background thread."""

    def __init__(self, interval=1.0, watch_dirs=()):
        import psutil
        self.psutil = psutil
        self.interval = interval
        self.samples = []
        self.gpu = []
        self.watch_dirs = [Path(d) for d in watch_dirs]
        self._stop = threading.Event()
        self._threads = []

    def _app_process(self):
        for p in self.psutil.process_iter(['cmdline', 'pid']):
            try:
                if any(str(x).endswith('app.py') for x in (p.info['cmdline'] or [])):
                    return p
            except (self.psutil.Error, TypeError):
                continue
        return None

    def _dir_size(self, path):
        total = 0
        if not path.exists():
            return 0
        for dirpath, _dirs, files in os.walk(path):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(dirpath, f))
                except OSError:
                    pass
        return total

    def _loop(self):
        ps = self.psutil
        disk0, net0, t0 = ps.disk_io_counters(), ps.net_io_counters(), time.monotonic()
        ps.cpu_percent(percpu=True)
        app = self._app_process()
        tick = 0
        while not self._stop.wait(self.interval):
            now = time.monotonic(); dt = max(1e-3, now - t0)
            disk, net = ps.disk_io_counters(), ps.net_io_counters()
            cores = ps.cpu_percent(percpu=True)
            vm = ps.virtual_memory()
            row = {'t': time.time(), 'cpu': round(sum(cores) / max(1, len(cores)), 1), 'cpu_max_core': max(cores or [0]),
                   'ram_used_gb': round((vm.total - vm.available) / 1e9, 2), 'ram_pct': vm.percent,
                   'disk_read_mbs': round((disk.read_bytes - disk0.read_bytes) / dt / 1e6, 2) if disk and disk0 else None,
                   'disk_write_mbs': round((disk.write_bytes - disk0.write_bytes) / dt / 1e6, 2) if disk and disk0 else None,
                   'net_recv_mbit': round((net.bytes_recv - net0.bytes_recv) * 8 / dt / 1e6, 2),
                   'net_sent_mbit': round((net.bytes_sent - net0.bytes_sent) * 8 / dt / 1e6, 2)}
            try:
                if app is None or not app.is_running():
                    app = self._app_process()
                if app is not None:
                    kids = app.children(recursive=True)
                    row['app_rss_mb'] = round(app.memory_info().rss / 1e6, 1)
                    row['ffmpeg_procs'] = sum(1 for k in kids if 'ffmpeg' in (k.name() or '').lower())
                    row['children_rss_mb'] = round(sum(k.memory_info().rss for k in kids) / 1e6, 1)
                    try:
                        row['app_open_files'] = len(app.open_files())
                    except ps.Error:
                        pass
            except ps.Error:
                pass
            if tick % 10 == 0 and self.watch_dirs:
                row['temp_mb'] = round(sum(self._dir_size(d) for d in self.watch_dirs) / 1e6, 1)
            disk0, net0, t0 = disk, net, now
            self.samples.append(row); tick += 1

    def _gpu_loop(self):
        smi = shutil.which('nvidia-smi')
        while not self._stop.wait(3.0):
            row = {'t': time.time()}
            try:
                if smi:
                    out = subprocess.run([smi, '--query-gpu=utilization.gpu,utilization.encoder,utilization.decoder,'
                                               'memory.used,memory.total', '--format=csv,noheader,nounits'],
                                         capture_output=True, text=True, timeout=10, creationflags=NO_WINDOW).stdout
                    g, e, d, used, total = [float(x) for x in out.strip().splitlines()[0].split(',')]
                    row.update(gpu_3d=g, gpu_encode=e, gpu_decode=d, vram_used_mb=used, vram_total_mb=total, source='nvidia-smi')
                elif os.name == 'nt':
                    ps = ("$s=(Get-Counter '\\GPU Engine(*)\\Utilization Percentage','\\GPU Adapter Memory(*)\\Dedicated Usage' "
                          "-ErrorAction SilentlyContinue).CounterSamples; $s | Select-Object Path,CookedValue | ConvertTo-Json -Compress")
                    out = subprocess.run(['powershell', '-NoProfile', '-Command', ps], capture_output=True, text=True,
                                         timeout=20, creationflags=NO_WINDOW).stdout
                    items = json.loads(out or '[]'); items = items if isinstance(items, list) else [items]
                    agg = {'3d': 0.0, 'videoencode': 0.0, 'videodecode': 0.0, 'mem': 0.0}
                    for it in items:
                        path = str(it.get('Path', '')).lower(); v = float(it.get('CookedValue') or 0)
                        if 'dedicated usage' in path: agg['mem'] += v
                        elif 'engtype_3d' in path: agg['3d'] += v
                        elif 'engtype_videoencode' in path: agg['videoencode'] += v
                        elif 'engtype_videodecode' in path: agg['videodecode'] += v
                    row.update(gpu_3d=min(100, agg['3d']), gpu_encode=min(100, agg['videoencode']),
                               gpu_decode=min(100, agg['videodecode']), vram_used_mb=round(agg['mem'] / 1e6, 1),
                               source='windows-counters')
            except Exception as error:
                row['error'] = type(error).__name__
            self.gpu.append(row)

    def start(self):
        for target in (self._loop, self._gpu_loop):
            t = threading.Thread(target=target, daemon=True); t.start(); self._threads.append(t)
        return self

    def stop(self):
        self._stop.set()
        for t in self._threads:
            t.join(timeout=25)

    @staticmethod
    def summarise(rows, keys):
        out = {}
        for k in keys:
            vals = [r[k] for r in rows if isinstance(r.get(k), (int, float))]
            if vals:
                out[k] = {'avg': round(statistics.mean(vals), 1), 'max': round(max(vals), 1)}
        return out

    def window(self, start, end):
        cpu_keys = ['cpu', 'cpu_max_core', 'ram_used_gb', 'disk_read_mbs', 'disk_write_mbs', 'net_recv_mbit',
                    'app_rss_mb', 'children_rss_mb', 'ffmpeg_procs', 'temp_mb']
        gpu_keys = ['gpu_3d', 'gpu_encode', 'gpu_decode', 'vram_used_mb']
        return {**self.summarise([r for r in self.samples if start <= r['t'] <= end], cpu_keys),
                **self.summarise([r for r in self.gpu if start <= r['t'] <= end], gpu_keys)}


# ----------------------------------------------------------------------------- machine

def machine(_args):
    import psutil
    import resources
    ff = _ffmpeg()
    info = {'cores_logical': os.cpu_count(), 'cores_physical': psutil.cpu_count(logical=False),
            'ram_gb': round(psutil.virtual_memory().total / 1e9, 1), 'ffmpeg': ff,
            'on_battery': None}
    try:
        bat = psutil.sensors_battery()
        info['on_battery'] = (not bat.power_plugged) if bat else None
    except Exception:
        pass
    caps = resources.capabilities()
    info['hardware_encoders_working'] = [e['name'] for e in caps.get('hardware', [])]
    info['proxy_encoder'] = caps.get('proxy_encoder')
    from documentary_final_renderer import _gpu_encoders, _piece_workers, _video_info
    gpu = _gpu_encoders(ff, 21)
    info['render_piece_workers'] = _piece_workers()
    info['render_gpu_encoder'] = gpu[0][1] if gpu else None
    if gpu:
        # The renderer's exact acceptance test on a 4-second 1080p clip.
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'gpu.mp4'
            frames = 120
            rate = '30000/1001'
            cmd = [ff, '-hide_banner', '-loglevel', 'error', '-y', '-f', 'lavfi', '-i',
                   f'testsrc2=s=1920x1080:r={rate}:d=5', '-vf',
                   f'trim=start_frame=0:end_frame={frames},setpts=N/({rate}*TB),format=yuv420p',
                   '-fps_mode', 'passthrough', *gpu[0], '-video_track_timescale', '30000',
                   '-frames:v', str(frames), str(out)]
            secs, r = _run(cmd, 120)
            got = _video_info(out) if out.is_file() else (None, None)
            info['render_gpu_check'] = {'encode_seconds': round(secs, 2), 'returncode': r.returncode,
                                        'frames': got[0], 'rate': str(got[1]), 'expected_frames': frames,
                                        'expected_rate': rate,
                                        'passes': got[0] == frames and got[1] == Fraction(30000, 1001),
                                        'stderr': (r.stderr or '')[-300:]}
    print(json.dumps(info, indent=2))
    LOGS.mkdir(exist_ok=True); (LOGS / 'machine.json').write_text(json.dumps(info, indent=2))


# ----------------------------------------------------------------------------- stages

def _project(pid):
    path = ROOT / 'projects' / pid / 'project.json'
    if not path.is_file():
        sys.exit(f'No project {pid} under {ROOT / "projects"}')
    return path.parent, json.loads(path.read_text(encoding='utf-8'))


def stages(args):
    import av, cv2
    import proxy as proxy_module
    from strict_cuts import packet_scan
    from conform import capture
    from documentary_final_renderer import _span_filters, _ss, VIDEO_PRESET, _seek_offset
    ff = _ffmpeg()
    root, p = _project(args.project)
    vids = [a for a in p.get('assets', []) if a.get('kind') == 'video' and (root / a['path']).is_file()]
    vids.sort(key=lambda a: -(a.get('duration') or 0))
    rows = []
    for a in vids[:args.sources]:
        src = root / a['path']; name = a.get('original_name') or a['name']; dur = float(a.get('duration') or 0)
        r = {'file': name, 'duration_s': round(dur, 1), 'mb': round(src.stat().st_size / 1e6, 1)}
        t, pr = _run([ff, '-hide_banner', '-i', str(src)], 60); r['probe_s'] = round(t, 3)
        t0 = time.monotonic(); scan = packet_scan(src, 10 ** 9, 10 ** 9); r['packet_scan_s'] = round(time.monotonic() - t0, 2)
        with av.open(str(src)) as c:
            v = c.streams.video[0]; v.thread_type = 'AUTO'
            r['codec'] = v.codec_context.name; r['size'] = f'{v.width}x{v.height}'; r['fps'] = str(v.base_rate)
            t0 = time.monotonic(); n = 0
            for _ in c.decode(v):
                n += 1
                if n >= 600: break
            r['decode_fps'] = round(n / max(1e-3, time.monotonic() - t0), 1)
        for label, at in (('thumb_start', 1.0), ('thumb_middle', dur / 2), ('thumb_late', dur * 0.9)):
            t0 = time.monotonic(); cap = capture(src)
            try:
                cap.set(cv2.CAP_PROP_POS_MSEC, at * 1000); ok, _img = cap.read()
            finally:
                cap.release()
            r[label + '_s'] = round(time.monotonic() - t0, 3)
        with tempfile.TemporaryDirectory() as tmp:
            info = proxy_module.probe(ff, src)
            if proxy_module.needs_proxy(info):
                enc = proxy_module.resources.encoder_for('proxy')
                old = [ff, '-y', '-hide_banner', '-loglevel', 'error', '-i', str(src), '-t', '30', '-map', '0:v:0',
                       '-vf', 'scale=-2:540:flags=fast_bilinear', *enc, '-preset', 'veryfast', '-crf', '26', '-an',
                       str(Path(tmp) / 'old.mp4')]
                t, res = _run(old, 600)
                r['proxy_old_args_30s'] = {'seconds': round(t, 2), 'ok': res.returncode == 0,
                                           'encoder': enc[1], 'error': (res.stderr or '').strip()[-160:]}
                new = old[:old.index(enc[0])] + ['-c:v', enc[1], *proxy_module._proxy_quality(enc[1]), '-an', old[-1]]
                t, res = _run(new, 600)
                r['proxy_new_args_30s'] = {'seconds': round(t, 2), 'ok': res.returncode == 0}
            # One final-render shot (10 s from the middle), exactly as the renderer encodes it.
            rate_f = Fraction(30000, 1001); rate = '30000/1001'; frames = 300
            span = {'source_start_frame': int(dur / 2 * 29.97), 'source_frame_count': frames, 'frame_conversion': None,
                    'picture_scale': 100}
            for enhance in (False, True):
                seek, filt = _span_filters(span, 0, frames, 1920, 1080, rate_f, rate, enhance, seek_offset=_seek_offset(src))
                cmd = [ff, '-hide_banner', '-loglevel', 'error', '-y', *_ss(seek), '-i', str(src), '-an', '-vf', filt,
                       '-fps_mode', 'passthrough', '-c:v', 'libx264', '-preset', VIDEO_PRESET, '-bf', '0', '-crf', '20',
                       '-threads', '2', '-frames:v', str(frames), str(Path(tmp) / 'shot.mp4')]
                t, _res = _run(cmd, 600)
                r['render_shot_fps_enhance' if enhance else 'render_shot_fps'] = round(frames / t, 1)
        rows.append(r); print(json.dumps(r))
    LOGS.mkdir(exist_ok=True)
    (LOGS / 'stages-bench.json').write_text(json.dumps(rows, indent=2))


# ----------------------------------------------------------------------------- yt-dlp

def ytdlp(args):
    from footage_downloader import YtDlpProvider
    cmd, path = YtDlpProvider.command()
    if not cmd:
        sys.exit('yt-dlp is not installed.')
    env = YtDlpProvider._env(path)
    fmt = YtDlpProvider._format_args(args.quality)
    results = {'extraction': [], 'variants': [], 'parallel': []}
    for url in args.urls:
        t0 = time.monotonic()
        out = subprocess.run(cmd + ['-J', '--no-playlist', *fmt[:4], url], capture_output=True, text=True, env=env,
                             timeout=300, creationflags=NO_WINDOW)
        meta = json.loads(out.stdout or '{}') if out.returncode == 0 else {}
        chosen = meta.get('requested_formats') or [meta]
        results['extraction'].append({'url': url, 'seconds': round(time.monotonic() - t0, 2),
                                      'formats': [{'id': f.get('format_id'), 'protocol': f.get('protocol'),
                                                   'vcodec': f.get('vcodec'), 'acodec': f.get('acodec'),
                                                   'size_mb': round((f.get('filesize') or f.get('filesize_approx') or 0) / 1e6, 1)}
                                                  for f in chosen]})
        print(json.dumps(results['extraction'][-1]))

    def download(url, folder, fragments, chunk):
        args_ = cmd + ['--no-playlist', '--ignore-config', '--no-mtime', '--newline', '--retries', '10',
                       '--concurrent-fragments', str(fragments), *(['--http-chunk-size', chunk] if chunk else []),
                       '--ffmpeg-location', _ffmpeg(), '-o', str(Path(folder) / '%(id)s.%(ext)s'), *fmt, url]
        t0 = time.monotonic(); merge_at = None
        proc = subprocess.Popen(args_, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env,
                                creationflags=NO_WINDOW)
        for line in proc.stdout:
            if line.startswith('[Merger]') and merge_at is None:
                merge_at = time.monotonic()
        proc.wait(); end = time.monotonic()
        size = sum(f.stat().st_size for f in Path(folder).glob('*.mp4'))
        dl = (merge_at or end) - t0
        return {'seconds': round(end - t0, 2), 'merge_s': round(end - merge_at, 2) if merge_at else 0,
                'mb': round(size / 1e6, 1), 'mbit_s': round(size * 8 / 1e6 / max(1e-3, dl), 1), 'ok': proc.returncode == 0}

    variants = [(1, '10M'), (4, '10M'), (4, ''), (8, '')]   # (4, '10M') is the editor's current setting
    for fragments, chunk in variants:
        with tempfile.TemporaryDirectory() as tmp:
            r = download(args.urls[0], tmp, fragments, chunk)
        r.update(fragments=fragments, chunk=chunk or 'none', current=(fragments, chunk) == (4, '10M'))
        results['variants'].append(r); print(json.dumps(r))
    if len(args.urls) > 1:
        for k in sorted({1, 2, min(3, len(args.urls)), min(4, len(args.urls))}):
            urls = args.urls[:k]
            with tempfile.TemporaryDirectory() as tmp:
                t0 = time.monotonic(); out = [None] * k
                threads = [threading.Thread(target=lambda i=i: out.__setitem__(i, download(urls[i], Path(tmp) / str(i), 4, '10M')))
                           for i in range(k)]
                for i in range(k): (Path(tmp) / str(i)).mkdir()
                for t in threads: t.start()
                for t in threads: t.join()
                wall = time.monotonic() - t0; mb = sum(o['mb'] for o in out if o)
            r = {'simultaneous': k, 'wall_s': round(wall, 1), 'mb': round(mb, 1), 'mbit_s': round(mb * 8 / max(1e-3, wall), 1),
                 'current_default': k == 2}
            results['parallel'].append(r); print(json.dumps(r))
    LOGS.mkdir(exist_ok=True); (LOGS / 'ytdlp-bench.json').write_text(json.dumps(results, indent=2))


# ----------------------------------------------------------------------------- render

def _stage_rows(since):
    path = LOGS / 'stages.jsonl'
    rows = []
    if path.is_file():
        for line in path.read_text(encoding='utf-8').splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            end = time.mktime(time.strptime(row['at'], '%Y-%m-%dT%H:%M:%S'))
            if end >= since - 1:
                row['_end'] = end; row['_start'] = end - row['seconds']; rows.append(row)
    return rows


def render(args):
    root, p = _project(args.project)
    status_file = root / 'render_status.json'
    before = status_file.stat().st_mtime if status_file.exists() else 0
    mon = Monitor(watch_dirs=[root / 'renders', Path(tempfile.gettempdir())]).start()
    started = time.time()
    body = json.dumps({'final': True, 'strict_checked_version': p.get('updated'), 'enhance_picture': bool(args.enhance),
                       'srt_subtitles': bool(args.srt)}).encode()
    req = urllib.request.Request(f'{args.url}/api/projects/{args.project}/render', data=body,
                                 headers={'Content-Type': 'application/json'}, method='POST')
    try:
        urllib.request.urlopen(req, timeout=600).read()
    except urllib.error.HTTPError as e:
        mon.stop(); sys.exit('The editor refused the render: ' + e.read().decode('utf-8', 'replace')[:500])
    state = {}
    while True:
        time.sleep(3)
        try:
            if status_file.stat().st_mtime > before:
                state = json.loads(status_file.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if state.get('status') in ('done', 'error', 'cancelled'):
            break
        print(f"\r{state.get('progress', 0):5.1f}%  {state.get('stage', '')[:60]:60}", end='', flush=True)
    ended = time.time(); mon.stop(); print()
    phases = [r for r in _stage_rows(started) if r['stage'].startswith('render.')]
    report = {'label': args.label, 'project': args.project, 'status': state.get('status'), 'error': state.get('error'),
              'wall_s': round(ended - started, 1), 'options': {'enhance_picture': bool(args.enhance), 'srt': bool(args.srt)},
              'phases': [{'phase': r['stage'][7:], 'seconds': r['seconds'], **mon.window(r['_start'], r['_end'])} for r in phases],
              'whole_run': mon.window(started, ended),
              'renderer_counts': next((({k: r.get(k) for k in ('pieces', 'frames', 'gpu_pieces', 'cpu_pieces', 'gpu_fallbacks')})
                                       for r in reversed(phases) if 'pieces' in r), {})}
    LOGS.mkdir(exist_ok=True)
    (LOGS / f'render-{args.label}.json').write_text(json.dumps(report, indent=2))
    (LOGS / f'render-{args.label}-samples.json').write_text(json.dumps({'system': mon.samples, 'gpu': mon.gpu}))
    md = [f"# Render {args.label}: {report['status']} in {report['wall_s'] / 60:.1f} min", '',
          '| Phase | Seconds | Share | CPU avg/max % | GPU enc % | Disk R/W MB/s | ffmpeg procs |', '|---|---|---|---|---|---|---|']
    total = sum(x['seconds'] for x in report['phases']) or 1
    for x in report['phases']:
        g = lambda k, s='avg': (x.get(k) or {}).get(s, '')
        md.append(f"| {x['phase']} | {x['seconds']:.0f} | {100 * x['seconds'] / total:.0f}% | {g('cpu')}/{g('cpu', 'max')} | "
                  f"{g('gpu_encode')} | {g('disk_read_mbs')}/{g('disk_write_mbs')} | {g('ffmpeg_procs', 'max')} |")
    (LOGS / f'render-{args.label}.md').write_text('\n'.join(md) + '\n', encoding='utf-8')
    print('\n'.join(md))


def compare(args):
    a, b = (json.loads(Path(x).read_text()) for x in (args.before, args.after))
    print(f"{'':24}{a['label']:>12}{b['label']:>12}{'change':>10}")
    print(f"{'wall time (min)':24}{a['wall_s'] / 60:12.1f}{b['wall_s'] / 60:12.1f}{(b['wall_s'] / a['wall_s'] - 1) * 100:+9.0f}%")
    pa = {x['phase']: x['seconds'] for x in a.get('phases', [])}; pb = {x['phase']: x['seconds'] for x in b.get('phases', [])}
    for k in list(dict.fromkeys(list(pa) + list(pb))):
        va, vb = pa.get(k), pb.get(k)
        ch = f"{(vb / va - 1) * 100:+9.0f}%" if va and vb else ''
        print(f"{k:24}{(va or 0):12.0f}{(vb or 0):12.0f}{ch:>10}")
    if a.get('options') != b.get('options'):
        print('WARNING: the two renders used different options:', a.get('options'), b.get('options'))


def report(_args):
    rows = _stage_rows(0)
    if not rows:
        sys.exit('No stage timings yet. Use the editor (download, import, build, render), then run this again.')
    by = {}
    for r in rows:
        by.setdefault(r['stage'], []).append(r['seconds'])
    total = sum(sum(v) for v in by.values())
    print(f"{'stage':34}{'count':>7}{'total s':>10}{'mean s':>9}{'share':>8}")
    for k, v in sorted(by.items(), key=lambda kv: -sum(kv[1])):
        print(f"{k:34}{len(v):7}{sum(v):10.1f}{statistics.mean(v):9.2f}{100 * sum(v) / total:7.0f}%")
    dl = [r for r in rows if r['stage'] == 'download.ytdlp' and r.get('mbps')]
    if dl:
        print(f"\nyt-dlp: {len(dl)} downloads, median {statistics.median(r['mbps'] for r in dl):.1f} Mbit/s, "
              f"extraction {sum(r['extract_metadata_s'] for r in dl):.0f}s, download {sum(r['download_s'] for r in dl):.0f}s, "
              f"merge {sum(r['merge_s'] for r in dl):.0f}s; protocols: {sorted({(r.get('formats') or '').split('|')[1] if '|' in (r.get('formats') or '') else '?' for r in dl})}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('machine')
    s = sub.add_parser('stages'); s.add_argument('--project', required=True); s.add_argument('--sources', type=int, default=4)
    y = sub.add_parser('ytdlp'); y.add_argument('urls', nargs='+'); y.add_argument('--quality', default='1080')
    r = sub.add_parser('render'); r.add_argument('--project', required=True); r.add_argument('--label', required=True)
    r.add_argument('--enhance', action='store_true'); r.add_argument('--srt', action='store_true')
    r.add_argument('--url', default='http://127.0.0.1:8003')
    c = sub.add_parser('compare'); c.add_argument('before'); c.add_argument('after')
    sub.add_parser('report')
    a = ap.parse_args()
    {'machine': machine, 'stages': stages, 'ytdlp': ytdlp, 'render': render, 'compare': compare, 'report': report}[a.cmd](a)


if __name__ == '__main__':
    main()
