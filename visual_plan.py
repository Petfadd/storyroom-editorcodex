"""Visual plan: choose, for every line of narration, a picture that shows what is said.

Why this exists
  A production script that gives one source window per narration beat holds the same
  clip for 30-45 seconds while the narrator moves through several subjects, so the
  picture drifts away from the words. This planner works line by line (2-6 s), and it
  can only match what it knows, so it first builds a catalogue of what every shot
  shows, from everything the project already has:

    * an editing guide's cards ("Show: the railroad track seen low" for S49 1:10-1:14)
      and its base-picture table -- descriptions written by someone who looked;
    * a hand-checked b-roll catalogue (data/broll_catalog.json) for the same files;
    * local analysis reports (vision descriptions of sampled frames, and what the
      reporter says over each scene) where "Analyse locally" has been run;
    * the production script's own visual directions for each beat;
    * People-on-screen photos.

How a line is matched
  The line's subjects (who, where, what, when) are scored against every unused shot.
  A shot must score at least MATCH to count. The rules are hard: no suspect picture
  under a victim or family line, no suspect picture before the narration first names
  the suspect, no person, speaker or courtroom picture dated after the events being
  told, no talking head unless that person is the subject, no frame used twice. When
  nothing matches, the fallback order is fixed: a moving base clip of the right kind
  (places, police), the named person's photo, a base still, the script's own choice,
  and only then the best weak option, which is flagged. Stills are capped (10% of
  the film by default). Sound bites are copied from the script unchanged.

The result is a Beat production script (the format the editor already builds and
renders) plus a reason for every choice. Nothing is applied until the user says so,
and nothing here certifies who or what a picture shows.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

MIN_PIECE_MS = 1200  # shorter picture changes read as flashes
# Subjects too general to count as a new idea on their own.

# ---------------------------------------------------------------------- vocabulary
# Subject groups. A line and a shot that share a group are about the same thing.
GROUPS = {
    'track': r'track|tracks|railroad|railway|rail|rails|ballast|train|trains',
    'water': r'bayou|bayous|water|creek|river|stream|lake|pond|canal|drain|culvert|spillway|flood|floated|pool|beach|sea|ocean',
    'police': r'police|officer|officers|cop|cops|patrol|squad|deputy|deputies|detective|detectives|marshal|marshals|'
              r'tpd|hpd|precinct|badge|cruiser|helicopter|sheriff|investigators?|crime ?stoppers',
    'court': r'court|courtroom|courthouse|judge|trial|jury|jurors|bench|lectern|hearing|sentencing|sentenced|sentence|'
             r'verdict|defense|prosecutors?|attorney|plea|pleaded|guilty|testif\w*|bond',
    'custody': r'detention|jail|custody|inmate|escape|escaped|escaping|razor|fence|gate|padlock|transfer\w*|juvenile|'
               r'booking|arrest|arrested|charged|charges',
    'memorial': r'vigil|memorial|balloons?|teddy|candles?|flowers|prayers?|pray\w*|mourn\w*|banners?',
    'search': r'search\w*|volunteers?|k-?9|dog|dogs|missing|amber',
    'home': r'apartment|apartments|complex|playground|home|house|houses|neighbou?rhood|neighbou?rs?|stairs|doorway|door',
    'street': r'street|streets|road|roads|block|boulevard|blvd|avenue|ave|sign|signs|corner|intersection|markers?|dead ?end',
    'news_conf': r'podium|news conference|press conference|microphones?|chief|briefing|announce\w*',
    'family': r'mother|mom|mama|father|dad|grandfather|grandmother|grandma|granddaughter|grandson|family|relatives?|'
              r'son|daughter|aunt|uncle|brother|sister|nana|wife|husband|cousin|niece|nephew|'
              r'step(?:father|mother|dad|mom|son|daughter|brother|sister)|half[- ]?(?:brother|sister)',
    'school': r'school|classmates?|students?|teacher',
    'phone': r'phone|phones|call|called|911|message|messages|text|social media|instagram|facebook|google|search history',
    'weapon': r'gun|guns|weapon|weapons|shot|shooting|shots|bullet|firearm',
    'car': r'car|cars|vehicle|vehicles|suv|van|vans|truck',
    'nature': r'trees?|brush|grass|woods|palmetto|leaves|sky|field',
}
_GROUP_RE = {g: re.compile(r'\b(?:' + p + r')\b', re.I) for g, p in GROUPS.items()}
STOP = set('''a an the and or but if then than that this these those there here is are was were be been being of in on at
to for from by with without into onto over under about after before during while as it its he she they them his her
their him we you your i me my our us not no nor so too very can could would should will shall may might must do does
did done has have had having just also only even still yet again one two three four five six seven eight nine ten
says said say tell tells told asks asked according reports reported report times story video shows show seen see
footage picture pictures photo photos image images clip clips window approximate checked still frames frame later
news pictures event itself station banner reads actual care same another other first last next then'''.split())
_WORD = re.compile(r"[A-Za-z][A-Za-z'\-]+")
_YEAR = re.compile(r'\b(19[89]\d|20[0-4]\d)\b')
_NO_PEOPLE = re.compile(r'\bno people\b|\bnobody\b|\bno one is shown\b|\bnobody is shown\b|\bpeople only\b', re.I)
_NAME = re.compile(r'\b([A-Z][a-z]+(?:\s+(?:[A-Z]\.|[A-Z][a-z]+))+)\b')
# Capitalised words that are never somebody's name. No city, state or case-specific
# place is listed: a capitalised run that ends in a place or organisation word ("Sunset
# Crossing Apartments", "Harris County", "Houston Police Department", "Tampa Bay") is
# recognised as a place by _PLACE_END instead, so this works for any production.
_NOT_NAME_WORDS = {'News', 'Police', 'Department', 'County', 'Street', 'Avenue', 'Road', 'Center', 'Centre',
                   'Regional', 'Juvenile', 'Detention', 'Justice', 'State', 'Attorney', 'Office', 'Task', 'Force',
                   'Times', 'Channel', 'Courtesy', 'Crime', 'Stoppers', 'Welcome', 'Chief', 'Deputy', 'Major',
                   'Officer', 'Judge', 'Detective', 'Sergeant', 'Lieutenant', 'Captain', 'Mr', 'Mrs', 'Ms', 'Dr',
                   'Amber', 'Alert', 'January', 'February', 'March', 'April', 'May', 'June', 'July', 'August',
                   'September', 'October', 'November', 'December', 'Monday', 'Tuesday', 'Wednesday', 'Thursday',
                   'Friday', 'Saturday', 'Sunday', 'The', 'His', 'Her', 'A', 'North', 'South', 'East', 'West',
                   'Northwest', 'Northeast', 'Southwest', 'Southeast', 'Downtown', 'Breaking', 'Live', 'Update'}
_PLACE_END = {'County', 'Street', 'St', 'Avenue', 'Ave', 'Road', 'Rd', 'Boulevard', 'Blvd', 'Drive', 'Lane', 'Way',
              'Court', 'Place', 'Plaza', 'Square', 'Parkway', 'Highway', 'Freeway', 'Trail', 'Park', 'Bayou', 'River',
              'Creek', 'Lake', 'Bay', 'Beach', 'Island', 'Valley', 'Heights', 'Hills', 'Village', 'Estates', 'City',
              'Town', 'Township', 'Parish', 'Department', 'Office', 'News', 'Times', 'Channel', 'Network', 'Station',
              'University', 'College', 'School', 'Academy', 'Elementary', 'High', 'Hospital', 'Center', 'Centre',
              'Church', 'Apartments', 'Apartment', 'Complex', 'Crossing', 'Mall', 'Bridge', 'Airport', 'Courthouse',
              'Jail', 'Prison', 'Stoppers', 'Force', 'Alert', 'Search', 'Patrol', 'Sheriff', 'Police'}
_TITLES = {'Chief', 'Deputy', 'Major', 'Officer', 'Judge', 'Detective', 'Sergeant', 'Lieutenant', 'Captain',
           'Mr', 'Mrs', 'Ms', 'Dr', 'Attorney', 'Prosecutor', 'Sheriff'}


def _stem(word):
    w = word.lower().strip("'-")
    w = re.sub(r"'s$", '', w)
    for suffix in ('ing', 'ed', 'es', 's'):
        if len(w) > len(suffix) + 3 and w.endswith(suffix):
            return w[:-len(suffix)]
    return w


def tokens(text):
    return {_stem(w) for w in _WORD.findall(text or '') if w.lower() not in STOP and len(w) > 2}








def groups_in(text):
    return {g for g, rx in _GROUP_RE.items() if rx.search(text or '')}


def years_in(text):
    return [int(y) for y in _YEAR.findall(text or '')]


def surnames(text):
    """Surnames of the people a description names ("Chief Bercaw", "Michael Baldwin Sr.")."""
    found = set()
    for match in _NAME.finditer(text or ''):
        words = [w.rstrip('.') for w in match.group(1).split()]
        if words[-1] in _PLACE_END:
            continue                          # a place or an organisation, not a person
        real = [w for w in words if w not in _NOT_NAME_WORDS and len(w) > 2]
        if not real:
            continue
        if words[0] in _TITLES or len(real) >= 2:
            found.add(real[-1] if real[-1] not in ('Sr', 'Jr') else real[-2] if len(real) > 1 else real[-1])
    return found


def classify(text):
    """What kind of picture a description is: photo, speaker, graphic, people, place or unknown."""
    t = text or ''
    if re.search(r'\b(?:photos?|photographs?|booking photos?|mug ?shots?|selfies?|portraits?)\b', t, re.I):
        return 'photo'
    if re.search(r'\b(?:podium|lectern|speaking|interview|video call|news conference|press conference|on camera|'
                 r'addresses|addressing|statement|testif\w*)\b', t, re.I) and not _NO_PEOPLE.search(t):
        return 'speaker'
    if re.search(r'\b(?:map|graphic|screen that lists|on-screen text|title card)\b', t, re.I):
        return 'graphic'
    people = re.search(r'\b(?:officers?|people|crowd|family|relatives|volunteers|searchers|deputy|deputies|man|woman|'
                       r'boy|girl|walkers?|neighbou?rs|figure|mother|father|grandfather|grandmother|teen|teenagers?)\b', t, re.I)
    if people and not _NO_PEOPLE.search(t):
        return 'people'
    if groups_in(t) & {'track', 'water', 'street', 'home', 'custody', 'court', 'memorial', 'police', 'car', 'nature',
                       'school'} or re.search(r'\b(?:building|wall|car park|parking|sign|flags?|wire)\b', t, re.I):
        return 'place'
    return 'unknown'








# ---------------------------------------------------------------------- card guide







# ---------------------------------------------------------------------- people

def people_roles(project, guide=None):
    """Everyone the narration may name, with a role: victim, suspect, family or other."""
    from person_overlays import terms_for, ensure_ids
    from case_people import featured_role, source_is_supporting
    people = ensure_ids(list(project.get('people') or []))
    result = []
    setup = (guide or {}).get('setup', {})
    for p in people:
        role_text = (p.get('role') or '').lower()
        role = ('victim' if re.search(r'\bvictim\b', role_text) and not source_is_supporting(role_text) else
                'suspect' if re.search(r'suspect|accused|defendant|killer|convicted', role_text) else
                'family' if featured_role(role_text) and not re.search(r'\b(?:survivor|victim|suspect|accused|defendant)\b', role_text) else 'other')   # whole words: not "person"/"Thompson"
        if setup.get('victim', '').casefold() == p.get('name', '').casefold():
            role = 'victim'
        if setup.get('suspect', '').casefold() == p.get('name', '').casefold():
            role = 'suspect'
        result.append({'id': p['id'], 'name': p.get('name', ''), 'role': role, 'terms': terms_for(p, people),
                       'photo': (p.get('photo') or {}).get('path'), 'person': p})
    names = {r['name'].casefold() for r in result}
    for key in ('victim', 'suspect'):
        name = setup.get(key)
        if name and name.casefold() not in names:
            parts = name.split()
            terms = [name] + ([parts[0], parts[-1]] if len(parts) > 1 else [])
            result.append({'id': key, 'name': name, 'role': key, 'terms': terms, 'photo': None, 'person': None})
    for r in result:
        r['regex'] = re.compile(r'(?<![\w])(?:' + '|'.join(r'\s+'.join(map(re.escape, t.split())) for t in r['terms']
                                                          if t) + r")(?![\w])", re.I) if r['terms'] else None
    return result


def people_in(text, roles):
    return {r['id'] for r in roles if r['regex'] and r['regex'].search(text or '')}


# ---------------------------------------------------------------------- shots

def shot_bounds(root, path, at_ms, reach_ms=6000):
    """(start, end) ms of the shot that contains `at_ms`, from the picture itself.

    FFmpeg's scene score finds the cuts in a few seconds either side; the result is
    cached per file. Returns None when the file cannot be read.
    """
    import subprocess, imageio_ffmpeg
    cache_path = Path(root) / 'reviews' / 'shot_bounds.json'
    try:
        cache = json.loads(cache_path.read_text(encoding='utf-8')) if cache_path.is_file() else {}
    except (OSError, ValueError):
        cache = {}
    stat = Path(path).stat()
    key = f'{Path(path).name}|{stat.st_size}|{int(stat.st_mtime)}|{at_ms}'
    if key in cache:
        return tuple(cache[key]) if cache[key] else None
    start = max(0, at_ms - reach_ms)
    cmd = [imageio_ffmpeg.get_ffmpeg_exe(), '-hide_banner', '-nostats', '-ss', f'{start/1000:.3f}', '-t',
           f'{2*reach_ms/1000:.3f}', '-i', str(path), '-an', '-vf', "scale=160:-2,select='gt(scene,0.30)',showinfo",
           '-f', 'null', '-']
    try:
        run = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        cuts = [start + int(float(m) * 1000) for m in re.findall(r'pts_time:([0-9.]+)', run.stderr)]
        before = max([c for c in cuts if c <= at_ms] or [start])
        after = min([c for c in cuts if c > at_ms] or [at_ms + reach_ms])
        result = (before, after) if run.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        result = None
    cache[key] = list(result) if result else None
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache), encoding='utf-8')
    return result


# ---------------------------------------------------------------------- catalogue

def _item(file, a, b, text, source, kind=None, verified=False, year=None, extra=None):
    # Stable between builds, so a choice the user made ("use this shot here") still
    # points at the same shot the next time the plan is built.
    import hashlib
    key = f"{source}|{file}|{int(a)}|{int(b)}|{(text or '').strip()[:80]}|{(extra or {}).get('hold_name', '')}"
    item = {'id': hashlib.sha1(key.encode()).hexdigest()[:10], 'file': file, 'in_ms': int(a), 'out_ms': int(b), 'text': text.strip(),
            'source': source, 'kind': kind or classify(text), 'verified': verified, 'year': year, 'moving': True}
    item.update(extra or {})
    return item


def build_catalogue(project, root, guide=None, beats=None, broll_catalog=None):
    """Every described shot this project can use, plus base stills and person photos."""
    root = Path(root)
    assets = {(a.get('original_name') or a.get('name')): a for a in project.get('assets') or []
              if a.get('kind') == 'video' and not a.get('derived_from')}
    roles = people_roles(project, guide)
    items = []
    # 1. The guide's own cards: someone looked at these windows and wrote what they show.
    for card in (guide or {}).get('cards', []):
        if card['window'] and card['source_id']:
            a, b = card['window']
            items.append(_item(card['source_id'] + '.mp4', a, b, card['show'] + ' ' + card['care'], 'guide',
                               verified=True, year=card['year'], extra={'card': card['number']}))
    # 2. Only a catalogue explicitly supplied for THIS project can be used.
    #    The legacy installation bundled a hand-checked catalogue from a different
    #    documentary. Matching S01.mp4 names or durations does NOT prove that its
    #    shots belong to the current case. Never import that source as global truth.
    catalog = broll_catalog
    own = root / 'broll_catalog.json'
    if catalog is None and own.is_file():
        try:
            catalog = json.loads(own.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            catalog = None
    if catalog:
        sources = catalog.get('sources', {})
        same = {k for k, v in sources.items() if (k + '.mp4') in assets
                and abs(float(assets[k + '.mp4'].get('duration') or 0) - float(v.get('duration') or 0)) < 0.6}
        for shot in catalog.get('shots', []):
            if shot.get('source') in same and shot.get('verified', True):
                text = shot.get('what', '') + ' ' + ' '.join(shot.get('tags', []))
                kind = {'place': 'place', 'people': 'people', 'speaker': 'speaker', 'graphic': 'graphic'}.get(shot.get('kind'))
                if classify(text) in ('photo', 'people') and kind == 'place':
                    kind = classify(text)          # "a woman and a child at a gate" is people, not a place
                items.append(_item(shot['source'] + '.mp4', shot['in'] * 1000, shot['out'] * 1000, text, 'catalog',
                                   kind=kind, verified=True))
    # 3. Local analysis: what the vision model saw and what the reporter says per scene.
    for name, asset in assets.items():
        report = root / 'reviews' / 'understanding' / (asset['id'] + '.json')
        if not report.is_file():
            continue
        try:
            data = json.loads(report.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        stages = data.get('stages') or data
        visual = (stages.get('visual') or {}).get('observations') or []
        speech = (stages.get('transcript') or {}).get('segments') or []
        scenes = {}
        for obs in visual:
            key = (obs.get('scene_start_s'), obs.get('scene_end_s'))
            if None in key:
                continue
            scenes.setdefault(key, []).append(obs.get('description') or '')
        for (a, b), texts in scenes.items():
            words = ' '.join(s.get('text', '') for s in speech if s.get('start_s', 0) < b and s.get('end_s', 0) > a)
            items.append(_item(name, a * 1000, b * 1000, ' '.join(texts) + ' ' + words, 'analysis'))
    # 4. The script's own visual directions, as a weaker description of each window.
    for beat in beats or []:
        if beat['kind'] == 'narration' and beat.get('direction'):
            # "End on Octavius Bass pre-frame 2 sec silent" describes the NEXT shot (the
            # bite's speaker), not this window, so it is not part of the description.
            direction = re.sub(r'\bEnd on\b[^.]*\.?', '', beat['direction'], flags=re.I)
            items.append(_item(beat['source_file'], beat['source_in_ms'], beat['source_out_ms'], direction,
                               'script', extra={'beat': beat['label']}))
    # 5. Base pictures from the guide's table. The frame sits inside a moving shot, so
    #    the shot around it becomes a moving base clip. Frames are never used as stills.
    for base in (guide or {}).get('base', []):
        asset = assets.get(base['file'])
        bounds = None
        if asset and (root / asset.get('path', '')).is_file():
            bounds = shot_bounds(root, root / asset['path'], base['at_ms'])
        approx = bounds is None
        if approx:
            bounds = (max(0, base['at_ms'] - 1000), base['at_ms'] + 1000)
        if bounds[1] - bounds[0] >= MIN_PIECE_MS:
            kind = {'V': 'photo', 'S': 'photo', 'C': 'place'}[base['category']]
            items.append(_item(base['file'], bounds[0], bounds[1], base['what'] + ' ' + ' '.join(base['tags']), 'base_clip',
                               kind=kind, verified=True, year=base['year'],
                               extra={'category': base['category'], 'tags': base['tags'], 'base': Path(base['name']).stem,
                                      'approximate': approx}))
    # 6a. B-roll and base pictures from the footage sheet, with what the sheet says they
    #     show. A video is moving footage like any other; a picture is a still, used only
    #     when no moving footage fits the line (see the 'base_photo' step in fill).
    for a in project.get('assets') or []:
        pr = a.get('provenance') or {}
        if a.get('derived_from') or not (pr.get('media') == 'broll' or (pr.get('media') == 'photo' and not pr.get('person') and not pr.get('role') and pr.get('description'))):
            continue
        name = a.get('original_name') or a.get('name')
        label = re.sub(r'[_\-]+', ' ', Path(name).stem)
        text = ' '.join(x for x in (pr.get('description') or a.get('notes') or '', label) if x)
        if a.get('kind') == 'video' and a.get('duration'):
            items.append(_item(name, 0, float(a['duration']) * 1000, text, 'sheet_broll', kind='place', verified=True,
                               extra={'broll': True}))
        elif a.get('kind') == 'image' and (root / a.get('path', '')).is_file():
            items.append(_item(None, 0, 0, text, 'sheet_broll', kind='place', verified=True,
                               extra={'moving': False, 'still': {'kind': 'photo', 'path': a['path']},
                                      'hold_name': 'BASE-' + re.sub(r'[^A-Za-z0-9]+', '_', Path(name).stem).strip('_') + '.mp4',
                                      'broll': True}))
    # 6. People-on-screen photos: the only pictures that are not moving footage, and only
    #    of the victim, a suspect or family, shown when the narration names them.
    for r in roles:
        if r['photo'] and (root / r['photo']).is_file() and r['role'] in ('victim', 'suspect', 'family'):
            items.append(_item(None, 0, 0, f"Photo of {r['name']}", 'person_photo', kind='photo', verified=True,
                               extra={'moving': False, 'still': {'kind': 'photo', 'path': r['photo']},
                                      'hold_name': 'PHOTO-' + re.sub(r'[^A-Za-z0-9]+', '_', r['name']).strip('_') + '.mp4',
                                      'people': {r['id']}}))
    # Derived facts used by the matcher.
    role_of = {r['id']: r['role'] for r in roles}
    for item in items:
        item.setdefault('people', set())
        # A name in quotes is a slogan, banner or poster ("Justice for Maliyah Bass" on a
        # shirt), not the person being in the picture.
        unquoted = re.sub(r'["“][^"”]*["”]', ' ', item['text'])
        item['people'] = set(item['people']) | people_in(unquoted, roles)
        item['surnames'] = surnames(item['text'])
        item['groups'] = groups_in(item['text'])
        item['tokens'] = tokens(item['text'])
        item.setdefault('tags', set())
        item['guide_tags'] = set(item['tags'])          # the guide's own tags, exactly as written
        item['tags'] = set(item['tags']) | item['groups']
        if item['kind'] in ('place',) and not item['people']:
            item['tags'].add('location')
        if 'police' in item['groups']:
            item['tags'].add('police')
        roles_here = {role_of.get(p) for p in item['people']}
        item.setdefault('category', 'S' if 'suspect' in roles_here else 'V' if roles_here & {'victim', 'family'} else
                        'C' if item['kind'] == 'place' else None)
        if item['year'] is None:
            ys = years_in(item['text'])
            item['year'] = ys[-1] if ys else None
        item['available'] = item['still'] is not None if 'still' in item else (item['file'] in assets)
        if item.get('still', {}) and item['still'].get('kind') == 'frame':
            item['available'] = item['still']['file'] in assets
        item['duration_ms'] = int(float(assets[item['file']]['duration']) * 1000) if item['file'] in assets else None
        if item['duration_ms'] and item['out_ms'] > item['duration_ms']:
            item['out_ms'] = item['duration_ms']
    return items, roles


# ---------------------------------------------------------------------- narration



# ---------------------------------------------------------------------- matcher



# ---------------------------------------------------------------------- plan





# Pictures that only stand in for the line: a general place shot, the last-resort
# fallback, or nothing at all. These are the lines the footage does not yet show.






# ---------------------------------------------------------------------- stills -> hold clips

