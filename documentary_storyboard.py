"""Prepare a documentary review storyboard from explicit beats and approved gaps.

This is a picture/audio PLAN only; it never claims source identity or rights, and
is not a final renderer. Existing scripts, original SRT and media are not changed.
"""
import copy, hashlib, math, uuid
from pathlib import Path
from strict_cuts import source_rate
from documentary import validate_bite, build_timeline
from documentary_beats import read_beats
from documentary_gap_policy import is_subframe_gap

# One output frame at 30 fps, the rounding unit for every picture slot.
FRAME_MS = 34


def prepare(project, root, approved_gaps, approved_overlaps, allow_tail, has_audio, beats=None, allow_consecutive_bites=False, fitted_ranges=None, strict=False, clamp_pauses=False):
    root=Path(root).resolve();beats=beats if beats is not None else read_beats((project.get('production_script') or {}).get('text',''))
    # Direct callers, not only the HTTP preflight, must agree on the two clocks.
    from documentary_beats import reconcile_pause_clocks
    beats, pause_reconciliations = reconcile_pause_clocks(beats)
    if strict:
        from documentary_beats import is_strict_pipeline_script
        from documentary_strict import validate
        if not is_strict_pipeline_script((project.get('production_script') or {}).get('text','')):
            raise ValueError('Exact execution requires a production script with Full source fields.')
        validation=validate(project,root,beats)
        if validation['issues']:
            raise ValueError(' '.join(validation['issues']))
        if approved_gaps or approved_overlaps or allow_tail:
            raise ValueError('Strict execution cannot apply gap footage, source-overlap approvals or silent-tail adjustments. Correct the production script.')
    blocks=(project.get('srt') or {}).get('blocks') or []
    if not blocks or not project.get('voiceover'):raise ValueError('Upload original SRT and narration first.')
    if project.get('scenes'):raise ValueError('An existing storyboard must not be replaced automatically.')
    # Work on a copy: the narration clock below is recorded on the staged project only.
    project=copy.deepcopy(project);project['voiceover'].pop('clock_s',None);project['voiceover'].pop('end_s',None)
    assets=project.get('assets') or [];files={}
    for b in beats:
        matches=[a for a in assets if (a.get('original_name') or a.get('name'))==b['source_file']]
        if len(matches)!=1:raise ValueError(f"Beat {b['label']}: source {b['source_file']} is missing or ambiguous.")
        a=matches[0];path=(root/a.get('path','')).resolve()
        if a.get('kind')!='video' or not path.is_relative_to(root/'sources') or not path.is_file():raise ValueError(f"Beat {b['label']}: uploaded video is missing.")
        duration_ms=float(a.get('duration') or 0)*1000
        if b['source_out_ms']>duration_ms+.001:
            # Name the numbers and the fix; "source OUT exceeds video duration"
            # alone left no clue which range to change.
            raise ValueError(f"Beat {b['label']}: source OUT {b['source_out_ms']/1000:.3f}s is past the end of {b['source_file']} "
                             f"({duration_ms/1000:.3f}s). Review the Beat picture plan so the range is fitted before building, "
                             f"or set Source OUT to {duration_ms/1000:.3f}s or less in the script.")
        files[b['source_file']]=a
    # A script does not have to open or close on narration. The timeline is driven by
    # each beat's own pause point, so a leading bite simply starts at 0.0 and a
    # trailing one plays over the last of the audio; build_timeline handles both.
    # Requiring narration at both ends was a writing convention enforced as a hard
    # failure, which refused otherwise valid productions.
    if not beats:raise ValueError('The production script contains no Beats.')
    # A leading bite is anchored at 0.0 and a closing one at the end of the narration.
    # Those are checked in the bite loop below and rejected if the script says
    # otherwise: retiming a script here would silently move audio the user wrote at a
    # particular timecode, which this planner never does.
    if not isinstance(approved_gaps,list) or not isinstance(approved_overlaps,list):raise ValueError('Provide explicitly approved gap ranges and source overlaps.')
    pairs=set()
    for pair in approved_overlaps:
        if not isinstance(pair,list) or len(pair)!=2 or not all(isinstance(x,int) for x in pair):raise ValueError('Invalid approved overlap.')
        pairs.add(tuple(sorted(pair)))
    # Reused footage, including exact cold-open/main-story replay, is permitted
    # without a per-project overlap approval. Keep the actual pairs in the saved
    # review ledger so export and inspection see the same editorial source plan.
    found=set()
    for i,b in enumerate(beats):
        for a in beats[:i]:
            if a['source_file']==b['source_file'] and b['source_in_ms']<a['source_out_ms'] and b['source_out_ms']>a['source_in_ms']:
                found.add(tuple(sorted((a['number'],b['number']))))
    approved_overlaps=[list(pair) for pair in sorted(found)]
    narratives=[b for b in beats if b['kind']=='narration'];cursor=0;uncovered=[]
    for b in narratives:
        start,end=b['narration_in_ms'],b['narration_out_ms']
        if start<cursor:raise ValueError('Narration blocks overlap.')
        if start>cursor:uncovered.append((cursor,start))
        cursor=end
    voice=float(project['voiceover'].get('duration') or 0);voice_ms=round(voice*1000)
    # The narration duration comes from the uploaded file's container, which is rounded
    # to the nearest millisecond. A script whose final timecode lands a few milliseconds
    # past that is not longer than the audio -- it is the same audio, written out to a
    # third decimal. Measured on a real production: a 368.93s narration against a script
    # ending at 368.933s, a 3ms gap, refused the whole build. One output frame (33ms) is
    # the smallest meaningful difference here, and the end of the narration is snapped to
    # the script when it falls inside that tolerance so no phantom gap is invented.
    FRAME_MS=1000/30
    from documentary import END_SLACK_S
    if cursor>voice_ms+END_SLACK_S*1000:
        last=narratives[-1]['label'] if narratives else '?'
        from documentary import decoded_narration as _dn
        _info=_dn(root,project.get('voiceover')) or {}
        raise ValueError(f'Beat {last}: the script narration runs to {cursor/1000:.3f}s but the uploaded '
                         f'narration is only {voice_ms/1000:.3f}s long'
                         +(f' (decoded {_info["decoded_s"]:.3f}s)' if _info.get('decoded_s') is not None else '')
                         +f' ({(cursor-voice_ms)/1000:.3f}s short). '
                         f'That is more than a held last subtitle: upload the full narration, '
                         f'or correct the final narration clock in the script.')
    # The SRT/script ends a moment after the audio (a subtitle held past the last
    # word). Neither file is changed: the narration clock runs to the script end and
    # the audio is followed by silence for the difference.
    if cursor>voice_ms+FRAME_MS:project['voiceover']['clock_s']=round(cursor/1000,3)
    if cursor>voice_ms:voice_ms=cursor
    script_end_ms=cursor
    # v21: silence after the last Beat's word (no subtitle there) is not part of the
    # film: the narration clock ends on the last word. The audio file is not changed.
    if not strict and cursor<voice_ms:
        from documentary_beat_plan import end_tail
        tail=end_tail(project,beats)
        if tail and tail['kind']=='silence' and tail['from_ms']==cursor:
            project['voiceover']['end_s']=round(cursor/1000,3);voice_ms=cursor
    if cursor<voice_ms:uncovered.append((cursor,voice_ms))
    # The proposal and builder must use the same rule for sub-frame narration
    # remainders. They have no independently renderable picture at 30 fps.
    sub_frame=[(a,b) for a,b in uncovered if is_subframe_gap(a,b)]
    uncovered=[(a,b) for a,b in uncovered if not is_subframe_gap(a,b)]
    gaps={}
    for g in approved_gaps:
        if not isinstance(g,dict) or any(type(g.get(x)) is not int for x in ('narration_in_ms','narration_out_ms','source_in_ms','source_out_ms')):raise ValueError('Gap timing must be integer milliseconds.')
        key=(g['narration_in_ms'],g['narration_out_ms'])
        # A stale browser proposal may still contain a previously offered 5 ms
        # gap. Ignore that old suggestion safely; do not modify the user's SRT
        # or request a synthetic 5 ms source clip.
        if is_subframe_gap(*key):continue
        if key in gaps:raise ValueError('A gap was approved more than once.')
        filename=g.get('source_file');a=files.get(filename)
        if not a:raise ValueError('Gap footage must be an exact uploaded file already named in the script.')
        if g['source_in_ms']<0 or g['source_out_ms']<=g['source_in_ms'] or g['source_out_ms']>float(a['duration'])*1000+.001:raise ValueError('Approved gap footage is outside the source.')
        want=key[1]-key[0];actual=g['source_out_ms']-g['source_in_ms'];last=key[1]==voice_ms
        if abs(actual-want)>1 and not(last and allow_tail is True and 0<=actual-want<=34):raise ValueError('Gap picture duration differs from narration; no speed change or unapproved tail allowed.')
        # An explicitly selected gap may also revisit valid documentary footage;
        # neither a previous Beat nor another gap reserves source frames forever.
        gaps[key]=copy.deepcopy(g)
    if set(gaps)!=set(uncovered):raise ValueError('Explicit gap decisions do not match every uncovered narration interval.')
    bites=[];pause_clamps=[]
    from documentary import narration_clock_s, FRAME_TOLERANCE_S, decoded_narration
    clock_ms=round(narration_clock_s(project)*1000)
    def describe_end():
        info=decoded_narration(root,project.get('voiceover')) or {}
        parts=[f"the narration clock ends at {clock_ms/1000:.3f}s"]
        if info.get('decoded_s') is not None:parts.append(f"decoded audio {info['decoded_s']:.3f}s")
        if info.get('container_s') is not None:parts.append(f"file reports {info['container_s']:.3f}s")
        if info.get('start_offset_s'):parts.append(f"encoder start offset {info['start_offset_s']:.3f}s")
        return '; '.join(parts)
    def clamp(b,limit_ms,why,reviewed=False):
        pause_clamps.append({'beat':b['label'],'script_pause_ms':b['pause_ms'],'clamped_to_ms':limit_ms,
                             'difference_ms':b['pause_ms']-limit_ms,'reviewed':reviewed,'reason':why})
        return dict(b,pause_ms=limit_ms)
    for i,b in enumerate(beats):
        if b['kind']!='sound_bite':continue
        previous=beats[i-1] if i else None;following=beats[i+1] if i+1<len(beats) else None
        joined=allow_consecutive_bites and ((previous and previous['kind']=='sound_bite' and previous['pause_ms']==b['pause_ms']) or (following and following['kind']=='sound_bite' and following['pause_ms']==b['pause_ms']))
        # A bite may open or close the programme. At either edge there is no narration
        # neighbour to anchor it, so its own pause point is the anchor: 0.0 at the
        # start, and the end of the narration at the close. Inside the programme the
        # original rule still applies -- a bite must follow narration, or another bite
        # at the same pause when consecutive bites are approved.
        at_start=i==0;at_end=i+1>=len(beats)
        if at_start and at_end:raise ValueError(f"Beat {b['label']}: the script contains only one beat, and it is a sound bite. Add narration, or upload the full production script.")
        if not at_start and not (previous['kind']=='narration' or joined):raise ValueError(f"Beat {b['label']}: sound bite must follow narration unless consecutive bites are approved.")
        if not at_end and not (following['kind']=='narration' or joined):raise ValueError(f"Beat {b['label']}: sound bite must be followed by narration unless consecutive bites are approved.")
        if at_start:
            if b['pause_ms']!=0:raise ValueError(f"Beat {b['label']}: a sound bite before any narration must start at 00:00:00,000.")
        elif previous['kind']=='narration' and b['pause_ms']!=previous['narration_out_ms']:
            end_ms=previous['narration_out_ms'];over=b['pause_ms']-end_ms
            past_the_end=end_ms>=script_end_ms and b['pause_ms']>clock_ms
            if past_the_end and (over<=FRAME_TOLERANCE_S*1000 or clamp_pauses):
                b=clamp(b,end_ms,'within one output frame of the narration end' if over<=FRAME_TOLERANCE_S*1000 else 'clamped to the narration end after review',reviewed=over>FRAME_TOLERANCE_S*1000)
            else:
                raise ValueError(f"Beat {b['label']}: PAUSED at {b['pause_ms']/1000:.3f}s in the script, but the narration before it "
                                 f"(Beat {previous['label']}) ends at {end_ms/1000:.3f}s ({over/1000:+.3f}s)"
                                 +(f"; {describe_end()}. Correct the PAUSED clock in Beat {b['label']}, or use \"Clamp to narration end\" after review." if past_the_end
                                   else f". Correct the PAUSED clock or the narration clock so they meet."))
        elif previous['kind']=='sound_bite' and b['pause_ms']!=previous['pause_ms']:raise ValueError(f"Beat {b['label']}: consecutive bites must share one pause point.")
        # The voiceover holds a breath of silence after the script's last line. A
        # closing bite written at the last line comes in when the narration file
        # really ends, so none of the voiceover is cut; the silence keeps its picture.
        if not strict and at_end and b['pause_ms']==script_end_ms<voice_ms and voice_ms-script_end_ms<=END_SLACK_S*1000:
            b=dict(b,pause_ms=voice_ms)
        if strict and at_end and b['pause_ms']!=script_end_ms:
            raise ValueError(f"Beat {b['label']}: closing soundbite pause {b['pause_ms']/1000:.3f}s must equal the production script's final narration time {script_end_ms/1000:.3f}s. No pause was shifted.")
        if not strict and at_end and b['pause_ms']!=voice_ms and abs(b['pause_ms']-voice_ms)<=FRAME_TOLERANCE_S*1000:
            b=clamp(b,voice_ms,'closing sound bite within one output frame of the narration end')
        if not strict and at_end and b['pause_ms']>voice_ms and clamp_pauses:
            b=clamp(b,voice_ms,'closing sound bite clamped to the narration end after review',reviewed=True)
        if not strict and at_end and b['pause_ms']!=voice_ms:raise ValueError(f"Beat {b['label']}: a closing sound bite must start at the end of the narration ({voice_ms/1000:.3f}s), but the script pauses at {b['pause_ms']/1000:.3f}s ({(b['pause_ms']-voice_ms)/1000:+.3f}s; {describe_end()})."+(' Correct the PAUSED clock, or use "Clamp to narration end" after review.' if b['pause_ms']>voice_ms else ''))
        # A pause written a few milliseconds past the end of the narration (an MP3/AAC
        # encoder offset, or a timecode rounded to the millisecond) is the same moment
        # once cut to 30 fps frames: clamp it to the narration end and list the clamp.
        if b['pause_ms']>clock_ms:
            over=b['pause_ms']-clock_ms
            if over<=FRAME_TOLERANCE_S*1000:
                b=clamp(b,clock_ms,'within one output frame of the narration end')
            elif clamp_pauses:
                b=clamp(b,clock_ms,'clamped to the narration end after review',reviewed=True)
            else:
                raise ValueError(f"Beat {b['label']}: PAUSED at {b['pause_ms']/1000:.3f}s in the script, but {describe_end()} "
                                 f"— {over/1000:.3f}s after the narration ends. Correct the PAUSED clock in Beat {b['label']}, "
                                 f"or use \"Clamp to narration end\" to move this pause to {clock_ms/1000:.3f}s after review. "
                                 f"No audio was cut and no narration was retimed.")
        try:
            bite=validate_bite(project,root,{'asset_id':files[b['source_file']]['id'],'pause_s':b['pause_ms']/1000,'source_in_s':b['source_in_ms']/1000,'source_out_s':b['source_out_ms']/1000},has_audio)
        except ValueError as exc:
            if 'outside the narration' in str(exc):
                raise ValueError(f'Beat {b["label"]}: PAUSED at {b["pause_ms"]/1000:.3f}s in the script, but {describe_end()}. '
                                 f'Film master starts at {b.get("master_in_ms",0)/1000:.3f}s. '
                                 f'Correct the PAUSED clock in Beat {b["label"]}, or use "Clamp to narration end" after review. '
                                 f'Nothing was shortened or stretched.') from exc
            raise
        bite.update(script_beat=b['label'],script_caption=b['caption'],script_direction=b['direction'],speaker_declared=b.get('speaker',''),
                    anchor_id=b.get('anchor_id',''),exact_dialogue=b.get('exact_dialogue',''),continuity_note=b.get('continuity_note',''),visual_id=b.get('visual_id',''))
        bites.append(bite)
    # A narration-only film (an editing guide with no audio breaks) has no bites; that is
    # a valid programme, not an error.
    plan={'version':1,'revision':1,'bites':bites};build_timeline(project,plan)
    # Sound bites are picture as well as sound. The bite plan places them on the
    # master clock; without a span here the renderer played the narration picture
    # straight through and cut the bite audio in over somebody else's face - whoever
    # is talking has to be visible, so the bite gets the frames that carry it.
    timeline=build_timeline(project,plan)
    bite_spans=[]
    scripted_by_label={b['label']:b for b in beats}
    for seg in timeline['segments']:
        if seg['kind']!='sound_bite':continue
        a=files.get(seg['asset_name'])
        if not a:raise ValueError(f"Sound bite source {seg['asset_name']} is not uploaded.")
        script_beat=next((x.get('script_beat') for x in bites if x['id']==seg['id']),None)
        original=scripted_by_label.get(script_beat or '',{})
        bite_spans.append({'start':round(seg['timeline_in_s']*1000),'end':round(seg['timeline_out_s']*1000),
                           'source_in':round(seg['source_in_s']*1000),'source_out':round(seg['source_out_s']*1000),
                           # The slot carries the speaker the script wrote for this
                           # bite, so the caption burned on the bite and the one the
                           # audit checks are the same string.
                           'filename':seg['asset_name'],'beat':'sound-bite','bite_id':seg['id'],
                           'script_beat':script_beat,
                           'caption':(next((x.get('script_caption') or x.get('caption') or '' for x in bites if x['id']==seg['id']),'') or 'None'),
                           'direction':original.get('direction') or f"Sound bite: {seg['asset_name']} on camera.",
                           'continuity_note':original.get('continuity_note',''),'visual_id':original.get('visual_id',''),
                           'anchor_id':original.get('anchor_id',''),'speaker':original.get('speaker',''),
                           'exact_dialogue':original.get('exact_dialogue',''),'source_duration_ms':original.get('duration_ms'),
                           'beat_source_in_ms':original.get('source_in_ms',round(seg['source_in_s']*1000)),
                           'beat_source_out_ms':original.get('source_out_ms',round(seg['source_out_s']*1000)),
                           'script_master_in_ms':original.get('master_in_ms'),'script_master_out_ms':original.get('master_out_ms'),
                           'narration_in_ms':None,'narration_out_ms':None,
                           'srt_cues':[],
                           'gap':True})
    spans=[]
    for b in narratives:
        spans.append({'start':b['narration_in_ms'],'end':b['narration_out_ms'],'source_in':b['source_in_ms'],'source_out':b['source_out_ms'],'beat_source_in_ms':b['source_in_ms'],'beat_source_out_ms':b['source_out_ms'],'script_master_in_ms':b.get('master_in_ms'),'script_master_out_ms':b.get('master_out_ms'),'narration_in_ms':b['narration_in_ms'],'narration_out_ms':b['narration_out_ms'],'srt_cues':copy.deepcopy(b.get('srt_cues') or []),'filename':b['source_file'],'beat':b['label'],'caption':b['caption'],'direction':b['direction'],'continuity_note':b.get('continuity_note',''),'visual_id':b.get('visual_id',''),'anchor_id':b.get('anchor_id',''),'speaker':b.get('speaker',''),'exact_dialogue':b.get('exact_dialogue',''),'source_duration_ms':b['source_out_ms']-b['source_in_ms'],'gap':False})
    for key,g in gaps.items():
        end=key[1]
        # The approved tail is picture only. Extend to the enclosing output frame.
        if key[1]==voice_ms and g['source_out_ms']-g['source_in_ms']>key[1]-key[0]:end=math.ceil(voice*30-1e-9)*1000/30
        spans.append({'start':key[0],'end':end,'source_in':g['source_in_ms'],'source_out':g['source_out_ms'],'filename':g['source_file'],'beat':'approved-gap','caption':'None','direction':'Approved proposed gap footage; content and rights require review.','gap':True})
    # The narration spans were built on the narration clock, but the picture runs on
    # the master clock the bites created. Rather than shifting coordinates, cut the
    # narration spans at every bite point and emit them segment by segment: each
    # piece keeps its own source range and lands where the timeline says it should.
    bite_by_start={round(b['start']):b for b in bite_spans}
    out=[]
    # Walk the master timeline; within each narration segment, take the part of each
    # narration span that falls inside it.
    for seg in timeline['segments']:
        if seg['kind']=='sound_bite':
            out.append(bite_by_start[round(seg['timeline_in_s']*1000)])
            continue
        # `spans` are already laid out on the master clock: a narration span starts at
        # the script's own narration_in/out marks, which are master-clock marks when
        # the script is written on one continuous clock (every beat's pause point is
        # the previous narration's OUT). So the segment's own narration window is the
        # range to intersect with -- converting through source_in_s compares the voice
        # track's timeline against the edit's, which are two different clocks.
        lo=round(seg['source_in_s']*1000); hi=round(seg['source_out_s']*1000)
        base=round(seg['timeline_in_s']*1000)
        for sp in sorted(spans,key=lambda x:x['start']):
            a0=max(sp['start'],lo); a1=min(sp['end'],hi)
            if a1<=a0: continue
            piece=dict(sp)
            piece['start']=base+(a0-lo)
            piece['end']=base+(a1-lo)
            piece['source_in']=sp['source_in']+(a0-sp['start'])
            piece['source_out']=piece['source_in']+(piece['end']-piece['start'])
            out.append(piece)
    spans=out
    spans.sort(key=lambda x:(x['start'],x['end']));last=0;scenes=[];source_rates={}
    for span in spans:
        # The real narration may outlast its last script/SRT time by just a
        # few milliseconds. The audio is preserved. There is no separate video
        # frame to assign, so a sub-frame boundary before the next soundbite is
        # allowed; output-frame continuity below remains mandatory.
        delta=span['start']-last
        if abs(delta)>.001 and not (delta>0 and is_subframe_gap(last,span['start'])):
            raise ValueError('The picture plan contains a gap or overlap.')
        last=span['end']
        # A sound bite is one continuous piece of transmission: cutting it at a
        # subtitle boundary would splice somebody's sentence into two shots for no
        # editorial reason. Only the narration is indexed against the cues.
        # Subtitle starts are narration-clock times; spans are on the master clock.
        # Map each line into this span through the narration this span plays, or after
        # the first sound bite every cut lands that bite's length away from its line.
        if span.get('beat')=='sound-bite':
            points=[span['start'],span['end']]
        else:
            played=sum(min(sp['end'],span['start'])-sp['start'] for sp in bite_spans if sp['start']<span['start'])
            n0=span['start']-played;n1=n0+(span['end']-span['start'])
            points=[span['start']]+[span['start']+(b['start_ms']-n0) for b in blocks if n0<b['start_ms']<n1]+[span['end']]
        # A subtitle that starts within one output frame of a beat edge (or of another
        # subtitle) cannot be its own slot: it would round to zero frames. Such a split is
        # dropped -- the picture is unchanged, the frame simply belongs to its neighbour.
        kept=[points[0]]
        for x in points[1:-1]:
            if round(x*.03)>round(kept[-1]*.03) and round(points[-1]*.03)>round(x*.03):kept.append(x)
        points=kept+[points[-1]]
        for start,end in zip(points,points[1:]):
            fi,fo=round(start*.03),round(end*.03)
            if fo<=fi:raise ValueError('A script or subtitle boundary is shorter than one output frame.')
            # Scene times are on the master clock; the subtitle cues are on the
            # narration clock. Convert before looking the cue up, or a scene after a
            # sound bite is labelled with the wrong line of the script.
            # Master time to narration time: subtract only the bites that have
            # already finished by this point. Counting bites whose PAUSE sits before
            # this instant was wrong -- a bite's pause point is on the narration
            # clock, not the master clock -- and it swallowed the following line.
            # Only the part of a bite that has ALREADY played sits between the master
            # clock and the narration clock. Counting a whole bite the moment its slot
            # opened shifted every later scene back by the bite's remaining length and
            # labelled it with an earlier line of the script.
            bite_ms=sum(min(sp['end'],start)-sp['start'] for sp in bite_spans if sp['start']<start)
            narr_at=start-bite_ms
            # A line that starts inside this slot's first output frame (its own split was
            # dropped above as sub-frame) belongs to this slot, not to the line before it.
            cue=next((b for b in reversed(blocks) if b['start_ms']<narr_at+500/30),blocks[0]);a=files[span['filename']]
            source_ms=span['source_in']+(start-span['start']);source_end_ms=span['source_in']+(end-span['start'])
            if source_ms<span['source_in']-.001 or source_end_ms>span['source_out']+1:raise ValueError('A picture slot exceeds its explicitly approved source range.')
            try:
                rate_path=str(root/a['path'])
                if rate_path not in source_rates:source_rates[rate_path]=str(source_rate(root/a['path']))
                recorded_fps=source_rates[rate_path]
            except ValueError:recorded_fps=''
            row={'source_fps':recorded_fps,'shot_id':f"Srt{cue['number']:03d}",'source_file':span['filename'],
                 **({'bite_id':span['bite_id']} if span.get('bite_id') else {}),
                 'source_in_ms':round(source_ms),'source_out_ms':round(source_end_ms),
                 'beat_source_in_ms':span.get('beat_source_in_ms',span['source_in']),
                 'beat_source_out_ms':span.get('beat_source_out_ms',span['source_out']),
                 'timeline_in_ms':round(start),'timeline_out_ms':round(end),
                 'narration_in_ms':span.get('narration_in_ms'),'narration_out_ms':span.get('narration_out_ms'),
                 'script_master_in_ms':span.get('script_master_in_ms'),'script_master_out_ms':span.get('script_master_out_ms'),
                 'srt_blocks':[cue['number']],'srt_cues':copy.deepcopy(span.get('srt_cues') or []),
                 'required_caption':span['caption'],'continuity':f"Documentary beat {span['beat']}",
                 'continuity_note':span.get('continuity_note',''),'visual_id':span.get('visual_id',''),
                 'visual_direction':span.get('direction',''),'anchor_id':span.get('anchor_id',''),
                 'speaker_declared':span.get('speaker',''),'exact_dialogue':span.get('exact_dialogue',''),
                 'scripted_duration_ms':span.get('source_duration_ms'),
                 'plain_cue':True,'script_beat':span.get('script_beat') or span['beat']}
            scenes.append({'id':uuid.uuid4().hex[:16],'srt_blocks':[cue['number'],cue['number']],'frame_in':fi,'frame_out':fo,'narration':cue['text'],'purpose':'documentary review','emotion':'neutral','focus':span['direction'] or 'Documentary footage','category':'general','person':'','asset_id':a['id'],'in_s':round(source_ms/1000,6),'motion':'auto','transition':'cut','context_only':False,'notes':'','approved':False,'profile':project.get('profile','documentary'),'focus_position':'center','motion_strength':'subtle','plan_row':row})
    if not scenes or scenes[0]['frame_in']!=0 or any(a['frame_out']!=b['frame_in'] for a,b in zip(scenes,scenes[1:])):raise ValueError('The frame-aligned picture plan has a gap or overlap.')
    _script_transitions(scenes,beats)
    staged=copy.deepcopy(project);staged['scenes']=scenes;staged['review_only_draft']=True;staged['script_moving_only']=True
    staged['script_application']={'recognized_instructions':len(beats),'placed_scenes':len(scenes),'issues':[],'mode':'documentary_beat_review','note':'The production script controls source assignments and ranges. Review source content and identity before final export.'}
    staged['documentary_beat_review']={'strict_execution':bool(strict),
        'pause_clamps':pause_clamps,
        'execution_mode':'pipeline_v5_strict' if strict else 'legacy_fitted',
        'scripted_beats':copy.deepcopy(beats),
        'visual_reviews':{},
        'fitted_beats':[{'label':b['label'],'kind':b['kind'],'source_file':b['source_file'],
        'source_in_ms':b['source_in_ms'],'source_out_ms':b['source_out_ms'],
        'narration_in_ms':b.get('narration_in_ms'),'narration_out_ms':b.get('narration_out_ms'),
        'pause_ms':b.get('pause_ms'),'caption':b['caption'],'visual_id':b.get('visual_id',''),
        'direction':b.get('direction',''),'continuity_note':b.get('continuity_note',''),
        'speaker':b.get('speaker',''),'exact_dialogue':b.get('exact_dialogue',''),
        'anchor_id':b.get('anchor_id',''),'master_in_ms':b.get('master_in_ms'),
        'master_out_ms':b.get('master_out_ms')} for b in beats],
        'fitted_ranges':copy.deepcopy(fitted_ranges),
        # A sound bite's own timeline, saved with the storyboard, so the frame audit
        # can verify the bite's picture slot against the plan it was cut from.
        # The Beat each bite was cut from, and the caption that Beat asks for, have to
        # be saved with it. Without them the audit had no way to tell which scripted
        # caption a slot should carry, and the renderer had nothing to burn on screen;
        # both then reported the bite with an empty caption and silently dropped it.
        'sound_bites':[{'bite_id':seg['id'],
                        'script_beat':next((x['script_beat'] for x in bites if x['id']==seg['id']),None),
                        'source_file':seg['asset_name'],
                        'timeline_in_ms':round(seg['timeline_in_s']*1000),
                        'timeline_out_ms':round(seg['timeline_out_s']*1000),
                        'source_in_ms':round(seg['source_in_s']*1000),
                        'source_out_ms':round(seg['source_out_s']*1000),
                        'required_caption':(next((x.get('script_caption') or '' for x in bites if x['id']==seg['id']),'') or None)}
                       for seg in timeline['segments'] if seg['kind']=='sound_bite'],
        'sub_frame_gaps':[{'narration_in_ms':a,'narration_out_ms':b,'length_ms':b-a} for a,b in sub_frame],'script_sha256':hashlib.sha256(project['production_script']['text'].encode()).hexdigest(),'approved_gaps':copy.deepcopy(approved_gaps),'approved_overlaps':copy.deepcopy(approved_overlaps),'silent_tail_authorized':bool(allow_tail),'warning':'Review only: source content, identity, context and rights are unverified; script captions and final fade are not rendered.'}
    return staged,plan


