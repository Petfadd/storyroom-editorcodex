"""Build a lossless narration/sound-bite audio preview; never modify source media.

This deliberately does not build a video timeline or subtitles.
"""
import timebudget
from pathlib import Path
import copy, json, math, re, shutil, subprocess, tempfile, threading, uuid
import av
import imageio_ffmpeg
from documentary import annotate_plan, build_timeline

JOBS={}
GUARD=threading.RLock()
# v2: the preview mix no longer bakes in background music; the bed is a live
# layer in the browser. A v1 mix still sounds like the old bed, so it is rejected.
AUDIO_PROCESSING_VERSION='narration-loudness-match-v4-music-under-narration-only'


def _run_command(cmd):
    result=subprocess.run(cmd,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True,timeout=timebudget.seconds())
    if result.returncode:raise ValueError('Audio preparation failed: '+result.stderr[-1000:])


def measure_loudness(ff, path):
    """EBU R128 integrated loudness/true peak. Unmeasurable speech fails closed."""
    result=subprocess.run([ff,'-hide_banner','-nostats','-i',str(path),'-vn','-af','loudnorm=I=-16:TP=-1:LRA=11:print_format=json','-f','null','-'],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True,timeout=1800)
    match=re.search(r'\{\s*"input_i".*?\}',result.stderr,re.S)
    if result.returncode or not match:raise ValueError('Could not measure audio loudness. No automatic level change was applied.')
    try:
        data=json.loads(match.group());integrated=float(data['input_i']);peak=float(data['input_tp'])
        if not math.isfinite(integrated) or not math.isfinite(peak):raise ValueError()
    except (ValueError,KeyError,TypeError):raise ValueError('A narration or sound-bite segment is silent or too short to measure safely. Review its audio.')
    return {'integrated_lufs':integrated,'true_peak_db':peak}


def audio_levels(project):
    """The saved narration and clip levels, as percentages of their reviewed level.

    Absent keys mean 100%: a project that has never opened the faders must render
    exactly as it did before the control existed.
    """
    saved = project.get('documentary_audio_levels') or {}
    def read(key):
        value = saved.get(key, 100)
        if isinstance(value, bool) or not isinstance(value, int):
            return 100
        return max(0, min(150, value))
    return {'narration_percent': read('narration_percent'), 'clip_percent': read('clip_percent')}


def build_audio(root, project, plan, destination, progress=lambda *a:None, strict_handoffs=False, music=False, compact_preview=False):
    bites=sum(float(b.get('source_out_s',0))-float(b.get('source_in_s',0)) for b in (plan or {}).get('bites') or [])
    with timebudget.film_length(float((project.get('voiceover') or {}).get('duration') or 0)+bites):
        return _build_audio(root,project,plan,destination,progress,strict_handoffs,music,compact_preview)


RATE=48000
_PCM=f'aresample={RATE},aformat=sample_fmts=s16:sample_rates={RATE}:channel_layouts=stereo'
_PREVIEW_CACHE='preview-audio-parts-v2'


def _wav_frames(path):
    import wave
    with wave.open(str(path),'rb') as w:return w.getnframes()


def _preview_workers():
    # Two light jobs, one core each. More made the whole PC lag while it ran.
    return 2


def _light_run(cmd):
    """Run ffmpeg on one core at low priority, so the editor and the PC stay smooth.

    Returns stderr (the loudness summary is printed there)."""
    import os, sys
    kwargs={}
    if sys.platform=='win32':
        kwargs['creationflags']=getattr(subprocess,'BELOW_NORMAL_PRIORITY_CLASS',0x4000)|getattr(subprocess,'CREATE_NO_WINDOW',0)
    elif hasattr(os,'nice'):
        kwargs['preexec_fn']=lambda:os.nice(10)
    result=subprocess.run(cmd,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True,timeout=timebudget.seconds(),**kwargs)
    if result.returncode:raise ValueError('Audio preparation failed: '+result.stderr[-1000:])
    return result.stderr


