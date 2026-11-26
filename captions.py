"""Caption presets: the looks a caption can wear, in one place.

Each preset is one record that produces both renderings of the same choice: the CSS
the editor previews with and the libass (ASS) style ffmpeg burns in with. Fonts are optional local assets. When they are absent, use system-installed Windows
or Linux fonts rather than fail a completed documentary export. The text appearance
can differ slightly across systems when no matching font is installed.

The looks follow the caption styles common in short-form and documentary editing (the
kind CapCut and similar editors offer): clean documentary text, cinema subtitles, heavy
outlined "pop" captions, word-by-word highlight, boxed and news bands. They are built
here from open-licence fonts; nothing is copied from another product.

Sizes are authored at 1080 pixels of picture height and scale with the master.
ASS colours are &HAABBGGRR (AA is transparency, 00 = solid).
"""
from __future__ import annotations

from pathlib import Path

FONT_DIR = Path(__file__).resolve().parent / 'static' / 'fonts'

# file -> (ASS family name, bold flag, CSS family used by the editor's @font-face)
FONTS = {
    'Inter-SemiBold.otf': ('Inter SemiBold', 0, 'SR Inter SemiBold'),
    'Inter-Bold.otf': ('Inter', 1, 'SR Inter Bold'),
    'Inter-ExtraBold.otf': ('Inter ExtraBold', 0, 'SR Inter ExtraBold'),
    'Inter-Black.otf': ('Inter Black', 0, 'SR Inter Black'),
    'Poppins-Medium.ttf': ('Poppins Medium', 0, 'SR Poppins Medium'),
    'Poppins-Bold.ttf': ('Poppins', 1, 'SR Poppins Bold'),
    'Lora-Variable.ttf': ('Lora', 0, 'SR Lora'),
    'DejaVuSans-Bold.ttf': ('DejaVu Sans', 1, 'SR DejaVu Bold'),
}


def _hex(rgb, alpha=0):
    """'#RRGGBB' -> '&HAABBGGRR'."""
    r, g, b = rgb[1:3], rgb[3:5], rgb[5:7]
    return f'&H{alpha:02X}{b}{g}{r}'.upper()


# key -> look. `outline` and `shadow` are in pixels at 1080p. `box` draws a plate
# behind the text (ASS BorderStyle 3). `highlight` colours the word being spoken.
LOOKS = {
    'documentary': dict(label='Documentary', detail='Clean white, soft shadow. Calm and professional.',
                        font='Inter-SemiBold.otf', size=50, color='#FFFFFF', outline=0, outline_color='#000000',
                        shadow=3, upper=False),
    'cinema': dict(label='Cinema', detail='Streaming-service subtitles: white, thin black edge.',
                   font='Inter-Bold.otf', size=52, color='#FFFFFF', outline=2.6, outline_color='#000000',
                   shadow=1.2, upper=False),
    'bold_pop': dict(label='Bold Pop', detail='Heavy capitals, thick black outline. Social-video style.',
                     font='Inter-Black.otf', size=62, color='#FFFFFF', outline=6, outline_color='#000000',
                     shadow=2.5, upper=True),
    'highlight_yellow': dict(label='Word Highlight', detail='Each word turns yellow as it is spoken.',
                             font='Poppins-Bold.ttf', size=58, color='#FFFFFF', outline=5, outline_color='#000000',
                             shadow=2, upper=False, highlight='#FFD400'),
    'highlight_green': dict(label='Highlight Green', detail='Capitals; the spoken word lights up green.',
                            font='Inter-ExtraBold.otf', size=58, color='#FFFFFF', outline=5.5, outline_color='#000000',
                            shadow=2, upper=True, highlight='#3CEB64'),
    'highlight_red': dict(label='True-Crime Red', detail='White capitals; the spoken word turns red.',
                          font='Inter-Black.otf', size=58, color='#FFFFFF', outline=5.5, outline_color='#000000',
                          shadow=2, upper=True, highlight='#FF3B3B'),
    'boxed': dict(label='Boxed', detail='White text on a dark plate. Readable on any picture.',
                  font='Inter-Bold.otf', size=48, color='#FFFFFF', outline=0, outline_color='#000000',
                  shadow=0, upper=False, box='#000000', box_alpha=0x40),
    'news': dict(label='News Band', detail='Dark capitals on a yellow band.',
                 font='Inter-ExtraBold.otf', size=46, color='#111111', outline=0, outline_color='#000000',
                 shadow=0, upper=True, box='#F2C94C', box_alpha=0),
    'serif': dict(label='Cinematic Serif', detail='Elegant serif with a soft shadow. Reflective moments.',
                  font='Lora-Variable.ttf', size=54, color='#FFFFFF', outline=0, outline_color='#000000',
                  shadow=3, upper=False),
    'minimal': dict(label='Minimal', detail='Light, small and out of the way.',
                    font='Poppins-Medium.ttf', size=44, color='#FFFFFF', outline=1.2, outline_color='#000000',
                    shadow=1.5, upper=False),
}

