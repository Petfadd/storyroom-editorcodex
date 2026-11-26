"""YouTube Footage Importer: a Markdown sheet of links in, S01.mp4, S02.mp4 ... out.

Flow
  1. `parse_manifest` reads the uploaded .md sheet: every source ID (SRC-01, Source 2,
     S03 ...) with its YouTube link, in sheet order, plus what is wrong with the sheet
     (a source with no link, a link that is not YouTube, a source ID used twice).
  2. `DownloadJob` downloads each valid source in the background, a few at a time,
     with the chosen provider (yt-dlp by default). Every download goes to a temporary
     folder inside the project, is checked, and only then is handed to the editor's
     own import step, which saves it under the source's filename -- SRC-01 becomes
     S01.mp4 -- never under the YouTube title.
  3. State is written to `downloads/youtube.json` in the project after every change,
     so the page can show progress, a restart can resume, and nothing that failed is
     ever quietly skipped.

The numbering is the sheet's own: SRC-07 is S07.mp4 even when SRC-05 is missing, so
a production script that names S07.mp4 always gets the video the sheet calls SRC-07.

Providers are pluggable (`PROVIDERS`). yt-dlp is the default and the only one needed.
Apify is optional and is used only when configured. Downloading is the user's own
decision: this module records where each file came from but does not decide whether
it may be used.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
PRIVATE_LIBS = APP_DIR / '.cache' / 'yt-dlp'
STATE_NAME = 'youtube.json'

# Download states shown to the user.
WAITING, DOWNLOADING, RETRYING, COMPLETED, FAILED = 'waiting', 'downloading', 'retrying', 'completed', 'failed'
EXISTS, CANCELLED, INTERRUPTED = 'exists', 'cancelled', 'interrupted'
ACTIVE = (DOWNLOADING, RETRYING)
REDO = (FAILED, CANCELLED, INTERRUPTED)

DEFAULT_OPTIONS = {'provider': 'yt-dlp', 'quality': '1080', 'concurrency': 4, 'cookies_from_browser': '',
                   'attempts': 3, 'auto_start': True}
QUALITIES = ('720', '1080', 'best')
BROWSERS = ('', 'chrome', 'edge', 'firefox', 'brave', 'opera', 'safari', 'chromium', 'vivaldi')


# ============================================================================ sheet

_URL = re.compile(r'https?://[^\s<>()\[\]|"\'`]+', re.I)
_ID = re.compile(r'(?<![A-Za-z0-9])(?:SRC|SOURCE|SRCE)[\s\-_#:.]*0*(\d{1,3})(?![0-9])'
                 r'|(?<![A-Za-z0-9])S0*(\d{1,3})(?![0-9A-Za-z])', re.I)
_YT_ID = re.compile(r'^[A-Za-z0-9_-]{11}$')


def youtube_id(url):
    """The 11-character video id of a YouTube link, or None."""
    from urllib.parse import urlparse, parse_qs
    try:
        parts = urlparse(url.strip().rstrip('.,;'))
    except ValueError:
        return None
    host = (parts.hostname or '').lower()
    if host.startswith('www.'):
        host = host[4:]
    if host.startswith('m.'):
        host = host[2:]
    candidate = None
    if host == 'youtu.be':
        candidate = parts.path.strip('/').split('/')[0]
    elif host in ('youtube.com', 'music.youtube.com', 'youtube-nocookie.com'):
        if parts.path == '/watch':
            candidate = (parse_qs(parts.query).get('v') or [''])[0]
        else:
            bits = [b for b in parts.path.split('/') if b]
            if len(bits) >= 2 and bits[0] in ('shorts', 'live', 'embed', 'v', 'e'):
                candidate = bits[1]
    return candidate if candidate and _YT_ID.match(candidate) else None


def filename_for(number, width=2, kind='video'):
    if kind == 'photo':
        return f'P{number:0{width}d}.jpg'
    if kind == 'broll':
        return f'B{number:0{width}d}.mp4'
    return f'S{number:0{width}d}.mp4'


# B-roll and base pictures: B01, BR-02, BROLL 3, BASE-04 ... or a row that describes a
# place or thing (street, CCTV, house, apartment, police car ...) with a link. What the
# row says is kept with the file, so the visual plan puts it on the lines that need it.
_BROLL_ID = re.compile(r'(?<![A-Za-z0-9])(?:B[\s\-_]?ROLL|BROLL|BASE|BR|B)[\s\-_#:.]*0*(\d{1,3})(?![0-9A-Za-z])', re.I)
TOPIC_WORDS = (r'location|place|street|road|avenue|intersection|corner|block|neighbou?rhood|cctv|surveillance|camera|'
               r'doorbell|house|home|apartments?|complex|building|exterior|interior|outdoor|outside|environment|background|'
               r'police car|patrol car|squad car|cruiser|police|cars?|vehicle|truck|map|aerial|drone|skyline|bayou|river|'
               r'creek|park|playground|school|church|courthouse|court|jail|station|crime scene|scene|tape|evidence|'
               r'document|records?|vigil|memorial|candles|search|b-?roll|establishing|wide shot|night|sunset|base')
_TOPIC = re.compile(r'(?<![A-Za-z])(?:' + TOPIC_WORDS + r')(?![A-Za-z])', re.I)
_RANGE = re.compile(r'(?<![\d:])(\d{1,2}(?::\d{2}){1,2}|\d+(?:\.\d+)?s)\s*(?:-|–|—|to)\s*(\d{1,2}(?::\d{2}){1,2}|\d+(?:\.\d+)?s)(?![\d:])')


# One timestamp on its own (00:00:38, 1:15): on a picture row, the frame to take.
_ONE_TIME = re.compile(r'(?<![\d:.])(\d{1,2}(?::\d{2}){1,2}(?:[.,]\d+)?)(?![\d:])')


def _picture_window(url_free, window):
    """A picture row's window: its range, or else a single timestamp as a one-second window.

    A photo row like "| P01 | Patricia May | ... | 00:00:38 |" means "the frame at 0:38".
    Without this, every photo taken from the same video got that video's thumbnail.
    """
    if window is not None:
        return window
    stripped = _RANGE.sub(' ', url_free)
    m = _ONE_TIME.search(stripped)
    if not m:
        return None
    at = _seconds(m.group(1).replace(',', '.'))
    return (at, at + 1.0)


# A title written before a name ("Director Brendan Kelly") is a role, not part of the
# name: as a name it made "Director" count as his first name and "Brendan Kelly" alone
# never match.
TITLE_WORDS = ('director', 'councilman', 'councilwoman', 'councilmember', 'alderman', 'chief', 'sheriff',
               'deputy', 'officer', 'detective', 'det', 'sergeant', 'sgt', 'lieutenant', 'lt', 'captain', 'capt',
               'agent', 'trooper', 'judge', 'justice', 'mayor', 'pastor', 'reverend', 'rev', 'bishop', 'dr', 'doctor',
               'prosecutor', 'attorney', 'senator', 'governor', 'commissioner', 'superintendent', 'investigator',
               'coroner', 'president', 'professor', 'prof', 'state', 'district')


def _split_title(name, role):
    """(name, role) with leading title words moved from the name to the role."""
    words = name.split()
    taken = []
    while len(words) > 2 and words[0].rstrip('.').casefold() in TITLE_WORDS:
        taken.append(words.pop(0))
    if not taken:
        return name, role
    title = ' '.join(taken)
    title = title[:1].upper() + title[1:]
    return ' '.join(words), role or title


def _seconds(text):
    text = text.strip().lower()
    if text.endswith('s'):
        return float(text[:-1])
    total = 0.0
    for part in text.split(':'):
        total = total * 60 + float(part)
    return total


def _url_time(url):
    """The start time a YouTube link points at (&t=43s, ?t=1m5s, #t=43), in seconds, or None."""
    m = re.search(r'[?&#]t=(?:(\d+)h)?(?:(\d+)m)?(\d+)s?', url)
    if not m:
        return None
    return int(m.group(1) or 0) * 3600 + int(m.group(2) or 0) * 60 + int(m.group(3))


def _broll_details(url_free):
    """(description, window) of a b-roll row: what it shows, and an optional source window."""
    window = None
    m = _RANGE.search(url_free)
    if m:
        a, b = _seconds(m.group(1)), _seconds(m.group(2))
        if b > a:
            window = (a, b)
    cells = [c.strip() for c in url_free.strip().strip('|').split('|')] if '|' in url_free else [url_free]
    parts = []
    for c in cells:
        t = _ANY_FILE.sub(' ', c)
        t = _BROLL_ID.sub(' ', t)
        t = _PHOTO_ID.sub(' ', t)
        t = _RANGE.sub(' ', t)
        t = re.sub(r'[*_`#]+|^\s*[-–—:]+|[-–—:]+\s*$', ' ', t)
        t = ' '.join(t.split())
        if t and not re.fullmatch(r'(?i)(?:b-?roll|base|link|file|source|what it shows|description|footage|photo|image)', t):
            parts.append(t)
    return ' · '.join(parts)[:300], window


# Photo rows: P01, P-02, PHOTO 3, PIC-04, IMG05 ... or any image filename. The person's
# name and role can be given on the same row; the photo then shows whenever the
# narration names them (the People list is filled from the sheet).
_PHOTO_ID = re.compile(r'(?<![A-Za-z0-9])(?:PHOTO|PIC|IMG|IMAGE|P)[\s\-_#:.]*0*(\d{1,3})(?![0-9A-Za-z])', re.I)
IMAGE_EXT = ('jpg', 'jpeg', 'png', 'webp', 'gif', 'bmp', 'tif', 'tiff', 'heic', 'heif', 'avif', 'jfif')
VIDEO_EXT = ('mp4', 'mov', 'mkv', 'webm', 'm4v', 'avi', 'wmv', 'flv', 'mpg', 'mpeg', 'ts', '3gp')
ROLE_WORDS = {
    'victim': 'Victim', 'suspect': 'Suspect', 'accused': 'Suspect', 'defendant': 'Suspect', 'killer': 'Suspect',
    'mother': 'Mother', 'mom': 'Mother', 'mum': 'Mother', 'mommy': 'Mother',
    'father': 'Father', 'dad': 'Father', 'daddy': 'Father',
    'stepfather': 'Stepfather', 'stepmother': 'Stepmother',
    'brother': 'Brother', 'sister': 'Sister', 'son': 'Son', 'daughter': 'Daughter',
    'grandmother': 'Grandmother', 'grandma': 'Grandmother', 'grandfather': 'Grandfather', 'grandpa': 'Grandfather',
    'aunt': 'Aunt', 'uncle': 'Uncle', 'cousin': 'Cousin', 'wife': 'Wife', 'husband': 'Husband',
    'boyfriend': 'Boyfriend', 'girlfriend': 'Girlfriend', 'survivor': 'Survivor',
    'family member': 'Family member', 'relative': 'Relative', 'witness': 'Witness', 'friend': 'Friend',
}
_ROLE = re.compile(r'(?<![A-Za-z])(' + '|'.join(sorted(ROLE_WORDS, key=len, reverse=True)) + r')(?![A-Za-z])', re.I)
_ANY_FILE = re.compile(r'(?<![\w\-.])([\w\-().]+\.(?:' + '|'.join(IMAGE_EXT + VIDEO_EXT) + r'))(?![\w])', re.I)


def _photo_details(line, url_free):
    """(name, role) written on a photo row. Either may be ''."""
    cells = [c.strip() for c in url_free.strip().strip('|').split('|')] if '|' in url_free else [url_free]
    role = ''
    for c in cells:
        m = _ROLE.search(c)
        if m:
            role = ROLE_WORDS[m.group(1).lower()]
            break
    name = ''
    for c in cells:
        text = _ANY_FILE.sub(' ', c)
        text = _PHOTO_ID.sub(' ', text)
        text = _ID.sub(' ', text)
        if role:
            text = _ROLE.sub(' ', text, count=1)
        text = re.sub(r'(?i)^\s*(?:photo|picture|image|pic)\s+of\s+', '', text)
        text = re.sub(r"[\[\]()*_`#:;,\-\u2013\u2014]+", ' ', text)
        text = re.sub(r"(?i)\b(?:the|photo|picture|image|pic|link|file)\b", ' ', text)
        words = text.split()
        # A person's name: capitalised words, none of them a place or thing ("Apartment door" is not a name).
        if words and len(words) <= 5 and all(re.match(r"[A-Z][A-Za-z.'\u2019-]*$", w) for w in words) \
                and not _TOPIC.search(' '.join(words)):
            name = ' '.join(words)
            break
    return _split_title(name, role) if name else (name, role)


_FOR_PEOPLE = re.compile(r"(?i)\bFOR\s+PEOPLE\s*:\s*([A-Z][A-Za-z.'\u2019-]*(?:\s+[A-Z][A-Za-z.'\u2019-]*){0,4})")


def _frame_person(line, url_free):
    """(name, role) a frame row gives its person, or ('', '') when it names nobody."""
    text = _URL.sub(' ', line)
    m = _FOR_PEOPLE.search(text)
    if re.search(r"(?i)victim['’]s friend|friend of (?:the )?victim|family friend", url_free):
        role = 'Friend'
    elif re.search(r'(?i)\bsurvivor\b', url_free):
        role = 'Survivor'
    elif re.search(r'(?i)\badult family member\b|\bfamily relative\b', url_free):
        role = 'Family member'
    else:
        role_m = _ROLE.search(url_free)
        role = ROLE_WORDS[role_m.group(1).lower()] if role_m else ''
    if m:
        return _split_title(' '.join(m.group(1).split()), role)
    if role:
        name, role = _photo_details(line, url_free)
        return name, role
    return '', ''


def _source_number(text):
    """First source ID in a piece of text (URLs removed), as (label, number)."""
    for match in _ID.finditer(text):
        number = int(match.group(1) or match.group(2))
        if number < 1:
            continue
        return match.group(0).strip(), number
    return None




def _photo_identity(text):
    """(label, number, filename) of a photo row with its links removed, or None."""
    files = [f for f in _ANY_FILE.findall(text) if f.rsplit('.', 1)[-1].lower() in IMAGE_EXT]
    named = files[0] if files else None
    m = _PHOTO_ID.search(_ANY_FILE.sub(' ', text))
    if m and int(m.group(1)) > 0:
        return m.group(0).strip(), int(m.group(1)), named
    if named:
        m = re.fullmatch(r'(?:PHOTO|PIC|IMG|IMAGE|P)[\-_]?0*(\d{1,3})\.\w+', named, re.I)
        return named.rsplit('.', 1)[0], (int(m.group(1)) if m and int(m.group(1)) > 0 else None), named
    return None


def _identity(text):
    """(label, number, filename) for one line with its links removed, or None.

    A filename written in the sheet ("S01.mp4", "Bayou_drone.mp4") is used exactly as
    written. Otherwise the file is named from the source number: SRC-01 -> S01.mp4.
    """
    files = [f for f in _ANY_FILE.findall(text) if f.rsplit('.', 1)[-1].lower() in VIDEO_EXT]
    named = files[0] if files else None
    found = _source_number(_ANY_FILE.sub(' ', text))
    if not found and named:
        match = re.fullmatch(r'S0*(\d{1,3})\.\w+', named, re.I)
        if match and int(match.group(1)) > 0:
            found = (named.rsplit('.', 1)[0], int(match.group(1)))
    if found:
        return found[0], found[1], named
    if named:
        return named, None, named
    return None


def parse_manifest(text):
    """Read a footage sheet. Returns {'entries', 'issues', 'counts'}.

    Accepts the layouts people actually write: a Markdown table (one row per source),
    a list ("- SRC-01: https://..."), or a heading per source followed by its link.
    A row is matched by the source ID (or the filename it gives) and the link on the
    same line; a source on its own line takes the next link below it, before the next
    source.
    """
    entries, issues = [], []
    pending = None          # (label, number, filename, line, kind, person, role) seen without a link yet
    in_fence = False
    lines = (text or '').replace('\r\n', '\n').replace('\r', '\n').split('\n')

    def missing(item):
        issues.append({'kind': 'missing_link', 'line': item[3], 'text': f'{item[0]} (line {item[3]}) has no link.',
                       'number': item[1], 'named': item[2], 'media': item[4]})

    def broll(label, number, named, url_free, raw_line=''):
        description, window = _broll_details(url_free)
        person = role = ''
        if named and named.rsplit('.', 1)[-1].lower() in IMAGE_EXT:
            window = _picture_window(url_free, window)
            # A frame row (B15.jpg + a one-second window) that names a person is that
            # person's photo: it goes into People on screen like a P row would, so the
            # photo pops up when the narration says their name. Only when the row says
            # so ("FOR PEOPLE: Name" or a role such as Victim), never from a place name.
            person, role = _frame_person(raw_line, url_free)
        return (label, number, named, 'broll', person, role if person else '', description, window)

    def identify(url_free, raw_line, urls):
        """(label, number, filename, kind, person, role, description, window) for a line, or None."""
        # Markdown table rows are typed by the *first* column, never by an S##
        # parenthetical later in a B-roll or person-reference description.
        cells = [c.strip() for c in raw_line.strip().strip('|').split('|')] if raw_line.lstrip().startswith('|') else []
        first = _URL.sub(' ', cells[0]).strip(' *`') if cells else ''
        if re.fullmatch(r'(?i)(?:P|PHOTO|PIC|IMG|IMAGE)[- _#:.]*0*[1-9]\d{0,2}', first):
            photo = _photo_identity(url_free)
            if photo:
                person, role = _photo_details(raw_line, url_free)
                description, window = _broll_details(url_free)
                return photo + ('photo', person, role, description, _picture_window(url_free, window))
        if re.fullmatch(r'(?i)(?:B|BR|BROLL|B[-_ ]?ROLL|BASE)[- _#:.]*0*[1-9]\d{0,2}', first):
            m = _BROLL_ID.search(first)
            named = next(iter(_ANY_FILE.findall(url_free)), None)
            if first.upper().startswith('BASE'):
                return broll(first, None, named or (first + '.mp4'), url_free, raw_line)
            return broll(first, int(m.group(1)), named, url_free, raw_line)
        found = _identity(url_free)
        if found and (found[1] or found[2]) and not (found[2] and _BROLL_ID.match(found[2])):
            return found + ('video', '', '', '', None)
        stripped = _ANY_FILE.sub(' ', url_free)
        m = _BROLL_ID.search(stripped)
        files = _ANY_FILE.findall(url_free)
        base_file = next((f for f in files if re.match(r'(?i)(?:B[\-_]?ROLL|BROLL|BASE|BR|B)[\-_]?\d', f)), None)
        if m and int(m.group(1)) > 0:
            named = files[0] if files else None
            if not named and m.group(0).upper().startswith('BASE'):
                named = f'BASE-{int(m.group(1)):02d}.mp4'      # BASE rows keep their own name
            return broll(m.group(0).strip(), None if named and named.upper().startswith('BASE') else int(m.group(1)), named, url_free, raw_line)
        if base_file:
            return broll(base_file.rsplit('.', 1)[0], None, base_file, url_free, raw_line)
        photo = _photo_identity(url_free)
        if photo:
            person, role = _photo_details(raw_line, url_free)
            description, window = _broll_details(url_free)
            window = _picture_window(url_free, window)
            if person or role:
                # The row's own words are kept: "Mugshot" or "booking photo" there decides
                # that the photo never pops up before the narration reaches the arrest.
                return photo + ('photo', person, role, description, window)
            # A picture with nobody named on it is a base picture (a street, a house ...):
            # kept under its own name, with what the row says it shows.
            return photo + ('photo', '', '', description, window)
        # A row with a person's role and a link that is not a YouTube video is a photo
        # of that person, saved under their name ("Victim", "Maliyah Bass", ...).
        if urls and not any(youtube_id(u) for u in urls) and _ROLE.search(url_free):
            person, role = _photo_details(raw_line, url_free)
            stem = re.sub(r'[^\w\-]+', '_', person or role).strip('_') or 'Photo'
            return (person or role, None, stem + '.jpg', 'photo', person, role, '', None)
        # A row that describes a place or thing, with a link, is b-roll named after it.
        if urls and _TOPIC.search(url_free):
            description, window = _broll_details(url_free)
            stem = re.sub(r'[^\w\-]+', '_', ' '.join(description.split()[:5])).strip('_')[:60] or 'Broll'
            return (stem, None, stem + '.mp4', 'broll', '', '', description, window)
        return None

    excluded_section = False
    for line_no, raw in enumerate(lines, 1):
        line = raw.strip()
        if line.startswith('```'):
            in_fence = not in_fence
            continue
        if in_fence or not line or re.fullmatch(r'\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?', line):
            continue
        # Notes and exclusions are instructions, not unlinked footage entries.
        # Only a heading declaring an individual source may start a pending entry.
        heading = re.match(r'^#{1,6}\s+(.+)$', line)
        if heading:
            title = heading.group(1).strip()
            excluded_section = bool(re.search(r'(?i)\b(?:excluded|restricted|deliberately omitted|not for download)\b', title))
            if excluded_section or not re.match(
                r'(?i)^(?:(?:SRC|SOURCE|S|BROLL|B|BASE|PHOTO|P)[- _#:.]*0*[1-9]\d{0,2}\b|'
                r'[\w().-]+\.(?:mp4|mov|mkv|jpg|jpeg|png)\b)', title):
                continue
        if excluded_section:
            continue
        # A Markdown table is data only when its leading cell is an asset label;
        # source mentions inside prose cells are never download requests.
        if line.startswith('|'):
            cells = [c.strip(' *`') for c in line.strip('|').split('|')]
            first = cells[0]
            explicit_id = re.fullmatch(r'(?i)(?:SRC|SOURCE|S|BASE|BROLL|BR|B|PHOTO|P)[- _#:.]*0*[1-9]\d{0,2}', first)
            explicit_file = re.fullmatch(r'(?i)[\w().-]+\.(?:mp4|mov|mkv|jpg|jpeg|png)', first)
            named_second = (not first and len(cells) > 1 and
                            re.fullmatch(r'(?i)[\w().-]+\.(?:mp4|mov|mkv|jpg|jpeg|png)', cells[1]))
            if not (explicit_id or explicit_file or named_second):
                continue
        elif not _URL.search(line):
            # Retain heading/list-plus-link formats, but do not treat a sentence
            # saying 'S23 is excluded' or 'do not use B38' as a missing URL.
            candidate = re.sub(r'^(?:[-*]\s+|#{1,6}\s+)+', '', line).strip(' *`')
            if re.search(r'(?i)\b(?:exclude|excluded|avoid|do not use|not approved|restricted|omitted|never|no download)\b', candidate):
                continue
            if not re.match(
                r'(?i)^(?:(?:SRC|SOURCE|S|BROLL|B|BASE|PHOTO|P)[- _#:.]*0*[1-9]\d{0,2}\b|'
                r'[\w().-]+\.(?:mp4|mov|mkv|jpg|jpeg|png)\b)', candidate):
                continue
        urls = _URL.findall(line)
        url_free = _URL.sub(' ', line)
        found = identify(url_free, line, urls)
        if found and urls:
            if pending:
                missing(pending)
            pending = None
            entries.append({'source_label': found[0], 'number': found[1], 'named': found[2], 'url': urls[0],
                            'line': line_no, 'media': found[3], 'person': found[4], 'role': found[5],
                            'description': found[6], 'window': found[7]})
            for extra in urls[1:]:
                if youtube_id(extra) and found[3] == 'video':
                    issues.append({'kind': 'extra_link', 'line': line_no,
                                   'text': f'Line {line_no} has more than one YouTube link; only the first is used for {found[0]}.'})
        elif found:
            if pending:
                missing(pending)
            pending = (found[0], found[1], found[2], line_no, found[3], found[4], found[5], found[6], found[7])
        elif urls:
            if pending:
                desc, window = pending[7], pending[8]
                if not desc or window is None:
                    more, w2 = _broll_details(_URL.sub(' ', line))
                    desc, window = desc or more, window or w2
                entries.append({'source_label': pending[0], 'number': pending[1], 'named': pending[2], 'url': urls[0],
                                'line': line_no, 'media': pending[4], 'person': pending[5], 'role': pending[6],
                                'description': desc, 'window': window})
                pending = None
            elif any(youtube_id(u) for u in urls):
                issues.append({'kind': 'no_source_id', 'line': line_no,
                               'text': f'Line {line_no} has a YouTube link but no source ID or filename, so it was not '
                                       f'downloaded (the editor does not guess which source it is).'})
    if pending:
        missing(pending)

    numbers = [e['number'] for e in entries if e['number']] + [i['number'] for i in issues if i.get('number')]
    width = 3 if any(n > 99 for n in numbers) else 2

    def name_of(number, named, media='video'):
        return named or filename_for(number, width, media)

    def id_of(number, named, media='video'):
        if number:
            return {'photo': 'P', 'broll': 'B'}.get(media, 'SRC-') + f'{number:0{width}d}'
        return Path(named).stem

    for issue in issues:
        if issue['kind'] == 'missing_link':
            issue['filename'] = name_of(issue['number'], issue['named'], issue.get('media', 'video'))
            issue['source_id'] = id_of(issue['number'], issue['named'], issue.get('media', 'video'))
    seen_files, seen_videos, result = {}, {}, []
    for e in entries:
        media = e.get('media') or 'video'
        vid = youtube_id(e['url'])
        e['source_id'] = id_of(e['number'], e['named'], media)
        e['filename'] = name_of(e['number'], e['named'], media)
        e['named_by_sheet'] = bool(e['named']) and e['named'].casefold() in (text or '').casefold()
        # A name the editor made up (P02.jpg, Victim.jpg) takes the downloaded file's real type.
        e['fix_ext'] = media in ('photo', 'broll') and not e['named_by_sheet']
        e['video_id'] = vid
        # Any web link is accepted: yt-dlp reads YouTube and most video sites, and a
        # direct file link (a .jpg, an .mp4, a Drive or Dropbox share) is fetched as is.
        e['valid'] = bool(re.match(r'https?://', e['url'], re.I))
        e['problem'] = ''
        e['link_key'] = vid or e['url'].strip()
        key = e['filename'].casefold()
        if not e['valid']:
            e['problem'] = 'Not a web link.'
            issues.append({'kind': 'invalid_url', 'line': e['line'],
                           'text': f"{e['source_id']} (line {e['line']}): {e['url']} is not a web link."})
        elif key in seen_files and seen_files[key]['link_key'] == e['link_key']:
            # The same file and the same link again (a guide names each source on every
            # card that uses it): one source, not a problem.
            continue
        elif key in seen_files:
            first = seen_files[key]
            e['valid'] = False
            e['problem'] = f"Duplicate of {first['source_id']} on line {first['line']}."
            issues.append({'kind': 'duplicate_source', 'line': e['line'],
                           'text': f"{e['filename']} is given a different link on line {e['line']} than on line "
                                   f"{first['line']}. Only the first is downloaded; check which is right."})
        else:
            seen_files[key] = e
            share_key = (media, e['link_key'], _window_key(e.get('window')))
            if share_key in seen_videos:
                issues.append({'kind': 'duplicate_link', 'line': e['line'],
                               'text': f"{e['source_id']} is the same link as {seen_videos[share_key]['source_id']}. It is "
                                       f"downloaded once and saved as both {seen_videos[share_key]['filename']} and {e['filename']}."})
            else:
                seen_videos[share_key] = e
        if vid and media == 'video':
            e['url'] = f'https://www.youtube.com/watch?v={vid}'
        result.append(e)
    # A source named without a link is only missing if no line anywhere gives it one.
    linked = {e['filename'].casefold() for e in result}
    seen_missing, kept = set(), []
    for i in issues:
        if i['kind'] == 'missing_link':
            if i['filename'].casefold() in linked or i['filename'].casefold() in seen_missing:
                continue
            seen_missing.add(i['filename'].casefold())
        kept.append(i)
    issues = kept
    present = {e['number'] for e in result if e['number'] and e.get('media', 'video') == 'video'} | \
              {i['number'] for i in issues if i.get('number') and i.get('media', 'video') == 'video'}
    if present:
        absent = [n for n in range(1, max(present) + 1) if n not in present]
        if absent:
            runs, start = [], absent[0]
            for a, b in zip(absent, absent[1:] + [None]):
                if b != a + 1:
                    runs.append(f'S{start:0{width}d}' if start == a else f'S{start:0{width}d}-S{a:0{width}d}')
                    start = b
            issues.append({'kind': 'gap', 'text': f"Not in the sheet: {', '.join(runs)}. Numbering is kept as written, "
                                                  f"so those files will not exist (fine if the script does not use them)."})
    counts = {'sources': len(result), 'valid': sum(e['valid'] for e in result), 'issues': len(issues),
              'photos': sum(e.get('media') == 'photo' for e in result),
              'broll': sum(e.get('media') == 'broll' for e in result)}
    return {'entries': result, 'issues': issues, 'counts': counts}


# ============================================================================ providers

class DownloadError(Exception):
    def __init__(self, message, permanent=False):
        super().__init__(message)
        self.permanent = permanent


class Cancelled(Exception):
    pass


# yt-dlp error text -> (plain explanation, worth retrying?)
_KNOWN_ERRORS = [
    (r'private video', 'This video is private.', False),
    (r'video unavailable|this video is not available|has been removed|no longer available', 'This video is unavailable or was removed.', False),
    (r'account associated with this video has been terminated', 'The channel that posted this video was terminated.', False),
    (r'confirm your age|age[- ]restricted|inappropriate for some users',
     'This video is age-restricted. Choose a browser under "Use sign-in from" and retry.', False),
    (r"not a bot|confirm you.re not a bot",
     'YouTube asked for a sign-in check. Choose a browser under "Use sign-in from" and retry.', False),
    (r'members[- ]only|join this channel', 'This video is for channel members only.', False),
    (r'not available in your country|geo.?restrict', 'This video is blocked in your country.', False),
    (r'copyright', 'This video was blocked by a copyright claim.', False),
    (r'live event will begin|premieres in', 'This is a live stream or premiere that has not started.', False),
    (r'unsupported url|incomplete youtube id|is not a valid url', 'The link is not a downloadable video.', False),
    (r'requested format is not available', 'No downloadable format was offered for this video.', False),
    (r'no space left on device|disk full', 'The disk is full.', False),
    (r'http error 429|too many requests', 'YouTube is limiting requests right now.', True),
    (r'timed out|connection reset|temporary failure|name resolution|network is unreachable|http error 5\d\d|'
     r'remote end closed|unable to download|getaddrinfo|ssl', 'Network problem while downloading.', True),
]


def explain(text):
    low = (text or '').lower()
    for pattern, message, retry in _KNOWN_ERRORS:
        if re.search(pattern, low):
            return message, retry
    return (text or 'Download failed.').strip()[:300], True


class YtDlpProvider:
    """yt-dlp, run as a separate process so it can be cancelled and never blocks the app."""
    name = 'yt-dlp'

    @staticmethod
    def command():
        """How to start yt-dlp, or None. Override with STORYROOM_YTDLP_CMD."""
        override = os.environ.get('STORYROOM_YTDLP_CMD', '').strip()
        if override:
            import shlex
            parts = shlex.split(override, posix=os.name != 'nt')
            if os.name == 'nt':
                parts = [part[1:-1] if len(part) >= 2 and part[0] == part[-1] == chr(34) else part for part in parts]
            return parts, None
        if (PRIVATE_LIBS / 'yt_dlp').is_dir():
            return [sys.executable, '-m', 'yt_dlp'], str(PRIVATE_LIBS)
        try:
            import importlib.util
            if importlib.util.find_spec('yt_dlp'):
                return [sys.executable, '-m', 'yt_dlp'], None
        except (ImportError, ValueError):
            pass
        found = shutil.which('yt-dlp')
        return ([found], None) if found else (None, None)

    @classmethod
    def _env(cls, extra_path):
        env = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONUNBUFFERED='1')
        if extra_path:
            env['PYTHONPATH'] = extra_path + (os.pathsep + env['PYTHONPATH'] if env.get('PYTHONPATH') else '')
        # Use local Deno / FFprobe binaries without modifying the computer PATH.
        local_bin = APP_DIR / '.cache' / 'storyroom-tools' / 'bin'
        if local_bin.is_dir():
            env['PATH'] = str(local_bin) + os.pathsep + env.get('PATH', '')
        return env

    @classmethod
    def status(cls):
        cmd, path = cls.command()
        if not cmd:
            return {'available': False, 'version': None,
                    'detail': 'yt-dlp is not installed. Use "Install yt-dlp" below, or run: pip install yt-dlp'}
        try:
            out = subprocess.run(cmd + ['--version'], capture_output=True, text=True, timeout=60, env=cls._env(path))
            version = (out.stdout or '').strip().splitlines()[-1] if out.returncode == 0 and out.stdout.strip() else None
        except (OSError, subprocess.SubprocessError):
            version = None
        if not version:
            return {'available': False, 'version': None, 'detail': 'yt-dlp was found but did not start. Reinstall it.'}
        return {'available': True, 'version': version, 'detail': ''}

    @staticmethod
    def _format_args(quality):
        # Prefer H.264 video and AAC audio in MP4, which every editor and browser plays.
        # A higher resolution only offered as VP9/AV1 is still merged into an MP4.
        if quality == 'best':
            sort = 'res,vcodec:h264,acodec:m4a,ext:mp4:m4a'
        else:
            sort = f'res:{int(quality)},vcodec:h264,acodec:m4a,ext:mp4:m4a'
        return ['-f', 'bv*+ba/b', '-S', sort, '--merge-output-format', 'mp4', '--remux-video', 'mp4']

    def download(self, entry, work, options, report, cancel):
        """Download one entry into `work`. Returns the finished file's path."""
        cmd, path = self.command()
        if not cmd:
            raise DownloadError('yt-dlp is not installed. Use "Install yt-dlp" in the YouTube Footage Importer.', True)
        import imageio_ffmpeg
        stem = Path(entry['filename']).stem
        args = cmd + ['--newline', '--no-playlist', '--no-colors', '--ignore-config', '--no-mtime', '--progress',
                      '--no-simulate', '--continue', '--retries', '10', '--fragment-retries', '10',
                      # YouTube slows a long single request to playback speed. Asking for the
                      # file in 10 MB pieces, four at a time, keeps it at full line speed.
                      # STORYROOM_YTDLP_CHUNK / STORYROOM_YTDLP_FRAGMENTS override these for the
                      # download benchmark in tools/perf_audit.py; the defaults are unchanged.
                      *(['--http-chunk-size', os.environ.get('STORYROOM_YTDLP_CHUNK', '10M')]
                        if os.environ.get('STORYROOM_YTDLP_CHUNK', '10M') not in ('', '0') else []),
                      '--concurrent-fragments', os.environ.get('STORYROOM_YTDLP_FRAGMENTS', '4'),
                      '--socket-timeout', '30', '--ffmpeg-location', imageio_ffmpeg.get_ffmpeg_exe(),
                      '-o', str(Path(work) / (stem + '.%(ext)s')),
                      '--print', 'before_dl:SRTITLE %(title)s',
                      '--print', 'before_dl:SRSIZE %(filesize,filesize_approx)s',
                      '--print', 'before_dl:SRFORMAT %(format_id)s|%(protocol)s|%(vcodec)s|%(acodec)s|%(width)sx%(height)s',
                      '--print', 'after_move:SRFILE %(filepath)s',
                      '--progress-template', 'download:SRPROGRESS %(progress.downloaded_bytes)s '
                                             '%(progress.total_bytes,progress.total_bytes_estimate)s %(progress.status)s']
        args += self._format_args(options.get('quality', '1080'))
        if entry.get('window'):
            # B-roll with a window in the sheet: only that part of the video is downloaded.
            a, b = entry['window']
            args += ['--download-sections', f'*{a:.2f}-{b:.2f}', '--force-keyframes-at-cuts']
        if options.get('cookies_from_browser'):
            args += ['--cookies-from-browser', options['cookies_from_browser']]
        args.append(entry['url'])
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
        proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8',
                                errors='replace', bufsize=1, env=self._env(path), creationflags=flags,
                                start_new_session=os.name != 'nt')
        cancel.register(proc)
        import perflog
        began = time.monotonic(); t_meta = t_first = t_merge = None; fmt = ''
        final, errors, tail = None, [], []
        expected, done_parts, last_total, last_bytes = None, 0, None, 0
        try:
            for line in proc.stdout:
                line = line.rstrip('\n')
                if cancel.is_set():
                    break
                if line.startswith('SRTITLE '):
                    t_meta = t_meta or time.monotonic()
                    report(title=line[8:].strip())
                elif line.startswith('SRFORMAT '):
                    fmt = line[9:].strip()
                elif line.startswith('SRSIZE '):
                    expected = _int(line[7:])
                elif line.startswith('SRPROGRESS '):
                    bits = line.split()
                    got, total = _int(bits[1]) if len(bits) > 1 else None, _int(bits[2]) if len(bits) > 2 else None
                    if got is None:
                        continue
                    t_first = t_first or time.monotonic()
                    # Video and audio arrive as two downloads; keep the count rising.
                    if got < last_bytes and last_total:
                        done_parts += last_total
                    last_bytes, last_total = got, total or last_total
                    overall = done_parts + got
                    whole = expected or ((done_parts + total) if total else None)
                    percent = min(99.0, overall * 100 / whole) if whole else None
                    report(downloaded_bytes=overall, total_bytes=whole, progress=percent, phase='downloading')
                elif line.startswith('SRFILE '):
                    final = line[7:].strip()
                elif line.startswith('[Merger]') or line.startswith('[VideoRemuxer]'):
                    t_merge = t_merge or time.monotonic()
                    report(phase='merging', progress=99.0)
                elif line.startswith('ERROR:'):
                    errors.append(line[6:].strip())
                elif line.strip():
                    tail = (tail + [line])[-8:]
            proc.wait()
        finally:
            proc.stdout.close()
            cancel.unregister(proc)
            end = time.monotonic(); meta = t_meta or t_first or end
            try:
                size = Path(final).stat().st_size if final and Path(final).is_file() else None
            except OSError:
                size = None
            dl_end = t_merge or end
            perflog.record('download.ytdlp', end - began, file=entry.get('filename'), ok=proc.returncode == 0,
                           extract_metadata_s=round(meta - began, 3),
                           download_s=round(dl_end - meta, 3), merge_s=round(end - dl_end, 3) if t_merge else 0.0,
                           bytes=size, mbps=round(size * 8 / 1e6 / max(1e-3, dl_end - meta), 2) if size else None,
                           formats=fmt, window=entry.get('window'),
                           fragments=os.environ.get('STORYROOM_YTDLP_FRAGMENTS', '4'),
                           chunk=os.environ.get('STORYROOM_YTDLP_CHUNK', '10M'),
                           force_keyframes=bool(entry.get('window')))
        if cancel.is_set():
            raise Cancelled()
        if proc.returncode != 0 or not final:
            message, retry = explain(' '.join(errors) or ' '.join(tail))
            raise DownloadError(message, permanent=not retry)
        result = Path(final)
        if not result.is_file():
            candidates = sorted(Path(work).glob(stem + '.mp4'))
            if not candidates:
                raise DownloadError('yt-dlp finished but the downloaded file is missing.')
            result = candidates[0]
        return result


