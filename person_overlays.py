"""Person photo overlays: when the narrator says a name, that person's photo appears.

The photo is laid OVER the picture that is already playing: full screen by default
(the photo fitted to the frame over a blurred copy of itself), or as a corner card. Nothing on the
storyboard changes: no Beat is split, no cut moves, no frame is added or removed, and
the narration is untouched. The card is composited in the final render pass (and drawn
over the monitor in the preview), so turning overlays off gives back exactly the film
that was there before.

Rules
  * Timing `cue` (default): the photo is up for the whole SRT line that names the
    person, and through following lines that name them again. When one line names two
    people, the first holds until the second name is spoken, then the second takes over.
    Timing `fixed`: the photo arrives a moment before the word and stays for `hold_ms`.
  * Saying the same name again while the card is up keeps it up instead of flashing it
    off and on, up to `max_ms` in one stretch.
  * Only one card is on screen at a time. When the narrator moves on to another person
    the first card gives way to the second.
  * A card never crosses into a sound bite: sound bites show their speaker. A card that
    would have less than `min_ms` before a bite starts is left out and reported.
  * A person with no uploaded photo, or switched off, is reported and never shown.

Where a name falls inside an SRT cue is estimated from its position in the cue text.
SRT cues are a few seconds long, so this lands within a fraction of a second; the
preview shows the result so it can be checked by eye.

This module decides timing and draws the card. It does not verify who is in a photo,
where the photo came from or whether it may be published -- that is the uploader's
own responsibility and is recorded as such.
"""
from pathlib import Path
import hashlib
import re
import uuid


DEFAULTS = {
    'enabled': False,  # New/unspecified projects require explicit opt-in before portrait display.
    'style': 'full',          # full (photo fills the screen) | card (corner card)
    'timing': 'cue',          # cue (whole SRT line) | fixed (hold_ms after the name)
    'position': 'center',     # v17: photos are always centred (right/left kept only for old saves)
    'size': 'medium',         # small | medium | large
    'show_label': False,  # Legacy opt-in; replaced by the first-appearance name-only intro.
    'cinematic_name_intro': True,  # One tasteful name-only graphic per approved person, no role or allegations.
    'hold_ms': 3500,          # how long one mention keeps the card up
    'max_ms': 8000,           # longest one card stays up in one stretch
    'merge_gap_ms': 1500,     # same name again within this keeps the card up
    'lead_ms': 150,           # card arrives this long before the word
    'min_ms': 1500,           # shorter than this reads as a flash, so it is left out
    'fade_ms': 0,             # 0 = a clean cut on the frame (the photo pops); a dissolve if set
    'with_visual_plan': False,  # also show cards when an applied visual plan already shows the photos
    # When photos pop up. In the opening every mention shows the photo; after it, footage
    # that shows the person is left playing and the photo is used only where there is
    # none. A person's first mention always shows their photo, wherever it falls.
    'photo_opening': 'scene2',  # scene1 | scene2 | half | always
    # Slow camera move on a full-screen photo while it is up. The name label stays
    # still; only the photo moves. 'none' keeps the photo static, as before.
    'smart_photo_mode': False,   # One grouped control: approved people + selective movement + soft entrances
    'photo_motion': 'auto_story',     # none | auto_story | single/directional cinematic moves
    'photo_motion_intensity': 'medium',   # subtle | medium | strong
    # How each photo arrives and leaves. 'moves' = varied slides/drops/fades plus a slow
    # camera move (photo_motion); 'cut' = clean cut on the frame, still photo;
    # 'dissolve' = a very short (150 ms) dissolve at the start and end only, still photo.
    'photo_style': 'moves',
    # v17: the name graphic shows at a person's FIRST introduction only. 'every' was
    # removed; old saves that still say 'every' are read as 'first'.
    'name_display': 'first',
    # v17: when one line names two people who both have a photo, show them side by side.
    'pair_photos': True,
}
PHOTO_STYLES = ('moves', 'cut', 'dissolve')
NAME_DISPLAYS = ('first',)
DISSOLVE_MS = 150
MOTIONS = ('none', 'auto_story', 'portrait_reveal', 'zoom_in', 'zoom_out', 'pan_left', 'pan_right', 'pan_up', 'pan_down', 'push_left', 'push_right', 'push_up', 'push_down', 'reveal_left', 'reveal_right', 'drift_up_right', 'drift_down_left')
MOTION_INTENSITIES = ('subtle', 'medium', 'strong')
OPENINGS = ('scene1', 'scene2', 'half', 'always')
POSITIONS = ('right', 'left', 'center')
STYLES = ('full', 'card')
TIMINGS = ('cue', 'fixed')
# Between two photos of different people, footage showing for less than this would
# read as a flash, so the first photo is held until the second arrives.
BRIDGE_MS = 800
SIZES = {'small': 0.36, 'medium': 0.46, 'large': 0.58}   # photo height / frame height
LIMITS = {'hold_ms': (1000, 15000), 'max_ms': (2000, 30000), 'merge_gap_ms': (0, 10000),
          'lead_ms': (0, 1000), 'min_ms': (300, 5000), 'fade_ms': (0, 1000)}
# Short words that are names in nobody's case but often begin or end a full name.
_NOT_A_NAME = {'the', 'and', 'van', 'von', 'der', 'jr', 'sr', 'iii', 'mr', 'mrs', 'ms', 'dr'}
# A lone first name or surname followed by one of these is a place or an organisation
# ("Harris County", "Thompson Street"), not the person.
_PLACE_WORDS = ('County', 'Street', 'St', 'Avenue', 'Ave', 'Road', 'Rd', 'Boulevard', 'Blvd', 'Drive', 'Lane',
                'Park', 'Bayou', 'River', 'Creek', 'Lake', 'City', 'Town', 'Township', 'Parish', 'Department',
                'University', 'College', 'School', 'Elementary', 'High', 'Hospital', 'Center', 'Centre', 'Church',
                'Apartments', 'Mall', 'Bridge', 'Highway', 'Freeway', 'Station', 'Airport', 'Courthouse')


# ----------------------------------------------------------------------------- settings

def settings(project):
    """The project's overlay settings with defaults filled in and values bounded."""
    saved = project.get('person_overlay_settings') or {}
    result = dict(DEFAULTS)
    for key, value in saved.items():
        if key not in DEFAULTS:
            continue
        if key in ('enabled', 'show_label', 'cinematic_name_intro', 'with_visual_plan', 'smart_photo_mode', 'pair_photos'):
            result[key] = bool(value)
        elif key == 'position':
            result[key] = 'center'                 # v17: every still sits in the middle
        elif key == 'size':
            result[key] = value if value in SIZES else DEFAULTS['size']
        elif key == 'style':
            result[key] = value if value in STYLES else DEFAULTS['style']
        elif key == 'timing':
            result[key] = value if value in TIMINGS else DEFAULTS['timing']
        elif key == 'photo_opening':
            result[key] = value if value in OPENINGS else DEFAULTS['photo_opening']
        elif key == 'photo_motion':
            result[key] = value if value in MOTIONS else DEFAULTS['photo_motion']
        elif key == 'photo_motion_intensity':
            result[key] = value if value in MOTION_INTENSITIES else DEFAULTS['photo_motion_intensity']
        elif key == 'photo_style':
            result[key] = value if value in PHOTO_STYLES else DEFAULTS['photo_style']
        elif key == 'name_display':
            result[key] = 'first'                  # v17: names at the first introduction only
        else:
            try:
                low, high = LIMITS[key]
                result[key] = int(min(high, max(low, int(value))))
            except (TypeError, ValueError):
                pass
    return result


def clean_settings(data):
    """Validate a settings update from the client. Raises ValueError with a reason."""
    if not isinstance(data, dict):
        raise ValueError('Overlay settings must be an object.')
    out = {}
    for key, value in data.items():
        if key not in DEFAULTS:
            raise ValueError(f'Unknown overlay setting: {key}.')
        if key in ('enabled', 'show_label', 'cinematic_name_intro', 'with_visual_plan', 'smart_photo_mode', 'pair_photos'):
            out[key] = bool(value)
        elif key == 'position':
            if value not in POSITIONS:
                raise ValueError('Card position must be right, left or center.')
            out[key] = value
        elif key == 'size':
            if value not in SIZES:
                raise ValueError('Card size must be small, medium or large.')
            out[key] = value
        elif key == 'style':
            if value not in STYLES:
                raise ValueError('Photo style must be full or card.')
            out[key] = value
        elif key == 'timing':
            if value not in TIMINGS:
                raise ValueError('Photo timing must be cue (whole SRT line) or fixed.')
            out[key] = value
        elif key == 'photo_opening':
            if value not in OPENINGS:
                raise ValueError('Photos first must be scene1, scene2, half or always.')
            out[key] = value
        elif key == 'photo_motion':
            if value not in MOTIONS:
                raise ValueError('Photo motion must be one of: ' + ', '.join(MOTIONS) + '.')
            out[key] = value
        elif key == 'photo_motion_intensity':
            if value not in MOTION_INTENSITIES:
                raise ValueError('Photo motion strength must be subtle, medium or strong.')
            out[key] = value
        elif key == 'photo_style':
            if value not in PHOTO_STYLES:
                raise ValueError('Photo style must be moves (slides and zooms), cut or dissolve.')
            out[key] = value
        elif key == 'name_display':
            if value not in NAME_DISPLAYS:
                raise ValueError('Names show at the first introduction only.')
            out[key] = value
        else:
            low, high = LIMITS[key]
            if type(value) not in (int, float) or not low <= value <= high:
                raise ValueError(f'{key} must be between {low} and {high} milliseconds.')
            out[key] = int(value)
    return out


# ----------------------------------------------------------------------------- people

def new_person_id():
    return uuid.uuid4().hex[:12]


def ensure_ids(people):
    """Give every person a stable id (older projects stored only name/role/aliases)."""
    for person in people:
        if not person.get('id'):
            person['id'] = new_person_id()
    return people


_MUGSHOT = re.compile(r'\bmug ?shots?\b|\bbooking (?:photo|picture|image)s?\b', re.I)
_ARREST = re.compile(r'\barrest(?:ed|s)?\b|\bcharged\b|\bbooked\b|\bin custody\b|\bturned (?:himself|herself) in\b', re.I)