# Older saved projects used these names.
ALIASES = {'clean': 'documentary', 'lower_band': 'boxed', 'kinetic': 'bold_pop'}

SIZES = {'small': ('Small', 0.8), 'medium': ('Medium', 1.0), 'large': ('Large', 1.2), 'xl': ('Extra large', 1.45)}
POSITIONS = {
    # key -> (label, ASS alignment, margin from the edge at 1080p, CSS)
    'bottom': ('Bottom', 2, 60, 'top:auto;bottom:6%;'),
    'lower_third': ('Lower third', 2, 210, 'top:auto;bottom:19%;'),
    'middle': ('Middle', 5, 0, 'top:50%;bottom:auto;transform:translateY(-50%);'),
    'top': ('Top', 8, 70, 'top:6%;bottom:auto;'),
}
DEFAULT = 'documentary'
DEFAULT_SIZE = 'medium'
DEFAULT_POSITION = 'bottom'


def resolve(key):
    key = ALIASES.get(key, key)
    return key if key in LOOKS else DEFAULT


def look(key):
    return LOOKS[resolve(key)]


def _fallback_font_path():
    """An already-installed font. No font binaries are distributed by Storyroom."""
    import os
    from pathlib import Path
    windir = Path(os.environ.get('WINDIR') or os.environ.get('SystemRoot') or r'C:\Windows')
    candidates = (
        windir / 'Fonts' / 'arial.ttf',
        windir / 'Fonts' / 'segoeui.ttf',
        windir / 'Fonts' / 'calibri.ttf',
        Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'),
        Path('/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf'),
        Path('/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf'),
    )
    return next((x for x in candidates if x.is_file()), None)


def font_path(key):
    desired = FONT_DIR / look(key)['font']
    return desired if desired.is_file() else (_fallback_font_path() or desired)


def font_family(key):
    """libass font family matching the selected fontfile or installed fallback."""
    desired = FONT_DIR / look(key)['font']
    if desired.is_file():
        return FONTS[look(key)['font']][0]
    fallback = _fallback_font_path()
    if fallback and 'dejavu' in fallback.name.lower():
        return 'DejaVu Sans'
    if fallback and 'liberation' in fallback.name.lower():
        return 'Liberation Sans'
    return 'Arial'


def _css(look_, scale=1.0):
    family = FONTS[look_['font']][2] if (FONT_DIR / look_['font']).is_file() else 'Arial'
    parts = [f"font-family:'{family}',Inter,system-ui,sans-serif", 'font-weight:normal', f"color:{look_['color']}"]
    shadows = []
    if look_['outline']:
        w = max(1, round(look_['outline'] * 0.42 * scale, 1))
        parts.append(f"-webkit-text-stroke:{w * 2}px {look_['outline_color']};paint-order:stroke fill")
    if look_['shadow']:
        shadows.append(f"0 {max(1, round(look_['shadow'] * .6 * scale))}px {max(2, round(look_['shadow'] * 1.6 * scale))}px rgba(0,0,0,.85)")
    parts.append('text-shadow:' + (','.join(shadows) if shadows else 'none'))
    if look_.get('box'):
        alpha = round(1 - look_.get('box_alpha', 0) / 255, 2)
        r, g, b = (int(look_['box'][i:i + 2], 16) for i in (1, 3, 5))
        parts.append(f'background:rgba({r},{g},{b},{alpha});padding:.12em .45em;border-radius:.18em;'
                     '-webkit-box-decoration-break:clone;box-decoration-break:clone')
    else:
        parts.append('background:none;padding:0')
    if look_['upper']:
        parts.append('text-transform:uppercase;letter-spacing:.01em')
    return ';'.join(parts) + ';'


def css(key):
    return _css(look(key))


_RATIO = {}


