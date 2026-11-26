"""Reviewed picture-only cutaways inside uninterrupted documentary soundbites.

Cutaway timestamps are FILM/MASTER clock positions, never narrator-clock pauses.
Nothing here changes documentary_plan.json, the narration, or the soundbite audio.
An unapproved proposal has no effect; an approved but invalid cutaway fails closed.
"""
from __future__ import annotations

import json
import re
from fractions import Fraction
from pathlib import Path

_TIME = re.compile(r'^\d{1,3}:\d{2}:\d{2}[,.]\d{3}$')
_ID = re.compile(r'^CUTAWAY-\d{3,5}$', re.I)


def millis(value, name):
    if type(value) is int and value >= 0:
        return value
    value = str(value or '').strip()
    if not _TIME.fullmatch(value):
        raise ValueError(f'{name}: use HH:MM:SS.mmm on the finished-film clock.')
    hours, minutes, second = value.replace(',', '.').split(':')
    sec, ms = second.split('.')
    if int(minutes) > 59 or int(sec) > 59:
        raise ValueError(f'{name}: minute and second must be below 60.')
    return (int(hours) * 3600 + int(minutes) * 60 + int(sec)) * 1000 + int(ms)


def parse(payload):
    """Accept a JSON handoff or a Markdown table with the documented headings."""
    if isinstance(payload, str):
        source = payload.strip()
        if not source: return []
        if source.startswith('{') or source.startswith('['):
            try: payload = json.loads(source)
            except ValueError as err: raise ValueError('Cutaway JSON cannot be read.') from err
        else:
            lines = [line for line in source.splitlines() if line.strip().startswith('|')]
            if len(lines) < 3:
                raise ValueError('Upload CUTAWAY JSON or a Markdown table with the cutaway headings.')
            clean = lambda line: [x.strip() for x in line.strip().strip('|').split('|')]
            header = [re.sub(r'[^a-z0-9]+', '_', x.lower()).strip('_') for x in clean(lines[0])]
            aliases = {'cutaway_id':'id', 'id':'id', 'soundbite_beat':'soundbite_beat', 'anchor_beat':'soundbite_beat',
                       'film_in':'timeline_in', 'film_out':'timeline_out', 'picture_file':'picture_source',
                       'picture_source':'picture_source','picture_in':'source_in','picture_out':'source_out',
                       'reviewed':'approved','approved':'approved','claim':'reason','reason':'reason','speaker_file':'speaker_source','speaker_source':'speaker_source'}
            if any(k not in aliases for k in header):
                raise ValueError('Cutaway table headings must use ID, Soundbite Beat, Film IN, Film OUT, Picture File, Picture IN, Picture OUT, Approved, Reason.')
            data = []
            for line in lines[1:]:
                cells = clean(line)
                if all(re.fullmatch(r'[-: ]+', x) for x in cells): continue
                if len(cells) != len(header):
                    raise ValueError('A cutaway Markdown row has the wrong number of columns.')
                data.append({aliases[h]: x for h, x in zip(header,cells)})
            payload = data
    if isinstance(payload, dict):
        if payload.get('version') not in (None, 1): raise ValueError('Unsupported cutaway ledger version.')
        payload = payload.get('cutaways', [])
    if not isinstance(payload, list) or len(payload) > 300:
        raise ValueError('The cutaway ledger must contain a list of up to 300 rows.')
    results=[]; ids=set()
    for raw in payload:
        if not isinstance(raw, dict): raise ValueError('Each cutaway row must be an object.')
        id_=str(raw.get('id') or '').strip().upper()
        if not _ID.fullmatch(id_) or id_ in ids: raise ValueError(f'Invalid or repeated cutaway ID: {id_}')
        ids.add(id_)
        approved = raw.get('approved', False)
        if isinstance(approved, str): approved = approved.strip().lower() in ('yes','true','approved','1')
        t0 = millis(raw.get('timeline_in_ms',raw.get('timeline_in')),f'{id_} Film IN')
        t1 = millis(raw.get('timeline_out_ms',raw.get('timeline_out')),f'{id_} Film OUT')
        if t1 <= t0: raise ValueError(f'{id_}: Film OUT must follow Film IN.')
        photo = str(raw.get('picture_source') or '').strip()
        if not photo or photo != Path(photo).name or '/' in photo or '\\' in photo:
            raise ValueError(f'{id_}: picture filename must be an uploaded source basename.')
        raw_in=raw.get('source_in_ms',raw.get('source_in'))
        raw_out=raw.get('source_out_ms',raw.get('source_out'))
        s0 = None if raw_in in (None,'','N/A','n/a','—','-') else millis(raw_in,f'{id_} Picture IN')
        s1 = None if raw_out in (None,'','N/A','n/a','—','-') else millis(raw_out,f'{id_} Picture OUT')
        if (s0 is None) != (s1 is None) or (s0 is not None and s1 <= s0):
            raise ValueError(f'{id_}: provide both valid source IN and OUT, or neither for a photograph.')
        beat = str(raw.get('soundbite_beat') or '').strip().removeprefix('Beat ').strip()
        if not re.fullmatch(r'\d{1,4}',beat): raise ValueError(f'{id_}: name the original soundbite Beat number.')
        results.append({'id':id_,'soundbite_beat':beat.zfill(3),'timeline_in_ms':t0,'timeline_out_ms':t1,
                        'picture_source':photo,'source_in_ms':s0,'source_out_ms':s1,
                        'approved':bool(approved),'reason':str(raw.get('reason') or '')[:1200],
                        'speaker_source':str(raw.get('speaker_source') or '')[:128],
                        'approved_script_sha256':str(raw.get('approved_script_sha256') or '')[:64],
                        'approved_picture_revision':str(raw.get('approved_picture_revision') or '')[:128]})
    results.sort(key=lambda x:(x['timeline_in_ms'],x['timeline_out_ms'],x['id']))
    return results