# ============================================================================ photos

_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
       'Chrome/124.0 Safari/537.36')
_CTYPE_EXT = {'image/jpeg': '.jpg', 'image/jpg': '.jpg', 'image/pjpeg': '.jpg', 'image/png': '.png', 'image/webp': '.webp',
              'image/gif': '.gif', 'image/bmp': '.bmp', 'image/tiff': '.tif', 'image/heic': '.heic', 'image/heif': '.heif',
              'image/avif': '.avif', 'video/mp4': '.mp4', 'video/quicktime': '.mov', 'video/webm': '.webm'}


def direct_link(url):
    """A share link turned into a link to the file itself, where the site allows it."""
    m = re.match(r'https?://drive\.google\.com/(?:file/d/|open\?id=|uc\?(?:export=\w+&)?id=)([\w-]{10,})', url)
    if m:
        return f'https://drive.google.com/uc?export=download&id={m.group(1)}'
    if re.match(r'https?://(?:www\.)?dropbox\.com/', url):
        return re.sub(r'([?&])dl=0', r'\1dl=1', url) if 'dl=0' in url else url + ('&' if '?' in url else '?') + 'dl=1'
    return url


def _sniff_ext(head, ctype, url):
    if head[:3] == b'\xff\xd8\xff':
        return '.jpg'
    if head[:8] == b'\x89PNG\r\n\x1a\n':
        return '.png'
    if head[:4] == b'RIFF' and head[8:12] == b'WEBP':
        return '.webp'
    if head[:6] in (b'GIF87a', b'GIF89a'):
        return '.gif'
    if head[4:12] in (b'ftypavif', b'ftypavis'):
        return '.avif'
    if head[4:12] in (b'ftypheic', b'ftypheix', b'ftypmif1', b'ftyphevc'):
        return '.heic'
    if head[4:8] == b'ftyp':
        return '.mp4'
    if head[:2] == b'BM':
        return '.bmp'
    ext = _CTYPE_EXT.get((ctype or '').split(';')[0].strip().lower())
    if ext:
        return ext
    tail = Path(url.split('?')[0]).suffix.lower()
    return tail if tail.lstrip('.') in IMAGE_EXT + VIDEO_EXT else ''


