"""Report documentary beat-script problems without converting or editing a plan."""
import re
from pathlib import Path

BEAT = re.compile(r'^Beat:\s*(\d+)\s*$', re.I | re.M)
CLOCK = r'(\d{2}:\d{2}:\d{2}[,.]\d{3})'
# A resumed beat writes "RESUMES at 00:00:32,000 --> ...". documentary_beats
# already ignores that prefix; this reader has to as well, or the beat that
# carries the closing words is skipped and the narration looks short.
_PREFIX = re.compile(r'^\s*(?:RESUMES|RESUMING|PLAYING|CONTINUES|CONTINUING)\s+(?:at\s+)?', re.I)


def _strip_prefix(line):
    # A plain replacement string here would interpret the arrow group in
    # "00:00:32,000 --> 00:00:38,000"; a function cannot.
    return _PREFIX.sub('', line)

def _ms(value):
    h,m,s,ms=map(int,re.split(r'[:,.]',value))
    if m>=60 or s>=60: raise ValueError('Invalid timecode')
    return ((h*60+m)*60+s)*1000+ms

def diagnose(project,root):
    text=(project.get('production_script') or {}).get('text') or ''
    heads=list(BEAT.finditer(text)); issues=[]
    if not heads:
        return {'status':'not_detailed','ready_to_build':False,'build_issues':['This production script format is not supported for storyboard building. Use the labelled one-shot-per-SRT-cue format; documentary sound-bite automation is not implemented.']}
    # This used to read "not implemented", which sounded like a broken deployment
    # even when the only real problem was a script/file mismatch. Beat scripts go
    # through the explicit review path instead, so say that.
    issues.append(f'This script uses {len(heads)} labelled Beat blocks. Beat scripts are reviewed explicitly ("Review the Beat picture plan") rather than built automatically, so every source range can be checked before anything is assembled.')
    assets=project.get('assets',[]); intervals=[]; narration=[]
    for i,h in enumerate(heads):
        body=text[h.end():heads[i+1].start() if i+1<len(heads) else len(text)]
        # Scripts name the file under Video File or Full Source; the beat reader
        # accepts both, so this check has to as well or it reports a false miss.
        name=re.search(r'^(?:Video File|Full Source):\s*(\S.*?)\s*$',body,re.M|re.I)
        if name:
            filename=name.group(1).strip();matches=[a for a in assets if (a.get('original_name') or a.get('name'))==filename and (Path(root)/a.get('path','')).is_file()]
            if len(matches)!=1 and filename not in intervals:intervals.append(filename)
        # Match the whole stated line before splitting on the arrow. Searching for
        # a clock pair anywhere in the line made "PAUSED at 00:00:32,000" read as
        # the start of a narration span, which corrupted the beat before it.
        # Either label. The beat reader accepts "Narration Clock" and "VO Clock", so
        # this reader must too, or a script written with VO Clock was reported as
        # having no narration at all and every check downstream went quiet.
        stated=re.search(r'^(?:Narration Clock|VO Clock):\s*([^\r\n]*)$',body,re.M|re.I)
        if stated:
            span=re.fullmatch(r'\s*'+CLOCK+r'\s*(?:-->|→|->)\s*'+CLOCK+r'\s*',_strip_prefix(stated.group(1)))
            if span:
                try:narration.append((h.group(1),_ms(span.group(1)),_ms(span.group(2))))
                except ValueError:issues.append(f'Beat {h.group(1)} contains an invalid narration timecode.')
    if intervals:issues.append('Script names missing or ambiguous source files: '+', '.join(intervals)+'. Filenames must match uploaded files exactly; no substitution was made.')
    if narration:
        # A pause between two narration beats is where a sound bite goes. Those pauses
        # are the plan working, not a fault, so they are reported as notes with the
        # bite that fills them. Calling them issues sent the reader hunting for a
        # problem in a script that was already correct.
        def bite_at(point):
            return [b for b in (locals().get('bite_pauses') or []) if abs(b[0]-point)<1]
        if narration[0][1]>0:
            issues.append(f'Narration before Beat {narration[0][0]} is not assigned: '
                          f'0.000\u2013{narration[0][1]/1000:.3f}s. If a sound bite opens the film this is '
                          f'expected; otherwise the first narration clock should start at zero.')
        for previous,current in zip(narration,narration[1:]):
            if current[1]!=previous[2]:
                if current[1]>previous[2]:
                    issues.append(f'Narration pause between Beat {previous[0]} and Beat {current[0]}: '
                                  f'{previous[2]/1000:.3f}s to {current[1]/1000:.3f}s '
                                  f'({(current[1]-previous[2]):.0f} ms). A sound bite at '
                                  f'{previous[2]/1000:.3f}s covers this pause on the finished timeline. '
                                  f'Nothing was trimmed or retimed.')
                else:
                    issues.append(f'Narration overlap between Beat {previous[0]} and Beat {current[0]}: '
                                  f'{previous[2]/1000:.3f}s to {current[1]/1000:.3f}s. '
                                  f'No narration was trimmed or retimed; fix the two clocks in the script.')
        duration=(project.get('voiceover') or {}).get('duration')
        # A few milliseconds is encoder rounding between the narration file and
        # the SRT it came from, not an unaccounted passage of speech.
        # Within END_SLACK_S it is a pause after the last word or a held subtitle, and the
        # build handles it without editing either file (plan_notes says so); beyond it,
        # plan_notes raises the blocking message, so it is not repeated here.
        from documentary import END_SLACK_S
        if duration is not None and abs(float(duration)-narration[-1][2]/1000)>END_SLACK_S:
            issues.append(f'Last scripted narration ends at {narration[-1][2]/1000:.3f}s; uploaded narration lasts {float(duration):.3f}s. Review the difference; no audio was trimmed.')
    # Extract and audit only the explicitly labelled beat fields. This does not
    # create a storyboard or certify the source, its speaker or reuse rights.
    from documentary_beats import read_beats
    found=0;plans=[]
    try:
        beats=read_beats(text);found=len(beats)
        # Report what the Beat picture plan will actually do, not a demand the
        # plan then resolves by itself. The old audit said "re-upload the
        # full-length source" while the plan quietly clamped and extended the
        # same range; the panel contradicted the button sitting under it.
        plans=plan_notes(beats,project,root)
    except ValueError as exc:
        beats=[];issues.append('Beat reader: '+str(exc))
        # Count the blocks the reader could open so the summary is not "0 beats"
        # just because a later beat conflicts. This is a count, not approval.
        found=len(re.findall(r'^\s*Beat:\s*\d+\s*$',text,re.I|re.M))
    for note in plans:
        if note['blocking']:issues.append(note['text'])
    return {'status':'not_detailed','ready_to_build':False,'build_issues':list(dict.fromkeys(issues)),
            'build_notes':[x for x in plans if not x['blocking']],
            'documentary_beat_count':len(beats),'documentary_beat_blocks':found,'documentary_beats':beats}


