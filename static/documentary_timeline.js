/* Documentary-only timeline. The current review MP4 is a synchronized clock:
   narration and the single selected source-audio track are already mixed. */
window.docTimelineData=null;
let docTimelineGeneration=0,docTimelineTimer=null,docPlayGeneration=0,docSpeechWaveKey='',docSpeechPeaks=null,docSpeechDuration=0;
window.cancelDocPlay=function(){docPlayGeneration++;docDirectToken++;docDirectBusy=false;docNextToken++;docNextEvent=null;/* Stop silences every picture element: after a promote the live one is not the one docStandby() points at. */try{[masterNode,sourceNode,nextSourceNode,document.getElementById('program-source-next')].forEach(n=>{try{n&&n.pause()}catch{}})}catch{}try{docStandby().pause()}catch{}try{masterNode.classList.remove('is-live');sourceNode.classList.remove('is-live')}catch{}try{if(docMusicNode&&!docMusicNode.paused)docMusicNode.pause()}catch{}};
window.resetDocTimeline=function(){
 window.docTransitionPreviewOverride=null;window.docTransitionPreviewInfo=null;docTrackCache={};
 docPlayGeneration++;docTimelineGeneration++;clearTimeout(docTimelineTimer);docTimelineTimer=null;window.docTimelineData=null;
 musicReadSequence++;docMusic={};window.docMusicCard=null;docTrackVolume={audio:100,video:0,music:35,narration:100,clip:100};
 if(docMusicNode){docMusicNode.pause();docMusicNode.removeAttribute('src');docMusicNode.load()}
 if(P?.edit_mode==='documentary')window.docLoadMusic();
};
window.ensureDocTimeline=function(){const d=window.docTimelineData;if(P?.edit_mode!=='documentary'){if(d)resetDocTimeline();return}
 if(!d||d.id!==P.id){reloadDocTimeline();return}
 if(d.version===P.updated)return;
 // A transition, caption, scale or approval changes the project but not the sound or
 // the cuts. Refresh in place and keep playing; only a real audio change reloads.
 if(d.status==='ready'&&!d.loading&&d.direct){softReloadDocTimeline();return}
 reloadDocTimeline()};
