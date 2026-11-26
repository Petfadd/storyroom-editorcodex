"""Conservative, frame-indexed verification for script-directed exports.

CFR sources are verified by decoded frame timestamps; unreliable timestamps fail closed.
Source frames are selected by index; normal output-rate conversion keeps 1x playback.
"""
from pathlib import Path
from threading import Lock
from fractions import Fraction

_cache = {}
_lock = Lock()
FPS = 30
# Set by the app to a function returning its cache.Store. The frame check is the slow
# part of a build (every source decoded from its first frame); its result is a fact
# about the file, so it is kept on disk and survives a restart. Without this, the first
# build after every restart decoded every source again.
disk_store = None
_DISK_KIND = 'analysis'
_DISK_VERSION = 'frame-check-v1'


def decode_threads():
    """Half the machine's cores, at most 4, at least 1: the rest stay free for the UI."""
    import os
    return max(1, min(4, (os.cpu_count() or 2) // 2))


def _disk_name(path, stat):
    from cache import key
    return 'framecheck-' + key(str(Path(path).resolve()), stat.st_size, stat.st_mtime_ns, _DISK_VERSION)


def _disk_get(path, stat, required_frames):
    try:
        store = disk_store() if disk_store else None
        data = store.read_json(_DISK_KIND, _disk_name(path, stat)) if store else None
        if data and int(data.get('frames', 0)) >= required_frames:
            store.touch(_DISK_KIND, _disk_name(path, stat), '.json')
            return {'frames': int(data['frames']), 'fps': Fraction(data['fps'])}
    except Exception:
        pass
    return None


def _disk_put(path, stat, result):
    try:
        store = disk_store() if disk_store else None
        if store:
            store.write_json(_DISK_KIND, _disk_name(path, stat), {'frames': result['frames'], 'fps': str(result['fps'])})
    except Exception:
        pass

def _nearest_frame(ms, fps=Fraction(FPS,1), half_up=False):
    # Exactly half a frame is ambiguous. The strict script-review check reports it.
    # The documentary film clock (v24) rounds it to the later frame instead: a script
    # written in 20 ms steps lands on half frames all over a 25 fps film (146 times in
    # one real script), and both sides of a cut round the same time the same way, so
    # nothing gaps, overlaps or drifts. Cutaways and name cards already round this way.
    f=Fraction(int(ms),1000)*fps
    n=f.numerator//f.denominator
    if f-n==Fraction(1,2):
        if half_up:
            return n+1
        raise ValueError(f'{int(ms)/1000:.3f}s is exactly halfway between two frames at {float(fps):g} fps; choose a boundary')
    return n + int(f-n>Fraction(1,2))

def source_rate(path):
    import av
    try:
        with av.open(str(path)) as container:
            rate=container.streams.video[0].average_rate
            if not rate or rate<=0 or rate>120:raise ValueError('source frame rate is unavailable or unsupported')
            return Fraction(rate)
    except ValueError:raise
    except Exception as e:raise ValueError('source frame rate could not be verified: '+str(e)[:200]) from e

_DISCARD = 0x4          # AV_PKT_FLAG_DISCARD: a frame an edit list hides; decoders drop it
_REORDER_MARGIN = 64    # packets read past the target so B-frame reordering is covered


def _ffmpeg_exe():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        import shutil
        return shutil.which('ffmpeg')


def packet_scan(path, required_frames, target, progress=None):
    """Prove the same facts as the decode, from the file's packet index alone.

    Every coded picture is one packet carrying its presentation time, so sorting the
    packet times of the video stream gives exactly the frame times the decoder would
    produce -- without decoding a single picture. ffmpeg's stream copy reads them in
    about one-fortieth of the time a 1080p decode takes.

    Returns {'frames', 'fps'} when the file is regular, or None when anything is
    unusual (no ffmpeg, uneven spacing, a parse problem). None sends the caller to
    the full decode, which stays the authority and gives the precise error.
    """
    import subprocess
    exe = _ffmpeg_exe()
    if not exe:
        return None
    cmd = [exe, '-v', 'error', '-nostdin', '-i', str(path), '-map', '0:v:0',
           '-c', 'copy', '-f', 'framecrc', '-']
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                text=True, creationflags=flags)
    except Exception:
        return None
    tb = None; times = []; stopped = False
    try:
        for line in proc.stdout:
            if line.startswith('#'):
                if line.startswith('#tb 0:'):
                    num, den = line.split(':', 1)[1].strip().split('/')
                    tb = Fraction(int(num), int(den))
                continue
            parts = [p.strip() for p in line.split(',')]
            if len(parts) < 6 or parts[0] != '0':
                continue
            flag = 1
            if len(parts) > 6 and parts[6].startswith('F='):
                flag = int(parts[6][2:], 16)
            if flag & _DISCARD:
                continue
            if parts[2] in ('', 'N/A', 'NOPTS'):
                return None
            times.append(int(parts[2]))
            if progress and len(times) % 2000 == 0:
                progress(min(len(times), required_frames), required_frames)
            if len(times) >= target + _REORDER_MARGIN:
                stopped = True
                break
    except Exception:
        return None
    finally:
        try:
            proc.kill() if stopped else None
            proc.stdout.close(); proc.wait(timeout=10)
        except Exception:
            pass
    if tb is None or len(times) < 2:
        return None
    times.sort()
    usable = times[:-_REORDER_MARGIN] if stopped else times
    if len(usable) < 2:
        return None
    step = usable[1] - usable[0]
    if step <= 0:
        return None
    # Constant frame rate means every picture is exactly one step after the last.
    # Anything else -- rounded time bases, gaps, duplicates -- goes to the decode.
    for a, b in zip(usable, usable[1:]):
        if b - a != step:
            return None
    rate = 1 / (Fraction(step) * tb)
    if rate <= 0 or rate > 120:
        return None
    count = min(len(usable), target)
    if count < required_frames:
        return None          # let the decode report exactly where the source ends
    return {'frames': count, 'fps': rate}


def inspect_video(path, required_frames, progress=None):
    """Decode from the first frame, verifying each PTS through the exclusive OUT.

    `progress(done, total)` is called as frames are checked. This decode is the slow
    part of a documentary build, and reporting it is the difference between a progress
    bar that moves and one that sits still for a minute and then finishes.
    """
    import av
    path=Path(path);stat=path.stat();key=(str(path.resolve()),stat.st_size,stat.st_mtime_ns)
    # Cached answers skip the decode lock.
    cached=_cache.get(key)
    if cached and cached['frames']>=required_frames:return cached
    saved=_disk_get(path,stat,required_frames)
    if saved:
        _cache[key]=saved;return saved
    # A margin, so a later +1-frame check doesn't re-decode the file.
    target=required_frames+max(300,required_frames//10)
    with _lock:
        cached=_cache.get(key)
        if cached and cached['frames']>=required_frames:return cached
        fast=packet_scan(path,required_frames,target,progress)
        if fast:
            if progress:progress(required_frames,required_frames)
            _cache[key]=fast;_disk_put(path,stat,fast);return fast
        try:
            with av.open(str(path)) as container:
                stream=container.streams.video[0]
                # A few cores only, so the editor stays responsive; same frames, same PTS.
                threads=decode_threads()
                try:
                    stream.codec_context.thread_type='AUTO';stream.codec_context.thread_count=threads
                except Exception:
                    try:stream.thread_type='AUTO';stream.thread_count=threads
                    except Exception:pass
                # `average_rate` is frames divided by duration, so it drifts a few
                # thousandths of a frame per second away from the rate the frames
                # were actually laid out at. Checking PTS spacing against it makes
                # a perfectly regular file look discontinuous. `base_rate` is the
                # rate the stream declares, which is the one the timeline follows.
                rate=stream.base_rate or stream.average_rate
                if not rate or rate<=0 or rate>120:raise ValueError('source frame rate is unavailable or unsupported')
                rate=Fraction(rate)
                first=None;count=0;reported=0
                for frame in container.decode(stream):
                    if frame.pts is None or frame.time_base is None:raise ValueError('source frame timestamps are unavailable')
                    pts=Fraction(frame.pts)*frame.time_base
                    if first is None:first=pts
                    # Permit only timestamp quantization (one source time-base tick).
                    expected=Fraction(count,1)/rate
                    if abs((pts-first)-expected)>max(Fraction(stream.time_base),Fraction(1,1000000)):
                        raise ValueError(f'variable or discontinuous frame timestamps near source frame {count}')
                    count+=1
                    # Report about every hundred frames: often enough to look alive,
                    # rare enough that the callback costs nothing against decoding.
                    if progress and count-reported>=100:
                        reported=count
                        progress(min(count,required_frames),required_frames)
                    if count>=target:break
                if count<required_frames:raise ValueError(f'source ended after {count} frames, before the exclusive OUT frame {required_frames}')
                result={'frames':count,'fps':rate};_cache[key]=result;_disk_put(path,stat,result);return result
        except ValueError:raise
        except Exception as e:raise ValueError('source frames could not be verified: '+str(e)[:200]) from e

# Rebuild path: fast, bounded source check. The exact source windows and clip
# duration are already checked by documentary_strict/footage metadata; a rebuild
# only needs to verify that the video can actually be opened and sought near its
# last requested picture. Full contiguous frame audits remain in strict_cuts.report
# and the final export validation, not in the interactive rebuild loop.
_ENDPOINTS = {}


def verify_source_endpoint(path, out_ms, source_name=''):
    """Seek to the last requested picture without decoding a whole source.

    This is intentionally NOT a substitute for the full frame-by-frame export
    audit. It checks source accessibility; all Beat ranges are separately bounded
    by the project's measured media duration before this function is called.
    """
    path=Path(path)
    stat=path.stat()
    if out_ms <= 0:
        raise ValueError(f'{source_name or path.name}: source OUT must be positive.')
    key=(str(path.resolve()),stat.st_size,stat.st_mtime_ns,int(out_ms))
    if key in _ENDPOINTS:
        return _ENDPOINTS[key]
    import av
    try:
        with av.open(str(path)) as container:
            stream=container.streams.video[0]
            rate=stream.base_rate or stream.average_rate
            if not rate or rate <= 0 or rate > 120:
                raise ValueError('Source frame rate is unavailable or unsupported.')
            fps=Fraction(rate)
            frame_ms=Fraction(1000,1)/fps
            # Seek to a nearby keyframe and decode only the final few seconds.
            # A few codecs require >1s pre-roll, hence the 4-second window.
            seek_ms=max(0, int(out_ms)-4000)
            timestamp=int(Fraction(seek_ms,1000)/stream.time_base)
            container.seek(timestamp,stream=stream,backward=True)
            observed=False
            frames_seen=0
            threshold=Fraction(out_ms,1000)-Fraction(1,1)/fps
            for frame in container.decode(stream):
                frames_seen+=1
                if frame.pts is not None and frame.time_base is not None:
                    pts=Fraction(frame.pts)*frame.time_base
                    if pts>=threshold-Fraction(2,1000):
                        observed=True
                        break
                if frames_seen>=720:break
            if not observed:
                # A source with an unusual timestamp origin or sparse keyframes
                # needs the existing full verification instead of a false pass.
                required=_nearest_frame(out_ms,fps,half_up=True)
                result=inspect_video(path,required)
            else:
                result={'frames_checked_near_end':frames_seen,'fps':str(fps),'out_ms':int(out_ms)}
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f'{source_name or path.name}: cannot seek to its final required source frame: {str(exc)[:180]}') from exc
    _ENDPOINTS[key]=result
    return result


def report(project, root, progress=None):
    if project.get('edit_mode') == 'documentary' and project.get('documentary_beat_review'):
        from documentary_cue_groups import report as documentary_report
        return documentary_report(project, root, progress)
    root=Path(root);scenes=project.get('scenes') or [];assets={a['id']:a for a in project.get('assets',[])}
    required=bool(project.get('production_script')) or any((s.get('plan_row') or {}).get('strict_production') for s in scenes)
    result={'required':required,'checked_version':project.get('updated'),'mode':'strict frame-indexed 30 fps' if required else 'not applicable','shots':[],'errors':[],'adjustments':[]}
    if not required:return result
    if not scenes:result['errors'].append('No storyboard shots are placed.');return result
    last=0;previous_script_out=0
    expected=[b.get('number') for b in (project.get('srt') or {}).get('blocks',[])]
    seen=[]
    for i,s in enumerate(scenes):
        if progress:progress(i,len(scenes))
        row=s.get('plan_row') or {};label=row.get('shot_id') or f'Scene {i+1}';a=assets.get(s.get('asset_id'))
        item={'scene':i+1,'id':s.get('id'),'shot':label,'file':row.get('source_file'),'assigned_file':(a or {}).get('original_name',(a or {}).get('name')),'script_in_ms':row.get('source_in_ms'),'script_out_ms':row.get('source_out_ms'),'placed_in_ms':None,'placed_out_ms':None,'in_deviation_ms':None,'out_deviation_ms':None,'saved_in_ms':float(s.get('in_s',0))*1000,'timeline_script_in_ms':row.get('timeline_in_ms'),'timeline_script_out_ms':row.get('timeline_out_ms'),'timeline_placed_in_ms':s.get('frame_in',0)*1000/FPS,'timeline_placed_out_ms':s.get('frame_out',0)*1000/FPS,'errors':[],'adjustments':[],'photo':bool(row.get('uploaded_photo'))}
        err=item['errors']
        def fail(message):err.append(message)
        if not row.get('strict_production'):fail('No exact script shot and source timing is attached to this slot.')
        cue=list(dict.fromkeys(row.get('srt_blocks') or []))
        if len(cue)!=1:fail('Exactly one SRT cue must be assigned to this shot.')
        else:
            seen.append(cue[0])
            if i>=len(expected) or cue[0]!=expected[i]:fail('Shot does not match its SRT cue in the original order.')
        tin,tout=row.get('timeline_in_ms'),row.get('timeline_out_ms')
        if s.get('frame_in')!=last or s.get('frame_out',0)<=s.get('frame_in',0):fail('Placed timeline has a gap, overlap, or empty shot.')
        last=s.get('frame_out',last)
        if tin is None or tout is None:fail('Script narration IN/OUT is missing.')
        else:
            if tin!=previous_script_out:fail('Script narration shots have a gap or overlap.')
            previous_script_out=tout
            try:
                if s.get('frame_in')!=_nearest_frame(tin) or s.get('frame_out')!=_nearest_frame(tout):fail('Placed timeline differs from the nearest output-frame boundaries.')
            except ValueError as e:fail(str(e)+' (narration timeline).')
        if s.get('transition')!='cut':fail('Only a clean cut is allowed in strict mode.')
        if not a:fail('Shot is unassigned or the named source is missing.')
        elif not (root/a.get('path','')).is_file():fail('Assigned source file is missing from disk.')
        if a and item['assigned_file']!=row.get('source_file'):fail('Assigned filename does not exactly match the script.')
        if row.get('uploaded_photo'):
            if a and a.get('kind')!='image':fail('The named photograph is not an uploaded image.')
        else:
            si,so=row.get('source_in_ms'),row.get('source_out_ms')
            if si is None or so is None:fail('Script source IN or exclusive OUT is missing.')
            else:
                if so<=si:fail('Source OUT must be after IN.')
                if tin is not None and tout is not None and so-si!=tout-tin:fail('Source OUT minus IN does not equal the script narration span.')
                try:
                    if not a or a.get('kind')!='video':
                        if a:fail('The named video is not assigned as a video.')
                    else:
                        path=root/a.get('path','')
                        if path.resolve()!=(root/'sources'/path.name).resolve():fail('Assigned video path cannot be matched to the renderer source file.')
                        if so>float(a.get('duration') or 0)*1000+0.000001:fail('Script OUT exceeds the source runtime.')
                        if path.is_file():
                            rate=source_rate(path);fi,fo=_nearest_frame(si,rate),_nearest_frame(so,rate)
                            pin=float(Fraction(fi,1)/rate*1000);pout=float(Fraction(fo,1)/rate*1000)
                            item.update(source_start_frame=fi,source_end_frame=fo,source_fps=str(rate),placed_in_ms=pin,placed_out_ms=pout,in_deviation_ms=pin-si,out_deviation_ms=pout-so)
                            actual_duration=Fraction(fo-fi,1)/rate;output_duration=Fraction(s.get('frame_out',0)-s.get('frame_in',0),FPS)
                            difference=output_duration-actual_duration
                            # A user-authorized exception: for a shortfall of at most one
                            # output frame, use exactly the next source frame if that
                            # makes the durations compatible. Never slow, freeze or loop.
                            extend=(difference>=Fraction(1,2*FPS) and difference<=Fraction(1,FPS)
                                    and abs(actual_duration+Fraction(1,1)/rate-output_duration)<Fraction(1,2*FPS))
                            if fo<=fi:fail('Snapped source interval contains no frames.')
                            if fo>fi>=0:
                                try:
                                    inspect_video(path,fo+1 if extend else fo)
                                    if extend:
                                        fo+=1;pout=float(Fraction(fo,1)/rate*1000)
                                        item.update(source_end_frame=fo,placed_out_ms=pout,out_deviation_ms=pout-so,added_source_frames=1)
                                        item['adjustments'].append('One source frame added after the snapped script OUT; it may also appear at the next cut.')
                                    elif abs(difference)>=Fraction(1,2*FPS):fail('Snapped source and output durations differ by at least half an output frame; exact placement is not possible.')
                                except (ValueError,OSError,ImportError) as e:
                                    fail(('The extra source frame could not be verified: ' if extend else '')+str(e))
                    if abs(float(s.get('in_s',0))*1000-si)>1e-6:fail('Saved source IN differs from the script.')
                except (ValueError,OSError,ImportError) as e:fail(str(e)+' (source).')
        result['shots'].append(item)
        result['errors'].extend(f'{label}: {e}' for e in err)
        result['adjustments'].extend(f'{label}: {e}' for e in item['adjustments'])
    blocks=(project.get('srt') or {}).get('blocks',[])
    if blocks and blocks[-1].get('end_ms') is not None and previous_script_out!=blocks[-1]['end_ms']:result['errors'].append('The script timeline does not end at the original final SRT OUT.')
    if len(scenes)!=len(expected):result['errors'].append(f'Expected {len(expected)} shots for {len(expected)} SRT cues, found {len(scenes)}.')
    return result