def _page_image(html, base):
    """The photo a web page offers for sharing (og:image / twitter:image), or None."""
    from html import unescape
    from urllib.parse import urljoin
    for prop in ('og:image:secure_url', 'og:image', 'twitter:image', 'twitter:image:src'):
        for m in re.finditer(r'<meta\b[^>]*>', html, re.I):
            tag = m.group(0)
            if re.search(r'(?:property|name)\s*=\s*["\']' + re.escape(prop) + r'["\']', tag, re.I):
                c = re.search(r'content\s*=\s*["\']([^"\']+)["\']', tag, re.I)
                if c:
                    return urljoin(base, unescape(c.group(1)).strip())
    m = re.search(r'<link\b[^>]*rel\s*=\s*["\']image_src["\'][^>]*href\s*=\s*["\']([^"\']+)["\']', html, re.I)
    return urljoin(base, unescape(m.group(1))) if m else None


def _private(url):
    """True when a link points at this computer or a private network."""
    import ipaddress, socket
    from urllib.parse import urlparse
    host = (urlparse(url).hostname or '').lower()
    if not host or host == 'localhost':
        return True
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0].split('%')[0])
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return True
    return False


def _http_get(url, dest_stem, report, cancel, depth=0):
    """Download `url` to dest_stem + its real extension. Follows a page to its photo."""
    import urllib.request
    req = urllib.request.Request(direct_link(url), headers={'User-Agent': _UA, 'Accept': 'image/*,video/*,*/*;q=0.8'})
    try:
        resp = urllib.request.urlopen(req, timeout=40)
    except Exception as exc:                        # noqa: BLE001 - shown to the user
        code = getattr(exc, 'code', None)
        if code in (401, 403):
            raise DownloadError('The site refused the download (it needs a sign-in or blocks downloads). '
                                'Open the photo, save it, and upload it to the media pool instead.', True)
        if code == 404:
            raise DownloadError('Nothing is at that link any more (404). Check the link in the sheet.', True)
        raise DownloadError(f'Could not reach the link: {exc}')
    with resp:
        ctype = resp.headers.get('Content-Type', '')
        total = _int(resp.headers.get('Content-Length'))
        head = resp.read(65536)
        if 'html' in ctype.lower() or head.lstrip()[:15].lower().startswith((b'<!doctype html', b'<html')):
            if depth:
                raise DownloadError('The link opens a web page, not a photo.', True)
            page = (head + resp.read(3_000_000)).decode('utf-8', 'replace')
            image = _page_image(page, resp.geturl())
            if not image:
                raise DownloadError('This link is a web page with no photo the editor can pick out. Right-click the '
                                    'photo, choose "Copy image address", and put that link in the sheet.', True)
            report(phase='downloading', title='Photo from ' + (re.search(r'<title>([^<]{1,120})', page, re.I) or [None, ''])[1].strip())
            if _private(image) and not _private(url):
                # A public page cannot send the downloader into this computer or network.
                raise DownloadError('The page points its photo at a private address; it was not followed.', True)
            return _http_get(image, dest_stem, report, cancel, depth + 1)
        ext = _sniff_ext(head, ctype, resp.geturl()) or '.jpg'
        out = Path(str(dest_stem) + ext)
        got = len(head)
        with open(out, 'wb') as fh:
            fh.write(head)
            while True:
                if cancel.is_set():
                    raise Cancelled()
                chunk = resp.read(262144)
                if not chunk:
                    break
                fh.write(chunk)
                got += len(chunk)
                report(downloaded_bytes=got, total_bytes=total, progress=min(99.0, got * 100 / total) if total else None,
                       phase='downloading')
    if got < 200:
        out.unlink(missing_ok=True)
        raise DownloadError('The link returned an empty file.', True)
    return out