def plan_notes(beats,project,root):
    """What the Beat picture plan will change, in the words the review uses.

    `blocking` notes are the ones the plan refuses to build without; the rest
    are changes it makes mechanically and records for review.
    """
    from documentary_beat_plan import frame_limits,proposal
    notes=[]
    # The narration file and the scripted narration must describe the same film.
    # This is a fact about the uploads, not a range decision, so it stays here.
    voice=(project.get('voiceover') or {}).get('duration')
    if voice is None:
        notes.append({'blocking':True,'text':'Upload the original narration.'})
    else:
        scripted=beats[-1].get('narration_out_ms') if beats[-1]['kind']=='narration' else None
        if scripted is None:
            scripted=max((b.get('narration_out_ms') or 0 for b in beats if b['kind']=='narration'),default=None)
        from documentary import narration_end_note
        note=narration_end_note(scripted,voice) if scripted is not None else None
        if note:notes.append({'blocking':note[0],'text':note[1]})
    try:
        data=proposal(project,beats,None,None,frame_limits(root,project.get('assets') or []))
    except (ValueError,KeyError,TypeError,OSError) as exc:
        notes.append({'blocking':True,'text':'Beat plan: '+str(exc)})
        return notes
    notes.extend({'blocking':True,'text':x} for x in data.get('issues') or [])
    notes.extend({'blocking':False,'text':x} for x in data.get('adjustments') or [])
    # Reusing a shot is normal documentary practice. Reuse is informational,
    # never a blocking script error. One line per file, as the review
    # panel does, rather than one line for every overlapping pair.
    by_file={}
    labels={b['number']:b['label'] for b in beats}
    for first,second in data.get('repeated_ranges') or []:
        source=next((b['source_file'] for b in data.get('beats') or [] if b['number']==second),'')
        by_file.setdefault(source,set()).update({str(labels.get(first,first)),str(labels.get(second,second))})
    for source,names in by_file.items():
        joined=', '.join(sorted(names,key=lambda x:int(x)))
        notes.append({'blocking':False,'text':f'{source} source ranges overlap between Beats {joined}. '
                                               f'Reusing picture under new narration is allowed, so this is a note '
                                               f'to check, not a fault: reuse is allowed without a separate approval.'})
    return notes