def _cut_and_measure(ff, source, start, end, target, pad_to=None, coarse=0.0):
    """One decode: write the exact range as 48 kHz stereo PCM and measure its loudness.

    Seeks to `coarse` first (a couple of seconds early) so nothing before the range is
    decoded, then trims precisely. ebur128 gives the same BS.1770 integrated level as
    loudnorm's measurement without loudnorm's 192 kHz resampling, which was most of
    the cost on a long bite."""
    chain=f'atrim=start={start-coarse:.6f}:end={end-coarse:.6f},asetpts=PTS-STARTPTS,{_PCM}'
    if pad_to:chain+=f',apad=whole_len={pad_to}'
    graph=f'[0:a:0]{chain},asplit=2[o][m];[m]ebur128=framelog=quiet:peak=sample,anullsink'
    cmd=[ff,'-hide_banner','-nostats','-y','-threads','1','-filter_threads','1']
    if coarse>0:cmd+=['-ss',f'{coarse:.3f}']
    cmd+=['-i',str(source),'-filter_complex',graph,'-map','[o]','-c:a','pcm_s16le',str(target)]
    try:err=_light_run(cmd)
    except ValueError as e:
        if 'matches no streams' in str(e) or 'Stream specifier' in str(e) or 'Stream map' in str(e):
            raise ValueError('A selected sound-bite video has no audio stream.') from e
        raise
    summary=err[err.rfind('Summary:'):] if 'Summary:' in err else ''
    li=re.search(r'\bI:\s*(-?[\d.]+|-inf)\s*LUFS',summary);pk=re.search(r'Peak:\s*(-?[\d.]+|-inf)\s*dBFS',summary)
    try:
        integrated=float(li.group(1));peak=float(pk.group(1)) if pk else -1.0
    except (AttributeError,ValueError):raise ValueError('Could not measure audio loudness. No automatic level change was applied.')
    if not math.isfinite(integrated) or integrated<=-69.9:
        raise ValueError('A narration or sound-bite segment is silent or too short to measure safely. Review its audio.')
    return {'integrated_lufs':integrated,'true_peak_db':peak if math.isfinite(peak) else -70.0}


def _cache_key(*parts):
    import hashlib
    return hashlib.sha256(json.dumps(parts,sort_keys=True,default=str).encode()).hexdigest()[:40]


