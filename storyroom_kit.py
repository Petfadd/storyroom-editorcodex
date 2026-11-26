#!/usr/bin/env python3
"""Storyroom research kit: measure, never guess.

One file, for any agent or person writing a Storyroom documentary. Every timestamp,
every "who is on screen" and every script check comes from a tool, not from memory.

 ONE COMMAND on your own PC (YouTube blocks cloud machines):
    python storyroom_kit.py run SHEET.md --out work            # fetch + words + frames + people + check-sheet, then a zip for the agent
    (if YouTube says "Sign in to confirm you're not a bot": put cookies.txt next to this file, or add --cookies cookies.txt)

 Single steps:
    python storyroom_kit.py fetch   SHEET.md --out work/          # metadata, captions, video (yt-dlp)
    python storyroom_kit.py words   work/                         # word-level timings (captions, else faster-whisper)
    python storyroom_kit.py find    work/ "we just didn't know when" [--file S05]
    python storyroom_kit.py frames  work/ [--file S05] [--every 2] [--start 40 --end 80]
    python storyroom_kit.py people  SHEET.md --dir work/          # every person's photo on one sheet; same picture twice = FAIL
    python storyroom_kit.py check-sheet  SHEET.md
    python storyroom_kit.py convert      SCRIPT.md --srt NAMES.srt --out SCRIPT_editor.txt
    python storyroom_kit.py check-script SCRIPT_editor.txt --srt NAMES.srt --sheet SHEET.md
                                         [--sources work/sources.json] [--banned work/banned.json]

Needs: Python 3.9+, ffmpeg on PATH, Pillow. Optional: yt-dlp (fetch), faster-whisper
(words when a video has no captions). A step whose tool is missing or fails says
NOT VERIFIED and why; it never fills the gap with an estimate.
"""
from __future__ import annotations

import argparse, json, re, shutil, subprocess, sys
from pathlib import Path

# ── time helpers ──────────────────────────────────────────────────────────────
def to_ms(t: str) -> int:
    t = t.strip().replace('.', ',')
    parts = t.split(':')
    if len(parts) == 2: parts = ['0'] + parts
    h, m, s = parts
    s, f = (s.split(',') + ['0'])[:2]
    return ((int(h) * 60 + int(m)) * 60 + int(s)) * 1000 + int((f + '000')[:3])

def tc(ms: float) -> str:
    ms = int(round(ms)); h, ms = divmod(ms, 3600000); m, ms = divmod(ms, 60000); s, f = divmod(ms, 1000)
    return f'{h:02}:{m:02}:{s:02},{f:03}'

def mmss(sec: float) -> str:
    m, s = divmod(sec, 60); return f'{int(m)}:{s:06.3f}'

_TC = r'\d\d:\d\d:\d\d[,.]\d{3}'

# ── SRT / VTT ─────────────────────────────────────────────────────────────────
def read_srt(path) -> list[dict]:
    text = Path(path).read_text(encoding='utf-8-sig').replace('\r\n', '\n')
    cues = []
    for block in re.split(r'\n\s*\n', text.strip()):
        lines = block.strip().split('\n')
        for i, line in enumerate(lines):
            m = re.match(rf'({_TC})\s*-->\s*({_TC})', line)
            if m:
                cues.append({'start': to_ms(m.group(1)), 'end': to_ms(m.group(2)), 'text': ' '.join(lines[i + 1:]).strip()})
                break
    return cues

def vtt_words(path) -> tuple[list[dict], str]:
    """Words from a YouTube .vtt. Auto captions carry a time tag per word
    (`word<00:00:02.100><c> next</c>`): those give word-level timings. Plain cues give
    one timing per line; words are then spread across the line and marked 'cue'."""
    text = Path(path).read_text(encoding='utf-8', errors='ignore').replace('\r\n', '\n')
    words, method, seen = [], 'captions-word', set()
    blocks = re.split(r'\n\s*\n', text)
    any_tags = '<c>' in text or re.search(r'<\d\d:\d\d:\d\d\.\d{3}>', text)
    for block in blocks:
        m = re.search(rf'({_TC})\s*-->\s*({_TC})', block)
        if not m: continue
        start, end = to_ms(m.group(1)), to_ms(m.group(2))
        body = block[m.end():].strip().split('\n')
        if any_tags:
            line = next((l for l in body if '<' in l), None)
            if not line: continue                         # YouTube repeats the previous line untagged
            line = re.sub(r'</?c[^>]*>', '', line)
            pieces = re.split(r'<(\d\d:\d\d:\d\d\.\d{3})>', line)
            t = start
            for k in range(0, len(pieces), 2):
                for w in pieces[k].split():
                    key = (t, w)
                    if key not in seen:
                        seen.add(key); words.append({'w': w, 'start': t, 'end': None})
                if k + 1 < len(pieces): t = to_ms(pieces[k + 1])
        else:
            method = 'captions-cue'
            ws = ' '.join(re.sub(r'<[^>]+>', '', l) for l in body).split()
            for i, w in enumerate(ws):
                a = start + (end - start) * i / max(1, len(ws))
                words.append({'w': w, 'start': round(a), 'end': round(start + (end - start) * (i + 1) / max(1, len(ws)))})
    words.sort(key=lambda x: x['start'])
    for i, w in enumerate(words):                          # a word ends where the next begins (max 1.2 s)
        if w['end'] is None:
            nxt = words[i + 1]['start'] if i + 1 < len(words) else w['start'] + 600
            w['end'] = min(nxt, w['start'] + 1200)
    return words, method

