"""A curated transition library, and the rule that picks one for each cut.

The catalogue is deliberately short. FFmpeg's xfade filter offers 57 transitions,
and a library that long stops being a choice and becomes a menu nobody reads. These
are the ones that survive being used in a documentary: they read as edits rather than
as effects, and every one of them is symmetric enough not to look broken on a cut
between two wildly different scenes.

Nothing here changes timing. A transition overlaps the outgoing and incoming picture
inside the handles the timeline already reserves, so narration, SRT cues, duration
and audio sync are untouched -- which is the same contract `dissolve` already had.
"""
from __future__ import annotations

# name -> (ffmpeg xfade name, label, one-line description)
#
# `cut` is a real member of the library, not a fallback: on a hard news cut it is the
# most professional choice available, and auto-suggest picks it more often than any
# effect. The descriptions are short because they are shown in a grid of cards.
LIBRARY = {
    'cut': ('', 'Cut', 'Hard cut. No overlap.'),
    'fade': ('fade', 'Cross Fade', 'One scene dissolves into the next.'),
    'fadeblack': ('fadeblack', 'Black Fade', 'Dips through black between scenes.'),
    'fadewhite': ('fadewhite', 'White Fade', 'Flashes through white. Use sparingly.'),
    'dissolve': ('dissolve', 'Dissolve', 'Soft grain blend between pictures.'),
    'distance': ('distance', 'Distance', 'Next scene pushes in through depth.'),
    'pixelize': ('pixelize', 'Pixelate', 'Breaks into blocks, then resolves.'),
    'circleopen': ('circleopen', 'Circle Open', 'Reveal opens from the centre.'),
    'slideleft': ('slideleft', 'Slide', 'Next scene slides in from the right.'),
    'whip': ('slideleft', 'Whip Pan', 'A very fast sideways push into the next scene.'),
    'smoothup': ('smoothup', 'Smooth Rise', 'Picture lifts upward into the next.'),
    'zoomin': ('zoomin', 'Zoom Through', 'Camera pushes through into the next scene.'),
    'fadefast': ('fadefast', 'Quick Fade', 'A short, energetic cross fade.'),
    'fadeslow': ('fadeslow', 'Long Fade', 'A slow blend for reflective beats.'),
    'fadegrays': ('fadegrays', 'Grey Fade', 'Drains to grey, then into the next scene.'),
    'hblur': ('hblur', 'Blur Blend', 'Smears softly from one scene into the next.'),
    'wipeleft': ('wipeleft', 'Wipe', 'A clean edge wipes the next scene across.'),
    'slideright': ('slideright', 'Slide Right', 'Next scene slides in from the left.'),
    'slideup': ('slideup', 'Slide Up', 'Next scene slides up from below.'),
    'smoothleft': ('smoothleft', 'Smooth Pan', 'A soft panning blend to the next scene.'),
    'circleclose': ('circleclose', 'Circle Close', 'The picture closes to a point, then opens.'),
    'radial': ('radial', 'Clock Wipe', 'Sweeps round like a clock hand.'),
    'squeezeh': ('squeezeh', 'Squeeze', 'Squeezes away to reveal the next scene.'),
    'horzopen': ('horzopen', 'Split Open', 'Opens from the middle like a door.'),
    'diagtl': ('diagtl', 'Diagonal', 'A diagonal edge reveals the next scene.'),
}


# What the export page offers in its "Intensity" control. A stronger setting is
# allowed to choose a more visible transition; subtle stays close to a cut.
INTENSITY = {
    'subtle': ('Subtle', ['cut', 'fade', 'dissolve', 'fadefast']),
    'balanced': ('Balanced', ['cut', 'fade', 'dissolve', 'fadefast', 'fadeslow', 'fadeblack']),
    'expressive': ('Expressive', list(LIBRARY)),
}

# Durations in frames at 30fps. The renderer rounds to the nearest whole frame, so
# these are expressed in frames directly rather than seconds that drift.
DURATION = {
    'quick': ('Quick · 0.33 s', 10),
    'standard': ('Standard · 0.50 s', 15),
    'slow': ('Slow · 1.00 s', 30),
}

DEFAULT_DURATION = 'standard'
DEFAULT_INTENSITY = 'balanced'
DURATION_FRAMES = {k: v[1] for k, v in DURATION.items()}


def label(key):
    return LIBRARY.get(key, LIBRARY['cut'])[1]


def is_transition(key):
    return key in LIBRARY and key != 'cut'


def catalogue():
    """Everything the library dialog needs, in one payload."""
    return {'transitions': [{'key': k, 'label': v[1], 'detail': v[2], 'ffmpeg': v[0],
                             'overlaps': bool(v[0])} for k, v in LIBRARY.items()],
            'intensity': [{'key': k, 'label': v[0]} for k, v in INTENSITY.items()],
            'durations': [{'key': k, 'label': v[0], 'frames': v[1]} for k, v in DURATION.items()],
            'defaults': {'intensity': DEFAULT_INTENSITY, 'duration': DEFAULT_DURATION}}