def _build_preview_audio(root, project, plan, destination, progress, final=False, music=False):
    """The review preview, built for speed. Same parts, same levels, same order.

    The exact builder decodes the narration from its first sample for every one of
    its pieces, and each sound bite from the first second of its video: on a 25-minute
    film that is hundreds of full decodes, run one after another. Here the narration
    is decoded once and every piece is sliced out of that PCM by sample number, each
    bite seeks straight to its own second, bites are prepared side by side, and every
    finished piece is kept, so an edit re-prepares only the bites that changed.

    With final=True the same lossless pieces become the final MP4's soundtrack: every
    handoff is checked to the sample and the result stays lossless WAV.
    """
    import wave
    from concurrent.futures import ThreadPoolExecutor
    root=Path(root).resolve();destination=Path(destination).resolve()
    timeline=build_timeline(project,annotate_plan(project,root,copy.deepcopy(plan)))
    levels_config=audio_levels(project)
    segments=timeline['segments']
    if not any(s['kind']=='sound_bite' for s in segments):raise ValueError('Add at least one sound bite before preparing documentary audio.')
    assets={a['id']:a for a in project.get('assets',[])};voice=project.get('voiceover') or {};narration=(root/voice.get('path','')).resolve()
    if not narration.is_relative_to(root/'inputs') or not narration.is_file():raise ValueError('The original narration file is missing.')
    ff=imageio_ffmpeg.get_ffmpeg_exe();destination.parent.mkdir(parents=True,exist_ok=True)
    cache=root/'cache'/_PREVIEW_CACHE;cache.mkdir(parents=True,exist_ok=True)
    shutil.rmtree(root/'cache'/'preview-audio-parts-v1',ignore_errors=True)
    total=len(segments);done=[0];lock=threading.Lock()
    def tick():
        with lock:
            done[0]+=1;progress(min(done[0],total),total)
    progress(0,total)
    # 1. The narration, decoded once, measured once, kept until the file changes.
    st=narration.stat()
    nkey=_cache_key('narration',str(narration),st.st_size,st.st_mtime_ns,round(timeline['narration_duration_s'],3))
    reference=cache/f'narr-{nkey}.wav';nlevel_file=cache/f'narr-{nkey}.json'
    if not (reference.is_file() and nlevel_file.is_file()):
        tmp=reference.with_suffix('.tmp.wav')
        level=_cut_and_measure(ff,narration,0.0,float(timeline['narration_duration_s']),tmp)
        tmp.replace(reference)
        nlevel_file.write_text(json.dumps(level),encoding='utf-8')
    narration_level=json.loads(nlevel_file.read_text(encoding='utf-8'))
    with wave.open(str(reference),'rb') as w:
        if w.getframerate()!=RATE or w.getnchannels()!=2 or w.getsampwidth()!=2:raise ValueError('The narration could not be prepared as 48 kHz stereo.')
        narration_pcm=w.readframes(w.getnframes())
    frame_bytes=4
    # 2. Each sound bite: seek to its second, cut exactly, match its level to the
    #    narration. Cached by source file, range and the narration level it matched.
    def bite(i,segment):
        a=assets.get(segment['asset_id'])
        if not a or a.get('kind')!='video':raise ValueError('A sound-bite video is missing.')
        source=(root/a.get('path','')).resolve()
        if not source.is_relative_to(root/'sources') or not source.is_file():raise ValueError('A sound-bite video is missing.')
        start=float(segment['source_in_s']);end=float(segment['source_out_s']);expected=end-start
        s=source.stat()
        key=_cache_key('bite',str(source),s.st_size,s.st_mtime_ns,round(start,4),round(end,4),round(narration_level['integrated_lufs'],2),AUDIO_PROCESSING_VERSION)
        part=cache/f'bite-{key}.wav';meta=cache/f'bite-{key}.json'
        if part.is_file() and meta.is_file():
            info=json.loads(meta.read_text(encoding='utf-8'));tick();return part,info
        coarse=max(0.0,start-2.0)
        raw=cache/f'bite-{key}.raw.wav'
        measured=_cut_and_measure(ff,source,start,end,raw,coarse=coarse)
        length=_wav_frames(raw)/RATE
        if abs(length-expected)>.025:
            raw.unlink(missing_ok=True)
            raise ValueError(f'Audio segment {i+1} decoded as {length:.3f}s instead of {expected:.3f}s. Check the source audio and selected range.')
        requested=narration_level['integrated_lufs']-measured['integrated_lufs']
        gain=max(-12.0,min(24.0,requested))
        tmp=cache/f'bite-{key}.tmp.wav'
        _light_run([ff,'-hide_banner','-loglevel','error','-y','-threads','1','-filter_threads','1','-i',str(raw),'-af',f'volume={gain:.4f}dB,alimiter=limit=0.794328:level=0:latency=1','-c:a','pcm_s16le',str(tmp)])
        raw.unlink(missing_ok=True)
        adjusted_length=_wav_frames(tmp)/RATE
        if abs(adjusted_length-expected)>.025:
            tmp.unlink(missing_ok=True);raise ValueError('Level matching changed the selected sound-bite duration; preview stopped.')
        # The result is the measured level plus the gain; the limiter only touches
        # peaks above -2 dBFS. A second full loudness pass to report it cost a third
        # of each bite's preparation and changes nothing in the sound.
        info={'asset_name':segment.get('asset_name'),'original_lufs':round(measured['integrated_lufs'],2),'gain_db':round(gain,2),'result_lufs':round(measured['integrated_lufs']+gain,2),'result_true_peak_db':round(min(-2.0,measured['true_peak_db']+gain),2),'gain_capped':abs(gain-requested)>.01,'length':adjusted_length}
        tmp.replace(part);meta.write_text(json.dumps(info),encoding='utf-8')
        tick();return part,info
    jobs={}
    with ThreadPoolExecutor(max_workers=_preview_workers()) as pool:
        for i,segment in enumerate(segments):
            if segment['kind']=='sound_bite':jobs[i]=pool.submit(bite,i,segment)
        results={i:f.result() for i,f in jobs.items()}
    # 3. Assemble in order. Narration pieces are sliced by sample number from the PCM
    #    already in memory; the SRT's hold past the file's last sample is silence.
    used={p.name for p,_ in results.values()}|{reference.name,nlevel_file.name}
    with tempfile.TemporaryDirectory(prefix='audio-',dir=destination.parent) as temp:
        work=Path(temp);speech=work/'speech.wav';levels=[];segment_lengths=[];written=0
        with wave.open(str(speech),'wb') as out:
            out.setnchannels(2);out.setsampwidth(2);out.setframerate(RATE)
            for i,segment in enumerate(segments):
                if segment['kind']=='narration':
                    a=int(round(float(segment['source_in_s'])*RATE));b=int(round(float(segment['source_out_s'])*RATE))
                    chunk=narration_pcm[a*frame_bytes:b*frame_bytes]
                    if len(chunk)<(b-a)*frame_bytes:
                        # An MP3 declares a length a few hundredths of a second longer than
                        # the sound it holds (encoder padding). Past the last real sample
                        # there is only silence, so up to half a second is filled with it.
                        missing=((b-a)*frame_bytes-len(chunk))//frame_bytes
                        at_end=b>=len(narration_pcm)//frame_bytes
                        if missing>int((.5 if at_end else .025)*RATE):
                            raise ValueError(f'Audio segment {i+1} is shorter than its planned range. Check the narration file.')
                        chunk+=b'\0'*((b-a)*frame_bytes-len(chunk))
                    out.writeframes(chunk);n=(b-a);segment_lengths.append(n/RATE);written+=n;tick()
                else:
                    part,info=results[i]
                    with wave.open(str(part),'rb') as w:
                        n=w.getnframes();out.writeframes(w.readframes(n))
                    if final and i<len(segments)-1 and abs(n/RATE-(float(segment['source_out_s'])-float(segment['source_in_s'])))>2/RATE+1e-8:
                        raise ValueError(f'Audio segment {i+1} does not end on the planned sample boundary; final assembly stopped.')
                    written+=n;segment_lengths.append(info['length'])
                    levels.append({k:v for k,v in info.items() if k!='length'})
        speech_gain=min(levels_config['narration_percent'],levels_config['clip_percent'])/100.0
        duration=written/RATE
        if abs(duration-timeline['duration_s'])>max(.025,len(segments)*.005):raise ValueError('The assembled audio length does not match the planned timeline.')
        music_result=None
        if final:
            # Lossless out: the level as one gain on the speech, then the ducked bed
            # (silent through every bite) mixed under it, exactly as before.
            out=work/'result.wav';chain=[]
            if abs(speech_gain-1.0)>1e-9:
                chain.append(f'volume={speech_gain:.6f}'+(',alimiter=limit=0.891251:level=0:latency=1' if speech_gain>1.0 else ''))
            if music:
                from documentary_music import build_bed, music_path
                bed=work/'music-bed.wav'
                music_result=build_bed(project,music_path(root),bed,timeline['duration_s'],timeline['segments'])
                pre=(chain[0]+',') if chain else ''
                _light_run([ff,'-hide_banner','-loglevel','error','-y','-i',str(speech),'-i',str(bed),'-filter_complex',f'[0:a]{pre}anull[s];[s][1:a]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,alimiter=limit=0.891251:level=0:latency=1','-ar','48000','-c:a','pcm_s16le',str(out)])
            elif chain:
                _light_run([ff,'-hide_banner','-loglevel','error','-y','-i',str(speech),'-af',chain[0],'-c:a','pcm_s16le',str(out)])
            else:
                out=speech
            duration=_wav_frames(out)/RATE
            if abs(duration-timeline['duration_s'])>max(.025,len(segments)*.005):raise ValueError('The assembled audio length does not match the planned timeline.')
            shutil.move(str(out),str(destination))
            progress(total,total)
            return {'duration_s':duration,'planned_duration_s':timeline['duration_s'],'segments':segments,'audio_processing_version':AUDIO_PROCESSING_VERSION,'narration_lufs':round(narration_level['integrated_lufs'],2),'sound_bite_levels':levels,'segment_lengths_s':segment_lengths,'music':music_result,'audio_levels':{**levels_config,'applied_speech_gain':round(speech_gain,4)}}
        # Straight to a small streamable file: one encode, with the level applied in it.
        filt=[]
        if abs(speech_gain-1.0)>1e-9:
            filt=['-af',f'volume={speech_gain:.6f}'+(',alimiter=limit=0.891251:level=0:latency=1' if speech_gain>1.0 else '')]
        target=destination if str(destination).lower().endswith('.m4a') else destination.with_suffix('.m4a')
        tmp=work/'preview.m4a'
        # Opus encodes about twice as fast as ffmpeg's AAC and every current browser
        # plays it from an MP4 file. AAC stays as the fallback for an ffmpeg without it.
        base=[ff,'-hide_banner','-loglevel','error','-y','-threads','1','-filter_threads','1','-i',str(speech),*filt,'-map','0:a:0']
        try:
            _light_run(base+['-c:a','libopus','-b:a','128k','-f','mp4','-movflags','+faststart',str(tmp)])
        except ValueError:
            _light_run(base+['-c:a','aac','-b:a','192k','-ar',str(RATE),'-f','mp4','-movflags','+faststart',str(tmp)])
        tmp.replace(target)
    # Keep the cache to what this film uses, so it never grows without limit.
    try:
        for f in cache.iterdir():
            if f.name not in used and not f.name.replace('.json','.wav') in used:f.unlink(missing_ok=True)
    except OSError:pass
    progress(total,total)
    return {'duration_s':duration,'planned_duration_s':timeline['duration_s'],'segments':segments,'audio_processing_version':AUDIO_PROCESSING_VERSION,'narration_lufs':round(narration_level['integrated_lufs'],2),'sound_bite_levels':levels,'segment_lengths_s':segment_lengths,'music':None,'audio_levels':{**levels_config,'applied_speech_gain':round(speech_gain,4)}}


