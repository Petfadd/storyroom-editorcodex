"""Non-destructive sound-bite plans. Existing edits, media and SRT are never rewritten."""
from pathlib import Path
import json, math, time, uuid


def load_plan(root):
    path=Path(root)/'documentary_plan.json'
    if not path.exists():return {'version':1,'revision':0,'bites':[]}
    data=json.loads(path.read_text(encoding='utf-8'))
    if data.get('version')!=1 or not isinstance(data.get('bites'),list):raise ValueError('The documentary plan could not be read. It was not changed.')
    return data


def _number(value,label):
    if isinstance(value,bool):raise ValueError(f'{label} must be a time in seconds.')
    try:value=float(value)
    except (TypeError,ValueError):raise ValueError(f'{label} must be a time in seconds.')
    if not math.isfinite(value):raise ValueError(f'{label} must be a finite time.')
    return round(value,3)


# How far the end of the SRT/script may sit from the end of the narration file. The
# file usually carries a breath of silence after the last word, and subtitle tools
# often hold the last line a moment past the audio. Neither file is edited for it:
# the picture covers the silence, or the audio is followed by silence up to the last
# subtitle. A bigger difference is a different recording, and stays an error.
END_SLACK_S = 3.0


def narration_clock_s(project):
    """Length of the narration clock: the file, or the SRT/script end if that is later.

    `clock_s` is set by the storyboard build only when the script ends after the file
    (by at most END_SLACK_S); a new narration upload replaces the record and clears it.
    """
    voice = project.get('voiceover') or {}
    duration = float(voice.get('duration') or 0)
    # v21: silence after the last word (set by the Beat build, at most 10 s) is left out.
    end = voice.get('end_s')
    if isinstance(end, (int, float)) and not isinstance(end, bool) and duration - 10.5 <= end < duration:
        return round(float(end), 3)
    clock = voice.get('clock_s')
    if isinstance(clock, (int, float)) and not isinstance(clock, bool) and duration < clock <= duration + END_SLACK_S + .001:
        return round(float(clock), 3)
    return duration


# One output frame at 30 fps. A pause or Beat end this close to the narration's end is
# the same moment once the film is cut to frames; it is clamped, and the clamp listed.
FRAME_TOLERANCE_S = 1 / 30 + .0001

_DECODED = {}


def decoded_narration(root, voice):
    """Narration length as actually decoded, plus the container figures, in seconds.

    MP3 and AAC files carry an encoder delay and padding: the container (and ffprobe)
    may report a length a few hundredths of a second different from the samples a
    decoder returns. FFmpeg drops the delay/padding the file declares, so counting the
    decoded samples gives the true playable length. Cached per file size and mtime.
    Returns {'decoded_s', 'container_s', 'start_offset_s', 'sample_rate'} or None.
    """
    import re, subprocess
    path = Path(root) / (voice or {}).get('path', '')
    if not (voice or {}).get('path') or not path.is_file():
        return None
    stat = path.stat()
    key = (str(path.resolve()), stat.st_size, stat.st_mtime_ns)
    if key in _DECODED:
        return _DECODED[key]
    try:
        import imageio_ffmpeg
        ff = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        ff = 'ffmpeg'
    try:
        head = subprocess.run([ff, '-hide_banner', '-nostdin', '-i', str(path)], capture_output=True, text=True,
                              encoding='utf-8', errors='replace', timeout=30).stderr
        rate_match = re.search(r'Audio:.*?(\d{4,6}) Hz', head)
        rate = int(rate_match[1]) if rate_match else 48000
        dur = re.search(r'Duration: (\d+):(\d+):(\d+\.\d+)', head)
        start = re.search(r'start: (-?\d+\.\d+)', head)
        proc = subprocess.Popen([ff, '-hide_banner', '-nostdin', '-loglevel', 'error', '-i', str(path), '-map', '0:a:0',
                                 '-ac', '1', '-ar', str(rate), '-f', 's16le', '-'], stdout=subprocess.PIPE)
        total = 0
        while True:
            chunk = proc.stdout.read(1 << 20)
            if not chunk:
                break
            total += len(chunk)
        proc.wait(timeout=600)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    if not total:
        return None
    result = {'decoded_s': round(total / 2 / rate, 4),
              'container_s': round(int(dur[1]) * 3600 + int(dur[2]) * 60 + float(dur[3]), 4) if dur else None,
              'start_offset_s': round(float(start[1]), 4) if start else 0.0, 'sample_rate': rate}
    _DECODED[key] = result
    return result