def fetch_photo(entry, work, options, report, cancel):
    """Download a photo row into `work`. Returns the file's path (any image or video type).

    A YouTube link gives that video's thumbnail; any other link is fetched directly, and a
    web page (a news story, a memorial page) gives the photo it offers for sharing.
    """
    Path(work).mkdir(parents=True, exist_ok=True)
    stem = Path(work) / Path(entry['filename']).stem
    if youtube_id(entry['url']):
        # A time on the row (or &t= in the link) means a frame of the video at that
        # moment, the person's own picture; only a row with no time takes the thumbnail.
        at = _url_time(entry['url'])
        if at is None and entry.get('window'):
            at = entry['window'][0]
        if at is not None:
            return _frame_at(entry, work, at, options, report, cancel)
    report(phase='starting', progress=None)
    if youtube_id(entry['url']):
        cmd, path = YtDlpProvider.command()
        if not cmd:
            raise DownloadError('yt-dlp is not installed. Use "Install yt-dlp" in the YouTube Footage Importer.', True)
        import imageio_ffmpeg
        args = cmd + ['--no-playlist', '--no-colors', '--ignore-config', '--skip-download', '--no-simulate', '--write-thumbnail',
                      '--convert-thumbnails', 'jpg', '--ffmpeg-location', imageio_ffmpeg.get_ffmpeg_exe(),
                      '-o', str(stem) + '.%(ext)s', '--print', 'before_dl:SRTITLE %(title)s', entry['url']]
        if options.get('cookies_from_browser'):
            args[1:1] = ['--cookies-from-browser', options['cookies_from_browser']]
        proc = subprocess.run(args, capture_output=True, text=True, encoding='utf-8', errors='replace',
                              env=YtDlpProvider._env(path), timeout=180)
        title = next((l[8:] for l in proc.stdout.splitlines() if l.startswith('SRTITLE ')), '')
        if title:
            report(title='Thumbnail of ' + title.strip())
        found = sorted(Path(work).glob(stem.name + '.*'), key=lambda f: f.suffix != '.jpg')
        found = [f for f in found if f.suffix.lower().lstrip('.') in IMAGE_EXT]
        if proc.returncode != 0 or not found:
            message, retry = explain(proc.stdout + proc.stderr)
            raise DownloadError('Could not get the video thumbnail: ' + message, permanent=not retry)
        return found[0]
    return _http_get(entry['url'], stem, report, cancel)