def _build_audio(root, project, plan, destination, progress=lambda *a:None, strict_handoffs=False, music=False, compact_preview=False):
    if compact_preview and not strict_handoffs and not music and str(destination).lower().endswith('.m4a'):
        return _build_preview_audio(root,project,plan,destination,progress)
    if strict_handoffs and str(destination).lower().endswith('.wav'):
        # The final MP4's soundtrack: the very same lossless pieces the preview was
        # built from (usually already cached, so this takes seconds), checked to the
        # sample, with the level and music applied losslessly. The old one-step-at-a-
        # time builder took minutes on a full film with nothing on screen moving.
        return _build_preview_audio(root,project,plan,destination,progress,final=True,music=music)
    root=Path(root).resolve();destination=Path(destination).resolve();timeline=build_timeline(project,annotate_plan(project,root,copy.deepcopy(plan)))
    # Both levels are applied as one gain on the assembled speech, for the same
    # reason the preview applies the quieter of the two: narration and bites are
    # concatenated into a single stream, so a per-segment gain would have to be
    # baked into each part and could no longer be undone without a re-decode.
    levels_config = audio_levels(project)
    if not any(s['kind']=='sound_bite' for s in timeline['segments']):raise ValueError('Add at least one sound bite before preparing documentary audio.')
    assets={a['id']:a for a in project.get('assets',[])};voice=project.get('voiceover') or {};narration=(root/voice.get('path','')).resolve()
    if not narration.is_relative_to(root/'inputs') or not narration.is_file():raise ValueError('The original narration file is missing.')
    ff=imageio_ffmpeg.get_ffmpeg_exe();destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='audio-',dir=destination.parent) as temp:
        work=Path(temp);parts=[];levels=[];segment_lengths=[]
        # Measure the original narration without changing its samples. Convert it
        # to the same stereo format as the extracted sound bites for comparison.
        reference=work/'narration-reference.wav'
        _run_command([ff,'-hide_banner','-loglevel','error','-y','-i',str(narration),'-map','0:a:0','-vn','-af',f'atrim=start=0:end={timeline["narration_duration_s"]:.3f},asetpts=PTS-STARTPTS,aresample=48000,aformat=sample_fmts=s16:sample_rates=48000:channel_layouts=stereo','-c:a','pcm_s16le',str(reference)])
        narration_level=measure_loudness(ff,reference)
        for i,segment in enumerate(timeline['segments']):
            progress(i,len(timeline['segments']))
            if segment['kind']=='narration':source=narration
            else:
                a=assets.get(segment['asset_id'])
                if not a or a.get('kind')!='video':raise ValueError('A sound-bite video is missing.')
                source=(root/a.get('path','')).resolve()
                if not source.is_relative_to(root/'sources') or not source.is_file():raise ValueError('A sound-bite video is missing.')
            with av.open(str(source)) as media:
                if not media.streams.audio:raise ValueError('A selected sound-bite video has no audio stream.')
            start=segment['source_in_s'];end=segment['source_out_s'];part=work/f'{i:04d}.wav'
            filt=f'atrim=start={start:.3f}:end={end:.3f},asetpts=PTS-STARTPTS,aresample=48000,aformat=sample_fmts=s16:sample_rates=48000:channel_layouts=stereo'
            # The SRT holds its last line a moment past the end of the narration file
            # (narration_clock_s). Every recorded sample is kept; the difference after
            # the file's last sample is silence, so the sound runs as long as the film.
            # The SRT can hold its last line past the file's end, and an MP3 declares a
            # few hundredths of a second more than it decodes to (encoder padding). The
            # narration's last piece is therefore padded with silence to its planned
            # length; no recorded sample is changed or dropped.
            last_narration=segment['kind']=='narration' and end>=timeline.get('narration_file_s',end)-.5
            if segment['kind']=='narration' and (end>timeline.get('narration_file_s',end)+.0005 or last_narration):
                filt+=f',apad=whole_len={round((end-start)*48000)}'
            _run_command([ff,'-hide_banner','-loglevel','error','-y','-i',str(source),'-map','0:a:0','-vn','-af',filt,'-c:a','pcm_s16le',str(part)])
            # Refuse to silently extend a short or missing clip with silence.
            with av.open(str(part)) as media:
                stream=media.streams.audio[0];length=float(stream.duration*stream.time_base) if stream.duration is not None else 0
            expected=end-start
            if abs(length-expected)>.025:raise ValueError(f'Audio segment {i+1} decoded as {length:.3f}s instead of {expected:.3f}s. Check the source audio and selected range.')
            if strict_handoffs and i < len(timeline['segments'])-1 and abs(length-expected)>2/48000+.00000001:
                raise ValueError(f'Audio segment {i+1} does not end on the planned sample boundary; final assembly stopped.')
            if segment['kind']=='sound_bite':
                measured=measure_loudness(ff,part)
                # Limit extreme corrections and protect peaks. The only audio being
                # processed is this selected source interval; narration stays untouched.
                requested=narration_level['integrated_lufs']-measured['integrated_lufs']
                gain=max(-12.0,min(24.0,requested));adjusted=work/f'{i:04d}-levelled.wav'
                _run_command([ff,'-hide_banner','-loglevel','error','-y','-i',str(part),'-af',f'volume={gain:.4f}dB,alimiter=limit=0.794328:level=0:latency=1','-c:a','pcm_s16le',str(adjusted)])
                with av.open(str(adjusted)) as media:
                    stream=media.streams.audio[0];adjusted_length=float(stream.duration*stream.time_base) if stream.duration is not None else 0
                if abs(adjusted_length-expected)>.025:raise ValueError('Level matching changed the selected sound-bite duration; preview stopped.')
                if strict_handoffs and abs(adjusted_length-expected)>2/48000+.00000001:raise ValueError('Level matching changed the sound-bite sample boundary; final assembly stopped.')
                final=measure_loudness(ff,adjusted);levels.append({'asset_name':segment.get('asset_name'),'original_lufs':round(measured['integrated_lufs'],2),'gain_db':round(gain,2),'result_lufs':round(final['integrated_lufs'],2),'result_true_peak_db':round(final['true_peak_db'],2),'gain_capped':abs(gain-requested)>.01})
                part=adjusted
            segment_lengths.append(adjusted_length if segment['kind']=='sound_bite' else length);parts.append(part)
        listing=work/'concat.txt';listing.write_text(''.join("file '"+str(p).replace("'","'\\''")+"'\n" for p in parts),encoding='utf-8')
        speech=work/'speech.wav'
        # A level below 100% is a plain attenuation. Anything above it is limited
        # afterwards so a quiet source cannot clip on the way out.
        speech_gain=min(levels_config['narration_percent'],levels_config['clip_percent'])/100.0
        concat_cmd=[ff,'-hide_banner','-loglevel','error','-y','-f','concat','-safe','0','-i',str(listing)]
        if abs(speech_gain-1.0)>1e-9:
            filt=f'volume={speech_gain:.6f}'
            if speech_gain>1.0:
                filt+=',alimiter=limit=0.891251:level=0:latency=1'
            concat_cmd+=['-af',filt]
        concat_cmd+=['-c:a','pcm_s16le',str(speech)]
        _run_command(concat_cmd)
        music_result=None
        out=work/'result.wav'
        if music:
            from documentary_music import build_bed, music_path
            bed=work/'music-bed.wav'
            # The bed arrives already shaped: ducked under the narration and silent
            # through every sound bite (build_bed). Narration and bites stay at their
            # reviewed level on top of it.
            music_result=build_bed(project,music_path(root),bed,timeline['duration_s'],timeline['segments'])
            _run_command([ff,'-hide_banner','-loglevel','error','-y','-i',str(speech),'-i',str(bed),'-filter_complex','[0:a][1:a]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,alimiter=limit=0.891251:level=0:latency=1','-ar','48000','-c:a','pcm_s16le',str(out)])
            bed.unlink(missing_ok=True)
        else:
            shutil.copyfile(speech,out)
        with av.open(str(out)) as media:
            stream=media.streams.audio[0];duration=float(stream.duration*stream.time_base)
        if abs(duration-timeline['duration_s'])>max(.025,len(parts)*.005):raise ValueError('The assembled audio length does not match the planned timeline.')
        # The assembly is lossless WAV, but delivering 150MB of PCM made the
        # browser buffer for a long time before playback could start. The review
        # preview is encoded to a small streamable file; the lossless assembly is
        # still what was measured, and nothing upstream is re-encoded.
        # The browser review wants a small, streamable file; the assembly and the
        # bit-exact narration handoff want the lossless one. Only encode when the
        # caller explicitly asked for a preview.
        preview=encode_preview(ff,out) if compact_preview and str(destination).lower().endswith('.m4a') else None
        if preview:
            preview.replace(destination)
            out.unlink(missing_ok=True)
        else:
            out.replace(destination)
    progress(len(timeline['segments']),len(timeline['segments']))
    return {'duration_s':duration,'planned_duration_s':timeline['duration_s'],'segments':timeline['segments'],'audio_processing_version':AUDIO_PROCESSING_VERSION,'narration_lufs':round(narration_level['integrated_lufs'],2),'sound_bite_levels':levels,'segment_lengths_s':segment_lengths,'music':music_result,'audio_levels':{**levels_config,'applied_speech_gain':round(speech_gain,4)}}


