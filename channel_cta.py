"""Per-project transparent subscribe card, placed on the finished film clock.

A project must explicitly upload a card. Automatic detection reads approved narrator
text (production Beat script first, otherwise SRT); it does not pretend to hear audio.
Original sound, footage, SRT, source pictures and narrator timing are never changed.
"""
from __future__ import annotations
from pathlib import Path
from functools import lru_cache
import hashlib
import re
from PIL import Image, ImageOps

DEFAULTS = {'enabled': True, 'mode': 'auto', 'entry_style': 'slide', 'opacity': 0.70,
            'width': 0.97, 'position': 'center', 'center_x': 0.50, 'center_y': 0.50, 'motion_style': 'auto_varied',
            'slide_s': 0.55, 'fade_s': 0.25,
            'manual_in_s': None, 'manual_out_s': None,
            # When the narration triggers the card more than once: 'first' shows only
            # the first moment (the mid-story CTA); 'all' shows every moment found.
            'occurrences': 'first'}
_TRIGGER = re.compile(r'\b(?:subscribe|subscribing|notification(?:s)?(?:\s+bell)?|turn\s+on\s+(?:the\s+)?bell|hit\s+(?:the\s+)?bell|like\s+(?:this|the|our)\s+video|like\s+and\s+share)\b', re.I)
_LEAD = re.compile(r'\b(?:if you value|if you enjoy|if you(?:\s+are|\x27re) finding|before we continue|before we go on|if you appreciate|take a moment|support this channel)\b', re.I)
_FOLLOW = re.compile(r'\b(?:subscribe|like|notifications?|the bell|hit the bell|share this video)\b', re.I)


def settings(project):
    raw = project.get('channel_cta') or {}
    out = dict(DEFAULTS)
    for k in DEFAULTS:
        if k in raw: out[k] = raw[k]
    # Upgrade legacy corner/90%-width project geometry exactly once. New
    # projects record center_x/center_y and freely retain their saved placement.
    if 'center_x' not in raw and 'center_y' not in raw:
        # Migrate only previous default/corner layouts; retain any explicit custom width.
        if raw.get('width') in (None, 0.90, 0.38) or raw.get('position') not in (None, 'center'):
            out['width'] = 0.97
        out['center_x'] = out['center_y'] = 0.50
    out['position'] = 'center'  # legacy alias; center_x/center_y own placement
    return out


def motion_for(project, window_index=0):
    """Stable variation per video/window, not nondeterministic preview/export drift.

    `auto_varied` picks one of three physical directions. The same project
    uses the same selection on every seek and export; different projects rotate.
    """
    style = settings(project).get('motion_style') or 'auto_varied'
    if style != 'auto_varied':
        return style
    seed = (str(project.get('id') or '') + '|' + str(project.get('title') or '') +
            '|' + str(window_index)).encode('utf-8')
    return ('top_down', 'left_right', 'right_left')[hashlib.sha256(seed).digest()[0] % 3]


def validate_patch(patch):
    if not isinstance(patch, dict): raise ValueError('CTA settings must be an object.')
    values = {}
    for k, val in patch.items():
        if k not in DEFAULTS: raise ValueError('Unknown CTA setting: '+str(k))
        if k == 'enabled':
            if not isinstance(val, bool): raise ValueError('CTA enabled must be true or false.')
        elif k == 'mode':
            if val not in ('auto', 'manual'): raise ValueError('CTA timing must be automatic or manual.')
        elif k == 'entry_style':
            if val not in ('slide', 'dissolve'): raise ValueError('CTA entrance must be slide or dissolve.')
        elif k == 'position':
            if val != 'center': raise ValueError('Use center_x and center_y to place the CTA card.')
        elif k == 'motion_style':
            if val not in ('auto_varied','top_down','left_right','right_left','dissolve'): raise ValueError('Invalid CTA motion.')
        elif k == 'occurrences':
            if val not in ('first', 'all'): raise ValueError('CTA occurrences must be first or all.')
        elif k in ('opacity','width','center_x','center_y','slide_s','fade_s','manual_in_s','manual_out_s'):
            if val is None and k.startswith('manual_'): pass
            else:
                if isinstance(val,bool): raise ValueError('CTA setting must be a number.')
                try: val=float(val)
                except (ValueError,TypeError): raise ValueError('CTA setting must be a number.')
                from math import isfinite
                if not isfinite(val): raise ValueError('CTA setting must be finite.')
                lo,hi = {'opacity':(0,1),'width':(.20,1.00),'center_x':(0,1),'center_y':(0,1),'slide_s':(.0,2.),'fade_s':(.0,2.),
                         'manual_in_s':(0,4*3600),'manual_out_s':(0,4*3600)}[k]
                if not lo<=val<=hi: raise ValueError(f'{k} must be between {lo} and {hi}.')
        values[k]=val
    return values


def path_for(project, root):
    name = (project.get('channel_cta_asset') or {}).get('file') or ''
    if name not in ('channel_cta.png',): return None
    p = (Path(root)/'assets'/name).resolve()
    return p if p.is_relative_to((Path(root)/'assets').resolve()) and p.is_file() else None