def is_mugshot(text):
    """True when a photo's own description calls it a mugshot or booking photo."""
    return bool(_MUGSHOT.search(text or ''))


def arrest_ms(blocks):
    """Narration time of the first SRT line that speaks of an arrest or charge, or None."""
    return next((b['start_ms'] for b in blocks if _ARREST.search(b.get('text') or '')), None)


MAX_PERSON_PHOTOS = 5


def person_photos(person):
    """Backward-compatible ordered photo set (old projects have `photo` only)."""
    gallery = person.get('photos')
    if isinstance(gallery, list):
        valid = [x for x in gallery if isinstance(x, dict) and x.get('path')]
        if valid:
            return valid[:MAX_PERSON_PHOTOS]
    original = person.get('photo') or {}
    return [original] if original.get('path') else []


def photo_at(person, index=0):
    gallery = person_photos(person)
    try:
        index = int(index)
    except (ValueError, TypeError):
        index = 0
    return gallery[index] if 0 <= index < len(gallery) else None


def photo_person(person, index=0):
    """Shallow card-render copy: never mutate a project's selected primary photo."""
    selected = photo_at(person, index)
    if selected is None:
        raise ValueError('Person has no photo at that index.')
    return dict(person, photo=selected)


def has_photo(person, root):
    return any((Path(root) / x['path']).is_file() for x in person_photos(person))


_HASHES = {}


def _photo_hash(path):
    """A 256-bit difference hash of a photo (same picture = near-identical hash), or None."""
    try:
        st = path.stat(); key = (str(path), st.st_size, st.st_mtime_ns)
        if key not in _HASHES:
            from PIL import Image
            with Image.open(path) as im:
                g = im.convert('L').resize((17, 16))
                px = list(g.get_flattened_data() if hasattr(g, 'get_flattened_data') else g.getdata())
            _HASHES[key] = tuple(px[r * 17 + c] > px[r * 17 + c + 1] for r in range(16) for c in range(16))
        return _HASHES[key]
    except Exception:
        return None


def shared_photos(people, root):
    """{person id: [names of the other people whose photo is the same picture]}.

    Five people filed with one family graphic all pop up with the same face: each
    person needs their own photo, so the editor says so instead of letting it pass."""
    hashes = {}
    for p in people:
        if has_photo(p, root):
            h = _photo_hash(Path(root) / p['photo']['path'])
            if h: hashes[p['id']] = h
    out = {}
    ids = list(hashes)
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            if sum(x != y for x, y in zip(hashes[a], hashes[b])) <= 20:
                name = {p['id']: p.get('name', '') for p in people}
                out.setdefault(a, []).append(name[b]); out.setdefault(b, []).append(name[a])
    return out


def _tokens(name):
    return [t for t in re.findall(r"[A-Za-z][A-Za-z'\-]*", name or '')]


def _terms(person, people):
    """(term, short) pairs. `short` marks a lone first name or surname added automatically."""
    # Full names and complete approved aliases match by default. A legacy
    # one-word alias or auto-added surname cannot silently place a portrait.
    # The user can explicitly enable short-name matching for this person.
    allow_short = person.get('short_names') is True
    terms = [(person.get('name', ''), False)]
    terms += [(a, len(_tokens(a)) == 1) for a in person.get('aliases') or []
              if allow_short or len(_tokens(a)) > 1]
    if allow_short:
        others = set()
        for other in people:
            if other is person:
                continue
            for word in _tokens(other.get('name', '')) + [w for a in other.get('aliases') or [] for w in _tokens(a)]:
                others.add(word.casefold())
        words = _tokens(person.get('name', ''))
        if len(words) > 1:
            for word in (words[0], words[-1]):
                if len(word) >= 3 and word.casefold() not in _NOT_A_NAME and word.casefold() not in others:
                    terms.append((word, True))
    seen, result = set(), []
    for term, short in terms:
        term = ' '.join(term.split())
        if term and term.casefold() not in seen:
            seen.add(term.casefold())
            result.append((term, short))
    return result


def terms_for(person, people):
    """Every spelling that counts as saying this person's name.

    The full name and complete aliases count by default, in any letter case.
    One-word aliases require explicit short-name opt-in. With
    `short_names` on (opt-in) the first name and the surname count too, but
    only when written as a name (capital first letter), not followed by a place word
    ("Harris County"), and only when no other person in this production shares that
    word -- so "Bass" never decides between Maliyah Bass and Octavius Bass. Add the
    misspellings the SRT uses ("Malia", "Irvin") as aliases, and phrases that are not
    this person ("Harris County") under `exclude`.
    """
    return [term for term, _ in _terms(person, people)]


def _matcher(people):
    """One regex for every term of every person, longest first, plus a lookup."""
    lookup, short, parts = {}, set(), []
    for person in people:
        for term, is_short in _terms(person, people):
            key = ' '.join(term.casefold().split())
            # A term two people claim (both list "Bass" as an alias) names neither.
            if key in lookup and lookup[key] is not person:
                lookup[key] = None
                continue
            lookup[key] = person
            if is_short:
                short.add(key)
            parts.append(term)
    parts = sorted(set(parts), key=lambda t: (-len(t), t))
    if not parts:
        return None, lookup, short
    body = '|'.join(r'\s+'.join(re.escape(w) for w in term.split()) for term in parts)
    return re.compile(r"(?<![\w])(?:" + body + r")(?![\w])", re.I), lookup, short


_PLACE_AFTER = re.compile(r"\s+(?:" + '|'.join(_PLACE_WORDS) + r")\b")


def _excluded(person, text, start, end):
    """True when the match sits inside a phrase the user said is not this person."""
    for phrase in person.get('exclude') or []:
        phrase = ' '.join(str(phrase).split())
        if not phrase:
            continue
        pattern = r'\s+'.join(re.escape(w) for w in phrase.split())
        for hit in re.finditer(pattern, text, re.I):
            if hit.start() <= start and end <= hit.end():
                return True
    return False


# "Maliyah's mother", "Sahara Irvin's boyfriend": the line is about somebody else.
_RELATIONS = {
    'mother': r'mother|mom|mum|mama|mommy', 'father': r'father|dad|daddy|papa', 'brother': r'brother',
    'sister': r'sister', 'son': r'son', 'daughter': r'daughter', 'grandmother': r'grandmother|grandma|nana',
    'grandfather': r'grandfather|grandpa', 'aunt': r'aunt', 'uncle': r'uncle', 'cousin': r'cousin',
    'wife': r'wife', 'husband': r'husband', 'boyfriend': r'boyfriend', 'girlfriend': r'girlfriend',
    'stepfather': r'stepfather|stepdad', 'stepmother': r'stepmother|stepmom', 'family': r'family|relatives',
    'friend': r'friend|friends', 'lawyer': r'lawyer|attorney', 'neighbor': r'neighbou?rs?',
}
_POSSESSIVE = re.compile(r"\s*(?:'|\u2019)s?\s+(?:own\s+|two[- ]year[- ]old\s+|\w+[- ]year[- ]old\s+)?(" +
                         '|'.join(f'(?:{v})' for v in _RELATIONS.values()) + r")\b", re.I)


def _relation_of(word):
    for key, pattern in _RELATIONS.items():
        if re.fullmatch(pattern, word, re.I):
            return key
    return None


def _person_with_role(people, relation, owner):
    """The one person who is `owner`'s relative of this kind, or None.

    Roles in the People list are the victim's family by default: "Mother" is the
    victim's mother. So "Maliyah's mother" finds the person whose role is Mother, but
    "Thompson's mother" does not: that needs a role naming whose mother it is
    ("Suspect's mother", "Mother of Travion Thompson").
    """
    rel = r'\b(?:' + _RELATIONS.get(relation, relation) + r')\b'
    owner_role = (owner.get('role') or '').lower()
    owner_words = [w for w in (owner.get('name') or '').split() if len(w) > 2]
    owner_words += [w for w in re.findall(r'[a-z]+', owner_role) if w in ('victim', 'suspect', 'accused', 'defendant')]
    hits = []
    for p in people:
        if p is owner:
            continue
        role = p.get('role') or ''
        if not re.search(rel, role, re.I):
            continue
        names_owner = any(re.search(r'\b' + re.escape(w) + r'\b', role, re.I) for w in owner_words)
        names_someone = bool(re.search(r"\bof\b|'s\b|\u2019s\b", role))
        if names_owner or ('victim' in owner_role and not names_someone):
            hits.append(p)
    return hits[0] if len(hits) == 1 else None


def find_mentions(blocks, people, keep_blocked=False):
    """Each time a person's name is spoken, on the narration clock (ms).

    A name followed by "'s mother" (or father, boyfriend ...) is about that relative, not
    the person named: the relative's photo is used when their role is in the People
    list, and otherwise nobody's. With keep_blocked, mentions that are not shown are
    returned too, with `blocked` saying why, so the People list can show every moment.
    """
    regex, lookup, short = _matcher(people)
    found = []
    if regex is None:
        return found
    for block in blocks:
        text = block.get('text') or ''
        if not text:
            continue
        start, end = int(block['start_ms']), int(block['end_ms'])
        for match in regex.finditer(text):
            key = ' '.join(match.group(0).casefold().split())
            person = lookup.get(key)
            if person is None:
                continue
            if key in short and (not match.group(0)[0].isupper() or _PLACE_AFTER.match(text, match.end())):
                continue
            # Place the word by its position in the cue: the cue's words are spread
            # over its duration, so a name halfway through is said about halfway in.
            at = start + round((end - start) * match.start() / max(1, len(text)))
            item = {'person_id': person['id'], 'name': person.get('name', ''), 'cue': block.get('number'),
                    'narration_ms': at, 'said': match.group(0), 'text': text,
                    'short': key in short or len(key.split()) == 1}      # one word: worth a look
            if _excluded(person, text, match.start(), match.end()):
                if keep_blocked:
                    found.append(dict(item, blocked='inside a phrase you marked "not this person"'))
                continue
            rel = _POSSESSIVE.match(text, match.end())
            if rel:
                relation = _relation_of(rel.group(1))
                other = _person_with_role(people, relation, person) if relation else None
                said = text[match.start():rel.end()]
                if other is None:
                    if keep_blocked:
                        owner = person.get('name', '')
                        word = (relation or rel.group(1)).lower()
                        role = word.title() if 'victim' in (person.get('role') or '').lower() else f"{owner.split()[0]}'s {word}"
                        found.append(dict(item, said=said, blocked=f"about {owner}'s {rel.group(1).lower()}, not {owner}; "
                                                                 f"add that person with the role \"{role}\" to show their photo"))
                    continue
                item = dict(item, person_id=other['id'], name=other.get('name', ''), said=said,
                            via=person.get('name', ''), short=False)
                person = other
            skip = {int(x) for x in person.get('skip_cues') or [] if str(x).lstrip('-').isdigit()}
            if block.get('number') in skip:
                if keep_blocked:
                    found.append(dict(item, blocked='turned off for this line'))
                continue
            found.append(item)
    found.sort(key=lambda m: m['narration_ms'])
    return found


