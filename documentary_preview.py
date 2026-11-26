"""Explicitly review-only documentary timeline preview. Never approves an export."""
import copy, json, subprocess, tempfile, threading, uuid
from pathlib import Path
import av, imageio_ffmpeg
from documentary import annotate_plan, build_timeline
from documentary_audio import build_audio, AUDIO_PROCESSING_VERSION

JOBS={};GUARD=threading.RLock()


def picture_plan(project, plan, allow_tail=False):
    timeline=build_timeline(project,plan)
    scenes=project.get('scenes') or []
    if not scenes:raise ValueError('Build the base picture timeline first.')
    cursor=0
    assets={a['id']:a for a in project.get('assets',[])}
    for s in scenes:
        if s['frame_in']!=cursor or s['frame_out']<=cursor:raise ValueError('The base picture timeline has a gap or overlap; review it first.')
        a=assets.get(s.get('asset_id'))
        if not a or a.get('kind')!='video':raise ValueError('This review preview requires an assigned video in every base slot; no picture was substituted.')
        cursor=s['frame_out']
    # A built Beat storyboard is already on the *master film clock*: its scenes
    # include the pictures assigned to source-audio sound bites.  The older
    # narration-only storyboard instead needs bites inserted at their pauses.
    # Treating a Beat storyboard as narration-only counts those bites twice and
    # reports a fictitious several-second silent picture tail.
    beat_review=project.get('documentary_beat_review') or {}
    if beat_review.get('fitted_beats') and (project.get('script_application') or {}).get('mode')=='documentary_beat_review':
        tail=cursor/30-timeline['duration_s']
        if tail < -.001:
            raise ValueError('The Beat picture track ends before the finished film clock. Rebuild the timeline.')
        if tail > .001 and (tail>.251 or not allow_tail):
            raise ValueError(f'The Beat picture track ends {tail:.3f}s after the film clock. Review this picture tail.')
        parts=[]
        bites_by_id={b['id']:b for b in plan['bites']}
        for s in scenes:
            a=assets[s['asset_id']]
            first=int(s['frame_in']);count=int(s['frame_out'])-first
            source_bite=(s.get('plan_row') or {}).get('bite_id')
            kind='sound_bite' if source_bite else 'base'
            if source_bite:
                bite=bites_by_id.get(source_bite)
                if not bite or bite['asset_id']!=a['id'] or (
                    float(s.get('in_s') or 0)<float(bite['source_in_s'])-.001 or
                    float(s.get('in_s') or 0)+count/30>float(bite['source_out_s'])+.001
                ):
                    raise ValueError('A soundbite picture is not assigned to the correct source audio range. Rebuild the Beat timeline.')
            part={'asset_id':a['id'], 'start':float(s.get('in_s') or 0),
                  'frames':count, 'kind':kind}
            if kind=='base':
                from documentary_frame_audit import _camera
                part.update(scale=int(s.get('picture_scale') or project.get('picture_scale') or 100),
                            camera=_camera(s), camera_first=0, camera_total=count)
            if part['start']<0 or part['start']+count/30>float(a.get('duration') or 0)+.001:
                raise ValueError('A Beat picture source interval exceeds its uploaded video.')
            parts.append(part)
        expected_bite_frames=sum(round((b['source_out_s']-b['source_in_s'])*30) for b in plan['bites'])
        actual_bite_frames=sum(x['frames'] for x in parts if x['kind']=='sound_bite')
        if expected_bite_frames!=actual_bite_frames:
            raise ValueError('Beat storyboard soundbite picture duration differs from its audio plan. Rebuild the timeline.')
        return parts,tail,timeline
    narration=timeline['narration_duration_s'];tail=cursor/30-narration
    if tail < -.001:raise ValueError('The base picture ends before the narration. Fix the mismatch before previewing.')
    if tail > .001 and (tail>.251 or not allow_tail):raise ValueError(f'The base picture ends {tail:.3f}s after the narration. Confirm this silent picture tail before preparing the review preview.')
    # Each inserted sound bite must land on output frame boundaries. Never
    # silently round a user's selected pause or alter the audio duration.
    bites=[]
    for b in sorted(plan['bites'],key=lambda b:(b['pause_s'],b['created'])):
        pause=round(b['pause_s']*30);frames=round((b['source_out_s']-b['source_in_s'])*30)
        if abs(pause/30-b['pause_s'])>.001 or abs(frames/30-(b['source_out_s']-b['source_in_s']))>.001 or frames<1:
            raise ValueError('The sound-bite pause and duration must align to 30 fps output frames. Choose frame-aligned times; no timing was changed.')
        if b['asset_id'] not in assets:raise ValueError('Sound-bite source is missing.')
        bites.append((pause,frames,b))
    parts=[];pos=0
    def base_until(end):
        nonlocal pos
        while pos<end:
            scene=next((s for s in scenes if s['frame_in']<=pos<s['frame_out']),None)
            if not scene:raise ValueError('A base picture interval has no assigned shot.')
            last=min(end,scene['frame_out']);a=assets[scene['asset_id']]
            start=float(scene.get('in_s') or 0)+(pos-scene['frame_in'])/30
            from documentary_frame_audit import _camera
            parts.append({'asset_id':a['id'],'start':start,'frames':last-pos,'kind':'base','scale':int(scene.get('picture_scale') or project.get('picture_scale') or 100),
                          'camera':_camera(scene),'camera_first':pos-scene['frame_in'],'camera_total':scene['frame_out']-scene['frame_in']})
            pos=last
    for pause,frames,b in bites:
        base_until(pause);parts.append({'asset_id':b['asset_id'],'start':b['source_in_s'],'frames':frames,'kind':'sound_bite'})
    base_until(cursor)
    for part in parts:
        a=assets[part['asset_id']]
        if part['start']<0 or part['start']+part['frames']/30>float(a.get('duration') or 0)+.001:raise ValueError('A source interval exceeds its uploaded video; no extension or substitute was used.')
    return parts,tail,timeline