def _pool(intensity):
    return INTENSITY.get(intensity, INTENSITY[DEFAULT_INTENSITY])[1]


# Which transitions suit which feeling. The list is ordered: the first entry that is
# allowed by the current intensity wins, so raising intensity enriches the result
# without ever changing the fact that a reflective beat gets a soft transition.
AFFINITY = {
    'grief': ['fadeslow', 'fade', 'dissolve'],
    'mourning': ['fadeslow', 'fade', 'dissolve'],
    'remembrance': ['fadeslow', 'fade', 'dissolve'],
    'loss': ['fadeslow', 'fade', 'dissolve'],
    'orientation': ['fade', 'smoothup', 'slideleft'],
    'place': ['fade', 'smoothup', 'slideleft'],
    'location': ['fade', 'smoothup', 'slideleft'],
    'scrutiny': ['cut', 'fadefast', 'distance'],
    'investigation': ['fadefast', 'distance', 'cut'],
    'uncertainty': ['dissolve', 'fade', 'cut'],
    'legal': ['cut', 'fade', 'fadeblack'],
    'accountability': ['cut', 'fadeblack', 'fadefast'],
    'clarity': ['cut', 'fade', 'dissolve'],
    'attention / restraint': ['cut', 'fade', 'dissolve'],
}
DEFAULT_AFFINITY = ['cut', 'fade', 'dissolve']


def transition_prev_handle(key, scene):
    """Frames the blend INTO this scene's successor would consume from this scene."""
    return 0 if key == 'cut' else max(1, DURATION_FRAMES.get(key, 15))


def _inside_one_take(scenes, i):
    """True when scene i continues the previous take rather than cutting to a new shot.

    The test is the source interval, not the filename: consecutive beats whose intervals
    touch or overlap are the same continuous run, and blending inside one run is what
    looks like a fault. Beats pulled from different parts of the same clip are separate
    shots and take a transition like any other.
    """
    if i == 0:
        return False
    prev, cur = scenes[i - 1], scenes[i]
    if prev.get('asset_id') != cur.get('asset_id'):
        return False
    if prev.get('in_s') is None or cur.get('in_s') is None:
        # Without source clocks, touching timeline frames mean one continuous segment.
        return prev.get('frame_out') == cur.get('frame_in')
    return abs(float(prev['in_s']) - float(cur['in_s'])) < 0.002


def suggest(scene, previous=None, intensity=DEFAULT_INTENSITY, is_last=False,
            same_source=False, duration_frames=None):
    """Pick a transition for ONE boundary, from that scene's own content.

    The rules, in order:

    1. The last scene never carries a transition -- there is nothing to blend into.
    2. A cut that stays inside one continuous take stays a cut. Blending across a jump
       cut inside a single shot looks like a mistake, not a stylistic choice. Two beats
       taken from the same FILE are not that: a documentary draws many beats from one
       interview clip, and those are ordinary cuts between separate shots.
    3. A very short beat (under half a second) gets a fade at most: any transition
       long enough to see would eat the whole shot.
    4. Otherwise the scene's emotion decides, via AFFINITY.
    5. Two consecutive scenes never receive the same transition unless both resolved
       to a cut. Repeating an effect on every boundary is what makes auto-generated
       edits feel mechanical. Adjacent blends are allowed, but they must leave a whole
       scene between them: a blend may not be longer than the scene it leads into, so
       when two would overlap the incoming scene the second falls back to a cut.
    """
    if is_last:
        return 'cut'
    if same_source:
        return 'cut'
    allowed = _pool(intensity)
    tone = f"{scene.get('emotion', '')} {scene.get('purpose', '')}".lower()

    candidates = []
    for key in AFFINITY:
        if key in tone:
            candidates = AFFINITY[key]
            break
    if not candidates:
        candidates = DEFAULT_AFFINITY
    # Intensity gates the list without discarding its order: Subtle keeps whatever in
    # the affinity list is allowed, falling back to a cut rather than to a loud effect.
    usable = [c for c in candidates if c in allowed]
    if not usable:
        usable = ['cut']

    choice = usable[0]
    if duration_frames is not None and duration_frames < 15 and choice != 'cut':
        # Under half a second there is no room for anything but the briefest blend.
        choice = 'fadefast' if 'fadefast' in allowed else 'cut'
    if previous is not None and choice == previous and choice != 'cut':
        # Step to the next acceptable option so no two boundaries repeat an effect.
        # The wider pool is consulted before falling back to a cut, because "the same
        # effect twice" is a worse outcome than "a slightly less apt effect once".
        rest = [c for c in usable if c != choice] or \
               [c for c in allowed if c != choice and c != 'cut']
        choice = rest[0] if rest else 'cut'
    # A run of cuts is not a problem; a run of the SAME effect is. But an entirely
    # cut-only result on a film whose beats are all investigative would still fail the
    # brief of "make it more engaging", so every other boundary is asked to carry a
    # transition when the intensity allows one at all.
    return choice