# ----------------------------------------------------------------------------- clocks

def narration_segments(project, sound_plan):
    """Narration segments on both clocks, in ms. Bites sit in the gaps between them."""
    from documentary import build_timeline
    timeline = build_timeline(project, sound_plan or {'version': 1, 'revision': 0, 'bites': []})
    result = []
    for seg in timeline['segments']:
        if seg['kind'] != 'narration':
            continue
        result.append({'narration_in': round(seg['source_in_s'] * 1000), 'narration_out': round(seg['source_out_s'] * 1000),
                       'master_in': round(seg['timeline_in_s'] * 1000), 'master_out': round(seg['timeline_out_s'] * 1000)})
    return result, round(timeline['duration_s'] * 1000)


def to_master(segments, narration_ms):
    """(master ms, segment) for a narration moment, or (None, None) outside narration."""
    for seg in segments:
        if seg['narration_in'] <= narration_ms < seg['narration_out']:
            return seg['master_in'] + (narration_ms - seg['narration_in']), seg
    return None, None


# ----------------------------------------------------------------------------- plan

FPS = 30


def _snap_ms(ms, fps=FPS):
    """A moment snapped to the output frame grid, as whole milliseconds of that frame."""
    return int(round(round(ms * fps / 1000) * 1000 / fps))


def _clock(ms):
    ms = max(0, int(round(ms)))
    h, rest = divmod(ms, 3600000)
    m, rest = divmod(rest, 60000)
    sec, msec = divmod(rest, 1000)
    return f'{h:02d}:{m:02d}:{sec:02d}.{msec:03d}'


def _cue_windows(mentions, blocks, segments, conf, notes, all_mentions=None, cuts_ms=()):
    """Whole-SRT-cue photo windows (v15).

    * A window starts at the START of the cue that names the person and ends only on a
      cue boundary: never in the middle of a line.
    * One person per cue: the first-named person who can be shown holds the whole cue.
      Anyone else named in it waits for the next cue that names them, or is skipped
      (and listed in the notes). No mid-line handover, no stacking.
    * The photo holds through following cues that name the same person, and through
      following cues that name nobody until the picture underneath changes, up to the
      start of the next cue that names someone else (so the pause between lines stays
      on the photo, not a flash of footage).
    * max_ms ends the window at the cue boundary at or after it, never inside a cue.
    * Never crosses into a sound bite: a cue cut by a bite ends the window at the last
      cue boundary before it.
    * Every boundary is snapped to the 30 fps output grid. A window shorter than min_ms
      is reported, not flashed.

    `mentions` are the mentions that may be shown; `all_mentions` every person named
    (shown or not), which decides when a line "names someone else".
    """
    order = sorted([b for b in blocks if b.get('start_ms') is not None], key=lambda b: (b['start_ms'], b['end_ms']))
    names = {}
    for m in sorted(all_mentions if all_mentions is not None else mentions, key=lambda m: m['narration_ms']):
        names.setdefault(m['cue'], [])
        if m['person_id'] not in names[m['cue']]:
            names[m['cue']].append(m['person_id'])
    showable = {}
    for m in sorted(mentions, key=lambda m: m['narration_ms']):
        showable.setdefault(m['cue'], {}).setdefault(m['person_id'], dict(m, mentions=0))
        showable[m['cue']][m['person_id']]['mentions'] += 1
    person_name = {m['person_id']: m['name'] for m in (all_mentions or mentions)}

    def segment_for(ms):
        return next((g for g in segments if g['narration_in'] <= ms < g['narration_out']), None)

    def master(g, ms):
        return g['master_in'] + (ms - g['narration_in'])

    def cut_between(a, z):
        """First real picture cut at a master moment a <= cut < z, or None."""
        return next((c for c in sorted(cuts_ms) if a <= c < z), None)

    windows = []
    i = 0
    while i < len(order):
        cue = order[i]
        here = names.get(cue['number']) or []
        shown_here = showable.get(cue['number']) or {}
        pick = next((pid for pid in here if pid in shown_here), None)
        if pick is None:
            i += 1
            continue
        # v17: a line that names two people who can both be shown puts them side by side.
        partner = next((pid for pid in here if pid != pick and pid in shown_here), None) \
            if conf.get('pair_photos', True) else None
        group = {pick, partner} if partner else {pick}
        for other in here:
            if other in group or other not in shown_here:
                continue
            later = next((b['number'] for b in order[i + 1:] if other in (names.get(b['number']) or [])), None)
            notes.append(f"{person_name.get(other, other)} (cue {cue['number']}): this line already shows "
                         f"{person_name.get(pick, pick)}; "
                         + (f"their photo waits for cue {later}." if later else "skipped for this line."))
        seg = segment_for(cue['start_ms'])
        if seg is None:
            i += 1
            continue
        first = shown_here[pick]
        end_n = min(cue['end_ms'], seg['narration_out'])
        if cue['end_ms'] > seg['narration_out']:
            notes.append(f"{first['name']} (cue {cue['number']}): a sound bite starts inside this line, so the photo "
                         f"ends where the bite begins.")
        cues, said, count = [cue['number']], first['said'], first['mentions']
        j = i + 1
        while j < len(order) and cue['end_ms'] <= seg['narration_out']:
            nxt = order[j]
            if nxt['end_ms'] > seg['narration_out']:
                break                                    # the next line runs into a sound bite
            if nxt['start_ms'] - end_n > conf['merge_gap_ms']:
                break                                    # a long silence is not a pause between lines
            nn = names.get(nxt['number']) or []
            named_here = bool(nn)
            shown_next = [pid for pid in nn if pid in (showable.get(nxt['number']) or {})]
            if conf.get('pair_photos', True):
                if named_here and ((shown_next and set(shown_next) != group) or
                                   (not shown_next and nn[0] not in group)):
                    break                                # someone else's line, or a different pair
            else:
                primary = shown_next[0] if shown_next else (nn[0] if nn else None)
                if named_here and primary != pick:
                    break                                # someone else's line
            if master(seg, end_n) - master(seg, cue['start_ms']) >= conf['max_ms']:
                break                                    # long enough: end on this cue boundary
            if not named_here and cut_between(master(seg, end_n), master(seg, nxt['end_ms'])) is not None:
                break                                    # the picture changes; let it be seen
            end_n = nxt['end_ms']
            cues.append(nxt['number'])
            if named_here:
                count += (showable.get(nxt['number']) or {}).get(pick, {}).get('mentions', 1)
            j += 1
        # Cover the pause up to the next line, unless a bite or a picture cut falls there.
        if j < len(order):
            nxt = order[j]
            gap_end = nxt['start_ms']
            if gap_end <= seg['narration_out'] and 0 < gap_end - end_n <= max(BRIDGE_MS, conf['merge_gap_ms']):
                cut = cut_between(master(seg, end_n), master(seg, gap_end))
                end_n = gap_end if cut is None else max(end_n, cut - seg['master_in'] + seg['narration_in'])
        start_m, end_m = _snap_ms(master(seg, cue['start_ms'])), _snap_ms(master(seg, end_n))
        if end_m - start_m < conf['min_ms']:
            notes.append(f"{first['name']} (cue {cue['number']}, \"{said}\"): left out, the line is only "
                         f"{(end_m - start_m) / 1000:.2f}s (shorter than {conf['min_ms'] / 1000:.1f}s), "
                         f"so it would flash.")
            i = j
            continue
        window = {'person_id': pick, 'name': first['name'], 'start_ms': start_m, 'end_ms': end_m,
                  'cues': cues, 'said': said, 'mentions': count, 'narration_ms': cue['start_ms'],
                  'seg_out': seg['master_out']}
        if partner:
            window.update(partner_id=partner, partner_name=shown_here[partner]['name'])
        windows.append(window)
        i = j
    return windows


def window_report(windows):
    """One line per photo window for the Notes panel: person, cues, film-master IN/OUT."""
    out = []
    for w in sorted(windows, key=lambda w: w['start_ms']):
        cues = w.get('cues') or []
        label = f"cue {cues[0]}" if len(cues) == 1 else f"cues {cues[0]}–{cues[-1]}"
        who = w['name'] + (f" & {w['partner_name']}" if w.get('partner_id') else '')
        shown = [n for n, on in ((w['name'], w.get('name_intro')),
                                 (w.get('partner_name'), w.get('partner_name_intro'))) if n and on]
        out.append({'person_id': w['person_id'], 'partner_id': w.get('partner_id'), 'name': who, 'cues': cues,
                    'in': _clock(w['start_ms']), 'out': _clock(w['end_ms']),
                    'name_shown': bool(shown),
                    'text': f"{who} · {label} · {_clock(w['start_ms'])} → {_clock(w['end_ms'])}"
                            + (' · side by side' if w.get('partner_id') else '')
                            + ((f" · name shown: {', '.join(shown)}" if w.get('partner_id') else ' · name shown')
                               if shown else '')})
    return out