@lru_cache(maxsize=12)
def _from_beats(text):
    try:
        from documentary_beats import read_beats
        beats = read_beats(text)
    except ValueError:
        return None
    spans=[];cursor=0
    for beat in beats:
        start=beat.get('master_in_ms')
        end=beat.get('master_out_ms')
        if start is None or end is None:
            start=cursor
            end=cursor+(beat['narration_out_ms']-beat['narration_in_ms'] if beat['kind']=='narration' else beat['duration_ms'])
        cursor=end
        if beat['kind']=='narration':
            spoken=beat.get('spoken_narration') or ''
            # Narration Beats only: a sound bite's Exact Spoken Dialogue is never read.
            spans.append({'start_ms':start,'end_ms':end,'text':spoken.strip().strip('"'), 'beat':beat['label'],'cue':None})
    return spans


def _from_srt(project, sound_plan):
    blocks=(project.get('srt') or {}).get('blocks') or []
    if not blocks: return []
    spans=[]
    if sound_plan and (project.get('voiceover') or {}).get('duration'):
        from documentary import build_timeline
        try:
            timeline=build_timeline(project,sound_plan)
            segments=[s for s in timeline['segments'] if s['kind']=='narration']
        except (ValueError,KeyError): return []
    else: segments=[]
    for b in blocks:
        start=b.get('start_ms');end=b.get('end_ms')
        if start is None or end is None: continue
        if segments:
            offset=None
            for s in segments:
                a=round(s['source_in_s']*1000);z=round(s['source_out_s']*1000)
                if a<=start<z and end<=z+80:
                    offset=round(s['timeline_in_s']*1000)-a
                    break
            if offset is None:continue
        else:offset=0
        spans.append({'start_ms':start+offset,'end_ms':end+offset,'text':b.get('text',''),'beat':None,'cue':b.get('number')})
    return spans


def _windows(spans):
    found=[]
    for i,sp in enumerate(spans):
        if not _TRIGGER.search(sp['text'] or ''):continue
        first=i;last=i
        # A lead-in is often its own SRT/Beat. Attach one preceding short cue when
        # it explicitly sets up the CTA, without swallowing normal case narration.
        if i>0 and sp['start_ms']-spans[i-1]['end_ms']<250 and _LEAD.search(spans[i-1]['text'] or '') and sp['end_ms']-spans[i-1]['start_ms']<18000:
            first=i-1
        while last+1<len(spans) and spans[last+1]['start_ms']-spans[last]['end_ms']<250 and             spans[last+1]['start_ms']-spans[first]['start_ms']<15000 and _FOLLOW.search(spans[last+1]['text'] or ''):
            last+=1
        begin=spans[first]['start_ms'];finish=spans[last]['end_ms']
        matched=[{'cue':x.get('cue'),'beat':x.get('beat'),'text':(x.get('text') or '')[:200],
                  'start_ms':x['start_ms'],'end_ms':x['end_ms'],'trigger':bool(_TRIGGER.search(x.get('text') or ''))}
                 for x in spans[first:last+1]]
        if found and begin<=found[-1]['end_ms']+300:
            found[-1]['end_ms']=max(found[-1]['end_ms'],finish)
            found[-1]['beats'].extend(s['beat'] for s in spans[first:last+1] if s['beat'])
            found[-1]['matches'].extend(m for m in matched if m not in found[-1]['matches'])
        else:
            found.append({'start_ms':begin,'end_ms':finish,'beats':[s['beat'] for s in spans[first:last+1] if s['beat']],
                          'origin':'narration SRT' if spans[i].get('cue') is not None else 'narrator script','matches':matched})
    return [w for w in found if w['end_ms']>w['start_ms']]


def _with_motions(project, windows):
    return [dict(w, motion_style=motion_for(project, i)) for i,w in enumerate(windows)]


def plan(project, root=None, sound_plan=None):
    """CTA windows on the film clock. With occurrences='first' only the first one."""
    found=detect(project, root, sound_plan)
    if settings(project).get('occurrences','first')=='first':
        return found[:1]
    return found


def detect(project, root=None, sound_plan=None):
    """Every CTA moment the narration triggers (before the first-only rule)."""
    config=settings(project)
    asset=path_for(project,root) if root is not None else None
    if not config['enabled'] or not asset: return []
    if config['mode']=='manual':
        start,end=config['manual_in_s'],config['manual_out_s']
        if start is None or end is None or end<=start: return []
        return _with_motions(project, [{'start_ms':round(start*1000),'end_ms':round(end*1000),'beats':[], 'origin':'manual'}])
    text=(project.get('production_script') or {}).get('text') or ''
    spans=_from_beats(text) if text else None
    if (project.get('srt') or {}).get('blocks'):
        # The SRT is the narrator's real phrase timing. It is mapped onto the finished
        # film clock through the saved sound-bite plan (with or without bites), so it
        # is tried first whether or not the script repeats the spoken words.
        srt_windows=_windows(_from_srt(project, sound_plan))
        if srt_windows: return _with_motions(project, srt_windows)
    if spans is not None:
        # Otherwise fall back to the narration text written in the Beat script.
        return _with_motions(project, _windows(spans))
    return []