def _nearest(ms, fps):
    return int(Fraction(ms,1000)*fps + Fraction(1,2))


def _name(asset):
    return asset.get('original_name') or asset.get('name')


def validated(project, root, base_spans, fps):
    """Bind approved entries to uploaded assets and source audio slots; fail closed."""
    data=project.get('documentary_cutaways') or []
    # Keep stored valid data canonical even after direct JSON project editing.
    entries=parse(data)
    assets=project.get('assets') or []
    bind=[];previous_end=-1
    for row in entries:
        if not row['approved']:continue
        label=row['id']; start=_nearest(row['timeline_in_ms'],fps);end=_nearest(row['timeline_out_ms'],fps)
        if start < previous_end: raise ValueError(f'{label}: overlaps another approved cutaway.')
        previous_end=end
        if end <= start: raise ValueError(f'{label}: shorter than one output frame.')
        bites=[s for s in base_spans if s['kind']=='sound_bite' and s['output_start_frame'] <= start and end <= s['output_end_frame']]
        if len(bites)!=1: raise ValueError(f'{label}: must fit inside one uninterrupted original soundbite; check film clock.')
        parent=bites[0]
        if row.get('speaker_source') and row['speaker_source'] != parent['source']:
            raise ValueError(f'{label}: expected speaker source {row["speaker_source"]} but this Beat plays {parent["source"]}.')
        if row.get('approved_script_sha256'):
            import hashlib
            current=hashlib.sha256(((project.get('production_script') or {}).get('text') or '').encode()).hexdigest()
            if row['approved_script_sha256']!=current:
                raise ValueError(f'{label}: the production script changed after cutaway approval; review again.')
        beat=str(parent.get('soundbite_beat') or '').zfill(3)
        # Some legacy picture plans have no beat mapping. Require the fitted Beat label
        # for those instead of accepting an unrelated speaker under a matching film time.
        if beat != row['soundbite_beat']:
            raise ValueError(f'{label}: film time does not belong to soundbite Beat {row["soundbite_beat"]} (found {beat or "unknown"}).')
        matching=[a for a in assets if _name(a)==row['picture_source']]
        if len(matching)!=1: raise ValueError(f'{label}: source {row["picture_source"]} is missing or ambiguous.')
        asset=matching[0];root=Path(root).resolve();src=(root/str(asset.get('path') or '')).resolve()
        if row.get('approved_picture_revision') and row['approved_picture_revision']!=str(asset.get('revision') or ''):
            raise ValueError(f'{label}: cutaway picture was replaced after approval; review the new file.')
        # Videos are decoded into sources/; photographs are stored in assets/ (v23: they
        # were wrongly refused before, so every photo cutaway failed to activate).
        home=root/('assets' if asset.get('kind')=='image' else 'sources')
        if asset.get('kind') not in ('image','video') or not (src.is_relative_to(home) or src.is_relative_to(root/'sources')) or not src.is_file():
            raise ValueError(f'{label}: only a genuinely uploaded picture file can be a cutaway.')
        if asset.get('kind')=='image':
            if row['source_in_ms'] is not None:raise ValueError(f'{label}: photographs use Picture IN/OUT N/A.')
            source_fps=fps;first=0;mode='none'
        else:
            if row['source_in_ms'] is None: raise ValueError(f'{label}: videos require picture-local IN and OUT.')
            if row['source_out_ms'] > float(asset.get('duration') or 0)*1000 + 1:
                raise ValueError(f'{label}: cutaway exceeds {row["picture_source"]} runtime.')
            from strict_cuts import source_rate
            source_fps=Fraction(source_rate(src));first=_nearest(row['source_in_ms'],source_fps)
            n_source=_nearest(row['source_out_ms'],source_fps)-first
            desired=Fraction(end-start,1)/fps
            original=Fraction(n_source,1)/source_fps
            if abs(desired-original) > Fraction(1, fps) + Fraction(1,source_fps):
                raise ValueError(f'{label}: picture range is {float(original):.3f}s but film window is {float(desired):.3f}s; correct IN/OUT.')
            mode='none' if source_fps==fps else 'conform'
            # Same-rate cuts must have the exact number of output frames. A one-frame
            # discrepancy is not an instruction to freeze/drop evidence frames.
            if source_fps==fps and n_source != end-start:
                raise ValueError(f'{label}: video window contains {n_source} frames but film needs {end-start}; align the cut.')
        bind.append(dict(row,asset_id=asset['id'],kind=asset['kind'],output_start_frame=start,output_end_frame=end,
                         source_start_frame=first,source_fps=str(source_fps),frame_conversion=mode))
    return bind