def opening_end_ms(mode, sound_plan, narration_ms):
    """End of the opening on the narration clock: where photos always pop up.

    A scene is a stretch of narration between sound bites. With no bites, the first
    scene is the first quarter and two scenes the first half.
    """
    if mode == 'always':
        return float('inf')
    if mode == 'half' or not narration_ms:
        return narration_ms / 2
    pauses = sorted({round(float(b['pause_s']) * 1000) for b in (sound_plan or {}).get('bites') or []
                     if float(b.get('pause_s') or 0) * 1000 > 500})
    want = 1 if mode == 'scene1' else 2
    if len(pauses) >= want:
        return pauses[want - 1]
    return narration_ms * (0.25 if want == 1 else 0.5)


def footage_of_people(project, root, roles=None):
    """Windows of known footage that show a person: [(file, in_ms, out_ms, {person ids})].

    Taken from what the editor knows each shot shows: the b-roll catalogue, local
    analysis, the script's visual directions and the footage sheet's descriptions.
    """
    try:
        import visual_plan as vp
        from documentary_beats import read_beats
        try:
            beats = read_beats((project.get('production_script') or {}).get('text', ''))
        except ValueError:
            beats = None
        items, _roles = vp.build_catalogue(project, root, None, beats)
    except Exception:
        return []
    return [(i['file'], i['in_ms'], i['out_ms'], set(i['people'])) for i in items
            if i.get('moving') and i.get('file') and i.get('people')]


def _on_screen(project, master_ms):
    """(file, source ms) of the picture playing at a master-clock moment, or None."""
    assets = {a['id']: a for a in project.get('assets') or []}
    for scene in project.get('scenes') or []:
        row = scene.get('plan_row') or {}
        a0 = row.get('timeline_in_ms', scene.get('frame_in', 0) * 1000 / 30)
        a1 = row.get('timeline_out_ms', scene.get('frame_out', 0) * 1000 / 30)
        if a0 <= master_ms < a1:
            asset = assets.get(scene.get('asset_id')) or {}
            name = row.get('source_file') or asset.get('original_name') or asset.get('name')
            source = row.get('source_in_ms', float(scene.get('in_s') or 0) * 1000) + (master_ms - a0)
            return name, source
    return None


def _script_requires_moving_picture(project, master_ms):
    """A declared Beat video is authoritative; photo suggestions cannot cover it.

    Photo overlays are fallbacks for gaps, not replacements for a chosen source clip.
    Older projects without explicit Beat metadata keep their normal photo behavior.
    """
    for scene in project.get('scenes') or []:
        row = scene.get('plan_row') or {}
        # A legacy Beat script is authoritative too; never restrict this protection
        # to the former strict mode. Ignore rows without an explicitly assigned file.
        if not row.get('source_file'):
            continue
        start = row.get('timeline_in_ms')
        end = row.get('timeline_out_ms')
        if start is None or end is None or not (start <= master_ms < end):
            continue
        source = str(row.get('source_file') or '')
        return source.lower().endswith(('.mp4', '.mov', '.mkv', '.webm'))
    return False


def plan(project, root, sound_plan=None):
    """Every card window on the final timeline, plus what was left out and why."""
    conf = settings(project)
    from case_people import featured_person, in_story
    candidates = [p for p in ensure_ids(list(project.get('people') or []))
                  if featured_person(p, project.get('assets') or [])]
    blocks = (project.get('srt') or {}).get('blocks') or []
    # Match only people actually referenced by the SRT (using explicit aliases)
    # or explicitly named by the production script. Nothing from the sheet alone
    # becomes an automatic portrait, and future SRT uploads activate dormant entries.
    mentioned_ids = {m['person_id'] for m in find_mentions(blocks, candidates)}
    people = [p for p in candidates if p['id'] in mentioned_ids or in_story(p.get('name',''), project)]
    summary = {p['id']: {'id': p['id'], 'name': p.get('name', ''), 'role': p.get('role', ''),
                         'terms': terms_for(p, people), 'has_photo': has_photo(p, root),
                         'show': p.get('show') is True, 'mentions': 0, 'windows': 0, 'on_screen_ms': 0}
               for p in people}
    result = {'settings': conf, 'windows': [], 'notes': [], 'people': list(summary.values()),
              'mentions': 0, 'on_screen_ms': 0, 'duration_ms': 0}
    for pid, others in shared_photos(people, root).items():
        summary[pid]['same_photo_as'] = others
    groups = {}
    for info in summary.values():
        if info.get('same_photo_as'):
            groups.setdefault(frozenset([info['name'], *info['same_photo_as']]), None)
    for g in groups:
        result['notes'].append(f"{', '.join(sorted(g))} all have the same photo. Each person needs their own picture: "
                               f"replace it, or untick Show photo for the ones without one.")
    # The production owner has not approved automatic portrait overlays. Avoid
    # planning virtual "on screen" windows that are not actually rendered, while
    # still reporting named people so they can be reviewed and enabled manually.
    if not conf['enabled']:
        for mention in find_mentions(blocks, people):
            summary[mention['person_id']]['mentions'] += 1
            result['mentions'] += 1
        result['notes'].append('Automatic photographs are OFF. Enable the project setting and approve each person before any portrait appears.')
        return result
    if not people or not blocks:
        return result
    # In one-click mode, an explicitly approved victim/suspect portrait takes
    # priority over ordinary silent narration footage. Never override soundbites,
    # the user's per-line exclusions, or protected-minor identity restrictions.
    from case_people import featured_role
    core = lambda p: (p.get('show') is True and has_photo(p,root) and
                      bool(re.search(r'\b(?:victim|deceased|suspect|accused|defendant)\b',
                                     str(p.get('role') or ''), re.I)) and
                      featured_role(p.get('role', '')))
    automatic_core = {p['id'] for p in people if conf['smart_photo_mode'] and core(p)}
    explicit_photo_people = {p['id'] for p in people if p.get('photo_over_video') is True} | automatic_core
    if project.get('visual_plan_applied') and not conf['with_visual_plan'] and not explicit_photo_people:
        # The applied visual plan already puts source picture on screen. A separate
        # per-person explicit consent may override that for named SRT narration cues.
        result['notes'].append('An applied visual plan has picture priority. To show an approved portrait above it, '
                               'enable "Show photo over scripted video" for that person; interviews remain protected.')
        result['visual_plan'] = True
        return result
    if not (project.get('voiceover') or {}).get('duration'):
        result['notes'].append('Upload the narration so name mentions can be placed on the timeline.')
        return result
    if sound_plan is None:
        from documentary import load_plan
        sound_plan = load_plan(root)
    segments, duration = narration_segments(project, sound_plan)
    result['duration_ms'] = duration
    mentions = find_mentions(blocks, people)
    result['mentions'] = len(mentions)
    # Production picture takes priority unless the user explicitly enables
    # per-person portrait-over-video on checked narration cues; soundbites are safe.
    from documentary import narration_clock_s
    narration_total = round(narration_clock_s(project) * 1000)
    opening = opening_end_ms(conf['photo_opening'], sound_plan, narration_total)
    result['opening_ms'] = None if opening == float('inf') else int(opening)
    known = footage_of_people(project, root)
    kept, result['footage_lines'] = [], []
    last_auto_core = {}
    by_manual_override = {p['id']: p.get('photo_over_video') is True for p in people}
    by_id = {p['id']: p for p in people}
    for m in mentions:
        override = m['person_id'] in explicit_photo_people
        # Default auto placements are meaningful introductions, not 24 popups
        # just because a child's name is spoken 24 times. The per-person manual
        # override can deliberately show every approved SRT cue.
        if (m['person_id'] in automatic_core and
                not by_manual_override.get(m['person_id'], False) and
                len(person_photos(by_id[m['person_id']])) <= 1):
            # A single portrait is used selectively to avoid showing the same
            # image on every mention. With 2–5 uploaded portraits, honor each
            # checked SRT match (subject to soundbite/visual protections), and
            # rotate through distinct pictures instead.
            prev = last_auto_core.get(m['person_id'])
            if prev is not None and m['narration_ms'] - prev < 90000:
                continue
            last_auto_core[m['person_id']] = m['narration_ms']
        if project.get('visual_plan_applied') and not conf['with_visual_plan'] and not override:
            # The existing visual plan remains authoritative for everyone else.
            result['footage_lines'].append({'person_id': m['person_id'], 'cue': m['cue']})
            continue
        master, _seg = to_master(segments, m['narration_ms'])
        if not override and master is not None and _script_requires_moving_picture(project, master):
            result['footage_lines'].append({'person_id': m['person_id'], 'cue': m['cue']})
            continue
        here = _on_screen(project, master) if master is not None else None
        if not override and here and any(f == here[0] and a <= here[1] < b and m['person_id'] in who for f, a, b, who in known):
            result['footage_lines'].append({'person_id': m['person_id'], 'cue': m['cue']})
            continue
        kept.append(m)
    if result['footage_lines']:
        result['notes'].append(f"{len(result['footage_lines'])} mention(s) keep the production script's video or "
                               f"authenticated footage instead of covering it with a photograph.")
    mentions = kept
    shown, windows, eligible = [], [], []
    arrested = arrest_ms(blocks)
    held_back = {}
    by_id = {p['id']: p for p in people}
    for m in mentions:
        info = summary[m['person_id']]
        info['mentions'] += 1
        if not info['has_photo'] or not info['show']:
            continue
        if person_photos(by_id[m['person_id']]) and all(x.get('mugshot') for x in person_photos(by_id[m['person_id']])) and (arrested is None or m['narration_ms'] < arrested):
            # Their only photo is a mugshot: it never appears before the arrest is narrated.
            held_back[m['person_id']] = held_back.get(m['person_id'], 0) + 1
            continue
        eligible.append(m)
        master, seg = to_master(segments, m['narration_ms'])
        if master is None:
            continue
        shown.append(dict(m, master_ms=master, seg_in=seg['master_in'], seg_out=seg['master_out']))
    if conf['timing'] == 'cue':
        import transitions as _tr
        scenes_ = project.get('scenes') or []
        cuts_ms = [round(scenes_[c + 1].get('frame_in', 0) * 1000 / FPS) for c in _tr.documentary_cuts(scenes_)] if scenes_ else []
        windows = _cue_windows(eligible, blocks, segments, conf, result['notes'],
                               all_mentions=find_mentions(blocks, people), cuts_ms=cuts_ms)
        shown = []
    current = None

    def close(window, reason=None):
        if window['end_ms'] - window['start_ms'] < conf['min_ms']:
            windows.remove(window)
            result['notes'].append(
                f"{window['name']} (cue {window['cues'][0]}, \"{window['said']}\"): left out, only "
                f"{(window['end_ms']-window['start_ms'])/1000:.1f}s before {reason or 'the next card'}.")

    for m in shown:
        start = max(m['seg_in'], m['master_ms'] - conf['lead_ms'])
        end = min(m['seg_out'], m['master_ms'] + conf['hold_ms'])
        if current and current['person_id'] == m['person_id'] and current['seg_out'] == m['seg_out'] \
                and start <= current['end_ms'] + conf['merge_gap_ms']:
            # Same person again, close by: keep the card up rather than flash it.
            current['end_ms'] = min(max(current['end_ms'], end), current['start_ms'] + conf['max_ms'], m['seg_out'])
            current['mentions'] += 1
            if m['cue'] not in current['cues']:
                current['cues'].append(m['cue'])
            continue
        if current and start < current['end_ms']:
            # Someone else is named while a card is up: the new name takes over.
            current['end_ms'] = start
            close(current, f"{m['name']} is named")
        current = {'person_id': m['person_id'], 'name': m['name'], 'start_ms': start, 'end_ms': end,
                   'cues': [m['cue']], 'said': m['said'], 'mentions': 1, 'seg_out': m['seg_out'],
                   'narration_ms': m['narration_ms']}
        windows.append(current)
        if end - start < conf['min_ms']:
            close(current, 'a sound bite starts' if end == m['seg_out'] else None)
            current = None
    for pid_, count in held_back.items():
        result['notes'].append(f"{summary[pid_]['name']}'s photo is a mugshot, so {count} mention(s) before the arrest is "
                               f"narrated show no photo. Add a non-booking photo of them to show one in the opening.")
    # A photo suggestion might begin on an unscripted legacy shot but continue
    # through a later explicitly mapped case clip. Check the ENTIRE photo window,
    # not just the name's first estimated word position. Preserve source pictures.
    protected = []
    for scene in project.get('scenes') or []:
        row = scene.get('plan_row') or {}
        source = str(row.get('source_file') or '')
        if not source.lower().endswith(('.mp4', '.mov', '.mkv', '.webm')):
            continue
        a = row.get('timeline_in_ms', scene.get('frame_in', 0) * 1000 / 30)
        b = row.get('timeline_out_ms', scene.get('frame_out', 0) * 1000 / 30)
        if a is not None and b is not None and float(b) > float(a):
            protected.append((float(a), float(b)))
    safe_windows = []
    for window in windows:
        # A separately approved photo may cover the chosen *picture* for its
        # checked SRT narration cues, but never the source audio: windows were
        # already mapped strictly inside narration segments above.
        if window['person_id'] in explicit_photo_people:
            safe_windows.append(window)
            continue
        remaining = [(float(window['start_ms']), float(window['end_ms']))]
        for a, b in protected:
            new = []
            for x, y in remaining:
                if b <= x or a >= y:
                    new.append((x, y))
                else:
                    if x < a: new.append((x, a))
                    if b < y: new.append((b, y))
            remaining = new
        for x, y in remaining:
            if y - x >= conf['min_ms']:
                safe_windows.append(dict(window, start_ms=int(round(x)), end_ms=int(round(y))))
        if remaining != [(float(window['start_ms']), float(window['end_ms']))]:
            result['notes'].append(f"{window['name']}: photo window was trimmed around explicitly scripted video.")
    windows = safe_windows
    # Rotate only verified, actual planned appearances, independently for each
    # person. A single image still works exactly as before. The order is stable
    # across preview/export and project reloads; no immediate repeat until the
    # entire selected set has been shown.
    counts = {}
    arrest_master = to_master(segments, arrested)[0] if arrested is not None else None

    def pick_photo(pid, w):
        all_photos = person_photos(by_id[pid])
        available = [i for i, p in enumerate(all_photos) if (Path(root) / p['path']).is_file()
                     and (not p.get('mugshot') or (arrest_master is not None and w['start_ms'] >= arrest_master))]
        if not available:
            return None
        used = counts.get(pid, 0)
        counts[pid] = used + 1
        return available[used % len(available)]

    for w in sorted(windows, key=lambda x: (x['start_ms'], x['end_ms'])):
        # No safe available image means no card at this moment.
        w['photo_index'] = pick_photo(w['person_id'], w)
        if w.get('partner_id'):
            index = pick_photo(w['partner_id'], w) if w['partner_id'] in by_id else None
            if index is None:
                result['notes'].append(f"{w.get('partner_name')} (cue {w['cues'][0]}): no photo can be shown here, "
                                       f"so {w['name']} is shown alone.")
                for key in ('partner_id', 'partner_name'):
                    w.pop(key, None)
            else:
                w['partner_index'] = index
        if w['photo_index'] is None and w.get('partner_id'):
            # The second person can still be shown on their own.
            w.update(person_id=w.pop('partner_id'), name=w.pop('partner_name'), photo_index=w.pop('partner_index'))
    windows = [w for w in windows if w['photo_index'] is not None]
    # Only the FIRST truly displayed, approved portrait of each person receives
    # the cinematic name. This is not based on every SRT name mention.
    # v17: a name shows at that person's first introduction ONLY (never again later).
    introduced = set()
    names_on = bool(conf['cinematic_name_intro'] or conf['show_label'])
    for w in sorted(windows, key=lambda x: (x['start_ms'], x['end_ms'])):
        w['name_intro'] = names_on and w['person_id'] not in introduced
        introduced.add(w['person_id'])
        if w.get('partner_id'):
            w['partner_name_intro'] = names_on and w['partner_id'] not in introduced
            introduced.add(w['partner_id'])
    _assign_motions(project, windows, conf, by_id)
    for w in windows:
        w.pop('seg_out', None)
        for pid in (w['person_id'], w.get('partner_id')):
            if pid in summary:
                summary[pid]['windows'] += 1
                summary[pid]['on_screen_ms'] += w['end_ms'] - w['start_ms']
    result['windows'] = windows
    result['window_report'] = window_report(windows)
    result['on_screen_ms'] = sum(w['end_ms'] - w['start_ms'] for w in windows)
    for info in summary.values():
        if info['mentions'] and not info['has_photo']:
            result['notes'].append(f"{info['name']} is named {info['mentions']} time(s) but has no photo yet.")
        elif info['mentions'] and not info['show']:
            result['notes'].append(f"{info['name']} is switched off, so {info['mentions']} mention(s) show no card.")
        elif not info['mentions']:
            result['notes'].append(f"{info['name']} is never named in the SRT. Add the spelling the SRT uses as an alias "
                                   f"(it currently matches: {', '.join(info['terms']) or 'nothing'}).")
    return result


