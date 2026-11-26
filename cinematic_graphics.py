"""Review-stage settings for Storyroom's narration-synchronised graphics.

This module deliberately does not place graphics on the documentary timeline.
It stores the producer's design choices so the same values can be consumed by the
frame renderer after visual approval.
"""

from copy import deepcopy


BACKGROUNDS = ('charcoal', 'midnight', 'warm', 'neutral', 'transparent')
MOTIONS = ('adaptive', 'mask', 'rise', 'slide', 'soft')
DISPLAY_FONTS = ('bahnschrift', 'inter', 'montserrat')
BODY_FONTS = ('inter', 'poppins', 'lora')

DEFAULT = {
    'approved': False,
    'automatic_placement': False,
    'design': {
        'motion': 'adaptive', 'background': 'charcoal',
        'accent': '#DC656C', 'text': '#F1F1EF', 'muted': '#C0C3C9',
        'display_font': 'bahnschrift', 'body_font': 'inter',
        'title_scale': 1.0, 'body_scale': 1.0,
        'speed': 1.0, 'background_motion': 1.0,
    },
    'preview': {'title': '', 'subtitle': ''},
}


def catalogue():
    return {
        'backgrounds': list(BACKGROUNDS), 'motions': list(MOTIONS),
        'display_fonts': list(DISPLAY_FONTS), 'body_fonts': list(BODY_FONTS),
        'automatic_placement_available': False,
    }


def _colour(value, name):
    value = str(value or '').upper()
    if len(value) != 7 or value[0] != '#' or any(x not in '0123456789ABCDEF' for x in value[1:]):
        raise ValueError(f'{name} must be a six-digit colour such as #DC656C.')
    return value


def _number(value, low, high, name):
    try:
        value = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f'{name} must be a number.') from error
    if not low <= value <= high:
        raise ValueError(f'{name} must be between {low:g} and {high:g}.')
    return round(value, 3)


def normalise(value):
    """Return a complete, bounded configuration safe for preview and rendering."""
    value = value if isinstance(value, dict) else {}
    old_design = value.get('design') if isinstance(value.get('design'), dict) else {}
    old_preview = value.get('preview') if isinstance(value.get('preview'), dict) else {}
    design = deepcopy(DEFAULT['design'])
    design.update(old_design)
    for name, choices in (('background', BACKGROUNDS), ('motion', MOTIONS),
                          ('display_font', DISPLAY_FONTS), ('body_font', BODY_FONTS)):
        design[name] = str(design[name]).lower()
        if design[name] not in choices:
            raise ValueError(f'Choose a supported {name.replace("_", " ")}.')
    for name in ('accent', 'text', 'muted'):
        design[name] = _colour(design[name], name.replace('_', ' ').title())
    design['title_scale'] = _number(design['title_scale'], .75, 1.35, 'Title size')
    design['body_scale'] = _number(design['body_scale'], .75, 1.3, 'Body size')
    design['speed'] = _number(design['speed'], .65, 1.65, 'Motion speed')
    design['background_motion'] = _number(design['background_motion'], 0, 1.5, 'Background motion')
    preview = {}
    for name, limit in (('title', 90), ('subtitle', 140)):
        preview[name] = str(old_preview.get(name) or '').strip()
        if len(preview[name]) > limit:
            raise ValueError(f'{name.title()} must be {limit} characters or fewer.')
    # Approval and automatic placement cannot be enabled through this review panel.
    return {'approved': False, 'automatic_placement': False,
            'design': design, 'preview': preview}


def settings(project):
    return normalise(project.get('cinematic_graphics') or DEFAULT)