let docSoftBusy=false,docSoftAgain=false;
window.softReloadDocTimeline=async function(){
 if(docSoftBusy){docSoftAgain=true;return}
 docSoftBusy=true;
 try{
  do{
   docSoftAgain=false;
   const d=window.docTimelineData,id=P.id,version=P.updated;if(!d||d.id!==id)return;
   const [plan,timeline,state]=await Promise.all([api(`/api/projects/${id}/documentary-bites`),api(`/api/projects/${id}/documentary-timeline`),api(`/api/projects/${id}/documentary-audio`)]);
   if(window.docTimelineData!==d||P?.id!==id)return;
   // Different sound (a bite moved, new narration): this needs the full reload, and
   // the preview audio is prepared again by itself.
   if(plan.revision!==d.revision||state.status!=='done'||state.url!==d.url){reloadDocTimeline();return}
   d.version=version;d.bites=plan.bites;d.levels=state.sound_bite_levels||d.levels;
   // Music is its own live layer: a new or changed bed starts right away.
   const musicUrl=await docMusicUrl();
   if(window.docTimelineData!==d||P?.id!==id)return;
   d.musicUrl=musicUrl;
   if(editorPlaying)docSyncMusic(narrNode.currentTime||0,true);
   const tail=d.tail||0,segments=[...timeline.segments];
   if(tail>.001)segments.push({kind:'picture_tail',source_in_s:timeline.narration_duration_s,source_out_s:timeline.narration_duration_s+tail,timeline_in_s:timeline.duration_s,timeline_out_s:timeline.duration_s+tail});
   d.segments=segments;docTrackCache={};
   // The frame schedule follows in the background; the old one keeps playing until then.
   docLoadSchedule(id,version,plan.revision,docTimelineGeneration,true);
   if(!editorPlaying)renderProject();else if(typeof renderTimeline==='function')renderTimeline();
  }while(docSoftAgain);
 }catch(e){reloadDocTimeline()}
 finally{docSoftBusy=false}
};
// While the audio mix renders, poll only the tiny job record. Re-running the full
// load every 1.5s re-fetched the 65KB schedule and re-rendered the whole editor,
// which is what made "preparing" feel stuck. A full load happens only once, when
// the job actually finishes.
window.docPollAudioState=async function(){
 clearTimeout(docTimelineTimer);const d=window.docTimelineData;
 if(P?.edit_mode!=='documentary'||!d||d.loading)return;
 if(!['queued','running'].includes(d.status))return;
 const id=P.id,token=docTimelineGeneration;
 try{
  const st=await api(`/api/projects/${id}/documentary-audio`);
  if(token!==docTimelineGeneration||P?.id!==id||window.docTimelineData!==d)return;
  if(st.status==='done'){reloadDocTimeline();return}
  if(!['queued','running'].includes(st.status)){reloadDocTimeline();return}
  // Show real progress without touching the picture or the schedule.
  if(typeof st.completed==='number'&&st.total){
   const pct=Math.round(st.completed/st.total*100);
   const el=document.querySelector('#monitor-empty span');
   if(el)el.textContent=`Preparing documentary audio preview… ${st.completed} of ${st.total} segments (${pct}%)`;
  }
  docTimelineTimer=setTimeout(docPollAudioState,1200);
 }catch(e){docTimelineTimer=setTimeout(docPollAudioState,3000)}
};
// When a change needs new sound (a moved bite, new narration), the timeline has to
// reload and its preview audio is prepared again. Playback picks up again by itself
// at the same moment once that is ready, instead of waiting for another click.
let docResume=null;
window.reloadDocTimeline=async function(){
 if(P?.edit_mode!=='documentary')return;
 // Nothing to play until narration and SRT exist; asking would only log an error.
 if(!P.voiceover||!(P.srt?.blocks||[]).length){window.docTimelineData={id:P.id,version:P.updated,loading:false,duration:0,segments:[],bites:[],status:'empty'};window.updateDocumentaryTimelineNotice?.();return}
 const id=P.id,version=P.updated,token=++docTimelineGeneration;clearTimeout(docTimelineTimer);
 if(editorPlaying){docResume={id,t:narrNode.currentTime||0};pauseEditor()}docTrackCache={};window.docTimelineData={id,version,loading:true,duration:0,segments:[],bites:[],status:'loading'};window.updateDocumentaryTimelineNotice?.();
 try{
  // A request that never answers must not leave the timeline on "Loading" for good:
  // after 40 seconds it is abandoned and the load is tried again.
  const patient=(promise)=>Promise.race([promise,new Promise((_,reject)=>setTimeout(()=>reject(Object.assign(new Error('The editor is busy; trying again.'),{slow:true})),40000))]);
  const direct=!!P?.documentary_beat_review;const [plan,timeline,state]=await patient(Promise.all([api(`/api/projects/${id}/documentary-bites`),api(`/api/projects/${id}/documentary-timeline`),api(`/api/projects/${id}/`+(direct?'documentary-audio':'documentary-review-preview'))]));// The schedule is planning data from the audited picture plan, not part of the
// The schedule is planning data, not part of the rendered mix, so it must not
// wait for the audio render. It also audits every source frame (over a minute on
// a large storyboard), so it is never awaited here: the tracks and the picture
// draw from the segments immediately, then the schedule fills in and the monitor
// repaints. Awaiting it froze the whole editor on load.
let schedule=null;
  if(token!==docTimelineGeneration||P?.id!==id||P?.updated!==version)return;
  // Music is played as its own layer against the same clock, so changing its
  // level never needs the audio mix to be rebuilt.
  const musicUrl=await docMusicUrl();
  if(token!==docTimelineGeneration||P?.id!==id||P?.updated!==version)return;
  // A Beat-built storyboard is laid out on the programme clock (narration + sound bites),
  // so its end is compared with the programme length. Comparing it with the narration
  // alone counted every second of sound bite twice and drew a long silent "tail" with
  // the pictures sliding later and later past the voice.
  const master=docScenesOnMaster(),pictureEnd=scenes().at(-1)?.frame_out/30||0,clockEnd=master?timeline.duration_s:timeline.narration_duration_s,rawTail=Math.max(0,pictureEnd-clockEnd),tail=rawTail>=1/30-1e-6?rawTail:0,segments=[...timeline.segments];
  if(tail>.001)segments.push({kind:'picture_tail',source_in_s:master?timeline.narration_duration_s:timeline.narration_duration_s,source_out_s:master?timeline.narration_duration_s+tail:pictureEnd,timeline_in_s:timeline.duration_s,timeline_out_s:timeline.duration_s+tail});
  if(schedule&&(schedule.project_version!==version||schedule.plan_revision!==plan.revision))throw Error('The storyboard changed while preparing playback.');window.docTimelineData={id,version,loading:false,revision:plan.revision,bites:plan.bites,segments,duration:direct&&state.status==='done'?state.duration_s:timeline.duration_s+tail,tail,direct,schedule:schedule?.events||[],status:direct&&state.status==='done'?'ready':state.status,url:state.url||'',renderer:state.renderer||'',detail:state.detail||'',levels:state.sound_bite_levels||[],music_url:musicUrl};
  // First time this film is shown, fit the whole timeline to the window.
  if(window.__fitZoomFor!==id&&typeof fitTimelineZoom==='function'){window.__fitZoomFor=id;fitTimelineZoom(window.docTimelineData.duration,false)}
  renderProject();window.updateDocumentaryTimelineNotice?.();
  // Fetch the frame-accurate schedule in the background. It is slow (a full
  // source-frame audit), so it must never hold up the first paint; the monitor
  // simply becomes accurate, including bite boundaries, once it arrives.
  if(direct)docLoadSchedule(id,version,plan.revision,token);
  // No preview yet, or an edit made it out of date: prepare it now, without a click.
  if(direct&&['idle','stale'].includes(state.status)&&scenes().length)docAutoPrepare(id,version);
  if(docResume&&docResume.id===id&&direct&&state.status==='done'&&window.docTimelineData?.url){
   const at=Math.min(docResume.t,(window.docTimelineData.duration||docResume.t)-.05);docResume=null;
   setTimeout(()=>{if(P?.id===id&&!editorPlaying){docSeekTimeline(at,false);docPlayTimeline()}},150);
  }
  if(window.docLoadMusic)window.docLoadMusic();
  if(['queued','running'].includes(state.status))docTimelineTimer=setTimeout(docPollAudioState,1200);
 }catch(e){if(token!==docTimelineGeneration||P?.id!==id)return;if(e.slow){window.docTimelineData={...window.docTimelineData,detail:e.message};window.updateDocumentaryTimelineNotice?.();docTimelineTimer=setTimeout(()=>{if(P?.id===id&&token===docTimelineGeneration)reloadDocTimeline()},3000);return}window.docTimelineData={id,version,loading:false,duration:0,segments:[],bites:[],direct:!!P?.documentary_beat_review,status:'error',detail:e.message};renderProject();window.updateDocumentaryTimelineNotice?.()}
};
// One automatic start per project version. A failure is shown, not retried in a loop;
// the button stays there to try again by hand.
const docAutoPrepared=new Set();
async function docAutoPrepare(id,version){
 const key=id+':'+version;if(docAutoPrepared.has(key))return;docAutoPrepared.add(key);
 try{await api(`/api/projects/${id}/documentary-audio`,'POST')}
 catch(e){if(!/already being prepared/.test(e.message||''))return}
 if(P?.id===id&&P?.updated===version)reloadDocTimeline();
}
function docRenderProgram(){
 const d=window.docTimelineData,ready=d?.status==='ready'&&d.url;
 // Repainting the editor must not interrupt what is already playing. When the
 // same timeline is already on screen and running, leave the players alone.
 const sameReady=ready&&d.direct&&editorPlaying&&narrNode.getAttribute('src')===d.url&&!narrNode.paused;
 if(sameReady){
  masterNode.muted=true;masterNode.classList.add('is-active');
  $('#monitor-empty').hidden=true;
  $('#preview-mode').textContent='BROWSER REVIEW · LIVE APPROXIMATE TRANSITIONS';
  return;
 }
 const prepare=$('#documentary-prepare-timeline');prepare.hidden=!!(P?.edit_mode==='documentary'&&P?.script_reading?.status==='not_detailed'&&!scenes().length);prepare.disabled=!d||d.loading||['running','queued'].includes(d.status);prepare.textContent=['running','queued'].includes(d?.status)?'Preparing timeline preview…':(P?.documentary_beat_review?'Rebuild timeline from latest script':ready?'Refresh timeline preview':'Prepare timeline preview');prepare.title=d?.direct?'Browser review playback; cuts may be approximate and the preview has no fade.':'';
 sourceNode.pause();nextSourceNode.pause();sourceNode.muted=true;nextSourceNode.muted=true;sourceNode.classList.remove('is-active');nextSourceNode.classList.remove('is-active');imageNode.hidden=true;editorMaster=true;
 if(ready&&d.direct){if(narrNode.getAttribute('src')!==d.url){narrNode.pause();narrNode.src=d.url;narrNode.load();docDirectEvent=null;docPictureAt=null;docResetStandby();liveNode=masterNode}masterNode.muted=true;masterNode.classList.add('is-active');$('#monitor-empty').hidden=true;$('#preview-mode').textContent='BROWSER REVIEW · LIVE APPROXIMATE TRANSITIONS';if(!editorPlaying)docDirectSwitch(narrNode.currentTime||0,false);return}
 narrNode.pause();
 if(ready){
  if(masterUrl!==d.url){masterNode.pause();masterUrl=d.url;masterNode.src=d.url;masterNode.load()}
  masterNode.classList.add('is-active');$('#monitor-empty').hidden=true;$('#preview-mode').textContent='DOCUMENTARY TIMELINE · REVIEW PREVIEW';
 }else{
  masterNode.pause();masterNode.classList.remove('is-active');if(masterUrl){masterUrl='';masterNode.removeAttribute('src');masterNode.load()}
  $('#monitor-empty').hidden=false;
  const beatPlan=!!(P?.edit_mode==='documentary'&&P?.script_reading?.status==='not_detailed'&&!scenes().length);
  // `d.detail` is a diagnostic string. It is shown here only when the project is
  // merely not prepared yet -- never when the timeline failed, because a raw
  // sentence about a stored value is not something to put in the middle of the
  // monitor. A failure gets one plain line; the detail goes to the button's tooltip.
  const failed=!!d&&!d.loading&&d.status&&d.status!=='ready'&&!['queued','running','idle','stale'].includes(d.status);
  const starting=!!d&&!d.loading&&['idle','stale'].includes(d.status)&&scenes().length>0;
  const ready=!!d&&!d.loading&&!failed;
  // The timeline builds itself; say what it is doing instead of asking for a click.
  const auto=P?.auto_build||{};
  const autoText=!scenes().length||auto.status==='building'?(auto.status==='building'?`Building the timeline from your production script…${auto.progress!=null?' '+Math.round(Number(auto.progress)*100)+'%':''} It appears here by itself.`
    :auto.status==='waiting'?auto.reason
    :auto.status==='review'?'One production input needs attention: '+auto.reason
    :auto.status==='error'?'The timeline could not be built: '+auto.reason:''):'';
  const text=autoText?autoText:beatPlan?'The script is read, but no picture is built yet. Review the Beat picture plan to place each Beat\u2019s footage, then this monitor plays it.'
   :failed?'This project is not ready to preview yet. Prepare it again after its narration and timeline are complete.'
   :starting?'Preparing the timeline preview… It plays here as soon as it is ready.'
   :P?.documentary_beat_review?(d?.loading?'Loading the documentary timeline…':(ready&&d?.detail)||'Prepare the timeline preview to play. Browser cuts are approximate; the preview has no fade.')
   :d?.loading?'Loading the documentary timeline…':(ready&&d?.detail)||'Prepare a timeline preview to play the sound bite with your narration.';
  const action=autoText&&auto.status!=='error'?'':beatPlan?'<button class="button secondary" type="button" onclick="openBeatProposal()">Review the Beat picture plan</button>':d&&!d.loading&&!['queued','running'].includes(d.status)?'<button class="button secondary" type="button" onclick="docPrepareTimeline()">Prepare timeline preview</button>':'';
  $('#monitor-empty').innerHTML=`<strong>${autoText?(auto.status==='building'?'Building the timeline':auto.status==='review'?'Check the production inputs':auto.status==='error'?'Timeline not built':'Waiting for files'):beatPlan?'Picture beats not built yet':'Documentary timeline preview'}</strong><span>${E(text)}</span>${action}`;$('#preview-mode').textContent=beatPlan?'DOCUMENTARY PICTURE NOT BUILT':'DOCUMENTARY PREVIEW NOT READY';
 }
}
// Loaded after the first paint. One request per project version; the result is
// kept so switching scenes or repainting never re-triggers the audit.
const docScheduleCache=new Map();
async function docLoadSchedule(id,version,revision,token,soft){
 const key=id+':'+version;const cached=docScheduleCache.get(key);
 const apply=(events,warnings)=>{const d=window.docTimelineData;
  if(!d||d.id!==id||d.version!==version||token!==docTimelineGeneration)return;
  d.schedule=events||[];d.scheduleReady=true;d.scheduleWarnings=warnings||[];docUpdatePosition();docShowCutawayMarkers();
  // The schedule is what tells the monitor WHICH frame belongs here. Until it
  // arrives nothing can be loaded, so its arrival must repaint the picture --
  // otherwise the monitor stays black while the player sits marked active.
  if(!editorPlaying)d.schedule.length&&docDirectSwitch(narrNode.currentTime||0,false);
  // A quiet refresh mid-playback: the next cut uses the new schedule; the shot on
  // screen carries on rather than being reloaded.
  if(soft&&editorPlaying){docNextEvent=null;docNextToken++}
 };
 if(cached){apply(cached.events,cached.warnings);return}
 if(docScheduleCache.get(key+':loading'))return;
 docScheduleCache.set(key+':loading',true);
 try{
  const data=await api(`/api/projects/${id}/documentary-beat-playback-schedule`);
  if(data&&data.project_version!==version)return;           // storyboard moved on
  const events=data?.events||[],warnings=data?.warnings||[];
  docScheduleCache.set(key,{events,warnings});
  apply(events,warnings);
  // A changed script is worth saying out loud: the picture still plays, but it is
  // the one built earlier. It used to fail silently, so the monitor simply stayed
  // black with no explanation anywhere on the page.
  if(warnings.length)toast(warnings[0]);
 }catch(e){
  // The segments still drive playback, so a missing schedule must not stop the
  // editor -- but it also must not be silent, because without a schedule the
  // monitor has no frame to show and sitting there black looks like a crash.
  const d=window.docTimelineData;
  if(d&&d.id===id&&d.version===version&&token===docTimelineGeneration){
   d.scheduleUnavailable=e.message;
   if(!editorPlaying)docShowScheduleFailure(e.message);
  }
  toast('Frame-accurate playback could not be prepared: '+e.message);
 }finally{docScheduleCache.delete(key+':loading')}
}
// When the frame schedule cannot be built the monitor has no picture to show, and
// that must be visible in the monitor itself. It used to be swallowed, so the
// player was marked active, the empty-state was hidden, and the screen was black
// with nothing anywhere saying why.
function docShowScheduleFailure(detail){
 const box=$('#monitor-empty');if(!box)return;
 box.hidden=false;
 box.innerHTML=`<strong>This timeline cannot be played yet</strong><span>${E(detail||'The frame-accurate picture schedule could not be built.')}</span>`;
 const mode=$('#preview-mode');if(mode)mode.textContent='DOCUMENTARY PREVIEW BLOCKED';
}
// Two clocks live on this timeline. SRT cues are narration-clock times; scenes of a
// Beat-built storyboard are programme-clock times (the builder and the export both
// place them there). Older review storyboards kept scenes on the narration clock.
function docScenesOnMaster(){return !!P?.documentary_beat_review}
function docProgramSpans(start,end){const d=window.docTimelineData;if(!d)return [];return d.segments.filter(x=>x.kind==='narration'||x.kind==='picture_tail').flatMap(x=>{const a=Math.max(start,x.timeline_in_s),b=Math.min(end,x.timeline_out_s);return b>a?[{start:a,end:b}]:[]})}
function docPictureSpans(start,end){return docScenesOnMaster()?docProgramSpans(start,end):docNarrationSpans(start,end)}
function docNarrationSpans(start,end){const d=window.docTimelineData;if(!d)return [];return d.segments.filter(x=>x.kind==='narration'||x.kind==='picture_tail').flatMap(x=>{const a=Math.max(start,x.source_in_s),b=Math.min(end,x.source_out_s);return b>a?[{start:x.timeline_in_s+a-x.source_in_s,end:x.timeline_in_s+b-x.source_in_s}]:[]})}
// A cue shot is a display group, not a merge of source ranges. Physical slots
// stay individually selectable and keep their original saved timings/approvals.
function docCueGroups(){
 if(!P?.documentary_beat_review||!P?.srt?.blocks?.length)return null;
 // v19: index by cue number once (this was a search through every cue for every shot,
 // about 600,000 steps on an hour-long film, on every redraw).
 const groups=P.srt.blocks.map(b=>({cue:b.number,slots:[]})),byCue=new Map(groups.map(g=>[g.cue,g])),indexOf=new Map(groups.map((g,i)=>[g,i]));if(byCue.size!==groups.length)return null;let last=-1;
 for(const [i,s] of scenes().entries()){const numbers=s.plan_row?.srt_blocks||[],g=byCue.get(numbers[0]),index=g?indexOf.get(g):-1;if(numbers.length!==1||!g||index<last||!Number.isFinite(s.plan_row?.timeline_in_ms)||!Number.isFinite(s.plan_row?.timeline_out_ms))return null;last=index;g.slots.push({scene:s,index:i})}
 return groups.every(g=>g.slots.length)?groups:null;
}
function docGroupSpans(start,end){
 const result=[];for(const span of docPictureSpans(start,end)){const previous=result.at(-1);if(previous&&Math.abs(previous.end-span.start)<.00001)previous.end=span.end;else result.push({...span})}return result;
}
function docGroupedPictureClips(groups){
 const result=[];
 for(const group of groups){const first=group.slots[0].scene,last=group.slots.at(-1).scene;
  for(const fragment of docGroupSpans(first.plan_row.timeline_in_ms/1000,last.plan_row.timeline_out_ms/1000)){
   const children=[];
   for(const item of group.slots){const s=item.scene,a=assets().find(x=>x.id===s.asset_id);
    for(const span of docGroupSpans(s.plan_row.timeline_in_ms/1000,s.plan_row.timeline_out_ms/1000)){
     const start=Math.max(span.start,fragment.start),end=Math.min(span.end,fragment.end);if(end<=start)continue;
     const thumb=a?`/api/projects/${P.id}/scenes/${s.id}/thumbnail?v=${encodeURIComponent(a.revision||a.id)}&in=${encodeURIComponent(s.in_s||0)}`:'';
     children.push(`<div class="shot-clip doc-cue-slot ${selectedSlotIds.has(s.id)?'selected':''}" data-scene="${item.index}" role="button" tabindex="0" title="Cue shot ${E(group.cue)} · picture slot ${item.index+1} · ${E(a?.original_name||a?.name||'media needed')}" style="left:${(start-fragment.start)*timelineZoom}px;width:${Math.max(1,(end-start)*timelineZoom)}px" onclick="docSelectAt(${item.index},${start},event)">${thumb?`<img class="clip-thumb" src="${thumb}" loading="lazy" alt="">`:''}</div>`)
    }
   }
   result.push(`<div class="doc-cue-shot" data-cue="${E(group.cue)}" style="left:${fragment.start*timelineZoom}px;width:${Math.max(1,(fragment.end-fragment.start)*timelineZoom-1)}px" aria-label="Cue shot ${E(group.cue)} · ${group.slots.length} preserved picture slot${group.slots.length===1?'':'s'}"><div class="doc-cue-label">Shot ${E(group.cue)}</div>${children.join('')}</div>`)
  }
 }
 return result;
}
// Repainting 127 clips and 120 caption blocks costs ~35 ms, and the editor
// repaints on every selection, inspector and approval action. The markup only
// depends on the timeline data, the zoom, the selection and the scale preview,
// so it is cached and only rebuilt when one of those actually changes.
let docTrackCache={};
function docTrackKey(d,part){
 const sel=[...selectedSlotIds].sort().join(',');
 const scale=slotScalePreview?slotScalePreview.value+'@'+[...slotScalePreview.ids].sort().join(','):'';
 return [part,d.id,d.revision,timelineZoom,sel,scale,d.duration,d.segments.length].join('|');
}
function docRenderTimeline(){
 const d=window.docTimelineData;const button=$('#documentary-prepare-timeline');button.hidden=false;
 // An error and a load in progress both leave the tracks empty, so they must not
 // paint the same "loading" note: a failure sat there looking like a load that
 // never finished, with no way to tell what had gone wrong.
 if(!d||d.loading||!d.segments.length){
  $('#timeline-content').style.width='600px';$('#ruler-track').innerHTML='';$('#video-track').innerHTML='';
  $('#doc-source-track').innerHTML='';$('#audio-track').innerHTML='';
  // No raw failure sentence in the track. The timeline is a strip of the film, not a
  // console: a sentence naming an internal condition sat there in capitals for as long
  // as the project stayed in that state, and read like a crash. It is replaced by the
  // one thing a picture track is allowed to say when it has nothing to show.
  // The detail is not thrown away -- it goes to the button's tooltip and to the
  // console, so a report can still be diagnosed.
  const failed=!!d&&d.status&&d.status!=='loading'&&d.status!=='ready'&&!d.segments.length;
  const prepare=$('#documentary-prepare-timeline');
  if(prepare){
   if(failed&&d.detail){
    prepare.title=d.detail;
    if(window.docTimelineProblem!==d.detail){window.docTimelineProblem=d.detail;console.warn('[documentary timeline]',d.detail)}
   }else{prepare.removeAttribute('title')}
  }
  const note=d?.status==='loading'||!d?'Loading picture track…'
   :(d.segments.length?'':'No picture track yet');
  $('#caption-track').innerHTML=`<span class="caption-note">${E(note)}</span>`;
  return}
 const width=Math.max(d.duration*timelineZoom,$('#timeline-scroll').clientWidth-2,600);$('#timeline-content').style.width=width+'px';// The toolbar carries no counts: the top bar already reports cue shots,
 // picture slots and approvals, and the strip under the timeline was noise.
 $('#track-legend').textContent='';
 const step=timelineZoom<5?60:30;let ticks='';for(let t=0;t<=d.duration+step;t+=step)ticks+=`<span class="ruler-tick" style="left:${t*timelineZoom}px">${String(Math.floor(t/60)).padStart(2,'0')}:${String(t%60).padStart(2,'0')}</span>`;if(docTrackCache.rulerKey!==docTrackKey(d,'ruler')){docTrackCache.rulerKey=docTrackKey(d,'ruler');$('#ruler-track').innerHTML=ticks}
 const videoKey=docTrackKey(d,'video');
 // Skip the whole clip build when nothing that affects it has changed.
 const videoHit=docTrackCache.videoKey===videoKey&&docTrackCache.video;
 const cueGroups=videoHit?null:docCueGroups();const clips=videoHit?[]:cueGroups?docGroupedPictureClips(cueGroups):[];if(!videoHit&&!cueGroups)scenes().forEach((s,i)=>{const a=assets().find(x=>x.id===s.asset_id);for(const span of docPictureSpans(s.frame_in/30,s.frame_out/30)){const thumb=a?`/api/projects/${P.id}/scenes/${s.id}/thumbnail?v=${encodeURIComponent(a.revision||a.id)}&in=${encodeURIComponent(s.in_s||0)}`:'';clips.push(`<div class="shot-clip ${selectedSlotIds.has(s.id)?'selected':''}" data-scene="${i}" role="button" tabindex="0" style="left:${span.start*timelineZoom}px;width:${Math.max(3,(span.end-span.start)*timelineZoom-1)}px" onclick="docSelectAt(${i},${span.start},event)">${thumb?`<img class="clip-thumb" src="${thumb}" loading="lazy" alt="">`:''}<div class="clip-text"><strong>${E(s.plan_row?.shot_id||'Scene '+(i+1))} · ${E(a?.original_name||a?.name||'MEDIA NEEDED')}</strong><span>Original clip muted</span></div></div>`)}});
 for(const seg of d.segments.filter(s=>s.kind==='sound_bite')){const thumbs=Array.from({length:4},(_,i)=>{const time=seg.source_in_s+(seg.source_out_s-seg.source_in_s)*(i+.5)/4;return `<img src="/api/projects/${P.id}/assets/${E(seg.asset_id)}/timeline-thumbnail?at=${time.toFixed(3)}&v=${encodeURIComponent((assets().find(x=>x.id===seg.asset_id)||{}).revision||seg.asset_id)}" loading="lazy" alt="" onerror="this.hidden=true">`}).join('');clips.push(`<div class="shot-clip documentary-soundbite" role="button" style="left:${seg.timeline_in_s*timelineZoom}px;width:${Math.max(3,(seg.timeline_out_s-seg.timeline_in_s)*timelineZoom-1)}px" onclick="docSeekTimeline(${seg.timeline_in_s},false)"><div class="doc-soundbite-thumbs" aria-hidden="true">${thumbs}</div><div class="clip-text"><strong>🔊 ${E(seg.asset_name)} · sound bite</strong><span>Source ${docTime(seg.source_in_s)}–${docTime(seg.source_out_s)}</span></div></div>`)}if(!videoHit){
  // Small markers make saved transitions visible on the real shot boundaries.
  // Subtitle-only boundaries do not get a transition marker.
  const items=scenes();for(let i=0;i<items.length-1;i++){
   const scene=items[i],next=items[i+1];if(!scene.transition||scene.transition==='cut')continue;
   if(scene.asset_id===next.asset_id&&Math.abs(Number(next.in_s||0)-Number(scene.in_s||0))<.002)continue;
   const at=next.frame_in/30,key=String(scene.transition).replace(/[^a-z0-9-]/gi,'');
   clips.push(`<button type="button" class="doc-applied-transition" style="left:${at*timelineZoom}px" title="Applied transition: ${E(scene.transition)}. Open transition preview." onclick="openTransitionLibrary('${scene.id}')" aria-label="Applied transition ${E(scene.transition)}">↔</button>`);
  }
  docTrackCache.videoKey=videoKey;docTrackCache.video=clips.join('');$('#video-track').innerHTML=docTrackCache.video;docShowCutawayMarkers()
 }
 if(docTrackCache.captionKey!==docTrackKey(d,'captions'))$('#caption-track').innerHTML=(()=>{const key=docTrackKey(d,'captions');const html=(P?.srt?.blocks||[]).flatMap((b,i)=>docNarrationSpans(b.start_ms/1000,b.end_ms/1000).map(span=>`<div class="caption-block" data-caption-index="${i}" title="${E(b.text)}" style="left:${span.start*timelineZoom}px;width:${Math.max(2,(span.end-span.start)*timelineZoom-1)}px" onclick="docSeekTimeline(${span.start},true)">${E(b.text)}</div>`)).join('')+'<span class="caption-note" style="left:8px">SRT REFERENCE · ORIGINAL UNCHANGED</span>';docTrackCache.captionKey=key;docTrackCache.caption=html;return html})();
 if(!videoHit)$('#doc-source-track').innerHTML=d.segments.filter(seg=>seg.kind==='sound_bite').map(seg=>`<div class="audio-clip doc-audio-bite" role="button" tabindex="0" title="Drag to move the sound bite; narration splits at its new position" data-bite="${E(seg.id)}" data-start="${seg.source_in_s}" data-end="${seg.source_out_s}" style="left:${seg.timeline_in_s*timelineZoom}px;width:${Math.max(3,(seg.timeline_out_s-seg.timeline_in_s)*timelineZoom-1)}px" onpointerdown="docStartBiteDrag(event)"><canvas class="audio-waveform speech-wave" aria-hidden="true"></canvas><div class="audio-label"><strong>↔ Footage speech · ${E(seg.asset_name)}</strong><span>Source ${docTime(seg.source_in_s)}–${docTime(seg.source_out_s)} · drag to move</span></div></div>`).join('');
 if(!videoHit)$('#audio-track').innerHTML=d.segments.filter(seg=>seg.kind==='narration'||seg.kind==='picture_tail').map(seg=>{const width=Math.max(3,(seg.timeline_out_s-seg.timeline_in_s)*timelineZoom-1),left=seg.timeline_in_s*timelineZoom;
  if(seg.kind==='picture_tail')return `<div class="audio-clip doc-tail" style="left:${left}px;width:${width}px" title="Silent picture tail"></div>`;
  return `<div class="audio-clip doc-narration" role="button" tabindex="0" style="left:${left}px;width:${width}px" onclick="seekAudioTrack(event)"><canvas class="audio-waveform" data-start="${seg.source_in_s}" data-end="${seg.source_out_s}" aria-hidden="true"></canvas><div class="audio-label"><strong>♫ ${E(P.voiceover?.name||'Narration')}</strong><span>${docTime(seg.source_in_s)}–${docTime(seg.source_out_s)}</span></div></div>`;
 }).join('');
 // Waveforms are drawn after the clips have painted, and only when their canvases
 // were rebuilt: redrawing every canvas on an unchanged timeline cost ~40 ms.
 if(!videoHit)requestAnimationFrame(()=>{if(P?.voiceover?.url)loadNarrationWaveform(P.voiceover);loadDocBiteWaveforms()});
}
// Lightweight, non-intrusive picture-only markers; never changes the audio track.
function docShowCutawayMarkers(){
 const track=document.getElementById('video-track'),d=window.docTimelineData;
 if(!track||!d)return;
 track.querySelectorAll('.doc-cutaway-indicator').forEach(n=>n.remove());
 const entries=(d.schedule||[]).filter(s=>s.cutaway_id);
 for(const s of entries){const node=document.createElement('button');
  node.type='button';node.className='doc-cutaway-indicator';
  node.style.left=`${s.timeline_in_ms/1000*timelineZoom}px`;
  node.style.width=`${Math.max(18,(s.timeline_out_ms-s.timeline_in_ms)/1000*timelineZoom)}px`;
  node.textContent='CUTAWAY';node.title=`${s.cutaway_id} · picture only (source audio continues)`;
  node.onclick=()=>docSeekTimeline(s.timeline_in_ms/1000,false);track.appendChild(node);
 }
}
// v19: a waveform is drawn when its clip comes near the visible part of the timeline,
// not all at once: an hour-long film has hundreds of canvases, and drawing them all
// held the page for over 100 ms after every zoom.
let docWaveObserver=null;
function docLazyDraw(canvas,draw){
 if(!('IntersectionObserver' in window)){draw(canvas);return}
 if(!docWaveObserver)docWaveObserver=new IntersectionObserver(entries=>{for(const e of entries){if(!e.isIntersecting)continue;docWaveObserver.unobserve(e.target);const fn=e.target._waveDraw;e.target._waveDraw=null;if(fn&&e.target.isConnected)fn(e.target)}},{root:document.getElementById('timeline-scroll'),rootMargin:'0px 1200px'});
 canvas._waveDraw=draw;docWaveObserver.unobserve(canvas);docWaveObserver.observe(canvas);
}
function docDrawNarrationWave(c){
 if(!waveformPeaks||!P?.voiceover?.duration)return;const w=Math.max(1,Math.min(8192,Math.ceil(c.clientWidth))),h=40,start=Number(c.dataset.start)/P.voiceover.duration,end=Number(c.dataset.end)/P.voiceover.duration;c.width=w;c.height=h;const ctx=c.getContext('2d');ctx.fillStyle='rgba(180, 255, 227, .65)';for(let x=0;x<w;x++){const a=Math.floor((start+(end-start)*x/w)*waveformPeaks.length),b=Math.max(a+1,Math.floor((start+(end-start)*(x+1)/w)*waveformPeaks.length));let peak=0;for(let i=a;i<b&&i<waveformPeaks.length;i++)peak=Math.max(peak,waveformPeaks[i]);if(peak>0){const height=Math.max(1,peak*(h-4));ctx.fillRect(x,(h-height)/2,1,height)}}}