def _frame_at(entry, work, at, options, report, cancel):
    """One still frame of a YouTube video at `at` seconds (a base picture from a link with &t=)."""
    import imageio_ffmpeg
    clip_entry = dict(entry, filename=Path(entry['filename']).stem + '-frame.mp4', window=(at, at + 2.0))
    clip = YtDlpProvider().download(clip_entry, work, options, report, cancel)
    out = Path(work) / (Path(entry['filename']).stem + '.jpg')
    run = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-v', 'error', '-y', '-i', str(clip), '-frames:v', '1',
                          '-q:v', '2', str(out)], capture_output=True, text=True)
    Path(clip).unlink(missing_ok=True)
    if run.returncode or not out.is_file():
        raise DownloadError(f'Could not take the frame at {at:.0f}s from the video.', True)
    return out


def fetch_broll(entry, work, options, report, cancel):
    """Download a b-roll / base-picture row. Returns the file (a video or a picture)."""
    Path(work).mkdir(parents=True, exist_ok=True)
    url = entry['url']
    wants_picture = Path(entry['filename']).suffix.lower().lstrip('.') in IMAGE_EXT
    if youtube_id(url):
        if wants_picture:
            at = _url_time(url)
            if at is None and entry.get('window'):
                at = entry['window'][0]
            return _frame_at(entry, work, at, options, report, cancel) if at is not None else \
                fetch_photo(entry, work, options, report, cancel)
        return YtDlpProvider().download(entry, work, options, report, cancel)
    path = url.split('?')[0].lower()
    direct = path.rsplit('.', 1)[-1] in IMAGE_EXT + VIDEO_EXT or direct_link(url) != url
    if direct:
        return _http_get(url, Path(work) / Path(entry['filename']).stem, report, cancel)
    # A page on another site: yt-dlp reads most video sites; otherwise take the page's photo.
    try:
        return YtDlpProvider().download(entry, work, options, report, cancel)
    except Cancelled:
        raise
    except DownloadError as first:
        try:
            return _http_get(url, Path(work) / Path(entry['filename']).stem, report, cancel)
        except DownloadError as second:
            raise DownloadError(f'Neither yt-dlp nor a direct download got a file from this link ({first}; {second}). '
                                'Open the page and copy the address of the video or picture itself.',
                                permanent=first.permanent and second.permanent)