def encode_preview(ff, source):
    """Encode the assembled preview compactly so it starts playing quickly.

    Returns the encoded file, or None when encoding is unavailable, in which case
    the lossless WAV is delivered unchanged.
    """
    target=source.with_suffix('.m4a')
    if target==source:return None
    try:
        _run_command([ff,'-hide_banner','-loglevel','error','-y','-i',str(source),
                      '-map','0:a:0','-c:a','aac','-b:a','192k','-ar','48000',
                      '-movflags','+faststart',str(target)])
        return target if target.is_file() and target.stat().st_size>0 else None
    except Exception:
        target.unlink(missing_ok=True)
        return None


def signature(project, plan):
    """What the audio mix actually depends on.

    Deliberately excludes music level, music on/off and ducking: those are applied
    live in the browser, so they can change without the mix being stale. Picture,
    narration and the bites are what the mix is built from.
    """
    import hashlib, json
    voice=(project.get('voiceover') or {})
    payload={
        'narration':{'path':voice.get('path'),'duration':voice.get('duration')},
        'bites':[{k:b.get(k) for k in ('asset_id','asset_revision','pause_s','source_in_s','source_out_s','narration_size','narration_mtime_ns')} for b in (plan.get('bites') or [])],
        'revision':plan.get('revision'),
    }
    return hashlib.sha256(json.dumps(payload,sort_keys=True,default=str).encode()).hexdigest()

