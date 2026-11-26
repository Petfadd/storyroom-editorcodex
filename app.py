from __future__ import annotations
import winsafe  # noqa: F401 -- installs the Windows file-swap retry on import
import copy, hashlib, json, math, re, sys, threading, time, uuid, subprocess, os, shutil
from pathlib import Path
from collections import defaultdict
from functools import wraps
from flask import Flask, request, jsonify, send_from_directory, send_file, render_template, Response
from werkzeug.exceptions import BadRequest, NotFound, RequestEntityTooLarge, HTTPException
from types import SimpleNamespace
from PIL import Image, ImageOps
import cv2, imageio_ffmpeg
BASE=Path(__file__).resolve().parent
import media_tools
media_tools.register_private_packages()
from engine import RenderJob
import upscale
import transitions
import captions
# Verified playback schedules, keyed by project. Rebuilt only when the project or
# plan revision changes.
SCHEDULE_CACHE={};SCHEDULE_LOCKS=defaultdict(threading.Lock)

def _schedule_path(pid):
 return folder(pid)/'.cache'/'playback_schedule.json'

def _schedule_from_disk(pid,key):
 """Return the cached schedule when it was built for this exact version."""
 import json
 try:
  data=json.loads(_schedule_path(pid).read_text())
 except (OSError,ValueError):
  return None
 if list(data.get('key') or [])!=list(key):return None
 return data.get('events')

def _schedule_to_disk(pid,key,events):
 """Best effort: an unwritable cache must never break playback."""
 import json
 try:
  path=_schedule_path(pid);path.parent.mkdir(parents=True,exist_ok=True)
  path.write_text(json.dumps({'key':list(key),'events':events}))
 except OSError:
  pass
from document_plan import synchronize
PROJECTS=BASE/'projects';PROJECTS.mkdir(exist_ok=True)
MAX_VIDEO_BYTES=8*1024**3
app=Flask(__name__);app.config['TEMPLATES_AUTO_RELOAD']=True;app.config['MAX_CONTENT_LENGTH']=MAX_VIDEO_BYTES
LOCKS=defaultdict(threading.RLock);THUMBNAIL_SLOTS=threading.BoundedSemaphore(2);JOBS={};FFMPEG=imageio_ffmpeg.get_ffmpeg_exe()

# ---- Who may talk to this editor ------------------------------------------------------
# It has no sign-in, so it listens on this computer only unless STORYROOM_HOST says
# otherwise (0.0.0.0 shares it on the local network). Two checks apply either way:
#  * the address in the browser must be this machine or a plain IP address, so a web
#    page cannot reach the editor through a look-alike name (DNS rebinding);
#  * a request that changes anything must come from the editor's own page, so another
#    website open in the same browser cannot send it commands.
import ipaddress as _ip
_LOCAL_NAMES={'localhost','127.0.0.1','::1'}
_EXTRA_HOSTS={h.strip().lower() for h in os.environ.get('STORYROOM_ALLOWED_HOSTS','').split(',') if h.strip()}
def _host_only(value):
 value=(value or '').strip().lower()
 if value.startswith('['):return value[1:value.find(']')] if ']' in value else value
 return value.rsplit(':',1)[0] if value.count(':')==1 else value
def _allowed_host(host):
 name=_host_only(host)
 if name in _LOCAL_NAMES or name in _EXTRA_HOSTS:return True
 try:_ip.ip_address(name);return True          # reached by IP on the local network
 except ValueError:return False
@app.before_request
def _guard_requests():
 if not _allowed_host(request.host):
  return jsonify({'error':'This editor only answers at localhost or its IP address. Set STORYROOM_ALLOWED_HOSTS to add a name.'}),403
 if request.method not in ('GET','HEAD','OPTIONS'):
  origin=request.headers.get('Origin') or ''
  if origin and origin!='null':
   from urllib.parse import urlparse
   if urlparse(origin).netloc.lower()!=request.host.lower():
    return jsonify({'error':'Refused: this request came from another website.'}),403
  elif origin=='null':
   return jsonify({'error':'Refused: this request came from another website.'}),403
# Machine-wide settings and the single job queue. The queue is created here so every
# feature submits into the same dispatcher instead of starting its own threads.
import settings_store, jobqueue, proxy as proxy_module
SETTINGS=settings_store.Settings(BASE/'settings.json');SETTINGS.load()
import strict_cuts as _strict_cuts
_strict_cuts.disk_store=lambda:SETTINGS.cache_store()[0]
QUEUE=jobqueue.QUEUE
QUEUE_DISK_STATE=BASE/'.cache'/'queue_state.json'
jobqueue.QUEUE._state_path=QUEUE_DISK_STATE
jobqueue.QUEUE.start()
PROFILES=json.loads((BASE/'blueprints/style_profiles.json').read_text())
# Output geometry is a project setting, not a constant. `format` picks an aspect; `size`
# picks the pixel target. Anything the engine can encode is allowed, so the same build
# serves a 720p review, a 1080p master, a vertical cut and a square one.
TRANSITION_POLICIES=['clean_cuts_only','allow_dissolves']
ASPECTS={'landscape':(16,9),'portrait':(9,16),'square':(1,1),'vertical_4_5':(4,5),'cinema':(239,100)}
DEFAULT_SIZE={'landscape':'1080p','portrait':'1080p','square':'1080p','vertical_4_5':'1080p','cinema':'1080p'}
SIZES={'480p':480,'540p':540,'720p':720,'1080p':1080,'1440p':1440,'4k':2160}
# The export page offers three named resolutions. Each is a pair of pixel numbers people
# recognise, but the project still stores the SHORT side so a vertical film stays vertical:
# 2K QHD is 2560x1440 landscape and 1440x2560 portrait, never 1920 wide.
EXPORT_RESOLUTIONS=[
 {'key':'2k','label':'2K QHD','width':2560,'height':1440,'short':1440},
 {'key':'4k','label':'4K UHD','width':3840,'height':2160,'short':2160},
]
# 1080p is the default and names the short side already, so it is listed first for display
# but kept in SIZES where every existing caller expects it.
EXPORT_CHOICES=[
 {'key':'1080p','label':'1080p Full HD','width':1920,'height':1080,'short':1080},
 {'key':'2k','label':'2K QHD','width':2560,'height':1440,'short':1440},
 {'key':'4k','label':'4K UHD','width':3840,'height':2160,'short':2160},
]
# `2k` is stored as the `1440p` short side: one number, no second code path.
SIZE_ALIASES={'2k':'1440p'}
# What the AI stage is allowed to do to a picture. Nothing here changes duration, frame
# rate, aspect, audio or a single frame's timing; they are picture-quality settings only.
PICTURE_UPSCALERS={'auto':'Decide from the source','realesrgan':'Real-ESRGAN (AI)','lanczos':'Lanczos (no AI)'}
FRAMING_MODES={'auto':'Fit, crop or blur by source shape','fit':'Fit whole frame','crop':'Crop to fill','blur':'Blurred background'}
QUALITY_PRESETS={'high':{'crf':18,'audio_kbps':256,'label':'High'},"standard":{'crf':20,'audio_kbps':192,'label':'Standard'},'compact':{'crf':23,'audio_kbps':160,'label':'Compact'}}
def valid_size(size):
 """True for a named target or an explicit WxH in a sane range."""
 size=str(size or '').strip()
 if size in SIZES:return True
 # The export page names 2K by what it is. It is stored as the 1440p short side.
 if size in SIZE_ALIASES:return True
 match=re.fullmatch(r'\s*(\d{2,5})\s*[x×]\s*(\d{2,5})\s*',size)
 if not match:return False
 w,h=int(match[1]),int(match[2])
 return 64<=w<=7680 and 64<=h<=7680

def output_size(fmt,size):
 """Pixel width and height for an aspect and a target, rounded to even numbers.

 A target names the SHORT side in every case, so "1080p" always means the number people
 mean by it: 1920x1080 landscape, 1080x1920 portrait, 1080x1080 square, 1080x1350 for 4:5.
 An explicit "1920x1080" is also accepted and used as written.
 """
 fmt=fmt if fmt in ASPECTS else 'landscape'
 if size in SIZES:short=SIZES[size]
 else:
  match=re.fullmatch(r'\s*(\d{2,5})\s*[x×]\s*(\d{2,5})\s*',str(size or ''))
  if match:return (max(2,int(match[1])//2*2),max(2,int(match[2])//2*2))
  short=SIZES['1080p']
 aw,ah=ASPECTS[fmt]
 if aw>=ah:w,h=int(round(short*aw/ah)),short       # landscape: short side is the height
 else:w,h=short,int(round(short*ah/aw))             # portrait: short side is the width
 return max(2,w//2*2),max(2,h//2*2)

def export_choice(key):
 """The export-page resolution entry for a key, or None for anything else.

 Resolves in both directions: `2k` for a fresh request, and `1440p` for a project
 that was saved through the alias, so the label survives a reload.
 """
 key=str(key or '')
 key=SIZE_ALIASES.get(key,key)
 found=next((c for c in EXPORT_CHOICES if c['key']==key),None)
 if found:return found
 # Reverse lookup: the stored short side identifies the choice it came from.
 return next((c for c in EXPORT_CHOICES if c['key'] in SIZE_ALIASES and SIZE_ALIASES[c['key']]==key),None) or \
        next((c for c in EXPORT_CHOICES if c['key']==key),None)

def stored_size(key):
 """Turn an export-page choice into the size value a project stores.

 2K QHD is stored as `1440p` because a size names the short side: 1440 is what
 distinguishes it from 1080p and 2160. Keeping one spelling avoids two settings that
 mean the same thing and can therefore disagree.
 """
 key=str(key or '').strip()
 return SIZE_ALIASES.get(key,key)

def upscale_factor(source_short,target_short):
 """Smallest power-of-two factor that reaches the target, or 1 when none is needed.

 Real-ESRGAN works at x2 and x4. Asking for the smallest factor that covers the gap
 means a 720p source going to 1080p is not thrown through a x4 network and then
 crushed back down: it takes x2 and the resize finishes the job.
 """
 if not source_short or source_short<=0:return 1
 if target_short<=source_short:return 1
 return 2 if target_short<=source_short*2 else 4

def export_plan(p,fmt=None,size=None):
 """Everything the export page needs to describe a render before it starts.

 Returned to the browser so the number shown beside a resolution is the same number
 the renderer acts on, computed from the actual source dimensions.
 """
 fmt=fmt or p.get('format','landscape')
 requested=size if size is not None else p.get('size')
 size=stored_size(requested)
 # The choice is resolved from the REQUESTED value, not the stored alias: after `2k`
 # is stored as `1440p`, looking up `1440p` would lose the 2K label it came from.
 choice=export_choice(requested)
 width,height=output_size(fmt,size)
 target_short=min(width,height)
 sources=[]
 for a in p.get('assets') or []:
  if a.get('derived_from'):continue
  dims=asset_dimensions(a)
  if not dims:continue
  sw,sh=dims;source_short=min(sw,sh)
  sources.append({'id':a['id'],'name':a.get('original_name') or a.get('name'),'kind':a.get('kind'),
                  'width':sw,'height':sh,'factor':upscale_factor(source_short,target_short)})
 return {'size':size,'choice':choice['key'] if choice else None,'label':choice['label'] if choice else size,
         'width':width,'height':height,'target_short':target_short,'sources':sources,
         'max_factor':max([s['factor'] for s in sources],default=1),
         'choices':EXPORT_CHOICES}

def asset_dimensions(a):
 """Width and height of an uploaded asset, read once and cached on the asset itself."""
 dims=a.get('dimensions')
 if isinstance(dims,list) and len(dims)==2 and all(isinstance(x,int) and x>0 for x in dims):
  return tuple(dims)
 return None


# clips_only keeps native moving footage everywhere; mixed allows verified stills as well.
POLICIES={'clips_only':'Moving footage only','mixed':'Moving footage and photographs'}
STILL_LAYOUTS={'blurred_fit':'Photograph fitted over a blurred copy of itself','full_bleed':'Photograph cropped to fill the frame'}

def policy(p):return p.get('picture_policy') if p.get('picture_policy') in POLICIES else 'clips_only'

def is_still(p,asset):
 if not asset:return False
 if asset.get('kind')=='image':return True
 return str((asset.get('derived_from') or {}).get('kind') or '').lower()=='image'
def uid():return uuid.uuid4().hex[:16]
def write(path,data):
 t=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp');t.write_text(json.dumps(data,indent=2),encoding='utf-8');t.replace(path)
def folder(pid):
 if not re.fullmatch('[a-f0-9]{16}',pid):raise NotFound('Production not found.')
 p=PROJECTS/pid
 if not (p/'project.json').exists():raise NotFound('Production not found.')
 return p
def load(pid):
 # Scripts saved before Windows line endings were normalised on upload still hold
 # CRLF text, which no field reader can parse. Repair it on read so an existing
 # project is not stranded; the wording, order and timings are untouched.
 p=json.loads((folder(pid)/'project.json').read_text())
 script=p.get('production_script') or {}
 if '\r' in (script.get('text') or ''):
  script['text']=script['text'].replace('\r\n','\n').replace('\r','\n')
 return p
_SNAPSHOTS={};_SNAPSHOT_GUARD=threading.Lock()
def snapshot(pid):
 """The project as last saved, parsed once per saved version. READ-ONLY: never change
 or save what this returns. Image and status requests use it; a timeline asks for a
 couple of hundred thumbnails and posters at a time, and parsing the whole project file
 for each of them is what made the editor lag while it rendered."""
 path=folder(pid)/'project.json';st=path.stat();sig=(st.st_mtime_ns,st.st_size)
 with _SNAPSHOT_GUARD:
  hit=_SNAPSHOTS.get(pid)
  if hit and hit[0]==sig:return hit[1]
 p=load(pid)            # files are replaced atomically by write(), so no lock is needed
 with _SNAPSHOT_GUARD:_SNAPSHOTS[pid]=(sig,p)
 return p
def cached_image(response,request_version):
 """Thumbnails whose link names the source revision never change: let the browser
 keep them, so re-drawing the timeline or media pool sends no requests at all."""
 if request_version:response.storyroom_immutable=True
 return response
def _editor_input_signature(p):
 """Cheap input-only fingerprint: timeline edits MUST NOT schedule Beat rebuilds.

 A real change to narration, SRT, production script, imported media, stills,
 or featured-person configuration triggers an automatic replacement from the inputs.
 Script/audio bytes are hashed by path/revision/text; media itself is not reread.
 """
 script=(p.get('production_script') or {}).get('text','')
 srt=(p.get('srt') or {}).get('blocks') or []
 voice=p.get('voiceover') or {}
 assets=[(a.get('id'),a.get('original_name'),a.get('revision'),a.get('path'))
         for a in (p.get('assets') or []) if not a.get('derived_from')]
 people=[(x.get('id'),x.get('name'),x.get('photo'),x.get('show')) for x in (p.get('people') or [])]
 payload=json.dumps([script,srt,voice.get('path'),voice.get('revision'),assets,people],sort_keys=True,default=str)
 return hashlib.sha256(payload.encode('utf-8')).hexdigest()

def save(p):
 from approval import ensure_automatic_policy
 ensure_automatic_policy(p)
 synchronize(p)
 from production import reserve_id
 for a in p['assets']:
  a['reserve']=bool(reserve_id(a));a['source_label']=reserve_id(a) or Path(a.get('original_name',a['name'])).stem
 by_id={a['id']:a for a in p['assets']}
 for scene in p['scenes']:
  asset=by_id.get(scene.get('asset_id'));scene['source_label']=asset['source_label'] if asset else '';scene['source_role']='reserve' if asset and asset['reserve'] else 'primary' if asset else ''
 # Existing projects may lack a fingerprint. Compare the saved version once rather
 # than treating an ordinary edit as a new source import. Never substitute a shot.
 last=p.get('_editor_input_signature')
 if not last:
  try:last=_editor_input_signature(load(p['id']))
  except (OSError,ValueError,KeyError):last=None
 current=_editor_input_signature(p)
 inputs_changed=(last!=current)
 p['_editor_input_signature']=current
 p['updated']=time.time();write(folder(p['id'])/'project.json',p)
 # Keep a recoverable copy after every successful save. Best effort by design: a
 # project that cannot write history must still save. The snapshot is taken after the
 # write so it always records a state the app has already accepted.
 try:
  import project_history, os as _os
  if not _os.environ.get('STORYROOM_NO_HISTORY'):project_history.snapshot(folder(p['id']),p)
 except Exception:pass
 # No source changed: do not queue a costly auto-build, probe video inputs,
 # or reset the prepared preview for scale, transition, caption, and CTA edits.
 if inputs_changed and p.get('edit_mode')=='documentary':
  try:schedule_auto_build(p['id'], 1.0)
  except Exception:pass
def project_io_lock(func):
 @wraps(func)
 def locked(pid,*args,**kwargs):
  with LOCKS[pid]:return func(pid,*args,**kwargs)
 return locked

def busy(pid):return pid in JOBS and JOBS[pid].snapshot()['status'] in ['queued','running']

# ---------------------------------------------------------------------------------
# Automatic Beat build
#
# As soon as a documentary has its production script, SRT, narration and every video
# the script names (present and long enough), the Beat timeline is built by itself --
# repeats, narration gaps and back-to-back bites are accepted as the script wrote them
# -- and the preview audio is prepared after it. Any later change to those inputs (a
# new script, SRT or narration, a video finishing its download or being replaced)
# rebuilds it. Nothing is built while something is missing; the reason is recorded in
# p['auto_build'] for the editor to show.
_AUTO_TIMERS={};_AUTO_LOCK=threading.Lock()

def schedule_auto_build(pid,delay=4.0):
 with _AUTO_LOCK:
  old=_AUTO_TIMERS.pop(pid,None)
  if old:old.cancel()
  t=threading.Timer(delay,_auto_build,args=(pid,));t.daemon=True;_AUTO_TIMERS[pid]=t;t.start()

def _auto_fingerprint(p,root,beats):
 named={b['source_file'] for b in beats}
 parts=[hashlib.sha256(((p.get('production_script') or {}).get('text','')).encode()).hexdigest(),
        hashlib.sha256(json.dumps((p.get('srt') or {}).get('blocks') or [],sort_keys=True).encode()).hexdigest()]
 # New or replaced genuine photographs and their role assignments are part of the
 # picture plan too. A rebuild must not keep showing old people overlays.
 parts.append(hashlib.sha256(json.dumps([(a.get('original_name') or a.get('name'),a.get('revision')) for a in p.get('assets',[]) if a.get('kind')=='image'],sort_keys=True).encode()).hexdigest())
 parts.append(hashlib.sha256(json.dumps([(x.get('name'),x.get('role'),(x.get('photo') or {}).get('asset_id'),(x.get('photo') or {}).get('path')) for x in p.get('people',[])],sort_keys=True).encode()).hexdigest())
 voice=p.get('voiceover') or {}
 try:st=(root/voice.get('path','')).stat();parts.append(f"{voice.get('path')}|{st.st_size}|{st.st_mtime_ns}")
 except OSError:parts.append('no-voice')
 for a in sorted(p.get('assets') or [],key=lambda a:a.get('original_name') or ''):
  if (a.get('original_name') or a.get('name')) in named:
   try:st=(root/a.get('path','')).stat();parts.append(f"{a.get('original_name')}|{a.get('id')}|{st.st_size}|{st.st_mtime_ns}")
   except OSError:parts.append(f"{a.get('original_name')}|missing")
 return hashlib.sha256('\n'.join(parts).encode()).hexdigest()

def _auto_note(pid,status,reason=''):
 with LOCKS[pid]:
  p=load(pid);note={'status':status,'reason':reason,'at':time.time()}
  if (p.get('auto_build') or {}).get('status')==status and (p.get('auto_build') or {}).get('reason')==reason:return
  p['auto_build']=note;write(folder(pid)/'project.json',p)

def _auto_build(pid):
 import documentary_beat_build
 from documentary_beats import read_beats
 from documentary_beat_plan import proposal,frame_limits
 from documentary import load_plan
 try:
  if not (folder(pid)/'project.json').is_file():return
  if documentary_beat_build.snapshot(pid).get('status') in ('queued','running') or busy(pid):
   schedule_auto_build(pid,15.0);return
  # Do not start assembling half a new sheet while its files are still arriving.
  # Retry shortly after the downloader finishes; no old media is substituted.
  try:
   import footage_downloader as fd
   if fd.running(pid):schedule_auto_build(pid,2.0);return
  except ImportError:pass
  p=load(pid);root=folder(pid)
  if p.get('edit_mode')!='documentary':return
  script=(p.get('production_script') or {}).get('text','')
  if not script.strip() or not (p.get('srt') or {}).get('blocks') or not p.get('voiceover'):
   missing=[n for n,ok in (('production script',script.strip()),('SRT',(p.get('srt') or {}).get('blocks')),('narration',p.get('voiceover'))) if not ok]
   _auto_note(pid,'waiting','Waiting for: '+', '.join(missing)+'.');return
  try:beats=read_beats(script)
  except ValueError as e:_auto_note(pid,'error','The production script could not be read: '+str(e));return
  # Before expensive video probing, summarize only the filenames and exact
  # source durations the production script actually requires. Partial downloads
  # are normal project progress, not dozens of separate editing errors.
  from documentary_sync import required_source_state, readiness_message, srt_narration_bounds
  sources=required_source_state(beats,p.get('assets') or [],root)
  if not sources['all_ready']:
   status='waiting' if sources['missing'] and not (sources['ambiguous'] or sources['too_short']) else 'review'
   _auto_note(pid,status,readiness_message(sources));return
  alignment=srt_narration_bounds(beats,(p.get('srt') or {}).get('blocks') or [])
  if alignment['status']=='review':
   _auto_note(pid,'review',alignment['reason']);return
  fp=_auto_fingerprint(p,root,beats)
  if p.get('scenes') and (p.get('documentary_beat_review') or {}).get('auto_fingerprint')==fp:return
  if (p.get('auto_build') or {}).get('failed_fp')==fp:return   # same inputs failed before; wait for a change
  data=proposal(p,beats,None,None,frame_limits(root,p['assets']))
  if data.get('issues'):
   _auto_note(pid,'review',data['issues'][0]);return
  # A downloaded file being shorter than a scripted cut is not permission to
  # change the shot. A mechanical fit is still an edit. Present it for review
  # once instead of auto-applying any undeclared source-clock adjustment.
  if data.get('adjustments'):
   _auto_note(pid,'review',f'{len(data["adjustments"])} suggested footage-clock correction(s). '
              'The production script was not changed. Review the first: '+data['adjustments'][0]);return
  # proposal() treats every frame-sized uncovered interval as a blocker.
  # Sub-frame (container rounding) tails remain harmless and are not proposed.
  # No unassigned footage may be selected automatically, even for a short hole.
  current=load_plan(root)
  # The production script decides the film. A timeline made earlier by the automatic
  # Visual plan (its picture slots and its own sound bites) is replaced by the script's
  # Beat timeline instead of blocking it for good; the build keeps the old timeline and
  # puts it back if anything fails.
  body={'confirmed':True,'project_version':p.get('updated'),'plan_revision':current['revision'],
        'script_sha256':hashlib.sha256(script.encode()).hexdigest(),'replace_beat_timeline':bool(current['bites'] or p.get('scenes')),
        'approved_gaps':[],'approved_overlaps':data.get('repeated_ranges') or [],
        'allow_silent_tail':True,'approve_consecutive_bites':bool(data.get('consecutive_bites')),
        'scripted_review_beat':None,'scripted_review_source':None,'auto_fingerprint':fp}
  _auto_note(pid,'building','Building the Beat timeline from the production script…')
  body['project_version']=load(pid).get('updated')
  def work(report):
   try:return _documentary_beat_build_work(pid,root,body,report)
   except Exception as e:
    with LOCKS[pid]:
     q=load(pid);q['auto_build']={'status':'error','reason':str(e)[:400],'failed_fp':fp,'at':time.time()};write(folder(pid)/'project.json',q)
    raise
  documentary_beat_build.start(pid,work)
 except Exception as e:
  try:_auto_note(pid,'error',str(e)[:400])
  except Exception:pass
def editable(pid):
 if busy(pid):raise BadRequest('This production is exporting. Wait or cancel before editing.')
def stamp(t):
 h,m,s,ms=re.split('[:,.]',t);ms=(ms+'000')[:3]
 return ((int(h)*60+int(m))*60+int(s))*1000+int(ms)

def parse_srt(text):
 blocks=[];last=0;nums=set()
 for part in re.split(r'\n\s*\n',text.strip().replace('\r\n','\n')):
  lines=part.splitlines()
  if len(lines)<3 or not lines[0].strip().isdigit():raise BadRequest('SRT blocks need a number, time range and narration text.')
  # Cue clocks are accepted as the tools actually write them: a one- or two-digit hour
  # field and one to three millisecond digits. A 47-minute programme written as
  # 0:00:00,000 used to be rejected outright, which is a length limit nobody asked for.
  match=re.fullmatch(r'\s*(\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})\s*',lines[1])
  if not match:raise BadRequest('Use standard SRT time ranges: 00:00:00,000 --> 00:00:05,000.')
  n=int(lines[0]);a,b=map(stamp,match.groups());txt=' '.join(lines[2:]).strip()
  if n in nums or a<last or b<=a or not txt:raise BadRequest('SRT numbers must be unique and time ranges must be ordered, positive and non-overlapping.')
  nums.add(n);last=b;blocks.append({'number':n,'start_ms':a,'end_ms':b,'text':txt})
 if not blocks:raise BadRequest('The SRT is empty.')
 return blocks

def srt_stamp(ms):
 h,rem=divmod(int(ms),3600000);m,rem=divmod(rem,60000);sec,frac=divmod(rem,1000)
 return '%02d:%02d:%02d,%03d'%(h,m,sec,frac)

def probe(path):
 try:out=subprocess.run([FFMPEG,'-nostdin','-hide_banner','-probesize','2097152','-analyzeduration','3000000','-threads','2','-i',str(path)],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=15).stderr
 except subprocess.TimeoutExpired:raise ValueError('Metadata check timed out after 15 seconds. No full-video analysis was attempted. Check that the file is fully downloaded and playable locally.')
 m=re.search(r'Duration: (\d+):(\d+):(\d+\.\d+)',out)
 # Width and height are recorded here because ffmpeg has already decoded the stream
 # header; opening the file again in OpenCV just to learn its size is wasted work.
 v=re.search(r'Video:.*?(\d{2,5})x(\d{2,5})',out)
 return {'duration':int(m[1])*3600+int(m[2])*60+float(m[3]) if m else 0,'has_audio':'Audio:' in out,'has_video':'Video:' in out,
         'width':int(v[1]) if v else 0,'height':int(v[2]) if v else 0}

def intent(text,people,profile):
 """A coarse guess at a beat's tone, from wording alone.

 These word lists are hint dictionaries, not a taxonomy of subject matter: they exist to
 pick a movement family and an emotion label, and a production about any subject still
 resolves to neutral defaults when nothing matches. Add a production profile with its own
 lists instead of editing these for one programme.
 """
 found=next((x for x in people if any(re.search(r'\b'+re.escape(a)+r'\b',text,re.I) for a in [x['name']]+x.get('aliases',[]) if a)),None)
 lists=(PROFILES.get(profile) or {}).get('hints') or []
 # An unknown profile is not an error: with no hints the beat falls through to
 # the neutral defaults below, which is what every unmatched beat already gets.
 for hint in lists:
  if re.search(hint['pattern'],text,re.I):
   purpose,emotion,category=hint['purpose'],hint['emotion'],hint['category'];break
 else:purpose,emotion,category='develop the account','attention / restraint','general'
 if found:category='person'
 return purpose,emotion,category,found['name'] if found else ''

def motion(scene,index):
 # Intent chooses the family of movement; the stable hash only varies its path.
 n=int(hashlib.sha256(scene['id'].encode()).hexdigest()[:8],16);v=(n%997)/997;duration=(scene['frame_out']-scene['frame_in'])/30
 if scene.get('camera'):
  from cinematic import normalise
  camera=normalise(scene['camera'])
  if camera:
   return dict(id='motion-'+scene['id'],mode='photo_camera',move=camera.get('preset','custom'),
               emotion=scene.get('emotion',''),focus=scene.get('focus',''),duration_s=duration*(camera.get('motion_end') or 1),
               zoom_start=camera['zoom_start']/100,zoom_end=camera['zoom_end']/100,
               x_start=camera['x_start'],y_start=camera['y_start'],x_end=camera['x_end'],y_end=camera['y_end'],
               easing='linear' if camera['easing']=='linear' else 'smootherstep',
               rationale=camera.get('reason') or 'V11.7 restrained still-picture movement.')
 if scene.get('script_camera'):
  request=scene['script_camera'];move=request['move'];amount=request['amount'];z0,z1=(1,1+amount) if move=='push' else (1+amount,1) if move=='pull' else (1,1) if move=='static' else (1.04,1.04)
  phase0=request.get('phase_start',0);phase1=request.get('phase_end',1);full0,full1=z0,z1;z0=full0+(full1-full0)*phase0;z1=full0+(full1-full0)*phase1
  return dict(id='motion-'+scene['id'],mode='photo_camera',move=move,emotion=scene['emotion'],focus=scene['focus'],duration_s=duration,zoom_start=z0,zoom_end=z1,x_start=.25+.5*phase0 if move=='pan-right' else .5,x_end=.25+.5*phase1 if move=='pan-right' else .5,y_start=.5,y_end=.5,easing='linear',rationale=request['basis'])
 tone=(scene['emotion']+' '+scene['purpose']).lower();mode=scene.get('motion','auto')
 if any(k in tone for k in ['grief','mourning','remembrance','loss']):suggestions=['pull','reveal'];reason='Give the memory breathing room rather than manufacture urgency.'
 elif any(k in tone for k in ['orientation','place','location']):suggestions=['pan-left','pan-right','reveal'];reason='Reveal the spatial context that the narration is explaining.'
 elif any(k in tone for k in ['scrutiny','investigation','uncertainty']):suggestions=['push','reveal'] if scene.get('person') else ['pan-left','pan-right'];reason='Direct attention toward the subject, or survey the context, without implying an unverified exhibit.'
 elif any(k in tone for k in ['legal','accountability','clarity']):suggestions=['reveal','push'];reason='Identify the legal subject with a composed, restrained movement.'
 else:suggestions=['push','reveal','rise'];reason='Bring attention to the declared visual focus without a decorative effect.'
 if mode not in ['push','pull','pan-left','pan-right','rise','reveal']:mode=suggestions[(index+n)%len(suggestions)]
 z0,z1=(1.008+v*.006,1.055+v*.025) if mode=='push' else (1.065+v*.02,1.005+v*.01) if mode in ['pull','reveal'] else (1.05+v*.025,1.05+v*.025)
 x0,x1=(.78,.18) if mode=='pan-left' else (.18,.78) if mode=='pan-right' else (.35+v*.15,.40+v*.14)
 if mode not in ['pan-left','pan-right']:
  shift={'left':-.20,'center':0,'right':.20}.get(scene.get('focus_position'),0);x0+=shift;x1+=shift
 y0,y1=(.46,.23) if mode=='rise' else (.36,.40)
 factor=min(1.12,max(.5,duration/4.5))*{'subtle':.65,'purposeful':1,'strong':1.18}.get(scene.get('motion_strength'),1)
 factor*=(PROFILES.get(scene.get('profile')) or {}).get('motion_scale',1)
 z0=min(1.095,1+(z0-1)*factor);z1=min(1.095,1+(z1-1)*factor)
 return dict(id='motion-'+scene['id'],mode='photo_camera',move=mode,emotion=scene['emotion'],focus=scene['focus'],duration_s=duration,zoom_start=round(z0,6),zoom_end=round(z1,6),x_start=round(x0,6),x_end=round(x1,6),y_start=y0,y_end=y1,easing='quick_settle' if mode in ['push','pull','reveal'] else 'linear',rationale=reason+f' Complete the movement over {duration:.3f}s; human review must confirm the actual composition.')

def source_overlap_interval(scene, asset, project=None):
 """Use exact script boundaries for an unmodified strict shot; otherwise actual edit timing.

 The renderer's frame conformance still needs separate review. This avoids treating
 contiguous millisecond script ranges as overlaps solely due to 30-fps rounding.
 """
 if project and project.get('documentary_beat_review'):
  from documentary_storyboard import verified_source_interval
  interval=verified_source_interval(project,scene,asset)
  if interval is not None:return interval
 start=float(scene.get('in_s') or 0)
 end=start+(scene['frame_out']-scene['frame_in']+(scene.get('transition_handle_frames',4) if transitions.is_transition(scene.get('transition')) else 0))/30
 row=scene.get('plan_row') or {}
 if (row.get('strict_production') and scene.get('transition')=='cut' and
     asset.get('original_name',asset.get('name','')).casefold()==str(row.get('source_file','')).casefold() and
     row.get('source_in_ms') is not None and row.get('source_out_ms') is not None and
     abs(start-row['source_in_ms']/1000)<.001 and
     scene['frame_in']==round(row['timeline_in_ms']*.03) and scene['frame_out']==round(row['timeline_out_ms']*.03)):
  return start,row['source_out_ms']/1000
 return start,end

def beat_approvals(p):
 """Beat pairs whose source reuse the editor explicitly approved when building.

 The Beat storyboard saves the exact overlap and repeat decisions it was given.
 Re-flagging those same decisions at export time would mean nobody could ever
 finish a review, so they are read back here instead of being re-litigated.
 """
 review=p.get('documentary_beat_review') or {}
 pairs=set()
 for pair in review.get('approved_overlaps') or []:
  try:
   if isinstance(pair,(list,tuple)) and len(pair)==2:pairs.add(tuple(sorted((int(pair[0]),int(pair[1])))))
  except (TypeError,ValueError):continue
 repeats=set()
 for beat in review.get('repeated_ranges') or []:
  try:repeats.add(int(beat))
  except (TypeError,ValueError):continue
 return pairs,repeats

def _unapproved_repeats(p,errors):
 """Drop cooldown repeats the Beat build already approved.

 When a Beat timeline is built, every repeated source range is listed and approved
 with one checkbox. The six-slot cooldown check did not read that approval, so the
 same repeats came back at export as problems nobody could clear. A repeat inside
 one Beat, or between two Beats whose overlap was approved, is not reported again.
 """
 if not p.get('documentary_beat_review'):return errors
 pairs,repeats=beat_approvals(p);scenes=p.get('scenes') or [];kept=[]
 for e in errors:
  m=re.match(r'Scene (\d+): .*?from scene (\d+) inside',e) or re.match(r'Scene (\d+): .*?as scene (\d+) inside',e)
  if m:
   i,j=int(m.group(1)),int(m.group(2))
   if 0<i<=len(scenes) and 0<j<=len(scenes):
    a,b=scene_beat(scenes[i-1]),scene_beat(scenes[j-1])
    if a is not None and b is not None and (a==b or tuple(sorted((a,b))) in pairs or a in repeats or b in repeats):continue
  kept.append(e)
 return kept

def scene_beat(s):
 """The script Beat number a review scene was built from, or None if it has none.

 Sound-bite slots are saved with continuity "Documentary beat sound-bite", so the
 number has to come from plan_row['script_beat'] (e.g. '039'). Reading continuity
 alone returned None for every bite, and every approved reuse involving a bite was
 reported again at export as "source interval overlaps scene N".
 """
 row=s.get('plan_row') or {}
 beat=str(row.get('script_beat') or '').strip()
 if beat.isdigit():return int(beat)
 match=re.search(r'beat\s+(\d+)',str(row.get('continuity') or ''),re.I)
 return int(match.group(1)) if match else None

def scene_review(p,i,s,a,ranges,last,final=False):
 """Review one scene exactly as export readiness does. Bulk approval reuses this.

 Returns (errors, notes). `ranges` is the per-asset list of intervals already claimed
 by earlier scenes, so an overlap is caught the same way in both paths.
 """
 errors=[];notes=[];pre=f'Scene {i+1}: '
 if s['frame_in']!=last or s['frame_out']<=last:errors.append(pre+'timeline has a gap, overlap or empty scene.')
 if not a:return errors+[pre+'assign uploaded media.'],notes
 if not a['verified'] or not a['source'].strip():errors.append(pre+'confirm the asset’s identity/context and record its source.')
 person=s['person']
 # Earlier review drafts stored the whole Shows instruction as the person's name.
 # Interpret the explicit role/basis syntax without changing the saved draft or
 # granting identity verification; the photo still needs the user's label.
 if (s.get('plan_row') or {}).get('uploaded_photo') and person==(s.get('plan_row') or {}).get('shown_person'):
  from plain_script import shown_person_name
  person=shown_person_name(person)
 if person and person.casefold() not in [n.casefold().strip() for n in a['people']]:
  # Any subject category that is not a person can carry a disclosed wide/context picture;
  # the rule is that it is disclosed in notes, not that it belongs to a fixed list.
  if not(s['context_only'] and s['notes'].strip() and a['category']!='person' and not a['people']):errors.append(pre+'the named person is not verified in this asset. Select the correct person, or explicitly disclose genuine wide context with no substituted identity.')
  else:notes.append(pre+'disclosed context, not a verified portrait: '+s['notes'])
 lastscene=i==len(p['scenes'])-1
 blended=transitions.is_transition(s.get('transition'))
 if blended and lastscene:errors.append(pre+'the last scene cannot blend into a nonexistent next scene.')
 # Adjacent blends are allowed and render correctly: the chain applies each boundary to
 # the running result, so a scene can open on one transition and close on another. The
 # only real limit is room -- a blend may not be longer than the scene it leads into,
 # checked below -- because the handle has to come from somewhere.
 if blended and not lastscene and not p.get('documentary_beat_review') and s.get('transition_handle_frames',4)>p['scenes'][i+1]['frame_out']-p['scenes'][i+1]['frame_in']:errors.append(pre+'the transition is longer than the incoming picture beat.')
 still=is_still(p,a)
 if still and policy(p)!='mixed':errors.append(pre+'this production is set to moving footage only. Switch the picture policy to allow photographs, or use a clip.')
 if still and not p.get('documentary_beat_review') and not (a.get('approval_record') or {}).get('active',True):errors.append(pre+'the photograph’s use approval was revoked; re-approve it before exporting.')
 if a.get('derived_from'):errors.append(pre+'extracted frames are not permitted; use original uploaded media.')
 if not (folder(p['id'])/a['path']).is_file():errors.append(pre+'source file is missing from disk.')
 if a['kind']=='video':
  # A Beat timeline's transitions are measured against whole shots by its renderer,
  # which also holds the last frame if a source ends inside a blend.
  end_s=s['in_s']+(s['frame_out']-s['frame_in']+(s.get('transition_handle_frames',4) if transitions.is_transition(s.get('transition')) and not p.get('documentary_beat_review') else 0))/30
  if s['in_s']<0 or end_s>a['duration']+.001:errors.append(pre+'video is too short, including transition handles. No loop or frozen tail will be generated.')
  compare_in,compare_out=source_overlap_interval(s,a,p)
  approved_pairs,approved_beats=beat_approvals(p)
  own_beat=scene_beat(s)
  for start,stop,number,other_beat in ranges.get(a['id'],[]):
   if compare_in<stop and compare_out>start:
    if p.get('edit_mode')=='documentary' or p.get('documentary_beat_review'):
     # Replaying an authentic clip is a creative choice, never a blocking error.
     notes.append(pre+f'reuses source footage from scene {number} (allowed).')
    elif ((s.get('plan_row') or {}).get('strict_production') or not p.get('allow_archive_reuse')) and (s.get('plan_row') or {}).get('requested_treatment')!='ARCHIVAL REUSE':
     pair=tuple(sorted((own_beat,other_beat))) if own_beat and other_beat else None
     if pair and pair in approved_pairs:notes.append(pre+f'source interval reuses footage from scene {number}; this repeat was approved in the Beat plan.')
     else:errors.append(pre+f'source interval overlaps scene {number}.')
 if p.get('transition_policy')=='clean_cuts_only' and s['transition']!='cut':errors.append(pre+'only clean cuts are enabled for this production.')
 if not s['focus'].strip():errors.append(pre+'set the story focus.')
 # A Beat documentary renders without per-shot approval or rights paperwork: the
 # production script chose the footage, and the person rendering owns that choice.
 if final and not s['approved'] and not p.get('documentary_beat_review'):errors.append(pre+'editorial approval is pending.')
 if final and not p.get('documentary_beat_review') and ((a.get('reuse_review') or {}).get('decision')!='approved' or not (a.get('reuse_review') or {}).get('details','').strip()):errors.append(pre+'record an explicit reuse-rights approval and supporting details for this source before final export.')
 return errors,notes

import contextlib
def _reading(pid):
 """Read-only requests do not queue behind the project lock.

 A long job holding it (a build, an import, a check) used to leave the timeline on
 "Loading..." until the job ended. Project saves are atomic file swaps, so a read
 always sees one complete saved version."""
 return contextlib.nullcontext()

_RESULT_CACHE={};_RESULT_LOCK=threading.Lock()
def _remembered(kind,p,extra,compute,ttl=15.0):
 """Reuse a slow, read-only result while the production is byte-for-byte unchanged.

 Opening a documentary ran the full export check twice and the script diagnosis three
 times -- each re-opening every source video -- and the page asks again every few
 seconds. On a 442-shot film that kept the production locked almost continuously, so
 the timeline never loaded and the editor lagged. The key is a fingerprint of the
 project's contents, so any change at all is checked afresh; the short expiry picks up
 changes on disk (a file finishing its download) that the project record does not show.
 """
 try:key=(kind,extra,hashlib.sha1(json.dumps(p,sort_keys=True,default=str).encode()).hexdigest())
 except (TypeError,ValueError):return compute()
 now=time.monotonic()
 with _RESULT_LOCK:
  hit=_RESULT_CACHE.get(key)
  if hit and now-hit[0]<ttl:return copy.deepcopy(hit[1])
 value=compute()
 with _RESULT_LOCK:
  if len(_RESULT_CACHE)>24:
   for old in sorted(_RESULT_CACHE,key=lambda k:_RESULT_CACHE[k][0])[:12]:_RESULT_CACHE.pop(old,None)
  _RESULT_CACHE[key]=(now,copy.deepcopy(value))
 return value

def check(p,final=False):
 return _remembered('check',p,bool(final),lambda:_check_uncached(p,final))

def _check_uncached(p,final=False):
 errors=[];notes=[];assets={x['id']:x for x in p['assets']};ranges=defaultdict(list);last=0
 if p.get('review_only_draft'):
  rows=[s.get('plan_row') or {} for s in p['scenes']]
  supported=bool(rows) and all(r.get('plain_cue') for r in rows) and p.get('script_moving_only') and script_reading(p).get('ready_to_build') is True
  if final or not supported:errors.append('This is a script review draft, not a finished edit. Final export is blocked; complete the script and source checks before rendering.')
  else:
   notes.append('Review render only: script captions and SRT subtitles are burned in only if selected. Verify visual content, identity, still eligibility and reuse rights; final export remains blocked.')
   if p.get('voiceover'):
    from documentary import narration_clock_s
    audio_duration=narration_clock_s(p) if p.get('documentary_beat_review') else p['voiceover'].get('duration',0);timeline_duration=p['scenes'][-1]['frame_out']/30
    if audio_duration>timeline_duration+.001:errors.append('Narration is longer than the picture timeline. Use matching audio; the review render must not trim narration.')
    elif audio_duration<timeline_duration-.001:notes.append(f'Narration is {timeline_duration-audio_duration:.3f} seconds shorter than the timeline; the review render pads the end with silence without stretching it.')
 from automatic import repetition_errors,source_capacity_errors,_plan_coverage
 errors.extend(_unapproved_repeats(p,repetition_errors(p)));errors.extend(source_capacity_errors(p))
 # A block map written for a different runtime leaves blocks unplaced. Say so as a plan
 # problem with the numbers, rather than letting the picture come up short at the end.
 uncovered=_plan_coverage(p)
 if uncovered and p['scenes']:
  errors.append(str(len(uncovered))+' SRT block(s) are not placed by the block map (first is block '+str(uncovered[0])+'). Extend the map over the whole narration, or download a fresh template for this SRT.')
 if not p['brief'].strip() and not p.get('srt'):errors.append('Import your SRT story, or add a case brief.')
 if p.get('srt_removed') and p['scenes'] and not p.get('srt'):errors.append('The SRT was removed. Import an SRT and rebuild before exporting.')
 from production import document
 from edl import signature
 if p['scenes'] and (p.get('picture_plan') or p.get('assembly_signature')) and p.get('assembly_signature')!=signature(p):errors.append('Editing inputs changed. Rebuild the storyboard to apply the current SRT block map / production script.')
 # A Beat storyboard records the script it was built to inside its own review record,
 # and that record travels with the scenes. The generic hash below covers the whole
 # document (brief, SRT, assets, scenes) and is recalculated every time anything is
 # saved, so for a Beat storyboard it disagrees with itself as soon as a bite is
 # moved or a scene is approved. It was blocking export with "Production script
 # changed" on a timeline nobody had edited. For this storyboard type the Beat
 # record is authoritative; a genuinely stale script is reported as a warning by the
 # frame audit, which names the beats that moved.
 if p.get('production_script') and p['scenes'] and not p.get('documentary_beat_review') and p.get('edit_script_hash')!=hashlib.sha256(document(p).encode()).hexdigest():errors.append('Production script changed. Rebuild the storyboard to apply the new instructions.')
 # Narration is optional. A programme may be carried by its text alone; what is not
 # allowed is a narration track whose length disagrees with the picture it sits under.
 if not p['scenes']:
  if (p.get('production_script') or {}).get('text','').strip():
   # v19: name the real step and why it has not happened, instead of a generic SRT message.
   why=str((p.get('auto_build') or {}).get('reason') or '').strip()
   errors.append('The Beat timeline has not been built yet. Open Documentary tools > Beat picture plan to build it.'
                 +(f' It is waiting on: {why}' if why else ''))
  else:errors.append('Build the storyboard from the imported SRT.' if p.get('srt') else 'Import an SRT and build the storyboard.')
 # A Beat storyboard is on the programme clock: its picture is the narration plus every
 # sound bite, so the bites are taken off before comparing with the narration's length.
 if p.get('voiceover') and p['scenes']:
  covered=p['scenes'][-1]['frame_out']/30
  if p.get('documentary_beat_review'):
   covered-=sum((s['frame_out']-s['frame_in'])/30 for s in p['scenes'] if (s.get('plan_row') or {}).get('bite_id') or (s.get('plan_row') or {}).get('continuity')=='Documentary beat sound-bite')
  # The narration clock is the voiceover file, or the SRT end when the last subtitle
  # is held a moment past the audio (documentary.narration_clock_s). Silence after
  # the last word is covered by picture, so the film still meets the file's end.
  from documentary import narration_clock_s
  clock=narration_clock_s(p)
  if abs(clock-covered)>.25:errors.append(f"Narration duration ({clock:.2f}s) must match the narration the picture covers ({covered:.2f}s) within 0.25 seconds. Correct the timing; do not silently trim the voiceover.")
 for i,s in enumerate(p['scenes']):
  a=assets.get(s['asset_id'])
  scene_errors,scene_notes=scene_review(p,i,s,a,ranges,last,final)
  row=s.get('plan_row') or {}
  if s.get('source_replacement_pending') and not p.get('documentary_beat_review'):scene_errors.append(f'Scene {i+1}: review and approve the replaced source {s["source_replacement_pending"]} before export.')
  if row.get('strict_production'):
   if not s.get('approved'):scene_errors.append(f'Scene {i+1}: inspect the picture, identity, context and official source provenance before approval.')
   if s['frame_in']!=round(row['timeline_in_ms']*.03) or s['frame_out']!=round(row['timeline_out_ms']*.03) or s.get('transition')!='cut' or (a and abs(s.get('in_s',0)-row['source_in_ms']/1000)>.001):
    scene_errors.append(f'Scene {i+1}: edited timing or transition differs from the production script.')
   if a:
    from production import asset_matches
    if not asset_matches(a,row['source_file']):scene_errors.append(f'Scene {i+1}: selected source differs from the production script.')
   # The source image remains unchanged, but V11.7 presents it with restrained
   # timeline camera movement instead of requiring a frozen frame.
   if row.get('requested_treatment')=='CONTEXT VIDEO' and not s.get('context_only'):scene_errors.append(f'Scene {i+1}: context footage must remain labelled as context.')
  errors.extend(scene_errors);notes.extend(scene_notes)
  last=s['frame_out']
  if a and a['kind']=='video':
   compare_in,compare_out=source_overlap_interval(s,a,p)
   ranges[a['id']].append((compare_in,compare_out,i+1,scene_beat(s)))
 if any((s.get('plan_row') or {}).get('strict_production') for s in p['scenes']) and p['scenes']:
  still_frames=sum(s['frame_out']-s['frame_in'] for s in p['scenes'] if (assets.get(s.get('asset_id')) and (is_still(p,assets[s['asset_id']]) or (s.get('plan_row') or {}).get('native_static_interval'))))
  total=p['scenes'][-1]['frame_out']
  if total and still_frames/total>.1+1e-9:errors.append(f'Scheduled stills occupy {still_frames/total*100:.2f}% of the timeline, above the 10% limit. Review eligibility and replace only with appropriate footage.')
 flow=p.get('picture_flow') or {}
 from picture_flow import outstanding_notes
 notes.extend(outstanding_notes(flow))
 if not final and any(not s['approved'] for s in p['scenes']):notes.append('Review export only. Scene approval and rights review are required for final delivery.')
 return {'errors':errors,'notes':notes,'can_export':not errors,'final':final}

def is_plain_summary(text):
 return bool(re.search(r'^##\s+Storyboard Production Script\s*$',text,re.M|re.I))

def script_reading(p, include_shots=False):
 return _remembered('script_reading',p,bool(include_shots),lambda:_script_reading_uncached(p,include_shots))

def _script_reading_uncached(p, include_shots=False):
 from document_plan import rows_for
 from production import asset_matches
 try:rows,mode=rows_for(p)
 except ValueError as e:return {'status':'error','detail':str(e)}
 if mode!='detailed_production_script':
  if p.get('edit_mode')=='documentary':
   from documentary_script_diagnostics import diagnose
   return diagnose(p,folder(p['id']))
  return {'status':'not_detailed'}
 missing=[];short=[];overlaps=[];used={}
 for row in rows:
  matches=[a for a in p['assets'] if asset_matches(a,row['source_file'])]
  if len(matches)!=1 or not (folder(p['id'])/matches[0]['path']).is_file():missing.append(row['source_file']);continue
  asset=matches[0]
  if asset.get('kind')=='video' and (row['source_in_ms']/1000>=float(asset.get('duration') or 0) or ((row['visual_status']=='VIDEO' or row.get('native_static_interval')) and row['source_out_ms']/1000>float(asset.get('duration') or 0)+.001)):short.append(row['shot_id'])
  if asset.get('kind')=='video' and row.get('source_in_ms') is not None and row.get('source_out_ms') is not None:
   for start,end,shot in used.get(asset['id'],[]):
    if row['source_in_ms']<end and row['source_out_ms']>start:
     overlaps.append({'shot':row['shot_id'],'earlier_shot':shot});break
   used.setdefault(asset['id'],[]).append((row['source_in_ms'],row['source_out_ms'],row['shot_id']))
 mismatches=sorted({b for row in rows if row.get('narration_mismatch') for b in row['srt_blocks']})
 build_issues=[]
 if missing:build_issues.append('Missing or ambiguous source files: '+', '.join(sorted(set(missing)))+'.')
 if short:build_issues.append('Source intervals exceed uploaded file duration: '+', '.join(short)+'.')
 # Reused source windows are reported as informational overlap_shots only.
 # They must never block a documentary script's storyboard construction.
 if mismatches:build_issues.append('Script narration differs from the SRT in '+str(len(mismatches))+' cue(s).')
 if not p.get('voiceover'):build_issues.append('Upload the narration audio.')
 elif not p['voiceover'].get('path') or not (folder(p['id'])/p['voiceover']['path']).is_file():build_issues.append('The narration audio file is missing from disk.')
 elif abs(float(p['voiceover'].get('duration') or 0)-rows[-1]['timeline_out_ms']/1000)>.25:build_issues.append('Narration duration does not match the SRT timeline.')
 unsupported=[r['shot_id'] for r in rows if r.get('requested_treatment') in ('STILL HOLD','EDITORIAL FREEZE-FRAME') and not r.get('native_static_interval') and not r.get('uploaded_photo')]
 if unsupported:build_issues.append('Unsupported still or freeze instructions: '+', '.join(unsupported)+'. No frames will be extracted.')
 if policy(p)!='mixed' and any(r.get('uploaded_photo') for r in rows):build_issues.append('Enable moving footage and photographs for this project.')
 still_ms=sum(r['timeline_out_ms']-r['timeline_in_ms'] for r in rows if r.get('native_static_interval') or r.get('uploaded_photo'))
 if rows[-1]['timeline_out_ms'] and still_ms/rows[-1]['timeline_out_ms']>.1+1e-9:build_issues.append('Script-declared stills exceed the 10% limit.')

 result={'status':'read','shots':len(rows),'blocks':len({n for row in rows for n in row['srt_blocks']}),'duration_ms':rows[-1]['timeline_out_ms'],
         'source_count':len({r['source_file'] for r in rows}),'missing_files':sorted(set(missing)), 'short_shots':short,'overlap_shots':overlaps,'build_issues':build_issues,'ready_to_build':not build_issues,
         'native_static_ms':sum(r['timeline_out_ms']-r['timeline_in_ms'] for r in rows if r.get('native_static_interval')), 'photo_ms':sum(r['timeline_out_ms']-r['timeline_in_ms'] for r in rows if r.get('uploaded_photo')), 'photo_shots':sum(bool(r.get('uploaded_photo')) for r in rows), 'still_shots':sum(r.get('requested_treatment')=='STILL HOLD' for r in rows),'freeze_shots':sum(r.get('requested_treatment')=='EDITORIAL FREEZE-FRAME' for r in rows),
         'video_shots':sum(r.get('requested_treatment') in ('VIDEO','CONTEXT VIDEO','ARCHIVAL REUSE') for r in rows),
         'caption_shots':sum(bool(r.get('required_caption')) for r in rows),'narration_mismatch_blocks':mismatches,
         'blocker_count':sum(bool(r.get('import_blockers')) for r in rows)}
 if include_shots:
  result['shots_detail']=rows
  text=(p.get('production_script') or {}).get('text','')
  for key,title in (('project_instructions','Editor Assembly Instructions' if is_plain_summary(text) else 'Project instructions'),('final_checks','Final Coverage Summary' if is_plain_summary(text) else 'Final production checks')):
   section=re.search(r'^##\s+'+re.escape(title)+r'\s*$\n(.*?)(?=^##\s|\Z)',text,re.M|re.S|re.I)
   result[key]=section[1].strip() if section else ''
 return result

def public(p):
 d=copy.deepcopy(p)
 from caption_layout import caption_phrases
 d['caption_phrases']=caption_phrases((p.get('srt') or {}).get('blocks',[]))
 if isinstance(d.get('documentary_cutaways_pending'),dict):d['documentary_cutaways_pending'].pop('ledger',None)
 from document_plan import match_report
 d['source_match_report']=match_report(d)
 from footage_requirements import footage_requirements,photo_requirements
 d['footage_requirements']=footage_requirements(p);d['photo_requirements']=photo_requirements(p)
 if p.get('production_script'):
  from cue_script import is_cue_script
  from plain_script import is_plain_script
  if p.get('edit_mode')=='documentary' or is_plain_script(p['production_script'].get('text','')) or is_cue_script(p['production_script'].get('text','')) or re.search(r'^###\s+Srt\d+-[A-Za-z]+\s*$',p['production_script'].get('text',''),re.M|re.I):d['script_reading']=script_reading(p)
 if p.get('edit_mode')=='documentary':
  try:d['person_overlays']=person_overlay_report(p)
  except Exception as e:d['person_overlays']={'windows':[],'people':[],'notes':['Name cards could not be planned: '+str(e)[:300]]}
 if p.get('edit_mode')=='documentary':
  import watermark as _wm
  _wm_file=_wm.path_for(p,folder(p['id']))
  d['watermark_report']={'settings':_wm.settings(p),'present':bool(_wm_file),'positions':list(_wm.POSITIONS),
   'url':f'/api/projects/{p["id"]}/watermark/image?v={p.get("updated",0)}' if _wm_file else None,
   'name':(p.get('watermark_asset') or {}).get('original_name',''),'has_alpha':(p.get('watermark_asset') or {}).get('has_alpha',True)}
 if p.get('edit_mode')=='documentary':
  from channel_cta import settings as cta_settings, plan as cta_plan, path_for as cta_path, detect as cta_detect
  try:
   cta_file=cta_path(p,folder(p['id']))
   _cta_sound=__import__('documentary').load_plan(folder(p['id']))
   _cta_found=cta_detect(p,folder(p['id']),_cta_sound)
   d['channel_cta_report']={'settings':cta_settings(p),'present':bool(cta_file),
    'detected':_cta_found,
    'windows':cta_plan(p,folder(p['id']),_cta_sound),
    'url':f'/api/projects/{p["id"]}/channel-cta/image?v={p.get("updated",0)}' if cta_file else None,
    'name':(p.get('channel_cta_asset') or {}).get('original_name','')}
  except Exception as err:
   d['channel_cta_report']={'settings':cta_settings(p),'present':False,'windows':[],'error':str(err)}
 d['validation']=check(p);d['final_validation']=check(p,True)
 # What each resolution would actually mean for this project's sources. Computed from
 # the recorded dimensions, so the export page never has to estimate a factor.
 d['export_plan']=export_plan(p)
 saved=folder(p['id'])/'render_status.json'
 d['render']=JOBS[p['id']].snapshot() if p['id'] in JOBS else json.loads(saved.read_text()) if saved.exists() else {'status':'idle','progress':0,'stage':'No export yet'}
 if p['id'] not in JOBS and d['render']['status'] in ['running','queued']:d['render'].update(status='interrupted',stage='Previous export interrupted; start a new export',progress=0)
 if d['render'].get('output'):
  d['render']['url']=f'/api/projects/{p["id"]}/exports/{d["render"]["output"]}'
  record=folder(p['id'])/'reviews'/(Path(d['render']['output']).stem+'.json')
  saved_record=json.loads(record.read_text()) if record.exists() else {}
  d['render']['current']=bool(saved_record) and saved_record.get('project',{}).get('updated')==p['updated']
  if saved_record:
   d['render']['options']={'script_captions':saved_record.get('script_captions_requested',saved_record.get('captions_burned_in',False)), 'srt_subtitles':saved_record.get('srt_subtitles_burned_in',False), 'enhance_picture':saved_record.get('picture_enhancement',False)}
   if p.get('edit_mode')=='documentary' and saved_record.get('plan_revision') is not None:
    from documentary import load_plan,annotate_plan
    try:d['render']['current']=d['render']['current'] and load_plan(folder(p['id']))['revision']==saved_record['plan_revision'] and not any(b.get('stale_reasons') for b in annotate_plan(p,folder(p['id']),load_plan(folder(p['id'])))['bites'])
    except (OSError,ValueError,KeyError):d['render']['current']=False
    if saved_record.get('input_signatures'):
     try:
      for item in saved_record['input_signatures']:
       if item[0]=='frame_decisions_present':
        if (folder(p['id'])/'reviews'/'documentary_frame_decisions.json').exists()!=item[1]:d['render']['current']=False
       else:
        path=(folder(p['id'])/item[0]).resolve()
        if not path.is_relative_to(folder(p['id']).resolve()):raise ValueError('Invalid render input path.')
        stat=path.stat()
        if (stat.st_size,stat.st_mtime_ns)!=(item[2],item[3]):d['render']['current']=False
     except (OSError,ValueError,TypeError,IndexError):d['render']['current']=False
    name=saved_record.get('adjusted_srt')
    if name and re.fullmatch(r'documentary_final_[a-f0-9]{32}\.adjusted\.srt',name) and (folder(p['id'])/'renders'/name).is_file():d['render']['adjusted_srt_url']=f'/api/projects/{p["id"]}/exports/{name}'
 for i,scene in enumerate(d['scenes']):scene['motion_plan']=motion(scene,i)
 from production import reserve_id
 for a in d['assets']:
  a['url']=f'/api/projects/{p["id"]}/assets/{a["id"]}/file'+(f'?v={a["revision"]}' if a.get('revision') else '');a['reserve']=bool(reserve_id(a));a['source_label']=reserve_id(a) or Path(a.get('original_name',a['name'])).stem
  if a.get('kind')=='image':a['clean_url']=f'/api/projects/{p["id"]}/assets/{a["id"]}/clean-frame?v={a.get("revision",0)}-{__import__("clean_photo_framing").crop_token(a.get("crop"))}'
 # Photo-carrier videos and explicitly verified static intervals are photographs
 # in a video container.  The monitor receives the same clean framed still the
 # exporter uses; ordinary moving footage keeps its native video playback.
 from truecrime_camera import still_visual_kind
 public_assets={a.get('id'):a for a in d['assets']}
 for scene in d['scenes']:
  asset=public_assets.get(scene.get('asset_id')) or {}
  still_kind=still_visual_kind(asset,[scene])
  if still_kind and asset.get('kind')=='video':
   scene['photo_frame_kind']=still_kind
   scene['photo_frame_url']=(f'/api/projects/{p["id"]}/scenes/{scene["id"]}/photo-frame'
                             f'?v={asset.get("revision",asset.get("id"))}-{round(float(scene.get("in_s") or 0)*1000)}')
 if d['voiceover']:
  voice_path=folder(p['id'])/d['voiceover']['path']
  revision=str(voice_path.stat().st_mtime_ns) if voice_path.is_file() else 'missing'
  d['voiceover']['url']=f'/api/projects/{p["id"]}/narration?v={revision}'
 from automatic import automatic_readiness
 d['automatic_readiness']=automatic_readiness(p)
 status_path=folder(p['id'])/'automatic_status.json'
 try:d['automatic_status']=json.loads(status_path.read_text()) if status_path.exists() else {'status':'idle','detail':''}
 except (OSError,ValueError):d['automatic_status']={'status':'idle','detail':''}
 # Persisted progress is not proof of a live thread after a server restart or crash.
 from automatic import _QUEUE_LOCK, _PENDING
 with _QUEUE_LOCK:auto_active=p['id'] in _PENDING
 if d['automatic_status'].get('status') in ('queued','working','studying','storyboard_ready','rendering') and not auto_active and not busy(p['id']):
  d['automatic_status']={'status':'interrupted','detail':'The previous automatic job stopped. Check the storyboard and export validation before retrying.'}
 from preview_render import status as preview_status
 d['preview']=preview_status(folder(p['id']),p['id'],p['updated'])
 if d['preview'].get('status')=='done':d['preview']['url']=f'/api/projects/{p["id"]}/continuous-preview?version={p["updated"]}'
 from scene_exports import status as scene_export_status
 d['scene_exports']=scene_export_status(folder(p['id']),p['id'],p['updated'])
 if d['scene_exports'].get('status')=='done':d['scene_exports']['url']=f'/api/projects/{p["id"]}/scene-exports/{d["scene_exports"]["output"]}'
 d['inputs_ready']=bool(p.get('srt') and p.get('production_script') and p.get('assets'))
 d['picture_flow']=p.get('picture_flow') or None
 d['flow_review']=[{'scene':b.get('scene'),'asset':b.get('asset'),'status':b.get('status'),'note':b.get('note'),'declared_in_s':b.get('declared_in_s'),'conformed_in_s':b.get('conformed_in_s'),'shot':b.get('shot'),'suggestions':b.get('suggestions') or []} for b in ((p.get('picture_flow') or {}).get('picture') or {}).get('beats',[]) if b.get('review')]
 d['flow_summary']=(p.get('picture_flow') or {}).get('summary') or {}
 d['rebuild_report']=p.get('rebuild_report')
 # What the next export will actually be, resolved once here so the studio never has to
 # guess and no two parts of the app can disagree about the size.
 width,height=output_size(p.get('format','landscape'),p.get('size'))
 d['output']={'format':p.get('format','landscape'),'size':p.get('size'),'width':width,'height':height,
              'label':str(width)+'×'+str(height),'aspect':ASPECTS.get(p.get('format','landscape'))}
 d['picture_tools']={'upscaler':p.get('upscaler','auto'),'framing':p.get('framing','auto'),'quality':p.get('quality','standard'),
                     'quality_presets':QUALITY_PRESETS,'framing_modes':FRAMING_MODES,'upscalers':PICTURE_UPSCALERS}
 return d

@app.get('/')
def home():
 options=''.join('<option value="'+name+'"'+( ' selected' if name=='documentary' else '')+'>'+str(meta.get('name') or name)+'</option>' for name,meta in PROFILES.items())
 return render_template('index.html',asset_revision=max(p.stat().st_mtime_ns for p in (BASE/'static').glob('*') if p.is_file()),profile_options=options,
                        ai_upscale=upscale.describe())

@app.get('/api/transitions')
def transition_library():
 # The library dialog is built from this, so a transition cannot be offered in the UI
 # that the renderer has no filter for.
 return jsonify(transitions.catalogue())


@app.get('/api/projects/<pid>/cinematic-graphics')
def cinematic_graphics_settings(pid):
 """Editable visual-review settings. This endpoint never places timeline media."""
 import cinematic_graphics
 p=snapshot(pid)
 return jsonify({'settings':cinematic_graphics.settings(p),
                 'catalogue':cinematic_graphics.catalogue(),
                 'review_only':True})


@app.patch('/api/projects/<pid>/cinematic-graphics')
@project_io_lock
def save_cinematic_graphics_settings(pid):
 """Save one project's design preset without changing narration, scenes or timings."""
 import cinematic_graphics
 editable(pid);p=load(pid)
 try:settings=cinematic_graphics.normalise(request.get_json(silent=True) or {})
 except ValueError as error:raise BadRequest(str(error)) from error
 p['cinematic_graphics']=settings
 save(p)
 return jsonify({'settings':settings,'project':public(p),'review_only':True})


# --- Motion Graphics (Intelligent Cinematic Motion Graphics Engine) ------------

@app.get('/api/projects/<pid>/motion-graphics')
def motion_graphics_get(pid):
 """Read-only motion graphics state: settings, catalogue, cached analysis."""
 import motion_graphics as mg
 p=snapshot(pid);settings=mg.settings(p)
 analysis=None
 cache_path=folder(pid)/'reviews'/'motion_graphics_analysis.json'
 if cache_path.is_file():
  try:analysis=json.loads(cache_path.read_text(encoding='utf-8'))
  except (OSError,ValueError):analysis=None
 return jsonify({'version':mg.VERSION,'settings':settings,'catalogue':mg.catalogue(p),
                 'analysis':analysis,'signature':mg.signature(p)})


@app.patch('/api/projects/<pid>/motion-graphics')
@project_io_lock
def motion_graphics_patch(pid):
 """Save motion graphics settings (enable, mode, design, sequences)."""
 import motion_graphics as mg
 editable(pid);p=load(pid)
 patch=request.get_json(silent=True) or {}
 try:values=mg.validate_patch(patch)
 except ValueError as error:raise BadRequest(str(error)) from error
 current=p.get('motion_graphics') or {}
 current.update(values);p['motion_graphics']=mg.settings(p)
 save(p)
 return jsonify({'settings':p['motion_graphics'],'project':public(p),
                 'signature':mg.signature(p)})


@app.post('/api/projects/<pid>/motion-graphics/analyse')
@project_io_lock
def motion_graphics_analyse(pid):
 """Analyse the production script and SRT; return ranked placement suggestions.

 This is the engine's context-aware placement pass. It never modifies narration,
 footage or SRT; it reads them and proposes.
 """
 import motion_graphics as mg
 editable(pid);p=load(pid)
 script_text=(p.get('production_script') or {}).get('text','')
 srt_blocks=(p.get('srt') or {}).get('blocks') or []
 timeline=mg.analyse_script(script_text,srt_blocks)
 # Estimate total film duration from scenes.
 film_duration_s=sum((s.get('frame_out',0)-s.get('frame_in',0))/30 for s in p.get('scenes') or [])/1
 suggestions=mg.suggest_sequences(timeline,srt_blocks,film_duration_s)
 # Persist the analysis for the editor UI to display the rationale.
 analysis={'signature':mg.signature(p),'generated':time.time(),
           'summary':{'beats_total':timeline['beats_total'],
                      'narration_beats':timeline['narration_beats'],
                      'candidates':len(timeline['candidates']),
                      'excluded':len(timeline['excluded']),
                      'acts':[a['act'] for a in timeline['acts']]},
           'candidates':timeline['candidates'][:10],
           'excluded':timeline['excluded'][:10],
           'suggestions':suggestions}
 cache_dir=folder(pid)/'reviews';cache_dir.mkdir(parents=True,exist_ok=True)
 (cache_dir/'motion_graphics_analysis.json').write_text(json.dumps(analysis,ensure_ascii=False),encoding='utf-8')
 # Store suggestions so the user can accept them without re-analysing.
 current=p.get('motion_graphics') or {}
 current['suggestions']=suggestions;p['motion_graphics']=mg.settings(p);save(p)
 return jsonify({'analysis':analysis,'suggestions':suggestions,'signature':mg.signature(p)})


@app.post('/api/projects/<pid>/motion-graphics/preview')
def motion_graphics_preview(pid):
 """Render a lightweight preview MP4 of one sequence for the editor UI.

 Runs in a background thread so the editor never blocks. Returns a status
 object the UI can poll.
 """
 import motion_graphics as mg
 import motion_render as mr
 p=snapshot(pid);data=request.get_json(silent=True) or {}
 seq_id=data.get('id') or ''
 seqs=(p.get('motion_graphics') or {}).get('suggestions') or []
 seqs=seqs+((p.get('motion_graphics') or {}).get('sequences') or [])
 seq=next((s for s in seqs if s.get('id')==seq_id),None)
 if not seq:raise NotFound('Sequence not found.')
 settings=mg.settings(p)
 design=seq.get('design') or settings.get('design') or mg.DEFAULTS['design']
 # Lightweight preview: 640-wide, 15 fps.
 from fractions import Fraction
 width=640;height=max(2,int(width*9/16)//2*2)
 fps=Fraction(15,1)
 out_dir=folder(pid)/'.cache'/'motion-graphics-previews';out_dir.mkdir(parents=True,exist_ok=True)
 out_path=out_dir/f'{seq_id}.mp4'
 sig_path=out_dir/f'{seq_id}.sig'
 import motion_templates as mt
 sequence=mt.build_sequence(seq['template'],seq['content'],float(seq['end_s'])-float(seq['start_s']))
 current_sig=mr.sequence_signature(sequence,design,fps,width,height)
 if out_path.is_file() and sig_path.is_file() and sig_path.read_text(encoding='utf-8')==current_sig:
  return jsonify({'url':f'/api/projects/{pid}/motion-graphics/preview/{seq_id}/stream','ready':True})
 def _render():
  try:
   mr.preview_video(sequence,design,fps,width,height,out_path)
   sig_path.write_text(current_sig,encoding='utf-8')
  except Exception as exc:
   sig_path.write_text('error:'+str(exc)[:200],encoding='utf-8')
 threading.Thread(target=_render,daemon=True,name='mg-preview-'+seq_id).start()
 return jsonify({'ready':False,'url':f'/api/projects/{pid}/motion-graphics/preview/{seq_id}/stream'})


@app.get('/api/projects/<pid>/motion-graphics/preview/<seq_id>/stream')
def motion_graphics_preview_stream(pid,seq_id):
 root=folder(pid);path=root/'.cache'/'motion-graphics-previews'/f'{seq_id}.mp4'
 if not path.is_file() or not path.is_relative_to(root.resolve()):raise NotFound('Preview not ready yet.')
 return send_file(path,mimetype='video/mp4',conditional=True)


@app.post('/api/projects/<pid>/transition-suggest')
def suggest_transitions(pid):
 """Assign a transition to every boundary, each from that scene's own content.

 Rewrites only `transition` and its handle. Nothing about timing, source, approval or
 narration is touched, so this is safe to run on an approved timeline -- and it says
 up front what it changed, because an automatic rewrite of editorial choices should
 never be silent.
 """
 with LOCKS[pid]:
  editable(pid);p=load(pid)
  if not p.get('scenes'):raise BadRequest('Build a storyboard before suggesting transitions.')
  data=request.get_json(silent=True) or {}
  intensity=data.get('intensity') or transitions.DEFAULT_INTENSITY
  if intensity not in transitions.INTENSITY:raise BadRequest('Choose an intensity: '+', '.join(transitions.INTENSITY))
  frames=transitions.DURATION.get(data.get('duration') or transitions.DEFAULT_DURATION,(None,15))[1]
  if p.get('transition_policy')=='clean_cuts_only' and frames:
   # Pressing Auto Suggest is an explicit request for blends, not an imported
   # instruction silently overriding a clean-cuts policy.
   p['transition_policy']='allow_dissolves' 
  keys=transitions.suggest_all(p['scenes'],intensity)
  changed=0
  for scene,key in zip(p['scenes'],keys):
   if scene.get('transition')!=key:
    changed+=1
   scene['transition']=key
   scene['transition_handle_frames']=frames if transitions.is_transition(key) else 0
  p['manual_scene_edits']=True
  save(p)
  return jsonify({'project':public(p),'changed':changed,
                  'summary':{k:keys.count(k) for k in set(keys) if k!='cut'}})


def _asset_kinds(p):return {a.get('id'):a.get('kind') for a in p.get('assets') or []}
def _doc_cut_list(p):
 scenes=p.get('scenes') or [];cuts=transitions.documentary_cuts(scenes);lengths=transitions.shot_frames(scenes,cuts)
 out=[]
 for n,c in enumerate(cuts):
  a,b=scenes[c],scenes[c+1]
  out.append({'number':n+1,'scene_index':c,'scene_id':a['id'],'next_scene_id':b['id'],
              'at_s':round(b['frame_in']/30,3),'transition':a.get('transition') or 'cut',
              'frames':int(a.get('transition_handle_frames') or 0),'source':a.get('transition_source') or '',
              'locked':bool(a.get('transition_locked')),
              'into_speaker':transitions.scene_kind(b)=='sound_bite',
              'from':(a.get('plan_row') or {}).get('source_file') or '','to':(b.get('plan_row') or {}).get('source_file') or '',
              'shot_frames':lengths[c]})
 return out

# ---- Per-slot camera (animated zoom/pan), locks and undo -------------------------
_CINEMATIC_FIELDS=('camera','transition','transition_handle_frames','transition_source','transition_locked')
CINEMATIC_UNDO_DEPTH=30

def _cinematic_snapshot(p,scene_ids,label):
 """Remember the camera and transition settings of these slots so the change can be undone."""
 ids=set(scene_ids)
 if not ids:return
 saved={s['id']:{k:copy.deepcopy(s[k]) for k in _CINEMATIC_FIELDS if k in s} for s in p.get('scenes') or [] if s['id'] in ids}
 stack=p.setdefault('cinematic_undo',[])
 stack.append({'label':label,'at':time.time(),'scenes':saved})
 del stack[:-CINEMATIC_UNDO_DEPTH]



@app.get('/api/projects/<pid>/documentary-transitions')
def documentary_transitions(pid):
 p=load(pid)
 # Preview-only recommendations are deterministic and never mutate the project.
 style=request.args.get('style','cinematic')
 if style not in transitions.AUTO_STYLES:style='balanced'
 cuts=_doc_cut_list(p);suggestions=transitions.documentary_auto_details(p.get('scenes') or [],style,seed=0,assets=_asset_kinds(p))
 for cut in cuts:
  suggestion=suggestions.get(cut['scene_index'],{'key':'cut','frames':0,'reason':'No picture cut'})
  cut['suggested']=suggestion['key'];cut['suggested_frames']=suggestion['frames']
  cut['suggested_reason']=suggestion['reason'];cut['suggested_moment']=suggestion.get('moment')
 return jsonify({'cuts':cuts,'styles':[{'key':k,'label':transitions.AUTO_STYLES[k][0]} for k in ('cinematic','dynamic','truecrime','restrained')],
                 'catalogue':transitions.documentary_catalogue(),'suggestion_style':style})

@app.post('/api/projects/<pid>/documentary-transitions')
def set_documentary_transitions(pid):
 """Set transitions on the real picture cuts of a Beat timeline.

 Only the transition and its length change. Timing, sources, narration, SRT and
 approvals are untouched: a transition overlaps the outgoing shot onto the first
 frames of the next one, so the film's length and every cut point stay where they are.
 """
 with LOCKS[pid]:
  editable(pid);p=load(pid);scenes=p.get('scenes') or []
  if not scenes:raise BadRequest('Build the Beat timeline before choosing transitions.')
  d=request.get_json(silent=True) or {};action=d.get('action');duration=d.get('duration')
  if duration is not None and duration not in transitions.DURATION:raise BadRequest('Choose a transition length: '+', '.join(transitions.DURATION))
  exact=d.get('frames')
  if exact is not None and (isinstance(exact,bool) or not isinstance(exact,int) or not 4<=exact<=90):raise BadRequest('A transition length must be 4 to 90 frames (0.13 to 3 seconds).')
  cuts=transitions.documentary_cuts(scenes);lengths=transitions.shot_frames(scenes,cuts)
  include_locked=d.get('include_locked') is True
  # Still-only automatic moves share the grouped photo setting.
  auto_camera = {}
  snapshot_ids = [scenes[c]['id'] for c in cuts]
  _cinematic_snapshot(p,snapshot_ids,'transitions: '+str(action))
  def put(c,key,source,force=False):
   # A locked transition is the editor's decision: Auto and Apply-to-all leave it alone.
   if scenes[c].get('transition_locked') and not (force or include_locked):return
   key,frames=transitions.fit_frames(key,exact if exact and key!='cut' else transitions.frames_for(key,duration),*lengths[c])
   scenes[c]['transition']=key;scenes[c]['transition_handle_frames']=frames;scenes[c]['transition_source']=source
  def cut_for(scene_id,into):
   index=next((i for i,s in enumerate(scenes) if s['id']==scene_id),None)
   if index is None:raise NotFound('Scene not found.')
   if into:
    # The cut INTO the shot holding this scene is the last real cut before it.
    c=next((c for c in reversed(cuts) if c<index),None)
    if c is None:raise BadRequest('This is the first shot of the film; there is no cut into it.')
    return c
   # The shot holding this scene ends at the first real cut at or after it.
   c=next((c for c in cuts if c>=index),None)
   if c is None:raise BadRequest('This is the last shot of the film; there is no cut after it.')
   return c
  if action=='set':
   key=d.get('key')
   if key not in transitions.LIBRARY:raise BadRequest('Choose a transition from the library.')
   c=cut_for(d.get('scene_id'),d.get('into') is True)
   put(c,key,'manual',force=True)
   if 'locked' in d:scenes[c]['transition_locked']=bool(d['locked'])
  elif action=='lock':
   c=cut_for(d.get('scene_id'),d.get('into') is True)
   scenes[c]['transition_locked']=bool(d.get('locked',True))
  elif action=='all':
   key=d.get('key')
   if key not in transitions.LIBRARY:raise BadRequest('Choose a transition from the library.')
   for c in cuts:put(c,key,'manual')
   p['documentary_transition_choice']={'all':key,'duration':duration}
  elif action=='auto':
   style=d.get('style') or 'balanced'
   if style not in transitions.AUTO_STYLES:raise BadRequest('Choose an Auto style: '+', '.join(transitions.AUTO_STYLES))
   # Story-led auto is deterministic; never reshuffle on successive clicks.
   seed=0 if style in ('truecrime','restrained','cinematic','dynamic') else (d.get('seed') if isinstance(d.get('seed'),int) else 0)
   chosen=transitions.auto_documentary(scenes,style,duration,seed,assets=_asset_kinds(p))
   for c,(key,frames) in chosen.items():
    if scenes[c].get('transition_locked') and not include_locked:continue
    if scenes[c].get('transition_source') in ('manual','script'):continue
    scenes[c]['transition']=key;scenes[c]['transition_handle_frames']=frames;scenes[c]['transition_source']='auto'
   for scene in scenes:
    if scene['id'] in auto_camera and (not scene.get('camera') or (scene['camera'].get('origin')=='auto' and not scene['camera'].get('locked'))):
     scene['camera']=auto_camera[scene['id']]
   p['documentary_transition_choice']={'auto':style,'duration':duration,'camera_auto':False}
   _sync_smart_still_cameras(p)
  elif action=='script':
   from documentary_storyboard import _script_transitions
   from documentary_beats import read_beats
   held={c:(scenes[c].get('transition'),scenes[c].get('transition_handle_frames'),scenes[c].get('transition_source'))
         for c in cuts if scenes[c].get('transition_locked') and not include_locked}
   for c in cuts:scenes[c]['transition']='cut';scenes[c]['transition_handle_frames']=0;scenes[c].pop('transition_source',None)
   _script_transitions(scenes,read_beats((p.get('production_script') or {}).get('text','')))
   for c,(key,frames,source) in held.items():
    scenes[c]['transition']=key;scenes[c]['transition_handle_frames']=frames
    if source:scenes[c]['transition_source']=source
   p['documentary_transition_choice']={'script_only':True}
  elif action=='clear':
   for s in scenes:
    if s.get('transition_locked') and not include_locked:continue
    s['transition']='cut';s['transition_handle_frames']=0;s.pop('transition_source',None)
   p['documentary_transition_choice']={'disabled':True}
  else:raise BadRequest('Choose set, all, auto, script or clear.')
  # Anything that is not a real cut stays a cut: there is nothing there to blend.
  real=set(cuts)
  for i,s in enumerate(scenes):
   if i not in real and s.get('transition')!='cut':s['transition']='cut';s['transition_handle_frames']=0
  if any(s.get('transition')!='cut' for s in scenes):p['transition_policy']='allow_dissolves'
  save(p)
  listed=_doc_cut_list(p);used={}
  for x in listed:
   if x['transition']!='cut':used[x['transition']]=used.get(x['transition'],0)+1
  return jsonify({'project':public(p),'cuts':listed,'summary':used,
                  'automatic_camera_count':sum(1 for x in auto_camera if any(z['id']==x and (z.get('camera') or {}).get('origin')=='auto' for z in scenes))})


@app.get('/api/captions')
def caption_library():
 # The dialog is built from this, so it can only offer looks the renderer can burn in.
 data=captions.catalogue()
 saved=(load(request.args.get('pid')) if request.args.get('pid') else {})
 data['selected']=captions.resolve(saved.get('caption_preset') or captions.DEFAULT)
 data['size']=saved.get('caption_size') or captions.DEFAULT_SIZE
 data['position']=saved.get('caption_position') or captions.DEFAULT_POSITION
 return jsonify(data)


@app.after_request
def cache(response):
 # Two things are immutable once written and too large to re-fetch on every seek:
 # source media (the URL carries the asset revision) and the narration mix (a
 # fresh uuid per render). A 50MB clip served no-cache re-downloaded on each
 # seek, which is what left the monitor hanging on a black frame.
 # The music bed is served from one fixed path and is *replaced* rather than
 # re-written in place, so it must never be cached as immutable: a replacement
 # would otherwise keep playing the previous file for a year.
 music=bool(re.fullmatch(r'/api/projects/[^/]+/documentary-music/file',request.path))
 replayable=(request.path.endswith('/file') and not music
             or re.fullmatch(r'/api/projects/[^/]+/documentary-audio/documentary_audio_[a-f0-9]{32}\.(wav|m4a)',request.path))
 if replayable and request.args.get('download')!='1' and response.status_code in (200,206):
  response.headers['Cache-Control']='private, max-age=31536000, immutable'
 elif music and response.status_code in (200,206):
  # Still cacheable, but keyed by the file's own identity so a new upload is a
  # different URL and reaches the browser immediately.
  response.headers['Cache-Control']='private, max-age=604800'
 elif getattr(response,'storyroom_immutable',False) and response.status_code in (200,304):
  response.headers['Cache-Control']='private, max-age=31536000, immutable'   # versioned thumbnail (cached_image)
 else:
  response.headers['Cache-Control']='no-store'
 return response
@app.get('/api/build-info')
def build_info():
 return jsonify({'build':'2026-11-26-cinematic-graphics-review-v31','workflow':'simplified-documentary','script_and_srt_authoritative':True})

@app.get('/api/projects')
def projects():
 result=[]
 for f in PROJECTS.glob('*/project.json'):
  try:p=json.loads(f.read_text())
  except FileNotFoundError:continue  # A production may have been deleted while listing.
  result.append({k:p[k] for k in ['id','title','profile','format','updated']}|{'scenes':len(p['scenes']),'approved':sum(s['approved'] for s in p['scenes']),'portable':bool(p.get('portable_from_project')),'edit_mode':p.get('edit_mode','review')}|_home_card(p,f.parent))
 return jsonify({'projects':sorted(result,key=lambda x:-x['updated']),'profiles':PROFILES})

# v22 home page. Everything a project card shows comes from files that are already there,
# so listing stays a read of project.json plus a few stat calls per project.
def _cover_source(p):
 """The picture for the home card: the first timeline shot with media, else the first upload."""
 assets={a['id']:a for a in p.get('assets',[])}
 for s in p.get('scenes',[]):
  a=assets.get(s.get('asset_id'))
  if a and a.get('kind') in ('video','image'):return a,float(s.get('in_s') or 0)
 for kind in ('video','image'):
  a=next((a for a in p.get('assets',[]) if a.get('kind')==kind and not a.get('derived_from')),None)
  if a:return a,min(1.0,float(a.get('duration') or 0)*0.1)
 return None,0.0
def _home_card(p,root):
 from documentary import build_timeline, load_plan, narration_clock_s
 try:length=float(narration_clock_s(p)) if p.get('voiceover') else 0.0
 except (TypeError,ValueError):length=0.0
 picture_end=max((float(s.get('frame_out') or 0) for s in p.get('scenes',[])),default=0)/30
 if p.get('edit_mode')=='documentary' and length:
  try:
   timeline=build_timeline(p,load_plan(root))
   picture_clock=timeline['duration_s'] if p.get('documentary_beat_review') else timeline['narration_duration_s']
   length=timeline['duration_s']+max(0,picture_end-picture_clock)
  except (OSError,ValueError,TypeError,KeyError):
   length=max(length,picture_end)
 else:
  length=max(length,picture_end)
 finals=sorted((x for pat in ('documentary_final_*.mp4','final_*.mp4') for x in (root/'renders').glob(pat)),key=lambda x:x.stat().st_mtime,reverse=True) if (root/'renders').is_dir() else []
 current=False
 if finals:
  try:current=json.loads((root/'reviews'/(finals[0].stem+'.json')).read_text()).get('project',{}).get('updated')==p['updated']
  except (OSError,ValueError,AttributeError):current=False
 status='setup' if not p.get('assets') and not p.get('voiceover') else 'exported' if current else 'editing'
 a,at=_cover_source(p)
 cover=f"/api/projects/{p['id']}/cover.jpg?v={a['id']}-{a.get('revision') or 0}-{at:.3f}" if a else None
 return {'length_s':round(length,3),'status':status,'has_export':bool(finals),'cover_url':cover}

@app.get('/favicon.ico')
def favicon():
 """v26: the SR logo in the browser tab (browsers also ask for /favicon.ico directly)."""
 return send_from_directory(BASE/'static','favicon.ico',mimetype='image/vnd.microsoft.icon',max_age=86400)

@app.get('/api/projects/<pid>/cover.jpg')
def project_cover(pid):
 p=snapshot(pid);a,at=_cover_source(p)
 if not a:raise NotFound('This project has no pictures yet.')
 root=folder(pid).resolve();source=(root/a['path']).resolve()
 if not source.is_relative_to(root) or not source.is_file():raise NotFound('Media file is missing.')
 stat=source.stat()
 key=hashlib.sha256(json.dumps(['cover',a['id'],a.get('revision'),at,stat.st_size,stat.st_mtime_ns]).encode()).hexdigest()[:24]
 cache=root/'.cache'/'home';cache.mkdir(parents=True,exist_ok=True);out=cache/(key+'.jpg')
 if not out.exists():
  with THUMBNAIL_SLOTS:
   if not out.exists():
    if a.get('kind')=='image':img=cv2.imread(str(source));ok=img is not None
    else:
     from conform import capture
     cap=capture(source)
     try:cap.set(cv2.CAP_PROP_POS_MSEC,(at+0.4)*1000);ok,img=cap.read()
     finally:cap.release()
    if not ok:raise NotFound('The cover frame could not be decoded.')
    h,w=img.shape[:2];scale=min(1.0,480/max(1,w),480/max(1,h))   # keeps the shape; 9:16 stays 9:16
    temp=out.with_name(out.stem+'.'+uid()+'.jpg')
    try:cv2.imwrite(str(temp),cv2.resize(img,(max(1,int(w*scale)),max(1,int(h*scale))),interpolation=cv2.INTER_AREA),[cv2.IMWRITE_JPEG_QUALITY,84]);temp.replace(out)
    finally:temp.unlink(missing_ok=True)
 return cached_image(send_from_directory(cache,out.name,conditional=True),bool(request.args.get('v')))

@app.post('/api/projects/<pid>/open-export-folder')
def open_export_folder(pid):
 """Open the project's renders folder in Explorer / Finder on this computer."""
 load(pid);target=(folder(pid)/'renders');target.mkdir(parents=True,exist_ok=True)
 try:
  if sys.platform.startswith('win'):os.startfile(str(target))   # noqa: only exists on Windows
  elif sys.platform=='darwin':subprocess.Popen(['open',str(target)])
  else:subprocess.Popen(['xdg-open',str(target)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  opened=True
 except (OSError,AttributeError):opened=False
 return jsonify({'opened':opened,'path':str(target)})
@app.post('/api/projects')
def create():
 d=request.get_json() or {};title=str(d.get('title','')).strip()
 if not title or len(title)>100:raise BadRequest('Enter a production title of 1–100 characters.')
 mode=d.get('edit_mode','review')
 if mode not in ('review','documentary'):raise BadRequest('Choose either script review or documentary edit.')
 profile=d.get('profile') or 'documentary';fmt=d.get('format','landscape')
 if profile not in PROFILES or fmt not in ASPECTS:raise BadRequest('Choose a supported profile and format.')
 requested_size=d.get('size') or DEFAULT_SIZE.get(fmt)
 if not isinstance(requested_size,str) or not valid_size(requested_size):raise BadRequest('Choose an export size: '+', '.join(SIZES)+', or a pixel size such as 1920x1080.')
 requested_size=stored_size(requested_size)
 pid=uid();root=PROJECTS/pid;root.mkdir()
 for name in ['inputs','inputs/semantic','sources','assets','renders','reviews']: (root/name).mkdir(parents=True,exist_ok=True)
 requested=d.get('picture_policy')
 if requested is not None and requested not in POLICIES:raise BadRequest('Choose a picture policy: '+', '.join(POLICIES))
 p={'id':pid,'schema_version':1,'edit_mode':mode,'picture_policy':requested or 'clips_only','transition_policy':'clean_cuts_only', 'repetition_policy':{'cooldown_slots':0 if mode=='documentary' else 6,'source_interval_overlap_forbidden_within_window':False if mode=='documentary' else True},'auto_assemble_uploads':True,'title':title,'profile':profile,'format':fmt,'size':requested_size,'brief':str(d.get('brief','')),'people':[],'assets':[],'scenes':[],'voiceover':None,'srt':None,'updated':time.time()}
 from approval import ensure_automatic_policy
 ensure_automatic_policy(p)
 write(root/'project.json',p);write(root/'catalog.json',{'slots':{}});return jsonify(public(p)),201
def queue_proxy(pid,project,source):
 """Queue an editing copy for one uploaded video, at priority 2.

 Priority 2 rather than 3 because a proxy is what makes the clip editable at all:
 scrubbing the original while it is being made is the slow experience this exists to
 remove. It is still queue work, so it waits behind anything already running.
 """
 import cache, proxy as proxy_module
 settings=SETTINGS.load()
 if not settings.get('proxies_enabled'):return None
 store,_detail=SETTINGS.cache_store()
 try:info=proxy_module.probe(FFMPEG,source)
 except OSError:return None
 if not proxy_module.needs_proxy(info):return None
 quality=settings.get('proxy_quality') or proxy_module.DEFAULT_QUALITY
 needed=int((info.get('height') or 0)*(info.get('duration') or 0)*0.02*1024**2)
 warning=cache.would_fill_disk(store,max(needed,50*1024**2))
 if warning:return None
 def work(context):
  return proxy_module.ensure(FFMPEG,store,source,quality,context=context)
 job=jobqueue.Job('proxy-'+cache.entry_key(source,'proxy',quality),
                  'Editing copy · '+Path(source).name,
                  work,priority=jobqueue.PRIORITY_MEDIA,weight='light',
                  project=pid,meta={'asset':str(Path(source).name),'quality':quality})
 return QUEUE.submit(job)

@app.get('/api/projects/<pid>')
def get_project(pid):
 _maybe_auto(pid)
 return _get_project(pid)

_AUTO_SEEN=set()
def _maybe_auto(pid):
 # After the editor restarts, nothing has been saved yet: check once when opened.
 if pid in _AUTO_SEEN:return
 _AUTO_SEEN.add(pid)
 try:schedule_auto_build(pid,1.0)
 except Exception:pass

def _get_project(pid):
 # Reading never waits for a long job that holds the project lock: saves are atomic
 # file swaps, so the file on disk is always a complete version. Only the rare policy
 # upgrade below writes, and it takes the lock to do so.
 p=load(pid)
 from approval import ensure_automatic_policy
 if ensure_automatic_policy(copy.deepcopy(p)):
  with LOCKS[pid]:
   p=load(pid)
   if ensure_automatic_policy(p):save(p)
 return jsonify(public(p))
@app.get('/api/projects/<pid>/health')
def project_health_status(pid):
 """Read-only intake health: no media probing, job launches or project edits."""
 from project_health import assess
 return jsonify(assess(snapshot(pid),folder(pid)))

@app.get('/api/projects/<pid>/heartbeat')
def project_heartbeat(pid):
 """What the editor's 3-second poll needs to decide whether anything changed: the
 saved version and the progress of background jobs. The full project (with every check
 re-run) is fetched only when one of these moves."""
 p=snapshot(pid);root=folder(pid)
 saved=root/'render_status.json'
 try:render=JOBS[pid].snapshot() if pid in JOBS else json.loads(saved.read_text()) if saved.exists() else {'status':'idle','progress':0}
 except (OSError,ValueError):render={'status':'idle','progress':0}
 if pid not in JOBS and render.get('status') in ['running','queued']:render={'status':'interrupted','progress':0}
 from preview_render import status as preview_status
 from scene_exports import status as scene_export_status
 pick=lambda x:{k:x.get(k) for k in ('status','progress','output')}
 auto=p.get('auto_build') or {}
 try:
  import documentary_beat_build
  build=documentary_beat_build.snapshot(pid)
  if build.get('status') in ('queued','running'):auto={**auto,'status':'building','progress':(build.get('percent') or 0)/100}
 except Exception:pass
 return jsonify({'updated':p.get('updated'),'render':pick(render),'auto':{k:auto.get(k) for k in ('status','reason','progress')},
                 'preview':pick(preview_status(root,pid,p['updated'])),
                 'scene_exports':pick(scene_export_status(root,pid,p['updated']))})
@app.delete('/api/projects/<pid>')
def delete_project(pid):
 # The ID is validated by folder(), and all project writers/start operations use this lock.
 with LOCKS[pid]:
  root=folder(pid)
  if (request.get_json(silent=True) or {}).get('confirm') is not True:
   raise BadRequest('Confirm permanent deletion of the production and its files.')
  if busy(pid):raise BadRequest('This production is rendering. Wait for it to finish or cancel the render before deleting.')
  import automatic, preview_render, scene_exports, local_understanding
  with automatic._QUEUE_LOCK:
   if pid in automatic._PENDING:raise BadRequest('This production is assembling. Wait for it to finish before deleting.')
  for module,label in ((preview_render,'preview'),(scene_exports,'scene-clip export')):
   with module.GUARD:
    job=module.JOBS.get(pid)
    if job and job.get('status') in ('queued','running'):raise BadRequest('A '+label+' is being prepared. Wait for it to finish before deleting.')
  with local_understanding._GUARD:
   if any(Path(project)==root for project,target in local_understanding._RUNNING):raise BadRequest('Local media analysis is running. Wait for it to finish before deleting.')
  if root.is_symlink():raise BadRequest('Cannot delete a linked project folder. Remove it manually after checking its location.')
  try:shutil.rmtree(root)
  except OSError as e:
   app.logger.exception('Could not completely delete production %s',pid)
   raise BadRequest('Deletion could not finish; some project files may remain. Check the project folder and file permissions or close programs using them. '+str(e))
  JOBS.pop(pid,None)
  with preview_render.GUARD:preview_render.JOBS.pop(pid,None)
  with scene_exports.GUARD:scene_exports.JOBS.pop(pid,None)
  return jsonify({'deleted':True,'id':pid})

@app.get('/api/projects/<pid>/channel-cta')
def get_channel_cta(pid):
 from channel_cta import settings, plan, path_for
 p=load(pid);root=folder(pid);present=bool(path_for(p,root))
 return jsonify({'settings':settings(p),'present':present,'windows':plan(p,root,__import__('documentary').load_plan(root)),
    'name':(p.get('channel_cta_asset') or {}).get('original_name','')})

@app.get('/api/projects/<pid>/channel-cta/image')
def channel_cta_image(pid):
 from channel_cta import path_for
 p=load(pid);file=path_for(p,folder(pid))
 if not file:raise NotFound('No channel CTA card uploaded for this project.')
 return send_file(file,mimetype='image/png',conditional=True)

@app.post('/api/projects/<pid>/channel-cta')
def update_channel_cta(pid):
 from channel_cta import validate_patch
 with LOCKS[pid]:
  editable(pid);p=load(pid)
  try: patch=validate_patch(request.get_json() or {})
  except ValueError as e:raise BadRequest(str(e))
  p['channel_cta']={**(p.get('channel_cta') or {}),**patch}
  from channel_cta import settings
  cfg=settings(p)
  if cfg['mode']=='manual' and cfg['manual_in_s'] is not None and cfg['manual_out_s'] is not None and cfg['manual_out_s']<=cfg['manual_in_s']:
   raise BadRequest('CTA manual OUT must be later than IN.')
  save(p);return jsonify(public(p))

@app.get('/api/projects/<pid>/watermark/image')
def watermark_image(pid):
 import watermark
 p=load(pid);file=watermark.path_for(p,folder(pid))
 if not file:raise NotFound('No watermark logo uploaded for this project.')
 return send_file(file,mimetype='image/png',conditional=True)

@app.post('/api/projects/<pid>/watermark')
def update_watermark(pid):
 import watermark
 with LOCKS[pid]:
  editable(pid);p=load(pid)
  try:patch=watermark.validate_patch(request.get_json() or {})
  except ValueError as e:raise BadRequest(str(e))
  p['watermark']={**(p.get('watermark') or {}),**patch}
  save(p);return jsonify(public(p))

@app.post('/api/projects/<pid>/watermark/upload')
def upload_watermark(pid):
 import watermark
 from PIL import Image as PillowImage, ImageOps as PillowOps
 from io import BytesIO
 with LOCKS[pid]:
  editable(pid);p=load(pid);f=request.files.get('file')
  if not f or not f.filename:raise BadRequest('Choose a transparent PNG (or WebP) logo.')
  if Path(f.filename).suffix.lower() not in ('.png','.webp','.jpg','.jpeg'):raise BadRequest('Upload a PNG, WebP or JPG logo.')
  raw=f.read(12*1024*1024+1)
  if len(raw)>12*1024*1024:raise BadRequest('The logo must be no larger than 12 MB.')
  try:
   with PillowImage.open(BytesIO(raw)) as opened:
    if opened.width>6000 or opened.height>6000 or opened.width<16 or opened.height<16:
     raise ValueError('the logo must be between 16×16 and 6000×6000 pixels.')
    image=PillowOps.exif_transpose(opened).convert('RGBA')
  except (OSError,ValueError,PillowImage.DecompressionBombError) as e:raise BadRequest('Invalid logo image: '+str(e))
  # Trim fully transparent borders so size and corner placement follow the visible logo.
  box=image.getchannel('A').getbbox()
  if box:image=image.crop(box)
  target=folder(pid)/'assets'/watermark.FILE;temp=target.with_suffix('.upload.png')
  image.save(temp,format='PNG');temp.replace(target)
  p['watermark_asset']={'file':watermark.FILE,'original_name':Path(f.filename).name,'has_alpha':image.getchannel('A').getextrema()[0]<255}
  p['watermark']={**(p.get('watermark') or {})}
  save(p);return jsonify(public(p))

@app.delete('/api/projects/<pid>/watermark')
def delete_watermark(pid):
 import watermark
 with LOCKS[pid]:
  editable(pid);p=load(pid);file=watermark.path_for(p,folder(pid))
  p.pop('watermark_asset',None);save(p)
  if file:file.unlink(missing_ok=True)
  return jsonify(public(p))

@app.post('/api/projects/<pid>/channel-cta/upload')
def upload_channel_cta(pid):
 from PIL import Image as PillowImage, ImageOps as PillowOps
 from io import BytesIO
 with LOCKS[pid]:
  editable(pid);p=load(pid);f=request.files.get('file')
  if not f or not f.filename:raise BadRequest('Choose a PNG, WebP or JPG channel card.')
  if Path(f.filename).suffix.lower() not in ('.png','.webp','.jpg','.jpeg'):
   raise BadRequest('Upload PNG, WebP or JPG for the channel card.')
  raw=f.read(12*1024*1024+1)
  if len(raw)>12*1024*1024:raise BadRequest('CTA card must be no larger than 12 MB.')
  try:
   with PillowImage.open(BytesIO(raw)) as opened:
    if opened.width>5000 or opened.height>5000 or opened.width<32 or opened.height<16:
     raise ValueError('CTA image must be between 32×16 and 5000×5000 pixels.')
    image=PillowOps.exif_transpose(opened).convert('RGBA')
  except (OSError,ValueError,PillowImage.DecompressionBombError) as e:raise BadRequest('Invalid channel CTA image: '+str(e))
  target=folder(pid)/'assets'/'channel_cta.png';temp=target.with_suffix('.upload.png')
  image.save(temp,format='PNG');temp.replace(target)
  p['channel_cta_asset']={'file':'channel_cta.png','original_name':Path(f.filename).name}
  p['channel_cta']={**(p.get('channel_cta') or {}),'enabled':True}
  save(p);return jsonify(public(p))

# v26 stickers ---------------------------------------------------------------
def _film_seconds(p):
 try:
  from documentary import narration_clock_s
  return float(narration_clock_s(p)) if p.get('voiceover') else 0.0
 except (TypeError,ValueError,KeyError):return 0.0

@app.get('/api/projects/<pid>/stickers/library')
def sticker_library(pid):
 import stickers
 p=snapshot(pid)
 return jsonify({'stickers':stickers.library(p,pid),'groups':['Subscribe','Arrows & shapes','Yours']})

@app.post('/api/projects/<pid>/stickers')
def add_sticker(pid):
 import stickers
 data=request.get_json(silent=True) or {}
 with LOCKS[pid]:
  editable(pid);p=load(pid)
  try:row=stickers.new_sticker(p,data.get('sticker'),data.get('start_s',0),_film_seconds(p))
  except ValueError as e:raise BadRequest(str(e))
  p['stickers']=[*(p.get('stickers') or []),row]
  save(p);out=public(p);out['added_sticker']=row['id'];return jsonify(out),201

@app.patch('/api/projects/<pid>/stickers/<sid>')
def change_sticker(pid,sid):
 import stickers
 data=request.get_json(silent=True)
 with LOCKS[pid]:
  editable(pid);p=load(pid);rows=p.get('stickers') or []
  i=next((k for k,r in enumerate(rows) if r.get('id')==sid),None)
  if i is None:raise NotFound('That sticker is no longer in this project.')
  try:rows[i]=stickers.apply_patch(rows[i],data)
  except ValueError as e:raise BadRequest(str(e))
  p['stickers']=rows;save(p);return jsonify(public(p))

@app.delete('/api/projects/<pid>/stickers/<sid>')
def remove_sticker(pid,sid):
 with LOCKS[pid]:
  editable(pid);p=load(pid);rows=p.get('stickers') or []
  if not any(r.get('id')==sid for r in rows):raise NotFound('That sticker is no longer in this project.')
  p['stickers']=[r for r in rows if r.get('id')!=sid];save(p);return jsonify(public(p))

@app.post('/api/projects/<pid>/stickers/upload')
def upload_sticker(pid):
 """Your own sticker (PNG with transparency works best). Saved as PNG in assets/stickers."""
 import stickers
 from io import BytesIO
 from PIL import Image as PillowImage, ImageOps as PillowOps
 with LOCKS[pid]:
  editable(pid);p=load(pid);f=request.files.get('file')
  if not f or not f.filename:raise BadRequest('Choose a PNG, WebP or JPG sticker.')
  if Path(f.filename).suffix.lower() not in ('.png','.webp','.jpg','.jpeg'):raise BadRequest('Upload PNG, WebP or JPG for a sticker.')
  if len(stickers.uploads(p))>=stickers.MAX_UPLOADS:raise BadRequest(f'Up to {stickers.MAX_UPLOADS} of your own stickers per project.')
  raw=f.read(12*1024*1024+1)
  if len(raw)>12*1024*1024:raise BadRequest('A sticker must be no larger than 12 MB.')
  try:
   with PillowImage.open(BytesIO(raw)) as opened:
    if opened.width>6000 or opened.height>6000 or opened.width<16 or opened.height<16:
     raise ValueError('a sticker must be between 16×16 and 6000×6000 pixels.')
    image=PillowOps.exif_transpose(opened).convert('RGBA')
  except (OSError,ValueError,PillowImage.DecompressionBombError) as e:raise BadRequest('Invalid sticker image: '+str(e))
  image.thumbnail((1920,1920),PillowImage.LANCZOS)
  uid_='up_'+uuid.uuid4().hex[:12];name=uid_+'.png'
  target=folder(pid)/'assets'/stickers.UPLOAD_DIR;target.mkdir(parents=True,exist_ok=True)
  temp=target/(name+'.part');image.save(temp,format='PNG');temp.replace(target/name)
  p['sticker_uploads']=[*stickers.uploads(p),{'id':uid_,'file':name,'name':Path(f.filename).stem[:60]}]
  save(p);out=public(p);out['uploaded_sticker']=uid_;return jsonify(out),201

@app.delete('/api/projects/<pid>/stickers/upload/<uid_>')
def delete_sticker_upload(pid,uid_):
 """Remove one of your stickers from the library, and from the film where it is used."""
 import stickers
 with LOCKS[pid]:
  editable(pid);p=load(pid);row=next((u for u in stickers.uploads(p) if u['id']==uid_),None)
  if not row:raise NotFound('That sticker is no longer in your library.')
  p['sticker_uploads']=[u for u in stickers.uploads(p) if u['id']!=uid_]
  p['stickers']=[r for r in p.get('stickers') or [] if r.get('sticker')!=uid_]
  save(p);(folder(pid)/'assets'/stickers.UPLOAD_DIR/row['file']).unlink(missing_ok=True)
  return jsonify(public(p))

@app.get('/api/projects/<pid>/stickers/file/<name>')
def sticker_file(pid,name):
 import stickers
 p=snapshot(pid)
 if not any(u['file']==name for u in stickers.uploads(p)):raise NotFound('Sticker not found.')
 return send_from_directory(folder(pid)/'assets'/stickers.UPLOAD_DIR,name,mimetype='image/png',max_age=3600)

@app.delete('/api/projects/<pid>/channel-cta')
def delete_channel_cta(pid):
 with LOCKS[pid]:
  editable(pid);p=load(pid);from channel_cta import path_for
  f=path_for(p,folder(pid));p.pop('channel_cta_asset',None);p['channel_cta']={**(p.get('channel_cta') or {}),'enabled':False}
  save(p)
  if f:f.unlink(missing_ok=True)
  return jsonify(public(p))

@app.patch('/api/projects/<pid>')
def update_project(pid):
 with LOCKS[pid]:
  editable(pid);p=load(pid);d=request.get_json() or {};old_brief=p['brief'];old_people=copy.deepcopy(p['people'])
  for k in ['title','brief']:
   if k in d:p[k]=str(d[k])[:20000]
  if not p['title'].strip():raise BadRequest('A production title is required.')
  if 'people' in d:
   # Editing names here must not drop a person's photo or overlay choices, which are
   # managed through /people. They are carried over by id, or by name for old clients.
   kept={**{str(x.get('name','')).casefold():x for x in p['people']},**{x.get('id'):x for x in p['people'] if x.get('id')}}
   people=[]
   for x in d['people']:
    if not str(x.get('name','')).strip():continue
    old=kept.get(x.get('id')) or kept.get(str(x.get('name','')).strip().casefold()) or {}
    person={**{k:old[k] for k in ('id','photo','show','short_names','exclude','focus_y') if k in old},'name':str(x.get('name','')).strip()[:120],'role':str(x.get('role',''))[:80],'aliases':[str(a).strip()[:120] for a in x.get('aliases',[]) if str(a).strip()]}
    people.append(person)
   p['people']=people
  if 'person_overlay_settings' in d:
   from person_overlays import clean_settings
   try:p['person_overlay_settings']={**(p.get('person_overlay_settings') or {}),**clean_settings(d['person_overlay_settings'])}
   except ValueError as e:raise BadRequest(str(e))
   _sync_smart_still_cameras(p)
  if 'picture_policy' in d:
   if d['picture_policy'] not in POLICIES:raise BadRequest('Choose a picture policy: '+', '.join(POLICIES))
   p['picture_policy']=d['picture_policy']
   for scene in p['scenes']:scene['approved']=False
  if 'image_layout' in d:
   if d['image_layout'] not in STILL_LAYOUTS:raise BadRequest('Choose a photograph layout: '+', '.join(STILL_LAYOUTS))
   p['image_layout']=d['image_layout']
  # Output geometry. Changing it does not change a single cut: it re-encodes the picture
  # at the new size, so the beats, wording, approvals and duration all stay as reviewed.
  if 'format' in d:
   if d['format'] not in ASPECTS:raise BadRequest('Choose a format: '+', '.join(ASPECTS))
   if d['format']!=p.get('format'):
    p['format']=d['format']
    p['size']=d.get('size') or DEFAULT_SIZE[d['format']]
    if not valid_size(p['size']):raise BadRequest('Choose an export size: '+', '.join(SIZES)+', or a pixel size such as 1920x1080.')
    p['picture_rebuilt']=False
  response_extra={}
  if 'transition_policy' in d:
   if d['transition_policy'] not in TRANSITION_POLICIES:raise BadRequest('Choose a transition policy: '+', '.join(TRANSITION_POLICIES))
   if d['transition_policy']!=p.get('transition_policy'):
    p['transition_policy']=d['transition_policy']
    cleared=0
    if d['transition_policy']=='clean_cuts_only':
     # Turning dissolves off has to mean something for the scenes that already carry them.
     # Clearing them is the only consistent reading of "clean cuts only", and the response
     # says how many so a caller is never left guessing where its dissolves went. It is
     # reported rather than saved: it describes this request, not the production.
     for scene in p['scenes']:
      if scene.get('transition')!='cut':scene['transition']='cut';scene['transition_handle_frames']=0;cleared+=1
    p.pop('dissolves_cleared',None)
    response_extra={'dissolves_cleared':cleared}
  if 'picture_scale' in d:
   scale=d['picture_scale']
   if isinstance(scale,bool) or not isinstance(scale,int) or not 100<=scale<=200:raise BadRequest('Picture scale must be a whole percentage from 100 to 200.')
   if scale!=p.get('picture_scale',100):p['picture_scale']=scale;p['picture_rebuilt']=False
  if 'size' in d:
   if not isinstance(d['size'],str) or not valid_size(d['size']):raise BadRequest('Choose an export size: '+', '.join(SIZES)+', or a pixel size such as 1920x1080.')
   # The export page sends `2k`; store the one short-side number that means it.
   stored=stored_size(d['size'])
   if stored!=str(p.get('size')):
    p['size']=stored
    p['picture_rebuilt']=False
  # Export picture settings. These describe how a frame is made larger and how a
  # differently-shaped source sits in the canvas; none of them move a cut, retime a
  # frame or touch the audio.
  if 'framing' in d:
   if d['framing'] not in FRAMING_MODES:raise BadRequest('Choose a framing mode: '+', '.join(FRAMING_MODES))
   p['framing']=d['framing']
  if 'upscaler' in d:
   if d['upscaler'] not in PICTURE_UPSCALERS:raise BadRequest('Choose a picture upscaler: '+', '.join(PICTURE_UPSCALERS))
   p['upscaler']=d['upscaler']
  if 'quality' in d:
   if d['quality'] not in QUALITY_PRESETS:raise BadRequest('Choose an export quality: '+', '.join(QUALITY_PRESETS))
   p['quality']=d['quality']
  # On-screen script captions are opt-in. Turning them off only changes what is
  # burned into the picture; the script, the SRT and every cut stay as reviewed.
  if 'burn_captions' in d:
   if not isinstance(d['burn_captions'],bool):raise BadRequest('On-screen captions must be on or off.')
   p['burn_captions']=d['burn_captions']
  if 'caption_preset' in d:
   # The preset is a project setting so the preview and the export read the same value;
   # an unknown key is refused rather than silently rendered as the default, because a
   # caption style the editor cannot show is worse than an error.
   if d['caption_preset'] not in captions.PRESETS:raise BadRequest('Choose a caption style from the library.')
   p['caption_preset']=d['caption_preset']
  if 'caption_size' in d:
   if d['caption_size'] not in captions.SIZES:raise BadRequest('Choose a caption size: '+', '.join(captions.SIZES))
   p['caption_size']=d['caption_size']
  if 'caption_position' in d:
   if d['caption_position'] not in captions.POSITIONS:raise BadRequest('Choose a caption position: '+', '.join(captions.POSITIONS))
   p['caption_position']=d['caption_position']
  # The script's Cut Action fade. A fade ramps brightness on existing frames, so
  # it never changes a cut, a frame count or the reviewed timing.
  if 'documentary_fades' in d:
   fades=d['documentary_fades']
   if not isinstance(fades,dict):raise BadRequest('Fade settings must be an object.')
   current=dict(p.get('documentary_fades') or {})
   if 'enabled' in fades:
    if not isinstance(fades['enabled'],bool):raise BadRequest('Fades must be on or off.')
    current['enabled']=fades['enabled']
   for key in ('in_s','out_s'):
    if key in fades:
     try:value=float(fades[key])
     except (TypeError,ValueError):raise BadRequest('A fade length must be a number of seconds.')
     if not 0<=value<=5:raise BadRequest('A fade must be between 0 and 5 seconds.')
     current[key]=round(value,3)
   p['documentary_fades']=current
  if p['brief']!=old_brief or p['people']!=old_people:
   for scene in p['scenes']:scene['approved']=False
  save(p);body=public(p)
  if response_extra:body.update(response_extra)
  return jsonify(body)
# ---- People on screen: photo cards that appear when the narration names someone ----
# Photos live in the project's own people/ folder, not among the footage assets, so a
# portrait can never be put on the storyboard as footage or counted as a still. They
# are only ever drawn as an overlay card over the picture that is already playing.

def _person_words(value):
 if isinstance(value,list):items=value
 else:items=re.split(r'[,\n]',str(value or ''))
 return [' '.join(str(x).split())[:120] for x in items if str(x).strip()][:40]

def _find_person(p,person_id):
 from person_overlays import ensure_ids
 ensure_ids(p['people'])
 person=next((x for x in p['people'] if x.get('id')==person_id),None)
 if not person:raise NotFound('That person is not in this production.')
 return person

@app.post('/api/projects/<pid>/people')
def save_person(pid):
 """Add or update one person, optionally with a photo (multipart form)."""
 from person_overlays import ensure_ids,new_person_id,person_photos,MAX_PERSON_PHOTOS
 with LOCKS[pid]:
  editable(pid);p=load(pid);root=folder(pid);ensure_ids(p['people'])
  form=request.form;person_id=form.get('id') or ''
  person=_find_person(p,person_id) if person_id else None
  name=' '.join(str(form.get('name',person.get('name','') if person else '')).split())[:120]
  if not name:raise BadRequest('Enter the person’s name as the narration says it.')
  clash=next((x for x in p['people'] if x is not person and x.get('name','').casefold()==name.casefold()),None)
  if clash:raise BadRequest(f'{name} is already in this production. Edit that entry instead.')
  created=person is None
  if person is None:
   person={'id':new_person_id(),'name':name,'role':'','aliases':[],'short_names':False,'show':False};p['people'].append(person)
  person['name']=name
  if 'role' in form:person['role']=str(form.get('role',''))[:80].strip()
  if 'aliases' in form:person['aliases']=_person_words(form.get('aliases'))
  if created or form.get('find_spellings')=='1':
   # Fuzzy spelling searches are *suggestions*, not verified identity aliases.
   # Users can add appropriate complete names to the aliases field explicitly.
   known={x.casefold() for x in person.get('aliases') or []}
   person['suggested_aliases']=[x for x in srt_spellings(p,name) if x.casefold() not in known]
  if 'skip_cues' in form:
   try:person['skip_cues']=sorted({int(x) for x in re.split(r'[,\s]+',str(form.get('skip_cues'))) if x.strip()})
   except ValueError:raise BadRequest('Lines to skip must be SRT line numbers.')
  if 'exclude' in form:person['exclude']=_person_words(form.get('exclude'))
  if 'show' in form:person['show']=form.get('show') not in ('0','false','off','')
  if 'photo_over_video' in form:person['photo_over_video']=form.get('photo_over_video') not in ('0','false','off','')
  if 'short_names' in form:person['short_names']=form.get('short_names') not in ('0','false','off','')
  if 'focus_y' in form:
   try:person['focus_y']=max(0.0,min(1.0,float(form.get('focus_y'))))
   except ValueError:raise BadRequest('Photo focus must be a number from 0 (top) to 1 (bottom).')
  # The media-bin assignment is an explicitly user-confirmed identity. Never
  # identify from appearance, filename, OCR, or news metadata automatically.
  chosen_asset=form.get('asset_id','').strip()
  f=request.files.get('photo')
  operation=form.get('photo_action','replace').strip().lower()
  if operation not in ('replace','add'):
   raise BadRequest('Photo action must be add or replace.')
  try: replace_index=int(form.get('replace_index','0'))
  except ValueError: raise BadRequest('Invalid photo index.')
  prior=person_photos(person)
  if (chosen_asset or (f and f.filename)) and operation=='add' and len(prior)>=MAX_PERSON_PHOTOS:
   raise BadRequest('Each person can have up to five photos. Remove one before adding another.')
  if operation=='replace' and prior and not 0 <= replace_index < len(prior):
   raise BadRequest('Photo index does not exist.')
  if chosen_asset and f and f.filename:raise BadRequest('Choose an imported photo OR upload a new one.')
  if chosen_asset:
   asset=next((a for a in p.get('assets') or [] if a.get('id')==chosen_asset),None)
   if not asset or asset.get('kind')!='image' or asset.get('derived_from'):
    raise BadRequest('Choose a project photograph, not video footage.')
   source=(root / str(asset.get('path') or '')).resolve()
   if not source.is_relative_to(root.resolve()) or not source.is_file():
    raise BadRequest('This imported photo is missing. Re-upload it before assigning.')
   if form.get('identity_confirmed')!='1':
    raise BadRequest('Confirm that you personally checked who this photograph shows.')
   (root/'people').mkdir(exist_ok=True)
   ext=source.suffix.lower() if source.suffix.lower() in ('.png','.webp','.jpg','.jpeg') else '.jpg'
   dest=root/'people'/(uid()+ext)
   shutil.copy2(source,dest)
   try:dest,dims=_readable_photo(dest)
   except Exception:
    dest.unlink(missing_ok=True)
    raise BadRequest('This imported photo cannot be opened. Use a JPG, PNG or WebP.')
   if min(dims)<120:
    dest.unlink(missing_ok=True)
    raise BadRequest('Image too small to display (minimum side: 120 pixels).')
   entry={'path':dest.relative_to(root).as_posix(),'name':str(asset.get('original_name') or asset.get('name') or source.name)[:200],
          'dimensions':dims,'uploaded':time.time(),'source_asset_id':chosen_asset,
          'note':'User confirmed the pictured identity; verification and publication rights remain user responsibility.'}
   if operation=='add' or not prior:prior.append(entry)
   else:
    old=prior[replace_index].get('path')
    prior[replace_index]=entry
    if old and old!=entry['path']:(root/old).unlink(missing_ok=True)
   person['photos']=prior;person['photo']=prior[0]
  if f and f.filename:
   # Any photo: JPG, PNG and WebP are kept; HEIC, AVIF, GIF, BMP, TIFF ... become JPG.
   ext=Path(f.filename).suffix.lower() or '.jpg'
   if not re.fullmatch(r'\.[a-z0-9]{2,5}',ext):ext='.jpg'
   (root/'people').mkdir(exist_ok=True);dest=root/'people'/(uid()+ext)
   f.save(dest)
   try:dest,dims=_readable_photo(dest)
   except Exception:
    dest.unlink(missing_ok=True);raise BadRequest('That file is not a photo the editor can read. Save it as JPG and try again.')
   if min(dims)<120:dest.unlink(missing_ok=True);raise BadRequest('That photo is too small to show on screen (under 120 pixels).')
   entry={'path':Path(dest).relative_to(root).as_posix(),'name':Path(f.filename).name[:200],'dimensions':dims,'uploaded':time.time(),
          'note':'Identity, source and publication rights are the uploader’s own attestation; not independently verified.'}
   if operation=='add' or not prior:prior.append(entry)
   else:
    old=prior[replace_index].get('path')
    prior[replace_index]=entry
    if old and old!=entry['path']:(root/old).unlink(missing_ok=True)
   person['photos']=prior;person['photo']=prior[0]
  save(p);return jsonify(public(p))

@app.delete('/api/projects/<pid>/people/<person_id>')
def delete_person(pid,person_id):
 with LOCKS[pid]:
  editable(pid);p=load(pid);root=folder(pid);person=_find_person(p,person_id)
  from person_overlays import person_photos
  old=[x.get('path') for x in person_photos(person)]
  if request.args.get('photo_only')=='1':person.pop('photo',None);person.pop('photos',None)
  else:p['people']=[x for x in p['people'] if x is not person]
  for path in old:
   if path:(root/path).unlink(missing_ok=True)
  save(p);return jsonify(public(p))

@app.delete('/api/projects/<pid>/people/<person_id>/photos/<int:index>')
def delete_person_photo(pid,person_id,index):
 # Remove the specified photo only; keep the person and remaining images.
 from person_overlays import person_photos
 with LOCKS[pid]:
  editable(pid);p=load(pid);root=folder(pid);person=_find_person(p,person_id)
  gallery=person_photos(person)
  if index<0 or index>=len(gallery):raise NotFound('Photo slot not found.')
  removed=gallery.pop(index)
  if gallery:person['photos']=gallery;person['photo']=gallery[0]
  else:person.pop('photos',None);person.pop('photo',None);person['show']=False
  save(p)
  path=removed.get('path')
  if path and not any(path==x.get('path') for x in gallery):
   (root/path).unlink(missing_ok=True)
  return jsonify(public(p))

def _crop_target(p,root,args):
 """(record holding 'crop', image path, original url) for a person photo or an image asset."""
 if args.get('person'):
  from person_overlays import person_photos
  person=_find_person(p,str(args.get('person')))
  try:index=int(args.get('index',0))
  except (ValueError,TypeError):raise BadRequest('Invalid photo index.')
  gallery=person_photos(person)
  if not 0<=index<len(gallery):raise NotFound('No photo at that index for this person.')
  record=gallery[index]
  url=f'/api/projects/{p["id"]}/people/{person["id"]}/photo?index={index}'
  path=(root/str(record.get('path') or '')).resolve()
  if not path.is_relative_to(root.resolve()) or not path.is_file():raise NotFound('Photo file is missing.')
  return record,path,url,person
 asset=next((a for a in p.get('assets',[]) if a.get('id')==args.get('asset')),None)
 if not asset or asset.get('kind')!='image':raise NotFound('Image not found.')
 path=(root/str(asset.get('path') or '')).resolve()
 if not path.is_relative_to(root.resolve()) or not path.is_file():raise NotFound('Image file is missing.')
 return asset,path,f'/api/projects/{p["id"]}/assets/{asset["id"]}/file',None

def _crop_report(p,record,path,url,person,args):
 from clean_photo_framing import describe
 from PIL import Image
 with Image.open(path) as im:info=describe(im,record.get('crop'))
 info['original_url']=url
 if person is not None:
  info['after_url']=f'/api/projects/{p["id"]}/people/{person["id"]}/card.png?index={int(args.get("index",0))}&layer=photo&v={p.get("updated","")}'
 else:
  from clean_photo_framing import crop_token
  info['after_url']=f'/api/projects/{p["id"]}/assets/{record["id"]}/clean-frame?v={record.get("revision",0)}-{crop_token(record.get("crop"))}'
 return info

@app.get('/api/projects/<pid>/photo-crop')
def get_photo_crop(pid):
 """Adjust crop (v17): what the automatic clean-up cuts away, and the current setting."""
 with LOCKS[pid]:
  p=load(pid);root=folder(pid)
  record,path,url,person=_crop_target(p,root,request.args)
  return jsonify(_crop_report(p,record,path,url,person,request.args))

@app.post('/api/projects/<pid>/photo-crop')
def set_photo_crop(pid):
 """Save a photo's crop: automatic (default), a box drawn by hand, or the whole picture.

 Only the selection is stored; the uploaded original is never changed.
 """
 body=request.get_json(silent=True) or {}
 from clean_photo_framing import normalise_crop
 with LOCKS[pid]:
  editable(pid);p=load(pid);root=folder(pid)
  record,path,url,person=_crop_target(p,root,body)
  crop=body.get('crop')
  if crop is None or (isinstance(crop,dict) and crop.get('mode')=='auto'):
   record.pop('crop',None);clean=None
  else:
   clean=normalise_crop(crop)
   if clean is None:raise BadRequest('The crop box is too small or invalid.')
   record['crop']=clean
  if person is not None and isinstance(person.get('photo'),dict) and person['photo'].get('path')==record.get('path') and person['photo'] is not record:
   if clean is None:person['photo'].pop('crop',None)
   else:person['photo']['crop']=clean
  save(p)
  return jsonify({'project':public(p),'crop':_crop_report(p,record,path,url,person,body)})

@app.get('/api/projects/<pid>/people/<person_id>/photo')
def person_photo(pid,person_id):
 with LOCKS[pid]:
  p=load(pid);root=folder(pid);person=_find_person(p,person_id)
  from person_overlays import photo_at
  try:index=int(request.args.get('index',0))
  except (ValueError,TypeError):raise BadRequest('Invalid photo index.')
  selected=photo_at(person,index)
  path=selected.get('path') if selected else None
  if not path or not (root/path).is_file():raise NotFound('No photo at that index for this person.')
 return send_from_directory(root,path,conditional=True)

@app.get('/api/projects/<pid>/people/<person_id>/card.png')
def person_card(pid,person_id):
 """The overlay card exactly as the export draws it, at the project's output size."""
 from person_overlays import card_file,settings,has_photo,photo_person
 with LOCKS[pid]:
  p=load(pid);root=folder(pid);person=_find_person(p,person_id)
  if not has_photo(person,root):raise NotFound('No photo uploaded for this person.')
  try:person=photo_person(person,int(request.args.get('index',0)))
  except (ValueError,TypeError):raise NotFound('No photo at that index.')
  width,height=output_size(p.get('format','landscape'),p.get('size'))
  conf=settings(p)
  # v17: the name graphic shows only at a person's first introduction (intro=1).
  conf=dict(conf,show_label=request.args.get('intro')=='1')
  layer=request.args.get('layer')
  partner_id=request.args.get('with')
  if partner_id:
   # Two people named in one line, side by side (same files the export uses).
   from person_overlays import pair_layer_files
   partner=_find_person(p,partner_id)
   if not has_photo(partner,root):raise NotFound('No photo uploaded for the second person.')
   try:partner=photo_person(partner,int(request.args.get('with_index',0)))
   except (ValueError,TypeError):raise NotFound('No photo at that index.')
   intros=(request.args.get('intro')=='1',request.args.get('with_intro')=='1')
   photo,label=pair_layer_files([person,partner],root,width,height,dict(conf,style='full'),intros)
   out=label if layer=='label' else photo
   if out is None:raise NotFound('This pair has no name graphic.')
  elif layer in ('photo','label'):
   # A moving photo is drawn as two layers: the photo moves, the label stays still.
   from person_overlays import layer_files
   photo,label=layer_files(person,root,width,height,conf)
   out=photo if layer=='photo' else label
   if out is None:raise NotFound('This card has no label.')
  else:out=card_file(person,root,width,height,conf)
 return send_file(out,mimetype='image/jpeg' if out.suffix=='.jpg' else 'image/png',max_age=3600)

def person_overlay_report(p):
 """Overlay plan for the client: windows on the final timeline, card geometry as fractions."""
 from person_overlays import plan,settings,geometry
 root=folder(p['id']);conf=settings(p)
 try:data=plan(p,root)
 except ValueError as e:
  return {'settings':conf,'windows':[],'people':[],'notes':[str(e)],'mentions':0,'on_screen_ms':0,'duration_ms':0}
 from person_overlays import motion_camera,window_camera
 data['cameras']={x['id']:c for x in p.get('people') or [] if (c:=motion_camera(x,conf))}
 # Each photo appearance has its own move (entrance + camera); the preview uses these.
 people_by_id={x.get('id'):x for x in p.get('people') or []}
 for w in data.get('windows') or []:
  w['camera']=window_camera(w,people_by_id.get(w['person_id'])) if conf.get('style')=='full' else None
 width,height=output_size(p.get('format','landscape'),p.get('size'));g=geometry(width,height,conf)
 data['geometry']={'left':g['x']/width,'top':g['y']/height,'width':g['canvas_w']/width,'height':g['canvas_h']/height,'aspect':width/height}
 data['updated']=p.get('updated')
 # Every moment the narration names someone, shown or not, so the People list can be
 # checked line by line: the right person, the right line, and why a line shows nothing.
 from person_overlays import find_mentions,ensure_ids
 try:
  people=ensure_ids(list(p.get('people') or []))
  blocks=(p.get('srt') or {}).get('blocks') or []
  moments={}
  footage={(x['person_id'],x['cue']) for x in data.get('footage_lines') or []}
  opening=data.get('opening_ms')
  for m in find_mentions(blocks,people,keep_blocked=True):
   moments.setdefault(m['person_id'],[]).append({'cue':m['cue'],'ms':m['narration_ms'],'said':m['said'],'text':m['text'],
     'short':bool(m.get('short')),'via':m.get('via',''),'blocked':m.get('blocked',''),
     'footage':(m['person_id'],m['cue']) in footage,'opening':opening is None or m['narration_ms']<opening})
  data['moments']=moments
 except Exception as e:
  data['moments']={};data.setdefault('notes',[]).append('Moments could not be listed: '+str(e)[:200])
 return data


# ---- YouTube Footage Importer: a Markdown sheet of links in, S01.mp4 ... out ----
# The download engine is footage_downloader.py. These routes connect it to the
# project: every finished file is imported through register_downloaded_video below,
# which applies the same checks, naming and replacement rules as a manual upload.

_YTDLP_STATUS={'at':0,'value':None}
_YTDLP_INSTALL={'status':'idle','log':[],'error':'','finished':None}

def ytdlp_status(refresh=False):
 from footage_downloader import YtDlpProvider
 if refresh or not _YTDLP_STATUS['value'] or time.time()-_YTDLP_STATUS['at']>60:
  _YTDLP_STATUS.update(value=YtDlpProvider.status(),at=time.time())
 return _YTDLP_STATUS['value']

def _video_matches(p,name):
 return [a for a in p['assets'] if a.get('kind')=='video' and not a.get('derived_from') and str(a.get('original_name') or a.get('name') or '').casefold()==name.casefold()]

def _same_link(provenance,row):
 """True when an imported file came from the link on this sheet row (and the same window)."""
 pr=provenance or {}
 if (pr.get('window') or None)!=(row.get('window') or None) and [float(x) for x in pr.get('window') or []]!=[float(x) for x in row.get('window') or []]:return False
 if pr.get('video_id') and row.get('video_id'):return pr['video_id']==row['video_id'] and pr.get('media','video')==row.get('media','video')
 return bool(pr.get('url')) and pr.get('url')==row.get('url') and pr.get('media','video')==row.get('media','video')

def _photo_matches(p,name):
 stem=Path(name).stem.casefold()
 return [a for a in p['assets'] if a.get('kind')=='image' and not a.get('derived_from') and Path(str(a.get('original_name') or a.get('name') or '')).stem.casefold()==stem]

def _broll_matches(p,name):
 stem=Path(name).stem.casefold()
 return [a for a in p['assets'] if not a.get('derived_from') and Path(str(a.get('original_name') or a.get('name') or '')).stem.casefold()==stem]

def download_existing(pid,row):
 """'same' when this exact link is already imported under its name, 'other' when a different file has the name."""
 with LOCKS[pid]:
  p=load(pid);matches={'photo':_photo_matches,'broll':_broll_matches}.get(row.get('media'),_video_matches)(p,row['filename'])
 if not matches:return None
 if any(_same_link(a.get('provenance'),row) and (folder(pid)/a.get('path','')).is_file() for a in matches):return 'same'
 return 'other'

def register_download(pid,row,path,manifest='',analyse=None):
 """Import a finished download as what it really is: a photo or a video, whatever the row said."""
 path=Path(path)
 try:
  with Image.open(path) as im:im.verify()
  is_image=True
 except Exception:
  is_image=path.suffix.lower().lstrip('.') in ('heic','heif','avif')
 if is_image:return register_downloaded_photo(pid,row,path,manifest)
 if Path(row['filename']).suffix.lower()!='.mp4':
  # A picture link that turned out to be a video is kept as a video under the same name.
  row['filename']=Path(row['filename']).stem+'.mp4'
 aid=register_downloaded_video(pid,row,path,manifest,analyse=analyse)
 if row.get('media')=='broll' and row.get('description'):
  row['register_note']=f"In Footage as b-roll: {row['description'][:80]}"
 return aid

def _readable_photo(path):
 """(path, dims) of a photo the editor can show: JPG/PNG/WebP as they are, anything else converted to JPG."""
 path=Path(path)
 try:
  with Image.open(path) as im:
   im.load();fmt=im.format;im=ImageOps.exif_transpose(im);dims=[int(im.width),int(im.height)]
   if path.suffix.lower() in ('.jpg','.jpeg','.png','.webp') and fmt in ('JPEG','PNG','WEBP'):return path,dims
   out=path.with_suffix('.jpg');im.convert('RGB').save(out,quality=92)
   if out!=path:path.unlink(missing_ok=True)
   return out,dims
 except Exception:
  # HEIC/AVIF and other formats Pillow cannot open: ffmpeg usually can.
  out=path.with_name(path.stem+'-converted.jpg')
  r=subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-hide_banner','-loglevel','error','-y','-i',str(path),'-frames:v','1',str(out)],capture_output=True)
  if r.returncode!=0 or not out.is_file():raise ValueError('The downloaded file is not a photo the editor can read. Save it as JPG and upload it instead.')
  path.unlink(missing_ok=True)
  with Image.open(out) as im:dims=[int(im.width),int(im.height)]
  return out,dims

def _edit_distance(a,b):
 a,b=a.casefold(),b.casefold()
 if abs(len(a)-len(b))>2:return 9
 prev=list(range(len(b)+1))
 for i,x in enumerate(a,1):
  cur=[i]
  for j,y in enumerate(b,1):cur.append(min(prev[j]+1,cur[j-1]+1,prev[j-1]+(x!=y)))
  prev=cur
 return prev[-1]

def srt_spellings(p,name):
 """How the SRT actually spells a person's name ("Malia Bass" for Maliyah Bass, "Sahara
 Irvin" for Sahara Ervin): word runs of the same length within two letters of the name.
 Single-word spellings are never added automatically."""
 words=name.split()
 if len(words)<2:return []
 found=set()
 for block in (p.get('srt') or {}).get('blocks') or []:
  toks=re.findall(r"[A-Za-z][A-Za-z'\u2019-]*",block.get('text',''))
  for i in range(len(toks)-len(words)+1):
   run=toks[i:i+len(words)]
   if ' '.join(run).casefold()==name.casefold():continue
   if all(_edit_distance(a,b)<=2 for a,b in zip(run,words)) and sum(_edit_distance(a,b) for a,b in zip(run,words))<=2 \
      and all(len(a)>=3 for a in run) and (any(a.casefold()==b.casefold() for a,b in zip(run,words)) or all(a[:1].casefold()==b[:1].casefold() for a,b in zip(run,words))):
    cap=lambda x:x.capitalize() if x.islower() else x
    found.add(' '.join(cap(x) for x in run))
 return sorted(found)[:10]

def register_downloaded_photo(pid,row,path,manifest=''):
 """Import one downloaded photo under its sheet name (P01.jpg ...), and, when the sheet
 says whose photo it is, file it with that person so it shows when the narration names them."""
 from person_overlays import ensure_ids,new_person_id
 import shutil as _sh
 root=folder(pid)
 while busy(pid):time.sleep(5)
 path,dims=_readable_photo(path)
 ext=path.suffix.lower()
 name=row['filename']
 if row.get('fix_ext') or Path(name).suffix.lower() not in ('.jpg','.jpeg','.png','.webp'):name=Path(name).stem+('.jpg' if ext=='.jpeg' else ext)
 if not (row.get('person') or row.get('role')) and row.get('description'):
  note_base=f"In Photos as a base picture: {row['description'][:80]}"
 else:note_base=''
 dest=root/'assets'/(uid()+ext);dest.parent.mkdir(exist_ok=True);os.replace(path,dest)
 old_paths=[]
 try:
  with LOCKS[pid]:
   p=load(pid);matches=(_broll_matches if row.get('media')=='broll' else _photo_matches)(p,name)
   if matches and not row.get('replace') and not all(_same_link(a.get('provenance'),row) for a in matches):
    raise ValueError(f'{name} is already in this production. Choose Replace to download over it.')
   aid=matches[0]['id'] if matches else uid()
   person_label=' · '.join(x for x in (row.get('person'),row.get('role')) if x)
   asset={'id':aid,'name':name,'original_name':name,'path':dest.relative_to(root).as_posix(),'kind':'image','duration':0,'dimensions':dims,
          'source':row.get('url',''),'people':[row['person']] if row.get('person') else [],'category':'person' if person_label else 'broll',
          'verified':False,'rights':'unreviewed','notes':person_label or row.get('description',''),'revision':uid(),
          'provenance':{'kind':'sheet_photo','media':row.get('media','photo'),'description':row.get('description',''),'source_id':row.get('source_id'),'url':row.get('url'),'video_id':row.get('video_id'),
                        'title':row.get('title',''),'sheet':manifest,'downloaded':time.time(),'person':row.get('person',''),'role':row.get('role',''),
                        'note':'Downloaded at the user’s request. Identity, use and publication rights are the user’s own responsibility; not verified.'}}
   if matches:
    ids={a['id'] for a in matches}
    old_paths=[root/a['path'] for a in matches if a.get('path')]
    p['assets']=[a for a in p['assets'] if a['id'] not in ids]+[asset]
    for scene in p['scenes']:
     if scene.get('asset_id') in ids:scene['asset_id']=aid;scene['approved']=False;scene.pop('thumbnail',None)
   else:p['assets'].append(asset)
   note=note_base
   if row.get('person') or row.get('role'):
    from case_people import featured_role, source_is_supporting
    eligible=(bool(row.get('person')) and featured_role(row.get('role')) and
              not source_is_supporting(row.get('description')))
    if not eligible:
     note=(f"{name} saved as source media only. Supporting speakers use authentic video clips; "
           "unverified or unnamed portrait roles are never auto-overlaid.")
    else:
     # Eligible role becomes a dormant candidate. Actual SRT/script relevance is checked
     # at display time, so footage can be uploaded BEFORE the narration and script.
     ensure_ids(p['people'])
     who=row.get('person') or row.get('role')
     person=next((x for x in p['people'] if x.get('sheet_source')==row.get('source_id') or x.get('name','').casefold()==who.casefold()),None)
     if person is None:
      person={'id':new_person_id(),'name':who,'role':row.get('role',''),'aliases':[],'short_names':False,'show':False};p['people'].append(person)
     if row.get('role'):person['role']=row['role']
     person['sheet_source']=row.get('source_id')
     if row.get('person'):
      known={x.casefold() for x in person.get('aliases') or []}
      # "Cherie L. May" is said "Cherie May": the name without its middle initials counts too.
      plain=' '.join(w for w in row['person'].split() if not re.fullmatch(r"[A-Za-z]\.?",w))
      extra=[plain] if plain!=row['person'] and len(plain.split())>=2 else []
      # Only the middle-initial omission is a deterministic complete-name alias.
      # Fuzzy SRT spelling guesses require human approval before they can trigger a card.
      suggested=srt_spellings(p,row['person'])+(srt_spellings(p,plain) if extra else [])
      person['suggested_aliases']=[x for x in suggested if x.casefold() not in known]
      for x in extra:
       if x.casefold() not in known and x.casefold()!=row['person'].casefold():known.add(x.casefold());person['aliases']=list(person.get('aliases') or [])+[x]
     import person_overlays as _po
     gallery=_po.person_photos(person)
     mug=_po.is_mugshot(' '.join(str(row.get(k) or '') for k in ('description','role','person')))
     duplicate=any(row.get('source_id') and x.get('source_id')==row.get('source_id') for x in gallery)
     if duplicate:
      note=f'{name} was already attached to {who}; existing photo set preserved.'
     elif len(gallery)>=_po.MAX_PERSON_PHOTOS:
      note=f'{who} already has five photos. {name} remains in project Photos; choose one to replace manually.'
     elif min(dims)>=120:
      (root/'people').mkdir(exist_ok=True);copy=root/'people'/(uid()+ext);_sh.copyfile(dest,copy)
      entry={'path':copy.relative_to(root).as_posix(),'name':name,'dimensions':dims,'uploaded':time.time(),
             'asset_id':aid,'source':row.get('url',''),'source_id':row.get('source_id'),
             'sheet_line':row.get('line'),'mugshot':mug,
             'note':'From the footage sheet. Identity and reuse rights remain the user’s responsibility.'}
      # New non-booking photos precede existing booking photographs, but never
      # destroy them. A sheet import must not erase a manually approved gallery.
      if gallery and gallery[0].get('mugshot') and not mug:gallery.insert(0,entry)
      else:gallery.append(entry)
      person['photos']=gallery;person['photo']=gallery[0]
      note=f'Saved photo {len(gallery)} of up to five for {who}; photos will rotate across narration appearances.'
     else:note=f'{name} is too small to show full screen (under 120 pixels); it is in Photos only. Use a bigger photo for {who}.'
   from approval import auto_approve_upload
   auto_approve_upload(p,asset)
   if p.get('scenes') or p.get('documentary_beat_review'):p['timeline_needs_rebuild']=True
   save(p)
 except Exception:
  dest.unlink(missing_ok=True);raise
 if old_paths:remove_local_files(root,[x for x in old_paths if x.exists()])
 row['filename']=name;row['register_note']=note    # shown in the importer row
 try:schedule_auto_build(pid,0.6)
 except Exception:pass
 return aid

def register_downloaded_video(pid,row,path,manifest='',analyse=None):
 """Import one finished download as row['filename'] (S01.mp4 ...). Raises ValueError with a reason."""
 root=folder(pid);path=Path(path)
 # Never touch a project while it is exporting; wait for the export to finish.
 while busy(pid):time.sleep(5)
 import perflog
 with perflog.timed('import.probe',file=row.get('filename')):info=probe(path)
 if not info.get('has_video') or not info.get('duration'):raise ValueError('The downloaded file has no playable video. Retry, or try another quality.')
 with perflog.timed('import.faststart_remux',file=row.get('filename'),bytes=path.stat().st_size):make_fast_start(path)     # our own downloaded copy, so it is made seekable in place
 dest=root/'sources'/(uid()+'.mp4');dest.parent.mkdir(exist_ok=True);os.replace(path,dest)
 name=row['filename'];old_paths=[]
 try:
  with LOCKS[pid]:
   p=load(pid);matches=_video_matches(p,name)
   if matches and not row.get('replace') and not all(_same_link(a.get('provenance'),row) for a in matches):
    raise ValueError(f'{name} is already in this production. Choose Replace to download over it.')
   duration=info['duration'];dims=[int(info['width']),int(info['height'])] if info.get('width') and info.get('height') else None
   aid=matches[0]['id'] if matches else uid()
   asset={'id':aid,'name':name,'original_name':name,'path':dest.relative_to(root).as_posix(),'kind':'video','duration':duration,'dimensions':dims,
          'source':row.get('url',''),'people':[],'category':'broll' if row.get('media')=='broll' else 'general','verified':False,'rights':'unreviewed','notes':row.get('description',''),'revision':uid(),
          'provenance':{'kind':'youtube' if row.get('video_id') else 'web','media':row.get('media','video'),'description':row.get('description',''),'window':row.get('window'),'source_id':row.get('source_id'),'url':row.get('url'),'video_id':row.get('video_id'),'title':row.get('title',''),
                        'provider':row.get('provider','yt-dlp'),'sheet':manifest,'downloaded':time.time(),
                        'note':'Downloaded at the user’s request. Use and publication rights are the user’s own responsibility; not verified.'}}
   if matches:
    # Same rules as replacing an upload by name: scenes using the old file are flagged for review.
    ids={a['id'] for a in matches};related=[a for a in p['assets'] if (a.get('derived_from') or {}).get('asset_id') in ids]
    for item in related:
     item['verified']=False;item['derived_from']['source_replaced']=True
     if item.get('approval_record'):item['approval_record']['active']=False
    derived={a['id'] for a in related}
    for scene in p['scenes']:
     old=scene.get('asset_id')
     if old not in ids|derived:continue
     scene['approved']=False;scene['source_replacement_pending']=name;scene.pop('thumbnail',None)
     length=(scene['frame_out']-scene['frame_in'])/30
     if old in derived or float(scene.get('in_s') or 0)+length>duration+.001:
      scene['review_previous_asset_id']=old;scene['asset_id']=None
      scene['replacement_issue']='The replacement video is too short for this shot, or this shot used a frame derived from the previous upload.'
     else:scene['asset_id']=aid;scene.pop('replacement_issue',None)
    p['assets']=[a for a in p['assets'] if a['id'] not in ids]+[asset]
    p['source_bindings']={k:(aid if v in ids else v) for k,v in (p.get('source_bindings') or {}).items()}
    kept={a.get('path') for a in p['assets']};old_paths=[root/a['path'] for a in matches if a.get('path') and a['path'] not in kept]
   else:p['assets'].append(asset)
   from approval import auto_approve_upload
   auto_approve_upload(p,asset)
   if p.get('scenes') or p.get('documentary_beat_review'):p['timeline_needs_rebuild']=True
   save(p)
 except Exception:
  dest.unlink(missing_ok=True);raise
 try:queue_proxy(pid,p,dest)
 except Exception:app.logger.exception('Could not queue an editing copy for %s',name)
 if old_paths:remove_local_files(root,old_paths)
 try:
  from automatic import maybe_queue
  maybe_queue(sys.modules[__name__],p)
 except Exception:app.logger.exception('Automatic study could not be queued after a download.')
 if analyse is None:
  analyse = os.environ.get('STORYROOM_UNDERSTANDING_AUTO', '1') == '1'
 if analyse:
  try:
   from local_understanding import enqueue
   enqueue(root, aid, dest, 'video', duration)
  except Exception:
   app.logger.exception('Could not queue speech and scene analysis after download.')
 return aid

def youtube_report(pid):
 import footage_downloader as fd
 root=folder(pid);state=fd.load_state(root);active=fd.running(pid)
 if state and not active and fd.recover(state):fd.save_state(root,state)
 p=load(pid)
 try:check=fd.script_check(state,(p.get('production_script') or {}).get('text',''),p.get('assets') or [])
 except Exception:check=None
 return {'state':state,'summary':fd.summary(state) if state else None,'running':active,'tool':ytdlp_status(),'script_check':check,
         'apify':fd.ApifyProvider.status(),'install':{k:_YTDLP_INSTALL[k] for k in ('status','error','finished')}|{'log':_YTDLP_INSTALL['log'][-12:]},
         'options':{'analyse_default':os.environ.get('STORYROOM_UNDERSTANDING_AUTO', '1')=='1','qualities':list(fd.QUALITIES),'browsers':list(fd.BROWSERS)}}

def start_youtube_job(pid):
 import footage_downloader as fd
 root=folder(pid);state=fd.load_state(root)
 if not state:raise BadRequest('Upload a footage sheet first.')
 if not any(r['valid'] for r in state['rows']):raise BadRequest('The sheet has no links to download.')
 provider=state['options'].get('provider','yt-dlp')
 if provider=='yt-dlp' and not ytdlp_status(True)['available']:raise BadRequest('yt-dlp is not installed yet. Click "Install yt-dlp" first.')
 manifest=state.get('manifest','')
 def local_copy(row):
  with LOCKS[pid]:
   p=load(pid)
  for a in p['assets']:
   pr=a.get('provenance') or {}
   if _same_link(pr,row) and (root/a.get('path','')).is_file():return root/a['path'],pr.get('title','')
  return None
 job=fd.DownloadJob(pid,root,lambda row,path:register_download(pid,row,path,manifest,analyse=state['options'].get('analyse')),lambda row:download_existing(pid,row),local_copy=local_copy)
 try:job.start()
 except RuntimeError as e:raise BadRequest(str(e))

@app.get('/api/projects/<pid>/youtube')
def youtube_view(pid):
 folder(pid);return jsonify(youtube_report(pid))

@app.post('/api/projects/<pid>/youtube/sheet')
def youtube_sheet(pid):
 import footage_downloader as fd
 root=folder(pid);load(pid)
 if fd.running(pid):raise BadRequest('Downloads are running. Stop them before uploading a new sheet.')
 f=request.files.get('file')
 if not f or not f.filename:raise BadRequest('Choose your Markdown footage sheet.')
 if Path(f.filename).suffix.lower() not in ('.md','.markdown','.txt'):raise BadRequest('Upload the footage sheet as a .md (Markdown) or .txt file.')
 raw=f.read(2_000_001)
 if len(raw)>2_000_000:raise BadRequest('The footage sheet must be under 2 MB.')
 try:text=raw.decode('utf-8-sig')
 except UnicodeDecodeError:text=raw.decode('latin-1')
 parsed=fd.parse_manifest(text)
 if not parsed['entries']:raise BadRequest('No source IDs with YouTube links were found. Each source needs an ID like SRC-01 and its YouTube link on the same line (or the line below).')
 old=fd.load_state(root) or {}
 state=fd.new_state(Path(f.filename).name,parsed,old.get('options'))
 # Every NEW sheet uses four parallel downloads immediately, regardless of an old project's saved two.
 state['options']['concurrency']=4
 state['options']['auto_start']=True
 if 'analyse' in request.form:state['options']['analyse']=request.form['analyse']=='1'
 (root/'downloads').mkdir(exist_ok=True);(root/'downloads'/'footage_sheet.md').write_text(text,encoding='utf-8')
 fd.save_state(root,state)
 started=False;reason=''
 if state['options'].get('auto_start',True) and parsed['counts']['valid']:
  try:start_youtube_job(pid);started=True
  except BadRequest as e:reason=e.description
 report=youtube_report(pid);report['started']=started;report['not_started_reason']=reason
 return jsonify(report)

@app.post('/api/projects/<pid>/youtube/start')
def youtube_start(pid):
 """Start, resume, or retry. Completed files are never downloaded again."""
 import footage_downloader as fd
 root=folder(pid);d=request.get_json(silent=True) or {}
 with LOCKS[pid]:
  state=fd.load_state(root)
  if not state:raise BadRequest('Upload a footage sheet first.')
  if fd.running(pid):raise BadRequest('Downloads are already running.')
  only=d.get('source_id')
  for row in state['rows']:
   if not row['valid']:continue
   if only and row['source_id']!=only:continue
   if row['status'] in fd.REDO:row.update(status=fd.WAITING,error='',progress=0,phase='',attempts=0)
  fd.save_state(root,state)
 start_youtube_job(pid);return jsonify(youtube_report(pid))

@app.post('/api/projects/<pid>/youtube/replace/<source_id>')
def youtube_replace(pid,source_id):
 import footage_downloader as fd
 root=folder(pid)
 if fd.running(pid):raise BadRequest('Wait for the current downloads to finish, then choose Replace.')
 with LOCKS[pid]:
  state=fd.load_state(root)
  row=next((r for r in (state or {}).get('rows',[]) if r['source_id']==source_id and r['valid']),None)
  if not row:raise NotFound('That source is not in the footage sheet.')
  row.update(replace=True,status=fd.WAITING,error='',note='',progress=0);fd.save_state(root,state)
 start_youtube_job(pid)
 return jsonify(youtube_report(pid))

@app.post('/api/projects/<pid>/youtube/cancel')
def youtube_cancel(pid):
 import footage_downloader as fd
 with fd.JOBS_LOCK:job=fd.JOBS.get(pid)
 if job and job.thread.is_alive():job.stop()
 return jsonify(youtube_report(pid))

@app.post('/api/projects/<pid>/youtube/options')
def youtube_options(pid):
 import footage_downloader as fd
 root=folder(pid);d=request.get_json(silent=True) or {}
 if fd.running(pid):raise BadRequest('Settings apply to the next download run. Wait for this one to finish or stop it first.')
 with LOCKS[pid]:
  state=fd.load_state(root)
  if not state:raise BadRequest('Upload a footage sheet first.')
  opts=state['options']
  if 'quality' in d:
   if d['quality'] not in fd.QUALITIES:raise BadRequest('Quality must be 720, 1080 or best.')
   opts['quality']=d['quality']
  if 'cookies_from_browser' in d:
   if d['cookies_from_browser'] not in fd.BROWSERS:raise BadRequest('Choose a supported browser.')
   opts['cookies_from_browser']=d['cookies_from_browser']
  if 'concurrency' in d:
   if type(d['concurrency']) is not int or not 1<=d['concurrency']<=4:raise BadRequest('Download between 1 and 4 videos at a time.')
   opts['concurrency']=d['concurrency']
  if 'auto_start' in d:opts['auto_start']=bool(d['auto_start'])
  if 'provider' in d:
   if d['provider'] not in fd.PROVIDERS:raise BadRequest('Unknown downloader.')
   opts['provider']=d['provider']
  fd.save_state(root,state)
 return jsonify(youtube_report(pid))

@app.delete('/api/projects/<pid>/youtube')
def youtube_clear(pid):
 import footage_downloader as fd
 root=folder(pid)
 if fd.running(pid):raise BadRequest('Stop the downloads first.')
 fd.state_path(root).unlink(missing_ok=True);shutil.rmtree(root/'downloads'/'tmp',ignore_errors=True)
 return jsonify(youtube_report(pid))

@app.post('/api/youtube/install')
def youtube_install():
 """Install or update yt-dlp into the app's private folder, in the background."""
 import footage_downloader as fd
 if _YTDLP_INSTALL['status']=='running':raise BadRequest('yt-dlp is already being installed.')
 _YTDLP_INSTALL.update(status='running',log=[],error='',finished=None)
 def work():
  try:
   fd.install_ytdlp(True,lambda line:_YTDLP_INSTALL['log'].append(line[-300:]))
   ytdlp_status(True);_YTDLP_INSTALL.update(status='done')
  except Exception as e:_YTDLP_INSTALL.update(status='error',error=str(e)[:500])
  finally:_YTDLP_INSTALL['finished']=time.time()
 threading.Thread(target=work,daemon=True,name='yt-dlp-install').start()
 return jsonify({'status':'running'})

@app.get('/api/youtube/install')
def youtube_install_status():
 return jsonify({'install':{k:_YTDLP_INSTALL[k] for k in ('status','error','finished')}|{'log':_YTDLP_INSTALL['log'][-12:]},'tool':ytdlp_status()})

# ---- Visual plan: a picture for every narration line that shows what is said ----
# visual_plan.py does the matching; these routes run it, keep the result for review,
# let the user swap a pick, and apply it as the production script. Applying never
# deletes the user's script: it is kept as visual_plan_source and can be restored.













_STATUS_SLOW={'caps':None,'probing':False,'usage':None,'usage_at':0.0,'usage_busy':False}
_STATUS_GUARD=threading.Lock()


def _probe_encoders():
 import resources
 try:_STATUS_SLOW['caps']=resources.capabilities()
 except Exception as error:_STATUS_SLOW['caps']={'error':str(error)}
 finally:_STATUS_SLOW['probing']=False

def _measure_cache():
 try:_STATUS_SLOW['usage']=SETTINGS.cache_store()[0].usage();_STATUS_SLOW['usage_at']=time.time()
 except Exception:pass
 finally:_STATUS_SLOW['usage_busy']=False

@app.get('/api/system/status')
def system_status():
 """What the machine is doing, what is queued, and what the queue can do.

 The dialog polls this every two seconds, so it never waits on slow work: the encoder
 test runs once in the background, and the cache size (a walk over every cached file)
 is measured in the background at most every 30 seconds. Until they arrive the dialog
 shows the queue and says the rest is still being checked."""
 with _STATUS_GUARD:
  if _STATUS_SLOW['caps'] is None and not _STATUS_SLOW['probing']:
   _STATUS_SLOW['probing']=True;threading.Thread(target=_probe_encoders,daemon=True).start()
  if time.time()-_STATUS_SLOW['usage_at']>30 and not _STATUS_SLOW['usage_busy']:
   _STATUS_SLOW['usage_busy']=True;threading.Thread(target=_measure_cache,daemon=True).start()
 caps=_STATUS_SLOW['caps'] or {'checking':True}
 usage=_STATUS_SLOW['usage'] or {'kinds':{},'total_bytes':0,'checking':True}
 return jsonify({'queue':QUEUE.snapshot(),'encoders':caps,
                 'settings':SETTINGS.as_dict(),
                 'disk':settings_store.disk_report(SETTINGS.cache_store()[0]),
                 'cache':usage})

# ---- Local media analysis toolkit (explicit installation only) ----
@app.get('/api/media-tools')
def media_tools_status():
    return jsonify(media_tools.status(refresh=request.args.get('refresh') == '1'))

@app.post('/api/media-tools/install')
def media_tools_install():
    payload = request.get_json(silent=True) or {}
    try:
        result = media_tools.install(str(payload.get('tool') or ''))
    except (RuntimeError, ValueError) as error:
        raise BadRequest(str(error))
    return jsonify(result), 202

@app.get('/api/projects/<pid>/assets/<aid>/media-info')
def media_tools_asset_metadata(pid, aid):
    """Run FFprobe on an uploaded source file; never accept a browser-supplied path."""
    p = snapshot(pid)
    asset = next((a for a in p['assets'] if a.get('id') == aid), None)
    if not asset or asset.get('kind') not in ('video', 'audio'):
        raise NotFound('Source media not found.')
    root = folder(pid).resolve()
    source = (root / str(asset.get('path') or '')).resolve()
    if not source.is_relative_to(root) or not source.is_file():
        raise NotFound('Source media not found.')
    try:
        result = media_tools.read_metadata(source)
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as e:
        raise BadRequest(str(e))
    # Return relevant metadata, rather than absolute machine paths or other tags.
    streams = [{'type': x.get('codec_type'), 'codec': x.get('codec_name'),
                'width': x.get('width'), 'height': x.get('height'),
                'fps': x.get('avg_frame_rate'), 'sample_rate': x.get('sample_rate'),
                'channels': x.get('channels')}
               for x in result.get('streams') or []]
    return jsonify({'filename': asset.get('original_name') or asset.get('name'),
                    'duration_s': (result.get('format') or {}).get('duration'),
                    'streams': streams})

@app.get('/api/speech/setup')
def speech_setup_status():
 """Whether local speech is ready, and what is missing if not."""
 import speech_setup
 state=speech_setup.status()
 state['progress']=speech_setup.install_progress()
 return jsonify(state)

@app.post('/api/speech/setup')
def speech_setup_start():
 """Download and verify the missing half. Only ever runs because someone asked."""
 import speech_setup
 d=request.get_json(silent=True) or {}
 result=speech_setup.start(str(d.get('kind') or 'auto'))
 if not result.get('started'):raise BadRequest(result.get('reason') or 'Nothing to install.')
 return jsonify(result),202

@app.get('/api/settings')
def get_settings():
 return jsonify(SETTINGS.as_dict())

@app.patch('/api/settings')
def update_settings():
 d=request.get_json(silent=True) or {}
 before=SETTINGS.load()
 try:saved=SETTINGS.save(d)
 except ValueError as e:raise BadRequest(str(e))
 # Changing the quality of the editing copies should actually change them. Without
 # this the new setting would apply only to future uploads, and every existing clip
 # would keep playing at the old quality with no explanation.
 requeued=0
 if saved.get('proxies_enabled') and saved.get('proxy_quality')!=before.get('proxy_quality'):
  for project in PROJECTS.iterdir():
   if not (project/'project.json').exists():continue
   try:
    p=json.loads((project/'project.json').read_text())
   except (OSError,ValueError):continue
   for asset in p.get('assets') or []:
    if asset.get('kind')!='video':continue
    source=project/asset['path']
    if not source.is_file():continue
    try:
     if queue_proxy(p.get('id') or project.name,p,source):requeued+=1
    except Exception:pass
 fresh=SETTINGS.as_dict();fresh['disk']=settings_store.disk_report(SETTINGS.cache_store()[0])
 fresh['proxies_requeued']=requeued
 return jsonify(fresh)

@app.get('/api/cache')
def cache_usage():
 store,detail=SETTINGS.cache_store()
 return jsonify({'usage':store.usage(),'disk':settings_store.disk_report(store),
                 'detail':detail,'root':str(store.root)})

@app.post('/api/cache/cleanup')
def cache_cleanup():
 """Remove cached entries that have not been used recently.

 Only this app's cache directories are touched. Originals live in sources/ and
 assets/, which no cache routine can reach.
 """
 store,_detail=SETTINGS.cache_store()
 d=request.get_json(silent=True) or {}
 if d.get('all') is True:removed=store.clear()
 else:removed=store.cleanup(keep_seconds=int(SETTINGS.load().get('keep_cache_days') or 14)*86400)
 usage=store.usage();_STATUS_SLOW.update(usage=usage,usage_at=time.time())
 return jsonify({'removed':removed,'usage':usage,
                 'disk':settings_store.disk_report(store)})

@app.post('/api/queue/pause')
def queue_pause():
 d=request.get_json(silent=True) or {}
 return jsonify(QUEUE.snapshot()) if QUEUE.pause(d.get('id')) else (jsonify({'error':'That job is not running.'}),400)

@app.post('/api/queue/resume')
def queue_resume():
 d=request.get_json(silent=True) or {}
 return jsonify(QUEUE.snapshot()) if QUEUE.resume(d.get('id')) else (jsonify({'error':'That job is not paused.'}),400)

@app.post('/api/queue/cancel')
def queue_cancel():
 d=request.get_json(silent=True) or {}
 if not d.get('id'):raise BadRequest('Choose a job to cancel.')
 if not QUEUE.cancel(d['id']):raise BadRequest('That job has already finished.')
 return jsonify(QUEUE.snapshot())

@app.post('/api/queue/retry')
def queue_retry():
 d=request.get_json(silent=True) or {}
 if not d.get('id'):raise BadRequest('Choose a job to retry.')
 if not QUEUE.retry(d['id']):raise BadRequest('Only a failed, cancelled or interrupted job can be retried.')
 return jsonify(QUEUE.snapshot())

@app.post('/api/queue/clear')
def queue_clear():
 removed=QUEUE.clear_finished()
 return jsonify({'removed':removed,'queue':QUEUE.snapshot()})

@app.post('/api/projects/<pid>/proxies')
def build_proxies(pid):
 """Queue editing copies for every video in this production."""
 with LOCKS[pid]:
  editable(pid);p=load(pid);root=folder(pid)
  queued=[]
  for asset in p['assets']:
   if asset.get('kind')!='video':continue
   source=root/asset['path']
   if not source.is_file():continue
   job=queue_proxy(pid,p,source)
   if job:queued.append({'asset':asset['id'],'job':job.id})
  store,_detail=SETTINGS.cache_store()
  return jsonify({'queued':queued,'queue':QUEUE.snapshot(),
                  'usage':store.usage()}),202

@app.get('/api/projects/<pid>/proxies')
def proxy_status(pid):
 p=load(pid);root=folder(pid);store,_detail=SETTINGS.cache_store()
 items=[]
 for asset in p['assets']:
  if asset.get('kind')!='video':continue
  source=root/asset['path']
  meta=proxy_module.metadata(store,source) if source.is_file() else None
  items.append({'asset':asset['id'],'name':asset.get('original_name') or asset.get('name'),
                'ready':bool(meta),'height':(meta or {}).get('height'),
                'quality':(meta or {}).get('quality')})
 return jsonify({'proxies':items,'enabled':SETTINGS.load().get('proxies_enabled'),
                 'quality':SETTINGS.load().get('proxy_quality')})

@app.get('/api/projects/<pid>/history')
def project_history_list(pid):
 import project_history
 root=folder(pid)
 return jsonify({'versions':project_history.versions(root)[:40],
                 'size_bytes':project_history.size_bytes(root)})

@app.post('/api/projects/<pid>/history/<ident>/restore')
def project_history_restore(pid,ident):
 import project_history
 with LOCKS[pid]:
  editable(pid);p=load(pid);root=folder(pid)
  state=project_history.restore(root,ident,p)
  if state is None:raise NotFound('That saved version is no longer available.')
  # Keep identity and timestamps of the project being recovered, and nothing else.
  state['id']=p['id']
  save(state)
  return jsonify(public(load(pid)))

@app.delete('/api/projects/<pid>/history')
def project_history_clear(pid):
 import project_history
 with LOCKS[pid]:
  editable(pid);removed=project_history.clear(folder(pid))
  return jsonify({'cleared':removed})

@app.get('/api/projects/<pid>/imports/<key>')
def import_status(pid,key):
 from import_status import token,get
 folder(pid)
 if not token(key):raise NotFound('Import not found.')
 return jsonify(get(pid,key))

@app.delete('/api/projects/<pid>/imports/<key>')
def cancel_import(pid,key):
 from import_status import token,cancel
 folder(pid)
 if not token(key):raise NotFound('Import not found.')
 return jsonify(cancel(pid,key))

@app.post('/api/projects/<pid>/media-stream')
@app.post('/api/projects/<pid>/upload')
def upload(pid):
 from import_status import token,update
 key=token(request.headers.get('X-Upload-ID',''));folder(pid);update(pid,key,'waiting_for_project')
 try:
  limit=MAX_VIDEO_BYTES if request.path.endswith('/media-stream') else 2*1024**3
  if request.content_length is not None and request.content_length>limit:raise RequestEntityTooLarge('Video streaming supports up to 8 GB per MP4/MOV; other uploads support up to 2 GB per request.')
  return perform_upload(pid,key)
 except Exception as e:
  update(pid,key,'error',detail=str(getattr(e,'description',e))[:500]);raise

def mp4_moov_at_end(path):
 """True when the MP4 index sits after the media, so a player must fetch it all.

 A browser needs the moov atom before it can decode or seek. When it is written
 last, every seek re-reads the file from the end and the monitor sits black --
 which is what happened with 9 of the 11 source clips in one project.
 """
 import struct
 try:
  size=path.stat().st_size
  with open(path,'rb') as handle:
   pos=0
   while pos<size-8:
    handle.seek(pos);header=handle.read(8)
    if len(header)<8:return False
    box=struct.unpack('>I',header[:4])[0];kind=header[4:8]
    if box==1:box=struct.unpack('>Q',handle.read(8))[0]
    if box<=0:return False
    if kind==b'moov':return pos>size*0.5
    pos+=box
 except OSError:return False
 return False

def make_fast_start(path,out=None):
 """Write a copy with the index first. Never changes a frame or a timestamp.

 The uploaded file is left exactly as it arrived -- preserving the source bytes
 is a promise the editor already makes -- and the seekable copy is cached beside
 it. Best effort: a file that cannot be remuxed is simply served as it is.
 """
 import imageio_ffmpeg
 if not mp4_moov_at_end(path):return False
 tmp=out if out is not None else path.with_name(path.stem+'.faststart'+path.suffix)
 try:
  result=subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-v','error','-y','-i',str(path),
    '-map','0','-c','copy','-movflags','+faststart',str(tmp)],
    stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=900)
  if result.returncode!=0 or not tmp.exists() or tmp.stat().st_size<1024:
   tmp.unlink(missing_ok=True);return False
  if out is None:tmp.replace(path)
  return True
 except (OSError,subprocess.SubprocessError):
  tmp.unlink(missing_ok=True);return False

def perform_upload(pid,key=''):
 from import_status import update,check,project_lock,save_local
 with project_lock(LOCKS[pid]):
  editable(pid);p=load(pid);root=folder(pid);check(pid,key);update(pid,key,'receiving')
  if request.path.endswith('/media-stream'):
   if request.mimetype!='application/octet-stream':raise BadRequest('Use the editor video-stream upload control.')
   name=request.args.get('name','')
   if Path(name).suffix.lower() not in ['.mp4','.mov']:raise BadRequest('Direct streaming accepts MP4 or MOV video.')
   f=SimpleNamespace(filename=name,stream=request.stream);kind='asset'
  else:f=request.files.get('file');kind=request.form.get('kind')
  check(pid,key)
  if not f:raise BadRequest('Choose a file.')
  ext=Path(f.filename or '').suffix.lower();update(pid,key,'reading_document',filename=f.filename)
  if kind=='srt':
   try:
    raw=f.read(4_000_001)
    if len(raw)>4_000_000:raise BadRequest('SRT files must be under 4 MB.')
    text=raw.decode('utf-8-sig')
   except UnicodeDecodeError:raise BadRequest('SRT must be UTF-8 text.')
   blocks=parse_srt(text)
   if p['scenes'] and request.form.get('replace')!='yes':raise BadRequest('Replacing the SRT invalidates the current storyboard. Confirm replacement first.')
   # A replacement is compared with the SRT it replaces, so a "names only" correction
   # that also moved a timing or reworded a line is shown on the SRT card at once.
   import srt_compare
   compared=srt_compare.compare(p['srt']['blocks'],blocks) if (p.get('srt') or {}).get('blocks') else None
   if compared is not None:compared['previous_name']=p['srt'].get('name') or 'the previous SRT'
   (root/'inputs/captions.srt').write_bytes(raw);p['srt']={'blocks':blocks,'name':f.filename};p['scenes']=[];p.pop('srt_recovery',None);p.pop('srt_removed',None)
   p['timeline_needs_rebuild']=True
   if compared is not None:p['srt']['compared']=compared
  elif kind=='srt_block_map':
   from edl import parse,srt_signature
   expected_srt=request.form.get('expected_srt_signature')
   if expected_srt and (not p.get('srt') or expected_srt!=srt_signature(p)):
    raise BadRequest('The SRT changed while you were editing the block map. Reopen the editor to review the current SRT.')
   try:
    from automatic import link_frame_csv
    payload=f.read(4_000_001);payload=link_frame_csv(payload,p) if ext=='.csv' else payload
    beats=parse(payload,ext)
   except (ValueError,UnicodeError) as e:raise BadRequest('SRT block map: '+str(e))
   if not all(row.get('map_type')=='srt_block' for row in beats):raise BadRequest('Choose a block-map CSV with block,start,end,beat,media_file,source_in,source_out columns.')
   numbers=[row['srt_blocks'][0] for row in beats]
   if numbers!=list(range(1,len(numbers)+1)):raise BadRequest('Block map must contain unique ordered SRT blocks 1 through its final block.')
   p['srt_block_map']={'name':f.filename,'beats':beats,'schema_version':1,'based_on_srt':srt_signature(p) if p.get('srt') else None,'import_notes':list(dict.fromkeys(note for row in beats for note in row.get('import_notes',[]))),'import_blockers':[{'beat_id':row.get('beat_id') or row.get('plan_row_id',''),'note':note} for row in beats for note in row.get('import_blockers',[])]}
   write(root/'inputs/srt_block_map.json',p['srt_block_map'])
   for scene in p['scenes']:scene['approved']=False
  elif kind=='production_script':
   if ext not in ['.txt','.md','.json','.docx']:raise BadRequest('Upload a TXT, Markdown, JSON or DOCX production script.')
   from production import read_document
   try:text=read_document(f,ext)
   except Exception as e:raise BadRequest('The production script could not be read: '+str(e)[:200])
   from documentary_beats import is_strict_pipeline_script
   (root/'inputs/production_script.txt').write_text(text,encoding='utf-8');p['production_script']={'name':f.filename,'text':text,'execution_mode':'pipeline_v5_strict' if is_strict_pipeline_script(text) else 'legacy'}
   if p.get('scenes') or p.get('documentary_beat_review'):p['timeline_needs_rebuild']=True
   # A new script replaces whatever a visual plan was built from.
   p.pop('visual_plan_source',None);p.pop('visual_plan_applied',None)
   from document_plan import srt_outline_blocks
   recovered,outline_problems,outline_notes=srt_outline_blocks(text)
   if recovered and not p.get('srt'):
    p['srt']={'blocks':recovered,'name':f.filename+' · narration table','recovered_from':f.filename};p.pop('srt_removed',None)
    (root/'inputs/captions.srt').write_text('\n\n'.join('%d\n%s --> %s\n%s'%(b['number'],srt_stamp(b['start_ms']),srt_stamp(b['end_ms']),b['text']) for b in recovered),encoding='utf-8')
    p['srt_recovery']={'source':f.filename,'blocks':len(recovered),'total_s':recovered[-1]['end_ms']/1000,'note':'Narration blocks were recovered verbatim from a table in the production script. Wording, order and timing were copied, not rewritten; a separate .srt can still replace this.','adjustments':outline_notes}
   elif recovered and p.get('srt'):
    p['srt_recovery']={'source':f.filename,'blocks':len(recovered),'total_s':recovered[-1]['end_ms']/1000,'skipped':True,'note':'This production script also contains a narration block table. The separate .srt already uploaded is used; upload the table as .srt if you want it instead.'}
   elif outline_problems:
    p['srt_recovery']={'source':f.filename,'blocks':0,'problems':outline_problems[:5],'note':'A narration block table was found but not used; the reported problems would require altering timing.'}
   for scene in p['scenes']:scene['approved']=False
  elif kind=='voiceover':
   if ext not in ['.mp3','.wav','.m4a','.aac','.flac','.ogg']:raise BadRequest('Use MP3, WAV, M4A, AAC, FLAC or OGG narration.')
   dest=root/'inputs'/('pending'+ext);update(pid,key,'saving')
   try:
    save_local(f,dest,pid,key);check(pid,key);update(pid,key,'checking_metadata');info=probe(dest);check(pid,key)
   except Exception as e:
    dest.unlink(missing_ok=True)
    if isinstance(e,BadRequest):raise
    raise BadRequest(str(e))
   # `probe` reports duration 0 when ffmpeg finds no Duration line -- a container it
   # cannot read the length of, or a file still being written. Storing that 0 makes
   # the narration look present but zero seconds long, and every later step that
   # builds an edit clock then rejects it with "Narration duration must be a time in
   # seconds." Refuse it here instead, where the user is still looking at the upload
   # button and can pick a different export of the same file.
   if not info['has_audio']:dest.unlink();raise BadRequest('The uploaded file has no decodable audio.')
   if not info['duration']:
    dest.unlink();raise BadRequest('This file\'s length could not be read, so it cannot be used as narration. Re-export it as MP3 or M4A and upload it again.')
   for old in (root/'inputs').glob('voiceover.*'):old.unlink()
   final=root/'inputs'/('voiceover'+ext);dest.replace(final);p['voiceover']={'name':f.filename,'path':final.relative_to(root).as_posix(),'duration':info['duration'],'revision':uid()}
   for scene in p['scenes']:scene['approved']=False
   if p.get('scenes') or p.get('documentary_beat_review'):p['timeline_needs_rebuild']=True
  elif kind=='asset':
   if ext not in ['.mp4','.mov','.jpg','.jpeg','.png','.webp']:raise BadRequest('Use MP4/MOV video or JPG/PNG/WebP photographs.')
   photo=ext in ['.jpg','.jpeg','.png','.webp'];name=Path(f.filename).name
   # Only identical video filenames replace each other; source numbers alone are not identities.
   matches=[] if photo else [a for a in p['assets'] if a.get('kind')=='video' and not a.get('derived_from') and str(a.get('original_name') or a.get('name') or '').casefold()==name.casefold()]
   replacement=None;old_paths=[]
   if matches:
    ids={a['id'] for a in matches};related=[a for a in p['assets'] if (a.get('derived_from') or {}).get('asset_id') in ids]
    removable(pid,ids|{a['id'] for a in related})
    import preview_render,scene_exports
    # A job may be rendering an older project revision but still reading these paths.
    with preview_render.GUARD: preview_busy=(preview_render.JOBS.get(pid) or {}).get('status') in ('running','queued')
    with scene_exports.GUARD: scene_export_busy=(scene_exports.JOBS.get(pid) or {}).get('status') in ('running','queued')
    if preview_busy or scene_export_busy:raise BadRequest('Wait for the current preview or scene export to finish before replacing footage.')
   aid=matches[0]['id'] if matches else uid();dest=root/('assets' if photo else 'sources')/(uid()+ext);update(pid,key,'saving')
   try:
    save_local(f,dest,pid,key);check(pid,key);update(pid,key,'checking_image' if photo else 'checking_metadata')
    if photo:
     with Image.open(dest) as im:im.verify()
     duration=0
     with Image.open(dest) as im:source_dims=[int(im.width),int(im.height)]
    else:
     info=probe(dest)
     if not info['has_video'] or not info['duration']:raise ValueError('No decodable video')
     duration=info['duration']
     source_dims=[int(info['width']),int(info['height'])] if info.get('width') and info.get('height') else None
    check(pid,key)
   except Exception as e:
    dest.unlink(missing_ok=True)
    if isinstance(e,BadRequest):raise
    raise BadRequest('Media check failed: '+str(e)[:350])
   # Source dimensions are recorded once, at upload, so the export page can say what
   # upscale factor a resolution actually needs instead of guessing from a filename.
   asset={'id':aid,'name':name,'original_name':name,'path':dest.relative_to(root).as_posix(),'kind':'image' if photo else 'video','duration':duration,'dimensions':source_dims,'source':'','people':[],'category':'general','verified':False,'rights':'unreviewed','notes':'','revision':uid()}
   if matches:
    duplicate_ids={a['id'] for a in matches};derived_ids={a['id'] for a in related};affected=0;unassigned=0
    # Derived images came from the old bytes: preserve them, but never keep them on the timeline as if they came from the replacement.
    for item in related:
     item['verified']=False;item['derived_from']['source_replaced']=True
     if item.get('approval_record'):item['approval_record']['active']=False
    for scene in p['scenes']:
     old_id=scene.get('asset_id')
     if old_id not in duplicate_ids|derived_ids:continue
     affected+=1;scene['approved']=False;scene['source_replacement_pending']=name;scene.pop('thumbnail',None)
     length=(scene['frame_out']-scene['frame_in']+(scene.get('transition_handle_frames',0) if transitions.is_transition(scene.get('transition')) else 0))/30
     if old_id in derived_ids or float(scene.get('in_s') or 0)+length>duration+.001:
      scene['review_previous_asset_id']=old_id;scene['asset_id']=None;unassigned+=1
      scene['replacement_issue']='The replacement video is too short for this shot, or this shot used a frame derived from the previous upload.'
     else:scene['asset_id']=aid;scene.pop('replacement_issue',None)
    p['assets']=[a for a in p['assets'] if a['id'] not in duplicate_ids]+[asset]
    p['source_bindings']={key:(aid if value in duplicate_ids else value) for key,value in (p.get('source_bindings') or {}).items()}
    kept={a.get('path') for a in p['assets']};old_paths=[root/a['path'] for a in matches if a.get('path') and a['path'] not in kept]
    from local_understanding import result_path
    old_paths += [result_path(root,x) for x in duplicate_ids|derived_ids]
    replacement={'name':name,'affected_scenes':affected,'unassigned_scenes':unassigned,'replaced_count':len(matches)}
   else:p['assets'].append(asset)
  else:raise BadRequest('Unknown import type.')
  if kind=='asset':
   if p.get('scenes') or p.get('documentary_beat_review'):p['timeline_needs_rebuild']=True
   from approval import auto_approve_upload
   auto_approve_upload(p,p['assets'][-1])
  if kind in ['srt','production_script']:
   from production import infer
   p['profile']=infer(p)['profile']
  update(pid,key,'indexing')
  # Report a script/file duration mismatch the moment the pieces are together,
  # instead of letting it surface later as a wall of per-beat errors.
  preflight=[]
  try:
   if p.get('edit_mode')=='documentary' and (p.get('production_script') or {}).get('text'):
    from documentary_script_diagnostics import diagnose
    report=diagnose(p,root)
    found=list(report.get('build_issues') or [])
    # The panel now reports what the plan will change as notes rather than as a
    # demand for a different file, so preflight has to read those too. The
    # source/file mismatch must still reach the browser on upload.
    found.extend(x.get('text','') if isinstance(x,dict) else x for x in report.get('build_notes') or [])
    preflight=[x for x in found if 'run past the end of the uploaded file' in x
               or 'is past the end of' in x
               or 'The audio is not the timeline the script describes' in x
               or 'script ends its narration at' in x
               or 'is missing or ambiguous' in x
               or 'but the uploaded narration' in x
               or 'cannot cover this' in x]
  except Exception:
   preflight=[]
  try:save(p)
  except Exception:
   if kind=='asset':dest.unlink(missing_ok=True)
   raise
  # Queue an editing copy. Never inline: an upload of a long 4K file must return as
  # soon as the bytes are on disk, and the encode waits for its turn. A failure here
  # must not fail the upload -- the original is already safely stored, and a proxy is
  # a convenience that can always be made later.
  if kind=='asset' and dest.suffix.lower() in ('.mp4','.mov'):
   try:queue_proxy(pid,p,dest)
   except Exception:app.logger.exception('Could not queue an editing copy for %s',dest.name)
  replacement_warnings=remove_local_files(root,old_paths) if kind=='asset' and old_paths else []
  from automatic import maybe_queue
  maybe_queue(sys.modules[__name__],p)
  # Automatic analysis only when explicitly enabled; it never delays the upload or
  # changes the authored SRT/storyboard. The manual control works independently.
  if os.environ.get('STORYROOM_UNDERSTANDING_AUTO','1')=='1':
   try:
    from local_understanding import enqueue
    if kind=='voiceover':enqueue(root,'narration',root/p['voiceover']['path'],'audio',p['voiceover']['duration'])
    elif kind=='asset' and not photo:enqueue(root,aid,dest,'video',duration)
   except Exception as e:app.logger.warning('Could not queue local understanding: %s',e)
  result=public(p)
  if preflight:result['script_preflight']=preflight
  if kind=='asset' and replacement:result['replaced_video']=replacement;result['replacement_warnings']=replacement_warnings
  result=jsonify(result);update(pid,key,'done');return result

def removable(pid, targets=()):
 editable(pid)
 from automatic import _QUEUE_LOCK, _PENDING
 with _QUEUE_LOCK:
  if pid in _PENDING:raise BadRequest('Wait for automatic assembly or rendering to finish before removing files.')
 from local_understanding import _GUARD, _RUNNING
 with _GUARD:
  if any((str(folder(pid)),target) in _RUNNING for target in targets):
   raise BadRequest('Wait for local analysis of this file to finish before removing it.')

def remove_local_files(root, paths):
 warnings=[]
 for path in paths:
  try:
   path=Path(path).resolve()
   if not path.is_relative_to(root.resolve()):raise ValueError('File is outside this project')
   path.unlink(missing_ok=True)
  except (OSError,ValueError) as e:warnings.append('Could not remove a local file: '+str(e))
 return warnings

@app.delete('/api/projects/<pid>/assets/<aid>')
def delete_asset(pid,aid):
 with LOCKS[pid]:
  p=load(pid);root=folder(pid);asset=next((a for a in p['assets'] if a['id']==aid),None)
  if not asset:raise NotFound('Media not found.')
  related=[asset]+[a for a in p['assets'] if (a.get('derived_from') or {}).get('asset_id')==aid]
  ids={a['id'] for a in related};removable(pid,ids)
  d=request.get_json(silent=True) or {}
  if d.get('confirm') is not True:raise BadRequest('Confirm removal of this file.')
  affected=[s for s in p['scenes'] if s.get('asset_id') in ids]
  if (affected or len(related)>1) and d.get('confirm_used') is not True:
   raise BadRequest('Confirm removal of the source and any extracted frames; affected storyboard scenes will become unassigned.')
  remaining=[a for a in p['assets'] if a['id'] not in ids]
  remaining_paths={a.get('path') for a in remaining}
  paths=[root/a['path'] for a in related if a.get('path') and a['path'] not in remaining_paths]
  from local_understanding import result_path
  paths += [result_path(root, a['id']) for a in related]
  p['assets']=remaining
  p['source_bindings']={name:asset_id for name,asset_id in (p.get('source_bindings') or {}).items() if asset_id not in ids}
  for scene in affected:scene['asset_id']=None;scene['approved']=False
  save(p)
  warnings=remove_local_files(root,paths)
  result=public(p);result['removal_warnings']=warnings
  return jsonify(result)

@app.delete('/api/projects/<pid>/inputs/<kind>')
def delete_input(pid,kind):
 if kind not in ('voiceover','srt','production_script'):raise NotFound('Input not found.')
 with LOCKS[pid]:
  p=load(pid);root=folder(pid);removable(pid,['narration'] if kind=='voiceover' else [])
  d=request.get_json(silent=True) or {}
  if d.get('confirm') is not True:raise BadRequest('Confirm removal of this file.')
  if not p.get(kind):raise NotFound('Input not found.')
  if p['scenes'] and d.get('confirm_used') is not True:raise BadRequest('Confirm removal: the existing storyboard will need review or rebuilding.')
  paths=[]
  if kind=='voiceover':
   paths.append(root/p['voiceover']['path'])
   from local_understanding import result_path
   paths.append(result_path(root,'narration'))
  elif kind=='srt':
   paths.append(root/'inputs/captions.srt');p.pop('srt_recovery',None);p['srt_removed']=True
  else:paths.append(root/'inputs/production_script.txt')
  p[kind]=None
  for scene in p['scenes']:scene['approved']=False
  save(p)
  warnings=remove_local_files(root,paths)
  result=public(p);result['removal_warnings']=warnings
  return jsonify(result)



@app.post('/api/projects/<pid>/source-bindings')
def bind_script_source(pid):
 with LOCKS[pid]:
  editable(pid);p=load(pid);data=request.get_json() or {};name=str(data.get('source_file') or '').strip();aid=data.get('asset_id')
  if not name or len(name)>200 or '/' in name or chr(92) in name or Path(name).suffix.lower() not in ['.mp4','.mov','.jpg','.jpeg','.png','.webp']:raise BadRequest('Use a script filename such as S01.mp4, not a path or source label.')
  asset=next((a for a in p['assets'] if a['id']==aid),None)
  if not asset:raise BadRequest('Choose an existing upload from this project.')
  if asset.get('derived_from'):raise BadRequest('Choose the original source upload, not an extracted frame.')
  if Path(name).suffix.lower() in ['.mp4','.mov'] and asset['kind']!='video':raise BadRequest('A video filename must be linked to a video upload.')
  from production import reserve_id
  reserve=reserve_id(asset);logical=Path(name).stem.lower()
  if (reserve and logical!=reserve) or (re.fullmatch(r'r\d+',logical) and reserve!=logical):raise BadRequest('Reserve IDs cannot be renamed or reassigned. Keep the original r1, r2... source filename.')
  p['source_bindings']=dict(p.get('source_bindings') or {});p['source_bindings'][name.casefold()]=aid
  for scene in p['scenes']:scene['approved']=False
  save(p);return jsonify(public(p))

@app.put('/api/projects/<pid>/assets/<aid>/reuse-rights')
def set_asset_reuse_rights(pid,aid):
 """Record the user's specific decision; never infer ownership or legal clearance."""
 with LOCKS[pid]:
  editable(pid);p=load(pid);a=next((x for x in p['assets'] if x['id']==aid),None)
  if not a:raise NotFound('Asset not found.')
  d=request.get_json(silent=True) or {};decision=d.get('decision');basis=d.get('basis','');details=str(d.get('details') or '').strip()
  if decision not in ('unreviewed','approved','not_approved'):raise BadRequest('Choose a reuse-rights decision.')
  if len(details)>5000:raise BadRequest('Rights details must be at most 5,000 characters.')
  if decision=='approved':
   if d.get('attested') is not True:raise BadRequest('Confirm your reuse-rights decision for this file.')
   if basis not in ('permission','license','public_domain','other'):raise BadRequest('Choose the basis for your reuse decision.')
   if not details:raise BadRequest('Add the source, permission, license or other basis and any limits for this specific file.')
  else:basis=''
  if a.get('reuse_review'):a.setdefault('reuse_review_history',[]).append(copy.deepcopy(a['reuse_review']))
  a['reuse_review']={'decision':decision,'basis':basis,'details':details,'at':time.time(),'attested':decision=='approved','independent_verification':False}
  for scene in p['scenes']:
   if scene.get('asset_id')==aid:scene['approved']=False
  save(p);return jsonify(public(p))

@app.put('/api/projects/<pid>/assets/reuse-rights')
def set_all_asset_reuse_rights(pid):
 """Apply one expressly attested decision to the exact set shown to the user."""
 with LOCKS[pid]:
  editable(pid);p=load(pid);d=request.get_json(silent=True) or {};assets=p['assets'];ids=d.get('asset_ids')
  if not assets:raise BadRequest('There are no uploaded sources to review.')
  if not isinstance(ids,list) or len(ids)!=len(assets) or any(not isinstance(i,str) for i in ids) or set(ids)!={a['id'] for a in assets}:raise BadRequest('The uploaded sources changed. Refresh and review the list before approving.')
  basis=d.get('basis','');details=str(d.get('details') or '').strip()
  if d.get('attested') is not True:raise BadRequest('Confirm that your decision applies to every listed file.')
  if basis not in ('permission','license','public_domain','other'):raise BadRequest('Choose the basis for your reuse decision.')
  if not details or len(details)>5000:raise BadRequest('Provide supporting details and limits, up to 5,000 characters.')
  now=time.time()
  for a in assets:
   if a.get('reuse_review'):a.setdefault('reuse_review_history',[]).append(copy.deepcopy(a['reuse_review']))
   a['reuse_review']={'decision':'approved','basis':basis,'details':details,'at':now,'attested':True,'independent_verification':False}
  for scene in p['scenes']:
   if scene.get('asset_id') in ids:scene['approved']=False
  save(p);return jsonify(public(p))

@app.patch('/api/projects/<pid>/assets/<aid>')
def update_asset(pid,aid):
 with LOCKS[pid]:
  editable(pid);p=load(pid);a=next((x for x in p['assets'] if x['id']==aid),None)
  if not a:raise NotFound('Asset not found.')
  d=request.get_json() or {}
  if 'source' in d and str(d['source'])[:5000]!=a.get('source','') and a.get('reuse_review'):
   a.setdefault('reuse_review_history',[]).append(copy.deepcopy(a['reuse_review']))
   a['reuse_review']={'decision':'unreviewed','basis':'','details':'Source provenance changed; review reuse again.','at':time.time(),'attested':False,'independent_verification':False}
  for k in ['name','source','notes']:
   if k in d:a[k]=str(d[k])[:5000]
  if 'people' in d:a['people']=[str(n).strip()[:120] for n in d['people'] if str(n).strip()]
  if 'verified' in d:
   a['verified']=d['verified'] is True
   if not a['verified'] and a.get('approval_record'):a['approval_record']['active']=False
  if 'category' in d:
   # Categories are a free label ("person", "place", "institution", "product", anything).
   # Only "person" is meaningful to the rules; the rest is the editor's own vocabulary.
   value=str(d.get('category') or '').strip()[:40]
   if value:a['category']=value
  if d.get('rights') in ['unreviewed','permission','licensed','public_domain','reviewed_other']:a['rights']=d['rights']
  for s in p['scenes']:
   if s['asset_id']==aid:s['approved']=False
  save(p);return jsonify(public(p))
def merge_scoped_rebuild(previous, rebuilt, blocks):
 """Splice a rebuilt block range back into the saved timeline. Returns scenes plus a note.

 A block can belong to several beats (a parent beat spread across blocks 9 and 10 is one
 row per block, and both rows carry the same parent), so "beats touching these blocks" is
 the unit of replacement, not single blocks. Those beats are dropped from the saved
 timeline, the rebuilt ones are shifted so the range starts where it used to start, and
 the range is spliced back where the first dropped beat sat.

 Re-basing a range onto frame 0 can leave a sub-frame residue at its far end (a 268-frame
 range rebuilt alone can measure 269 because each end was rounded independently). A
 residue of at most 1 frame is absorbed at the last rebuilt beat and reported; anything
 larger is left alone so the caller's continuity guard refuses the save.
 """
 if not previous or not rebuilt:
  return {'scenes': previous or rebuilt, 'rounding_frames': 0, 'of': blocks}
 inside = set(blocks)
 def overlaps(scene):
  return bool(set(scene.get('srt_blocks') or []) & inside)
 replaced = [s for s in previous if overlaps(s)]
 rounding = 0
 if replaced:
  offset = min(s['frame_in'] for s in replaced) - min(s['frame_in'] for s in rebuilt)
  for scene in rebuilt:
   scene['frame_in'] += offset
   scene['frame_out'] += offset
  old_span = max(s['frame_out'] for s in replaced) - min(s['frame_in'] for s in replaced)
  new_span = max(s['frame_out'] for s in rebuilt) - min(s['frame_in'] for s in rebuilt)
  residue = old_span - new_span
  if residue and abs(residue) <= 1:
   last = max(rebuilt, key=lambda s: s['frame_out'])
   last['frame_out'] += residue
   rounding = residue
 ordered = []
 placed = False
 for scene in previous:
  if overlaps(scene):
   if not placed:
    ordered.extend(rebuilt)
    placed = True
   continue
  ordered.append(scene)
 if not placed:
  ordered.extend(rebuilt)
 return {'scenes': ordered, 'rounding_frames': rounding, 'of': blocks}

@app.post('/api/projects/<pid>/script-draft')
def script_draft(pid):
 """Display script shots for review; never claim unsupported instructions are rendered."""
 from import_status import token,update
 key=token(request.headers.get('X-Upload-ID',''))
 update(pid,key,'reading_script',detail='Reading the production script and matching each shot to its SRT cue.')
 with LOCKS[pid]:
  editable(pid);p=load(pid)
  payload=request.get_json(silent=True) or {}
  if p.get('scenes') and not (payload.get('replace_review') is True and p.get('review_only_draft') and not p.get('manual_scene_edits')):
   raise BadRequest('Existing storyboard was not replaced. Only an unmodified review draft can be rebuilt; manual edits must be preserved.')
  from document_plan import rows_for
  from edl import assemble,signature
  try:rows,mode=rows_for(p)
  except ValueError as e:raise BadRequest('Production script: '+str(e))
  if mode!='detailed_production_script' or not rows:raise BadRequest('A recognized detailed production script and matching SRT are required.')
  update(pid,key,'checking_sources',detail=f'Checked {len(rows)} cue instructions. Matching filenames and source ranges to uploaded footage.')
  review=script_reading(p)
  if payload.get('require_ready') is True and not review.get('ready_to_build'):
   raise BadRequest('Cannot build until all input checks pass: '+(' '.join(review.get('build_issues') or [review.get('detail') or 'Read the production script and SRT first.'])))
  moving_only=(request.get_json(silent=True) or {}).get('moving_only') is True
  if (review.get('missing_files') or review.get('short_shots')) and not moving_only:raise BadRequest('The review draft cannot be made: source files are missing, ambiguous or too short. No footage was substituted.')
  seeds=[];last=0
  for block in p['srt']['blocks']:
   end=round(block['end_ms']*.03)
   seeds.append(dict(id=uid(),srt_blocks=[block['number'],block['number']],frame_in=last,frame_out=end,narration=block['text'],purpose='script review',emotion='neutral',focus='Script review',category='general',person='',asset_id=None,in_s=0,motion='auto',transition='cut',context_only=False,notes='',approved=False,profile=p['profile'],focus_position='center',motion_strength='subtle'))
   last=end
  draft_rows=copy.deepcopy(rows)
  for row in draft_rows:row['review_warnings']=row.pop('import_blockers',[])
  moving_only=(request.get_json(silent=True) or {}).get('moving_only') is True
  # Never extract still frames: an explicit uploaded photo is a separate static source.
  prepared=draft_rows
  for row in prepared:
   if row.get('native_static_interval'):
    row['native_static_review']=True
   elif row.get('uploaded_photo'):
    pass
   elif row.get('requested_treatment') in ('STILL HOLD','EDITORIAL FREEZE-FRAME'):
    row['import_blockers']=['Only explicitly named uploaded photographs or native static intervals can be shown; no frame was extracted or substituted.']
  original_plan=p.get('picture_plan');had_plan='picture_plan' in p;reuse=p.get('allow_archive_reuse');had_reuse='allow_archive_reuse' in p
  p['picture_plan']={'beats':prepared};p['allow_archive_reuse']=False;p['_review_root']=str(folder(pid))
  update(pid,key,'assembling',detail=f'Preparing {len(rows)} timeline shots from the explicit source ranges; unresolved shots stay empty.')
  try:assemble(p,seeds)
  except ValueError as e:raise BadRequest('Could not prepare review draft: '+str(e))
  finally:
   p.pop('_review_root',None)
   if had_plan:p['picture_plan']=original_plan
   else:p.pop('picture_plan',None)
   if had_reuse:p['allow_archive_reuse']=reuse
   else:p.pop('allow_archive_reuse',None)
  p['review_only_draft']=True
  if moving_only:
   p['script_moving_only']=True
   for scene in p['scenes']:
    row=scene.get('plan_row') or {}
    if row.get('requested_treatment') in ('STILL HOLD','EDITORIAL FREEZE-FRAME') and not row.get('native_static_interval') and not row.get('uploaded_photo'):scene['missing_video_out']=True
  p['script_application']['mode']='moving_video_review' if moving_only else 'script_review_draft'
  p['script_application']['note']='Review draft only: caption layout, framing instructions and exact freeze frames are not verified or rendered. Names, uploaded SRT and script remain unchanged. Export is blocked.'
  p['edit_script_hash']=hashlib.sha256((p.get('production_script') or {}).get('text','').encode()).hexdigest()
  p['assembly_signature']=signature(p)
  update(pid,key,'saving_storyboard',detail='Saving the review timeline and its unresolved-shot report.')
  save(p);result=jsonify(public(p));update(pid,key,'done',detail=f'Review timeline saved: {p["script_application"]["placed_scenes"]} of {len(p["scenes"])} shots assigned.');return result



@app.post('/api/projects/<pid>/storyboard')
def build(pid):
 with LOCKS[pid]:
  editable(pid);p=load(pid)
  if not p['srt']:raise BadRequest('Import the narration SRT first.')
  payload=request.get_json(silent=True) or {}
  if p['scenes'] and not payload.get('replace'):raise BadRequest('A storyboard already exists. Confirm rebuilding to discard scene edits.')
  # Optional block range: rebuild only the beats covering these SRT blocks and leave the
  # rest of the timeline exactly as saved, approvals included.
  scope=None;adopted_surfaces=0
  if payload.get('blocks'):
   try:scope=sorted({int(x) for x in payload['blocks']})
   except (TypeError,ValueError):raise BadRequest('blocks must be a list of SRT block numbers.')
   if not scope:raise BadRequest('blocks must name at least one SRT block.')
   known={b['number'] for b in p['srt']['blocks']}
   unknown=[n for n in scope if n not in known]
   if unknown:raise BadRequest('These SRT blocks do not exist: '+', '.join(map(str,unknown[:8]))+'.')
  from document_plan import rows_for
  try:preflight_rows,preflight_mode=rows_for(p)
  except ValueError as e:raise BadRequest('Production plan: '+str(e))
  if preflight_mode=='detailed_production_script':
   blockers=[f"{r['shot_id']}: {issue}" for r in preflight_rows for issue in r.get('import_blockers',[])]
   if blockers:raise BadRequest('Detailed script needs attention: '+' '.join(blockers[:8]))
  from automatic import restore_reviewed,full_source_analysis,carry_previous_review
  previous=copy.deepcopy(p.get('scenes') or [])
  full_source_analysis(p,folder(pid))
  # A cached timeline may only stand in for a whole rebuild. On a block-range rebuild it
  # would replace the entire storyboard with the cached one, so a request that named three
  # blocks would silently rebuild (and resequence) all of them.
  if not scope and preflight_mode!='detailed_production_script' and restore_reviewed(p,folder(pid)):
   save(p);return jsonify(public(p))
  from production import infer
  detected=infer(p);p['profile']=detected['profile']
  identity_people=copy.deepcopy(p['people'])
  for name in detected['people']:
   if name.casefold() not in [x['name'].casefold() for x in identity_people]:identity_people.append({'name':name,'aliases':[],'role':''})
  scenes=[];last=0;cursor=defaultdict(float);usage=defaultdict(int)
  for i,b in enumerate(p['srt']['blocks']):
   purpose,emotion,category,person=intent(b['text'],identity_people,p['profile']);end=round(b['end_ms']*.03)
   if end<=last:raise BadRequest('An SRT block is shorter than one output frame.')
   s=dict(id=uid(),srt_blocks=[b['number'],b['number']],frame_in=last,frame_out=end,narration=b['text'],purpose=purpose,emotion=emotion,focus=person or category,category=category,person=person,asset_id=None,in_s=0,motion='auto',transition='cut',context_only=False,notes='',approved=False)
   for a in sorted(p['assets'],key=lambda a:(a['id']==(scenes[-1]['asset_id'] if scenes else None),usage[a['id']])):
    if p.get('production_script') or p.get('srt_block_map'):break
    from production import reserve_id
    if reserve_id(a):continue
    matches=person.casefold() in [n.casefold() for n in a['people']] if person else a['category']==category
    if not a['verified'] or not matches:continue
    if a['kind']=='video' and cursor[a['id']]+(end-last)/30>a['duration']-.05:continue
    s['asset_id']=a['id'];s['in_s']=round(cursor[a['id']],3);usage[a['id']]+=1
    if a['kind']=='video':cursor[a['id']]+=(end-last)/30+.05
    break
   s['profile']=p['profile'];s['focus_position']='center';s['motion_strength']='purposeful';scenes.append(s);last=end
  p['scenes']=scenes
  from production import apply,document
  from document_plan import rows_for
  from conform import stills
  try:decisions,plan_mode=rows_for(p)
  except ValueError as e:raise BadRequest('SRT block map: '+str(e) if p.get('srt_block_map') else 'Production table: '+str(e))
  if decisions:
   from automatic import native_rows
   from edl import assemble
     # Prepare original photographs only. Never create a still from a video frame.
   if scope:
    # Rebuild only the beats covering the requested blocks. The plan rows outside the
    # range are dropped, so assembling this subset cannot disturb them.
    inside=[r for r in decisions if set(r.get('srt_blocks') or []) & set(scope)]
    if not inside:raise BadRequest('No planned beat covers blocks '+', '.join(map(str,scope[:8]))+'.')
    timeline_start=min(r['timeline_in_ms'] for r in inside)
    decisions=[copy.deepcopy(r) for r in inside]
    for r in decisions:
     r['timeline_in_ms']-=timeline_start;r['timeline_out_ms']-=timeline_start
    # A cut can sit anywhere inside a beat's own wording and still be faithful to it: the
    # saved storyboard holds the surfaces the editor actually reviewed, block boundaries
    # nudged by up to 0.35s into narration breaths. When the range is one saved beat per
    # planned beat - the normal case - those exact surfaces are reused, so a rebuild
    # reproduces the reviewed picture instead of silently moving cuts and changing the
    # length of the range it was asked to preserve.
    saved=[s for s in previous if set(s.get('srt_blocks') or [])&set(scope)]
    if saved and len(saved)==len(decisions):
     first=min(s['frame_in'] for s in saved)
     for row,hit in zip(decisions,saved):
      row['timeline_in_ms']=round((hit['frame_in']-first)/30*1000)
      row['timeline_out_ms']=round((hit['frame_out']-first)/30*1000)
     adopted_surfaces=len(saved)
   if plan_mode=='detailed_production_script' and scope:raise BadRequest('Detailed shot scripts require a whole-timeline rebuild; partial rebuilding could change shot order.')
   if plan_mode=='detailed_production_script' and policy(p)!='mixed' and any(r.get('visual_status')=='STILL' for r in decisions):raise BadRequest('This script requests still holds or freeze-frames. Allow photographs and stills, or revise the script; no substitute was chosen.')
   still_plan=stills(p,folder(pid),copy.deepcopy(decisions))
   extracted=sum(bool(a.get('derived_from')) for a in p['assets'])
   if plan_mode!='detailed_production_script':
    still_plan=native_rows(p,still_plan)
    p['allow_archive_reuse']=True
   else:p['allow_archive_reuse']=False
   original=p.get('picture_plan')
   p['picture_plan']={'name':(p.get('srt_block_map') or {}).get('name','SRT block map'),'beats':still_plan,'schema_version':1,'partial':bool(scope)}
   try:
    # The plan decides the cuts. On a range rebuild the seed must also be limited to the
    # blocks being rebuilt: passing the whole-timeline seeds assembled every beat with
    # whole-timeline frame numbers, so a one-block rebuild moved the entire storyboard.
    assemble(p,[s for s in scenes if set(s['srt_blocks'])&set(scope)] if scope else scenes)
   except ValueError as e:raise BadRequest('SRT block map: '+str(e))
   finally:
    if original is None:p.pop('picture_plan',None)
    else:p['picture_plan']=original
   p['script_application']['mode']=plan_mode;p['script_application']['generated_stills']=extracted
  elif p.get('production_script'):apply(p)
  from edl import signature
  p['assembly_signature']=signature(p)
  p['edit_script_hash']=hashlib.sha256(document(p).encode()).hexdigest()
  from picture_flow import apply_flow
  if plan_mode=='detailed_production_script':
   p['picture_flow']={'note':'Exact script timings retained; no automatic source conform or breath snapping.'}
  else:p['picture_flow']=apply_flow(p,folder(pid))
  from automatic import validate_assembly
  decoded=validate_assembly(p,folder(pid));write(folder(pid)/'reviews/Automatic_frame_checks.json',decoded)
  if decoded['errors']:raise BadRequest('Automatic assembly stopped before saving an empty or undecodable timeline: '+' '.join((p.get('script_application') or {}).get('issues',[])[:3]+decoded['errors'][:3]))
  # An incremental rebuild: restore the review state of every beat whose picture the
  # rebuild reproduced exactly, and leave the rest unapproved. `scope` narrows this to a
  # block range, so editing one region does not disturb approvals elsewhere.
  if scope:
   if not decisions:raise BadRequest('An incremental rebuild needs a block map: the production script path has no per-block plan to rebuild by range.')
   spliced=merge_scoped_rebuild(previous,p['scenes'],scope);merged=spliced['scenes']
   # A range rebuild must reproduce the same timeline it replaces. If it does not, the
   # saved timeline would gain a gap or an overlap, so refuse rather than save a broken
   # storyboard and ask for a full rebuild instead.
   previous_last=0
   for i,scene in enumerate(merged):
    if scene['frame_in']!=previous_last:
     raise BadRequest('Rebuilding blocks '+', '.join(map(str,scope[:6]))+' would change the length of the surrounding timeline. Rebuild the whole storyboard instead.')
    previous_last=scene['frame_out']
   p['scenes']=merged
  if plan_mode=='detailed_production_script':p.pop('review_only_draft',None)
  carried=carry_previous_review({'scenes':previous},p['scenes'])
  p['rebuild_report']={'at':time.time(),'beats':len(p['scenes']),'approvals_carried':carried['carried'],'needs_review':carried['requiring_review'],'scope':scope,'previous_scenes':len(previous),'rounding_frames':(spliced['rounding_frames'] if scope else 0),'cut_surfaces_adopted':adopted_surfaces}
  # Detailed-script review builds also receive the locked V11.7 still treatment.
  # This changes framing only; source files, source clocks and narration are intact.
  _sync_smart_still_cameras(p)
  save(p);return jsonify(public(p))
@app.patch('/api/projects/<pid>/scenes/<sid>')
def edit_scene(pid,sid):
 with LOCKS[pid]:
  editable(pid);p=load(pid);s=next((s for s in p['scenes'] if s['id']==sid),None)
  if not s:raise NotFound('Scene not found.')
  d=request.get_json() or {}
  if p.get('script_moving_only'):
   if d.get('asset_id',s.get('asset_id'))!=s.get('asset_id'):
    raise BadRequest('The moving-video review uses only explicit script source intervals. Change the production script with an explicit IN and OUT, then rebuild; no substitute or timing guess was applied.')
  p['manual_scene_edits']=True
  for k in ['purpose','emotion','focus','person','notes']:
   if k in d:s[k]=str(d[k])[:5000]
  if 'asset_id' in d:
   if d['asset_id'] is not None and not any(a['id']==d['asset_id'] for a in p['assets']):raise BadRequest('Asset does not belong to this production.')
   s['asset_id']=d['asset_id']
  moved_in_point=False
  if 'in_s' in d:
   try:n=float(d['in_s'])
   except (TypeError,ValueError):raise BadRequest('Source in-point must be a number.')
   if not math.isfinite(n) or n<0:raise BadRequest('Source in-point must be a nonnegative finite number.')
   moved_in_point=abs(n-float(s.get('in_s') or 0))>.001
   if p.get('script_moving_only') and moved_in_point:raise BadRequest('The moving-video review uses the script source IN; edit the script and rebuild instead.')
   s['in_s']=n
  if d.get('motion') in ['auto','push','pull','pan-left','pan-right','rise','reveal']:
   if d['motion']!='auto' and d['motion']!=s.get('motion'):s.pop('script_camera',None)
   s['motion']=d['motion']
  if d.get('focus_position') in ['left','center','right']:s['focus_position']=d['focus_position']
  if d.get('motion_strength') in ['subtle','purposeful','strong']:s['motion_strength']=d['motion_strength']
  if 'transition' in d and d['transition'] not in transitions.LIBRARY:
   # An unknown name used to be dropped silently, so the request looked accepted and the
   # boundary quietly stayed as it was. Refusing is the only honest answer: the caller
   # picked a transition the renderer cannot produce.
   raise BadRequest('Choose a transition from the library: '+', '.join(transitions.LIBRARY))
  if d.get('transition') in transitions.LIBRARY:
   # A blended transition is refused while the production is clean-cuts-only rather than
   # silently rewritten to a cut. Silently forcing it meant the request appeared to succeed
   # and the scene then validated as a cut, so the policy error it should have produced
   # could never be reached and there was nothing to explain why it never appeared.
   blended=transitions.is_transition(d['transition'])
   if blended and p.get('transition_policy')=='clean_cuts_only':
    # The user's explicit selection is approval to enable the picture blend.
    # This does not change the source clocks, narration, or other cuts.
    p['transition_policy']='allow_dissolves' 
   s['transition']=d['transition']
   s['transition_handle_frames']=(int(d.get('transition_handle_frames') or 0) or 4) if blended else 0
  if 'context_only' in d:s['context_only']=d['context_only'] is True
  # Partial autosave must not revoke approval when only a transition or note
  # changes. Source/picture changes, however, require renewed visual review.
  if 'approved' in d:s['approved']=d['approved'] is True
  elif 'asset_id' in d or moved_in_point:s['approved']=False
  if s['approved'] and s.get('asset_id'):
   s.pop('source_replacement_pending',None);s.pop('replacement_issue',None)
  if moved_in_point:s.pop('picture_flow',None)  # an explicit human in-point overrides the automatic conform
  save(p)
  if request.args.get('compact')=='1':
   return jsonify({'id':p['id'],'updated':p['updated'],'scene':s})
  return jsonify(public(p))

@app.patch('/api/projects/<pid>/scenes/<sid>/picture-scale')
def edit_scene_picture_scale(pid,sid):
 with LOCKS[pid]:
  editable(pid);p=load(pid);scene=next((s for s in p['scenes'] if s['id']==sid),None)
  if scene is None:raise NotFound('Scene not found.')
  data=request.get_json(silent=True) or {}
  if 'picture_scale' not in data:raise BadRequest('Specify a picture scale or null to use the project scale.')
  value=data['picture_scale']
  if value is not None and (isinstance(value,bool) or not isinstance(value,int) or not 100<=value<=200):raise BadRequest('Picture scale must be a whole percentage from 100 to 200, or null to use the project scale.')
  if value is None:scene.pop('picture_scale',None)
  else:scene['picture_scale']=value
  save(p);return jsonify(public(p))

@app.patch('/api/projects/<pid>/scenes/picture-scale')
def edit_selected_picture_scale(pid):
 with LOCKS[pid]:
  editable(pid);p=load(pid);data=request.get_json(silent=True) or {};ids=data.get('scene_ids');value=data.get('picture_scale')
  if not isinstance(ids,list) or not ids or any(not isinstance(x,str) for x in ids) or len(ids)!=len(set(ids)):raise BadRequest('Select one or more distinct timeline slots.')
  if 'picture_scale' not in data or (value is not None and (isinstance(value,bool) or not isinstance(value,int) or not 100<=value<=200)):raise BadRequest('Picture scale must be a whole percentage from 100 to 200, or null to use the project scale.')
  by_id={s['id']:s for s in p['scenes']}
  if any(x not in by_id for x in ids):raise BadRequest('A selected slot is no longer in this production; no changes were made.')
  for sid in ids:
   if value is None:by_id[sid].pop('picture_scale',None)
   else:by_id[sid]['picture_scale']=value
  save(p)
  if request.args.get('compact')=='1':
   return jsonify({'id':p['id'],'updated':p['updated'],'scenes':[{ 'id':sid,'picture_scale':by_id[sid].get('picture_scale')} for sid in ids]})
  return jsonify(public(p))

@app.post('/api/projects/<pid>/scenes/approve')
def approve_scenes(pid):
 """Approve every scene that passes the same review export readiness applies.

 A scene that raises any export-readiness error is left unapproved and reported with
 its reasons. That keeps bulk approval honest: it cannot approve a beat whose media,
 timing or disclosure would block the export a moment later.
 """
 with LOCKS[pid]:
  editable(pid);p=load(pid);d=request.get_json(silent=True) or {}
  if d.get('attested') is not True:raise BadRequest('Confirm that you have reviewed the picture beats before approving them.')
  from documentary_beats import is_strict_pipeline_script
  if is_strict_pipeline_script((p.get('production_script') or {}).get('text','')):
   from documentary_strict import review_blockers
   blockers=review_blockers(p,folder(pid))
   if blockers:raise BadRequest('Strict Beat visual review must pass before scene approval: '+ ' '.join(blockers))
  scope=str(d.get('scope') or 'ready')
  if scope not in ['ready','all']:raise BadRequest('Choose scope "ready" (default) or "all".')
  assets={x['id']:x for x in p['assets']};ranges=defaultdict(list);last=0
  approved=[];skipped=[]
  for i,scene in enumerate(p['scenes']):
   a=assets.get(scene['asset_id'])
   errors,_=scene_review(p,i,scene,a,ranges,last)
   if not errors:
    if not scene['approved']:
     scene['approved']=True;scene['approval_record']={'method':'bulk_scene_approval','scope':scope,'at':time.time(),'reasons':'media assigned, source recorded, timing valid, no blocking review item'}
     approved.append(i+1)
   else:
    scene['approved']=False;skipped.append({'scene':i+1,'srt_blocks':scene.get('srt_blocks'),'reasons':errors})
   last=scene['frame_out']
   if a and a['kind']=='video':
    ranges[a['id']].append((*source_overlap_interval(scene,a,p),i+1,scene_beat(scene)))
  p.setdefault('scene_approval_history',[]).append({'action':'bulk_scene_approval','scope':scope,'approved':len(approved),'skipped':len(skipped),'at':time.time()})
  if scope=='all' and skipped:raise BadRequest(str(len(skipped))+' picture beat(s) cannot be approved yet. Nothing was approved; open the first one to see why: Scene '+str(skipped[0]['scene'])+' — '+skipped[0]['reasons'][0])
  save(p)
  result=public(p);result['bulk_approval']={'approved':approved,'skipped':skipped,'scope':scope}
  return jsonify(result)

@app.post('/api/projects/<pid>/scenes/<sid>/split')
def split_scene(pid,sid):
 raise BadRequest('Splitting a cue is disabled: use exactly one shot per SRT cue.')

@app.post('/api/projects/<pid>/scenes/<sid>/merge')
def merge_scene(pid,sid):
 raise BadRequest('Merging cues is disabled: use exactly one shot per SRT cue.')

def manifest(p, strict=None, enhance_picture=False):
 from production import reserve_id,asset_used
 root=folder(p['id']);w,h=output_size(p.get('format','landscape'),p.get('size'));assets={a['id']:a for a in p['assets']};shots=[];signatures=set()
 for i,s in enumerate(p['scenes']):
  a=assets[s['asset_id']];frames=s['frame_out']-s['frame_in'];m=motion(s,i);signature=tuple(m[k] for k in ['zoom_start','zoom_end','x_start','x_end','y_start','y_end'])
  while signature in signatures and m.get('move')!='static':m['x_end']+=.00001;signature=tuple(m[k] for k in ['zoom_start','zoom_end','x_start','x_end','y_start','y_end'])
  signatures.add(signature)
  # The final scene has no boundary after it, so a handle on it would reserve source
  # frames and add picture frames that no transition ever consumes -- which lengths the
  # programme by the handle and pushes the narration out of sync. The handle exists only
  # where a transition will actually use it.
  last_scene=i==len(p['scenes'])-1
  extra=s.get('transition_handle_frames',4) if (transitions.is_transition(s.get('transition')) and not last_scene) else 0
  shot={'shot':i+1,'kind':'narration','slot':None,'subject':s['focus'],'srt_blocks':s['srt_blocks'],'frame_in':s['frame_in'],'frame_out':s['frame_out'],'duration_frames':frames,'duration_ms':frames/30*1000,'timeline_in_ms':s['frame_in']/30*1000,'timeline_out_ms':s['frame_out']/30*1000,'voiceover_in_ms':s['frame_in']/30*1000,'voiceover_out_ms':s['frame_out']/30*1000,'narration_text':s['narration'],'source_id':reserve_id(a) or a.get('editorial_source_id') or ((a.get('document_plan') or {}).get('source_ids') or [a['id']])[0],'original_filename':a.get('original_name',a['name']),'source_role':'reserve' if reserve_id(a) else 'primary','source_file':Path(a['path']).name,'media_type':a['kind'],'video_in_ms':s['in_s']*1000,'video_out_ms':math.ceil((s['in_s']+(frames+extra)/30)*1000)+1,'motion_plan':m,'transition_handle_frames':extra,'image_approved':a['verified'],'match_note':s['notes'],'loop_required':False,'hold_last':False}
  if a['kind']=='image':
   # A photograph is prepared once per (source revision, canvas, framing, mode) and then
   # reused. Without the revision in the key, replacing a photo would silently keep
   # serving the old enhanced file.
   import upscale
   framing=(shot.get('framing') or p.get('framing') or 'auto')
   if framing=='auto':framing='full_bleed' if p.get('image_layout')=='full_bleed' else 'blur'
   mode='full_bleed' if framing=='crop' else ('fit' if framing=='fit' else 'blur')
   key=f'{a["id"]}-{a.get("revision","0")}-{w}x{h}-{mode}'
   out=root/'.cache/prepared_images'/f'{key}.png';out.parent.mkdir(parents=True,exist_ok=True)
   report=None
   if not out.is_file():
    with Image.open(root/a['path']) as opened:
     im=ImageOps.exif_transpose(opened).convert('RGB')
    prepared,report=upscale.prepare(im,(w,h),prefer_ai=(p.get('upscaler','auto')!='lanczos'),
                                    framing=mode,cache_dir=root/'.cache'/'upscaled',cache_key=f'{a["id"]}-{a.get("revision","0")}')
    prepared.save(out)
   shot['picture_upscale']=report or {'framing':mode}
   shot['image']=out.relative_to(root).as_posix()
  if strict and strict.get('required') and a['kind']=='video':
   timing=strict['shots'][i]
   shot['strict_source_frames']=[timing['source_start_frame'],timing['source_end_frame']]
   shot['video_in_ms']=timing['placed_in_ms'];shot['video_out_ms']=timing['placed_out_ms']
  shot['picture_scale']=s.get('picture_scale',p.get('picture_scale',100))
  # Framing is per shot so a single differently-shaped insert can be fitted without
  # changing how the rest of the film is framed.
  shot['framing']=s.get('framing') or p.get('framing','auto')
  # The engine blends whatever this names. `cut` carries no handle, so it costs nothing.
  shot['transition']=s.get('transition','cut')
  if a['kind']=='video':
   from truecrime_camera import still_visual_kind
   if not still_visual_kind(a,[s]):shot['motion_plan'].update(mode='native_video',move='Preserve source camera and human action')
  shots.append(shot)
 result={'project':p['title'],'version':1,'editorial_approved':all(s['approved'] for s in p['scenes']),'captions_burned_in':False,'settings':{'width':w,'height':h,'fps':30,'caption_srt':'inputs/captions.srt','transition_frames':0,'picture_scale':p.get('picture_scale',100),'enhance_picture':enhance_picture,'framing':p.get('framing','auto'),'quality':p.get('quality','standard'),'caption_preset':p.get('caption_preset') or captions.DEFAULT},'shots':shots,'reserve_sources':[{'source_id':reserve_id(a),'original_filename':a.get('original_name',a['name']),'source_file':Path(a['path']).name,'status':'explicitly_selected' if asset_used(p,a) else 'held_in_reserve'} for a in p['assets'] if reserve_id(a) and not a.get('derived_from')]}
 write(root/'storyboard.json',result);return result
@app.post('/api/projects/<pid>/continuous-preview')
def prepare_continuous_preview(pid):
 from preview_render import start
 with LOCKS[pid]:
  p=load(pid);root=folder(pid)
  if p.get('edit_mode','review')=='documentary':raise BadRequest('Documentary smooth preview is not implemented yet.')
  if p.get('review_only_draft'):raise BadRequest('This review draft cannot be rendered as a smooth preview until its caption, framing and freeze-frame instructions are implemented.')
  if not p['scenes']:raise BadRequest('Build a storyboard first.')
  def publish(updated,temp,base):
   with LOCKS[pid]:
    if load(pid)['updated']!=updated:return False
    temp.replace(base/'preview.mp4')
    write(base/'status.json',{'status':'done','updated':updated,'progress':100,'detail':'Temporary smooth preview ready.'})
    return True
  try:result=start(root,p,publish)
  except ValueError as e:raise BadRequest(str(e))
  return jsonify(result),202

@app.get('/api/projects/<pid>/continuous-preview')
def continuous_preview_file(pid):
 from preview_render import status as preview_status
 p=load(pid);root=folder(pid);state=preview_status(root,pid,p['updated'])
 if state.get('status')!='done' or request.args.get('version')!=str(p['updated']):raise NotFound('Preview is not current.')
 return send_from_directory(root/'.cache/continuous_preview','preview.mp4',conditional=True)

@app.post('/api/projects/<pid>/scene-exports')
def prepare_scene_exports(pid):
 from scene_exports import start
 with LOCKS[pid]:
  p=load(pid);root=folder(pid);data=request.get_json(silent=True) or {};kind=data.get('source')
  if p.get('edit_mode','review')=='documentary':raise BadRequest('Documentary scene export is not implemented yet.')
  if p.get('review_only_draft'):raise BadRequest('A review draft cannot be exported as finished scene clips.')
  if kind not in ('preview','render'):raise BadRequest('Choose the smooth preview or a rendered master.')
  d=public(p)
  if kind=='preview':
   if d['preview'].get('status')!='done':raise BadRequest('Prepare a current smooth preview first.')
   source=root/'.cache/continuous_preview/preview.mp4'
  else:
   render_info=d['render']
   if render_info.get('status')!='done' or not render_info.get('current'):raise BadRequest('Render the current storyboard first.')
   name=render_info.get('output','')
   if Path(name).name!=name:raise BadRequest('Invalid rendered video name.')
   source=root/'renders'/name
  def publish(updated,archive,name,source_kind):
   with LOCKS[pid]:
    if load(pid)['updated']!=updated:return False
    dest=root/'renders/scene_exports';dest.mkdir(parents=True,exist_ok=True);archive.replace(dest/name)
    write(root/'scene_exports_status.json',{'status':'done','updated':updated,'source_kind':source_kind,'naming':'C','output':name,'progress':100,'detail':str(len(p['scenes']))+' scene clips ready.'})
    return True
  try:result=start(root,p,source,kind,publish)
  except ValueError as e:raise BadRequest(str(e))
  return jsonify(result),202

@app.get('/api/projects/<pid>/scene-exports/<name>')
def download_scene_exports(pid,name):
 if not re.fullmatch(r'scenes_[0-9]{8}_[0-9]{6}_[a-f0-9]{8}\.zip',name):raise NotFound('Scene archive not found.')
 return send_from_directory(folder(pid)/'renders/scene_exports',name,conditional=True,as_attachment=True)

@app.get('/api/projects/<pid>/documentary-bites')
def get_documentary_bites(pid):
 from documentary import load_plan,annotate_plan
 root=folder(pid)
 with _reading(pid):
  try:return jsonify(annotate_plan(load(pid),root,load_plan(root)))
  except ValueError as e:raise BadRequest(str(e))

@app.post('/api/projects/<pid>/documentary-bites')
def add_documentary_bite(pid):
 from documentary import load_plan,validate_bite,annotate_plan
 root=folder(pid);data=request.get_json(silent=True) or {}
 with LOCKS[pid]:
  plan=load_plan(root)
  if data.get('revision')!=plan['revision']:raise BadRequest('The sound-bite plan changed in another window. Reopen it before saving.')
  if len(plan['bites'])>=200:raise BadRequest('The plan is limited to 200 sound bites.')
  try:bite=validate_bite(load(pid),root,data,lambda path:probe(path)['has_audio'])
  except (ValueError,OSError) as e:raise BadRequest(str(e))
  plan['bites'].append(bite);plan['bites'].sort(key=lambda x:(x['pause_s'],x['created']))
  plan['revision']+=1;write(root/'documentary_plan.json',plan)
  return jsonify(annotate_plan(load(pid),root,plan))

@app.put('/api/projects/<pid>/documentary-bites')
def replace_documentary_bites(pid):
 from documentary import load_plan,validate_bite,annotate_plan
 root=folder(pid);data=request.get_json(silent=True) or {}
 with LOCKS[pid]:
  project=load(pid)
  if project.get('edit_mode','review')!='documentary':raise BadRequest('Sound-bite editing is only available in documentary mode.')
  plan=load_plan(root)
  if data.get('revision')!=plan['revision']:raise BadRequest('The sound-bite plan changed in another window. Reopen it before saving.')
  items=data.get('bites')
  if not isinstance(items,list) or len(items)>200:raise BadRequest('Provide a list of at most 200 sound bites.')
  try:
   new=[validate_bite(project,root,x,lambda path:probe(path)['has_audio']) for x in items]
  except (ValueError,OSError,TypeError,AttributeError) as e:raise BadRequest(str(e))
  new.sort(key=lambda b:(b['pause_s'],b['created']));plan['bites']=new;plan['revision']+=1
  write(root/'documentary_plan.json',plan)
  return jsonify(annotate_plan(project,root,plan))

@app.patch('/api/projects/<pid>/documentary-bites/<bid>')
def move_documentary_bite(pid,bid):
 from documentary import load_plan,validate_bite,annotate_plan
 root=folder(pid);data=request.get_json(silent=True) or {}
 with LOCKS[pid]:
  p=load(pid)
  if p.get('edit_mode','review')!='documentary':raise BadRequest('Sound-bite dragging is only available in documentary mode.')
  plan=load_plan(root)
  if data.get('revision')!=plan['revision']:raise BadRequest('The sound-bite plan changed in another window. Reopen it before moving the bite.')
  old=next((b for b in plan['bites'] if b['id']==bid),None)
  if not old:raise NotFound('Sound bite not found.')
  if annotate_plan(p,root,{'bites':[copy.deepcopy(old)]})['bites'][0]['stale_reasons']:raise BadRequest('The source or narration changed; review this sound bite before moving it.')
  try:
   checked=validate_bite(p,root,{'asset_id':old['asset_id'],'pause_s':data.get('pause_s'),'source_in_s':old['source_in_s'],'source_out_s':old['source_out_s']},lambda path:probe(path)['has_audio'])
  except (ValueError,OSError) as e:raise BadRequest(str(e))
  old['pause_s']=checked['pause_s'];plan['bites'].sort(key=lambda b:(b['pause_s'],b['created']));plan['revision']+=1
  write(root/'documentary_plan.json',plan)
  return jsonify(annotate_plan(p,root,plan))

@app.delete('/api/projects/<pid>/documentary-bites/<bid>')
def remove_documentary_bite(pid,bid):
 from documentary import load_plan,annotate_plan
 root=folder(pid);data=request.get_json(silent=True) or {}
 with LOCKS[pid]:
  plan=load_plan(root)
  if data.get('revision')!=plan['revision']:raise BadRequest('The sound-bite plan changed in another window. Reopen it before removing anything.')
  new=[x for x in plan['bites'] if x['id']!=bid]
  if len(new)==len(plan['bites']):raise NotFound('Sound bite not found.')
  plan['bites']=new;plan['revision']+=1;write(root/'documentary_plan.json',plan)
  return jsonify(annotate_plan(load(pid),root,plan))

@app.post('/api/projects/<pid>/documentary-audio')
def start_documentary_audio(pid):
 try:return jsonify(_start_documentary_audio(pid)),202
 except (ValueError,OSError) as e:raise BadRequest(str(e))

def _start_documentary_audio(pid):
 """Start preparing the review mix. Raises ValueError with a sentence for the user.

 Shared by the button and by the Beat build, which starts it the moment the timeline
 is saved, so the preview is ready (or nearly) by the time anyone presses play.
 """
 import documentary_audio
 from documentary import load_plan,annotate_plan,build_timeline
 with LOCKS[pid]:
  p=load(pid);root=folder(pid)
  if p.get('edit_mode','review')!='documentary':raise BadRequest('Documentary audio is available only in a documentary project.')
  plan=load_plan(root)
  try:
   timeline=build_timeline(p,annotate_plan(p,root,copy.deepcopy(plan)))
   if not any(s['kind']=='sound_bite' for s in timeline['segments']):raise ValueError('Add a sound bite first.')
   def current(original,source_plan):
    with LOCKS[pid]:
     current_p=load(pid);current_plan=load_plan(root)
     if current_p.get('updated')!=original.get('updated') or current_plan['revision']!=source_plan['revision']:return False
     return not any(x.get('stale_reasons') for x in annotate_plan(current_p,root,current_plan)['bites'])
   # The preview mix carries narration and the chosen bites only. Background music
   # is played as its own live browser layer against the same clock, so the bed is
   # never doubled and a level or ducking change is heard without re-rendering.
   return documentary_audio.start(root,copy.deepcopy(p),copy.deepcopy(plan),current,music=False)
  except OSError as e:raise ValueError(str(e)) from e

@app.get('/api/projects/<pid>/documentary-audio')
def documentary_audio_status(pid):
 import documentary_audio
 from documentary import load_plan,annotate_plan
 root=folder(pid)
 with _reading(pid):
  p=load(pid);plan=load_plan(root);state=documentary_audio.status(pid,root)
  if p.get('edit_mode','review')!='documentary':raise BadRequest('Documentary audio is available only in a documentary project.')
  if state.get('status')=='done':
   from documentary_music import settings as music_settings,music_path
   music=music_settings(p);expected_music=bool(music['enabled'] and music['present'] and music_path(root).is_file())
   mixed_music=bool((state.get('music') or {}).get('present') if isinstance(state.get('music'),dict) else state.get('music_baked'))
   # A silent bed changes nothing, so only a real music difference invalidates it.
   # Only real assembly changes invalidate the mix. Music level, music on/off,
   # ducking and other review settings are applied live, so they must not force an
   # eight-minute re-render; what matters is whether the picture, narration or
   # bites moved.
   audio_signature=documentary_audio.signature(p,plan)
   stale=(state.get('audio_signature') not in (None,audio_signature) and state.get('audio_signature')!=audio_signature) or state.get('audio_processing_version')!=documentary_audio.AUDIO_PROCESSING_VERSION or state.get('plan_revision')!=plan['revision'] or any(b.get('stale_reasons') for b in annotate_plan(p,root,plan)['bites'])
   # The bed is NOT mixed into the file any more: since v2 the browser plays it
   # as a live layer, so adding or removing music must never invalidate a mix.
   # (Comparing it against the recorded output marked every mix stale forever as
   # soon as a bed was added, which blanked the monitor and stopped playback.)
   # Only a v1 mix, which does have the bed baked in, can disagree with it.
   legacy_baked=state.get('audio_processing_version')!=documentary_audio.AUDIO_PROCESSING_VERSION
   if not stale and legacy_baked and expected_music!=mixed_music:stale=True
   if stale:state={'status':'stale','detail':'Project or plan changed; prepare documentary audio again.'}
   else:state['url']=f'/api/projects/{pid}/documentary-audio/{state["output"]}'
  return jsonify(state)

@app.get('/api/projects/<pid>/documentary-audio/<name>')
def documentary_audio_file(pid,name):
 import documentary_audio
 from documentary import load_plan,annotate_plan
 if not re.fullmatch(r'documentary_audio_[a-f0-9]{32}\.(wav|m4a)',name):raise NotFound('Documentary audio not found.')
 root=folder(pid)
 with LOCKS[pid]:
  p=load(pid);plan=load_plan(root);job=documentary_audio.status(pid,root)
  current=(job.get('audio_signature') or documentary_audio.signature(p,plan))==documentary_audio.signature(p,plan)
  if p.get('edit_mode','review')!='documentary' or job.get('status')!='done' or job.get('audio_processing_version')!=documentary_audio.AUDIO_PROCESSING_VERSION or job.get('output')!=name or not current or job.get('plan_revision')!=plan['revision'] or any(b.get('stale_reasons') for b in annotate_plan(p,root,plan)['bites']):raise NotFound('Documentary audio is not current.')
  return send_from_directory(root/'renders',name,conditional=True,as_attachment=request.args.get('download')=='1')

def _music_state(p,root):
 """One reply shape for upload, patch and read, so the panel cannot be told half a story."""
 from documentary_music import settings,music_path
 state=settings(p)
 music=p.get('documentary_music') or {}
 # Name and length are what prove a file actually landed. Without them a
 # successful upload and a silent no-op look identical in the panel.
 state['name']=music.get('name') or ''
 state['size']=int(music.get('size') or 0)
 state['duration_s']=float(music.get('duration_s') or 0)
 bed=music_path(root)
 state['file_present']=bool(state['name'] and bed.is_file())
 state['present']=state['file_present']
 # The preview scales the raw file; without the measured loudness it cannot know
 # how much gain the exporter would apply, so the two played at different levels.
 state['loudness_lufs']=music.get('loudness_lufs')
 # The version comes from the file's own size and mtime, so replacing the bed
 # changes the URL and no browser can serve the previous one from cache.
 version=f"{state['size']}-{bed.stat().st_mtime_ns}" if state['file_present'] else ''
 state['url']=f'/api/projects/{p["id"]}/documentary-music/file?v={version}' if state['file_present'] else ''
 levels=p.get('documentary_audio_levels') or {}
 state['narration_percent']=levels.get('narration_percent',100)
 state['clip_percent']=levels.get('clip_percent',100)
 return state

@app.get('/api/projects/<pid>/documentary-music')
def documentary_music_state(pid):
 root=folder(pid)
 with _reading(pid):
  p=load(pid)
  if p.get('edit_mode','review')!='documentary':raise BadRequest('Background music is available only in a documentary project.')
  return jsonify(_music_state(p,root))

@app.post('/api/projects/<pid>/documentary-music')
def upload_documentary_music(pid):
 from documentary_music import save_upload
 root=folder(pid)
 upload=request.files.get('music')
 if not upload or not upload.filename:raise BadRequest('Choose an audio file for the background music.')
 with LOCKS[pid]:
  editable(pid);p=load(pid)
  if p.get('edit_mode','review')!='documentary':raise BadRequest('Background music is available only in a documentary project.')
  try:record=save_upload(root,upload,upload.filename)
  except (ValueError,OSError) as e:raise BadRequest(str(e))
  music=dict(p.get('documentary_music') or {})
  first_bed=not music.get('name')
  music.update(record);music.setdefault('enabled',True);music.setdefault('volume_percent',35);music.setdefault('narration_level','duck')
  if first_bed:music['enabled']=True
  p['documentary_music']=music;save(p)
  return jsonify(_music_state(p,root))

@app.patch('/api/projects/<pid>/documentary-music')
def update_documentary_music(pid):
 from documentary_music import settings,music_path
 data=request.get_json(silent=True) or {}
 root=folder(pid)
 with LOCKS[pid]:
  editable(pid);p=load(pid)
  if p.get('edit_mode','review')!='documentary':raise BadRequest('Background music is available only in a documentary project.')
  music=dict(p.get('documentary_music') or {})
  if 'enabled' in data:
   if not isinstance(data['enabled'],bool):raise BadRequest('Music on/off must be true or false.')
   music['enabled']=data['enabled']
  # The bed ducks under speech. It is one continuous piece for the whole film -- it is
  # never cut, and it comes back up wherever the speaking stops -- but while narration or
  # a sound bite is carrying words it sits underneath them, which is what makes speech
  # intelligible. `duck` is therefore the only accepted mode, and an old client asking
  # for a flat 'full' bed is stored as a duck rather than being honoured.
  if 'duck_under_speech' in data:
   if not isinstance(data['duck_under_speech'],bool):raise BadRequest('Ducking must be true or false.')
   if data['duck_under_speech'] is False:
    raise BadRequest('The background music ducks under speech; it cannot be switched to play flat.')
  for key in ('narration_level','speech_mode'):
   if key in data:
    if data[key] not in ('full','mute','duck'):raise BadRequest('Choose ducked music, or turn the bed off.')
    music['narration_level']='duck'
  music.pop('duck_under_speech',None)
  music['narration_level']='duck'
  if 'volume_percent' in data:
   value=data['volume_percent']
   if isinstance(value,bool) or not isinstance(value,int):raise BadRequest('Music volume must be a whole percentage from 0 to 100.')
   if value==0:raise BadRequest('Use the music switch to turn the bed off instead of a zero volume.')
   if not -12<=value<=100:raise BadRequest('Music volume must be between -12 and 100 percent.')
   music['volume_percent']=value
  if data.get('remove') is True:
   for stale in (root/'inputs').glob('background_music*'):
    stale.unlink(missing_ok=True)
   music={'name':'','size':0,'duration_s':0,'path':'','version':music.get('version','')}
  if not music_path(root).is_file():music['enabled']=False
  p['documentary_music']=music;save(p)
  state=_music_state(p,root)
 return jsonify(state)

@app.patch('/api/projects/<pid>/documentary-audio-levels')
def update_documentary_audio_levels(pid):
 """Save the narration, clip-audio and music balance that the export will apply."""
 from documentary_music import settings as music_settings
 data=request.get_json(silent=True) or {}
 with LOCKS[pid]:
  editable(pid);p=load(pid)
  if p.get('edit_mode','review')!='documentary':raise BadRequest('Audio levels are available only in a documentary project.')
  levels=dict(p.get('documentary_audio_levels') or {})
  # Percentages, not decibels: a reviewer can reason about 80% without knowing
  # what a dB step sounds like. 150% is the ceiling for the two speech levels so a
  # quiet source can be lifted; music keeps its own 1-100 range because the bed is
  # already expressed that way everywhere else.
  for key,ceiling in (('narration_percent',150),('clip_percent',150)):
   if key not in data:continue
   value=data[key]
   if isinstance(value,bool) or not isinstance(value,int):raise BadRequest('Audio levels must be whole percentages.')
   if not 0<=value<=ceiling:raise BadRequest(f'Audio level must be between 0 and {ceiling} percent.')
   levels[key]=value
  music=dict(p.get('documentary_music') or {})
  if 'volume_percent' in data:
   value=data['volume_percent']
   if isinstance(value,bool) or not isinstance(value,int):raise BadRequest('Music level must be a whole percentage.')
   if not 1<=value<=100:raise BadRequest('Music level must be between 1 and 100 percent. Use the music switch to turn the bed off.')
   music['volume_percent']=value;p['documentary_music']=music
  levels.setdefault('narration_percent',100);levels.setdefault('clip_percent',100)
  p['documentary_audio_levels']=levels;save(p)
  state=music_settings(p);state['file_present']=bool((p.get('documentary_music') or {}).get('name'))
  state['volume_percent']=(p.get('documentary_music') or {}).get('volume_percent',state.get('volume_percent',35))
  state['narration_percent']=levels['narration_percent'];state['clip_percent']=levels['clip_percent']
 return jsonify(state)

@app.get('/api/projects/<pid>/documentary-music/file')
def documentary_music_file(pid):
 from documentary_music import music_path
 root=folder(pid)
 with LOCKS[pid]:
  p=load(pid)
  if not (p.get('documentary_music') or {}).get('name') or not music_path(root).is_file():raise NotFound('No background music is saved in this production.')
  return send_file(music_path(root),conditional=True,as_attachment=request.args.get('download')=='1')

@app.get('/api/projects/<pid>/documentary-beat-proposal')
def documentary_beat_proposal(pid):
 """Preflight an authoritative v5 script or show the legacy fitting proposal."""
 from documentary_beats import read_beats, is_strict_pipeline_script, reconcile_pause_clocks
 from documentary_beat_plan import proposal
 from documentary_strict import validate as validate_strict
 with LOCKS[pid]:
  p=load(pid)
  if p.get('edit_mode')!='documentary':raise BadRequest('Beat proposals are available only in documentary mode.')
  script=(p.get('production_script') or {}).get('text','')
  try:
   beats, pause_fixes = reconcile_pause_clocks(read_beats(script))
   if is_strict_pipeline_script(script):
    checked=validate_strict(p,folder(pid),beats)
    consecutive=[[beats[i-1]['label'],beats[i]['label']] for i in range(1,len(beats))
                 if beats[i-1]['kind']==beats[i]['kind']=='sound_bite' and beats[i-1].get('pause_ms')==beats[i].get('pause_ms')]
    data={'strict_execution':True,'issues':checked['issues'],'adjustments':[],
          'narration_gaps':[],'repeated_ranges':[],'reuse_notes':checked.get('reuse_notes') or [],'consecutive_bites':consecutive,
          'beats':checked['beats'],'frame_ranges':checked['frame_ranges'],
          'source_signatures':checked['source_signatures'],
          'assets':[{'name':a.get('original_name') or a.get('name'),'duration':float(a.get('duration') or 0)} for a in p.get('assets',[]) if a.get('kind')=='video']}
   else:
    from documentary_beat_plan import frame_limits
    data=proposal(p,beats,request.args.get('scripted_review_beat'),request.args.get('scripted_review_source'),frame_limits(folder(pid),p['assets']))
    data['strict_execution']=False
   data['pause_clock_reconciliations']=pause_fixes
  except ValueError as e:raise BadRequest(str(e))
  # Narration length as decoded (encoder delay/padding removed) beside the file's own
  # figure, so a pause written at the "end" can be checked against the real end.
  from documentary import decoded_narration, narration_clock_s
  info=decoded_narration(folder(pid),p.get('voiceover')) or {}
  data['narration_length']={**info,'clock_s':round(narration_clock_s(p),3) if p.get('voiceover') else None}
  # The client used to send plan_revision:0 for every project. Once a plan holds
  # bites its revision is never 0, so every rebuild was refused as "the plan
  # changed; review the proposal again" -- with the proposal it had just shown --
  # and a script edited after a build could never be rebuilt at all. Report the
  # revision the build will be checked against and let the client echo it back.
  from documentary import load_plan
  current=load_plan(folder(pid))
  recorded=(p.get('documentary_beat_review') or {}).get('script_sha256') or ''
  changed=bool(recorded) and recorded!=hashlib.sha256(script.encode()).hexdigest()
  return jsonify({'project_version':p.get('updated'),'script_sha256':hashlib.sha256(script.encode()).hexdigest(),
                  'plan_revision':current['revision'],'replaces_beat_timeline':bool(current['bites'] or p.get('scenes')),
                  'beat_timeline_stale':changed,
                  'assets':[{'name':a.get('original_name') or a.get('name'),'duration':a.get('duration')} for a in p.get('assets',[])],
                  **data})

def _sync_smart_still_cameras(p):
 """Auto-motion is a grouped style setting, never a Beat rebuild.

 Imported photographs, P##_..._video photo carriers, and explicitly mapped
 native static intervals in narration shots receive restrained camera motion.
 Script/manual-locked settings and evidence screenshots stay unchanged.
 """
 from person_overlays import settings as person_settings
 conf=person_settings(p)
 # V11.7 locks restrained movement on for still visuals. The grouped people
 # overlay switch does not turn the main picture back into a frozen hold.
 enabled=True
 for scene in p.get('scenes') or []:
  c=scene.get('camera') or {}
  if c.get('origin')=='auto' and c.get('reason','').startswith('Smart still:'):
   scene.pop('camera',None)
  legacy=scene.get('script_camera') or {}
  if (legacy.get('move')=='static' and
      str(legacy.get('basis') or '').startswith('Still/frame is held without invented camera motion')):
   scene.pop('script_camera',None)
 if not enabled or not p.get('scenes'):return 0
 from truecrime_camera import suggest_still_cameras
 suggested=suggest_still_cameras(p)
 applied=0
 for scene in p.get('scenes') or []:
  cam=suggested.get(scene.get('id'))
  if not cam or scene.get('camera_locked') or scene.get('script_camera') or scene.get('camera'):
   continue
  scene['camera']={**cam,'origin':'auto','reason':'Smart still: '+str(cam.get('reason') or 'story-led framing')}
  applied+=1
 return applied

def _reapply_transition_choice(p):
 """After a rebuild, give the new cuts the same treatment the user last chose.

 A cut the script names keeps the script's transition; the rest get the saved Auto
 style or the "apply to all" transition. Without this every rebuild quietly went back
 to hard cuts.
 """
 scenes=p.get('scenes') or [];choice=p.get('documentary_transition_choice') or {}
 cuts=transitions.documentary_cuts(scenes);lengths=transitions.shot_frames(scenes,cuts)
 free=[c for c in cuts if scenes[c].get('transition_source')!='script']
 if choice.get('auto') in transitions.AUTO_STYLES:
  chosen=transitions.auto_documentary(scenes,choice['auto'],choice.get('duration'),choice.get('seed') or 0,assets=_asset_kinds(p))
  for c in free:
   key,frames=chosen.get(c,('cut',0));scenes[c].update(transition=key,transition_handle_frames=frames,transition_source='auto')
 elif choice.get('all') in transitions.LIBRARY:
  for c in free:
   key,frames=transitions.fit_frames(choice['all'],transitions.frames_for(choice['all'],choice.get('duration')),*lengths[c])
   scenes[c].update(transition=key,transition_handle_frames=frames,transition_source='manual')
 else:
  # The script may ask for AUTO on some Beats without a saved choice: use Balanced.
  wanted=[c for c in cuts if scenes[c].get('transition_source')=='script-auto']
  if wanted:
   chosen=transitions.auto_documentary(scenes,'balanced')
   for c in wanted:
    key,frames=chosen.get(c,('cut',0));scenes[c].update(transition=key,transition_handle_frames=frames)
 if any(s.get('transition')!='cut' for s in scenes):p['transition_policy']='allow_dissolves'
 _sync_smart_still_cameras(p)

def _slot_key(scene):
 """What identifies one slot across rebuilds: its Beat and its subtitle cue."""
 row=scene.get('plan_row') or {}
 return (str(row.get('script_beat') or ''),str(row.get('shot_id') or ''),str(row.get('source_file') or ''))

def _carry_cinematic(old_scenes,new_scenes):
 """Keep camera moves and locked transitions through a Beat rebuild.

 A rebuild makes new slots. A slot with the same Beat, cue and source as before gets its
 camera back, and a locked transition stays where it was if that slot still ends on a
 real cut. Anything that no longer matches is dropped rather than guessed.
 """
 old={}
 for s in old_scenes:
  k=_slot_key(s)
  if k[0] and k not in old:old[k]=s
 cuts=set(transitions.documentary_cuts(new_scenes));lengths=transitions.shot_frames(new_scenes,sorted(cuts))
 for i,s in enumerate(new_scenes):
  before=old.get(_slot_key(s))
  if not before:continue
  if before.get('camera'):s['camera']=copy.deepcopy(before['camera'])
  if before.get('transition_locked') and i in cuts:
   key,frames=transitions.fit_frames(before.get('transition') or 'cut',int(before.get('transition_handle_frames') or 0),*lengths[i])
   s.update(transition=key,transition_handle_frames=frames,transition_source=before.get('transition_source') or 'manual',transition_locked=True)

def _documentary_beat_build_work(pid, root, data, report):
 """The Beat build, with progress. Raises ValueError for anything the user can fix."""
 from documentary import load_plan
 from documentary_storyboard import prepare
 from strict_cuts import verify_source_endpoint
 from production import document
 p=load(pid)
 if p.get('edit_mode')!='documentary':raise ValueError('This operation is available only in documentary mode.')
 if data.get('confirmed') is not True:raise ValueError('Explicit confirmation of the proposed gap ranges and repeats is required.')
 # Say what is missing before comparing versions. A build attempted before the script
 # and SRT exist used to report that the project had changed, which is true but sends
 # the user looking for an edit that never happened.
 if not (p.get('production_script') or {}).get('text','').strip():raise ValueError('Upload the production script before building the Beat timeline.')
 if not ((p.get('srt') or {}).get('blocks')):raise ValueError('Upload the original SRT before building the Beat timeline.')
 if not p.get('voiceover'):raise ValueError('Upload the narration before building the Beat timeline.')
 current=load_plan(root)
 if data.get('project_version')!=p.get('updated') or data.get('plan_revision')!=current['revision']:raise ValueError('The project or sound-bite plan changed; review the proposal again.')
 # A rebuild replaces this project's own Beat timeline. Refusing whenever any bite
 # existed meant a script corrected after a build could never be rebuilt and the
 # storyboard stayed blocked for good. Only an unrelated saved plan is refused.
 record=p.get('documentary_beat_review') or {}
 if current['bites'] and not record and data.get('replace_beat_timeline') is not True:raise ValueError('Existing sound bites will not be replaced automatically; remove them in the documentary tools first.')
 if current['bites'] and data.get('replace_beat_timeline') is not True:raise ValueError(f"This rebuild replaces the saved Beat timeline and its {len(current['bites'])} sound bites. Confirm the replacement in the Beat picture plan first.")
 script=(p.get('production_script') or {}).get('text','')
 if data.get('script_sha256')!=hashlib.sha256(script.encode()).hexdigest():raise ValueError('The production script changed; review the proposal again.')
 from documentary_beats import read_beats, is_strict_pipeline_script, reconcile_pause_clocks
 from documentary_beat_plan import fit,frame_limits
 report('read',0.5)
 beats, pause_fixes = reconcile_pause_clocks(read_beats(script))
 report('read',1.0)
 # Source bytes, SRT, script, voiceover, portrait roles and asset revisions are
 # rechecked at commit. This fingerprint is an input identity, not a visual QA.
 starting_inputs_fingerprint=_auto_fingerprint(p,root,beats)
 if data.get('auto_fingerprint') and data['auto_fingerprint']!=starting_inputs_fingerprint:
  raise ValueError('The inputs changed since the automatic build was queued. No timeline was saved; rebuild the latest inputs.')
 strict=is_strict_pipeline_script(script)
 if strict:
  from documentary_strict import validate as validate_strict
  checked=validate_strict(p,root,beats,frame_limits(root,p['assets']))
  if checked['issues']:raise ValueError(' '.join(checked['issues']))
  if data.get('scripted_review_beat') or data.get('scripted_review_source'):
   raise ValueError('Exact Beat execution cannot replace a Beat source. Correct the Full source line in the production script.')
  if data.get('approved_gaps') or data.get('approved_overlaps') or data.get('allow_silent_tail') is True:
   raise ValueError('Exact Beat execution cannot add gap footage, approve overlapping sources or extend a silent tail. Correct the production script.')
  adjustments=[]
  report('validate',1.0)
 else:
  # Legacy Video File scripts keep the prior explicit fit-and-review workflow.
  # Pipeline v5 Full source scripts never enter this path.
  # v21: the last few seconds of narration after the final Beat are closed in the
  # same shot (speech) or the film ends on the last word (silence).
  from documentary_beat_plan import close_end_tail
  beats,tail_note=close_end_tail(p,beats)
  beats,adjustments,issues=fit(beats,p['assets'],data.get('scripted_review_beat'),data.get('scripted_review_source'),frame_limits(root,p['assets']))
  if tail_note:adjustments=[tail_note]+list(adjustments)
  if issues:raise ValueError(' '.join(issues))
  checked=None
  report('fit',1.0)
 # Defense in depth: reject even a stale/forged client payload that supplies
 # "approved" footage for a narration hole. Only a mapped script Beat may fill it.
 from documentary_beat_plan import narration_gaps
 from documentary_gap_policy import is_subframe_gap
 uncovered, gap_issues=narration_gaps(p,beats)
 if gap_issues:
  raise ValueError(' '.join(gap_issues))
 if any(not is_subframe_gap(g.get('narration_in_ms',0),g.get('narration_out_ms',0))
        for g in (data.get('approved_gaps') or [])):
  raise ValueError('Unscripted gap footage is not allowed. Assign the footage in the production script and rebuild.')
 fitted={b['label']:{'source_file':b['source_file'],'source_in_ms':b['source_in_ms'],'source_out_ms':b['source_out_ms']} for b in beats}
 # A confirmed replacement starts from an empty picture plan. `prepare` refuses to
 # overwrite an existing storyboard on its own, which is right for an accidental
 # build and wrong here: the user has just confirmed this exact replacement, and
 # without clearing it the rebuild could never run. The old scenes are kept in
 # memory (`previous`) and put back if anything below fails, so a failed rebuild
 # never leaves the project without its timeline.
 previous={'scenes':p.get('scenes') or [],'review':p.get('documentary_beat_review')}
 replacing=bool(current['bites'] or p.get('scenes')) and data.get('replace_beat_timeline') is True
 if replacing:
  p['scenes']=[];p.pop('documentary_beat_review',None)
 try:
  staged,plan=prepare(p,root,data.get('approved_gaps') or [],data.get('approved_overlaps') or [],data.get('allow_silent_tail') is True,lambda path:probe(path)['has_audio'],beats=beats,allow_consecutive_bites=data.get('approve_consecutive_bites') is True,fitted_ranges=fitted,strict=strict,clamp_pauses=data.get('clamp_pauses_to_narration_end') is True)
  # A rebuilt plan must invalidate the previous timeline/audio/schedule revision.
  # prepare() initially assigns revision 1 for a *new* plan.
  plan['revision']=int(current.get('revision') or 0)+1
 except Exception:
  if replacing:
   p['scenes']=previous['scenes']
   if previous['review'] is not None:p['documentary_beat_review']=previous['review']
  raise
 staged['documentary_beat_adjustments']=list(pause_fixes)+list(adjustments)+list(staged.get('documentary_beat_adjustments') or [])
 # New documentaries should look edited on their FIRST build, not silently remain
 # all hard cuts and static frames until a hidden second click is discovered.
 # Existing projects and deliberate user choices are never reset by a rebuild.
 if not previous['scenes'] and not staged.get('documentary_transition_choice'):
  staged['documentary_transition_choice']={'auto':'cinematic','duration':'quick','camera_auto':False,
                                          'origin':'first_beat_build'}
 _reapply_transition_choice(staged)
 _carry_cinematic(previous.get('scenes') or [],staged.get('scenes') or [])
 # This build uses transitions only. Old scene camera metadata may remain for
 # compatibility/rollback, but no renderer or preview applies it.
 if strict:
  staged['documentary_beat_review']['source_signatures']=checked['source_signatures']
  staged['documentary_beat_review']['visual_reviews']={}
  staged['documentary_beat_review']['execution_mode']='pipeline_v5_strict'
  decision_path=root/'reviews'/'documentary_frame_decisions.json'
  if decision_path.is_file():
   try:
    old_decisions=json.loads(decision_path.read_text(encoding='utf-8'))
   except (OSError,ValueError,TypeError):
    old_decisions={'unreadable':True,'changes':[]}
   staged['documentary_beat_review']['invalidated_frame_decisions']={
    'reason':'A strict storyboard rebuild requires a fresh frame review.',
    'at':time.time(),
    'changes':copy.deepcopy(old_decisions.get('changes') or []),
    'previous_approvals':copy.deepcopy((previous.get('review') or {}).get('frame_adjustments') or [])}
 report('prepare',1.0)
 assets={(a.get('original_name') or a.get('name')):a for a in p['assets']}
 # Rebuilding must be fast: reuse the script's validated source ranges and inspect
 # just the last required source window by seeking to it. A full every-frame scan
 # belongs to the strict export audit, not to each timeline rebuild. In particular,
 # adding a new source must never re-decode forty other multi-minute uploads.
 names=sorted({b['source_file'] for b in beats})
 for index,name in enumerate(names):
  asset=next(a for a in p['assets'] if (a.get('original_name') or a.get('name'))==name)
  path=root/asset['path']
  last_ms=max([b['source_out_ms'] for b in beats if b['source_file']==name]+[g['source_out_ms'] for g in data.get('approved_gaps',[]) if g['source_file']==name])
  report('frames',index/max(1,len(names)),source=name,
         detail=f'Checking last required picture in {name} ({index+1}/{len(names)})')
  verify_source_endpoint(path,last_ms,source_name=name)
 report('frames',1.0)
 staged['edit_script_hash']=hashlib.sha256(document(p).encode()).hexdigest()
 staged['documentary_beat_review']['at']=time.time()
 # Remember which inputs this timeline was built from, so the automatic builder
 # rebuilds only when one of them really changes.
 if data.get('auto_fingerprint'):staged['documentary_beat_review']['auto_fingerprint']=data['auto_fingerprint']
 else:
  try:
   from documentary_beats import read_beats as _rb
   staged['documentary_beat_review']['auto_fingerprint']=_auto_fingerprint(staged,root,_rb((staged.get('production_script') or {}).get('text','')))
  except Exception:pass
 staged['auto_build']={'status':'built','reason':'','at':time.time()}
 staged['timeline_needs_rebuild']=False
 staged['timeline_rebuilt_at']=time.time()
 report('save',0.4)
 # All proposal/build modes (not only the rarely used strict mode) must use
 # compare-and-save under the same project lock. A newer manual edit, new
 # download, changed SRT, image role or audio-plan revision invalidates our
 # older staging copy. Never capture rollback bytes before the revision check.
 from documentary_rebuild_guards import assert_rebuild_is_current
 from documentary import load_plan as _load_latest_plan
 with LOCKS[pid]:
  latest=load(pid)
  latest_plan=_load_latest_plan(root)
  assert_rebuild_is_current(
   p.get('updated'),latest.get('updated'),
   current['revision'],latest_plan['revision'],
   starting_inputs_fingerprint,_auto_fingerprint(latest,root,beats))
  if strict:
   from documentary_strict import source_signatures as strict_source_signatures
   latest_signatures=strict_source_signatures(latest,root,beats)
   expected_script=hashlib.sha256(script.encode()).hexdigest()
   current_script=hashlib.sha256((latest.get('production_script') or {}).get('text','').encode()).hexdigest()
   if current_script!=expected_script or latest_signatures!=checked['source_signatures']:
    raise ValueError('An exact source or production script changed during the strict storyboard build. No timeline was saved; review the current script and try again.')
  # Check job cancellation before any project data or audio plan is committed.
  report('save',0.8)
  oldpath=root/'documentary_plan.json';old=oldpath.read_bytes() if oldpath.exists() else None
  project_path=root/'project.json';old_project=project_path.read_bytes() if project_path.exists() else None
  decision_path=root/'reviews'/'documentary_frame_decisions.json'
  decision_archive=(root/'reviews'/f'documentary_frame_decisions_invalidated_{uuid.uuid4().hex}.json') if strict and decision_path.is_file() else None
  try:
   write(oldpath,plan)
   if decision_archive:decision_path.replace(decision_archive)
   save(staged)
  except Exception:
   if old is None:oldpath.unlink(missing_ok=True)
   else:
    temp=oldpath.with_name(oldpath.name+'.'+uuid.uuid4().hex+'.restore');temp.write_bytes(old);temp.replace(oldpath)
   if decision_archive and decision_archive.exists():decision_archive.replace(decision_path)
   if old_project is not None:project_path.write_bytes(old_project)
   raise
 report('save',1.0)
 # A cutaway file chosen before this build is applied now (v20).
 try:
  if _apply_pending_cutaways(pid):staged=load(pid)
 except Exception:pass
 # Start the review mix straight away, so the timeline plays without another click.
 # It runs on its own thread; a build that cannot be previewed yet still succeeds.
 try:_start_documentary_audio(pid)
 except Exception:pass
 return public(staged)

@app.post('/api/projects/<pid>/documentary-beat-storyboard')
def build_documentary_beat_storyboard(pid):
 """Start the Beat build as a job and return at once.

 The build decodes every source up to its last used frame, which is far too long to
 hold a request open: the editor looked frozen with no way to tell whether anything
 was happening. The work is unchanged, it simply runs where it can be watched.
 """
 import documentary_beat_build
 data=request.get_json(silent=True) or {}
 with LOCKS[pid]:
  editable(pid);root=folder(pid)
  try:
   job=documentary_beat_build.start(pid,lambda report:_documentary_beat_build_work(pid,root,data,report))
  except ValueError as e:raise BadRequest(str(e))
 return jsonify(job),202

@app.get('/api/projects/<pid>/documentary-beat-storyboard')
def documentary_beat_storyboard_status(pid):
 """How the build is going, and its finished storyboard once there is one."""
 import documentary_beat_build
 with LOCKS[pid]:
  if load(pid).get('edit_mode')!='documentary':raise BadRequest('This operation is available only in documentary mode.')
  job=documentary_beat_build.snapshot(pid)
  if job.get('status')=='done':
   built=documentary_beat_build.result(pid)
   job['project']=built
   job['scenes']=len((built or {}).get('scenes') or [])
 return jsonify(job)

@app.post('/api/projects/<pid>/documentary-beat-storyboard/cancel')
def cancel_documentary_beat_storyboard(pid):
 import documentary_beat_build
 with LOCKS[pid]:
  if not documentary_beat_build.cancel(pid):raise BadRequest('No Beat build is running.')
  return jsonify(documentary_beat_build.snapshot(pid))

@app.get('/api/projects/<pid>/documentary-beat-review')
def documentary_beat_review(pid):
 from documentary_beats import is_strict_pipeline_script
 from documentary_strict import review_state
 with LOCKS[pid]:
  p=load(pid);root=folder(pid);text=(p.get('production_script') or {}).get('text','')
  if not is_strict_pipeline_script(text):raise BadRequest('This project does not use the separate strict-script review workflow.')
  state=review_state(p,root)
  record=p.get('documentary_beat_review') or {}
  state['built']=bool(record.get('strict_execution'))
  state['execution_mode']=record.get('execution_mode')
  state['invalidated_frame_decisions']=record.get('invalidated_frame_decisions')
  return jsonify(state)

@app.post('/api/projects/<pid>/documentary-beat-review/<label>')
def save_documentary_beat_review(pid,label):
 from documentary_beats import is_strict_pipeline_script
 from documentary_strict import make_review,review_state
 data=request.get_json(silent=True) or {}
 with LOCKS[pid]:
  editable(pid);p=load(pid);root=folder(pid);text=(p.get('production_script') or {}).get('text','')
  if not is_strict_pipeline_script(text):raise BadRequest('This project does not use the separate strict-script review workflow.')
  record=p.get('documentary_beat_review') or {}
  if not record.get('strict_execution'):raise BadRequest('Build the strict Beat storyboard before recording visual review.')
  try:review=make_review(p,root,label,data.get('status'),data.get('detail',''))
  except ValueError as e:raise BadRequest(str(e))
  record.setdefault('visual_reviews',{})[str(label)]=review
  p['documentary_beat_review']=record
  p['updated']=time.time();save(p)
  state=review_state(p,root);state['built']=True;state['execution_mode']=record.get('execution_mode')
  return jsonify(state)

@app.post('/api/projects/<pid>/documentary-frame-decisions/<label>')
def approve_documentary_frame_quantization(pid,label):
 """Record an explicit, one-output-frame quantisation exception for a Beat."""
 from documentary import load_plan,annotate_plan,build_timeline
 from documentary_beats import is_strict_pipeline_script
 from documentary_render_plan import load_decisions
 data=request.get_json(silent=True) or {};detail=str(data.get('detail') or '').strip()
 if not detail:raise BadRequest('Explain the one-frame quantisation exception you are approving.')
 with LOCKS[pid]:
  editable(pid);p=load(pid);root=folder(pid);record=p.get('documentary_beat_review') or {}
  if not is_strict_pipeline_script((p.get('production_script') or {}).get('text','')) or not record.get('strict_execution'):
   raise BadRequest('Build the Beat storyboard before approving frame quantisation.')
  from documentary_strict import review_blockers
  blockers=review_blockers(p,root)
  if blockers:raise BadRequest('Resolve strict script and visual review blockers first: '+ ' '.join(blockers))
  try:
   sound=annotate_plan(p,root,load_plan(root));build_timeline(p,sound)
   frame_state=documentary_frame_preflight(pid,copy.deepcopy(p),root,copy.deepcopy(sound))
  except (ValueError,OSError,KeyError,TypeError) as e:raise BadRequest(str(e))
  if frame_state['status']=='checking':raise BadRequest('Frame preflight is still running. Refresh export readiness and retry when it is done.')
  if frame_state['status']=='error':raise BadRequest(frame_state.get('error') or 'Frame preflight failed.')
  preview=frame_state['report']
  quant=next((q for q in preview.get('quantization',[]) if str(q.get('label'))==str(label)),None)
  if not quant:raise BadRequest(f'Beat {label} has no pending frame quantisation decision.')
  delta=int(quant.get('difference_frames') or 0)
  if delta not in (-1,1):raise BadRequest(f'Beat {label} differs by {delta} frame(s); correct the production script range rather than approving an adjustment.')
  asset=next((a for a in p.get('assets',[]) if a.get('id')==quant.get('asset_id')),None)
  if not asset:raise BadRequest(f'Beat {label}: exact source is missing.')
  source=(root/asset.get('path','')).resolve()
  if asset.get('kind')!='video' or not source.is_relative_to(root.resolve()/'sources') or not source.is_file():raise BadRequest(f'Beat {label}: exact source video is missing.')
  source_stat=source.stat();source_signature=(source_stat.st_size,source_stat.st_mtime_ns)
  source_id=asset['id'];asset_revision=asset.get('revision');asset_name=asset.get('original_name') or asset.get('name')
  script_sha=hashlib.sha256((p.get('production_script') or {}).get('text','').encode()).hexdigest()
  plan_revision=sound.get('revision');output_fps=preview.get('output_fps')
  frame_start=quant['requested_start_frame'];frame_end=quant['requested_end_frame_exclusive']
  timeline_in=quant['timeline_in_ms'];timeline_out=quant['timeline_out_ms']
  root_path=root
  existing=load_decisions(root) if (root/'reviews'/'documentary_frame_decisions.json').exists() else None
  if existing and (existing.get('script_sha256')!=script_sha or existing.get('plan_revision')!=plan_revision or existing.get('source_fps')!=output_fps):
   raise BadRequest('Saved frame decisions belong to an older script or sound plan. Rebuild and review before approving this interval.')
 # Hashing a long source can take time. Do it outside the project lock, then verify
 # the path, revision and stat signature again before recording the decision.
 try:
   if delta>0:
    from strict_cuts import inspect_video
    inspect_video(source,int(frame_end)+1)
   with source.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
 except Exception as e:raise BadRequest(f'Beat {label}: cannot verify the approved source-frame adjustment: {e}')
 with LOCKS[pid]:
   p=load(pid);root=folder(pid);record=p.get('documentary_beat_review') or {}
   current_asset=next((a for a in p.get('assets',[]) if a.get('id')==source_id),None)
   if hashlib.sha256((p.get('production_script') or {}).get('text','').encode()).hexdigest()!=script_sha or not current_asset or current_asset.get('revision')!=asset_revision or (current_asset.get('original_name') or current_asset.get('name'))!=asset_name:
    raise BadRequest('The script or source changed while the frame decision was being prepared. Refresh and review again.')
   now_source=(root/current_asset.get('path','')).resolve();stat=now_source.stat()
   if now_source!=source or (stat.st_size,stat.st_mtime_ns)!=source_signature:raise BadRequest('The source file changed while the frame decision was being prepared. Refresh and review again.')
   from documentary_strict import review_blockers
   blockers=review_blockers(p,root)
   if blockers:raise BadRequest('Resolve strict script and visual review blockers first: '+ ' '.join(blockers))
   latest_plan=load_plan(root)
   if latest_plan.get('revision')!=plan_revision:raise BadRequest('The sound-bite plan changed. Refresh and review the current storyboard.')
   path=root_path/'reviews'/'documentary_frame_decisions.json'
   latest=load_decisions(root) if path.exists() else None
   if latest and (latest.get('script_sha256')!=script_sha or latest.get('plan_revision')!=plan_revision or latest.get('source_fps')!=output_fps):raise BadRequest('Saved frame decisions belong to an older script or sound plan. Rebuild and review before approving this interval.')
   change={'asset_id':source_id,'asset_revision':asset_revision,'source':asset_name,'source_sha256':digest,
           'source_start_frame':frame_start,'source_end_frame':frame_end,
           'timeline_in_ms':timeline_in,'timeline_out_ms':timeline_out,'delta':delta,'label':str(label)}
   changes=[x for x in (latest or {}).get('changes',[]) if x.get('label')!=str(label)];changes.append(change)
   write(path,{'version':1,'script_sha256':script_sha,'plan_revision':plan_revision,'source_fps':output_fps,'changes':changes})
   record.setdefault('frame_adjustments',[])
   record['frame_adjustments']=[x for x in record['frame_adjustments'] if x.get('beat_label')!=str(label)]
   approved_at=time.time()
   record['frame_adjustments'].append({'beat_label':str(label),'source':asset_name,
       'requested_start_frame':frame_start,'requested_end_frame_exclusive':frame_end,
       'delta_frames':delta,'detail':detail,'explicit_approval':True,'approved_at':approved_at})
   p['documentary_beat_review']=record;p['updated']=approved_at;save(p)
   return jsonify({'approved':True,'beat_label':str(label),'delta_frames':delta,
                   'detail':detail,'approved_at':approved_at,'source':asset_name})

@app.get('/api/projects/<pid>/documentary-timeline')
def documentary_timeline(pid):
 from documentary import load_plan,annotate_plan,build_timeline
 with _reading(pid):
  p=load(pid)
  if p.get('edit_mode','review')!='documentary':raise BadRequest('Documentary timeline is available only in a documentary project.')
  try:return jsonify(build_timeline(p,annotate_plan(p,folder(pid),load_plan(folder(pid)))))
  except ValueError as e:raise BadRequest(str(e))

def documentary_review_preview_state(pid):
 from documentary import load_plan,annotate_plan
 from documentary_audio import AUDIO_PROCESSING_VERSION
 root=folder(pid);p=load(pid)
 if p.get('edit_mode','review')!='documentary':return {'status':'unavailable'}
 try:
  record=json.loads((root/'reviews'/'documentary_review_preview.json').read_text(encoding='utf-8'))
  name=record['output']
  if not re.fullmatch(r'documentary_review_[a-f0-9]{32}\.mp4',name) or not (root/'renders'/name).is_file():return {'status':'unavailable'}
  plan=load_plan(root)
  # A preview made for a different frame shape is not a preview of this film. Records
  # written before the shape was recorded are judged on the values they carry.
  import documentary_preview
  shape=documentary_preview.preview_size(p)
  if record.get('width') is not None and (record.get('width'),record.get('height'))!=shape:return {'status':'stale'}
  if record.get('audio_processing_version')!=AUDIO_PROCESSING_VERSION or record.get('project_version')!=p.get('updated') or record.get('plan_revision')!=plan['revision'] or any(x.get('stale_reasons') for x in annotate_plan(p,root,plan)['bites']):return {'status':'stale'}
  if (p.get('documentary_beat_review') or {}).get('fitted_beats') and record.get('renderer')!='export_matched_lowres':return {'status':'stale'}
  label=('Export-renderer low-resolution preview: picture transitions and channel overlays are encoded, not merely simulated.'
         if record.get('renderer')=='export_matched_lowres' else
         'Legacy cut-only review preview; not transition-accurate.')
  return {'status':'ready','url':f'/api/projects/{pid}/documentary-review-preview/{name}',
          'detail':label+' Review-only; not a final export. SRT burn-in must be checked separately.',
          'renderer':record.get('renderer'),'narration_lufs':record.get('narration_lufs'),
          'sound_bite_levels':record.get('sound_bite_levels',[])}
 except (OSError,ValueError,KeyError,TypeError):return {'status':'unavailable'}

@app.get('/api/projects/<pid>/documentary-bite-speech')
def documentary_bite_speech_status(pid):
 from documentary import load_plan,annotate_plan
 import bite_speech
 with LOCKS[pid]:
  p=load(pid)
  if p.get('edit_mode','review')!='documentary':raise BadRequest('Sound-bite speech is available only in a documentary project.')
  plan=annotate_plan(p,folder(pid),load_plan(folder(pid)))
 ok,reason=bite_speech.available()
 # Speech needs two separate things -- the package and the model -- and saying only
 # "not installed" leaves the user with nowhere to go. The setup state names which half
 # is missing and whether it can be installed from here.
 import speech_setup
 setup=speech_setup.status()
 return jsonify({'available':ok,'detail':reason or setup['message'],
                 'setup':setup,
                 'model':bite_speech.model_dir().name if ok else '',
                 'revision':plan['revision'],'captions':int(p.get('captions') or 0),
                 'bites':[{'id':b['id'],'script_beat':b.get('script_beat'),'has_speech':bool(b.get('speech'))} for b in plan['bites']]})

@app.post('/api/projects/<pid>/documentary-bites/<bid>/speech')
def transcribe_documentary_bite(pid,bid):
 """Transcribe one saved bite locally; save only the words, never the media."""
 from documentary import load_plan,annotate_plan
 import bite_speech
 from documentary_speech import save
 root=folder(pid);data=request.get_json(silent=True) or {}
 with LOCKS[pid]:
  p=load(pid)
  if p.get('edit_mode','review')!='documentary':raise BadRequest('Sound-bite speech is available only in a documentary project.')
  plan=load_plan(root)
  if data.get('revision')!=plan['revision']:raise BadRequest('The sound-bite plan changed. Reload before transcribing.')
  bite=next((b for b in plan['bites'] if b['id']==bid),None)
  if not bite:raise NotFound('That sound bite is no longer in the plan.')
  asset=next((a for a in p.get('assets',[]) if a.get('id')==bite.get('asset_id')),None)
  reasons=annotate_plan(p,root,{'bites':[dict(bite)]})['bites'][0].get('stale_reasons') or []
  if reasons:raise BadRequest(' '.join(reasons))
  source=(root/asset.get('path','')).resolve()
  if not asset or not source.is_relative_to((root/'sources').resolve()) or not source.is_file():raise BadRequest('The sound-bite source video is missing.')
 try:
  segments,meta=bite_speech.transcribe(source,bite['source_in_s'],bite['source_out_s'])
  entry=save(root,plan,bite,asset,segments,meta)
 except (ValueError,OSError,KeyError,TypeError) as e:raise BadRequest(str(e))
 with LOCKS[pid]:
  current=load(pid)
  if current.get('updated')!=p.get('updated'):raise BadRequest('The project changed while transcribing. Review the words again before saving.')
 return jsonify({'bite_id':bid,'segments':entry['segments'],'transcript':entry['transcript'],
                 'note':'Machine transcription of this bite only. Listen before publishing; speaker identity is not established by audio.'})

@app.delete('/api/projects/<pid>/documentary-bites/<bid>/speech')
def remove_documentary_bite_speech(pid,bid):
 from documentary_speech import load as load_speech,path as speech_path
 root=folder(pid)
 with LOCKS[pid]:
  p=load(pid)
  if p.get('edit_mode','review')!='documentary':raise BadRequest('Sound-bite speech is available only in a documentary project.')
  data=load_speech(root)
  if bid not in data['bites']:raise NotFound('That sound bite has no saved speech.')
  data['bites'].pop(bid);write(speech_path(root),data)
 return jsonify({'removed':bid})

@app.get('/api/projects/<pid>/documentary-cutaways')
def get_documentary_cutaways(pid):
 with LOCKS[pid]:
  p=load(pid)
  if p.get('edit_mode')!='documentary':raise BadRequest('Documentary projects only.')
  return jsonify({'cutaways':p.get('documentary_cutaways') or [],'version':1,
                  'note':'Reviewed picture changes only. The original soundbite audio is not edited.'})

def _validated_cutaways(p,root,cutaways,sound=None):
 """Tie approvals to the current script/source and check the picture still fits.

 Raises ValueError with a readable reason. Needs a built Beat storyboard.
 `sound` (the annotated plan) may be passed in when checking many rows in a row.
 """
 from documentary import load_plan,annotate_plan
 from documentary_render_plan import plan as make_picture
 # Tie each approval to the current script and source revision. Rebuilds cannot
 # quietly carry a cutaway into a different case or changed source file.
 current_hash=hashlib.sha256(((p.get('production_script') or {}).get('text') or '').encode()).hexdigest()
 for row in cutaways:
  if row['approved']:
   row['approved_script_sha256']=current_hash
   hit=[a for a in p.get('assets') or [] if (a.get('original_name') or a.get('name'))==row['picture_source']]
   if len(hit)!=1:raise ValueError(f"{row['id']}: uploaded picture source missing or ambiguous.")
   row['approved_picture_revision']=str(hit[0].get('revision') or '')
  else:
   row['approved_script_sha256']='';row['approved_picture_revision']=''
 staged=dict(p);staged['documentary_cutaways']=cutaways
 if any(x['approved'] for x in cutaways):
  try:
   if sound is None:sound=annotate_plan(staged,root,load_plan(root))
   picture=make_picture(staged,root,sound)
  except (KeyError,TypeError,OSError) as exc:raise ValueError(str(exc))
  if not picture['picture_compatible']:raise ValueError(' '.join(picture['errors']))
 return cutaways

def _apply_pending_cutaways(pid):
 """After a Beat build: apply a cutaway file that was chosen before the build (v20)."""
 from documentary_cutaways import parse
 with LOCKS[pid]:
  p=load(pid);pending=p.get('documentary_cutaways_pending')
  if not pending or not (p.get('documentary_beat_review') or {}).get('fitted_beats'):return False
  try:
   p['documentary_cutaways']=_validated_cutaways(p,folder(pid),parse(pending.get('ledger') or ''))
   p.pop('documentary_cutaways_pending',None)
  except (ValueError,TypeError) as exc:
   pending['error']=str(exc)[:400]
  save(p)
  return 'documentary_cutaways_pending' not in p

@app.post('/api/projects/<pid>/documentary-cutaways')
def save_documentary_cutaways(pid):
 from documentary_cutaways import parse
 data=request.get_json(silent=True) or {}
 if not isinstance(data,dict):raise BadRequest('Provide a CUTAWAY ledger.')
 ledger=data.get('ledger',data.get('cutaways', []))
 try: cutaways=parse(ledger)
 except (ValueError,TypeError) as exc:raise BadRequest(str(exc))
 with LOCKS[pid]:
  editable(pid);p=load(pid);root=folder(pid)
  if p.get('edit_mode')!='documentary':raise BadRequest('Cutaways are for documentary projects.')
  if not (p.get('documentary_beat_review') or {}).get('fitted_beats'):
   # v20: the file can be chosen before the Beat timeline exists. It is checked now,
   # kept, and applied by the next successful Beat build.
   if not cutaways:
    p.pop('documentary_cutaways_pending',None);save(p)
    return jsonify({'version':1,'pending':False,'cutaways':[],'active':0,'note':'Cutaway file removed.'})
   if not isinstance(ledger,str):ledger=json.dumps(ledger)
   p['documentary_cutaways_pending']={'ledger':ledger,'rows':len(cutaways),'name':str(data.get('name') or '')[:160],
                                      'at':time.time()}
   save(p)
   return jsonify({'version':1,'pending':True,'rows':len(cutaways),
                   'note':'Saved. It is applied automatically when the Beat timeline is built.'})
  try:cutaways=_validated_cutaways(p,root,cutaways)
  except ValueError as exc:raise BadRequest(str(exc))
  p['documentary_cutaways']=cutaways
  p.pop('documentary_cutaways_pending',None)
  save(p)
  return jsonify({'version':1,'cutaways':cutaways, 'active':sum(bool(x['approved']) for x in cutaways),
                  'note':'Picture only; uninterrupted interview audio is preserved. Render a new preview to verify.'})

_CUTAWAY_ID=re.compile(r'^(CUTAWAY-\d{3,5})\s*:\s*',re.I)
@app.post('/api/projects/<pid>/documentary-cutaways/approve')
def approve_documentary_cutaways(pid):
 """v23: approve (or turn off) the ticked cutaway rows.

 Every ticked row that passes the checks is approved; a row that fails stays off and
 its reason is returned, so one bad row no longer blocks all the others. The checks
 themselves are the same as before (same Beat, same film clock, file present, range
 length), and the interview audio is never touched.
 """
 from documentary_cutaways import parse
 from documentary import load_plan,annotate_plan
 data=request.get_json(silent=True) or {}
 ids=data.get('ids');approve=data.get('approved',True)
 if not isinstance(ids,list) or not ids or not all(isinstance(x,str) for x in ids) or not isinstance(approve,bool):
  raise BadRequest('Tick at least one cutaway.')
 want={x.strip().upper() for x in ids}
 with LOCKS[pid]:
  editable(pid);p=load(pid);root=folder(pid)
  if p.get('edit_mode')!='documentary':raise BadRequest('Cutaways are for documentary projects.')
  if not (p.get('documentary_beat_review') or {}).get('fitted_beats'):raise BadRequest('Build the Beat timeline first.')
  try:rows=parse(p.get('documentary_cutaways') or [])
  except (ValueError,TypeError) as exc:raise BadRequest(str(exc))
  known={r['id'].upper() for r in rows}
  if not want<=known:raise BadRequest('Some ticked cutaways are no longer in the plan. Reopen Documentary tools.')
  rejected={}
  if not approve:
   for r in rows:
    if r['id'].upper() in want:r['approved']=False
   try:rows=_validated_cutaways(p,root,rows)
   except ValueError as exc:raise BadRequest(str(exc))
  else:
   try:sound=annotate_plan(p,root,load_plan(root))
   except (ValueError,KeyError,TypeError,OSError) as exc:raise BadRequest(str(exc))
   wanted=[dict(r,approved=r['approved'] or r['id'].upper() in want) for r in rows]
   try:rows=_validated_cutaways(p,root,copy.deepcopy(wanted),sound)      # usual case: all pass at once
   except ValueError as first:
    # Something failed. Add the rows one at a time in film order and keep each one
    # that still passes with the ones before it.
    if not _CUTAWAY_ID.match(str(first)):
     raise BadRequest('No cutaway can be approved until this is fixed: '+str(first))
    # v24: a problem in the picture plan itself (not in any cutaway) would otherwise
    # be reported against every row. Check the plan with no cutaways first.
    from documentary_render_plan import plan as make_picture
    base=make_picture(dict(p,documentary_cutaways=[]),root,sound)
    if not base['picture_compatible']:
     raise BadRequest('No cutaway can be approved until the picture plan is fixed (Render MP4 needs this too): '+' '.join(base['errors'][:3]))
    current=[dict(r,approved=False) for r in rows]
    for i,r in enumerate(wanted):
     if not r['approved']:continue
     trial=copy.deepcopy(current);trial[i]['approved']=True
     try:current=_validated_cutaways(p,root,trial,sound)
     except ValueError as exc:
      msg=str(exc);m=_CUTAWAY_ID.match(msg)
      rejected[r['id']]=msg[m.end():] if m else msg
    rows=current
  p['documentary_cutaways']=rows
  save(p)
  return jsonify({'version':1,'cutaways':rows,'active':sum(bool(x['approved']) for x in rows),'rejected':rejected})

@app.get('/api/projects/<pid>/documentary-beat-playback-schedule')
def documentary_beat_playback_schedule(pid):
 """Verified source ranges for browser review playback, not a final render."""
 from documentary import load_plan,annotate_plan
 from documentary_frame_audit import playback_schedule
 root=folder(pid)
 # Read under the project lock; audit outside it. The frame walk takes from seconds to
 # over a minute after a build, and holding the lock for it stalled every other request
 # for the project (saving, Documentary tools, thumbnails) until it finished. A separate
 # per-project lock keeps two tabs from running the same audit twice.
 with _reading(pid):
  p=load(pid)
  if p.get('edit_mode')!='documentary' or not p.get('documentary_beat_review'):raise BadRequest('This is not a Beat storyboard.')
  try:plan=annotate_plan(p,root,load_plan(root))
  except (ValueError,OSError,KeyError,TypeError) as e:raise BadRequest(str(e))
 try:
  key=(p.get('updated'),plan['revision'])
  notes=[]
  with SCHEDULE_LOCKS[pid]:
   cached=SCHEDULE_CACHE.get(pid)
   if cached and cached[0]==key:
    events=cached[1]
    notes=list(cached[2] if len(cached)>2 else [])
   else:
    # Deterministic for a project version, so it is also kept on disk across restarts.
    events=_schedule_from_disk(pid,key)
    if events is None:
     events=playback_schedule(p,root,plan,notes)
     with LOCKS[pid]:
      if load(pid).get('updated')==key[0]:_schedule_to_disk(pid,key,events)
    SCHEDULE_CACHE[pid]=(key,events,notes)
  # A schedule served from disk or memory was not audited again, so its notes are
  # rebuilt from the cheap part only: comparing the recorded script hash.
  if not notes:
   try:
    from documentary_frame_audit import stale_script_message
    record=p.get('documentary_beat_review') or {}
    text=(p.get('production_script') or {}).get('text','')
    recorded=record.get('script_sha256')
    if text and recorded and recorded!=hashlib.sha256(text.encode()).hexdigest():
     notes=[stale_script_message(p,record,text)]
   except (ValueError,OSError,KeyError,TypeError):
    notes=[]
  if any(c.get('approved') for c in (p.get('documentary_cutaways') or [])):
   from documentary_cutaways import split_events
   events=split_events(p,root,events)
  return jsonify({'project_version':p.get('updated'),'plan_revision':plan['revision'],'events':events,'warnings':notes})
 except (ValueError,OSError,KeyError,TypeError) as e:raise BadRequest(str(e))

@app.post('/api/projects/<pid>/documentary-review-preview')
def start_documentary_review_preview(pid):
 import documentary_preview
 from documentary import load_plan,annotate_plan
 root=folder(pid);data=request.get_json(silent=True) or {}
 with LOCKS[pid]:
  p=load(pid)
  if p.get('edit_mode','review')!='documentary':raise BadRequest('Documentary preview is available only in a documentary project.')
  plan=load_plan(root)
  try:
   if not (p.get('documentary_beat_review') or {}).get('fitted_beats'):
    documentary_preview.picture_plan(p,annotate_plan(p,root,copy.deepcopy(plan)),data.get('allow_silent_tail') is True)
   def current(original,original_plan):
    with LOCKS[pid]:
     now=load(pid);now_plan=load_plan(root)
     return now.get('updated')==original.get('updated') and now_plan['revision']==original_plan['revision'] and not any(x.get('stale_reasons') for x in annotate_plan(now,root,now_plan)['bites'])
   result=documentary_preview.start(root,copy.deepcopy(p),copy.deepcopy(plan),data.get('allow_silent_tail') is True,current)
   return jsonify(result),202
  except (ValueError,OSError,KeyError) as e:raise BadRequest(str(e))

@app.get('/api/projects/<pid>/documentary-review-preview')
def documentary_review_preview_status(pid):
 import documentary_preview
 with LOCKS[pid]:
  job=documentary_preview.status(pid)
  if job.get('status') in ('queued','running','error'):return jsonify(job)
  return jsonify(documentary_review_preview_state(pid))

@app.get('/api/projects/<pid>/documentary-review-preview/<name>')
def documentary_review_preview_file(pid,name):
 with LOCKS[pid]:
  state=documentary_review_preview_state(pid)
  if state.get('status')!='ready' or state['url'].rsplit('/',1)[-1]!=name:raise NotFound('This documentary review preview is no longer current.')
  return send_from_directory(folder(pid)/'renders',name,conditional=True,as_attachment=request.args.get('download')=='1')

@app.route('/api/projects/<pid>/documentary-subtitles',methods=['GET','POST'])
def documentary_subtitles(pid):
 from documentary import load_plan,annotate_plan,adjusted_srt
 with LOCKS[pid]:
  p=load(pid);root=folder(pid)
  if p.get('edit_mode','review')!='documentary':raise BadRequest('Adjusted subtitles are available only in a documentary project.')
  if not p.get('srt') or p['srt'].get('recovered_from'):raise BadRequest('Upload the original SRT before creating adjusted subtitles.')
  try:
   original=(root/'inputs'/'captions.srt').read_text(encoding='utf-8-sig')
   # Confirm the on-disk original still has the timings stored in the project.
   if parse_srt(original)!=p['srt']['blocks']:raise ValueError('The uploaded SRT no longer matches the project. Upload it again.')
   plan=load_plan(root);data=request.get_json(silent=True) or {}
   if request.method=='POST' and data.get('revision')!=plan['revision']:raise ValueError('The sound-bite plan changed. Review subtitle splits again.')
   result=adjusted_srt(original,p,annotate_plan(p,root,plan),data.get('splits',[]) if request.method=='POST' else None)
  except (ValueError,OSError) as e:raise BadRequest(str(e))
  return Response(result,content_type='application/x-subrip; charset=utf-8',headers={'Content-Disposition':'attachment; filename="documentary-adjusted.srt"','Cache-Control':'no-store'})

# Frame verification may require decoding the entire source. Cache the result in
# memory by project/plan version and source stat; no project data is changed.
DOCUMENTARY_FRAME_JOBS={}
DOCUMENTARY_FRAME_LOCK=threading.Lock()

def documentary_frame_preflight(pid,p,root,plan):
 from documentary_render_plan import plan as make_plan, load_decisions
 files=[]
 for asset in p.get('assets',[]):
  path=(root/asset.get('path','')).resolve()
  try:
   stat=path.stat();files.append((asset.get('id'),str(path),stat.st_size,stat.st_mtime_ns))
  except OSError:files.append((asset.get('id'),str(path),None,None))
 decision_path=root/'reviews'/'documentary_frame_decisions.json'
 try:
  decision_stat=decision_path.stat();decision_key=(decision_stat.st_size,decision_stat.st_mtime_ns)
 except OSError:decision_key=None
 key=(pid,p.get('updated'),plan.get('revision'),tuple(files),decision_key)
 with DOCUMENTARY_FRAME_LOCK:
  job=DOCUMENTARY_FRAME_JOBS.get(key)
  if job is None:
   job={'status':'checking'};DOCUMENTARY_FRAME_JOBS[key]=job
   for old in list(DOCUMENTARY_FRAME_JOBS):
    if old!=key and old[0]==pid and DOCUMENTARY_FRAME_JOBS[old]['status']!='checking':DOCUMENTARY_FRAME_JOBS.pop(old,None)
   def run():
    try:
     result=make_plan(p,root,plan,load_decisions(root))
     with DOCUMENTARY_FRAME_LOCK:job.update(status='done',report=result)
    except Exception:
     app.logger.exception('Documentary frame preflight failed')
     with DOCUMENTARY_FRAME_LOCK:job.update(status='error',error='Frame preflight failed; no export was made.')
   threading.Thread(target=run,daemon=True,name='documentary-frame-preflight').start()
  return copy.deepcopy(job)

_DOCUMENTARY_DRAFT_BLOCKER='This is a script review draft, not a finished edit. Final export is blocked; complete the script and source checks before rendering.'

def documentary_final_errors(p,root,plan):
 from documentary_cue_groups import groups
 errors=[];notes=[]
 if not p.get('documentary_beat_review'):return (['Final documentary export currently supports script-driven Beat storyboards only.'],notes)
 record=p.get('documentary_beat_review') or {}
 _text=(p.get('production_script') or {}).get('text','')
 from documentary_beats import is_strict_pipeline_script
 strict_script=is_strict_pipeline_script(_text)
 if strict_script:
  from documentary_strict import review_blockers
  errors.extend(review_blockers(p,root))
 elif _text and record.get('script_sha256') and record['script_sha256']!=hashlib.sha256(_text.encode()).hexdigest():
  try:
   from documentary_frame_audit import stale_script_message
   notes.append(stale_script_message(p,record,_text))
  except (ValueError,KeyError,TypeError):
   notes.append('The production script changed after this Beat timeline was built; rebuild it to put the current script on screen.')
 # A Beat storyboard has its own source-range, cue and sound-bite validation.
 # Do not mutate the draft flag or infer approvals from it.
 errors.extend(e for e in check(p,True)['errors'] if e!=_DOCUMENTARY_DRAFT_BLOCKER)
 if not p.get('scenes'):errors.append('Build the Beat timeline before exporting.')
 try:groups(p)
 except ValueError as e:errors.append(str(e))
 if not plan.get('bites'):errors.append('The script-driven sound-bite plan is empty.')
 for b in plan.get('bites',[]):
  if b.get('stale_reasons'):errors.extend(b['stale_reasons'])
 assets={a['id']:a for a in p.get('assets',[])}
 used={s.get('asset_id') for s in p.get('scenes',[])}|{b.get('asset_id') for b in plan.get('bites',[])}
 for aid in used:
  a=assets.get(aid)
  if not a:errors.append('A used picture or sound-bite source is missing.');continue
 return list(dict.fromkeys(errors)),list(dict.fromkeys(notes))

@app.get('/api/projects/<pid>/documentary-export-readiness')
def documentary_export_readiness(pid):
 from documentary import load_plan,annotate_plan,build_timeline
 with LOCKS[pid]:
  p=load(pid);root=folder(pid)
  if p.get('edit_mode','review')!='documentary':raise BadRequest('Documentary readiness is only available in documentary projects.')
  report=check(p,True);errors=list(report['errors']);warnings=[];frame_preflight=None;implemented=bool(p.get('documentary_beat_review'))
  try:
   plan=annotate_plan(p,root,load_plan(root));build_timeline(p,plan)
   if implemented:errors,notes=documentary_final_errors(p,root,plan);warnings.extend(notes)
   # A Beat project gets its sound bites from the script when the timeline is built;
   # before that, asking the person to 'add a sound bite' sent them looking for a control.
   if not plan['bites'] and p['scenes']:errors.append('Add at least one sound bite to the documentary plan.')
   if p.get('documentary_beat_review'):
    frame_preflight=documentary_frame_preflight(pid,copy.deepcopy(p),root,copy.deepcopy(plan))
    if frame_preflight['status']=='done':errors.extend(frame_preflight['report']['errors'])
    elif frame_preflight['status']=='error':errors.append(frame_preflight['error'])
    else:warnings.append('Frame-accurate picture preflight is still running.')
   assets={a['id']:a for a in p.get('assets',[])}
   for b in plan['bites']:
    a=assets.get(b['asset_id']) or {};reuse=a.get('reuse_review') or {}
    if not p.get('documentary_beat_review') and (reuse.get('decision')!='approved' or not str(reuse.get('details') or '').strip()):errors.append(f"Sound bite {b['asset_name']}: record explicit reuse-rights approval with supporting details.")
    warnings.append(f"Sound bite {b['asset_name']} {b['source_in_s']:.3f}–{b['source_out_s']:.3f}: independently review speaker, context, identity and source provenance before delivery.")
  except (ValueError,OSError,KeyError) as e:errors.append(str(e))
  return jsonify({'status':'checking' if frame_preflight and frame_preflight['status']=='checking' else ('blocked' if errors or not implemented else 'ready'),'export_implemented':implemented,'errors':errors,'warnings':warnings,'frame_preflight':frame_preflight,'detail':('Beat documentary export checks; human approvals are attestations, not independent verification.' if implemented else 'Final documentary rendering is not implemented for this storyboard type.')})

@app.get('/api/projects/<pid>/strict-cut-check')
def strict_cut_check(pid):
 from strict_cuts import report
 p=load(pid);return jsonify(report(p,folder(pid)))

# Strict decoding may exceed a proxy's request timeout. Run it once per saved
# project version in the background; polling never starts a render or edits data.
STRICT_JOBS={}
STRICT_JOBS_LOCK=threading.Lock()

@app.get('/api/projects/<pid>/strict-cut-status')
def strict_cut_status(pid):
 from strict_cuts import report
 p=load(pid);version=p.get('updated');key=(pid,version)
 with STRICT_JOBS_LOCK:
  job=STRICT_JOBS.get(key)
  if job is None:
   job={'state':'checking','version':version,'completed':0,'total':len(p.get('scenes') or [])}
   STRICT_JOBS[key]=job
   # Keep only the newest non-running status for this project.
   for old in list(STRICT_JOBS):
    if old!=key and old[0]==pid and STRICT_JOBS[old]['state']!='checking':STRICT_JOBS.pop(old,None)
   def work():
    try:
     def progress(completed,total):
      with STRICT_JOBS_LOCK:job.update(completed=completed,total=total)
     result=report(p,folder(pid),progress=progress)
     with STRICT_JOBS_LOCK:job.update(state='done',report=result,completed=len(p.get('scenes') or []))
    except Exception as exc:
     app.logger.exception('Strict cut check failed')
     with STRICT_JOBS_LOCK:job.update(state='error',error=str(exc)[:300] or 'Strict check failed.')
   threading.Thread(target=work,daemon=True,name='strict-cut-check').start()
  return jsonify(dict(job))

@app.post('/api/projects/<pid>/strict-cut-status/retry')
def retry_strict_cut_status(pid):
 p=load(pid);key=(pid,p.get('updated'))
 with STRICT_JOBS_LOCK:
  job=STRICT_JOBS.get(key)
  if job and job['state']=='error':STRICT_JOBS.pop(key,None)
 return jsonify({'ok':True})

def _strict_storyboard_fingerprint(project):
 rows=[]
 for scene in project.get('scenes') or []:
  row=scene.get('plan_row') or {}
  rows.append({'scene_id':scene.get('id'),'asset_id':scene.get('asset_id'),
   'frame_in':scene.get('frame_in'),'frame_out':scene.get('frame_out'),
   'source_file':row.get('source_file'),'source_in_ms':row.get('source_in_ms'),
   'source_out_ms':row.get('source_out_ms'),'timeline_in_ms':row.get('timeline_in_ms'),
   'timeline_out_ms':row.get('timeline_out_ms'),'script_beat':row.get('script_beat'),
   'camera':scene.get('camera'),'transition':scene.get('transition'),
   'transition_handle_frames':scene.get('transition_handle_frames'),
   'picture_scale':scene.get('picture_scale')})
 return hashlib.sha256(json.dumps(rows,sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()

def start_documentary_final(pid,p,data):
 from documentary import load_plan,annotate_plan,adjusted_srt
 from documentary_render_job import DocumentaryRenderJob
 root=folder(pid)
 if not p.get('documentary_beat_review'):raise BadRequest('Documentary export currently supports script-driven Beat storyboards only.')
 if data.get('final') is not True:raise BadRequest('Choose final documentary export.')
 # One click renders. The page's cut check may be a few saves old (a caption style, an
 # approval); rather than refuse, the server re-runs the cut check on the current
 # production now and renders if it passes.
 if data.get('strict_checked_version')!=p.get('updated'):
  from strict_cuts import report as strict_report
  strict=strict_report(p,root)
  if strict['errors']:raise BadRequest('The cut check found a problem: '+strict['errors'][0])
 # The fade follows the production's saved setting unless the request says otherwise.
 if data.get('omit_fade') is not True and data.get('fade') is not True:
  fades=p.get('documentary_fades') or {}
  use=fades.get('enabled') is not False and ((float(fades.get('in_s') or 0))>0 or (float(fades.get('out_s') or 0))>0)
  data={**data,'fade':use,'omit_fade':not use}
 try:
  plan=annotate_plan(p,root,load_plan(root));errors,_warnings=documentary_final_errors(p,root,plan)
  if errors:return jsonify({'errors':errors,'warnings':_warnings}),400
  from documentary_beats import is_strict_pipeline_script
  strict_script=is_strict_pipeline_script((p.get('production_script') or {}).get('text',''))
  if strict_script:
   frame_state=documentary_frame_preflight(pid,copy.deepcopy(p),root,copy.deepcopy(plan))
   if frame_state['status']=='checking':raise ValueError('Frame-accurate source preflight is still running. Wait for it to finish, then render again.')
   if frame_state['status']=='error':raise ValueError(frame_state.get('error') or 'Frame-accurate source preflight failed; no render was started.')
   if frame_state['report'].get('errors'):raise ValueError('Frame-accurate source preflight failed: '+ ' '.join(frame_state['report']['errors']))
  width,height=output_size(p.get('format','landscape'),p.get('size'))
  burn_srt=data.get('srt_subtitles') is True;subtitle_ass=None;adjusted=None
  if burn_srt:
   from caption_layout import make_single_line_ass
   original=(root/'inputs'/'captions.srt').read_text(encoding='utf-8-sig')
   if parse_srt(original)!=(p.get('srt') or {}).get('blocks'):raise ValueError('The original SRT no longer matches the project.')
   adjusted=adjusted_srt(original,p,plan,data.get('subtitle_splits') or [])
   subtitle_ass=make_single_line_ass(parse_srt(adjusted),width,height,p.get('caption_preset'),p.get('caption_size'),p.get('caption_position'))
  def current(original,source_plan):
   with LOCKS[pid]:
    now=load(pid);now_plan=annotate_plan(now,root,load_plan(root))
    # Only a change to the sound (the bite plan or its media) makes the finished file
    # wrong. A caption, approval or transition saved during the render leaves a valid
    # MP4 of the version it started from; the editor then offers "Render again".
    if now_plan['revision']!=source_plan['revision'] or any(b.get('stale_reasons') for b in now_plan['bites']):raise ValueError('The sound-bite plan changed during the render; no MP4 was published. Render again.')
    from documentary_beats import is_strict_pipeline_script
    if is_strict_pipeline_script((original.get('production_script') or {}).get('text','')):
     from documentary_strict import review_blockers
     expected=(original.get('documentary_beat_review') or {}).get('script_sha256')
     actual=hashlib.sha256((now.get('production_script') or {}).get('text','').encode()).hexdigest()
     if not expected or actual!=expected:raise ValueError('The strict production script changed during rendering; no MP4 was published. Rebuild and review again.')
     if _strict_storyboard_fingerprint(now)!=_strict_storyboard_fingerprint(original):raise ValueError('The approved Beat timeline changed during rendering; no MP4 was published. Review and render the current storyboard.')
     blockers=review_blockers(now,root)
     if blockers:raise ValueError('Strict visual review changed during rendering; no MP4 was published. '+ ' '.join(blockers))
  def publish(original,source_plan,candidate,final,record,adjusted_text):
   with LOCKS[pid]:
    current(original,source_plan)
    srt_file=None;record_file=root/'reviews'/(final.stem+'.json')
    try:
     if adjusted_text is not None:
      srt_file=final.with_suffix('.adjusted.srt');srt_file.write_text(adjusted_text,encoding='utf-8');record['adjusted_srt']=srt_file.name
     write(record_file,record);candidate.replace(final)
    except Exception:
     record_file.unlink(missing_ok=True)
     if srt_file:srt_file.unlink(missing_ok=True)
     raise
  from documentary_music import music_path,settings as music_settings
  music=music_settings(p);use_music=bool(music['enabled'] and music['present'] and music_path(root).is_file())
  job=DocumentaryRenderJob(root,p,plan,width,height,{'enhance_picture':data.get('enhance_picture') is True,'srt_subtitles':burn_srt,'music':use_music},subtitle_ass,adjusted,current,publish,lambda state:write(root/'render_status.json',state))
  JOBS[pid]=job;job.start();_hold_queue_during(job);return jsonify({'render':job.snapshot()}),202
 except (ValueError,OSError,KeyError,TypeError) as e:raise BadRequest(str(e))

def _hold_queue_during(job):
 """Pause background queue work (editing copies, analysis) while a final render runs.

 The documentary render runs outside the job queue, so up to two proxy transcodes and
 a queued heavy job kept encoding beside it and took the same cores. The queue's own
 pause parks those ffmpeg processes; it is resumed when the render thread ends, and
 left alone if the user had already paused it.
 """
 try:
  if getattr(QUEUE,'_paused_all',False):return
  QUEUE.pause()
 except Exception:
  app.logger.exception('Could not pause the job queue for the render');return
 def wait():
  try:
   worker=getattr(job,'worker_thread',None)
   if worker is not None:worker.join()
  finally:
   try:QUEUE.resume()
   except Exception:app.logger.exception('Could not resume the job queue after the render')
 threading.Thread(target=wait,daemon=True,name='render-queue-hold').start()

@app.post('/api/projects/<pid>/render')
def render(pid):
 with LOCKS[pid]:
  editable(pid);p=load(pid);data=request.get_json(silent=True) or {};final=data.get('final') is True
  if p.get('edit_mode','review')=='documentary':return start_documentary_final(pid,p,data)
  report=check(p,final)
  from strict_cuts import report as strict_report
  strict=strict_report(p,folder(pid))
  if strict['errors']:report['errors'].extend(strict['errors']);report['can_export']=False
  if strict['required'] and data.get('strict_checked_version')!=p.get('updated'):
   report['errors'].append('Review and confirm the current per-shot strict cut check before export.');report['can_export']=False
  if report['errors']:return jsonify(report),400
  enhance_picture=data.get('enhance_picture') is True
  manifest(p,strict,enhance_picture);root=folder(pid);name=('final' if final else 'review')+'_'+time.strftime('%Y%m%d_%H%M%S')+'.mp4'
  job=RenderJob(root,on_change=lambda state:write(root/'render_status.json',state),story_path=root/'storyboard.json',catalog_path=root/'catalog.json',output_name=name);JOBS[pid]=job
  burn_script=data.get('script_captions') is True;burn_srt=data.get('srt_subtitles') is True
  caption_entries=[]
  if burn_script:
   for scene in p['scenes']:
    row=scene.get('plan_row') or {}
    # Older combined fields are ambiguous editing instructions, not caption text.
    caption='' if row.get('plain_cue') and 'continuity' not in row else str(row.get('required_caption') or '').strip()
    if caption and caption.casefold() not in ('none','n/a','na','—','-'):
     caption_entries.append((scene['frame_in'],scene['frame_out'],caption))
  caption_file=None
  if caption_entries:
   caption_file=root/'reviews'/(Path(name).stem+'_script_captions.srt')
   caption_file.write_text('\n\n'.join(f'{i}\n{srt_stamp(round(a/30*1000))} --> {srt_stamp(round(b/30*1000))}\n{re.sub(chr(10)+chr(10), chr(10), text)}' for i,(a,b,text) in enumerate(caption_entries,1))+'\n',encoding='utf-8')
  write(root/'reviews'/(Path(name).stem+'.json'),{'project':copy.deepcopy(p),'validation':report,'strict_cut_report':strict,'export_type':'final' if final else 'review','captions_burned_in':bool(caption_entries),'script_captions_requested':burn_script,'srt_subtitles_burned_in':burn_srt,'picture_enhancement':enhance_picture,'created':time.time()})
  one_line_file=None
  if burn_srt:
   from caption_layout import make_single_line_ass
   if not (p.get('srt') or {}).get('blocks'):raise BadRequest('Import an SRT before burning subtitles.')
   width,height=output_size(p.get('format','landscape'),p.get('size'))
   try:ass=make_single_line_ass(p['srt']['blocks'],width,height)
   except ValueError as e:raise BadRequest(str(e))
   one_line_file=root/'reviews'/(Path(name).stem+'_srt_display.ass');one_line_file.write_text(ass,encoding='utf-8')
  job.start(captions=burn_srt,script_caption_srt=caption_file,narration_caption_file=one_line_file);return jsonify({'render':job.snapshot()}),202
@app.post('/api/projects/<pid>/cancel')
def cancel(pid):
 folder(pid)
 if pid in JOBS and busy(pid):JOBS[pid].cancel()
 return jsonify({'ok':True})
_PROXY_REFRESH=set()
@app.get('/api/projects/<pid>/assets/<aid>/file')
def asset_file(pid,aid):
 # The cached, read-only snapshot: a scrub sends many range requests, and parsing the
 # whole project file for each one delayed every frame the monitor asked for.
 p=snapshot(pid);a=next((x for x in p['assets'] if x['id']==aid),None)
 if not a:raise NotFound('Asset not found.')
 root=folder(pid)
 if a.get('kind')=='video' and str(a.get('path','')).lower().endswith(('.mp4','.mov')):
  source=root/a['path']
  # Playback and scrubbing use the small editing copy. Export never comes through
  # here -- engine.py opens the sources folder directly -- so a proxy can never
  # reach a delivered frame. Only an existing proxy is used: this request must not
  # trigger an encode, or the monitor would stall waiting for one.
  try:
   # Read the settings once, not twice. This runs on every video request, including
   # every scrub, and each load re-parses settings.json from disk.
   settings=SETTINGS.load()
   if settings.get('proxies_enabled'):
    store,_detail=SETTINGS.cache_store()
    prepared=proxy_module.metadata(store,source)
    # Only a proxy made at the CURRENTLY selected quality is used. A proxy built at a
    # different quality is not wrong, just not what was asked for, and serving it would
    # make the quality setting appear to do nothing.
    wanted=settings.get('proxy_quality') or proxy_module.DEFAULT_QUALITY
    if prepared and prepared.get('quality')==wanted:
     # A copy made with the old, long keyframe spacing still plays; a quick-seeking
     # one is made once in the background and replaces it when it is ready.
     if prepared.get('keyint')!=proxy_module.PROXY_KEYINT and str(source) not in _PROXY_REFRESH:
      _PROXY_REFRESH.add(str(source))
      threading.Thread(target=lambda:queue_proxy(pid,load(pid),source),daemon=True,name='proxy-refresh').start()
     return send_file(prepared['path'],conditional=True)
  except (OSError,ValueError):pass
  # A player cannot seek a file whose index is at the end without fetching all of
  # it; that is what left the monitor black. Serve a cached fast-start copy and
  # leave the uploaded original untouched.
  try:
   if mp4_moov_at_end(source):
    cached=root/'.cache/faststart'/(a['id']+'.mp4')
    if not cached.exists() or cached.stat().st_size<1024 or cached.stat().st_mtime<source.stat().st_mtime:
     cached.parent.mkdir(parents=True,exist_ok=True)
     if not make_fast_start(source,cached):cached=cached if cached.exists() else None
    if cached and cached.exists():return send_file(cached,conditional=True)
  except OSError:pass
 return send_from_directory(root,a['path'],conditional=True)

@app.get('/api/projects/<pid>/assets/<aid>/clean-frame')
def asset_clean_photo(pid, aid):
 # The still exactly as the export draws it (v17): news panels, logos and black bars
 # cut away, the clean photo centred over a blur of itself, at the output shape.
 # The original upload is untouched and still available at /file.
 p=snapshot(pid);asset=next((a for a in p.get('assets',[]) if a.get('id')==aid),None)
 if not asset or asset.get('kind')!='image':raise NotFound('Image asset not found.')
 root=folder(pid).resolve();source=(root/str(asset.get('path') or '')).resolve()
 if not (source.is_relative_to(root/'assets') or source.is_relative_to(root/'sources')) or not source.is_file():
  raise NotFound('Original image source is unavailable.')
 from clean_photo_framing import framed_still_file,crop_token
 width,height=output_size(p.get('format','landscape'),p.get('size'))
 scale=min(1.0,1280/max(width,height));width,height=max(2,round(width*scale)),max(2,round(height*scale))
 stamp=source.stat()
 import hashlib
 key=hashlib.sha256('|'.join([str(source),str(stamp.st_mtime_ns),str(stamp.st_size),crop_token(asset.get('crop')),
                              str(width),str(height)]).encode()).hexdigest()[:24]
 dest=root/'.cache'/'clean-still-v17'/(key+'.jpg')
 if not dest.is_file():framed_still_file(source,dest,width,height,asset.get('crop'))
 return send_file(dest,mimetype='image/jpeg',conditional=True)

@app.get('/api/projects/<pid>/scenes/<sid>/photo-frame')
def scene_photo_frame(pid, sid):
 """A still interval from a video, presented exactly like an uploaded photo.

 The original clip is never rewritten.  Only metadata-approved photo carriers and
 explicit native-static intervals can use this route.
 """
 p=snapshot(pid);scene=next((s for s in p.get('scenes',[]) if s.get('id')==sid),None)
 if not scene:raise NotFound('Scene not found.')
 asset=next((a for a in p.get('assets',[]) if a.get('id')==scene.get('asset_id')),None)
 from truecrime_camera import still_visual_kind
 if not asset or asset.get('kind')!='video' or not still_visual_kind(asset,[scene]):
  raise NotFound('This scene is not an approved still-picture interval.')
 root=folder(pid).resolve();source=(root/str(asset.get('path') or '')).resolve()
 if not source.is_relative_to(root/'sources') or not source.is_file():raise NotFound('Source video is missing.')
 width,height=output_size(p.get('format','landscape'),p.get('size'))
 scale=min(1.0,1280/max(width,height));width,height=max(2,round(width*scale)),max(2,round(height*scale))
 stamp=source.stat();at=max(0.0,float(scene.get('in_s') or 0))
 from clean_photo_framing import VERSION,framed_image_file
 key=hashlib.sha256('|'.join([str(source),str(stamp.st_mtime_ns),str(stamp.st_size),VERSION,
                              f'{at:.6f}',str(width),str(height)]).encode()).hexdigest()[:24]
 cache=root/'.cache'/'scene-photo-frames';cache.mkdir(parents=True,exist_ok=True);dest=cache/(key+'.jpg')
 if not dest.is_file():
  from conform import capture
  with THUMBNAIL_SLOTS:
   if not dest.is_file():
    cap=capture(source)
    try:cap.set(cv2.CAP_PROP_POS_MSEC,at*1000);ok,bgr=cap.read()
    finally:cap.release()
    if not ok:raise NotFound('The still-picture frame could not be decoded.')
    framed_image_file(Image.fromarray(cv2.cvtColor(bgr,cv2.COLOR_BGR2RGB)),dest,width,height)
 return send_file(dest,mimetype='image/jpeg',conditional=True)

@app.get('/api/projects/<pid>/assets/<aid>/source-file')
def documentary_source_file(pid,aid):
 """Read-only original-media preview; never substitutes a proxy or derived clip."""
 p=snapshot(pid);asset=next((a for a in p.get('assets',[]) if a.get('id')==aid),None)
 if not asset or asset.get('kind')!='video':raise NotFound('Original source video not found.')
 root=folder(pid).resolve();path=(root/str(asset.get('path') or '')).resolve()
 if not path.is_relative_to(root/'sources') or not path.is_file():
  raise NotFound('The exact uploaded source video is missing.')
 return send_from_directory(path.parent,path.name,conditional=True)
@app.get('/api/projects/<pid>/narration')
def narration(pid):
 p=load(pid)
 if not p.get('voiceover'):raise NotFound('No narration imported.')
 return send_from_directory(folder(pid),p['voiceover']['path'],conditional=True)
@app.get('/api/projects/<pid>/exports/<name>')
def export_file(pid,name):
 if Path(name).name!=name:raise BadRequest('Invalid export name.')
 return send_from_directory(folder(pid)/'renders',name,conditional=True,as_attachment=request.args.get('download')=='1')
@app.get('/api/projects/<pid>/assets/<aid>/planned-samples/<bid>')
def planned_samples(pid,aid,bid):
 from conform import samples
 p=snapshot(pid);a=next((a for a in p['assets'] if a['id']==aid),None)   # frames are decoded outside the project lock
 if not a:raise NotFound('Media file not found.')
 cut=next((r for r in a.get('document_plan',{}).get('cuts',[]) if str(r['beat_id'])==bid),None)
 if not cut or a['kind'] not in ['video','image']:raise NotFound('Planned cut not found.')
 try:path=samples(folder(pid),a,cut)
 except Exception as e:raise BadRequest('Cannot inspect planned cut: '+str(e)[:250])
 return send_from_directory(path.parent,path.name,conditional=True)

@app.get('/api/projects/<pid>/cut-audit')
def download_cut_audit(pid):
 from cut_audit import audit
 import csv,io
 from flask import Response
 try:result=audit(load(pid))
 except ValueError as e:raise BadRequest('Cannot compare the SRT block map: '+str(e))
 if request.args.get('format')=='json':return jsonify(result)
 output=io.StringIO();fields=list(result['rows'][0]) if result['rows'] else ['scene','status'];writer=csv.DictWriter(output,fieldnames=fields);writer.writeheader();writer.writerows(result['rows'])
 return Response(output.getvalue(),mimetype='text/csv',headers={'Content-Disposition':'attachment; filename="cut-audit.csv"'})


@app.get('/api/projects/<pid>/script-reading')
@project_io_lock
def script_reading_report(pid):
 return jsonify(script_reading(load(pid),include_shots=True))


@app.get('/api/projects/<pid>/feasibility')
def feasibility_report(pid):
 from shot_plan import feasibility
 p=load(pid)
 blocks=request.args.get('blocks')
 scope=[int(x) for x in re.findall(r'\d+',blocks)] if blocks else None
 try:return jsonify(feasibility(p,folder(pid),scope))
 except ValueError as e:raise BadRequest('Feasibility: '+str(e))

@app.get('/api/projects/<pid>/candidates')
def candidate_report(pid):
 from shot_plan import candidates as candidate_list,shots_of_length
 p=load(pid)
 limit=min(int(request.args.get('limit',8) or 8),40)
 try:
  if request.args.get('length_s') is not None:
   length=float(request.args['length_s'])
   if not 0<length<3600:raise ValueError('Picture length must be between 0 and 3600 seconds.')
   handle=float(request.args.get('handle_s') or 0)
   if not 0<=handle<1.5:raise ValueError('Transition handle must be under 1.5 seconds.')
   return jsonify({'length_s':round(length,3),'needed_s':round(length+handle,3),'candidates':shots_of_length(folder(pid),p,length,handle,limit)})
  return jsonify(candidate_list(p,folder(pid),beat_id=request.args.get('beat'),limit=limit))
 except ValueError as e:raise BadRequest(str(e))

@app.get('/api/projects/<pid>/coverage-summary')
def coverage_summary(pid):
 p=load(pid);assets={a['id']:a for a in p['assets']};video=still=unassigned=0;used=set()
 for scene in p.get('scenes',[]):
  seconds=(scene['frame_out']-scene['frame_in'])/30
  asset=assets.get(scene.get('asset_id'))
  if not asset:unassigned+=seconds;continue
  used.add(asset['id'])
  if is_still(p,asset) or (scene.get('plan_row') or {}).get('native_static_interval'):still+=seconds
  else:video+=seconds
 total=video+still+unassigned
 result={'narration_duration_seconds':(p.get('voiceover') or {}).get('duration'), 'cue_count':len((p.get('srt') or {}).get('blocks',[])), 'source_count':len(used), 'timeline_seconds':round(total,3), 'video_seconds':round(video,3), 'still_seconds':round(still,3), 'unassigned_seconds':round(unassigned,3), 'video_percent':round(100*video/total,2) if total else 0, 'still_percent':round(100*still/total,2) if total else 0, 'unresolved_issues':check(p,True)['errors'], 'note':'Declared native static intervals count as stills; source identity, eligibility and rights require review.'}
 response=jsonify(result);response.headers['Content-Disposition']='attachment; filename="coverage-summary.json"';return response

@app.get('/api/projects/<pid>/frame-qc')
def frame_qc_sheet(pid):
 from frame_qc import build
 p=copy.deepcopy(snapshot(pid))         # decoded outside the project lock; build gets its own copy
 try:manifest=build(folder(pid),p,per_sheet=request.args.get('per_sheet',20),group=request.args.get('sheet',1))
 except ValueError as e:raise BadRequest(str(e))
 if request.args.get('format')=='json':
  return jsonify({k:v for k,v in manifest.items() if k!='file'}|{'url':f'/api/projects/{pid}/frame-qc/{manifest["file"]}'})
 return send_from_directory(folder(pid)/'.cache/frame_qc',manifest['file'],conditional=True)

@app.get('/api/projects/<pid>/frame-qc/<name>')
def frame_qc_file(pid,name):
 if not re.fullmatch(r'frame_qc_sheet_\d{2,5}_[0-9a-f]{24}\.jpg',name):raise NotFound('Sheet not found.')
 return send_from_directory(folder(pid)/'.cache/frame_qc',name,conditional=True)

@app.get('/api/projects/<pid>/understanding/<target>/soundbites')
def review_source_soundbites(pid, target):
 from footage_review import candidates
 from local_understanding import read_result
 root, path, kind, duration = understanding_source(pid, target)
 if kind != 'video':
  raise BadRequest('Choose a video source.')
 try:
  cue = int(request.args['cue']) if 'cue' in request.args else None
  offset = int(request.args.get('offset', 0))
  if offset < 0:
   raise ValueError('Invalid page.')
  result = candidates(read_result(root, target, path), (snapshot(pid).get('srt') or {}).get('blocks', []), cue, duration, offset)
 except (ValueError, TypeError) as error:
  raise BadRequest(str(error))
 return jsonify(result)


@app.get('/api/projects/<pid>/understanding/<target>/frame.png')
def review_source_frame(pid, target):
 root, path, kind, duration = understanding_source(pid, target)
 at = request.args.get('ms', type=int)
 if kind != 'video' or at is None or not 0 <= at < duration * 1000:
  raise BadRequest('Choose a time inside the source video.')
 if not THUMBNAIL_SLOTS.acquire(blocking=False):
  return jsonify(error='Frame extraction is busy. Try again.'), 429
 try:
  proc = subprocess.run([FFMPEG, '-nostdin', '-v', 'error', '-ss', f'{at/1000:.3f}', '-i', str(path),
                         '-map', '0:v:0', '-frames:v', '1', '-threads', '1', '-c:v', 'png', '-f', 'image2pipe', '-'],
                         capture_output=True, timeout=45)
 except subprocess.TimeoutExpired:
  raise BadRequest('Frame extraction timed out.')
 finally:
  THUMBNAIL_SLOTS.release()
 if proc.returncode or not proc.stdout:
  raise BadRequest('No source frame decoded at that position.')
 return Response(proc.stdout, mimetype='image/png', headers={'Content-Disposition': f'attachment; filename="{target}-{at}ms.png"'})


@app.get('/api/local-understanding/capabilities')
def local_understanding_capabilities():
 from local_understanding import capabilities
 return jsonify(capabilities())

def understanding_source(pid,target):
 p=load(pid);root=folder(pid)
 if target=='narration':
  a=p.get('voiceover');kind='audio'
 else:
  if not re.fullmatch('[a-f0-9]{16}',target):raise NotFound('Media not found.')
  a=next((a for a in p['assets'] if a['id']==target and a['kind']=='video'),None);kind='video'
 if not a:raise NotFound('Media not found.')
 path=(root/a['path']).resolve()
 if not path.is_relative_to(root.resolve()) or not path.is_file():raise NotFound('Media file not found.')
 return root,path,kind,float(a['duration'])

@app.route('/api/projects/<pid>/understanding/<target>',methods=['GET','POST'])
def local_understanding_report(pid,target):
 from local_understanding import enqueue,read_result
 with LOCKS[pid]:
  root,path,kind,duration=understanding_source(pid,target)
  if request.method=='POST':enqueue(root,target,path,kind,duration)
  return jsonify(read_result(root,target,path))

@app.post('/api/projects/<pid>/understanding/<target>/sound-events')
def reanalyse_sound_events(pid,target):
 from local_understanding import enqueue_sound_events
 with LOCKS[pid]:
  root,path,_,_=understanding_source(pid,target)
  try: enqueue_sound_events(root,target,path)
  except ValueError as e: raise BadRequest(str(e))
  return jsonify({'status':'queued'})


@app.post('/api/projects/<pid>/understanding/<target>/visual')
def reanalyse_visual(pid,target):
 from local_understanding import enqueue_visual
 with LOCKS[pid]:
  root,path,kind,_=understanding_source(pid,target)
  if kind != 'video': raise BadRequest('Visual analysis requires a video source.')
  try: enqueue_visual(root,target,path)
  except ValueError as e: raise BadRequest(str(e))
  return jsonify({'status':'queued'})


def transcript_srt(report, require_complete=False):
 if report.get('status') in ('stale','not_started','error','interrupted'):raise BadRequest('No current transcript is available for this source.')
 stage=(report.get('stages') or {}).get('transcript') or {}
 if require_complete and stage.get('status')!='complete':raise BadRequest('Wait for transcription to finish before using it as the project SRT.')
 segments=(stage.get('result') or {}).get('segments') or []
 if not segments:raise BadRequest('No transcript segments are available yet.')
 lines=[];last=0
 for i,segment in enumerate(segments,1):
  try:a=round(float(segment['start_s'])*1000);b=round(float(segment['end_s'])*1000)
  except (ValueError,TypeError,KeyError,OverflowError):raise BadRequest('Transcript has invalid timestamps; review it in the analysis report.')
  text=' '.join(str(segment.get('text') or '').split())
  if a<last or a<0 or b<=a or not text:raise BadRequest('Transcript timestamps overlap or are invalid; review the analysis report before making an SRT.')
  lines.append('%d\n%s --> %s\n%s'%(i,srt_stamp(a),srt_stamp(b),text));last=b
 return '\n\n'.join(lines)+'\n', stage.get('status')=='complete'

@app.get('/api/projects/<pid>/understanding/<target>/transcript.srt')
def local_transcript_srt(pid,target):
 from flask import Response
 from local_understanding import read_result
 with LOCKS[pid]:
  root,path,_,_=understanding_source(pid,target)
  text,complete=transcript_srt(read_result(root,target,path))
  suffix='' if complete else '-partial'
  return Response(text,mimetype='text/plain; charset=utf-8',headers={'Content-Disposition':'attachment; filename="transcript'+suffix+'.srt"'})

@app.post('/api/projects/<pid>/understanding/narration/apply-srt')
def apply_narration_transcript(pid):
 from local_understanding import read_result
 with LOCKS[pid]:
  editable(pid);p=load(pid);d=request.get_json(silent=True) or {}
  if d.get('confirm_generated') is not True:raise BadRequest('Confirm that this is an unverified machine transcript before applying it.')
  if (p.get('srt') or p.get('scenes')) and d.get('confirm_replace') is not True:
   raise BadRequest('Confirm replacement: this replaces the current SRT and clears the storyboard.')
  root,path,_,_=understanding_source(pid,'narration')
  text,_=transcript_srt(read_result(root,'narration',path),require_complete=True)
  blocks=parse_srt(text)
  # Match normal SRT upload semantics, but only after the user confirms. No timestamps
  # are stretched to match narration and old block maps remain detectably stale.
  (root/'inputs/captions.srt').write_text(text,encoding='utf-8')
  p['srt']={'blocks':blocks,'name':'Machine transcript · review required.srt'};p.pop('srt_removed',None)
  p['scenes']=[];p.pop('srt_recovery',None)
  save(p)
  from automatic import maybe_queue
  maybe_queue(sys.modules[__name__],p)
  return jsonify(public(p))

@app.get('/api/projects/<pid>/scenes/<sid>/understanding')
def scene_understanding_report(pid,sid):
 from local_understanding import read_result,scene_context
 with LOCKS[pid]:
  p=load(pid)
  scene=next((s for s in p['scenes'] if s['id']==sid),None)
  if not scene:raise NotFound('Scene not found.')
  target=scene.get('asset_id')
  if not target:raise NotFound('This scene has no video source.')
  root,path,kind,_=understanding_source(pid,target)
  return jsonify(scene_context(read_result(root,target,path),scene))


@app.get('/api/projects/<pid>/block-map-template')
def block_map_template(pid):
 from shot_plan import prefill_csv,guidance
 from flask import Response
 p=load(pid)
 try:
  if request.args.get('format')=='json':return jsonify(guidance(p,folder(pid),parent_beat_min(1)))
  text=prefill_csv(p,parent_beat_min(1))
 except ValueError as e:raise BadRequest(str(e))
 return Response(text,mimetype='text/csv',headers={'Content-Disposition':'attachment; filename="block-map-template.csv"'})

def parent_beat_min(value):
 from edl import integer
 return integer(value,'beat')

@app.get('/api/projects/<pid>/flow-audit')
@project_io_lock
def download_flow_audit(pid):
 from picture_flow import csv_rows,apply_flow
 import csv,io
 from flask import Response
 p=load(pid);report=p.get('picture_flow') or apply_flow(copy.deepcopy(p),folder(pid),snap=False)
 if request.args.get('format')=='json':return jsonify(report)
 rows=csv_rows(report);output=io.StringIO();writer=csv.writer(output);writer.writerows(rows)
 return Response(output.getvalue(),mimetype='text/csv',headers={'Content-Disposition':'attachment; filename="flow-audit.csv"'})

def thumbnail_key(scene,asset,path):
 path=Path(path);stat=path.stat();key=hashlib.sha256(json.dumps([asset['id'],asset['path'],stat.st_size,stat.st_mtime_ns,round(scene['in_s']*1000000)]).encode()).hexdigest()[:24]
 return scene['id']+'_'+key+'.jpg'

@app.get('/api/projects/<pid>/assets/<aid>/timeline-thumbnail')
def documentary_timeline_thumbnail(pid,aid):
 # The project is read under its lock; the frame is decoded outside it. A new timeline
 # asks for ~175 thumbnails at once, and holding the lock through each decode made every
 # other request for the project (saving, Documentary tools, reloading) queue behind them.
 p=snapshot(pid)
 if p.get('edit_mode','review')!='documentary':raise NotFound('Documentary timeline thumbnail not found.')
 asset=next((a for a in p.get('assets',[]) if a['id']==aid and a.get('kind')=='video'),None)
 if not asset:raise NotFound('Source video not found.')
 try:
  at=float(request.args.get('at',''))
  if not math.isfinite(at) or at<0 or at>=float(asset.get('duration') or 0):raise ValueError()
 except (ValueError,TypeError):raise BadRequest('Choose a time within the source video.')
 source=(folder(pid)/asset['path']).resolve();root=folder(pid).resolve()
 if not source.is_relative_to(root/'sources') or not source.is_file():raise NotFound('Source video is missing.')
 at=round(at,2);stat=source.stat();key=hashlib.sha256(json.dumps([aid,asset.get('revision'),stat.st_size,stat.st_mtime_ns,at]).encode()).hexdigest()[:24]
 cache=root/'.cache'/'documentary-thumbnails';cache.mkdir(parents=True,exist_ok=True);out=cache/(key+'.jpg')
 if not out.exists():
  from conform import capture
  with THUMBNAIL_SLOTS:
   if not out.exists():
    import perflog
    with perflog.timed('thumbnail.timeline',asset=asset.get('original_name'),at=at):
     cap=capture(source)
     try:cap.set(cv2.CAP_PROP_POS_MSEC,at*1000);ok,img=cap.read()
     finally:cap.release()
    if not ok:raise NotFound('The source frame could not be decoded.')
    temp=out.with_name(out.stem+'.'+uid()+'.jpg')
    try:cv2.imwrite(str(temp),cv2.resize(img,(200,112)));temp.replace(out)
    finally:temp.unlink(missing_ok=True)
 return cached_image(send_from_directory(cache,out.name,conditional=True),request.args.get('v')==str(asset.get('revision') or asset['id']))

@app.get('/api/projects/<pid>/assets/<aid>/poster')
def asset_poster(pid,aid):
 """A poster frame for the media pool grid: a still for a photograph, a decoded
 frame for a video. Unassigned uploads have no scene to borrow a thumbnail from,
 so this reads the asset itself. Cached per revision so the pool stays cheap."""
 p=snapshot(pid)                      # decode outside the project lock, as for thumbnails
 a=next((x for x in p['assets'] if x['id']==aid),None)
 if not a:raise NotFound('Media not found.')
 root=folder(pid).resolve();source=(root/a['path']).resolve()
 # Photographs are stored under assets/, decoded video under sources/.
 if a.get('kind')=='image':
  if not source.is_relative_to(root/'assets') or not source.is_file():raise NotFound('Media file is missing.')
  return send_from_directory(root,a['path'],conditional=True)
 if not source.is_relative_to(root/'sources') or not source.is_file():raise NotFound('Media file is missing.')
 cache=root/'.cache'/'posters';cache.mkdir(parents=True,exist_ok=True)
 stat=source.stat()
 key=hashlib.sha256(json.dumps([aid,a.get('revision'),stat.st_size,stat.st_mtime_ns]).encode()).hexdigest()[:24]
 out=cache/(key+'.jpg')
 if not out.exists():
  from conform import capture
  with THUMBNAIL_SLOTS:
   if not out.exists():
    import perflog;_t=time.monotonic()
    cap=capture(source)
    try:
     # A tenth of the way in avoids a black lead-in on most footage.
     cap.set(cv2.CAP_PROP_POS_MSEC,min(1.0,max(0.0,float(a.get('duration') or 0)*0.1))*1000);ok,img=cap.read()
    finally:cap.release()
    perflog.record('thumbnail.poster',time.monotonic()-_t,asset=a.get('original_name'))
    if not ok:raise NotFound('The poster frame could not be decoded.')
    temp=out.with_name(out.stem+'.'+uid()+'.jpg')
    try:
     # Portrait uploads keep their shape; the grid crops with object-fit.
     h,w=img.shape[:2];scale=240/max(1,min(h,w))
     cv2.imwrite(str(temp),cv2.resize(img,(max(1,int(w*scale)),max(1,int(h*scale)))),[cv2.IMWRITE_JPEG_QUALITY,82]);temp.replace(out)
    finally:temp.unlink(missing_ok=True)
 return cached_image(send_from_directory(cache,out.name,conditional=True),request.args.get('v')==str(a.get('revision') or a['id']))

@app.get('/api/projects/<pid>/scenes/<sid>/thumbnail')
def scene_thumbnail(pid,sid):
 p=snapshot(pid)                      # decode outside the project lock, as for thumbnails
 s=next((s for s in p['scenes'] if s['id']==sid),None)
 if not s:raise NotFound('Scene not found.')
 a=next((a for a in p['assets'] if a['id']==s['asset_id']),None)
 if not a:raise NotFound('Assign an asset first.')
 try:same_in=abs(float(request.args.get('in',''))-float(s.get('in_s') or 0))<1e-9
 except ValueError:same_in=False
 fresh=request.args.get('v')==str(a.get('revision') or a['id']) and same_in
 if a['kind']=='image':return cached_image(send_from_directory(folder(pid),a['path'],conditional=True),fresh)
 cache=folder(pid)/'.cache/thumbnails';cache.mkdir(parents=True,exist_ok=True)
 source=folder(pid)/a['path'];out=cache/thumbnail_key(s,a,source)
 if not out.exists():
  from conform import capture
  with THUMBNAIL_SLOTS:
   if not out.exists():
    import perflog
    with perflog.timed('thumbnail.scene',asset=a.get('original_name')):
     cap=capture(source)
     try:cap.set(cv2.CAP_PROP_POS_MSEC,s['in_s']*1000);ok,img=cap.read()
     finally:cap.release()
    if not ok:raise NotFound('This source frame could not be decoded.')
    tmp=out.with_name(out.stem+'.'+uid()+'.jpg');cv2.imwrite(str(tmp),cv2.resize(img,(320,180)));tmp.replace(out)
 return cached_image(send_from_directory(cache,out.name,conditional=True),fresh)
@app.errorhandler(400)
@app.errorhandler(404)
@app.errorhandler(405)
@app.errorhandler(413)
@app.errorhandler(415)
@app.errorhandler(422)
@app.errorhandler(429)
def friendly(e):return jsonify({'error':str(e.description)}),e.code


@app.errorhandler(HTTPException)
def any_http_error(e):
 # Every remaining HTTP error must still be JSON. A bare 405 (wrong method) or a
 # proxy-generated error arrives as HTML, and the client only reads JSON -- the
 # reader then reports "the server response could not be read" instead of the
 # real reason, which is how a wrong method surfaced as an unreachable server.
 return jsonify({'error':str(e.description or e.name)}), e.code
@app.errorhandler(ModuleNotFoundError)
def missing_library(e):
 import dependencies
 app.logger.error('Missing library: %s',e)
 return jsonify({'error':dependencies.friendly_error(e),'missing_dependency':(getattr(e,'name','') or '').split('.')[0]}),503

@app.get('/api/dependencies')
def dependency_status():
 import dependencies
 return jsonify(dependencies.status())

@app.post('/api/dependencies/repair')
def dependency_repair():
 import dependencies
 started=dependencies.start_repair(BASE)
 return jsonify({**dependencies.status(),'started':started}),202

@app.errorhandler(500)
def internal(e):return jsonify({'error':'The operation could not finish. Your saved project remains on disk. Check server diagnostics.'}),500
if __name__=='__main__':app.run(host=os.environ.get('STORYROOM_HOST','127.0.0.1'),port=int(os.environ.get('PORT','8004')),threaded=True,debug=False)