def verified_source_interval(project, scene, asset):
    """Exact plan range for an unchanged beat-review slot, otherwise None.

    Checking against both the original script and the explicit gap approval prevents
    frame-rounding noise being mistaken for an overlap without forgiving real edits.

    A storyboard is verified against the ranges recorded when it was built. Legacy
    records may include explicitly reviewed fitted ranges; strict Pipeline v5 records
    preserve the exact script values. A strict script or source change makes its review
    stale and blocks playback/export until the storyboard is rebuilt.
    """
    try:
        record=project.get('documentary_beat_review') or {}
        if not record:return None
        row=scene.get('plan_row') or {};filename=asset.get('original_name') or asset.get('name')
        # A transition overlaps the shot before it onto this slot's first frames; the
        # frames this slot is cut from do not change, so its transition is not checked.
        if row.get('source_file')!=filename:return None
        a,b,si,so=(row[k] for k in ('timeline_in_ms','timeline_out_ms','source_in_ms','source_out_ms'))
        if any(type(x) is not int for x in (a,b,si,so)) or b<=a or so<=si:return None
        if scene.get('frame_in')!=round(a*.03) or scene.get('frame_out')!=round(b*.03) or abs(float(scene.get('in_s',-1))*1000-si)>.001:return None
        label=str(row.get('continuity') or '')
        if label=='Documentary beat sound-bite':
            # A sound bite is not a scripted Beat: its range comes from the bite
            # plan, and the plan is what the audio is cut from. Verify the slot
            # against the plan's own IN/OUT rather than against a narration Beat.
            candidates=[]
            for bit in (record.get('sound_bites') or []):
                if bit.get('source_file')!=filename:continue
                candidates.append((bit['timeline_in_ms'],bit['timeline_out_ms'],
                                   bit['source_in_ms'],bit['source_out_ms']))
        elif label=='Documentary beat approved-gap':
            candidates=[]
            for g in record.get('approved_gaps',[]):
                if g.get('source_file')!=filename:continue
                end=g['narration_out_ms']
                if end==round(float(project['voiceover']['duration'])*1000) and record.get('silent_tail_authorized') and g['source_out_ms']-g['source_in_ms']>end-g['narration_in_ms']:
                    end=round(math.ceil(float(project['voiceover']['duration'])*30-1e-9)*1000/30)
                candidates.append((g['narration_in_ms'],end,g['source_in_ms'],g['source_out_ms']))
        elif label.startswith('Documentary beat '):
            number=label[len('Documentary beat '):]
            # Prefer the ranges saved with this storyboard. Strict records hold the
            # exact request; legacy records may contain an explicitly reviewed fit.
            fitted=[x for x in (record.get('fitted_beats') or []) if x.get('kind')=='narration' and x.get('label')==number and x.get('source_file')==filename]
            saved=(record.get('fitted_ranges') or {}).get(number)
            if not fitted and saved and saved.get('source_file')==filename:
                # A storyboard saved before the fitted ranges were embedded can still
                # be verified against the range recorded when it was built.
                fitted=[{'label':number,'kind':'narration','source_file':filename,
                         'narration_in_ms':saved.get('narration_in_ms'),'narration_out_ms':saved.get('narration_out_ms'),
                         'source_in_ms':saved['source_in_ms'],'source_out_ms':saved['source_out_ms']}]
            candidates=[(x['narration_in_ms'],x['narration_out_ms'],x['source_in_ms'],x['source_out_ms'])
                        for x in fitted if x.get('narration_in_ms') is not None and x.get('narration_out_ms') is not None]
        else:return None
        # A narration Beat interrupted by a sound bite appears twice: once before
        # the bite and once after it, both on the same source file. The second
        # piece starts at a source offset the original range never mentioned, so
        # the check has to allow a slot that begins INSIDE the approved range and
        # runs from the matching offset.
        # A slot boundary is rounded to a whole frame (1/30 s = 34 ms), and both
        # ends of every slot are rounded independently, so an interior slot can sit
        # up to one frame past its window without any frame being used twice. Allow
        # exactly that, and nothing more.
        for start,end,source_in,source_out in candidates:
            if a>=start and b<=end and abs(si-(source_in+a-start))<=1 and abs(so-(source_in+b-start))<=1 and so<=source_out+FRAME_MS:
                return si/1000,so/1000
            offset=si-source_in
            if 0<=offset and b>a and so-si==b-a and si+ (b-a) <= source_out+1:
                # Continuation: same Beat, source picked up where the bite left it.
                if source_in <= si and so<=source_out+1:
                    return si/1000,so/1000
    except (ValueError,KeyError,TypeError,OverflowError):pass
    return None


def _script_transitions(scenes, beats):
    """Put each Beat's scripted Cut action on the cut that leads into it.

    Only real picture cuts take a transition; a Beat that continues the same footage
    has nothing to blend. "AUTO" leaves the cut for the automatic picker. A plain
    CUT (the default) stays a hard cut.
    """
    import transitions
    actions = {str(b.get('label')): b.get('cut_action') or '' for b in (beats or [])}
    cuts = transitions.documentary_cuts(scenes)
    lengths = transitions.shot_frames(scenes, cuts)
    for c in cuts:
        incoming = scenes[c + 1]
        label = str((incoming.get('plan_row') or {}).get('script_beat') or '')
        key = transitions.from_cut_action(actions.get(label, ''))
        if key and key != 'auto':
            fitted, frames = transitions.fit_frames(key, transitions.frames_for(key), *lengths[c])
            scenes[c]['transition'] = fitted
            scenes[c]['transition_handle_frames'] = frames
            scenes[c]['transition_source'] = 'script'
        elif key == 'auto':
            scenes[c]['transition_source'] = 'script-auto'