class ApifyProvider:
    """Optional: download through an Apify actor. Used only when configured.

    Configure with STORYROOM_APIFY_TOKEN and STORYROOM_APIFY_ACTOR (an actor that takes
    a YouTube URL and returns a direct video download URL in its dataset). The field
    names can be adjusted with STORYROOM_APIFY_INPUT_FIELD (default "url") and
    STORYROOM_APIFY_RESULT_FIELD (default: the first of downloadUrl, videoUrl, url).
    Apify runs are billed by Apify; nothing here runs unless it is configured.
    """
    name = 'apify'

    @staticmethod
    def config():
        return {'token': os.environ.get('STORYROOM_APIFY_TOKEN', '').strip(),
                'actor': os.environ.get('STORYROOM_APIFY_ACTOR', '').strip(),
                'input_field': os.environ.get('STORYROOM_APIFY_INPUT_FIELD', 'url').strip() or 'url',
                'result_field': os.environ.get('STORYROOM_APIFY_RESULT_FIELD', '').strip()}

    @classmethod
    def status(cls):
        conf = cls.config()
        if not conf['token'] or not conf['actor']:
            return {'available': False, 'version': None,
                    'detail': 'Optional. Set STORYROOM_APIFY_TOKEN and STORYROOM_APIFY_ACTOR to enable Apify.'}
        return {'available': True, 'version': conf['actor'], 'detail': ''}

    def download(self, entry, work, options, report, cancel):
        import urllib.request
        conf = self.config()
        if not conf['token'] or not conf['actor']:
            raise DownloadError('Apify is not configured.', True)
        actor = conf['actor'].replace('/', '~')
        api = (f'https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items?token={conf["token"]}')
        body = json.dumps({conf['input_field']: entry['url']}).encode()
        request = urllib.request.Request(api, data=body, headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(request, timeout=600) as response:
                items = json.loads(response.read().decode('utf-8'))
        except Exception as exc:
            raise DownloadError(f'Apify run failed: {exc}') from exc
        item = items[0] if isinstance(items, list) and items else {}
        fields = [conf['result_field']] if conf['result_field'] else ['downloadUrl', 'videoUrl', 'url']
        link = next((item.get(f) for f in fields if isinstance(item.get(f), str) and item.get(f).startswith('http')), None)
        if not link:
            raise DownloadError('The Apify actor returned no download URL.', True)
        if item.get('title'):
            report(title=str(item['title']))
        target = Path(work) / (Path(entry['filename']).stem + '.download')
        with urllib.request.urlopen(link, timeout=60) as response, open(target, 'wb') as out:
            total = _int(response.headers.get('Content-Length'))
            got = 0
            while True:
                if cancel.is_set():
                    raise Cancelled()
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                got += len(chunk)
                report(downloaded_bytes=got, total_bytes=total, progress=min(99.0, got * 100 / total) if total else None)
        final = target.with_suffix('.mp4')
        target.replace(final)
        return final


PROVIDERS = {'yt-dlp': YtDlpProvider, 'apify': ApifyProvider}


def _int(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


# ============================================================================ script check

_SCRIPT_FILE = re.compile(r'^\s*(?:\*\*)?(?:Full\s+source|Video\s+File|Source\s+file|Footage)(?:\*\*)?\s*:\s*(?:\*\*)?\s*'
                          r'([\w\-().]+\.(?:mp4|mov))', re.I | re.M)


def script_needs(text):
    """{filename: latest Source OUT in seconds (or None)} for every video the script names."""
    needs = {}
    try:
        from documentary_beats import read_beats
        for beat in read_beats(text):
            name = beat['source_file']
            needs[name] = max(needs.get(name) or 0, beat['source_out_ms'] / 1000)
        return needs
    except Exception:
        pass
    for name in _SCRIPT_FILE.findall(text or ''):
        needs.setdefault(name, None)
    return needs


def script_check(state, script_text, assets):
    """Compare the sheet with the production script: names, coverage and length.

    Every file the script names should come from a row of the sheet (or already be in
    the project), and every downloaded file must be long enough for the latest Source
    OUT the script asks of it. Footage is downloaded whole from 0:00, so the script's
    timestamps refer to the file as it is.
    """
    if not script_text:
        return None
    needs = script_needs(script_text)
    if not needs:
        return None
    rows = {r['filename'].casefold(): r for r in (state or {}).get('rows', []) if r.get('valid')}
    files = {str(a.get('original_name') or a.get('name') or '').casefold(): a for a in assets
             if a.get('kind') == 'video' and not a.get('derived_from')}
    missing, short, ready = [], [], []
    for name, out in sorted(needs.items()):
        key = name.casefold()
        asset = files.get(key)
        if not asset and key not in rows:
            missing.append(name)
            continue
        if asset and out and float(asset.get('duration') or 0) + 0.001 < out:
            short.append({'filename': name, 'duration_s': float(asset.get('duration') or 0), 'needs_s': out})
        elif asset:
            ready.append(name)
    unused = [r['filename'] for k, r in rows.items() if k not in {n.casefold() for n in needs}]
    return {'script_files': sorted(needs), 'ready': ready, 'missing': missing, 'short': short, 'unused': unused}


# ============================================================================ install

def install_ytdlp(upgrade=True, log=lambda line: None):
    """Install (or update) yt-dlp into the app's private .cache folder.

    Staged in a temporary folder and swapped in only when pip succeeds, so a failed
    or interrupted install leaves the previous copy working.
    """
    import tempfile
    PRIVATE_LIBS.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='yt-dlp-install-', dir=PRIVATE_LIBS.parent) as tmp:
        stage = Path(tmp) / 'yt-dlp'
        cmd = [sys.executable, '-m', 'pip', 'install', '--disable-pip-version-check', '--target', str(stage)]
        if upgrade:
            cmd.append('--upgrade')
        cmd.extend(['yt-dlp', 'yt-dlp-ejs'])
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors='replace')
        for line in proc.stdout:
            log(line.rstrip())
        proc.wait()
        if proc.returncode != 0 or not (stage / 'yt_dlp').is_dir():
            raise RuntimeError('pip could not install yt-dlp. Check the internet connection and try again.')
        old = PRIVATE_LIBS.with_name('yt-dlp.old')
        shutil.rmtree(old, ignore_errors=True)
        if PRIVATE_LIBS.exists():
            PRIVATE_LIBS.replace(old)
        stage.replace(PRIVATE_LIBS)
        shutil.rmtree(old, ignore_errors=True)
    return YtDlpProvider.status()


