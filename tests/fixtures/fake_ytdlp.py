#!/usr/bin/env python3
"""A stand-in for yt-dlp used by the tests: same arguments, same output lines.

It never touches the network. It makes a real 2-second MP4 with ffmpeg so the rest of
the import (probe, fast start, registration) runs for real. The video id decides
what happens: PRIVATExxxx fails as a private video, BOTCHECKxxx asks for a sign-in,
FLAKYxxxxxx fails once with a network error then works, SLOWxxxxxxx downloads slowly
(for cancelling), anything else succeeds.
"""
import re, subprocess, sys, time
from pathlib import Path

args = sys.argv[1:]
if '--version' in args:
    print('2099.01.01-fake'); sys.exit(0)
def value(flag):
    return args[args.index(flag) + 1] if flag in args else None
url = args[-1]
m = re.search(r'v=([A-Za-z0-9_-]{11})', url)
if not m and 'unsupported' in url:
    print(f'ERROR: Unsupported URL: {url}', flush=True); sys.exit(1)
vid = m.group(1) if m else 'GENERICsite'
template = value('-o')
ffmpeg = value('--ffmpeg-location') or 'ffmpeg'
out = Path(template.replace('%(ext)s', 'mp4'))
out.parent.mkdir(parents=True, exist_ok=True)
import os
if os.environ.get('FAKE_YTDLP_LOG'):
    with open(os.environ['FAKE_YTDLP_LOG'], 'a') as log:
        log.write(vid + '\n')
if os.environ.get('FAKE_YTDLP_SECTIONS'):
    with open(os.environ['FAKE_YTDLP_SECTIONS'], 'a') as log:
        log.write(f"{vid} {value('--download-sections') or 'whole'}\n")
print(f'[youtube] Extracting URL: {url}', flush=True)
if '--write-thumbnail' in args and '--skip-download' in args:
    # Thumbnail only (a photo row with a YouTube link): a real JPG, as yt-dlp writes it.
    thumb = Path(template.replace('%(ext)s', 'jpg'))
    subprocess.run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-y', '-f', 'lavfi', '-i',
                    'testsrc2=s=1280x720', '-frames:v', '1', str(thumb)], check=True)
    print(f'SRTITLE Fake video {vid}', flush=True)
    sys.exit(0)
if vid.startswith('PRIVATE'):
    print(f"ERROR: [youtube] {vid}: Private video. Sign in if you've been granted access to this video", flush=True); sys.exit(1)
if vid.startswith('BOTCHECK'):
    print(f"ERROR: [youtube] {vid}: Sign in to confirm you’re not a bot. Use --cookies-from-browser", flush=True); sys.exit(1)
marker = out.parent / (vid + '.tried')
if vid.startswith('FLAKY') and not marker.exists():
    marker.write_text('1')
    print('ERROR: Unable to download webpage: <urlopen error timed out> (caused by URLError(timeout))', flush=True); sys.exit(1)
print(f'SRTITLE Test video {vid}', flush=True)
print('SRSIZE 3000000', flush=True)
steps, pause = (40, 0.25) if vid.startswith('SLOW') else (5, 0.02)
part = out.with_suffix('.f137.mp4.part'); part.write_bytes(b'')
for total in (2000000, 1000000):            # video, then audio: two downloads
    for i in range(1, steps + 1):
        print(f'SRPROGRESS {total * i // steps} {total} downloading', flush=True)
        time.sleep(pause)
part.unlink(missing_ok=True)
print(f'[Merger] Merging formats into "{out}"', flush=True)
subprocess.run([ffmpeg, '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=30', '-f', 'lavfi',
                '-i', 'sine=frequency=440', '-t', '2', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac',
                '-shortest', str(out)], check=True)
print(f'SRFILE {out}', flush=True)