def prepared_card(project, root, width, height, work):
    """Rescale a CTA to project geometry without changing its source alpha."""
    source = path_for(project, root)
    if not source: return None
    conf = settings(project)
    with Image.open(source) as f:
        im = ImageOps.exif_transpose(f).convert('RGBA')
    target_w = max(32, round(width * conf['width']))
    target_h = max(16, round(im.height * target_w / im.width))
    if target_h > height:
        ratio = height / target_h
        target_w = max(16, round(target_w * ratio))
        target_h = max(16, round(target_h * ratio))
    im = im.resize((target_w, target_h), Image.Resampling.LANCZOS)
    alpha = im.getchannel('A').point(lambda n: round(n * conf['opacity']))
    im.putalpha(alpha)
    dest = Path(work) / 'channel-cta-wide-v13.png'
    im.save(dest)
    return dest, target_w, target_h


def motion_coordinates(direction, width, height, card_width, card_height, begin, end, slide, fade, center_x=.5, center_y=.5):
    """Return overlay position expressions on the authoritative film clock.

    Slide motions cross the entire screen and leave in the opposite direction.
    The final opacity fade merely softens the last frames and is independent of
    how the image moves. Every value comes from a validated film window.
    """
    x0 = max(0, min(width-card_width, round(float(center_x)*width-card_width/2)))
    y0 = max(0, min(height-card_height, round(float(center_y)*height-card_height/2)))
    if direction == 'dissolve' or slide <= 0:
        return str(x0), str(y0)
    if direction == 'top_down':
        axis, enter, landing, leave = 'y', -card_height - 3, y0, height + 3
    elif direction == 'left_right':
        axis, enter, landing, leave = 'x', -card_width - 3, x0, width + 3
    else:
        axis, enter, landing, leave = 'x', width + 3, x0, -card_width - 3
    # Smoothstep, avoid pop/jerk where slide meets hold; comma-escape for FFmpeg.
    def easing(phase, duration):
        p = f'max(0\\,min(1\\,({phase})/{duration:.6f}))'
        return f'({p}*{p}*(3-2*{p}))'
    in_value = f'({enter}+({landing}-{enter})*{easing(f"t-{begin:.6f}", slide)})'
    out_time = end - slide
    out_value = f'({landing}+({leave}-{landing})*{easing(f"t-{out_time:.6f}", slide)})'
    expression = f'if(lt(t\\,{begin+slide:.6f})\\,{in_value}\\,if(gte(t\\,{out_time:.6f})\\,{out_value}\\,{landing}))'
    return (expression, str(y0)) if axis == 'x' else (str(x0), expression)

def render_filters(project, root, sound_plan, width, height, rate, work, first_input, between=None, cache=None, input_label='base'):
    """Return FFmpeg inputs and steps from [input_label] to [cta].

    The incoming PTS are on the film clock. Each input still is aligned to the
    *same* clock, so animations don't restart when the film is split into pieces.
    """
    store=cache if cache is not None else {}
    if 'windows' not in store: store['windows']=plan(project,root,sound_plan)
    windows=store['windows']
    if not windows:return [], [], 0
    from fractions import Fraction
    fps=Fraction(str(rate));f0,f1=between or (0,4*3600*fps)
    active=[w for w in windows if w['start_ms']*fps/1000 < f1 and w['end_ms']*fps/1000>f0]
    if not active:return [], [], 0
    if 'card' not in store:store['card']=prepared_card(project,root,width,height,work)
    card=store['card']
    if not card:return [],[],0
    filename,cw,ch=card
    conf = settings(project)
    inputs=[];steps=[];label=input_label
    for i, w in enumerate(active):
        a = w['start_ms'] / 1000
        b = w['end_ms'] / 1000
        window_idx = next(j for j, original in enumerate(windows) if original is w)
        direction = motion_for(project, window_idx)
        available = (b - a)
        fade = min(conf['fade_s'], available / 5.)
        slide = min(conf['slide_s'], available / 3.) if direction != 'dissolve' else 0
        x, y = motion_coordinates(direction, width, height, cw, ch, a, b, slide, fade, conf['center_x'], conf['center_y'])
        index=first_input+i
        # v19: the card is decoded once and held, on the film clock from frame f0.
        from still_layers import hold
        inputs += ['-i',str(filename)]
        fades=(f',fade=t=in:st={a:.6f}:d={fade:.6f}:alpha=1'
               f',fade=t=out:st={b-fade:.6f}:d={fade:.6f}:alpha=1') if fade else ''
        steps.append(f'[{index}:v]{hold(rate, int(f1-f0)+1, int(f0))},format=yuva420p{fades}[cta_image_{i}]')
        out=f'cta_{i}'
        steps.append(f"[{label}][cta_image_{i}]overlay=x='{x}':y={y}:eof_action=pass:format=yuv420:enable='gte(t,{a:.6f})*lt(t,{b:.6f})'[{out}]")
        label=out
    if steps:steps[-1]=steps[-1][:steps[-1].rindex('[')]+'[cta]'
    return inputs,steps,len(active)