def _run(args):
    r=subprocess.run(args,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True,timeout=1800)
    if r.returncode:raise ValueError('Review preview preparation failed: '+r.stderr[-700:])


def build(root,project,plan,dest,allow_tail=False,progress=lambda *x:None,width=640,height=360):
    root=Path(root).resolve();dest=Path(dest)
    if (project.get('documentary_beat_review') or {}).get('fitted_beats'):
        # Export-matched review: use the production compositor, including xfade,
        # channel overlays, person photos, fades, and master-clock soundtrack.
        # This is a real low-resolution encode, NOT an instantaneous UI preview;
        # crucially, it never depicts a hard cut in place of an authored transition.
        from documentary_final_renderer import render as render_export_picture
        from documentary_music import music_path, settings as music_settings
        opts=music_settings(project)
        soundtrack_music=bool(opts.get('enabled') and opts.get('present') and music_path(root).is_file())
        result=render_export_picture(root,project,plan,dest,width,height,
            progress=progress,music=soundtrack_music)
        return {
            'duration_s':result['duration_s'],'picture_tail_s':result.get('silent_tail_s',0),
            'audio_processing_version':AUDIO_PROCESSING_VERSION,
            'narration_lufs':None,'sound_bite_levels':result['sound_bite_levels'],
            'renderer':'export_matched_lowres',
            'rendered_transitions':True,'audio_duration_s':result.get('audio_duration_s'),
            'captions_rendered':result.get('captions',0),
        }
    plan=annotate_plan(project,root,copy.deepcopy(plan));parts,tail,timeline=picture_plan(project,plan,allow_tail)
    if not plan['bites']:raise ValueError('Add a sound bite before preparing this documentary preview.')
    if any(s.get('transition') not in (None,'cut') for s in project.get('scenes') or []):
        raise ValueError('Legacy cut-only review would misrepresent your selected transitions. Use the export-rendered preview after building the Beat timeline.')
    assets={a['id']:a for a in project['assets']};ff=imageio_ffmpeg.get_ffmpeg_exe();dest.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='documentary-review-',dir=dest.parent) as tmp:
        work=Path(tmp);audio=work/'audio.wav'
        from documentary_music import music_path,settings as music_settings
        music=music_settings(project);audio_result=build_audio(root,project,plan,audio,music=bool(music['enabled'] and music['present'] and music_path(root).is_file()))
        def encode_part(i,part):
            a=assets[part['asset_id']];src=(root/a.get('path','')).resolve()
            if not src.is_relative_to(root/'sources') or not src.is_file():raise ValueError('A required video source is missing.')
            clip=work/f'{i:04d}.mp4';scale=part.get('scale',100)
            if not 100<=scale<=200:raise ValueError('The picture scale must be between 100 and 200 percent.')
            # Same framing rule as the final renderer: a narrow frame is filled and
            # cropped from the centre, a wide frame keeps all of the picture.
            narrow=width/height < 16/9
            fit=(f'increase,crop={width}:{height}' if narrow
                 else f'decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black')
            filt=f'fps=30,scale={width}:{height}:force_original_aspect_ratio={fit},setsar=1'
            # The zoom's scale would otherwise leave a non-square pixel ratio behind;
            # reset it so the preview matches the export exactly.
            if part.get('camera'):
                # The same camera arithmetic as the final render, at preview size.
                from cinematic import ffmpeg_filter
                filt+=','+ffmpeg_filter(part['camera'],width,height,part['camera_first'],part['camera_total'])+',setsar=1'
            elif scale!=100:filt+=f',scale={round(width*scale/100/2)*2}:{round(height*scale/100/2)*2},crop={width}:{height},setsar=1'
            filt+=',format=yuv420p'
            _run([ff,'-hide_banner','-loglevel','error','-y','-ss',f'{part["start"]:.6f}','-i',str(src),'-an','-vf',filt,'-frames:v',str(part['frames']),'-c:v','libx264','-preset','ultrafast','-crf','23','-threads','2',str(clip)])
            with av.open(str(clip)) as media:
                if not media.streams.video or media.streams.video[0].frames!=part['frames']:raise ValueError('A source did not decode enough frames; preview stopped rather than freezing or looping.')
            return clip
        # Parts are independent encodes, so they run side by side like the final
        # renderer's pieces (same worker count, two threads each) instead of one after
        # another on two cores. The list keeps script order whatever finishes first.
        from concurrent.futures import ThreadPoolExecutor
        from documentary_final_renderer import _piece_workers
        import perflog,time as _time;_began=_time.monotonic()
        clips=[None]*len(parts);done=0;progress(0,len(parts))
        with ThreadPoolExecutor(max_workers=_piece_workers()) as pool:
            futures={pool.submit(encode_part,i,part):i for i,part in enumerate(parts)}
            try:
                from concurrent.futures import as_completed
                for future in as_completed(futures):
                    clips[futures[future]]=future.result();done+=1;progress(done,len(parts))
            except BaseException:
                for f in futures:f.cancel()
                raise
        perflog.record('preview.encode_parts',_time.monotonic()-_began,parts=len(parts),workers=_piece_workers())
        listing=work/'clips.txt';listing.write_text(''.join("file '"+str(p).replace("'","'\\''")+"'\n" for p in clips),encoding='utf-8')
        picture=work/'picture.mp4';_run([ff,'-hide_banner','-loglevel','error','-y','-f','concat','-safe','0','-i',str(listing),'-c','copy',str(picture)])
        duration=sum(x['frames'] for x in parts)/30;result=work/'result.mp4';cmd=[ff,'-hide_banner','-loglevel','error','-y','-i',str(picture),'-i',str(audio),'-map','0:v:0','-map','1:a:0','-c:v','copy']
        if tail>.001:cmd+=['-af',f'apad=pad_dur={tail:.6f}']
        cmd+=['-c:a','aac','-b:a','160k','-t',f'{duration:.6f}','-movflags','+faststart',str(result)];_run(cmd)
        with av.open(str(result)) as media:
            actual=media.streams.video[0].frames
            if actual!=sum(x['frames'] for x in parts):raise ValueError('The review preview frame count is incorrect.')
        result.replace(dest)
    progress(len(parts),len(parts));return {'duration_s':duration,'picture_tail_s':max(0,tail),'audio_processing_version':AUDIO_PROCESSING_VERSION,'narration_lufs':audio_result['narration_lufs'],'sound_bite_levels':audio_result['sound_bite_levels'],'renderer':'legacy_cut_only','rendered_transitions':False}