def narration_end_note(script_end_ms, voice_s):
    """Compare the script/SRT end with the narration file. Returns (blocking, text) or None."""
    diff = float(voice_s) - script_end_ms / 1000
    if abs(diff) <= .25:
        return None
    if abs(diff) <= END_SLACK_S:
        if diff > 0:
            return (False, f'The narration file runs {diff:.3f}s past the last subtitle ({script_end_ms/1000:.3f}s): '
                           f'silence after the last word. Nothing is cut; the picture keeps running over it.')
        return (False, f'The last subtitle ends {-diff:.3f}s after the narration file ({float(voice_s):.3f}s). '
                       f'Nothing is cut or retimed: the film runs to the end of the SRT, with silence after the last word.')
    return (True, f'The script ends its narration at {script_end_ms/1000:.3f}s, but the uploaded narration '
                  f'file lasts {float(voice_s):.3f}s ({diff:+.3f}s). That is more than a pause or a held '
                  f'subtitle ({END_SLACK_S:.0f}s): either the narration file includes words the script does not '
                  f'account for, the script is missing the closing narration block, or this is a different '
                  f'recording. No audio was trimmed and no narration was retimed to hide this.')


def validate_bite(project, root, data, has_audio):
    voice=project.get('voiceover') or {}; duration=narration_clock_s(project) if voice.get('duration') else 0
    if not duration or not (Path(root)/voice.get('path','')).is_file():raise ValueError('Upload narration before adding a sound bite.')
    assets={a['id']:a for a in project.get('assets',[])};asset=assets.get(data.get('asset_id'))
    if not asset or asset.get('kind')!='video' or asset.get('derived_from'):raise ValueError('Choose an uploaded source video.')
    path=(Path(root)/asset.get('path','')).resolve();base=Path(root).resolve()
    if not path.is_relative_to(base/'sources') or not path.is_file():raise ValueError('The selected source video is missing.')
    pause=_number(data.get('pause_s'),'Narration pause');start=_number(data.get('source_in_s'),'Source IN');end=_number(data.get('source_out_s'),'Source OUT')
    if not 0<=pause<=duration:
        raise ValueError(f'Narration pause is outside the narration: PAUSED at {pause:.3f}s, '
                         f'but the narrator-only audio clock ends at {duration:.3f}s. '
                         f'The finished documentary master clock is separate; no footage was shortened.')
    if start<0 or end<=start or end>float(asset.get('duration') or 0):raise ValueError('Choose a source IN and OUT within the video, with OUT after IN.')
    if not has_audio(path):raise ValueError('The selected source video has no audio stream. Choose footage with audio.')
    voice_path=Path(root)/voice['path'];stat=voice_path.stat()
    return {'id':uuid.uuid4().hex[:16], 'pause_s':pause,'asset_id':asset['id'],'asset_name':asset.get('original_name') or asset.get('name'),'asset_revision':asset.get('revision'), 'source_in_s':start,'source_out_s':end,'narration_name':voice.get('name'),'narration_size':stat.st_size,'narration_mtime_ns':stat.st_mtime_ns,'created':time.time()}