# ----------------------------------------------------------------------------- card

def _font(size, bold):
    from PIL import ImageFont
    names = (['DejaVuSans-Bold.ttf', 'arialbd.ttf', 'Arial Bold.ttf', 'LiberationSans-Bold.ttf'] if bold
             else ['DejaVuSans.ttf', 'arial.ttf', 'Arial.ttf', 'LiberationSans-Regular.ttf'])
    bundled = str(Path(__file__).resolve().parent / 'static' / 'fonts') + '/'
    folders = [bundled, '', '/usr/share/fonts/truetype/dejavu/', '/usr/share/fonts/truetype/liberation/',
               'C:/Windows/Fonts/', '/Library/Fonts/', '/System/Library/Fonts/Supplemental/']
    for folder in folders:
        for name in names:
            try:
                return ImageFont.truetype(folder + name, size)
            except OSError:
                continue
    try:
        return ImageFont.load_default(size)
    except TypeError:
        return ImageFont.load_default()


def geometry(width, height, conf):
    """Card size and position on a width x height frame, in pixels."""
    if conf.get('style') == 'full':
        return {'card_w': width, 'card_h': height, 'canvas_w': width, 'canvas_h': height, 'x': 0, 'y': 0,
                'label_h': 0, 'shadow': 0, 'border': 0, 'photo_w': width, 'photo_h': height}
    photo_h = SIZES[conf['size']] * height
    photo_w = photo_h * 0.8
    if photo_w > 0.42 * width:            # tall frames: bound by width instead
        photo_w = 0.42 * width
        photo_h = photo_w / 0.8
    photo_w, photo_h = round(photo_w), round(photo_h)
    border = max(3, round(photo_h * 0.012))
    label_h = round(photo_h * 0.19) if conf['show_label'] else 0
    shadow = max(6, round(photo_h * 0.035))
    card_w = photo_w + 2 * border
    card_h = photo_h + 2 * border + label_h
    canvas_w, canvas_h = card_w + 2 * shadow, card_h + 2 * shadow
    margin = round(0.05 * width)
    if conf['position'] == 'left':
        x = margin
    elif conf['position'] == 'center':
        x = (width - card_w) // 2
    else:
        x = width - margin - card_w
    # Vertically a little above centre: clear of top captions and bottom subtitles.
    y = max(round(0.06 * height), round((height - card_h) / 2 - 0.03 * height))
    return {'photo_w': photo_w, 'photo_h': photo_h, 'border': border, 'label_h': label_h, 'shadow': shadow,
            'card_w': card_w, 'card_h': card_h, 'canvas_w': canvas_w, 'canvas_h': canvas_h,
            # Where the canvas (card plus its shadow) goes on the frame.
            'x': x - shadow, 'y': y - shadow}


def _label_lines(draw, name, role, room, height_px):
    lines = [(name.upper(), True, 0.36, (255, 255, 255, 255))]
    # For documentary introductions, the name is the ONLY text displayed.
    sized = []
    for text, bold, share, colour in lines:
        size = max(8, round(height_px * share))
        font = _font(size, bold)
        while size > 8 and draw.textlength(text, font=font) > room:
            size -= 1
            font = _font(size, bold)
        sized.append((text, font, colour, draw.textbbox((0, 0), text, font=font)))
    return sized