function docDrawNarrationWaveforms(){
 if(!waveformPeaks||!P?.voiceover?.duration)return;for(const c of document.querySelectorAll('#audio-track .doc-narration .audio-waveform'))docLazyDraw(c,docDrawNarrationWave);
}
// Direct Beat playback is an approximate browser review, not a final render.
//
// The mixed narration WAV is the clock: it already contains every bite at its
// planned pause, so it starts once and then runs uninterrupted. Picture follows
// the clock and must never stall it. Two elements are used throughout: `liveNode`
// shows the current cut, `standbyNode` pre-rolls the next one. At a cut the two
// roles swap, so a prepared picture is already decoded and simply appears.
let docDirectEvent=null,docDirectBusy=false,docDirectToken=0;
let docNextEvent=null,docNextToken=0,docPictureAt=null;
let liveNode=masterNode,standbyNodeEl=null;
// Prepare the next picture well before the cut. A source clip is tens of MB and
// must be fetched and seeked on the standby element; at 1.5s the incoming
// picture arrived after the cut, leaving the monitor blank while audio ran on.
const DOC_PREROLL_S=8;
const DOC_DRIFT_S=0.08;    // picture/clock drift tolerated before correcting
function docStandby(){return standbyNodeEl||(standbyNodeEl=($('#program-source-next')||nextSourceNode))}
// Most playback frames stay in the same event. A cursor + binary search avoids
// rescanning hundreds of schedule rows on every animation frame or mouse move.
let docEventIndex=-1,docEventSchedule=null;
function docDirectIndex(t){
 const events=window.docTimelineData?.schedule||[],ms=t*1000;
 if(events!==docEventSchedule){docEventIndex=-1;docEventSchedule=events}
 const previous=events[docEventIndex];
 if(previous&&ms>=previous.timeline_in_ms&&ms<previous.timeline_out_ms)return docEventIndex;
 let lo=0,hi=events.length;
 while(lo<hi){const mid=(lo+hi)>>1;if(events[mid].timeline_in_ms<=ms)lo=mid+1;else hi=mid}
 const idx=lo-1,part=events[idx];docEventIndex=part&&ms<part.timeline_out_ms?idx:-1;
 return docEventIndex;
}
function docDirectAt(t){const i=docDirectIndex(t);return i<0?null:docEventSchedule[i]}
function docNextAt(t){const i=docDirectIndex(t);return i<0?null:docEventSchedule[i+1]||null}
function docPhotoFrame(part){
 const scene=part?.scene_id?scenes().find(s=>s.id===part.scene_id):null;
 const asset=assets().find(a=>a.id===part?.asset_id);
 return scene?.photo_frame_url||(asset?.kind==='image'?(asset.clean_url||asset.url):'');
}
function docDesiredTime(part,t){
 const [num,den]=(String(part.source_fps).includes('/')?part.source_fps:part.source_fps+'/1').split('/').map(Number),rate=num/den;
 return part.source_start_frame/rate+Math.max(0,t-part.timeline_in_ms/1000);
}
function docClearStandby(){
 const node=docStandby();docNextToken++;docNextEvent=null;
 node.onloadedmetadata=node.onseeked=node.onloadeddata=node.onerror=null;
 node.pause();node.muted=true;node.classList.remove('is-active');node.classList.remove('is-live');node.classList.remove('doc-standby');
 node.removeAttribute('src');try{node.load()}catch{}
}
function docResetStandby(){docClearStandby();docPictureAt=null;docDirectEvent=null}
// Load and seek the upcoming cut on the standby element. Never touches audio.
function docPremoteNext(t){
 const d=window.docTimelineData;if(!d?.direct)return;
 const next=docNextAt(t);if(!next)return;
 if(docNextEvent&&docNextEvent.timeline_in_ms===next.timeline_in_ms&&docStandby().getAttribute('src'))return;
 const asset=assets().find(a=>a.id===next.asset_id);if(!asset?.url||docPhotoFrame(next))return;
 // Consecutive events in the same file are already being played through by the
 // live element. Re-loading them onto the standby would force a re-decode and
 // could drop a frame at the cut, so leave the picture where it is.
 const live=liveNode||masterNode,cur=docDirectAt(t);
 // The standby must never be the element the viewer is looking at.
 if(docStandby()===live){standbyNodeEl=(live===masterNode?nextSourceNode||sourceNode:masterNode)}
 if(cur&&cur.asset_id===next.asset_id&&live.getAttribute('src')===asset.url){
  const at=next.timeline_in_ms/1000;
  if(Math.abs(docDesiredTime(cur,at)-docDesiredTime(next,at))<.07)return;
 }
 // The standby is still playing the end of a transition; prepare it once that ends.
 if(docStandby().dataset.trBusy)return;
 const node=docStandby();docClearStandby();
 const token=docNextToken;docNextEvent=next;
 const valid=()=>token===docNextToken&&node===docStandby()&&window.docTimelineData===d;
 const seek=()=>{
  if(!valid()||node.readyState<1)return;
  const target=docDesiredTime(next,next.timeline_in_ms/1000);
  if(!Number.isFinite(target)||target<0)return;
  try{if(Math.abs(node.currentTime-target)>.01)node.currentTime=target}catch{}
 };
 node.onloadedmetadata=seek;node.onseeked=seek;node.onloadeddata=seek;
 node.onerror=()=>{if(valid())docNextEvent=null};
 node.muted=true;
 // Chrome does not decode a display:none video, so a hidden standby never reached
 // a ready frame and every cut to another file fell back to a black reload. The
 // standby is laid out under the live picture at zero opacity instead.
 node.classList.add('doc-standby');node.preload='auto';
 node.src=asset.url;try{node.load()}catch{}
}
// Swap the pre-rolled picture in. Audio is untouched; returns false when the
// prepared cut is not actually ready, so the caller can seek in place instead.
function docPromote(t){
 const next=docNextEvent;if(!next)return false;
 // Same file as the outgoing cut and already showing it: nothing to swap.
 const live=liveNode||masterNode;
 if(docPictureAt&&docPictureAt.asset_id===next.asset_id&&live.getAttribute('src')===(assets().find(a=>a.id===next.asset_id)?.url||'')){
  const at=next.timeline_in_ms/1000;
  if(Math.abs(docDesiredTime(docPictureAt,at)-docDesiredTime(next,at))<.07){docPictureAt=docDirectAt(t)||docPictureAt;docDirectEvent=docPictureAt;docNextEvent=null;return true}
 }
 const part=docDirectAt(t);
 if(!part||part.timeline_in_ms!==next.timeline_in_ms)return false;
 const node=docStandby();
 if(node.readyState<2||node.seeking)return false;
 const target=docDesiredTime(part,t);
 // Pre-rolled at the cut's first frame; only nudge it if the clock has moved on.
 try{if(Math.abs(node.currentTime-target)>DOC_DRIFT_S)node.currentTime=Math.max(0,target)}catch{return false}
 node.classList.remove('doc-standby');docWaitSince=0;imageNode.hidden=true;imageNode.classList.remove('is-cutaway');
 const old=liveNode;
 const oldVisible=old&&old!==node&&old.classList.contains('is-active');
 // A preview-only recommendation may override the look, never saved scene data.
 const tr=docTransitionAt(docPictureAt,part,editorPlaying);
 node.muted=true;node.classList.add('is-active');node.classList.add('is-live');
 if(oldVisible&&tr){old.classList.remove('is-live');docAnimateTransition(old,node,tr.key,tr.frames)}
 // Keep the outgoing picture until the incoming one is actually showing.
 else if(oldVisible){old.pause();old.muted=true;old.classList.remove('is-active');old.classList.remove('is-live')}
 liveNode=node;standbyNodeEl=(old===node?null:old);
 docPictureAt=part;docDirectEvent=part;docNextEvent=null;docNextToken++;
 if(editorPlaying)node.play().catch(()=>{});
 return true;
}
let docWaitSince=0;
// Play a cut's transition in the monitor: the same look the export blends in, drawn
// with the two picture players. The outgoing shot keeps running underneath until the
// blend ends, just as the renderer lets it run on past the cut.
const DOC_TR_ON_TOP=new Set(['circleclose','squeezeh','zoomin']);
// The suggestion is only a temporary audition; it never modifies the script,
// timeline, project or export until the user explicitly applies it.
window.docTransitionPreviewOverride=null;
window.docTransitionPreviewInfo=null;
const docTransitionLive=document.createElement('div');docTransitionLive.id='doc-transition-live';docTransitionLive.hidden=true;
$('#monitor-frame').append(docTransitionLive);
let docTransitionBadgeText='';
function docTransitionAt(previous,incoming,playing){
 if(!playing||!previous||!incoming||previous.scene_id===incoming.scene_id)return null;
 const scene=scenes().find(s=>s.id===previous.scene_id);if(!scene)return null;
 const override=window.docTransitionPreviewOverride;
 const match=override&&override.scene_id===scene.id&&Math.abs(override.at_s-incoming.timeline_in_ms/1000)<.12;
 const key=match?override.key:scene.transition||'cut';
 return key!=='cut'?{key,frames:match?override.frames:Number(scene.transition_handle_frames)||15}:null;
}
function docUpdateTransitionBadge(t){
 const info=window.docTransitionPreviewInfo,view=window.docTrState?.(),cuts=view?.cuts||[];
 let cue=info&&Math.abs(info.at_s-t)<2.5?info:null;
 if(!cue){const c=cuts.find(c=>t>=c.at_s-.12&&t<c.at_s+1.4);if(c)cue={at_s:c.at_s,kind:'Applied',label:(view.catalogue?.transitions||[]).find(x=>x.key===c.transition)?.label||c.transition}}
 const next=cue?`${cue.kind.toUpperCase()} · ${cue.label}${cue.kind==='Suggested'?' · preview only':''}`:'';
 if(next!==docTransitionBadgeText){docTransitionBadgeText=next;docTransitionLive.hidden=!next;if(next)docTransitionLive.textContent=next}
}
function docAnimateTransition(old,node,key,frames){
 const ms=Math.max(150,Math.min(2500,frames/30*1000)),o={duration:ms,easing:'ease-in-out'};
 let a=null,b=[{opacity:0},{opacity:1}];
 switch(key){
  case 'fadeblack':a=[{opacity:1},{opacity:0,offset:.5},{opacity:0}];b=[{opacity:0},{opacity:0,offset:.5},{opacity:1}];break;
  case 'fadewhite':a=[{filter:'brightness(1)'},{filter:'brightness(5)',offset:.5},{filter:'brightness(5)'}];b=[{opacity:0,filter:'brightness(5)'},{opacity:1,filter:'brightness(5)',offset:.5},{opacity:1,filter:'brightness(1)'}];break;
  case 'fadegrays':a=[{filter:'grayscale(0)'},{filter:'grayscale(1)'}];b=[{opacity:0,filter:'grayscale(1)'},{opacity:1,filter:'grayscale(0)'}];break;
  case 'hblur':a=[{filter:'blur(0px)'},{filter:'blur(14px)'}];b=[{opacity:0,filter:'blur(14px)'},{opacity:1,filter:'blur(0px)'}];break;
  case 'whip':case 'slideleft':a=[{transform:'translateX(0)'},{transform:'translateX(-100%)'}];b=[{transform:'translateX(100%)'},{transform:'translateX(0)'}];break;
  case 'slideright':a=[{transform:'translateX(0)'},{transform:'translateX(100%)'}];b=[{transform:'translateX(-100%)'},{transform:'translateX(0)'}];break;
  case 'slideup':a=[{transform:'translateY(0)'},{transform:'translateY(-100%)'}];b=[{transform:'translateY(100%)'},{transform:'translateY(0)'}];break;
  case 'smoothup':a=[{transform:'none',opacity:1},{transform:'translateY(-25%)',opacity:0}];b=[{transform:'translateY(25%)',opacity:0},{transform:'none',opacity:1}];break;
  case 'smoothleft':a=[{transform:'none',opacity:1},{transform:'translateX(-25%)',opacity:0}];b=[{transform:'translateX(25%)',opacity:0},{transform:'none',opacity:1}];break;
  case 'wipeleft':b=[{clipPath:'inset(0 0 0 100%)'},{clipPath:'inset(0 0 0 0)'}];break;
  case 'circleopen':b=[{clipPath:'circle(0% at 50% 50%)'},{clipPath:'circle(75% at 50% 50%)'}];break;
  case 'horzopen':b=[{clipPath:'inset(0 50% 0 50%)'},{clipPath:'inset(0 0 0 0)'}];break;
  case 'diagtl':b=[{clipPath:'polygon(0 0,0 0,0 0)'},{clipPath:'polygon(0 0,200% 0,0 200%)'}];break;
  case 'distance':b=[{transform:'scale(.6)',opacity:0},{transform:'scale(1)',opacity:1}];break;
  case 'circleclose':a=[{clipPath:'circle(75% at 50% 50%)'},{clipPath:'circle(0% at 50% 50%)'}];b=[{opacity:1},{opacity:1}];break;
  case 'squeezeh':a=[{transform:'scaleX(1)'},{transform:'scaleX(0)'}];b=[{opacity:1},{opacity:1}];break;
  case 'zoomin':a=[{transform:'scale(1)',opacity:1},{transform:'scale(1.8)',opacity:0}];b=[{opacity:1},{opacity:1}];break;
  case 'pixelize':a=[{filter:'blur(0px)'},{filter:'blur(8px)'}];b=[{opacity:0,filter:'blur(8px)'},{opacity:1,filter:'blur(0px)'}];break;
 }
 if(DOC_TR_ON_TOP.has(key))old.style.zIndex='4';
 old.dataset.trBusy='1';
 const runs=[];try{if(a)runs.push(old.animate(a,o));runs.push(node.animate(b,o))}catch{}
 const done=()=>{old.style.zIndex='';delete old.dataset.trBusy;try{runs.forEach(r=>r.cancel())}catch{}
  if(old!==liveNode){old.pause();old.muted=true;old.classList.remove('is-active');old.classList.remove('is-live')}};
 setTimeout(done,ms+30);
}
// Load a cut into the standby and swap it in only once its frame is showing, so the
// outgoing picture stays on screen while the new file loads. Never shows black.
async function docSwapInto(part,asset,t,playing,d){
 const old=liveNode||masterNode,oldPart=docPictureAt;
 if(docStandby()===old)standbyNodeEl=(old===masterNode?nextSourceNode||sourceNode:masterNode);
 const node=docStandby();docClearStandby();
 const token=++docDirectToken;docDirectBusy=true;docDirectEvent=part;docPictureAt=part;
 try{
  // Mark the player as busy so the next-shot preparation cannot take it over and
  // wipe this file half-way through loading.
  node.dataset.trBusy='swap';
  node.muted=true;node.classList.add('doc-standby');node.preload='auto';node.src=asset.url;try{node.load()}catch{}
  if(node.readyState<1)await new Promise(r=>{const x=setTimeout(r,6000);node.addEventListener('loadedmetadata',()=>{clearTimeout(x);r()},{once:true});node.addEventListener('error',()=>{clearTimeout(x);r()},{once:true})});
  if(token!==docDirectToken||window.docTimelineData!==d)return;
  const target=docDesiredTime(part,playing&&editorPlaying?(narrNode.currentTime||t):t);
  await new Promise(r=>{const x=setTimeout(r,6000);const done=()=>{clearTimeout(x);r()};node.addEventListener('seeked',done,{once:true});try{node.currentTime=Math.max(0,target)}catch{done()}});
  if(node.readyState<2)await new Promise(r=>{const x=setTimeout(r,3000);node.addEventListener('loadeddata',()=>{clearTimeout(x);r()},{once:true})});
  if(token!==docDirectToken||window.docTimelineData!==d)return;
  node.classList.remove('doc-standby');node.classList.add('is-active');node.classList.add('is-live');imageNode.hidden=true;imageNode.classList.remove('is-cutaway');
  const tr=docTransitionAt(oldPart,part,playing&&editorPlaying);
  if(old&&old!==node&&old.classList.contains('is-active')&&tr){docAnimateTransition(old,node,tr.key,tr.frames)}
  else if(old&&old!==node){old.pause();old.muted=true;old.classList.remove('is-active');old.classList.remove('is-live')}
  liveNode=node;standbyNodeEl=(old===node?null:old);
  if(playing&&editorPlaying)await node.play().catch(()=>{});
 }finally{if(node.dataset.trBusy==='swap')delete node.dataset.trBusy;if(token===docDirectToken)docDirectBusy=false}
}
async function docDirectSwitch(t,playing,force){
 const d=window.docTimelineData,part=docDirectAt(t);if(!d?.direct||!part)return;
 const asset=assets().find(a=>a.id===part.asset_id);if(!asset?.url){pauseEditor();toast('Playback stopped: source footage is missing.');return}
 const photoFrame=docPhotoFrame(part);
 if(photoFrame){
  docNextEvent=null;docNextToken++;docDirectEvent=part;docPictureAt=part;
  const node=liveNode||masterNode;try{node.pause()}catch{}
  imageNode.src=photoFrame;imageNode.classList.add('is-cutaway');imageNode.hidden=false;$('#monitor-empty').hidden=true;
  return;
 }
 if(!force&&docPromote(t)){imageNode.hidden=true;imageNode.classList.remove('is-cutaway');return;}/* Arriving from a seek: any pre-rolled cut was for the old position. */if(force){docNextEvent=null;docNextToken++}
 // The pre-rolled cut is still loading: keep the outgoing picture up for a moment
 // rather than blanking the monitor; the next tick promotes it as soon as it is ready.
 if(!force&&playing&&docNextEvent&&docNextEvent.timeline_in_ms===part.timeline_in_ms&&docStandby().getAttribute('src')){
  if(!docWaitSince)docWaitSince=performance.now();
  if(performance.now()-docWaitSince<1500)return;
 }
 docWaitSince=0;
 const node=liveNode||masterNode;
 const desired=docDesiredTime(part,t);const different=node.getAttribute('src')!==asset.url;
 // A different file while a picture is showing goes through the standby.
 if(different&&node.getAttribute('src')&&node.classList.contains('is-active')){await docSwapInto(part,asset,t,playing,d);return}
 const needsSeek=different||Math.abs(node.currentTime-desired)>DOC_DRIFT_S;
 docDirectEvent=part;docPictureAt=part;
 // A refused picture play() (autoplay, decode pressure) must not stop the
 // narration clock; the next tick retries the picture.
 if(!needsSeek){imageNode.hidden=true;imageNode.classList.remove('is-cutaway');if(playing&&editorPlaying){try{node.muted=true;node.classList.add('is-active');await node.play()}catch{node.classList.remove('is-active')}}return}
 const token=++docDirectToken;docDirectBusy=true;
 // While the clock runs, chase the live position rather than a stale target.
 const live=!!editorPlaying&&playing;
 try{
  if(different){node.muted=true;node.src=asset.url;node.load()}
  // Waiting on metadata or a seek must never stop the clock. If the browser is
  // slow the picture catches up on a later tick; the audio keeps playing.
  if(node.readyState<1)await new Promise(resolve=>{const timer=setTimeout(resolve,6000);node.addEventListener('loadedmetadata',()=>{clearTimeout(timer);resolve()},{once:true});node.addEventListener('error',()=>{clearTimeout(timer);resolve()},{once:true})});
  if(token!==docDirectToken||window.docTimelineData!==d)return;
  const target=live?docDesiredTime(part,narrNode.currentTime||t):desired;
  if(Math.abs(node.currentTime-target)>.005){await new Promise(resolve=>{const timer=setTimeout(resolve,6000);node.addEventListener('seeked',()=>{clearTimeout(timer);resolve()},{once:true});try{node.currentTime=Math.max(0,target)}catch{clearTimeout(timer);resolve()}})}
  if(token!==docDirectToken||window.docTimelineData!==d)return;
  node.classList.add('is-active');node.classList.add('is-live');imageNode.hidden=true;imageNode.classList.remove('is-cutaway');
  if(playing&&editorPlaying){node.muted=true;await node.play().catch(()=>{})}
 }catch(e){
  // A picture problem is reported once; it never halts narration or the clock.
  if(token===docDirectToken){node.classList.remove('is-active');toast('Picture skipped a frame: '+e.message)}
 }finally{if(token===docDirectToken)docDirectBusy=false}
}
let docSegmentCache=-1,docSegmentRows=null;
function docSegmentAt(t){
 const rows=window.docTimelineData?.segments||[];if(rows!==docSegmentRows){docSegmentCache=-1;docSegmentRows=rows}
 const p=rows[docSegmentCache];if(p&&t>=p.timeline_in_s-.00001&&t<p.timeline_out_s-.00001)return p;
 let lo=0,hi=rows.length;
 while(lo<hi){const mid=(lo+hi)>>1;if(rows[mid].timeline_in_s<=t+.00001)lo=mid+1;else hi=mid}
 const i=lo-1,seg=rows[i];docSegmentCache=seg&&t<seg.timeline_out_s-.00001?i:-1;
 return docSegmentCache>=0?rows[docSegmentCache]:rows.at(-1);
}
function docBaseAt(t){const seg=docSegmentAt(t);if(!seg)return 0;return seg.kind==='sound_bite'?seg.narration_resume_s:Math.min(seg.source_out_s,seg.source_in_s+Math.max(0,t-seg.timeline_in_s))}
function docSelectAt(i,t,event){if(!leave())return;/* docSeekTimeline keeps playing if it was */if(event&&(event.ctrlKey||event.metaKey)){const id=scenes()[i].id;if(selectedSlotIds.has(id))selectedSlotIds.delete(id);else selectedSlotIds.add(id)}else selectedSlotIds=new Set([scenes()[i].id]);sceneIndex=i;docSeekTimeline(t,false);renderInspector(true);markSelected();syncPictureScale()}
function docSelectScene(i,event){const s=scenes()[i],span=s&&docPictureSpans(s.frame_in/30,s.frame_out/30)[0];if(span)docSelectAt(i,span.start,event)}
// Dragging the playhead: show the picture as fast as the files allow, never queue up
// work. The visible player is nudged when it already holds the right file; another
// file is loaded only when no load is in flight, and that load is allowed to finish.
function docScrubTo(t){
 const d=window.docTimelineData;t=Math.max(0,Math.min(d.duration-.001,t));
 if(editorPlaying)pauseEditor();
 try{narrNode.currentTime=Math.min(t,narrNode.duration||t)}catch{}
 movePlayhead(t*timelineZoom);setTimecode(fmt(t),fmt(d.duration||0));
 if(d.status!=='ready'||!d.direct)return;
 const part=docDirectAt(t);if(!part)return;
 const asset=assets().find(a=>a.id===part.asset_id);if(!asset?.url)return;
 const photoFrame=docPhotoFrame(part);
 if(photoFrame){imageNode.src=photoFrame;imageNode.hidden=false;imageNode.classList.add('is-cutaway');docPictureAt=part;return}
 imageNode.hidden=true;imageNode.classList.remove('is-cutaway');
 const node=liveNode||masterNode,want=Math.max(0,docDesiredTime(part,t));
 if(node.getAttribute('src')===asset.url){
  docPictureAt=part;
  if(node.seeking){node._scrubTo=want;return}
  try{if(typeof node.fastSeek==='function'&&Math.abs(node.currentTime-want)>1)node.fastSeek(want);else node.currentTime=want}catch{}
  if(!node._scrubHook){node._scrubHook=true;node.addEventListener('seeked',()=>{const x=node._scrubTo;if(x!=null){node._scrubTo=null;try{node.currentTime=x}catch{}}})}
  return;
 }
 if(!docDirectBusy)docDirectSwitch(t,false,true);
}
window.docScrubTo=docScrubTo;
function docSeekTimeline(t,select=true){const d=window.docTimelineData;if(!d?.duration)return;
 if(playheadDrag&&d.status==='ready'&&d.direct){docScrubTo(t);return}
 if(select&&!leave())return;const was=editorPlaying;pauseEditor();t=Math.max(0,Math.min(d.duration-.001,t));
 // While a drag is in flight, only move the picture and the playhead. The
 // inspector and the scene selection settle once the pointer is released.
 const scrubbing=!!playheadDrag;if(d.status==='ready'){try{if(d.direct){docResetStandby();liveNode=masterNode;narrNode.currentTime=Math.min(t,narrNode.duration||t);docSyncMusic(t,false);masterNode.pause();docStandby().pause();docStandby().classList.remove('is-active');docDirectSwitch(t,false,true)}else masterNode.currentTime=t}catch{}}if(select&&!scrubbing){const base=docBaseAt(t),i=scenes().findIndex(s=>base>=s.frame_in/30&&base<s.frame_out/30);if(i>=0&&i!==sceneIndex){sceneIndex=i;renderInspector();markSelected()}}docUpdatePosition();if(was&&!scrubbing)docPlayTimeline()}