def ass_ratio(key):
    """libass sizes text by the font's whole line height (ascent + descent), while the
    editor's CSS and these looks size it by the em. Fonts with tall line metrics
    (Poppins, Lora) therefore came out a third smaller when burned in. Multiplying by
    this ratio makes every look the same visible size in the preview and the export."""
    path = font_path(key)
    if path not in _RATIO:
        try:
            from PIL import ImageFont
            ascent, descent = ImageFont.truetype(str(path), 1000).getmetrics()
            _RATIO[path] = max(0.8, min(1.8, (ascent + descent) / 1000))
        except Exception:
            _RATIO[path] = 1.0
    return _RATIO[path]


def em_size(key, height=1080, size='medium'):
    """The caption's letter (em) size in pixels for a master of this height."""
    factor = SIZES.get(size, SIZES[DEFAULT_SIZE])[1]
    return look(key)['size'] * factor * (height or 1080) / 1080


def ass_style_line(key, height=1080, size='medium', position='bottom', name='Default'):
    """One ASS `Style:` line for this look at the master's height."""
    lk = look(key)
    _, bold, _ = FONTS[lk['font']]
    family = font_family(key)
    scale = (height or 1080) / 1080
    factor = SIZES.get(size, SIZES[DEFAULT_SIZE])[1]
    _, align, margin, _ = POSITIONS.get(position, POSITIONS[DEFAULT_POSITION])
    fontsize = round(em_size(key, height, size) * ass_ratio(key))
    if lk.get('box'):
        border_style, outline, back = 3, max(1, round(10 * scale)), _hex(lk['box'], lk.get('box_alpha', 0))
        outline_colour = back
        shadow = 0
    else:
        border_style, outline, back = 1, round(lk['outline'] * scale * factor, 2), '&H96000000'
        outline_colour = _hex(lk['outline_color'])
        shadow = round(lk['shadow'] * scale, 2)
    return (f"Style: {name},{family},{fontsize},{_hex(lk['color'])},{_hex(lk.get('highlight') or lk['color'])},"
            f"{outline_colour},{back},{-1 if bold else 0},0,0,0,100,100,0,0,{border_style},{outline},{shadow},"
            f"{align},{round(40 * scale)},{round(40 * scale)},{round(margin * scale)},1")


def ass_style_for_size(key, height):
    """A force_style string for the general editor's `subtitles` filter.

    That renderer authors sizes for a 1080p master and scales them with the master's
    height, so a 4K render does not draw quarter-size text.
    """
    lk = look(key)
    _, bold, _ = FONTS[lk['font']]
    family = font_family(key)
    scale = (height or 1080) / 1080
    size = round(round(16 * lk['size'] / 50 * ass_ratio(key) / 1.211, 3) * scale, 2)
    parts = [f'FontName={family}', f'FontSize={size}', f"PrimaryColour={_hex(lk['color'])}", f'Bold={-1 if bold else 0}']
    if lk.get('box'):
        parts += [f"BackColour={_hex(lk['box'], lk.get('box_alpha', 0))}", 'BorderStyle=3', 'Outline=1', 'Shadow=0']
    else:
        parts += [f"OutlineColour={_hex(lk['outline_color'])}", 'BorderStyle=1',
                  f"Outline={round(lk['outline'] * 16 / 50 * scale, 2)}", f"Shadow={round(lk['shadow'] * 16 / 50 * scale, 2)}"]
    parts += ['Alignment=2', f'MarginV={round(34 * scale)}', f'MarginL={round(85 * scale)}', f'MarginR={round(85 * scale)}']
    return ','.join(parts)


def ass_style(key):
    return ass_style_for_size(key, 1080)


def catalogue():
    fonts = [{'family': v[2], 'url': f'/static/fonts/{k}'} for k, v in FONTS.items() if (FONT_DIR / k).is_file()]
    return {'presets': [{'key': k, 'label': v['label'], 'detail': v['detail'], 'css': _css(v),
                         'upper': v['upper'], 'highlight': v.get('highlight'), 'size': v['size'],
                         'font': FONTS[v['font']][2] if (FONT_DIR / v['font']).is_file() else font_family(k)} for k, v in LOOKS.items()],
            'sizes': [{'key': k, 'label': v[0], 'factor': v[1]} for k, v in SIZES.items()],
            'positions': [{'key': k, 'label': v[0], 'css': v[3]} for k, v in POSITIONS.items()],
            'fonts': fonts, 'selected': DEFAULT,
            'defaults': {'size': DEFAULT_SIZE, 'position': DEFAULT_POSITION}}


# Kept for callers that validate a saved key against the library.
PRESETS = {k: (v['label'], v['detail'], _css(v), '') for k, v in LOOKS.items()}
PRESETS.update({k: PRESETS[v] for k, v in ALIASES.items()})


def get(key):
    return PRESETS[resolve(key)]