NAME_FONT = 'Montserrat-ExtraBold.ttf'


def _name_font(size):
    """Heavy, wide capitals for the name graphic (bundled Montserrat ExtraBold)."""
    from PIL import ImageFont
    bundled = Path(__file__).resolve().parent / 'static' / 'fonts'
    for path in (bundled / NAME_FONT, bundled / 'Inter-ExtraBold.otf', Path('C:/Windows/Fonts/arialbd.ttf'),
                 Path('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf')):
        try:
            return ImageFont.truetype(str(path), size)
        except OSError:
            continue
    return _font(size, True)


_CLEAN_CACHE = {}


def clean_photo(photo_path, crop=None):
    """(clean PIL photo, details): news panels, logos and black bars cut away (v17).

    See clean_photo_framing. `crop` is the photo's saved crop setting (auto by default).
    """
    from PIL import Image
    from clean_photo_framing import clean_portrait, crop_token
    path = Path(photo_path)
    stat = path.stat()
    key = (str(path), stat.st_mtime_ns, stat.st_size, crop_token(crop))
    hit = _CLEAN_CACHE.get(key)
    if hit is None:
        with Image.open(path) as source:
            hit = clean_portrait(source, crop)
        if len(_CLEAN_CACHE) > 16:
            _CLEAN_CACHE.clear()
        _CLEAN_CACHE[key] = hit
    return hit[0].copy(), dict(hit[1])


def _crop_of(person):
    return (person.get('photo') or {}).get('crop')


def draw_full(photo_path, name, role, width, height, conf, focus_y=0.3, crop=None):
    """The clean photo, whole and centred, over a blurred copy of itself (v17).

    Screen grabs lose their side panels, channel logos and black bars first
    (clean_photo_framing), so the blur behind the photo is made from the photo only.
    The photo is never stretched or cropped further, and it is ALWAYS in the middle.
    """
    from clean_photo_framing import frame_still
    photo, _ = clean_photo(photo_path, crop)
    frame, rect = frame_still(photo, width, height, focus_y)
    frame = frame.convert('RGBA')
    if conf.get('show_label', False) and name:
        draw_names(frame, [(name, rect)], width, height)
    return frame, geometry(width, height, conf)


def _tracked_width(draw, text, font, track):
    return sum(draw.textlength(c, font=font) for c in text) + track * max(0, len(text) - 1)


def _draw_tracked(draw, xy, text, font, fill, track):
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=font, fill=fill)
        x += draw.textlength(ch, font=font) + track


def _name_place(rect, width, height):
    """(x of the red bar, room for the text) for a name under a photo at `rect`."""
    k = height / 1080
    x, _, w, _ = rect
    if w >= width * .98:                     # photo fills the frame: classic lower-third margin
        bar_x = round(width * .06)
        room = round(width * .80)
    else:
        bar_x = x + max(round(28 * k), round(w * .04))
        room = x + w - bar_x - round(40 * k)
    return bar_x, room


def name_size(names_rects, width, height):
    """One shared text size for every name on screen (two names never differ)."""
    from PIL import Image, ImageDraw
    k = height / 1080
    draw = ImageDraw.Draw(Image.new('RGB', (8, 8)))
    size = max(14, round(78 * k))
    floor = max(12, round(40 * k))
    for name, rect in names_rects:
        if not name:
            continue
        text = ' '.join(name.upper().split())
        _, room = _name_place(rect, width, height)
        while size > floor and _tracked_width(draw, text, _name_font(size), size * .035) > room - round(42 * k):
            size -= 1
    return size


def draw_names(frame, names_rects, width, height):
    """Cinematic NAME-ONLY graphic(s) on `frame` (RGBA), one under each photo rect.

    Heavy white capitals (Montserrat ExtraBold), a red vertical bar, and a thin red line
    underneath with a bright, glowing centre, over a dark navy fade at the bottom of the
    picture. No role, charge, broadcaster or case text is ever added.
    """
    import math
    from PIL import Image, ImageDraw, ImageFilter
    names_rects = [(n, r) for n, r in names_rects if n and n.strip()]
    if not names_rects:
        return
    k = height / 1080
    layer = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    # Dark navy fade over the bottom half (the photo stays clear above it).
    fade = Image.new('L', (1, height), 0)
    start = .5
    for y in range(height):
        t = max(0.0, (y / height - start) / (1 - start))
        fade.putpixel((0, y), round(240 * t ** 1.05))
    layer.paste((6, 12, 28, 255), (0, 0, width, height), fade.resize((width, height)))
    frame.alpha_composite(layer)
    size = name_size(names_rects, width, height)
    font = _name_font(size)
    track = size * .035
    for name, rect in names_rects:
        text = ' '.join(name.upper().split())
        draw = ImageDraw.Draw(frame)
        tw = _tracked_width(draw, text, font, track)
        bar_x, _ = _name_place(rect, width, height)
        y = height - round(205 * k)
        bbox = font.getbbox('H')
        tx = bar_x + round(42 * k)
        bar_top = y + bbox[1] - round(26 * k)
        line_y = y + bbox[3] + round(40 * k)
        bar_bot = line_y + round(22 * k)
        glow = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        g = ImageDraw.Draw(glow)
        bar_w = max(3, round(10 * k))
        for yy in range(bar_top, bar_bot):
            t = (yy - bar_top) / max(1, bar_bot - bar_top)
            a = round(255 * min(1, 4 * t, 4 * (1 - t) + .15))
            g.line([(bar_x, yy), (bar_x + bar_w, yy)], fill=(245, 25, 35, a))
        lx0, lx1 = bar_x + round(16 * k), round(tx + tw + 30 * k)
        hot = lx0 + (lx1 - lx0) * .42
        half = max(1, round(1.5 * k))
        for i in range(lx0, lx1):
            t = (i - lx0) / max(1, lx1 - lx0)
            edge = math.sin(math.pi * t) ** .45
            core = math.exp(-((i - hot) / ((lx1 - lx0) * .16)) ** 2)
            g.line([(i, line_y - half), (i, line_y + half + 1)], fill=(225, 15, 25, round(255 * edge)))
            if core > .05:
                g.line([(i, line_y), (i, line_y + max(1, half))],
                       fill=(255, 150 + round(90 * core), 140 + round(90 * core), round(255 * core)))
        halo = glow.copy()
        ImageDraw.Draw(halo).ellipse((hot - 150 * k, line_y - 9 * k, hot + 150 * k, line_y + 11 * k),
                                     fill=(255, 30, 30, 200))
        for radius in (28, 12, 4):
            frame.alpha_composite(halo.filter(ImageFilter.GaussianBlur(max(1, radius * k))))
        frame.alpha_composite(glow)
        shadow = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        _draw_tracked(ImageDraw.Draw(shadow), (tx + 2 * k, y + 5 * k), text, font, (0, 0, 0, 210), track)
        frame.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(max(1, 9 * k))))
        _draw_tracked(ImageDraw.Draw(frame), (tx, y), text, font, (255, 255, 255, 255), track)




# ----------------------------------------------------------------------------- pairs