async function docPlayTimeline(){const token=++docPlayGeneration,d=window.docTimelineData;if(d?.status!=='ready'||!d.url){toast(['queued','running','idle','stale'].includes(d?.status)?'The preview is still being prepared. It plays here as soon as it is ready.':'Prepare the documentary timeline preview first.');return}try{const state=await api(`/api/projects/${d.id}/`+(d.direct?'documentary-audio':'documentary-review-preview'));if(token!==docPlayGeneration||window.docTimelineData!==d)return;if((d.direct?state.status!=='done':state.status!=='ready')||state.url!==d.url){toast('The timeline changed. Prepare the preview again.');reloadDocTimeline();return}}catch(e){toast('Cannot verify the timeline preview: '+e.message);return}if(dirty){toast('Save or discard scene edits before playing.');return}if(d.direct){if(narrNode.currentTime>=d.duration-.05)narrNode.currentTime=0;editorPlaying=true;updatePlaybackButton();docDirectEvent=null;docPictureAt=null;docResetStandby();masterNode.muted=true;narrNode.muted=editorMuted;try{await narrNode.play()}catch(e){pauseEditor();toast('Playback could not start: '+e.message);return}/* the picture follows the clock */docDirectSwitch(narrNode.currentTime,true,true);if(editorPlaying){docPremoteNext(narrNode.currentTime||0);docSyncMusic(narrNode.currentTime||0,true)}return}if(masterNode.currentTime>=d.duration-.01)masterNode.currentTime=0;editorPlaying=true;updatePlaybackButton();try{masterNode.muted=editorMuted;await masterNode.play()}catch(e){pauseEditor();toast('Timeline playback could not start: '+e.message)}}
// The Scale slider crops or enlarges the picture in the monitor. It must survive
// the per-frame position repaint, which used to reset the layer to scale(1).
// A live slider drag (slotScalePreview) wins over the saved slot scale so the
// change is visible immediately, before the PATCH has been confirmed.
function docApplyPictureScale(){
 const d=window.docTimelineData;
 if(!d||d.status!=='ready'){$('#picture-layer').style.transform='scale(1)';return}
 const t=d.direct?(narrNode.currentTime||0):(masterNode.currentTime||0);
 // In beat playback the schedule says which slot is actually on screen; a
 // sound-bite event has no slot, so fall back to the selected shot.
 const event=d.direct?docDirectAt(t):null;
 const all=(typeof scenes==='function'?scenes():[]);
 // docPictureAt is the slot last put on screen; during a sound bite it is still
 // the picture behind the bite, so the bite never resets the crop.
 const onScreen=d.direct?(docPictureAt||event):event;
 const scene=onScreen?.scene_id?(all.find(s=>s.id===onScreen.scene_id)||all[sceneIndex])
  :(all.find(s=>s.frame_in/30<=t&&t<s.frame_out/30)||all[sceneIndex]);
 if(!scene){$('#picture-layer').style.transform='scale(1)';return}
 // Use one continuous camera only for automatically directed still-image slots.
 // Videos retain original composition; narration and source ranges are untouched.
 const saved=Number(scene.picture_scale??P?.picture_scale??100)||100;
 const live=(typeof slotScalePreview!=='undefined'&&slotScalePreview&&slotScalePreview.ids.has(scene.id))?Number(slotScalePreview.value):saved;
 const pct=Math.max(100,Math.min(200,Number.isFinite(live)?live:saved));
 const layer=$('#picture-layer');
 // Only touch the DOM when it actually changed; this runs every frame.
 const cam=(P?.person_overlays?.settings?.smart_photo_mode===true && scene.camera?.reason?.startsWith('Smart still:'))?scene.camera:null;
 const prog=window.Cinematic&&cam?Cinematic.slotProgress(scene.frame_in/30*1000,scene.frame_out/30*1000,t,30):0;
 const next=cam&&window.Cinematic?Cinematic.camTransform(cam,prog):`scale(${(pct/100).toFixed(4)})`;
 if(layer.style.transform!==next)layer.style.transform=next;
}
window.docApplyPictureScale=docApplyPictureScale;
function docUpdatePosition(){const d=window.docTimelineData,t=d?.status==='ready'?(d.direct?narrNode.currentTime||0:masterNode.currentTime||0):0,base=docBaseAt(t),seg=docSegmentAt(t);docApplyPictureScale();setTimecode(fmt(t),fmt(d?.duration||0));movePlayhead(t*timelineZoom);setPlayheadAria(t,d?.duration||0);// The monitor's CC preview is independent of permanent MP4 subtitle burn-in.
 // The editor never forces subtitle export merely because CC preview is on; the text
 // is still available in the Shot inspector and the Documentary panel.
 const captionOn=!!editorCC;
 // A sound bite and ordinary footage never carry on-screen text, whatever the
 // script's On-screen caption line says: only a narration beat can show one.
 // The caption and the kind must come from the SAME source. Reading the caption
 // from the schedule while asking the planning clock whether this is a bite let a
 // bite's caption paint over its own footage whenever the two clocks drifted.
 const scheduled=d?.direct?docDirectAt(t):null;
 const shownKind=scheduled?.kind||seg?.kind;
 const narrationBeat=shownKind==='narration'||shownKind==='picture_tail';
 const captions=P?.caption_phrases||[],cueIndex=captionOn&&narrationBeat?findActiveIntervalIndex(captions,base*1000,'start_ms','end_ms'):-1;
 const cue=cueIndex>=0?captions[cueIndex]:null;{const ov=$('#editor-captions'),off=!editorCC||!cue;if(ov.classList.contains('captions-off')!==off)ov.classList.toggle('captions-off',off);if(ov.style.opacity!=='1')ov.style.opacity='1'}fitSrtCaption(cue,base);if(typeof updatePersonOverlay==='function')updatePersonOverlay(t)}