def annotate_plan(project,root,plan):
    assets={a['id']:a for a in project.get('assets',[])};voice=project.get('voiceover') or {};path=Path(root)/voice.get('path','')
    for bite in plan['bites']:
        asset=assets.get(bite['asset_id']);reasons=[]
        if not asset or asset.get('revision')!=bite.get('asset_revision') or not (Path(root)/asset.get('path','')).is_file():reasons.append('Source video was removed or replaced; review this bite again.')
        if not path.is_file() or path.stat().st_size!=bite.get('narration_size') or path.stat().st_mtime_ns!=bite.get('narration_mtime_ns'):reasons.append('Narration changed; review the pause point again.')
        try:
            from documentary_speech import for_bite
            bite['speech']=for_bite(root,plan,bite,asset) if asset else []
        except ValueError:
            # Unreadable saved speech must never silently change the on-screen words.
            bite['speech']=[];reasons.append('Saved sound-bite speech cannot be read; spoken captions are not shown.')
        bite['stale_reasons']=reasons
    return plan


def _bite_order(plan):
    """Bites in narrative order.

    Two bites may share one pause point (a back-to-back statement with no
    narration between). Those keep the order they were saved in; everything
    else is ordered by its pause.
    """
    bites=list(plan.get('bites',[]))
    for b in bites:_number(b['pause_s'],'Narration pause')
    return sorted(bites,key=lambda b:(b['pause_s'],b.get('created') if b.get('created') is not None else 0))


def _spans(bites):
    """Group bites into runs that share one pause point."""
    runs=[]
    for b in bites:
        if runs and abs(runs[-1][0]['pause_s']-b['pause_s'])<.0005:runs[-1].append(b)
        else:runs.append([b])
    return runs


def build_timeline(project, plan):
    """Map narration and inserted footage onto a separate, immutable edit clock.

    This is a planning representation only, not a rendered MP4 or subtitle file.
    """
    voice=project.get('voiceover') or {};_number(voice.get('duration'),'Narration duration');duration=narration_clock_s(project)
    if duration<=0:raise ValueError('Upload narration to build a documentary timeline.')
    bites=_bite_order(plan)
    stale=[b for b in bites if b.get('stale_reasons')]
    if stale:
        b=stale[0];more=f' ({len(stale)-1} more like it)' if len(stale)>1 else ''
        raise ValueError(f"Sound bite {b.get('script_beat') and 'Beat '+str(b.get('script_beat'))+' · ' or ''}{b.get('asset_name') or 'source video'}: "
                         f"{b['stale_reasons'][0]}{more} This happens when a video finishes downloading, is re-downloaded or the narration is re-uploaded after the build. Rebuild the Beat timeline to use the current files.")
    cursor=0;output=0;segments=[]
    for run in _spans(bites):
        at=_number(run[0]['pause_s'],'Narration pause')
        if at<cursor or at>duration:raise ValueError('A planned sound bite has invalid timings. Review it before continuing.')
        if at>cursor:
            span=at-cursor;segments.append({'kind':'narration','source_in_s':round(cursor,3),'source_out_s':round(at,3),'timeline_in_s':round(output,3),'timeline_out_s':round(output+span,3)});output+=span
        for b in run:
            start=_number(b['source_in_s'],'Source IN');end=_number(b['source_out_s'],'Source OUT')
            if start<0 or end<=start:raise ValueError('A planned sound bite has invalid timings. Review it before continuing.')
            # Spoken words are bite-relative, exactly as saved and reviewed; the
            # preview adds them to this segment's own start on the edit clock.
            span=end-start;segments.append({'kind':'sound_bite','id':b['id'],'asset_id':b['asset_id'],'asset_name':b['asset_name'],'source_in_s':start,'source_out_s':end,'timeline_in_s':round(output,3),'timeline_out_s':round(output+span,3),'narration_resume_s':at,'speech':list(b.get('speech') or [])});output+=span
        cursor=at
    if cursor<duration:
        span=duration-cursor;segments.append({'kind':'narration','source_in_s':round(cursor,3),'source_out_s':duration,'timeline_in_s':round(output,3),'timeline_out_s':round(output+span,3)});output+=span
    return {'status':'planning_only','duration_s':round(output,3),'narration_duration_s':duration,'narration_file_s':round(float(voice.get('duration')),3),'segments':segments,'subtitles':'not_generated','export_available':False}