def suggest_all(scenes, intensity=DEFAULT_INTENSITY, enrich=False):
    """A transition per scene, each chosen against its own content and its neighbour.

    With `enrich`, a timeline where the affinity rules produced nothing but cuts gets
    alternating transitions on every other boundary. This is the difference between
    "the rules were applied" and "the film has rhythm": a documentary entirely of hard
    cuts is correct but flat, and the request was for something more engaging. Beats
    that genuinely must stay cuts -- the last scene, and runs inside one continuous
    take -- are never touched.
    """
    out = []
    previous = None
    for i, scene in enumerate(scenes):
        same = _inside_one_take(scenes, i)
        length = scene.get('frame_out', 0) - scene.get('frame_in', 0)
        key = suggest(scene, previous=previous, intensity=intensity,
                      is_last=i == len(scenes) - 1,
                      same_source=same, duration_frames=length)
        # A blend needs a handle longer than nothing but shorter than the scene it
        # leads into. If this scene is too short to carry the previous blend as well,
        # it must not open on one.
        if i and transition_prev_handle(out[-1], scenes[i - 1]) >= length:
            key = 'cut'
        out.append(key)
        previous = key
    if enrich:
        allowed = [c for c in _pool(intensity) if c != 'cut']
        if allowed:
            soft = [c for c in ('fade', 'dissolve', 'fadefast', 'fadeslow') if c in allowed]
            last = len(scenes) - 1
            # Two boundaries in a row must never both be cuts on a film that has room
            # for a transition: a run of hard cuts is what makes an automatic pass look
            # like it did nothing. Only a take, or a beat too short to carry a blend,
            # is allowed to interrupt that rhythm.
            for i, scene in enumerate(scenes):
                # `out[i]` is the transition on the boundary AFTER scene i, chosen from
                # scene i's own content. Whether the previous boundary already carries
                # a transition therefore depends on out[i-1], and whether this one must
                # stay a cut depends on the take scene i continues.
                if i == last or out[i] != 'cut':
                    continue
                same = _inside_one_take(scenes, i)
                short = (scene.get('frame_out', 0) - scene.get('frame_in', 0)) < 15
                if same or short:
                    continue
                if i > 0 and out[i - 1] != 'cut':
                    continue          # one transition already separates these beats
                # Avoid repeating whichever effect the previous boundary used.
                choice = next((c for c in soft if c != (out[i - 1] if i else None)), None)
                out[i] = choice or 'cut'
    return out


# ---------------------------------------------------------------------------------
# Documentary (Beat-built) timelines
#
# A Beat timeline is cut at every subtitle line, so most scene boundaries are not
# picture cuts at all: the same footage simply carries on. A transition only means
# something where the picture really changes -- a different file, a jump within one
# file, or a sound bite starting or ending. These helpers find those boundaries the
# same way the renderer merges continuous footage, so what you set is what renders.

# How long each transition runs by default, in frames at 30 fps.
DEFAULT_FRAMES = {'fadefast': 8, 'fadeslow': 30, 'fadeblack': 20, 'fadewhite': 12, 'fadegrays': 20, 'whip': 6}

# The production script's "Cut action" line, read as the transition INTO that Beat.
# Matched in order, longest phrases first; anything that just says CUT stays a cut.
CUT_ACTION_WORDS = [
    ('whip pan', 'whip'), ('whip', 'whip'), ('dip to black', 'fadeblack'), ('fade through black', 'fadeblack'), ('fade to black', 'fadeblack'),
    ('black fade', 'fadeblack'), ('dip to white', 'fadewhite'), ('white flash', 'fadewhite'),
    ('flash', 'fadewhite'), ('quick fade', 'fadefast'), ('fast fade', 'fadefast'),
    ('slow fade', 'fadeslow'), ('long fade', 'fadeslow'), ('grey fade', 'fadegrays'), ('gray fade', 'fadegrays'),
    ('cross fade', 'fade'), ('crossfade', 'fade'), ('cross-fade', 'fade'), ('dissolve', 'dissolve'),
    ('blur', 'hblur'), ('wipe', 'wipeleft'), ('slide up', 'slideup'), ('slide right', 'slideright'),
    ('slide', 'slideleft'), ('push', 'slideleft'), ('pan', 'smoothleft'), ('rise', 'smoothup'),
    ('zoom', 'zoomin'), ('distance', 'distance'), ('circle close', 'circleclose'), ('iris', 'circleopen'),
    ('circle', 'circleopen'), ('clock', 'radial'), ('squeeze', 'squeezeh'), ('split', 'horzopen'),
    ('diagonal', 'diagtl'), ('pixel', 'pixelize'), ('pixelate', 'pixelize'), ('clock wipe', 'radial'),
    ('zoom through', 'zoomin'), ('fade', 'fade'),
]