function docTick(){
 const d=window.docTimelineData;if(!editorPlaying||d?.status!=='ready')return;
 const t=d.direct?narrNode.currentTime||0:masterNode.currentTime||0;
 if(t>=d.duration-.005||(d.direct&&narrNode.ended)){pauseEditor();return}
 if(d.direct){
  const part=docDirectAt(t);
  if(part){
   // Pre-roll the next event well before its cut so the swap is a no-op.
   const next=docNextAt(t);
   if(next&&(next.timeline_in_ms/1000-t)<=DOC_PREROLL_S)docPremoteNext(t);
   if(part!==docPictureAt){
    // Use the pre-rolled picture if it is ready; otherwise seek in place,
    // which never stops the audio clock.
    if(!docPromote(t)&&!docDirectBusy)docDirectSwitch(t,true);
   }else if(!docDirectBusy){
    const node=liveNode||masterNode;
    if(docPhotoFrame(part)){imageNode.hidden=false}
    else {const wantUrl=assets().find(a=>a.id===part.asset_id)?.url||'';
    // The right second of the WRONG file looks plausible and is worse than a late
    // picture: if the player on screen holds another file, load the right one.
    if(wantUrl&&node.getAttribute('src')!==wantUrl){docDirectSwitch(t,true,true)}
    // Picture lagging the clock is corrected by seeking, not by pausing.
    else if(node.readyState>=2&&!node.seeking){
     const want=docDesiredTime(part,t);
     if(Math.abs(node.currentTime-want)>DOC_DRIFT_S*2.5){
      try{node.currentTime=Math.max(0,want)}catch{}
     }
    }
    }
   }
  }
 }
 docSyncMusic(t,true);
 docUpdateTransitionBadge(t);
 const base=docScenesOnMaster()?t:docBaseAt(t),i=findActiveIntervalIndex(scenes(),Math.floor(base*30),'frame_in','frame_out');
 if(i>=0&&i!==sceneIndex){sceneIndex=i;renderInspector();markSelected()}
}
function docUpdateMuteControls(){
 const audio=$('#mute-audio'),video=$('#mute-mp4'),music=$('#music-volume');
 if(audio){audio.textContent=editorMuted?'Muted':'On';audio.setAttribute('aria-pressed',String(editorMuted));audio.setAttribute('aria-label',(editorMuted?'Unmute':'Mute')+' documentary narration and bite audio');audio.title='Mutes narration and footage speech in preview'}
 if(video){video.textContent='Muted';video.setAttribute('aria-pressed','true');video.setAttribute('aria-label','Ordinary footage is muted');video.title='Ordinary footage is muted; chosen sound-bite audio is in the audio track'}
 if(music)music.textContent=docMusic.enabled?String(docTrackVolume.music):'Off';
 window.docApplyPreviewVolumes();
}
window.docStepVolume=async function(track,delta){
 const step=Number(delta)||0;
 if(track==='music'){
  if(!docMusic.file_present){toast('Add background music first.');return}
  const value=Math.max(1,Math.min(100,(docTrackVolume.music||35)+step));
  if(value===docTrackVolume.music)return;
  if(!P)return;
  // Apply at once, then save quietly. Asking for a fresh timeline here is what
  // made a volume tap feel like a restart.
  const previous=docTrackVolume.music;
  docTrackVolume.music=value;
  const readout=$('#music-volume');if(readout)readout.textContent=docMusic.enabled?String(value):'Off';
  window.docApplyPreviewVolumes();
  const id=P.id;
  try{const saved=await api(`/api/projects/${id}/documentary-music`,'PATCH',{volume_percent:value});
   if(P?.id!==id)return;
   applyProjectMusic(saved);
   window.docApplyPreviewVolumes();
  }catch(e){if(P?.id!==id)return;docTrackVolume.music=previous;if(readout)readout.textContent=docMusic.enabled?String(previous):'Off';window.docApplyPreviewVolumes();toast(e.message)}
  return;
 }
};
async function docPrepareTimeline(){const d=window.docTimelineData;if(!d||d.loading)return;
 // In documentary Beat mode, Rebuild Timeline MUST regenerate the actual scene
 // and soundbite plan, not merely refresh an old audio-only preview.
 if(P?.edit_mode==='documentary'&&P?.production_script&&P?.srt&&P?.voiceover&&P?.documentary_beat_review)return openBeatProposal();
 if(d.status==='ready'&&d.url){toast('The prepared preview is already current.');return}if(['queued','running'].includes(d.status))return;if(d.direct){try{const st=await api(`/api/projects/${d.id}/documentary-audio`);if(st.status==='done'&&st.url){await reloadDocTimeline();if(window.docTimelineData?.status==='ready')return}}catch{}try{await api(`/api/projects/${d.id}/documentary-audio`,'POST');reloadDocTimeline()}catch(e){toast(e.message)}return}let allow=false;if(d.tail>.001){allow=confirm(`The base picture is ${d.tail.toFixed(3)} seconds longer than narration. Keep that existing picture with silence at the end of this review preview?`);if(!allow)return}try{await api(`/api/projects/${d.id}/documentary-review-preview`,'POST',{allow_silent_tail:allow});reloadDocTimeline()}catch(e){toast(e.message)}}