# ── footage sheet ─────────────────────────────────────────────────────────────
_LINK = re.compile(r'https?://\S+?(?=\s*\||\s*$)')
def read_sheet(path) -> dict:
    rows = {'S': [], 'B': [], 'issues': []}; section = ''
    for n, line in enumerate(Path(path).read_text(encoding='utf-8').splitlines(), 1):
        if line.startswith('#'): section = line.strip('# ').lower()
        if not line.strip().startswith('|') or re.fullmatch(r'[|\s:-]+', line.strip()): continue
        cells = [c.strip() for c in line.strip().strip('|').split('|')]
        link = next((c for c in cells if c.startswith('http')), '')
        f = next((c for c in cells if re.fullmatch(r'[SBP]\d{2,3}\.(mp4|jpg|jpeg|png|webp)', c, re.I)), '')
        if not f:
            pid = next((c for c in cells if re.fullmatch(r'P\d{2,3}', c)), '')
            if pid: f = pid + '.jpg'; cells[cells.index(pid)] = f                        # a P row gives its ID; the photo is saved as P01.jpg
        if not f:
            if any(c in ('—', '-', 'UNMAPPED') for c in cells) and len(cells) > 3:
                rows['issues'].append(f'line {n}: placeholder row ("—" / UNMAPPED) — remove it')
            continue
        window = next((c for c in cells if re.fullmatch(r'\d+:\d\d(?:\.\d+)?\s*[–-]\s*\d+:\d\d(?:\.\d+)?', c)), '')
        w = None
        if window:
            a, b = re.split(r'\s*[–-]\s*', window)
            sec = lambda x: int(x.split(':')[0]) * 60 + float(x.split(':')[1])
            w = (sec(a), sec(b))
        desc = ' · '.join(c for c in cells if c not in (f, link, window) and not re.fullmatch(r'(SRC-|B)\d+', c))
        kind = 'S' if f.upper().startswith('S') else 'B'          # P rows travel with the B rows (pictures)
        person = ''
        fp = re.search(r'FOR PEOPLE:\s*([^—–\-|]+)', line, re.I)
        if fp:
            person = fp.group(1).strip()
        elif f.upper().startswith('P') or ('people' in section and f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))):
            i = cells.index(f); person = cells[i + 1] if i + 1 < len(cells) else ''
        rows[kind].append({'file': f, 'link': link, 'window': w, 'desc': desc, 'line': n, 'person': person})
    return rows

def yt_id(url: str) -> str:
    m = re.search(r'(?:v=|youtu\.be/|shorts/)([\w-]{11})', url or ''); return m.group(1) if m else ''

# ── fetch ─────────────────────────────────────────────────────────────────────
COOKIES = []                                             # --cookies-from-browser chrome (set in main)

def _ytdlp():
    """yt-dlp: this Python's, the Storyroom editor's own copy (.cache/yt-dlp next to the kit
    or in --editor), or one on PATH."""
    import os
    for folder in [Path(__file__).resolve().parent, *(Path(x) for x in EDITOR)]:
        lib = folder / '.cache' / 'yt-dlp'
        if (lib / 'yt_dlp').is_dir():
            os.environ['PYTHONPATH'] = str(lib) + (os.pathsep + os.environ['PYTHONPATH'] if os.environ.get('PYTHONPATH') else '')
            return [sys.executable, '-m', 'yt_dlp'] + COOKIES
    try:
        import yt_dlp  # noqa: F401
        return [sys.executable, '-m', 'yt_dlp'] + COOKIES
    except ImportError:
        return (['yt-dlp'] + COOKIES) if shutil.which('yt-dlp') else None

EDITOR = []

def FF():
    """ffmpeg on PATH, or the one the editor ships (imageio-ffmpeg)."""
    if shutil.which('ffmpeg'): return 'ffmpeg'
    try:
        import imageio_ffmpeg; return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        sys.exit('NOT VERIFIED: ffmpeg not found (install ffmpeg, or pip install imageio-ffmpeg)')

def duration(path) -> float:
    r = subprocess.run([FF(), '-hide_banner', '-i', str(path)], capture_output=True, text=True, errors='replace')
    m = re.search(r'Duration:\s*(\d+):(\d\d):(\d\d(?:\.\d+)?)', r.stderr)
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else 0.0