def from_cut_action(text):
    """The library key a script's Cut action asks for, 'auto', or None for a plain cut.

    `FADE IN FROM BLACK` on the opening Beat is the film's fade-in, handled separately,
    so it is not read as a transition.
    """
    t = ' '.join(str(text or '').lower().replace('_', ' ').split())
    if not t or 'fade in from black' in t:
        return None
    if t in LIBRARY:
        return t if t != 'cut' else None
    for key, (_, name, _) in LIBRARY.items():
        if t == name.lower():
            return key if key != 'cut' else None
    if 'auto' in t:
        return 'auto'
    import re
    # Whole words, longest phrase first: "CLOCK WIPE" is not a plain wipe, and "PAN"
    # must not fire inside "PANORAMA".
    for phrase, key in sorted(CUT_ACTION_WORDS, key=lambda x: -len(x[0])):
        if re.search(r'(?<![a-z])' + re.escape(phrase) + r'(?![a-z])', t):
            return key
    return None


def scene_kind(scene):
    row = scene.get('plan_row') or {}
    return 'sound_bite' if row.get('bite_id') or 'sound-bite' in str(row.get('continuity') or '') else 'narration'


def is_picture_cut(previous, scene):
    """True when the picture really changes between two consecutive scenes."""
    if previous.get('asset_id') != scene.get('asset_id'):
        return True
    if scene_kind(previous) != 'narration' or scene_kind(scene) != 'narration':
        return True
    if (previous.get('picture_scale') or 100) != (scene.get('picture_scale') or 100):
        return True
    a, b = previous.get('plan_row') or {}, scene.get('plan_row') or {}
    if a.get('source_out_ms') is None or b.get('source_in_ms') is None:
        return True
    return abs(float(a['source_out_ms']) - float(b['source_in_ms'])) > 40


def documentary_cuts(scenes):
    """Indexes i where the boundary AFTER scene i is a real picture cut."""
    return [i for i in range(len(scenes) - 1) if is_picture_cut(scenes[i], scenes[i + 1])]


def shot_frames(scenes, cuts):
    """Frame length of the shot that runs up to each cut, and of the shot after it."""
    out = {}
    starts = [0] + [c + 1 for c in cuts]
    ends = [c + 1 for c in cuts] + [len(scenes)]
    lengths = [scenes[e - 1]['frame_out'] - scenes[s]['frame_in'] for s, e in zip(starts, ends)]
    for n, c in enumerate(cuts):
        out[c] = (lengths[n], lengths[n + 1])
    return out