function docStartBiteDrag(event){
 if(event.button!==0||!leave())return;event.preventDefault();event.stopPropagation();const d=window.docTimelineData,element=event.currentTarget,bite=d?.bites.find(x=>x.id===element.dataset.bite),segment=d?.segments.find(x=>x.kind==='sound_bite'&&x.id===bite?.id);if(!bite||!segment)return;if(bite.stale_reasons?.length){toast('Review the stale sound bite before moving it.');return}pauseEditor();element.setPointerCapture(event.pointerId);const startX=event.clientX,initialLeft=segment.timeline_in_s*timelineZoom;let x=initialLeft,moved=false;
 const move=e=>{x=Math.max(0,Math.min(d.duration*timelineZoom,initialLeft+e.clientX-startX));if(Math.abs(e.clientX-startX)>4)moved=true;element.style.left=x+'px'};
 const finish=async e=>{element.removeEventListener('pointermove',move);element.removeEventListener('pointerup',finish);element.removeEventListener('pointercancel',cancel);if(!moved){element.style.left=initialLeft+'px';docSeekTimeline(segment.timeline_in_s,false);return}const pause=Math.min(P.voiceover.duration,Math.max(0,Math.round(docBaseAt(x/timelineZoom+(x>initialLeft?(segment.timeline_out_s-segment.timeline_in_s):0))*30)/30));try{await api(`/api/projects/${d.id}/documentary-bites/${bite.id}`,'PATCH',{revision:d.revision,pause_s:pause});toast('Sound bite moved. The preview is updating by itself.');reloadDocTimeline()}catch(err){element.style.left=initialLeft+'px';toast(err.message)}};
 const cancel=()=>{element.removeEventListener('pointermove',move);element.removeEventListener('pointerup',finish);element.removeEventListener('pointercancel',cancel);element.style.left=initialLeft+'px'};element.addEventListener('pointermove',move);element.addEventListener('pointerup',finish);element.addEventListener('pointercancel',cancel);
}