def _pair_panels(width, height):
    """Layout of both panels in their shared foreground image."""
    if width >= height:
        panel, gap = max(1, width // 2), max(2, width // 160)
        return (2 * panel + gap, height), [(0, 0, panel, height), (panel + gap, 0, panel, height)]
    panel, gap = max(1, height // 2), max(2, height // 160)
    return (width, 2 * panel + gap), [(0, 0, width, panel), (0, panel + gap, width, panel)]


def pair_rects(width, height):
    """Positions of the two panels on the final picture, also used by name labels."""
    from clean_photo_framing import photo_rect
    size, panels = _pair_panels(width, height)
    left, top, card_w, card_h = photo_rect(size, width, height, inset=True)
    sx, sy = card_w / size[0], card_h / size[1]
    return [(left + round(x * sx), top + round(y * sy), round(w * sx), round(h * sy))
            for x, y, w, h in panels]


def _cover(photo, w, h, focus_y=.3):
    from PIL import Image
    pw, ph = photo.size
    c = max(w / pw, h / ph)
    big = photo.resize((max(w, round(pw * c)), max(h, round(ph * c))), Image.LANCZOS)
    left = (big.width - w) // 2
    top = round((big.height - h) * max(0.0, min(1.0, focus_y)))
    return big.crop((left, top, left + w, top + h))


def draw_pair(people, width, height, root, intros=(False, False)):
    """Two people side by side: (photo layer RGB, label layer RGBA or None)."""
    from PIL import Image
    from clean_photo_framing import frame_still
    # Build both panels on one canvas before applying the same treatment as a
    # single photo. The canvas is wide on landscape and stacked on portrait.
    size, rects = _pair_panels(width, height)
    photos = [clean_photo(Path(root) / p['photo']['path'], _crop_of(p))[0] for p in people]
    strip = Image.new('RGB', size, (30, 30, 30))
    for person, photo, (x, y, w, h) in zip(people, photos, rects):
        strip.paste(_cover(photo, w, h, float(person.get('focus_y', .3))), (x, y))
    frame, _ = frame_still(strip, width, height)
    placed = pair_rects(width, height)
    names = [(p.get('name', '') if on else '', r) for p, on, r in zip(people, intros, placed)]
    label = None
    if any(n for n, _ in names):
        label = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        draw_names(label, names, width, height)
    return frame, label


def pair_layer_files(people, root, width, height, conf, intros=(False, False), folder=None):
    """(photo layer JPEG, label layer PNG or None) for two people side by side."""
    import uuid as _uuid
    folder = Path(folder or Path(root) / '.cache' / 'person-cards')
    folder.mkdir(parents=True, exist_ok=True)
    keys = [card_key(p, root, width, height, dict(conf, show_label=False, intro_layout=False)) for p in people]
    from clean_photo_framing import VERSION
    base = hashlib.sha256(('|'.join(keys) + '|framed-pair-v29|' + VERSION).encode()).hexdigest()[:24]
    photo = folder / (base + '-pair-photo.jpg')
    label = folder / (base + '-pair-label-' + ''.join('1' if x else '0' for x in intros) + '.png')
    need_label = any(intros) and any(p.get('name') for p in people)
    if not photo.is_file() or (need_label and not label.is_file()):
        image, names = draw_pair(people, width, height, root, intros)
        temp = photo.with_name(photo.stem + '.' + _uuid.uuid4().hex[:8] + photo.suffix)
        image.convert('RGB').save(temp, quality=93); temp.replace(photo)
        if names is not None:
            temp = label.with_name(label.stem + '.' + _uuid.uuid4().hex[:8] + label.suffix)
            names.save(temp); temp.replace(label)
    return photo, (label if need_label and label.is_file() else None)


def draw_card(photo_path, name, role, width, height, conf, focus_y=0.3, crop=None):
    """The card as an RGBA image sized for a width x height frame."""
    from PIL import Image, ImageDraw, ImageFilter
    if conf.get('style') == 'full':
        return draw_full(photo_path, name, role, width, height, conf, focus_y, crop)
    g = geometry(width, height, conf)
    # The same news-panel clean-up applies to smaller cards.
    photo, _cleaning = clean_photo(photo_path, crop)
    # Fill a 4:5 portrait. Faces sit in the upper part of most photos, so a tall photo
    # is cropped toward its top rather than its middle.
    target = g['photo_w'] / g['photo_h']
    w, h = photo.size
    if w / h > target:
        new_w = round(h * target)
        left = (w - new_w) // 2
        photo = photo.crop((left, 0, left + new_w, h))
    else:
        new_h = round(w / target)
        top = round((h - new_h) * max(0.0, min(1.0, focus_y)))
        photo = photo.crop((0, top, w, top + new_h))
    photo = photo.resize((g['photo_w'], g['photo_h']), Image.LANCZOS)
    canvas = Image.new('RGBA', (g['canvas_w'], g['canvas_h']), (0, 0, 0, 0))
    s = g['shadow']
    shade = Image.new('L', canvas.size, 0)
    ImageDraw.Draw(shade).rectangle((s, s + s // 3, s + g['card_w'], s + g['card_h'] + s // 3), fill=150)
    shade = shade.filter(ImageFilter.GaussianBlur(s / 2))
    canvas.paste((0, 0, 0, 255), (0, 0), shade)
    card = Image.new('RGBA', (g['card_w'], g['card_h']), (255, 255, 255, 255))
    card.paste(photo, (g['border'], g['border']))
    if g['label_h']:
        draw = ImageDraw.Draw(card)
        top = g['photo_h'] + 2 * g['border']
        draw.rectangle((0, top, g['card_w'], g['card_h']), fill=(18, 18, 20, 255))
        pad = round(g['card_w'] * 0.06)
        room = g['card_w'] - 2 * pad
        sized = _label_lines(draw, name, role, room, g['label_h'])
        gap = round(g['label_h'] * 0.06)
        total = sum(b[3] - b[1] for *_, b in sized) + gap * (len(sized) - 1)
        y = top + (g['label_h'] - total) // 2
        for text, font, colour, box in sized:
            draw.text((pad, y - box[1]), text, font=font, fill=colour)
            y += box[3] - box[1] + gap
    canvas.alpha_composite(card, (s, s))
    return canvas, g


def card_key(person, root, width, height, conf):
    photo = Path(root) / (person.get('photo') or {}).get('path', '')
    stat = photo.stat()
    from clean_photo_framing import crop_token
    fields = [person.get('name', ''), person.get('role', ''), str(person.get('focus_y', 0.3)), str(stat.st_size),
              str(stat.st_mtime_ns), str(width), str(height), conf['size'], conf['position'], str(conf['show_label']),
              conf['style'], crop_token(_crop_of(person)), 'v17-centred-montserrat-name']
    return hashlib.sha256('|'.join(fields).encode()).hexdigest()[:24]


def _assign_motions(project, windows, conf, people_by_id):
    """Give every photo appearance its own professional move (photo_motion.plan_moves).

    Neighbouring photos never arrive the same way or move the same way. A photo that
    replaces another directly slides over it instead of fading through footage.
    """
    import photo_motion
    ordered = sorted(windows, key=lambda x: (x['start_ms'], x['end_ms']))
    mode = conf.get('photo_motion') or 'auto_story'
    style = conf.get('photo_style') or 'moves'
    if style == 'cut':
        for w in ordered:
            w['motion'] = {'move': 'clean_cut', 'entrance': 'cut', 'camera_preset': None, 'enter_ms': 0,
                           'exit': 'none', 'exit_ms': 0, 'reason': 'Photo style: clean cut.', 'label': 'Clean cut'}
        return
    if style == 'dissolve':
        starts = {w['start_ms'] for w in ordered}
        ends = {w['end_ms'] for w in ordered}
        for w in ordered:
            d = min(DISSOLVE_MS, (w['end_ms'] - w['start_ms']) // 4)
            w['motion'] = {'move': 'short_dissolve', 'entrance': 'fade' if w['start_ms'] not in ends else 'cut',
                           'camera_preset': None, 'enter_ms': d if w['start_ms'] not in ends else 0,
                           'exit': 'fade' if w['end_ms'] not in starts else 'none',
                           'exit_ms': d if w['end_ms'] not in starts else 0,
                           'reason': 'Photo style: clean cut with a short dissolve.', 'label': 'Short dissolve'}
        return
    if mode == 'none':
        for w in ordered:
            w['motion'] = {'move': 'none', 'entrance': 'cut', 'camera_preset': None, 'enter_ms': 0,
                           'exit': 'none', 'exit_ms': 0, 'reason': 'Photo motion is switched off.', 'label': 'No motion'}
        return
    cue_text = {b.get('number'): b.get('text') or '' for b in (project.get('srt') or {}).get('blocks') or []}
    starts = {w['start_ms'] for w in ordered}
    ends = {w['end_ms'] for w in ordered}
    items = []
    for w in ordered:
        person = people_by_id.get(w['person_id']) or {}
        photos = person_photos(person)
        index = w.get('photo_index') or 0
        photo = photos[index] if 0 <= index < len(photos) else {}
        items.append({'text': ' '.join(cue_text.get(c, '') for c in w.get('cues') or []),
                      'duration_ms': w['end_ms'] - w['start_ms'], 'name_intro': w.get('name_intro'),
                      'handover': w['start_ms'] in ends, 'handed_over': w['end_ms'] in starts,
                      'mugshot': bool(photo.get('mugshot'))})
    fixed = None if mode == 'auto_story' else mode
    seed = str(project.get('id') or project.get('title') or '')
    moves = photo_motion.plan_moves(items, seed, fixed_camera=fixed,
                                    intensity=conf.get('photo_motion_intensity') or 'subtle')
    for w, move in zip(ordered, moves):
        if conf.get('style') != 'full':
            # A small card keeps its frame; it slides or fades in but does not zoom inside.
            move = dict(move, camera_preset=None)
        w['motion'] = move


def window_camera(window, person=None, conf=None):
    """The camera move for one planned photo appearance (full-screen style only)."""
    move = window.get('motion')
    if move is None:
        # An unplanned window (older callers): one move per person.
        return motion_camera(person or {}, conf) if conf is not None else None
    if not move.get('camera_preset'):
        return None
    import photo_motion
    fy = .5
    if person is not None:
        fy = min(.8, max(.2, .5 + (float(person.get('focus_y', .3)) - .5) * .7))
    return photo_motion.camera_for(move, (.5, fy))


def motion_camera(person, conf):
    """A single camera move for a person's photo when no per-appearance plan exists.

    The editor plans a different move for every appearance (window['motion']); this is
    the fallback for callers without a plan. 'none' keeps photos still, a named move is
    used as chosen, and automatic picks a stable move per person. Full-screen only.
    """
    if conf.get('style') != 'full':
        return None
    mode = conf.get('photo_motion') or 'auto_story'
    if mode == 'none':
        return None
    from cinematic import preset, normalise, is_active
    if mode == 'auto_story':
        moves = ('push_left','push_right','portrait_reveal','zoom_in','zoom_out',
                 'drift_up_right','reveal_left','drift_down_left')
        token = str(person.get('id') or person.get('name') or 'portrait').encode('utf-8')
        mode = moves[hashlib.sha256(token).digest()[0] % len(moves)]
    fy = min(.8, max(.2, .5 + (float(person.get('focus_y', .3)) - .5) * .7))
    try:
        cam = normalise(preset(mode, conf.get('photo_motion_intensity') or 'subtle', (.5, fy)))
    except ValueError:
        return None
    return cam if is_active(cam) else None

def layer_files(person, root, width, height, conf, folder=None):
    """(photo layer JPEG, label layer PNG or None) for a moving full-screen photo.

    The photo moves and the label must not, so they are drawn apart: the photo with no
    label, and the label alone on a transparent frame.
    """
    folder = Path(folder or Path(root) / '.cache' / 'person-cards')
    folder.mkdir(parents=True, exist_ok=True)
    # v17: the photo sits in the middle whether or not the name shows.
    key = card_key(person, root, width, height, dict(conf, show_label=False))
    photo = folder / (key + '-photo.jpg')
    source = Path(root) / person['photo']['path']
    if not photo.is_file():
        image, _ = draw_full(source, '', '', width, height, dict(conf, show_label=False),
                             float(person.get('focus_y', 0.3)), _crop_of(person))
        temp = photo.with_name(photo.stem + '.' + uuid.uuid4().hex[:8] + photo.suffix)
        image.convert('RGB').save(temp, quality=93); temp.replace(photo)
    if not (conf.get('show_label', False) and person.get('name')):
        return photo, None
    label = folder / (card_key(person, root, width, height, conf) + '-label.png')
    if not label.is_file():
        from PIL import Image
        from clean_photo_framing import photo_rect
        clean, _ = clean_photo(source, _crop_of(person))
        frame = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        draw_names(frame, [(person.get('name', ''), photo_rect(clean.size, width, height))], width, height)
        temp = label.with_name(label.stem + '.' + uuid.uuid4().hex[:8] + label.suffix)
        frame.save(temp); temp.replace(label)
    return photo, label


def card_file(person, root, width, height, conf, folder=None):
    """Render (or reuse) the card PNG for this person at this frame size."""
    folder = Path(folder or Path(root) / '.cache' / 'person-cards')
    folder.mkdir(parents=True, exist_ok=True)
    # A full-screen photo is opaque, so it is stored as a JPEG: a fraction of the size
    # of a PNG, and much quicker for the export to read once per frame.
    full = conf.get('style') == 'full'
    out = folder / (card_key(person, root, width, height, conf) + ('.jpg' if full else '.png'))
    if not out.is_file():
        image, _ = draw_card(Path(root) / person['photo']['path'], person.get('name', ''), person.get('role', ''),
                             width, height, conf, float(person.get('focus_y', 0.3)), _crop_of(person))
        temp = out.with_name(out.stem + '.' + uuid.uuid4().hex[:8] + out.suffix)
        if full:
            image.convert('RGB').save(temp, quality=93)
        else:
            image.save(temp)
        temp.replace(out)
    return out


# ----------------------------------------------------------------------------- render

def covered_spans(project, root, sound_plan):
    """(start_s, end_s) on the final timeline where a full-screen photo hides the footage.

    The script's on-screen captions describe the footage ("Sunset Crossing
    Apartments"), so they are held back while a full-screen photo covers it.
    """
    conf = settings(project)
    if not conf['enabled'] or conf['style'] != 'full':
        return []
    return [(w['start_ms'] / 1000, w['end_ms'] / 1000) for w in plan(project, root, sound_plan)['windows']]


def frame_of(seconds, fps):
    """The output frame a moment falls on: the same rounding the picture cuts use."""
    from fractions import Fraction
    return int((Fraction(str(seconds)) * Fraction(str(fps)) + Fraction(1, 2)).__floor__())


def _frames_on(f0, f1, fps):
    """ffmpeg expression true for output frames f0 .. f1-1 exactly."""
    from fractions import Fraction
    fps = Fraction(str(fps))
    return f'gte(t,{float((f0 - Fraction(1, 2)) / fps):.6f})*lt(t,{float((f1 - Fraction(1, 2)) / fps):.6f})'


def caption_enable(start_s, end_s, spans, fps=None):
    """ffmpeg `enable` expression: on from start to end, except under a full-screen photo.

    With `fps`, it is written in frame numbers on the picture's own cut grid, so a
    caption comes on and goes off on exactly the frame where the shot cuts.
    """
    if fps:
        expr = _frames_on(frame_of(start_s, fps), frame_of(end_s, fps), fps)
        inside = [_frames_on(frame_of(x, fps), frame_of(y, fps), fps) for x, y in spans if x < end_s and y > start_s]
        return expr + (f"*not({'+'.join(inside)})" if inside else '')
    expr = f'gte(t,{start_s:.3f})*lt(t,{end_s:.3f})'
    inside = [f'between(t,{a:.3f},{b:.3f})' for a, b in spans if a < end_s and b > start_s]
    return expr + (f"*not({'+'.join(inside)})" if inside else '')



def render_filters(project, root, sound_plan, width, height, rate, work, first_input, between=None, cache=None):
    """ffmpeg inputs and filter chain that put the cards over the finished picture.

    Returns (input_args, filter_steps, count). `filter_steps` are filtergraph pieces
    that read [base] and leave [cards]; with no cards there are none. Every card input
    lasts exactly its window, so the frame count and timing of the film are unchanged.

    `between=(first_frame, end_frame)` keeps only the cards on screen in those frames
    (one piece of the film; its picture must already be on the film's clock).
    `cache` (a dict) keeps the plan and card files between calls for the same render.
    """
    conf = settings(project)
    if not conf['enabled']:
        return [], [], 0
    if cache is not None and 'plan' in cache:
        data = cache['plan']
    else:
        data = plan(project, root, sound_plan)
        if cache is not None:
            cache['plan'] = data
    people = {p['id']: p for p in project.get('people') or []}
    windows = [w for w in data['windows'] if w['person_id'] in people]
    if not windows:
        return [], [], 0
    inputs, steps, label = [], [], 'base'
    cards = cache.setdefault('cards', {}) if cache is not None else {}
    starts = {w['start_ms'] for w in windows}
    ends = {w['end_ms'] for w in windows}
    from fractions import Fraction
    fr = Fraction(str(rate))
    used = 0
    next_input = first_input
    for w in windows:
        # Snapped to the picture's frame grid (the rounding every cut uses): the photo
        # appears on the exact frame its line starts and is gone on the frame it ends.
        f0, f1 = frame_of(w['start_ms'] / 1000, fr), frame_of(w['end_ms'] / 1000, fr)
        if f1 <= f0:
            continue
        if between is not None and not (f0 < between[1] and f1 > between[0]):
            continue
        original_person = people[w['person_id']]
        person = photo_person(original_person, w.get('photo_index', 0))
        # v17: the name shows only at the person's first introduction (name_intro).
        local_conf = dict(conf, show_label=bool(w.get('name_intro')))
        partner = None
        if w.get('partner_id') in people:
            partner = photo_person(people[w['partner_id']], w.get('partner_index', 0))
            local_conf = dict(local_conf, style='full')      # two people always fill the frame
        camera = window_camera(w, person, local_conf) if local_conf.get('style') == 'full' else None
        move = w.get('motion') or {}
        separated = bool(camera or partner or (local_conf.get('show_label') and local_conf['style'] == 'full'))
        intros = (bool(w.get('name_intro')), bool(w.get('partner_name_intro')))
        card_id = (w['person_id'], w.get('photo_index', 0), bool(local_conf.get('show_label')), separated,
                   w.get('partner_id'), w.get('partner_index'), intros)
        if card_id not in cards:
            if partner:
                layers = pair_layer_files([person, partner], root, width, height, local_conf, intros,
                                          Path(work) / 'person-cards')
                cards[card_id] = (layers, geometry(width, height, local_conf))
            elif separated:
                layers = layer_files(person, root, width, height, local_conf, Path(work) / 'person-cards')
                cards[card_id] = (layers, geometry(width, height, local_conf))
            else:
                path = card_file(person, root, width, height, local_conf, Path(work) / 'person-cards')
                cards[card_id] = (path, geometry(width, height, local_conf))
        path, g = cards[card_id]
        k = used; used += 1
        start = float(f0 / fr)
        length = (f1 - f0) / fr
        fade = min((max(220, conf['fade_ms']) if conf['smart_photo_mode'] else conf['fade_ms']) / 1000, length / 3)
        enter_fade = min((move.get('enter_ms') or 0) / 1000, float(length) / 3) if move.get('entrance') == 'fade' else 0
        exit_fade = min((move.get('exit_ms') or 0) / 1000, float(length) / 4) if move.get('exit') == 'fade' else 0
        # v19: each picture is decoded once and held (still_layers.hold), and drawn in
        # YUV with an alpha plane instead of RGBA: the same picture, far less work.
        from still_layers import hold, opaque_box
        frames = int(f1 - f0)
        # One frame beyond the window: the overlay's `enable` ends it exactly, and the
        # last frame of the window never falls through to the footage at EOF.
        held = hold(rate, frames + 1)
        if separated:
            # The photo and name graphic are independent layers. Name is animated
            # on first introduction only; the photograph moves when requested.
            from cinematic import ffmpeg_filter
            photo_layer, label_layer = path
            inputs += ['-i', str(photo_layer)]
            moved = (f'[{next_input}:v]{held},format=yuva420p,{ffmpeg_filter(camera, width, height, 0, frames)}'
                     if camera else f'[{next_input}:v]{held},format=yuva420p')
            next_input += 1
            if label_layer:
                inputs += ['-i', str(label_layer)]
                steps.append(f'{moved}[ph{k}]')
                # The name stays for the whole photo window. It arrives and leaves with
                # the photo (cut, short dissolve or slide), never fading out partway.
                # Only the part of the label that has pixels is drawn.
                box = opaque_box(label_layer)
                crop, (lx, ly) = (f'crop={box[2]}:{box[3]}:{box[0]}:{box[1]},', box[:2]) if box else ('', (0, 0))
                steps.append(f'[{next_input}:v]{crop}{held},format=yuva420p[lb{k}]')
                steps.append(f'[ph{k}][lb{k}]overlay={lx}:{ly}:format=yuv420,format=yuva420p[pc{k}]')
                next_input += 1
            else:
                steps.append(f'{moved}[pc{k}]')
            index = None
        else:
            inputs += ['-i', str(path)]
            index = next_input; next_input += 1
        # Fade only where a photo meets footage. Where one photo hands straight over
        # to the next, a fade would dip to the footage underneath for a few frames.
        fades = ''
        if move:
            # A planned move owns the entrance and exit (cut, dissolve or slide).
            fade_in, fade_out = enter_fade, exit_fade
        else:
            fade_in = fade if w['start_ms'] not in ends else 0
            fade_out = fade if w['end_ms'] not in starts else 0
        if move.get('entrance') in ('left', 'right', 'top', 'bottom'):
            fade_in = 0          # it slides in from off-picture instead
        if fade_in > 0:
            fades += f'fade=t=in:st=0:d={fade_in:.3f}:alpha=1,'
        if fade_out > 0:
            fades += f'fade=t=out:st={float(length)-fade_out:.6f}:d={fade_out:.3f}:alpha=1,'
        source = f'[{index}:v]{held},format=yuva420p,' if index is not None else f'[pc{k}]'
        steps.append(f'{source}{fades}setpts=PTS-STARTPTS+{start:.6f}/TB[card{k}]')
        nxt = f'over{k}'
        # On from frame f0 up to (not including) frame f1. Written as times half a frame
        # before each cut, so exactly those frames are chosen: never one frame early,
        # never one frame into the next shot.
        import photo_motion
        ox, oy = photo_motion.overlay_position(move, g['x'], g['y'], g.get('canvas_w', width), g.get('canvas_h', height),
                                               width, height, start)
        steps.append(f"[{label}][card{k}]overlay=x='{ox}':y='{oy}':eof_action=pass:"
                     f"enable='{_frames_on(f0, f1, fr)}'[{nxt}]")
        label = nxt
    if steps:
        # The last overlay is the graph's output.
        steps[-1] = steps[-1][:steps[-1].rindex('[')] + '[cards]'
    return inputs, steps, (len(windows) if between is None else used)