# ============================================================================ state

def state_path(root):
    return Path(root) / 'downloads' / STATE_NAME


def load_state(root):
    path = state_path(root)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def save_state(root, state):
    path = state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex[:8] + '.tmp')
    temp.write_text(json.dumps(state, indent=1), encoding='utf-8')
    temp.replace(path)


def new_state(manifest_name, parsed, options):
    rows = []
    for e in parsed['entries']:
        rows.append({'source_id': e['source_id'], 'number': e['number'], 'filename': e['filename'], 'url': e['url'],
                     'named_by_sheet': e.get('named_by_sheet', False),
                     'media': e.get('media', 'video'), 'person': e.get('person', ''), 'role': e.get('role', ''),
                     'description': e.get('description', ''), 'window': list(e['window']) if e.get('window') else None,
                     'fix_ext': e.get('fix_ext', False), 'link_key': e.get('link_key') or e['video_id'] or e['url'],
                     'video_id': e['video_id'], 'line': e['line'], 'valid': e['valid'], 'problem': e['problem'],
                     'title': '', 'status': WAITING if e['valid'] else FAILED, 'progress': 0, 'phase': '',
                     'downloaded_bytes': 0, 'total_bytes': None, 'size': None, 'error': '' if e['valid'] else e['problem'],
                     'attempts': 0, 'asset_id': None, 'replace': False, 'started': None, 'finished': None})
    # A source with no link is still a row, so it can never be missed in the table.
    for issue in parsed['issues']:
        if issue['kind'] == 'missing_link' and not any(r['filename'].casefold() == issue['filename'].casefold() for r in rows):
            rows.append({'source_id': issue['source_id'], 'number': issue['number'],
                         'filename': issue['filename'], 'url': '', 'video_id': None, 'line': issue['line'],
                         'media': issue.get('media', 'video'),
                         'valid': False, 'problem': 'No link in the sheet.', 'title': '', 'status': FAILED, 'progress': 0,
                         'phase': '', 'downloaded_bytes': 0, 'total_bytes': None, 'size': None, 'error': 'No link in the sheet.',
                         'attempts': 0, 'asset_id': None, 'replace': False, 'started': None, 'finished': None})
    rows.sort(key=lambda r: r['line'])
    return {'version': 1, 'id': uuid.uuid4().hex[:12], 'manifest': manifest_name, 'created': time.time(),
            'options': dict(DEFAULT_OPTIONS, **(options or {})), 'issues': parsed['issues'], 'rows': rows,
            'job': {'status': 'ready', 'started': None, 'finished': None, 'message': ''}}


def summary(state):
    rows = [r for r in state['rows'] if r['valid']]
    done = sum(r['status'] in (COMPLETED, EXISTS) for r in rows)
    return {'total': len(rows), 'done': done, 'downloaded': sum(r['status'] == COMPLETED for r in rows),
            'existing': sum(r['status'] == EXISTS for r in rows), 'failed': sum(r['status'] == FAILED for r in rows),
            'active': sum(r['status'] in ACTIVE for r in rows), 'waiting': sum(r['status'] == WAITING for r in rows),
            'stopped': sum(r['status'] in (CANCELLED, INTERRUPTED) for r in rows),
            'invalid': sum(not r['valid'] for r in state['rows'])}


def recover(state):
    """After a restart nothing is downloading any more: say so, and allow a resume."""
    changed = False
    for row in state['rows']:
        if row['status'] in ACTIVE:
            row.update(status=INTERRUPTED, phase='', error='The editor was closed during this download. Resume to continue.')
            changed = True
    if state['job']['status'] in ('running', 'cancelling'):
        state['job'].update(status='interrupted', message='Interrupted. Resume to continue where it stopped.')
        changed = True
    return changed


# ============================================================================ job

class CancelToken:
    def __init__(self):
        self._event = threading.Event()
        self._procs = set()
        self._lock = threading.Lock()

    def is_set(self):
        return self._event.is_set()

    def set(self):
        self._event.set()
        with self._lock:
            for proc in list(self._procs):
                _kill_tree(proc)

    def register(self, proc):
        with self._lock:
            self._procs.add(proc)
            if self._event.is_set():
                _kill_tree(proc)

    def unregister(self, proc):
        with self._lock:
            self._procs.discard(proc)


def _kill_tree(proc):
    """Stop a download and anything it started (ffmpeg merging), on every platform."""
    try:
        import psutil
        parent = psutil.Process(proc.pid)
        for child in parent.children(recursive=True):
            child.kill()
        parent.kill()
        return
    except Exception:
        pass
    try:
        if os.name == 'nt':
            subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'], capture_output=True)
        else:
            os.killpg(proc.pid, 9)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


JOBS = {}
JOBS_LOCK = threading.Lock()


def _window_key(window):
    return tuple(float(x) for x in window) if window else None


def share_key(row):
    """Rows with the same key are the same download: one link, fetched as the same kind,
    over the same window. Two B rows that cut different windows from one video (a clean
    stretch of a news package each) are two downloads, never one copied to both names."""
    return (row.get('media') or 'video', row.get('link_key') or row.get('video_id') or row.get('url'),
            _window_key(row.get('window')))


def row_key():
    return uuid.uuid4().hex


def running(pid):
    with JOBS_LOCK:
        job = JOBS.get(pid)
        return bool(job and job.thread.is_alive())