def frames_for(key, duration=None):
    if key == 'cut':
        return 0
    if duration in DURATION:
        base = DURATION[duration][1]
        if key == 'fadefast':
            return max(6, base * 2 // 3)
        if key == 'fadeslow':
            return base * 2
        return base
    return DEFAULT_FRAMES.get(key, 15)


def fit_frames(key, frames, before, after):
    """Shorten a transition so it never eats a whole shot. Too short a shot gets a cut."""
    if key == 'cut' or not frames:
        return 'cut', 0
    room = min(after - 1, before)
    if room < 6:
        return 'cut', 0
    return key, max(4, min(frames, room // 2 if room < 24 else room))


# What "Auto" may use, from gentle to lively. Every pool is ordered so that a run of
# cuts moves through it, giving each cut a different transition from its neighbours.
AUTO_STYLES = {
    # Existing restrained modes stay fully compatible. Pro modes use only existing
    # verified FFmpeg xfade filters; these are original presets, not CapCut plugins.
    'cinematic': ('Cinematic · reads each moment (recommended)', ['cut', 'fadefast', 'fade', 'dissolve', 'hblur',
                  'smoothup', 'smoothleft', 'distance', 'zoomin', 'fadeblack', 'slideleft']),
    'dynamic': ('Dynamic · lively, reads each moment', ['cut', 'fadefast', 'fade', 'dissolve', 'hblur',
                 'smoothup', 'smoothleft', 'distance', 'zoomin', 'fadeblack', 'slideleft', 'slideright',
                 'wipeleft', 'circleopen', 'fadewhite']),
    'truecrime': ('True crime · story-led', ['cut', 'fade', 'dissolve', 'fadefast', 'fadeblack']),
    'restrained': ('True crime · restrained', ['cut', 'fade', 'dissolve', 'fadefast']),
    'subtle': ('Subtle', ['fade', 'dissolve', 'fadefast', 'fadeslow']),
    'balanced': ('Balanced', ['fade', 'dissolve', 'fadeblack', 'fadefast', 'smoothup', 'hblur',
                              'fadeslow', 'distance', 'fadegrays']),
    'expressive': ('Expressive · every cut different',
                   ['fade', 'slideleft', 'dissolve', 'zoomin', 'fadeblack', 'wipeleft', 'smoothup',
                    'circleopen', 'hblur', 'slideright', 'distance', 'fadefast', 'radial', 'smoothleft',
                    'fadegrays', 'slideup', 'squeezeh', 'horzopen', 'diagtl', 'circleclose', 'pixelize',
                    'fadewhite', 'fadeslow']),
}
# Into or out of a person speaking, keep it soft: a slide or a wipe across someone's
# face as they start talking reads as a mistake, not a style.
SPEAKER_SAFE = ['fade', 'dissolve', 'fadefast', 'hblur', 'fadeblack', 'fadegrays']


# Only these effects are shown for Beat-documentary editing. The full legacy
# catalogue remains available to preserve existing projects and non-documentary edits.
TRUE_CRIME_KEYS = ('cut', 'fadefast', 'fade', 'dissolve', 'fadeslow', 'fadeblack', 'fadegrays', 'fadewhite',
                   'hblur', 'smoothleft', 'smoothup', 'zoomin', 'distance', 'whip', 'slideleft', 'slideright',
                   'wipeleft', 'circleopen')  # Curated. Legacy filters still render.


def documentary_catalogue():
    selected = catalogue()
    selected['transitions'] = [t for t in selected['transitions'] if t['key'] in TRUE_CRIME_KEYS]
    return selected


def _story_text(scene):
    row = scene.get('plan_row') or {}
    fields = ('spoken_narration', 'narration', 'voiceover', 'script_text', 'spoken_source_dialogue', 'exact_dialogue',
              'visual_direction', 'direction', 'continuity_note', 'picture_instruction', 'continuity', 'cut_action', 'notes',
              'purpose', 'emotion', 'category', 'focus')
    return ' '.join(str(row.get(k) or scene.get(k) or '') for k in fields).lower()


def _has_any(text, words):
    import re
    return any(re.search(r'\b' + re.escape(w) + r'\b', text) for w in words)


def _truecrime_auto(scenes, style='truecrime', duration=None):
    """Evidence-limited, deterministic scene decisions; never randomize for variety.

    Scripted/manual transition choices are protected by the caller. These rules only
    classify the supplied editorial text and scene metadata; they DO NOT assert that
    the source pictures have been visually verified.
    """
    cuts = documentary_cuts(scenes)
    lengths = shot_frames(scenes, cuts)
    out = {}
    last_soft_at = float('-inf')
    for c in cuts:
        a, b = scenes[c], scenes[c + 1]
        left, right = _story_text(a), _story_text(b)
        combined = left + ' ' + right
        boundary = b.get('frame_in', 0) / 30
        speaker = scene_kind(a) == 'sound_bite' or scene_kind(b) == 'sound_bite'
        before, after = lengths[c]
        choice, reason = 'cut', 'Keep dialogue and factual continuity clear.'
        if speaker:
            reason = 'Interview / original soundbite boundary: preserve a clean, truthful cut.'
        elif _has_any(combined, ('court','judge','charge','charges','prosecutor','police','evidence',
                                 'detective','interview','briefing','investigation','alleged','allegation')):
            reason = 'Factual or investigative sequence: hard cut avoids implying an event or time change.'
        else:
            grief = _has_any(combined, ('memorial','mourning','remembrance','funeral','vigil',
                                        'grief','remember','loss','tribute','prayer'))
            left_grief = _has_any(left, ('memorial','mourning','remembrance','funeral','vigil','grief','tribute'))
            right_grief = _has_any(right, ('memorial','mourning','remembrance','funeral','vigil','grief','tribute'))
            shift = _has_any(right, ('later','meanwhile','years later','days later','afterwards',
                                     'next morning','next day','at the service','at the church',
                                     'community response','back at','in the days'))
            if grief and (left_grief != right_grief or shift):
                choice, reason = 'dissolve', 'Emotional or memorial chapter change: gentle dissolve.'
            elif shift:
                choice, reason = 'fadefast', 'Narration indicates a change of time or setting: short, restrained blend.'
            elif _has_any(right, ('chapter ending','end of chapter','chapter break')):
                choice, reason = 'fadeblack', 'Explicit chapter break: brief dip through black.'
            elif grief and style != 'restrained' and before >= 90 and after >= 90 and boundary-last_soft_at >= 20:
                choice, reason = 'fade', 'Long reflective picture change: gentle cross-fade.'
            else:
                reason = 'No supported narrative change: preserve the hard cut.'
        if choice != 'cut' and boundary - last_soft_at < (30 if style == 'restrained' else 15):
            choice, reason = 'cut', 'Avoid repetitive dissolves; recent nearby transition already provides a pause.'
        if choice != 'cut' and min(before, after) < 18:
            choice, reason = 'cut', 'Shot too short for an unobtrusive transition.'
        if choice != 'cut':
            last_soft_at = boundary
        key, frames = fit_frames(choice, frames_for(choice, 'quick' if choice == 'fadefast' else duration), before, after)
        if key == 'cut' and choice != 'cut':
            reason = 'Insufficient safe frame handles: retain the original hard cut.'
        out[c] = {'key': key, 'frames': frames, 'reason': reason}
    return out




# ---- Story director (v14) ---------------------------------------------------------------
# Reads each real picture cut as an editor would: what the narration says on both sides,
# whether a person starts or stops speaking, whether a photograph arrives or leaves, where
# the cut falls in the film, and how long the shots around it are. Each moment has a short
# list of transitions a professional documentary editor would reach for; the director
# takes the first one that does not repeat what the audience has just seen, so the film
# varies without ever looking random. Same project, same result.
_WORDS = {
    'big_jump': ('years later', 'months later', 'decades later', 'a year later', 'the following year', 'months passed',
                 'years passed', 'fast forward', 'years earlier', 'months earlier', 'years before', 'flashback',
                 'back in', 'decades'),
    'small_jump': ('later', 'meanwhile', 'the next day', 'next morning', 'the following', 'that night', 'that evening',
                   'hours later', 'days later', 'weeks later', 'afterwards', 'afterward', 'eventually', 'by then',
                   'that morning', 'the next morning', 'overnight', 'at dawn', 'by nightfall'),
    'place': ('arrived', 'returned', 'drove', 'travelled', 'traveled', 'outside', 'inside', 'back at', 'at the scene',
              'across town', 'headed to', 'went to', 'neighborhood', 'neighbourhood', 'street', 'apartment', 'house',
              'home', 'hospital', 'station', 'park', 'motel', 'highway', 'road', 'river', 'woods', 'city', 'town'),
    'reveal': ('discovered', 'revealed', 'uncovered', 'suddenly', 'turned out', 'the truth',
               'new evidence', 'breakthrough', 'turning point', 'twist', 'little did', 'no one knew',
               'found out', 'realized', 'realised', 'shocking', 'unexpected'),
    'shock': ('shot', 'shots', 'gunshot', 'gunfire', 'fired', 'stabbed', 'crash', 'crashed', 'explosion', 'attack',
              'attacked', 'screamed', 'scream', 'killed', 'murdered', 'struck', 'beaten', 'opened fire', 'flash'),
    'grief': ('memorial', 'funeral', 'vigil', 'mourning', 'mourned', 'grief', 'grieving', 'tribute', 'remembered',
              'remembrance', 'loss', 'died', 'death', 'passed away', 'buried', 'prayer', 'tears', 'heartbroken'),
    'tension': ('missing', 'vanished', 'disappeared', 'search', 'searched', 'searching', 'dark', 'darkness', 'alone',
                'body', 'found dead', 'no sign', 'silence', 'fear', 'afraid', 'threat', 'stalked', 'hunt', 'manhunt'),
    'investigation': ('police', 'detective', 'detectives', 'investigator', 'investigators', 'evidence', 'court', 'trial',
                      'judge', 'jury', 'charged', 'arrested', 'warrant', 'prosecutor', 'autopsy', 'forensic', 'dna',
                      'interrogation', 'interview room', 'suspect', 'verdict', 'sentenced'),
    'chapter': ('chapter', 'part one', 'part two', 'part three', 'part four', 'act one', 'act two'),
    'memory': ('childhood', 'grew up', 'as a child', 'young', 'photo', 'photograph', 'pictures', 'remember when',
               'family', 'born', 'smile', 'loved'),
}

# Frames at 30 fps for each transition at "Standard" length. Quick/slow scale these.
_MOMENT_FRAMES = {'fadefast': 8, 'hblur': 10, 'whip': 6, 'fadewhite': 9, 'zoomin': 10, 'fade': 14, 'dissolve': 18,
                  'fadeslow': 30, 'fadeblack': 22, 'fadegrays': 20, 'smoothleft': 14, 'smoothup': 14, 'distance': 14,
                  'slideleft': 12, 'slideright': 12, 'slideup': 12, 'wipeleft': 12, 'circleopen': 16, 'horzopen': 14}
_LENGTH_SCALE = {'quick': .7, 'standard': 1.0, 'slow': 1.6, None: 1.0}

# Per moment: (cinematic candidates, dynamic candidates, reason). Order = preference.
_MOMENTS = {
    'opening': (['dissolve', 'fade'], ['distance', 'dissolve', 'fade'], 'Opening of the story: a soft blend eases the viewer in.'),
    'closing': (['fadeslow', 'fadeblack'], ['fadeslow', 'fadeblack'], 'Final picture change: a slow blend lets the ending land.'),
    'chapter': (['fadeblack', 'fadeslow'], ['fadeblack', 'zoomin'], 'New chapter: a dip through black marks the break.'),
    'big_jump': (['fadeblack', 'fadeslow', 'fadegrays'], ['fadeblack', 'fadegrays', 'fadeslow'], 'Large time jump: a deliberate fade tells the viewer time has passed.'),
    'shock': (['fadewhite', 'fadeblack', 'hblur'], ['fadewhite', 'whip', 'zoomin'], 'Sudden violent moment: a short flash or snap carries the impact.'),
    'grief': (['fadeslow', 'dissolve', 'fadegrays'], ['fadeslow', 'fadegrays', 'dissolve'], 'Grief or remembrance: a slow, gentle blend.'),
    'into_bite': (['fadefast', 'cut', 'hblur'], ['hblur', 'fadefast', 'cut'], 'A person starts speaking: a short, clean change keeps their first words clear.'),
    'out_of_bite': (['dissolve', 'fadefast', 'hblur'], ['smoothleft', 'dissolve', 'distance'], 'Back from the interview to the story: the narration picture flows back in.'),
    'bite_to_bite': (['cut', 'fadefast'], ['cut', 'fadefast'], 'One speaker to another: keep the exchange crisp.'),
    'reveal': (['hblur', 'zoomin', 'fadefast'], ['zoomin', 'whip', 'hblur', 'distance'], 'Story turn or reveal: a punch-in or focus snap adds emphasis.'),
    'tension': (['fadeblack', 'hblur', 'fadegrays'], ['hblur', 'fadeblack', 'fadegrays'], 'Tension or danger: a dark, quick dip keeps the unease.'),
    'small_jump': (['fade', 'dissolve', 'smoothleft'], ['smoothleft', 'smoothup', 'fade', 'slideleft'], 'Change of time or setting: a smooth blend moves the story on.'),
    'place': (['smoothleft', 'smoothup', 'fade'], ['smoothleft', 'slideleft', 'smoothup', 'distance', 'slideright'], 'New location: a directional move carries the viewer there.'),
    'photo_in': (['distance', 'fade', 'smoothup'], ['distance', 'circleopen', 'zoomin', 'smoothup'], 'A photograph arrives: it eases in with depth.'),
    'photo_out': (['fade', 'smoothleft', 'dissolve'], ['smoothleft', 'fade', 'slideleft'], 'Leaving a photograph: a soft move back into footage.'),
    'memory': (['dissolve', 'fade', 'fadegrays'], ['dissolve', 'distance', 'fade'], 'Memory or family moment: a warm dissolve.'),
    'investigation': (['cut', 'fadefast', 'hblur'], ['fadefast', 'wipeleft', 'hblur', 'cut'], 'Investigation and facts: crisp changes keep it factual.'),
}
_RHYTHM = {
    'cinematic': ['cut', 'fadefast', 'smoothleft', 'cut', 'fade', 'hblur', 'cut', 'smoothup', 'dissolve', 'cut', 'distance'],
    'dynamic': ['fadefast', 'smoothleft', 'zoomin', 'hblur', 'cut', 'smoothup', 'distance', 'slideleft', 'fade',
                'wipeleft', 'slideright', 'cut'],
}
# Strong moments may sit closer together than the normal breathing space allows.
_STRONG = {'chapter', 'big_jump', 'shock', 'grief', 'opening', 'closing', 'into_bite', 'out_of_bite'}
# Never slide, wipe or zoom across a person who is speaking.
_SPEAKER_SAFE = {'cut', 'fadefast', 'fade', 'dissolve', 'hblur', 'fadeblack', 'fadegrays', 'fadeslow'}


def _is_photo(scene, assets):
    row = scene.get('plan_row') or {}
    if row.get('uploaded_photo') or str(row.get('treatment') or '').upper().startswith('PHOTO'):
        return True
    kind = (assets or {}).get(scene.get('asset_id'))
    return kind == 'image'


def _moments(a, b, c, first, last, assets):
    left, right = _story_text(a), _story_text(b)
    both = left + ' ' + right
    found = []
    if c == first:
        found.append('opening')
    if c == last:
        found.append('closing')
    ka, kb = scene_kind(a), scene_kind(b)
    if ka != 'sound_bite' and kb == 'sound_bite':
        found.append('into_bite')
    elif ka == 'sound_bite' and kb != 'sound_bite':
        found.append('out_of_bite')
    elif ka == kb == 'sound_bite':
        found.append('bite_to_bite')
    for name in ('chapter', 'big_jump', 'shock', 'grief', 'reveal', 'tension', 'small_jump', 'place', 'memory', 'investigation'):
        # A transition introduces what comes next, so it reads the incoming shot.
        text = both if name == 'investigation' else right
        if _has_any(text, _WORDS[name]):
            found.append(name)
    lead = str(b.get('narration') or (b.get('plan_row') or {}).get('spoken_narration') or '').strip().lower()
    if lead.startswith(('but ', 'but,', 'however', 'suddenly', 'until ', 'then,', 'and then', 'that was when',
                        'that is when', "that's when")):
        found.append('reveal')
    if _is_photo(b, assets) and not _is_photo(a, assets):
        found.append('photo_in')
    elif _is_photo(a, assets) and not _is_photo(b, assets):
        found.append('photo_out')
    # Priority: structure first, then the strongest emotional reading.
    order = ['chapter', 'big_jump', 'shock', 'into_bite', 'out_of_bite', 'bite_to_bite', 'grief',
             'reveal', 'tension', 'closing', 'photo_in', 'photo_out', 'small_jump', 'place', 'memory',
             'opening', 'investigation']
    return sorted(set(found), key=order.index)


def _story_director(scenes, style='cinematic', duration=None, assets=None):
    cuts = documentary_cuts(scenes)
    lengths = shot_frames(scenes, cuts)
    out = {}
    if not cuts:
        return out
    dynamic = style == 'dynamic'
    spacing = 1.6 if dynamic else 2.6
    recent = []                       # last effects used, newest last
    from collections import Counter
    seen = Counter()
    last_effect_at = float('-inf')
    rhythm = _RHYTHM['dynamic' if dynamic else 'cinematic']
    # A stable starting point per film, so two different films do not open identically.
    import hashlib
    turn = hashlib.sha256('|'.join(str(s.get('id', '')) for s in scenes[:8]).encode()).digest()[0] % len(rhythm)
    scale = _LENGTH_SCALE.get(duration, 1.0)
    for c in cuts:
        a, b = scenes[c], scenes[c + 1]
        before, after = lengths[c]
        at_s = b.get('frame_in', 0) / 30
        moments = _moments(a, b, c, cuts[0], cuts[-1], assets)
        speaker = scene_kind(a) == 'sound_bite' or scene_kind(b) == 'sound_bite'
        candidates, reason, moment = None, None, None
        for m in moments:
            cin, dyn, why = _MOMENTS[m]
            pool = list(dyn if dynamic else cin)
            # The same kind of moment, met again, gets the next choice in its list.
            k = seen[m] % len(pool); seen[m] += 1
            candidates, reason, moment = pool[k:] + pool[:k], why, m
            break
        if candidates is None:
            # No story signal: keep a professional rhythm of cuts and soft moves.
            candidates = [rhythm[(turn + k) % len(rhythm)] for k in range(len(rhythm))]
            turn += 1
            reason, moment = 'Picture change with no story signal: varied rhythm keeps the edit alive without drawing attention.', 'rhythm'
        if speaker:
            candidates = [k for k in candidates if k in _SPEAKER_SAFE] or ['fadefast', 'cut']
        # Do not repeat what was just used; a hard cut may always repeat.
        fresh = [k for k in candidates if k == 'cut' or k not in recent[-2:]]
        key = (fresh or candidates)[0]
        # Breathing space between visible effects, unless the moment demands one.
        if key != 'cut' and at_s - last_effect_at < spacing and moment not in _STRONG:
            key, reason = 'cut', 'Close to the previous transition: a hard cut keeps the pace clean.'
        base = _MOMENT_FRAMES.get(key, 15)
        frames = max(4, int(round(base * scale))) if key != 'cut' else 0
        key, frames = fit_frames(key, frames, before, after)
        if key == 'cut' and candidates and candidates[0] != 'cut' and reason and not reason.startswith('Close to'):
            if min(before, after) < 12:
                reason = 'Shot too short for a transition: hard cut.'
        if key != 'cut':
            recent.append(key)
            last_effect_at = at_s
        label = LIBRARY.get(key, ('', key.title(), ''))[1]
        out[c] = {'key': key, 'frames': frames, 'reason': reason, 'moment': moment, 'label': label}
    return out


def documentary_auto_details(scenes, style='truecrime', duration=None, seed=0, assets=None):
    if style in ('cinematic', 'dynamic'):
        return _story_director(scenes, style, duration, assets)
    if style in ('truecrime', 'restrained'):
        return _truecrime_auto(scenes, style, duration)
    # Legacy style compatibility only; not offered in the True Crime UI.
    legacy = _legacy_auto_documentary(scenes, style, duration, seed)
    return {k: {'key': v[0], 'frames': v[1], 'reason': 'Legacy transition style'} for k,v in legacy.items()}


def auto_documentary(scenes, style='truecrime', duration=None, seed=0, assets=None):
    return {i: (d['key'], d['frames']) for i,d in documentary_auto_details(scenes,style,duration,seed,assets).items()}


# Backward-compatibility implementation for projects explicitly saved with old styles.
def _legacy_auto_documentary(scenes, style='balanced', duration=None, seed=0):

    """{scene index: (key, frames)} for every real cut, each different from the last.

    `seed` reshuffles the order the style's transitions are used in, so pressing Auto
    again gives a fresh mix. The same seed always gives the same result.
    """
    import random
    pool = list(AUTO_STYLES.get(style, AUTO_STYLES['balanced'])[1])
    if seed:
        random.Random(seed).shuffle(pool)
    cuts = documentary_cuts(scenes)
    lengths = shot_frames(scenes, cuts)
    result = {}
    previous = None
    turn = 0
    for c in cuts:
        before, after = lengths[c]
        speaker = scene_kind(scenes[c]) == 'sound_bite' or scene_kind(scenes[c + 1]) == 'sound_bite'
        choices = [k for k in pool if k in SPEAKER_SAFE] if speaker else pool
        choices = choices or ['fade']
        key = choices[turn % len(choices)]
        if key == previous and len(choices) > 1:
            turn += 1
            key = choices[turn % len(choices)]
        turn += 1
        key, frames = fit_frames(key, frames_for(key, duration), before, after)
        result[c] = (key, frames)
        previous = key
    return result