def prune_renders(root, keep):
    """Delete superseded documentary audio previews for this project.

    Each rebuild used to leave its own 150MB file behind, so repeated rebuilds
    quietly filled the disk and made the project slow to work with.
    """
    import re
    renders=Path(root)/'renders'
    try:
        for path in renders.glob('documentary_audio_*'):
            if path.name!=keep and path.is_file() and re.fullmatch(r'documentary_audio_[a-f0-9]{32}\.(wav|m4a)',path.name):
                path.unlink(missing_ok=True)
    except OSError:
        pass


def start(root, project, plan, is_current, music=False):
    root=Path(root);pid=project['id']
    with GUARD:
        old=JOBS.get(pid)
        if old and old['status'] in ('queued','running'):raise ValueError('Documentary audio is already being prepared.')
        job={'status':'queued','completed':0,'total':0,'detail':'Preparing documentary audio preview.','project_version':project.get('updated'),'plan_revision':plan['revision']};JOBS[pid]=job
    def work():
        output=root/'renders'/('documentary_audio_'+uuid.uuid4().hex+'.m4a')
        try:
            with GUARD:job['status']='running'
            def progress(n,total):
                with GUARD:job.update(completed=n,total=total,detail=f'Preparing audio segment {min(n+1,total)} of {total}.')
            result=build_audio(root,project,plan,output,progress,music=music,compact_preview=True)
            if not is_current(project,plan):
                output.unlink(missing_ok=True)
                raise ValueError('The project or sound-bite plan changed during preparation. Prepare audio again.')
            prune_renders(root,output.name)
            signature_value=signature(project,plan)
            with GUARD:
                job.update(status='done',audio_signature=signature_value,detail='Documentary audio preview ready. Video and adjusted SRT are not yet built.',output=output.name,**result)
                record=root/'reviews'/'documentary_audio_status.json';record.parent.mkdir(parents=True,exist_ok=True)
                temp=record.with_name(record.name+'.'+uuid.uuid4().hex+'.tmp')
                try:
                    temp.write_text(json.dumps(job,indent=2),encoding='utf-8');temp.replace(record)
                finally:temp.unlink(missing_ok=True)
        except Exception as e:
            output.unlink(missing_ok=True)
            with GUARD:job.update(status='error',detail=str(e))
    threading.Thread(target=work,daemon=True,name='documentary-audio-'+pid).start()
    return dict(job)


def status(pid, root=None):
    with GUARD:
        if pid in JOBS:return dict(JOBS[pid])
        if root:
            try:
                saved=json.loads((Path(root)/'reviews'/'documentary_audio_status.json').read_text(encoding='utf-8'))
                if saved.get('status')=='done' and (Path(root)/'renders'/Path(saved.get('output','')).name).is_file():return saved
            except (OSError,ValueError,TypeError):pass
        return {'status':'idle'}