setInterval(async()=>{const d=window.docTimelineData;if(!d||d.status!=='ready'||P?.id!==d.id||document.hidden)return;try{const state=await api(`/api/projects/${d.id}/`+(d.direct?'documentary-audio':'documentary-review-preview'));if(window.docTimelineData===d&&((d.direct?state.status!=='done':state.status!=='ready')||state.url!==d.url)){pauseEditor();reloadDocTimeline()}}catch{if(window.docTimelineData===d){d.verifyFailures=(d.verifyFailures||0)+1;if(d.verifyFailures>=3){pauseEditor();d.status='error';d.detail='Could not verify the timeline preview; playback stopped.';renderProject()}}}},15000);

/* Background music: optional bed under the narration only, silent through sound bites. */
let musicReadSequence=0;
function applyProjectMusic(state){
 musicReadSequence++;
 docMusic=state||{};
 window.docMusicCard=docMusic;
 docTrackVolume.music=Number.isFinite(docMusic.volume_percent)?docMusic.volume_percent:35;
 if(Number.isFinite(docMusic.narration_percent))docTrackVolume.narration=docMusic.narration_percent;
 if(Number.isFinite(docMusic.clip_percent))docTrackVolume.clip=docMusic.clip_percent;
 docRenderMusicTrack();
 renderMediaPool();
 window.docUpdateMuteControls?.();
 docSyncMusic(narrNode.currentTime||0,editorPlaying);
}
window.docLoadMusic=async function(){
 if(P?.edit_mode!=='documentary')return;
 const id=P.id, sequence=++musicReadSequence;
 try{
  const state=await api(`/api/projects/${id}/documentary-music`);
  if(P?.id===id&&sequence===musicReadSequence)applyProjectMusic(state);
 }catch(e){if(P?.id===id&&sequence===musicReadSequence)applyProjectMusic({})}
};
// The bed is silent through every sound bite, so the strip shows a gap at each one:
// what is drawn is what will be heard. Back-to-back bites make one gap.
function docMusicCuts(duration){
 const total=Math.max(0,duration||0),cuts=[];
 for(const s of (window.docTimelineData?.segments||[])){if(s.kind!=='sound_bite')continue;
  const a=Math.max(0,s.timeline_in_s),b=Math.min(total,s.timeline_out_s);if(b<=a)continue;
  const last=cuts.at(-1);if(last&&a-last.end<.05)last.end=Math.max(last.end,b);else cuts.push({start:a,end:b})}
 return cuts;
}
function docMusicSpans(duration){
 const total=Math.max(0,duration||0);if(!total)return [];
 const spans=[];let at=0;
 for(const c of docMusicCuts(total)){if(c.start-at>.001)spans.push({start:at,end:c.start});at=c.end}
 if(total-at>.001)spans.push({start:at,end:total});
 return spans;
}
window.docMusicSpans=docMusicSpans;
function docRenderMusicTrack(){
 const track=$('#music-track'),label=$('#music-track-label'),clip=$('#music-track-clip');
 if(!track||!label||!clip)return;
 const documentary=P?.edit_mode==='documentary';
 // An empty bed draws NOTHING: no bar, no amber strip, no prompt text. A music track
 // that has never been given a file is not a thing on the timeline, and a full-width
 // placeholder read as though a clip had already been placed there. The row itself
 // stays mounted (so its height stays measurable) but collapses to nothing until a
 // file exists, which also gives the other tracks that space back.
 const hasMusic=documentary&&!!docMusic.file_present;
 const deleteButton=$('#music-track-delete');
 if(deleteButton)deleteButton.hidden=!hasMusic;
 // The ROW is always there in a documentary -- it is part of the track stack, and a
 // row that appears and disappears shifts every other track under the pointer. What
 // stays hidden until a file exists is the clip inside it: an empty track shows its
 // label and nothing else, exactly as CapCut leaves an unused audio row.
 track.style.display=documentary?'block':'none';
 label.style.display=documentary?'flex':'none';
 if(!documentary)return;
 if(!hasMusic){
  clip.innerHTML='';clip.onclick=null;
  clip.style.width='0px';clip.style.left='0px';
  const readout0=$('#music-volume');if(readout0)readout0.textContent='Off';
  return;
 }
 const duration=window.docTimelineData?.duration||0;
 // With no timeline loaded yet there is no film to draw a bed across. Drawing a
 // 3px placeholder here is what left a brown sliver sitting in an empty track; the
 // track itself stays mounted and visible, it simply holds no picture of a clip.
 if(!duration){
  clip.innerHTML='';clip.onclick=null;clip.style.left='0px';clip.style.width='0px';
  clip.style.background='transparent';clip.style.borderColor='transparent';
  const r=$('#music-volume');if(r)r.textContent=docMusic.enabled?String(docTrackVolume.music):'Off';
  return;
 }
 const spans=docMusicSpans(duration);
 const zoom=timelineZoom;
 // One piece per stretch of narration; the gaps are the sound bites.
 clip.style.left='0px';clip.style.width=Math.max(3,duration*zoom-1)+'px';
 // The strip itself is only the scaled background; the piece carries the audio.
 clip.style.background='transparent';clip.style.borderColor='transparent';
 clip.className='audio-clip doc-music doc-music-strip';
 clip.onclick=()=>docPickMusic();
 
 clip.innerHTML=spans.map((sp,k)=>`<div class="doc-music-piece" style="left:${sp.start*zoom}px;width:${Math.max(3,(sp.end-sp.start)*zoom-1)}px" title="${E(docMusic.name||'Background music')} · ${docTime(sp.start)}–${docTime(sp.end)}"><canvas class="audio-waveform doc-music-wave" aria-hidden="true"></canvas><div class="audio-label"><strong>♪ ${E(docMusic.name||'Background music')}${docMusic.enabled?'':' · off'}</strong>${docMusic.enabled?'':'<span>off</span>'}</div></div>`).join('');
 requestAnimationFrame(()=>{
  document.querySelectorAll('#music-track .doc-music-wave').forEach(drawDocMusicWaveform);
  window.docPaintPlayhead?.();
 });
 const readout=$('#music-volume');if(readout)readout.textContent=docMusic.enabled?String(docTrackVolume.music):'Off';
}
let docMusicPeaks=null,docMusicPeaksKey='';
async function drawDocMusicWaveform(canvas){
 if(!canvas||!docMusic.file_present||!docMusic.url)return;
 const key=docMusic.url+'|'+(docMusic.duration_s||'');
 if(docMusicPeaksKey!==key){
  try{
   const response=await fetch(docMusic.url);if(!response.ok)throw Error('Music file could not be read.');
   const buffer=await response.arrayBuffer();
   const ctx=new (window.AudioContext||window.webkitAudioContext)();
   const audio=await ctx.decodeAudioData(buffer);
   const channels=[audio.getChannelData(0)];if(audio.numberOfChannels>1)channels.push(audio.getChannelData(1));
   const bins=Math.min(60000,Math.max(1,Math.ceil(audio.duration*120))),peaks=new Float32Array(bins);
   for(let b=0;b<bins;b++){const start=Math.floor(b*audio.length/bins),end=Math.floor((b+1)*audio.length/bins);let peak=0;for(let i=start;i<end;i++)for(const channel of channels)peak=Math.max(peak,Math.abs(channel[i]));peaks[b]=peak}
   docMusicPeaks={peaks,duration:audio.duration};docMusicPeaksKey=key;ctx.close().catch(()=>{});
  }catch{
   canvas.title='Waveform unavailable for this file. The music itself still plays.';
   return;
  }
 }
 paintDocMusicWaveform(canvas);
}
function paintDocMusicWaveform(canvas){
 if(!canvas||!docMusicPeaks)return;
 const {peaks,duration}=docMusicPeaks,width=Math.max(1,Math.min(8192,Math.ceil(canvas.clientWidth))),height=40;
 canvas.width=width;canvas.height=height;const ctx=canvas.getContext('2d');ctx.clearRect(0,0,width,height);
 ctx.fillStyle=docMusic.enabled?'rgba(255, 226, 173, .8)':'rgba(255, 226, 173, .3)';
 // The bed loops to the timeline length, so repeat the file's own waveform.
 for(let x=0;x<width;x++){
  const t=(x/width)*(window.docTimelineData?.duration||duration);
  const a=Math.floor(((t%duration)/duration)*peaks.length),b=Math.max(a+1,Math.floor((((t%duration)+0.02)/duration)*peaks.length));
  let peak=0;for(let i=a;i<b&&i<peaks.length;i++)peak=Math.max(peak,peaks[i]);
  if(peak>0){const bar=Math.max(1,peak*(height-6));ctx.fillRect(x,(height-bar)/2,1,bar)}
 }
}
window.docPickMusic=function(){
 const id=P?.id;if(!id)return;
 const input=document.createElement('input');input.type='file';input.accept='audio/*,.mp3,.wav,.m4a,.aac,.flac,.ogg,.opus';
 input.onchange=async()=>{const file=input.files?.[0];if(!file||P?.id!==id)return;
  const form=new FormData();form.append('music',file);
  try{const response=await fetch(`/api/projects/${id}/documentary-music`,{method:'POST',body:form});
  // Read the body defensively: a non-JSON reply (a proxy error page, a dropped
  // upload) must not be reported as an unreadable server.
  let data={};try{data=await response.json()}catch{data={}}
  if(!response.ok)throw Error(data.error||`Music could not be saved (${response.status}).`);
  // The upload replaces whatever was saved. Refresh every place that shows the
  // file, or a previous name keeps sitting in Setup after the swap.
  if(P?.id!==id)return;
  applyProjectMusic(data);
  toast(`${data.name||'Music'} saved to this project.`);
  if($('#manage-dialog')?.open)renderManagement();
  }catch(e){if(P?.id===id)toast(e.message)}};
 input.click();
};
window.docToggleMusic=async function(){
 const id=P?.id;if(!id)return;
 if(!docMusic.file_present){await window.docPickMusic();return}
 try{
  const saved=await api(`/api/projects/${id}/documentary-music`,'PATCH',{enabled:!docMusic.enabled});
  if(P?.id!==id)return;
  applyProjectMusic(saved);
  if($('#manage-dialog')?.open)renderManagement();
 }catch(e){if(P?.id===id)toast(e.message)}
};
window.docRemoveMusic=async function(){
 const id=P?.id;
 if(!id||!docMusic.file_present||!confirm('Remove the background music from this project?'))return;
 try{
  const saved=await api(`/api/projects/${id}/documentary-music`,'PATCH',{remove:true});
  if(P?.id!==id)return;
  applyProjectMusic(saved);
  if($('#manage-dialog')?.open)renderManagement();
  toast('Background music removed from this project.');
 }catch(e){if(P?.id===id)toast(e.message)}
};
// Music is a separate, live layer. The delivered mix carries narration and the
// chosen bites; music is played alongside it so level changes take effect at
// once instead of invalidating an eight-minute render.
let docMusicNode=null,docMusicSrc='';
async function docMusicUrl(){
 const id=P?.id;
 await window.docLoadMusic();
 return P?.id===id&&docMusic.enabled&&docMusic.file_present?docMusic.url:'';
}
function docMusicElement(){
 if(!docMusicNode){
  docMusicNode=document.createElement('audio');
  docMusicNode.id='doc-music-layer';docMusicNode.preload='auto';docMusicNode.loop=true;
  document.body.append(docMusicNode);
 }
 return docMusicNode;
}