def cmd_fetch(a):
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    sheet = read_sheet(a.sheet); y = _ytdlp(); report = {}
    if not y: sys.exit('NOT VERIFIED: yt-dlp is not installed (pip install yt-dlp).')
    for r in sheet['S']:
        stem = r['file'].rsplit('.', 1)[0]; rec = {'file': r['file'], 'link': r['link']}
        info = subprocess.run(y + ['--skip-download', '--dump-json', '--no-warnings', r['link']], capture_output=True, text=True)
        if info.returncode:
            rec['status'] = 'NOT VERIFIED: ' + (info.stderr.strip().splitlines() or ['no metadata'])[-1][:200]
            report[stem] = rec; print(stem, rec['status']); continue
        d = json.loads(info.stdout)
        rec.update(title=d.get('title'), channel=d.get('channel') or d.get('uploader'), upload_date=d.get('upload_date'),
                   duration_s=d.get('duration'), width=d.get('width'), height=d.get('height'),
                   vertical=bool(d.get('height') and d.get('width') and d['height'] > d['width']))
        subprocess.run(y + ['--skip-download', '--write-subs', '--write-auto-subs', '--sub-langs', 'en.*,en', '--sub-format', 'vtt',
                            '-o', str(out / stem), r['link']], capture_output=True, text=True)
        vtts = sorted(out.glob(f'{stem}*.vtt'))
        rec['captions'] = vtts[0].name if vtts else 'NONE (use faster-whisper in `words`)'
        if not a.no_video and (out / f'{stem}.mp4').exists():
            rec['video'] = f'{stem}.mp4 (already downloaded)'
        elif not a.no_video:
            v = subprocess.run(y + ['--ffmpeg-location', FF(), '-f', 'bv*[height<=720][ext=mp4]+ba[ext=m4a]/b[height<=720]/b', '--merge-output-format', 'mp4',
                                    '-o', str(out / f'{stem}.%(ext)s'), r['link']], capture_output=True, text=True)
            rec['video'] = f'{stem}.mp4' if (out / f'{stem}.mp4').exists() else 'NOT VERIFIED: ' + (v.stderr.strip().splitlines() or ['download failed'])[-1][:200]
        rec['status'] = 'OK'
        report[stem] = rec
        print(f"{stem}: {rec['title']!r} · {rec['channel']} · {rec['upload_date']} · {mmss(rec['duration_s'] or 0)}"
              f"{' · VERTICAL' if rec['vertical'] else ''} · captions: {rec['captions']} · video: {rec.get('video', 'skipped')}")
    (out / 'sources.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(f"\nWrote {out / 'sources.json'}. Every row above is measured; anything NOT VERIFIED must be reported as such.")

# ── words ─────────────────────────────────────────────────────────────────────
def cmd_words(a):
    out = Path(a.dir); stems = sorted({p.name.split('.')[0] for p in list(out.glob('S*.mp4')) + list(out.glob('S*.vtt'))})
    for stem in stems:
        if a.file and stem != a.file: continue
        vtts = sorted(out.glob(f'{stem}*.vtt')); words, method = [], ''
        if vtts and not a.whisper:
            words, method = vtt_words(vtts[0])
        if not words or a.whisper:
            vid = out / f'{stem}.mp4'
            try:
                from faster_whisper import WhisperModel
            except ImportError:
                print(f'{stem}: NOT VERIFIED — no captions and faster-whisper is not installed (pip install faster-whisper)'); continue
            if not vid.exists():
                print(f'{stem}: NOT VERIFIED — no captions and no downloaded video to transcribe'); continue
            model = WhisperModel(a.model, device='auto', compute_type='int8')
            segs, _ = model.transcribe(str(vid), word_timestamps=True, vad_filter=True)
            words = [{'w': w.word.strip(), 'start': round(w.start * 1000), 'end': round(w.end * 1000)} for s in segs for w in (s.words or [])]
            method = f'whisper-{a.model}'
        (out / f'{stem}.words.json').write_text(json.dumps({'method': method, 'words': words}), encoding='utf-8')
        lines, cur = [], []
        for w in words:
            if cur and (w['start'] - cur[-1]['end'] > 700 or len(cur) >= 14):
                lines.append(cur); cur = []
            cur.append(w)
        if cur: lines.append(cur)
        (out / f'{stem}.transcript.txt').write_text('\n'.join(f"[{mmss(l[0]['start']/1000)}–{mmss(l[-1]['end']/1000)}] " + ' '.join(x['w'] for x in l) for l in lines), encoding='utf-8')
        print(f'{stem}: {len(words)} words · {method} → {stem}.words.json, {stem}.transcript.txt')
    print('\nwhisper and caption text are navigation aids: quote only words you have checked by ear or against the caption track.')

# ── find ──────────────────────────────────────────────────────────────────────
def _norm(w): return re.sub(r"[^a-z0-9']", '', w.lower().replace('\u2019', "'"))

def cmd_find(a):
    out = Path(a.dir); target = [_norm(w) for w in a.phrase.split() if _norm(w)]; hits = 0
    for f in sorted(out.glob('S*.words.json')):
        stem = f.name.split('.')[0]
        if a.file and stem != a.file: continue
        d = json.loads(f.read_text()); ws = d['words']; toks = [_norm(w['w']) for w in ws]
        for i in range(len(toks) - len(target) + 1):
            window = toks[i:i + len(target)]
            same = sum(x == y for x, y in zip(window, target))
            if same >= max(1, len(target) - max(1, len(target) // 5)):
                a_ms = ws[i]['start']; z_ms = ws[i + len(target) - 1]['end']
                ctx = ' '.join(w['w'] for w in ws[max(0, i - 4):i + len(target) + 4])
                print(f"{stem}.mp4  first word {mmss(a_ms/1000)}  last word ends {mmss(z_ms/1000)}  "
                      f"→ suggested IN {tc(max(0, a_ms - 150))}  OUT {tc(z_ms + 250)}  [{d['method']}, {same}/{len(target)} words]\n    …{ctx}…")
                hits += 1
    if not hits: print('NOT FOUND in any words.json: do not guess a time; listen, or transcribe with --whisper.')
    else: print('\nCheck each IN/OUT by ear and on the contact sheet (speaker on screen IN→OUT) before using it.')

# ── frames ────────────────────────────────────────────────────────────────────
def cmd_frames(a):
    from PIL import Image, ImageDraw
    out = Path(a.dir); sheets = out / 'frames'; sheets.mkdir(exist_ok=True)
    vids = [out / f'{a.file}.mp4'] if a.file else sorted(out.glob('S*.mp4')) + sorted(out.glob('B*.mp4'))
    for vid in vids:
        if not vid.exists(): print(vid.name, 'NOT FOUND'); continue
        dur = duration(vid)
        t0, t1 = a.start or 0, min(a.end or dur, dur); times = []; t = t0
        while t < t1: times.append(t); t += a.every
        thumbs = []
        for t in times:
            r = subprocess.run([FF(), '-v', 'error', '-ss', f'{t:.3f}', '-i', str(vid), '-frames:v', '1', '-vf', 'scale=320:-2',
                                '-f', 'image2pipe', '-vcodec', 'png', '-'], capture_output=True)
            if r.stdout:
                import io
                im = Image.open(io.BytesIO(r.stdout)).convert('RGB'); d = ImageDraw.Draw(im)
                label = mmss(t); d.rectangle([0, 0, 8 + 7 * len(label), 16], fill=(0, 0, 0)); d.text((4, 2), label, fill=(255, 255, 0))
                thumbs.append(im)
        per = a.cols * a.rows
        for p in range(0, len(thumbs), per):
            chunk = thumbs[p:p + per]; w, h = chunk[0].size
            sheet = Image.new('RGB', (w * a.cols, h * ((len(chunk) - 1) // a.cols + 1)), (20, 20, 20))
            for k, im in enumerate(chunk): sheet.paste(im, ((k % a.cols) * w, (k // a.cols) * h))
            name = sheets / f'{vid.stem}_{int(times[p])}-{int(times[min(p + per, len(times)) - 1])}s.jpg'
            sheet.save(name, quality=85); print(name)
    print('\nOpen every sheet and LOOK: who is on screen, reporters/anchors, lower thirds over faces, logos, vertical video, '
          'minors. Record banned intervals in banned.json: {"S05.mp4": [[0, 51, "studio + reporter"]]}')

# ── people: one person, one picture ──────────────────────────────────────────
def _dhash(im):
    g = im.convert('L').resize((17, 16)); px = list(g.getdata())
    return [px[r * 17 + c] > px[r * 17 + c + 1] for r in range(16) for c in range(16)]

def cmd_people(a):
    """Grab every person's photo exactly as the editor will, put them on one labelled sheet,
    and fail when two people get the same picture or a photo shows no single face."""
    import io
    from PIL import Image, ImageDraw
    out = Path(a.dir); out.mkdir(parents=True, exist_ok=True); pdir = out / 'people'; pdir.mkdir(exist_ok=True)
    sheet = read_sheet(a.sheet); local = {yt_id(r['link']): out / r['file'] for r in sheet['S']}
    y = _ytdlp(); shots, bad, warn = [], [], []
    for r in [x for x in sheet['B'] if x['person']]:
        dest = pdir / f"{r['file'].rsplit('.', 1)[0]}.jpg"; vid = local.get(yt_id(r['link']))
        if r['window'] and vid and vid.exists():
            subprocess.run([FF(), '-v', 'error', '-y', '-ss', f"{r['window'][0]:.3f}", '-i', str(vid), '-frames:v', '1', str(dest)])
        elif r['window'] and y:
            tmp = pdir / f"{dest.stem}-clip.mp4"
            subprocess.run(y + ['--ffmpeg-location', FF(), '--download-sections', f"*{r['window'][0]}-{r['window'][0] + 2}", '-f', 'b[height<=720]/bv*+ba/b',
                                '--merge-output-format', 'mp4', '-o', str(tmp), r['link']], capture_output=True)
            subprocess.run([FF(), '-v', 'error', '-y', '-i', str(tmp), '-frames:v', '1', str(dest)]); tmp.unlink(missing_ok=True)
        elif y:
            subprocess.run(y + ['--ffmpeg-location', FF(), '--skip-download', '--write-thumbnail', '--convert-thumbnails', 'jpg',
                                '-o', str(pdir / dest.stem), r['link']], capture_output=True)
        if not dest.exists():
            bad.append(f"{r['file']} ({r['person']}): NOT VERIFIED — could not get the picture (download the S file with fetch, or install yt-dlp)"); continue
        im = Image.open(dest).convert('RGB'); faces = None
        try:
            import cv2, numpy as np
            cas = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
            if not cas.empty():
                g = cv2.cvtColor(np.array(im), cv2.COLOR_RGB2GRAY)
                faces = len(cas.detectMultiScale(g, 1.1, 6, minSize=(max(24, g.shape[0] // 12),) * 2))
        except Exception:
            faces = None                                    # no face counting: the labelled sheet is still made
        shots.append((r, im, _dhash(im), faces))
    for i, (r, im, h, faces) in enumerate(shots):
        if faces == 0: warn.append(f"{r['file']} ({r['person']}): no face found — is this a graphic, a building or a lower third?")
        elif faces and faces > 1: bad.append(f"{r['file']} ({r['person']}): {faces} faces — a group photo or collage is not one person's photo")
        for q, _, h2, _ in shots[i + 1:]:
            if q['person'].casefold() != r['person'].casefold() and sum(x != y for x, y in zip(h, h2)) <= 20:
                bad.append(f"{r['file']} ({r['person']}) and {q['file']} ({q['person']}): the same picture")
    if not shots and not bad:
        bad.append('no person rows found (P rows, or B .jpg rows whose description starts "FOR PEOPLE: Name —"): nothing was checked')
    if shots:
        w = 320; tiles = []
        for r, im, _, faces in shots:
            t = im.copy(); t.thumbnail((w, 240)); c = Image.new('RGB', (w, 270), (20, 20, 20)); c.paste(t, ((w - t.width) // 2, 0))
            d = ImageDraw.Draw(c); d.text((6, 246), f"{r['file']} {r['person']}  faces: {'?' if faces is None else faces}", fill=(255, 255, 0)); tiles.append(c)
        cols = 4; board = Image.new('RGB', (w * cols, 270 * ((len(tiles) - 1) // cols + 1)), (0, 0, 0))
        for k, t in enumerate(tiles): board.paste(t, ((k % cols) * w, (k // cols) * 270))
        board.save(out / 'people_sheet.jpg', quality=88); print(f"Wrote {out / 'people_sheet.jpg'}: OPEN IT and confirm each picture is that person, alone.")
    for x in warn: print('warn:', x)
    print('PASS' if not bad else f'FAIL ({len(bad)})\n- ' + '\n- '.join(bad)); sys.exit(1 if bad else 0)

# ── checks ────────────────────────────────────────────────────────────────────
def cmd_check_sheet(a):
    s = read_sheet(a.sheet); bad = list(s['issues']); seen = {}
    for r in s['S'] + s['B']:
        if not r['link'].startswith('http'): bad.append(f"{r['file']}: no link")
        if r['link'] and 'youtube' not in r['link'] and 'youtu.be' not in r['link']: bad.append(f"{r['file']}: not a YouTube link")
        if r['file'].startswith('B') and not r['window']: bad.append(f"{r['file']}: B row needs a real window like 0:43–0:58")
        if r['file'].lower().endswith(('.jpg', '.png')) and r['window'] and r['window'][1] - r['window'][0] > 2:
            bad.append(f"{r['file']}: a photo frame row needs a one-second window")
        seen.setdefault(r['file'], []).append(r['line'])
    for f, lines in seen.items():
        if len(lines) > 1: bad.append(f'{f}: listed twice (lines {lines})')
    people = [r for r in s['B'] if r['person']]
    for i, r in enumerate(people):
        for q in people[i + 1:]:
            if r['person'].casefold() == q['person'].casefold() or yt_id(r['link']) != yt_id(q['link']): continue
            if not r['window'] and not q['window']:
                bad.append(f"{r['file']} ({r['person']}) and {q['file']} ({q['person']}): the same video's thumbnail — two people cannot share one picture")
            elif r['window'] and q['window'] and abs(r['window'][0] - q['window'][0]) < 20:
                bad.append(f"{r['file']} ({r['person']}) and {q['file']} ({q['person']}): frames {abs(r['window'][0] - q['window'][0]):.0f} s apart in the same video — "
                           f"almost always the same group photo or graphic. Find each person's own photo, then run `people` to prove it")
    s_by_id = {yt_id(r['link']): r['file'] for r in s['S']}
    for r in s['B']:
        if r['window'] and yt_id(r['link']) in s_by_id:
            print(f"note: {r['file']} is cut from {s_by_id[yt_id(r['link'])]} {mmss(r['window'][0])}–{mmss(r['window'][1])} "
                  f"(never place it next to that same stretch of {s_by_id[yt_id(r['link'])]})")
    print(f"\n{len(s['S'])} videos · {len(s['B'])} clips/frames")
    print('PASS' if not bad else 'FAIL\n- ' + '\n- '.join(bad))

def parse_editor_script(text: str) -> list[dict]:
    beats = []
    for block in re.split(r'(?m)^(?=Beat:\s*\d+\s*$)', text):
        m = re.match(r'Beat:\s*(\d+)', block)
        if not m: continue
        g = lambda k: (re.search(rf'(?m)^{k}:\s*(.*)$', block) or [None, ''])[1].strip()
        b = {'label': m.group(1), 'type': g('Type'), 'file': g('Full source'), 'clock': g('Narration clock'),
             'in': g('Source in'), 'out': g('Source out'), 'speaker': g('Speaker'), 'caption': g('On-screen caption')}
        for k in ('in', 'out'):
            t = re.search(_TC, b[k]); b[k + '_ms'] = to_ms(t.group(0)) if t else None
        b['bite'] = b['type'].upper().startswith('DOC')
        if b['bite']:
            p = re.search(rf'PAUSED at ({_TC})', b['clock']); b['pause_ms'] = to_ms(p.group(1)) if p else None
        else:
            r = re.findall(_TC, b['clock']); b['n_in'], b['n_out'] = (to_ms(r[0]), to_ms(r[1])) if len(r) == 2 else (None, None)
        beats.append(b)
    return beats

def cmd_check_script(a):
    text = Path(a.script).read_text(encoding='utf-8'); beats = parse_editor_script(text); bad, warn = [], []
    if re.search(r'(?m)^Source in:.*-->', text): bad.append('Source in and Source out must be two separate lines (run `convert` first)')
    if not beats: sys.exit('FAIL: no "Beat: 001" blocks found')
    cues = read_srt(a.srt); srt_end = cues[-1]['end'] if cues else 0
    sheet = read_sheet(a.sheet) if a.sheet else None
    files = {r['file'] for r in sheet['S'] + sheet['B']} if sheet else set()
    origin = {}
    if sheet:
        s_by_id = {yt_id(r['link']): r['file'] for r in sheet['S']}
        for r in sheet['B']:
            if r['window'] and yt_id(r['link']) in s_by_id: origin[r['file']] = (s_by_id[yt_id(r['link'])], r['window'][0] * 1000)
    lengths = {}
    if a.sources and Path(a.sources).exists():
        for rec in json.loads(Path(a.sources).read_text()).values():
            if rec.get('duration_s'): lengths[rec['file']] = rec['duration_s'] * 1000
    banned = json.loads(Path(a.banned).read_text()) if a.banned and Path(a.banned).exists() else {}
    # clock, durations, files
    clock = 0; master = 0; placed = []
    for i, b in enumerate(beats):
        L = f"Beat {b['label']}"
        if b['in_ms'] is None or b['out_ms'] is None or b['out_ms'] <= b['in_ms']: bad.append(f'{L}: bad Source in/out'); continue
        d = b['out_ms'] - b['in_ms']
        if sheet and b['file'] not in files: bad.append(f"{L}: {b['file']} is not in the footage sheet")
        if b['file'] in lengths and b['out_ms'] > lengths[b['file']] + 40: bad.append(f"{L}: Source out {mmss(b['out_ms']/1000)} is past the end of {b['file']}")
        if b['bite']:
            if b['pause_ms'] != clock: bad.append(f"{L}: PAUSED at {tc(b['pause_ms'] or 0)} but the narration clock is at {tc(clock)}")
            if not b['speaker']: warn.append(f'{L}: sound bite has no Speaker')
        else:
            if clock == 0 and cues and b['n_in'] is not None and b['n_in'] <= cues[0]['start']: clock = b['n_in']   # narration may start a beat after 0
            if b['n_in'] != clock: bad.append(f"{L}: RESUMES at {tc(b['n_in'] or 0)} but the clock is at {tc(clock)} (gap or overlap)")
            if b['n_out'] is not None and abs((b['n_out'] - b['n_in']) - d) > 40:
                bad.append(f"{L}: picture {d} ms ≠ narration {b['n_out'] - b['n_in']} ms")
            clock = b['n_out'] or clock
        f, off = origin.get(b['file'], (b['file'], 0))
        placed.append((L, f, b['in_ms'] + off, b['out_ms'] + off, master, master + d, b))
        for s0, e0, why in banned.get(f, []):
            if not b['bite'] and b['in_ms'] + off < e0 * 1000 and b['out_ms'] + off > s0 * 1000:
                bad.append(f"{L}: {b['file']} {mmss(b['in_ms']/1000)}–{mmss(b['out_ms']/1000)} is banned footage ({why})")
        master += d
    if abs(clock - srt_end) > 300: bad.append(f'narration clock ends at {tc(clock)} but the SRT ends at {tc(srt_end)}')
    # cold open: 2-3 bites before the first narration
    first_vo = next((i for i, b in enumerate(beats) if not b['bite']), 0)
    if not 2 <= first_vo <= 3: bad.append(f'cold open has {first_vo} sound bites before the narrator (must be 2 or 3)')
    for b in beats[:first_vo]:
        if b['caption'] and b['caption'].lower() not in ('none', ''): warn.append(f"Beat {b['label']}: on-screen text in the cold open")
    # repeats
    for i, (l1, f1, a1, z1, m1a, m1z, b1) in enumerate(placed):
        for l2, f2, a2, z2, m2a, m2z, b2 in placed[i + 1:]:
            if f1 != f2 or not (a1 < z2 and a2 < z1): continue
            if (a1, z1) == (a2, z2): bad.append(f'{l1} and {l2}: exactly the same frames of {f1} (the editor refuses this)')
            elif m2a - m1z < 20000 and not (b1['bite'] or b2['bite']):
                bad.append(f'{l1} and {l2}: same footage of {f1} again within 20 s')
            elif m2a - m1z < 20000:
                warn.append(f'{l1} and {l2}: same footage of {f1} within 20 s (a pre-frame next to its own bite is fine)')
    print(f'{len(beats)} beats · {sum(b["bite"] for b in beats)} sound bites · narration clock ends {tc(clock)} · picture {mmss(master/1000)}')
    for w in warn: print('warn:', w)
    print('PASS' if not bad else f'FAIL ({len(bad)})\n- ' + '\n- '.join(bad))
    sys.exit(1 if bad else 0)

# ── convert to the editor's one-field-per-line format ─────────────────────────
def cmd_convert(a):
    code = Path(a.script).read_text(encoding='utf-8')
    if '```text' in code: code = code.split('```text', 1)[1].split('```', 1)[0]
    cues = read_srt(a.srt) if a.srt else []
    blocks = re.split(r'(?m)^(?=Beat:\s*\d+\s*$)', code); head = blocks[0].strip(); out = []; n = 0
    def f(b, name):
        m = re.search(r'(?m)^' + re.escape(name) + r':\s*(.*)$', b); return m.group(1).strip() if m else ''
    for b in blocks[1:]:
        typ = f(b, 'Type'); src = f(b, 'Full source')
        mi = re.findall(_TC, f(b, 'Master in') or f(b, 'Master timeline'))
        ranges = re.findall(rf'({_TC})\s*-->\s*(?:Source out:\s*)?({_TC})', f(b, 'Source in')) or [(f(b, 'Source in'), f(b, 'Source out'))]
        master = to_ms(mi[0]) if mi else 0
        for k, (x, z) in enumerate(ranges):
            n += 1; d = to_ms(z) - to_ms(x); L = [f'Beat: {n:03d}', f'Type: {typ}']
            bite = typ.upper().startswith('DOC')
            L.append(f'Master timeline: {tc(master)} --> {tc(master + d)}' + (f' (Duration: {tc(d)})' if bite else ''))
            if bite:
                p = re.search(rf'PAUSED at ({_TC})', f(b, 'Narration clock')).group(1)
                L += [f'Narration clock: PAUSED at {p}', 'Narration state: PAUSED (Suspended for duration of bite)', f"Speaker: {f(b, 'Speaker')}", f'Duration: {tc(d)}']
            else:
                ni, no = re.findall(_TC, f(b, 'Narration clock'))[:2]
                words = ' '.join(c['text'] for c in cues if to_ms(ni) - 50 <= c['start'] < to_ms(no) - 50)
                L += [f'Narration clock: RESUMES at {ni} --> {no}', 'Narration state: RESUMING'] + ([f'Spoken narration: "{words}"'] if cues else [])
            L += [f'Full source: {src}', f'Source in: {x}', f'Source out: {z}', f"Footage audio: {f(b, 'Footage audio')}",
                  f"Cut action: {f(b, 'Cut action') if k == 0 else 'CONTINUOUS (same file, same speech, internal cut)'}",
                  f"Visual direction: {f(b, 'Visual direction')}", f"On-screen caption: {f(b, 'On-screen caption') if k == 0 else 'None'}"]
            out.append('\n'.join(L)); master += d
    Path(a.out).write_text(head + '\n\n\n' + ('\n' + '-' * 80 + '\n').join(out) + '\n', encoding='utf-8')
    print(f'{n} beats written to {a.out} (one field per line; multi-range beats split into back-to-back beats).')

def write_report(out: Path) -> Path:
    """One Markdown file with every measured result, for agents that take only .md uploads:
    sources, timed transcripts, logs and the list of contact-sheet pictures."""
    L = [f'# Research pack — {out.resolve().name}', '',
         'Made on the producer\'s PC by storyroom_kit.py. Every time below is measured (captions or whisper), not estimated.', '']
    src = out / 'sources.json'
    if src.exists():
        L += ['## Sources (yt-dlp)', '', '| File | Title | Channel | Date | Length | Vertical | Captions | Video | Status |', '|---|---|---|---|---|---|---|---|---|']
        for r in json.loads(src.read_text(encoding='utf-8')).values():
            L.append(f"| {r.get('file')} | {r.get('title', '')} | {r.get('channel', '')} | {r.get('upload_date', '')} | "
                     f"{mmss(r['duration_s']) if r.get('duration_s') else ''} | {r.get('vertical', '')} | {r.get('captions', '')} | {r.get('video', '')} | {r.get('status', '')} |")
        L.append('')
    for name in ('people', 'check-sheet', 'fetch', 'words'):
        f = out / 'logs' / f'{name}.log'
        if f.exists(): L += [f'## {name} output', '', '```text', f.read_text(encoding='utf-8').strip(), '```', '']
    pics = sorted((out / 'frames').glob('*.jpg')) + ([out / 'people_sheet.jpg'] if (out / 'people_sheet.jpg').exists() else [])
    if pics:
        L += ['## Pictures to look at (upload these JPGs with this file)', '',
              'Each contact sheet shows one frame every few seconds; the time is printed in the top-left of every frame.', '']
        L += [f'- {p.name}' for p in pics] + ['']
    for t in sorted(out.glob('S*.transcript.txt')):
        L += [f'## Timed transcript — {t.name.split(".")[0]}.mp4', '', '```text', t.read_text(encoding='utf-8').strip(), '```', '']
    dest = out.parent / f'{out.name}_research_pack.md'
    dest.write_text('\n'.join(L), encoding='utf-8'); return dest

def cmd_pack(a):
    """Zip everything an agent needs to read (sources.json, captions, words, transcripts,
    contact sheets, people sheet, banned.json, logs), without the big video files."""
    import zipfile
    out = Path(a.dir); dest = Path(a.zip or (out.name + '_for_agent.zip')); n = 0
    with zipfile.ZipFile(dest, 'w', zipfile.ZIP_DEFLATED) as z:
        for f in sorted(out.rglob('*')):
            if f.is_file() and f.suffix.lower() not in ('.mp4', '.m4a', '.webm', '.mkv', '.part'):
                z.write(f, f.relative_to(out.parent)); n += 1
    md = write_report(out)
    pics = out.parent / f'{out.name}_pictures'; pics.mkdir(exist_ok=True)
    for f in list((out / 'frames').glob('*.jpg')) + [out / 'people_sheet.jpg']:
        if f.exists(): shutil.copy(f, pics / f.name)
    print(f'{dest}: {n} files, {dest.stat().st_size / 1e6:.1f} MB (for agents that take a zip).')
    print(f'{md}: everything measured, as one Markdown file.')
    print(f'{pics}{chr(92) if sys.platform == "win32" else "/"}: {len(list(pics.glob("*.jpg")))} pictures. For agents that take no zip: upload the .md file and these JPGs.')

def cmd_run(a):
    """Everything for one footage sheet, in order: fetch, words, frames, people, check-sheet, pack."""
    import contextlib, io, types
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True); (out / 'logs').mkdir(exist_ok=True)
    steps = [('fetch', cmd_fetch, dict(sheet=a.sheet, out=a.out, no_video=False)),
             ('words', cmd_words, dict(dir=a.out, file=None, whisper=False, model='small')),
             ('frames', cmd_frames, dict(dir=a.out, file=None, every=a.every, start=None, end=None, cols=4, rows=5)),
             ('people', cmd_people, dict(sheet=a.sheet, dir=a.out)),
             ('check-sheet', cmd_check_sheet, dict(sheet=a.sheet))]
    for name, fn, kw in steps:
        print(f'\n=== {name} ==='); buf = io.StringIO()
        class Tee(io.TextIOBase):
            def write(self, t): sys.__stdout__.write(t); buf.write(t); return len(t)
        try:
            with contextlib.redirect_stdout(Tee()): fn(types.SimpleNamespace(**kw))
        except SystemExit as e:
            if e.code not in (0, 1, None): print(e.code); buf.write(str(e.code))
        (out / 'logs' / f'{name}.log').write_text(buf.getvalue(), encoding='utf-8')
    if not Path(a.sheet).resolve().parent == out.resolve():
        shutil.copy(a.sheet, out / Path(a.sheet).name)
    print('\n=== pack ==='); cmd_pack(types.SimpleNamespace(dir=a.out, zip=None))

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter); sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('fetch'); p.add_argument('sheet'); p.add_argument('--out', default='work'); p.add_argument('--no-video', action='store_true'); p.set_defaults(fn=cmd_fetch)
    p = sub.add_parser('words'); p.add_argument('dir'); p.add_argument('--file'); p.add_argument('--whisper', action='store_true'); p.add_argument('--model', default='small'); p.set_defaults(fn=cmd_words)
    p = sub.add_parser('find'); p.add_argument('dir'); p.add_argument('phrase'); p.add_argument('--file'); p.set_defaults(fn=cmd_find)
    p = sub.add_parser('frames'); p.add_argument('dir'); p.add_argument('--file'); p.add_argument('--every', type=float, default=2.0)
    p.add_argument('--start', type=float); p.add_argument('--end', type=float); p.add_argument('--cols', type=int, default=4); p.add_argument('--rows', type=int, default=5); p.set_defaults(fn=cmd_frames)
    p = sub.add_parser('people'); p.add_argument('sheet'); p.add_argument('--dir', default='work'); p.set_defaults(fn=cmd_people)
    p = sub.add_parser('check-sheet'); p.add_argument('sheet'); p.set_defaults(fn=cmd_check_sheet)
    p = sub.add_parser('check-script'); p.add_argument('script'); p.add_argument('--srt', required=True); p.add_argument('--sheet')
    p.add_argument('--sources'); p.add_argument('--banned'); p.set_defaults(fn=cmd_check_script)
    p = sub.add_parser('convert'); p.add_argument('script'); p.add_argument('--srt'); p.add_argument('--out', required=True); p.set_defaults(fn=cmd_convert)
    p = sub.add_parser('pack'); p.add_argument('dir'); p.add_argument('--zip'); p.set_defaults(fn=cmd_pack)
    p = sub.add_parser('run'); p.add_argument('sheet'); p.add_argument('--out', default='work'); p.add_argument('--every', type=float, default=2.0)
    p.set_defaults(fn=cmd_run)
    for sp in sub.choices.values():
        sp.add_argument('--cookies-from-browser', dest='cookies', help='chrome, edge or firefox: use your signed-in browser if YouTube asks to sign in')
        sp.add_argument('--editor', help='Storyroom editor folder, to use its yt-dlp')
        sp.add_argument('--cookies', dest='cookie_file', help='cookies.txt exported from a signed-in YouTube session')
    a = ap.parse_args()
    import os
    if a.cookies: COOKIES[:] = ['--cookies-from-browser', a.cookies]
    cf = a.cookie_file or os.environ.get('YTDLP_COOKIES') or next((str(c) for c in (Path('cookies.txt'), Path(a.__dict__.get('out') or a.__dict__.get('dir') or '.') / 'cookies.txt') if c.is_file()), None)
    if cf: COOKIES[:] = COOKIES + ['--cookies', cf]; print(f'Using cookies from {cf}')
    js = next((r for r in ('deno', 'node') if shutil.which(r)), None)
    if js and js != 'deno': COOKIES[:] = COOKIES + ['--js-runtimes', js]
    if a.editor: EDITOR[:] = [a.editor]
    a.fn(a)

if __name__ == '__main__':
    main()