class DownloadJob:
    """Download every waiting row of one project's sheet, then register each file.

    `register(row, path)` is supplied by the app. It imports the finished file into the
    project under row['filename'] and returns the new asset id, raising ValueError with
    a reason the user can act on if the file is not usable.
    `existing(row)` returns 'same' (this video is already imported), 'other' (a
    different file with that name is in the project) or None.
    """

    def __init__(self, pid, root, register, existing, retry_delays=(5, 20), local_copy=None):
        self.pid, self.root = pid, Path(root)
        self.register, self.existing = register, existing
        # local_copy(row) -> (path, title) of a file already in the project downloaded
        # from the same video, so it is copied instead of downloaded a second time.
        self.local_copy = local_copy
        self.video_locks, self.shared, self.titles = {}, {}, {}
        self.share = set()
        self.retry_delays = retry_delays
        self.cancel = CancelToken()
        self.lock = threading.RLock()
        self.state = load_state(self.root)
        self.thread = threading.Thread(target=self.run, daemon=True, name='youtube-download-' + pid)
        self._last_save = 0

    # -- state helpers
    def save(self, force=False):
        now = time.time()
        if force or now - self._last_save > 0.5:
            with self.lock:
                save_state(self.root, self.state)
            self._last_save = now

    def update(self, row, **values):
        with self.lock:
            row.update(values)
        self.save(force='status' in values)

    def start(self):
        with JOBS_LOCK:
            old = JOBS.get(self.pid)
            if old and old.thread.is_alive():
                raise RuntimeError('Downloads are already running for this production.')
            JOBS[self.pid] = self
        self.thread.start()
        return self

    def stop(self):
        with self.lock:
            self.state['job'].update(status='cancelling', message='Stopping downloads...')
        self.save(force=True)
        self.cancel.set()

    # -- work
    def run(self):
        work_root = self.root / 'downloads' / 'tmp'
        work_root.mkdir(parents=True, exist_ok=True)
        options = dict(DEFAULT_OPTIONS, **self.state.get('options', {}))
        with self.lock:
            self.state['job'].update(status='running', started=time.time(), finished=None, message='')
            for row in self.state['rows']:
                if not row['valid'] or row['status'] in (COMPLETED,):
                    continue
                if row['status'] == EXISTS and not row.get('replace'):
                    continue
                kind = self.existing(row)
                if kind == 'same' and not row.get('replace'):
                    row.update(status=COMPLETED, progress=100, phase='', error='', note='Already downloaded into this production.')
                elif kind == 'other' and not row.get('replace'):
                    row.update(status=EXISTS, progress=0, phase='', error='',
                               note=f"{row['filename']} is already in this production. Choose Replace to download over it.")
                elif row['status'] in (WAITING,) + REDO + (EXISTS,):
                    row.update(status=WAITING, progress=0, phase='', error='', attempts=0)
        self.save(force=True)
        queue = [r for r in self.state['rows'] if r['valid'] and r['status'] == WAITING]
        # Source masters first; B-roll/photo extracts follow. Each finished source can be
        # analysed as it arrives, while up to four downloads use the network.
        queue.sort(key=lambda r: 0 if r.get('media') == 'video' and
                   re.fullmatch(r'S\d+\.mp4', r.get('filename', ''), re.I) else 1)
        seen = set()
        for r in queue:
            key = share_key(r)
            if key in seen:
                self.share.add(key)
            seen.add(key)
        pool = threading.Semaphore(max(1, min(4, int(options.get('concurrency') or 4))))
        workers = []
        for row in queue:
            if self.cancel.is_set():
                break
            pool.acquire()
            if self.cancel.is_set():
                pool.release()
                break
            thread = threading.Thread(target=self._one, args=(row, options, work_root, pool), daemon=True)
            thread.start()
            workers.append(thread)
        for thread in workers:
            thread.join()
        shutil.rmtree(work_root / 'shared', ignore_errors=True)
        with self.lock:
            if self.cancel.is_set():
                for row in self.state['rows']:
                    if row['status'] in (WAITING,) + ACTIVE:
                        row.update(status=CANCELLED, phase='', error='Stopped before it finished. Resume to continue.')
                self.state['job'].update(status='cancelled', finished=time.time(), message='Downloads stopped.')
            else:
                s = summary(self.state)
                done = 'complete' if not s['failed'] and not s['stopped'] else 'finished_with_failures'
                self.state['job'].update(status=done, finished=time.time(),
                                         message=f"{s['done']}/{s['total']} files ready." +
                                                 (f" {s['failed']} failed." if s['failed'] else ''))
        self.save(force=True)

    def _one(self, row, options, work_root, pool):
        try:
            self._download_with_retries(row, options, work_root)
        finally:
            pool.release()

    def _video_lock(self, vid):
        with self.lock:
            return self.video_locks.setdefault(vid or row_key(), threading.Lock())

    def _copy_existing(self, row, work):
        """Use a copy of this video if it is already here. True when the row is done."""
        vid = share_key(row)
        source, title, origin = self.shared.get(vid), self.titles.get(vid, ''), 'this run'
        if not (source and Path(source).is_file()) and self.local_copy and row.get('media', 'video') == 'video':
            found = self.local_copy(row)
            if found:
                source, title, origin = found[0], found[1], 'the project'
        if not (source and Path(source).is_file()):
            return False
        Path(work).mkdir(parents=True, exist_ok=True)
        target = Path(work) / (Path(row['filename']).stem + (Path(source).suffix or '.mp4'))
        self.update(row, status=DOWNLOADING, phase='copying', progress=50, title=title or row.get('title', ''),
                    started=time.time(), provider='copy')
        shutil.copyfile(source, target)              # streamed on disk, never read into memory
        size = target.stat().st_size
        self.update(row, phase='checking', progress=99.5)
        asset_id = self.register(row, target)
        self.update(row, status=COMPLETED, progress=100, phase='', error='', asset_id=asset_id, finished=time.time(),
                    size=size, replace=False, note=f'Same video as another source; copied from {origin}, not downloaded again.')
        return True

    def _download_with_retries(self, row, options, work_root):
        with self._video_lock(share_key(row)):
            try:
                if self._copy_existing(row, work_root / Path(row['filename']).stem):
                    return
            except ValueError as exc:
                self.update(row, status=FAILED, phase='', progress=0, finished=time.time(), error=str(exc))
                return
            except OSError:
                pass                                # fall back to downloading it
            self._download(row, options, work_root)

    def _download(self, row, options, work_root):
        attempts = max(1, int(options.get('attempts') or 3))
        names = [options.get('provider') or 'yt-dlp']
        if row.get('media', 'video') == 'video' and names[0] != 'apify' and ApifyProvider.status()['available'] and options.get('apify_fallback'):
            names.append('apify')
        work = work_root / Path(row['filename']).stem
        work.mkdir(parents=True, exist_ok=True)
        last = None
        for name in names:
            provider = PROVIDERS[name]()
            if row.get('media') in ('photo', 'broll'):
                class _Direct:                  # photos and b-roll: fetch_photo / fetch_broll
                    download = staticmethod(fetch_photo if row.get('media') == 'photo' else fetch_broll)
                provider = _Direct()
            for attempt in range(1, attempts + 1):
                if self.cancel.is_set():
                    return
                self.update(row, status=DOWNLOADING if attempt == 1 else RETRYING, attempts=row['attempts'] + 1,
                            started=row.get('started') or time.time(), error='' if attempt == 1 else row['error'],
                            phase='starting', provider=name)
                try:
                    def report(**values):
                        if row['status'] == RETRYING and values.get('downloaded_bytes'):
                            values.update(status=DOWNLOADING, error='')
                        self.update(row, **values)
                    path = Path(provider.download(row, work, options, report, self.cancel))
                    size = path.stat().st_size if path.is_file() else None
                    vid = share_key(row)
                    if vid in self.share and path.is_file():
                        # Another source in this sheet is the same link: keep a copy for it.
                        cache = work_root / 'shared' / (uuid.uuid5(uuid.NAMESPACE_URL, repr(vid)).hex + path.suffix)
                        cache.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(path, cache)
                        self.shared[vid], self.titles[vid] = cache, row.get('title', '')
                    self.update(row, phase='checking', progress=99.5)
                    asset_id = self.register(row, path)
                    self.update(row, status=COMPLETED, progress=100, phase='', error='', asset_id=asset_id,
                                finished=time.time(), size=size, replace=False, note=row.pop('register_note', ''))
                    shutil.rmtree(work, ignore_errors=True)
                    return
                except Cancelled:
                    return
                except DownloadError as exc:
                    last = exc
                    if exc.permanent:
                        break
                    if attempt < attempts:
                        delay = self.retry_delays[min(attempt - 1, len(self.retry_delays) - 1)]
                        self.update(row, status=RETRYING, phase='', error=f'{exc} Retrying in {delay}s '
                                                                          f'(attempt {attempt + 1} of {attempts}).')
                        if self.cancel._event.wait(delay):
                            return
                except ValueError as exc:            # the downloaded file was not usable
                    last = DownloadError(str(exc), permanent=True)
                    break
                except Exception as exc:              # never let one row stop the queue
                    last = DownloadError(f'Unexpected error: {exc}')
                    if attempt >= attempts:
                        break
        self.update(row, status=FAILED, phase='', progress=0, finished=time.time(),
                    error=str(last) if last else 'Download failed.')
        try:
            work.rmdir()            # only when empty: a partial download is kept for a resume
        except OSError:
            pass