// The bed's own loudness is measured once on upload, so the preview can apply
// the same gain the exporter applies: a quiet track is lifted, a loud one is
// pulled down, and 35% means the same thing in the preview and in the file.
function docMusicGain(){
 if(!docMusic||!docMusic.enabled)return 0;
 const pct=Math.max(0,Math.min(100,Number(docTrackVolume.music)||0));
 const measured=Number(docMusic.loudness_lufs);
 if(!Number.isFinite(measured)||measured<=-70)return pct/100;
 // Same curve as `target_lufs` in documentary_music.py: the percentage already
 // picks the bed loudness, so it must not be applied a second time as a volume.
 const target=Math.max(-42,Math.min(-18,-42+pct*0.18));
 return Math.min(1,Math.pow(10,(target-measured)/20));
}
// Keep the music bed locked to the narration clock and follow the saved level.
// Background music belongs to the narration: it dips under the narrator's voice and
// is silent through every sound bite, fading out into the bite and back in after it.
// Same rule and fade lengths as the exported mix (documentary_music.build_bed).
const DOC_MUSIC_DUCK=Math.pow(10,-11/20),DOC_MUSIC_FADE_OUT=.35,DOC_MUSIC_FADE_IN=.6;
function docMusicShapeAt(t){
 const d=window.docTimelineData;if(!d?.segments?.length)return 1;
 let g=1;
 for(const s of d.segments){if(s.kind!=='sound_bite')continue;
  const a=s.timeline_in_s,b=s.timeline_out_s;
  g*=Math.max(0,Math.min(1,Math.max((a-t)/DOC_MUSIC_FADE_OUT,(t-b)/DOC_MUSIC_FADE_IN)));}
 // n: 1 inside narration, easing to 0 over 0.4 s outside it (as the export does).
 let n=0;for(const s of d.segments){if(s.kind!=='narration')continue;n+=Math.max(0,Math.min(1,Math.min((t-s.timeline_in_s)/.4+1,(s.timeline_out_s-t)/.4+1)))}
 return g*(1-(1-DOC_MUSIC_DUCK)*Math.min(1,n));
}
function docSyncMusic(t,playing){
 // The timeline payload carries no music field, so this used to read an undefined
 // `music_url` and bail out on the line below: the bed was created, then silently
 // paused forever. The URL comes from the music settings instead, which already
 // report whether a file is present and enabled.
 // `docMusic.url` is versioned by the file's size and length, so replacing the
 // bed yields a different URL and the browser cannot replay the old one.
 const url=docMusic?.enabled&&docMusic.file_present?docMusic.url:'';
 const node=docMusicNode;
 if(!url){if(node&&node.hasAttribute('src')){node.pause();node.removeAttribute('src');node.load()}return}
 if(!node||node.getAttribute('src')!==url){
  docMusicSrc=url;
  const el=docMusicElement();el.src=url;
  try{el.currentTime=Math.max(0,t||0)}catch{}
  return;
 }
 // The export normalises the bed to a target loudness; the browser can only
 // scale the raw file. Without this the preview played several dB quieter than
 // the file it was previewing, which is why the bed seemed not to be there.
 node.volume=Math.max(0,Math.min(1,docMusicGain()*docMusicShapeAt(Math.max(0,t||0))));
 if(!playing){if(!node.paused)node.pause();return}
 // A live layer may drift; nudge it back without restarting the picture.
 // The bed loops, so its own position wraps while the film clock does not.
 // Compare where the loop actually is with where it should be, rather than
 // against the unwrapped time, which could never match past the first pass.
 const want=Math.max(0,t||0);
 const length=node.duration||0;
 const here=length>0?node.currentTime%length:node.currentTime;
 const there=length>0?want%length:want;
 if(node.readyState>=1&&Math.abs(here-there)>0.35){
  try{node.currentTime=there}catch{}
 }
 if(node.paused)node.play().catch(()=>{});
}

window.docApplyPreviewVolumes=function(){
 // Preview-only switching. The export always uses the saved narration, bite and
 // ducked music levels; nothing here changes the rendered file.
 //
 // Narration and the selected sound bites arrive as a single mixed stream, so one
 // fader cannot move one without the other. The quieter of the two saved levels is
 // what that stream can honestly represent; raising either alone would lift both.
 const speechLevel=Math.min(100,Math.min(docTrackVolume.narration??100,docTrackVolume.clip??100))/100;
 if(window.docTimelineData?.direct)narrNode.volume=speechLevel;
 else masterNode.volume=speechLevel;
 masterNode.muted=window.docTimelineData?.direct?true:editorMuted;
 sourceNode.volume=0;
 const t=window.docTimelineData?.direct?(narrNode.currentTime||0):(masterNode.currentTime||0);
 docSyncMusic(t,editorPlaying);
};

async function loadDocBiteWaveforms(){
 // One decode of the source audio feeds every bite waveform; nothing is uploaded.
 const clips=[...document.querySelectorAll('#doc-source-track .doc-audio-bite')];
 if(!clips.length)return;
 const source=assets().find(a=>a.kind==='video'&&a.url);
 if(!source)return;
 const key=source.url;
 if(docSpeechWaveKey!==key){docSpeechWaveKey=key;docSpeechPeaks=null;
  try{
   const response=await fetch(source.url);const buffer=await response.arrayBuffer();
   const ctx=new (window.AudioContext||window.webkitAudioContext)();const audio=await ctx.decodeAudioData(buffer);
   const channels=[audio.getChannelData(0)];if(audio.numberOfChannels>1)channels.push(audio.getChannelData(1));
   const bins=Math.min(60000,Math.max(1,Math.ceil(audio.duration*120))),peaks=new Float32Array(bins);
   for(let b=0;b<bins;b++){const a=Math.floor(b*audio.length/bins),e=Math.floor((b+1)*audio.length/bins);let peak=0;for(let i=a;i<e;i++)for(const channel of channels)peak=Math.max(peak,Math.abs(channel[i]));peaks[b]=peak}
   docSpeechPeaks=peaks;docSpeechDuration=audio.duration;ctx.close().catch(()=>{});
  }catch{return}
 }
 drawDocBiteWaveforms();
}
function drawDocBiteWaveforms(){const peaks=docSpeechPeaks,duration=docSpeechDuration;if(!peaks||!duration)return;
 for(const clip of document.querySelectorAll('#doc-source-track .doc-audio-bite canvas.speech-wave'))docLazyDraw(clip,drawDocBiteWave);
}
function drawDocBiteWave(clip){const peaks=docSpeechPeaks,duration=docSpeechDuration;if(!peaks||!duration)return;
 {
  const start=Number(clip.parentElement.dataset.start),end=Number(clip.parentElement.dataset.end);
  const width=Math.max(1,Math.min(4096,Math.ceil(clip.clientWidth))),height=16;clip.width=width;clip.height=height;
  const ctx=clip.getContext('2d');ctx.clearRect(0,0,width,height);ctx.fillStyle='rgba(255, 232, 197, .75)';
  for(let x=0;x<width;x++){const a=Math.floor((start+(end-start)*x/width)/duration*peaks.length),b=Math.max(a+1,Math.floor((start+(end-start)*(x+1)/width)/duration*peaks.length));let peak=0;for(let i=a;i<b&&i<peaks.length;i++)peak=Math.max(peak,peaks[i]);if(peak>0){const bar=Math.max(1,peak*(height-2));ctx.fillRect(x,(height-bar)/2,1,bar)}}
 }
}