def split_spans(project,root,spans,fps):
    """Change PICTURE spans only; keep the master clock and all audio Beat ranges."""
    # Attach speaker beat labels using the immutable fitted record / scenes metadata.
    beats={s.get('id'):str((s.get('plan_row') or {}).get('script_beat') or '')
           for s in project.get('scenes') or []}
    annotated=[]
    for s in spans:
        clone=dict(s)
        if s['kind']=='sound_bite':
            labels=[beats.get(x,'') for x in s.get('scene_ids') or []]
            clone['soundbite_beat']=next((x for x in labels if re.fullmatch(r'\d+',x)), None)
        annotated.append(clone)
    approved=validated(project,root,annotated,fps)
    if not approved:return spans,[]
    out=[]
    for span in annotated:
        start,end=span['output_start_frame'],span['output_end_frame']
        rows=[r for r in approved if start <= r['output_start_frame'] < end]
        if not rows:
            out.append(span);continue
        cursor=start
        for row in rows:
            if cursor<row['output_start_frame']:
                out.append(_original_piece(span,cursor,row['output_start_frame'],fps))
            count=row['output_end_frame']-row['output_start_frame']
            extra={**span,'asset_id':row['asset_id'],'source':row['picture_source'],'kind':'cutaway',
                   'cutaway_id':row['id'],'source_start_frame':row['source_start_frame'],
                   'source_end_frame':row['source_start_frame']+(count if row['kind']=='image' else
                      _nearest(round(count*1000/float(fps)),Fraction(row['source_fps']))),
                   'source_rate_fps':row['source_fps'],'source_fps':row['source_fps'],
                   'frame_conversion':row['frame_conversion'], 'camera':None,'picture_scale':100,
                   'output_start_frame':row['output_start_frame'],'output_end_frame':row['output_end_frame'],
                   'source_frame_count':count,'output_frame_count':count,'frame_difference':0,
                   'timeline_in_ms':round(row['output_start_frame']*1000/float(fps)),
                   'timeline_out_ms':round(row['output_end_frame']*1000/float(fps))}
            out.append(extra);cursor=row['output_end_frame']
        if cursor<end:out.append(_original_piece(span,cursor,end,fps))
    if sum(x['source_frame_count'] for x in out)!=sum(x['source_frame_count'] for x in spans):
        raise ValueError('Cutaway picture would change the documentary frame count.')
    return out,approved


def _original_piece(span,start,end,fps):
    x=dict(span);src_fps=Fraction(str(span.get('source_rate_fps') or span['source_fps']))
    source_offset=_nearest(round((start-span['output_start_frame'])*1000/float(fps)),src_fps)
    x['source_start_frame']=span['source_start_frame']+source_offset
    x['source_end_frame']=x['source_start_frame']+_nearest(round((end-start)*1000/float(fps)),src_fps)
    x.update(output_start_frame=start, output_end_frame=end,source_frame_count=end-start,output_frame_count=end-start,
             timeline_in_ms=round(start*1000/float(fps)),timeline_out_ms=round(end*1000/float(fps)),
             frame_difference=0,camera=None, picture_scale=span.get('picture_scale',100))
    return x


def split_events(project,root,events):
    """Cutaway-aware browser schedule built from the same reviewed picture plan."""
    if not any(r.get('approved') for r in (project.get('documentary_cutaways') or [])):
        return events
    # The rendered picture plan uses the same master-clock time windows. Use that
    # precise plan rather than allowing browser playback to invent another mapping.
    from documentary import load_plan,annotate_plan
    from documentary_render_plan import plan
    p=plan(project,root,annotate_plan(project,root,load_plan(root)))
    if not p['picture_compatible']: raise ValueError('; '.join(p['errors']))
    results=[]
    for s in p['spans']:
        results.append({'label':s['labels'][0], 'kind':s['kind'], 'asset_id':s['asset_id'],
                        'source':s['source'],'source_start_frame':s['source_start_frame'],
                        'source_end_frame':s['source_end_frame'],
                        'source_fps':s.get('source_rate_fps') or s.get('source_fps'),
                        'timeline_in_ms':s['timeline_in_ms'],'timeline_out_ms':s['timeline_out_ms'],
                        'cutaway_id':s.get('cutaway_id')})
    return results
