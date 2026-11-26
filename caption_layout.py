"""Short one-line SRT phrase presentation for rendering; never edits the uploaded SRT."""
import re
from PIL import ImageFont


def _stamp(ms):
    # ASS/libass uses centiseconds (as it also does when reading SRT directly).
    cs = max(0, (int(ms) + 5) // 10)
    return f'{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}'


def caption_phrases(blocks, max_chars=36, max_words=6):
    """Split each SRT cue into short readable phrases with estimated within-cue timing.

    SRT has no word timestamps: weighted character counts provide an approximation,
    not speech alignment. Preserve all words and punctuation, and never cross cues.
    """
    result=[]
    for index,cue in enumerate(blocks):
        words=str(cue.get('text','')).split()
        if not words: continue
        chunks=[];current=[]
        for word in words:
            if current and (len(current)>=max_words or len(' '.join(current+[word]))>max_chars):
                chunks.append(current);current=[]
            current.append(word)
            if len(' '.join(current))>=16 and re.search(r'[.!?;:,]["\'”’)]*$',word):
                chunks.append(current);current=[]
        if current:chunks.append(current)
        start=int(cue['start_ms']);end=int(cue['end_ms']);duration=end-start
        # Avoid creating unrepresentable centisecond events in a very short cue.
        if duration < len(chunks)*20:chunks=[words]
        weights=[sum(len(w) for w in c) for c in chunks];total=sum(weights);done=0
        group=[]
        for chunk,weight in zip(chunks,weights):
            a=start+round(duration*done/total);done+=weight;b=start+round(duration*done/total)
            group.append({'cue_index':index,'text':' '.join(chunk),'start_ms':a,'end_ms':b})
        if any(_stamp(x['start_ms'])==_stamp(x['end_ms']) for x in group):
            group=[{'cue_index':index,'text':' '.join(words),'start_ms':start,'end_ms':end}]
        result.extend(group)
    return result


def _ass_text(text):
    return text.replace('\\', '\\\\').replace('{', '\\{').replace('}', '\\}')


def _ass_colour(rgb):
    return f'&H{rgb[5:7]}{rgb[3:5]}{rgb[1:3]}&'.upper()


def make_single_line_ass(blocks, width, height, preset=None, size=None, position=None):
    """Burned-in subtitles in the project's caption style. No cue text is changed.

    Each phrase is fitted to one line in the style's own font (shipped with the
    editor, so the measurement matches what libass draws). A word-highlight style
    gets one event per word, with the spoken word coloured, timed across the phrase.
    """
    import captions
    key = captions.resolve(preset or captions.DEFAULT)
    look = captions.look(key)
    size = size if size in captions.SIZES else captions.DEFAULT_SIZE
    position = position if position in captions.POSITIONS else captions.DEFAULT_POSITION
    xres = round(1080 * width / height)
    max_width = xres * .86
    style = captions.ass_style_line(key, 1080, size, position)
    base = round(captions.em_size(key, 1080, size))
    ratio = captions.ass_ratio(key)
    try:
        font = ImageFont.truetype(str(captions.font_path(key)), base)
    except OSError as exc:
        raise ValueError('The caption font that ships with the editor is missing from static/fonts.') from exc
    header = f'''[Script Info]
ScriptType: v4.00+
PlayResX: {xres}
PlayResY: 1080
WrapStyle: 2
ScaledBorderAndShadow: yes
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
{style}
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    highlight = look.get('highlight')
    lines = []
    for cue in caption_phrases(blocks):
        text = re.sub(r'\s*\n\s*', ' ', str(cue.get('text', ''))).strip()
        if not text:
            continue
        shown = text.upper() if look['upper'] else text
        # SRT words stay intact; only original line breaks become spaces on screen.
        length = max(1.0, font.getlength(shown))
        # Measured at the em size (PIL), written in libass's line-height units.
        fs = max(1, round(min(base, base * max_width / (length + base * .4)) * ratio))
        start, end = _stamp(cue['start_ms']), _stamp(cue['end_ms'])
        if start == end:
            raise ValueError('An SRT cue is too short for subtitle rendering.')
        words = shown.split()
        if not highlight or len(words) < 2:
            lines.append(f'Dialogue: 0,{start},{end},Default,,0,0,0,,{{\\q2\\fs{fs}}}{_ass_text(shown)}')
            continue
        # SRT has no word times: share the phrase's time by word length, the same
        # estimate the editor's preview uses, so the two highlight the same word.
        weights = [len(w) + 1 for w in words]
        total = sum(weights)
        a, b = int(cue['start_ms']), int(cue['end_ms'])
        done = 0
        colour = _ass_colour(highlight)
        for i, w in enumerate(words):
            s0 = a + round((b - a) * done / total); done += weights[i]; s1 = a + round((b - a) * done / total)
            if _stamp(s0) == _stamp(s1):
                continue
            body = ' '.join((f'{{\\c{colour}}}{_ass_text(x)}{{\\r}}' if j == i else _ass_text(x)) for j, x in enumerate(words))
            lines.append(f'Dialogue: 0,{_stamp(s0)},{_stamp(s1)},Default,,0,0,0,,{{\\q2\\fs{fs}}}{body}')
    return header + '\n'.join(lines) + '\n'