def preview_size(project):
    """Pixel size for the review preview: keeps the project's shape at review scale.

    A 9:16 film reviewed through a 16:9 preview hides every framing error until the
    export, so the preview is rendered at the project's aspect and only the long side
    is reduced. Portrait 1080x1920 becomes 360x640.
    """
    width=640
    aw,ah={'landscape':(16,9),'portrait':(9,16),'square':(1,1),'vertical_4_5':(4,5),'cinema':(239,100)}.get(project.get('format') or 'landscape',(16,9))
    return width,max(2,int(round(width*ah/aw/2)*2))


def start(root,project,plan,allow_tail,is_current):
    root=Path(root);pid=project['id'];width,height=preview_size(project)
    with GUARD:
        if JOBS.get(pid,{}).get('status') in ('queued','running'):raise ValueError('A documentary preview is already being prepared.')
        job={'status':'queued','completed':0,'total':0,'detail':'Preparing documentary timeline preview.'};JOBS[pid]=job
    def run():
        output=root/'renders'/('documentary_review_'+uuid.uuid4().hex+'.mp4')
        try:
            with GUARD:job['status']='running'
            def report(n,total):
                with GUARD:job.update(completed=n,total=total,detail=f'Preparing picture {min(n+1,total)} of {total}.')
            result=build(root,project,plan,output,allow_tail,report,width=width,height=height)
            if not is_current(project,plan):raise ValueError('Project or sound-bite plan changed during preparation. Prepare again.')
            record={'output':output.name,'project_version':project.get('updated'),'plan_revision':plan['revision'],'width':width,'height':height,**result}
            with GUARD:
                dest=root/'reviews'/'documentary_review_preview.json';dest.parent.mkdir(parents=True,exist_ok=True);temp=dest.with_name(dest.name+'.'+uuid.uuid4().hex+'.tmp')
                try:temp.write_text(json.dumps(record,indent=2),encoding='utf-8');temp.replace(dest)
                finally:temp.unlink(missing_ok=True)
                job.update(status='done',detail='Documentary timeline review preview ready.',**result)
        except Exception as e:
            output.unlink(missing_ok=True)
            with GUARD:job.update(status='error',detail=str(e))
    threading.Thread(target=run,daemon=True,name='documentary-preview-'+pid).start();return dict(job)


def status(pid):
    with GUARD:return dict(JOBS.get(pid,{}))