def adjusted_srt(original, project, plan, splits=None):
    """Shift a separate SRT; a crossing cue requires an explicit word split.

    Split points are editorial input, not automatic word alignment. Every word
    remains verbatim and ordered. The original file is never changed.
    """
    import re
    timeline=build_timeline(project,plan)
    source=original.replace('\r\n','\n').replace('\r','\n').strip()
    parts=re.split(r'\n\s*\n',source);blocks=(project.get('srt') or {}).get('blocks') or []
    if not blocks or len(parts)!=len(blocks):raise ValueError('The original uploaded SRT does not match this project. Upload it again before creating adjusted subtitles.')
    def clock(ms):
        h,rem=divmod(ms,3600000);m,rem=divmod(rem,60000);sec,ms=divmod(rem,1000)
        return f'{h:02}:{m:02}:{sec:02},{ms:03}'
    bites=[(round(s['narration_resume_s']*1000),round((s['timeline_out_s']-s['timeline_in_s'])*1000)) for s in timeline['segments'] if s['kind']=='sound_bite']
    rules={}
    if not isinstance(splits or [],list):raise ValueError('Subtitle split choices must be a list.')
    for rule in splits or []:
        if not isinstance(rule,dict) or type(rule.get('cue')) is not int or type(rule.get('pause_ms')) is not int or type(rule.get('words_before')) is not int:raise ValueError('Invalid subtitle split choice.')
        key=(rule['cue'],rule['pause_ms'])
        if key in rules:raise ValueError('Duplicate subtitle split choice.')
        rules[key]=rule['words_before']
    used=set();entries=[];any_split=False
    for part,block in zip(parts,blocks):
        lines=part.split('\n')
        if len(lines)<3 or lines[0].strip()!=str(block['number']) or ' '.join(lines[2:]).strip()!=block['text']:raise ValueError('The original SRT contents do not match the project. Upload the original SRT again.')
        text='\n'.join(lines[2:]);start,end=block['start_ms'],block['end_ms']
        pauses=sorted({pause for pause,_ in bites if start<pause<end})
        if len(pauses)>1:raise ValueError(f"Cue {block['number']} spans multiple pause points; split it manually in a separate subtitle editor.")
        sections=[(start,end,text)]
        if pauses:
            pause=pauses[0];key=(block['number'],pause)
            if '<' in text or '>' in text:raise ValueError(f"Cue {block['number']} contains formatting; split it manually in a separate subtitle editor.")
            words=list(re.finditer(r'\S+',text))
            if key in rules:count=rules[key];used.add(key)
            else:
                # No split chosen: divide the line by time, so the words spoken before
                # the pause stay before the sound bite. The words are unchanged.
                share=(pause-start)/max(1,end-start)
                count=max(1,min(len(words)-1,round(len(words)*share))) if len(words)>1 else 1
                if len(words)<2:
                    sections=[(start,end,text)]
                    count=None
            if count is not None:
                if count<1 or count>=len(words):raise ValueError(f"Choose a word boundary inside SRT cue {block['number']}.")
                left=text[:words[count-1].end()].rstrip();right=text[words[count].start():].lstrip()
                if not left or not right:raise ValueError('A split subtitle cannot be empty.')
                sections=[(start,pause,left),(pause,end,right)];any_split=True
        for a,b,content in sections:
            shift_start=sum(length for pause,length in bites if pause<=a)
            shift_end=sum(length for pause,length in bites if pause<b)
            if b+shift_end<=a+shift_start:raise ValueError('A subtitle segment has no duration.')
            entries.append((block['number'],a+shift_start,b+shift_end,content))
    if set(rules)!=used:raise ValueError('A subtitle split choice no longer matches the current plan. Review it again.')
    return '\n\n'.join(f'{i if any_split else number}\n{clock(a)} --> {clock(b)}\n{text}' for i,(number,a,b,text) in enumerate(entries,1))+'\n'
