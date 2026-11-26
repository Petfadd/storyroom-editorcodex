/* The project system lives inside the established media/monitor/inspector/timeline shell. */
let sourceReady=false,sourceSeekToken=0,masterSeekToken=0,editorBuffering=false;
let pictureScaleSaving=false,exportScriptCaptions=false;
let timelineZoom=12,editorPlaying=false,editorMuted=false,editorVideoMuted=true,editorCC=false,burnSrtOnExport=false,editorMaster=false,masterUrl='',sourceScene='',clockBase=0,clockAt=0,editorContext='',activeSRT=-1,editorTickHandle=0;
const intervalIndexCache=new WeakMap();
let clipNodesByScene = new Map(), lastMarkedSceneIds = null;
const masterNode=$('#program-master'),imageNode=$('#program-image'),narrNode=$('#program-narration');
const standbyNode=document.createElement('video');standbyNode.id='program-source-next';standbyNode.muted=true;standbyNode.playsInline=true;standbyNode.preload='auto';standbyNode.disablePictureInPicture=true;standbyNode.setAttribute('disableremoteplayback','');imageNode.before(standbyNode);
let sourceNode=$('#program-source'),nextSourceNode=standbyNode,preparedScene='',preparedReady=false,prepareToken=0;
sourceNode.loop=false;nextSourceNode.loop=false;
imageNode.addEventListener('load',()=>drawBackdrop());
const scenes=()=>P?P.scenes:[],assets=()=>P?P.assets:[];
const totalTime=()=>P?.edit_mode==='documentary'?(window.docTimelineData?.duration||0):(scenes().at(-1)?.frame_out/30||0);
const fmt=t=>{t=Math.max(0,t||0);const f=Math.floor(t*30+.00001),pad=n=>String(Math.floor(n)).padStart(2,'0');return `${pad(f/108000)}:${pad(f/1800%60)}:${pad(f/30%60)}:${pad(f%30)}`};
const frameAt=t=>Math.floor(t*30+.001);
let enhancePicture=(()=>{try{const v=localStorage.getItem('storyroom.enhancePicture');return v===null?true:v==='1'}catch(e){return true}})(),docMusic={enabled:false,volume_percent:35,narration_level:'duck',file_present:false},docTrackVolume={audio:100,video:0,music:35,narration:100,clip:100},waveformKey='',waveformPeaks=null,waveformPending=null,slotScalePreview=null,selectedSlotIds=new Set(),selectionExplicitlyEmpty=false,marquee=null,suppressClipClick=false;
const editorTime=()=>editorMaster?(masterNode.currentTime||0):(P?.voiceover&&narrNode.getAttribute('src')?narrNode.currentTime:clockBase+(editorPlaying&&!editorBuffering?(performance.now()-clockAt)/1000:0));
const deletingProjects=new Set();
list=async function(){const d=await api('/api/projects');projects=d.projects;PROFILES=d.profiles||PROFILES;if($('#project-list'))$('#project-list').innerHTML=projects.map(p=>`<div class="project-row ${P?.id===p.id?'active':''}"><button type="button" class="project-link" onclick="openProject('${p.id}')">${E(p.title)}<small>${p.scenes} scenes · ${p.edit_mode==='documentary'?'Documentary':'Script review'}</small></button><button type="button" class="project-delete" aria-label="Delete ${E(p.title)}" onclick="deleteProduction('${p.id}')" ${deletingProjects.has(p.id)?'disabled':''}>Delete</button></div>`).join('')||'<p class="muted">No productions yet.</p>';return d};
async function deleteProduction(id){
 const project=projects.find(p=>p.id===id);if(!project||deletingProjects.has(id))return;
 if(uploading){toast('Please wait for the import to finish before deleting a production.');return}
 if(!confirm(`Permanently delete “${project.title}”?\n\nThis deletes the production and all its uploaded files, scripts, previews, and exports stored in this project. This cannot be undone.`))return;
 const active=P?.id===id;
 if(active&&!leave())return;
 deletingProjects.add(id);const button=document.querySelector(`.project-delete[onclick="deleteProduction('${id}')"]`);if(button)button.disabled=true;
 if(active){pauseEditor();resetEditor()}
 try{
  await api('/api/projects/'+id,'DELETE',{confirm:true});
  if(P?.id===id){P=null;sceneIndex=0;dirty=false;history.replaceState(null,'',location.pathname+location.search);renderProject()}
  await list();toast('Production and its project files deleted.');
 }catch(e){if(active&&P?.id===id)renderProject();toast(e.message)}
 finally{deletingProjects.delete(id);if(button&&button.isConnected)button.disabled=false}
}
function pauseManagementMedia(){document.querySelectorAll('#manage-dialog audio,#manage-dialog video').forEach(node=>node.pause())}
function closeTools(){pauseManagementMedia();for(const id of ['#manage-dialog'])if($(id)?.open)$(id).close()}
openProject=async function(id){if(!leave())return;pauseEditor();closeTools();P=await api('/api/projects/'+id);sceneIndex=P.script_moving_only?Math.max(0,P.scenes.findIndex(s=>P.assets.some(a=>a.id===s.asset_id&&a.kind==='video'))):0;tab='brief';history.replaceState(null,'','#/production/'+id);await list();resetEditor();renderProject();if(P.script_moving_only&&scenes()[sceneIndex]?.asset_id)seekEditor(scenes()[sceneIndex].frame_in/30,false)};
function resetEditor(){if(typeof clearScrubPreview==='function')clearScrubPreview();if(window.resetDocTimeline)window.resetDocTimeline();exportScriptCaptions=false;editorCC=false;burnSrtOnExport=false;$('#caption-toggle').textContent='CC Off';$('#caption-toggle').setAttribute('aria-pressed','false');selectedSlotIds=new Set();selectionExplicitlyEmpty=false;clipNodesByScene=new Map();lastMarkedSceneIds=null;slotScalePreview=null;clearPreparedSource();editorBuffering=false;sourceSeekToken++;masterSeekToken++;sourceReady=false;sourceScene='';clockBase=0;clockAt=performance.now();masterUrl='';editorMaster=false;masterNode.pause();masterNode.removeAttribute('src');masterNode.load();sourceNode.pause();sourceNode.removeAttribute('src');sourceNode.load();narrNode.pause();narrNode.removeAttribute('src');narrNode.load();$('#timeline-scroll').scrollLeft=0}
$('#new-form').onsubmit=async e=>{e.preventDefault();const button=e.submitter||$('#new-form button[type=submit]');button.disabled=true;try{pauseEditor();P=await api('/api/projects','POST',Object.fromEntries(new FormData(e.target)));sceneIndex=0;$('#new-dialog').close();history.replaceState(null,'','#/production/'+P.id);resetEditor();await list();renderProject();if(window.hideHomePage)hideHomePage();manage('brief');toast('New production created in the same timeline editor.')}finally{button.disabled=false}};
function manage(which){if(!['brief','assets','delivery'].includes(which))which='brief';if(!P){toast('Create a production first.');return}if(!leave())return;pauseEditor();tab=which;renderManagement();if(!$('#manage-dialog').open)$('#manage-dialog').showModal()}
changeTab=manage;
function closeManagement(){if(!leave())return;pauseManagementMedia();$('#manage-dialog').close();renderProject()}
function renderManagement(){if(!P)return;ensureStrictStatus();if(P.edit_mode==='documentary'&&tab==='delivery'){documentaryDeliveryHTML();return}$('#crumb').textContent=P.title;$('#manage-title').textContent={brief:'Production script, SRT & narration',assets:'Media uploads',delivery:'Review & export'}[tab]||'Production setup';$('#content').innerHTML=({brief:briefHTML,assets:assetsHTML,delivery:deliveryHTML}[tab]||briefHTML)();if(P.edit_mode==='documentary'&&P.documentary_beat_review&&tab==='brief')loadDocumentaryReadiness(P.id,'doc-brief-readiness');if(tab==='brief'&&typeof loadProjectHealth==='function')loadProjectHealth(P.id);
 // The music card reads its saved state after the panel is on screen, so opening
 // Setup never waits on an extra request.
 if(P.edit_mode==='documentary'&&tab==='brief'&&typeof loadDocMusicCard==='function')loadDocMusicCard().then(()=>{
  // Only refresh the music card. Rebuilding ALL of Setup after an async fetch
  // destroys user focus/scroll and can interrupt photo-list clicks or drags.
  if(P?.edit_mode!=='documentary'||tab!=='brief')return;
  const card=document.getElementById('doc-music-setup-card');if(!card)return;
  const info=window.docMusicCard||{},status=card.querySelector('.setup-status');
  if(status){status.textContent=info.present?'Saved':'Optional';status.classList.toggle('ready',!!info.present)}
  const summary=card.querySelector('p');
  if(summary)summary.textContent=info.present?`${info.name||'Background audio'}${info.duration_s?' · '+Number(info.duration_s).toFixed(1)+'s':''} · ${info.enabled?'on':'off'}`:'No file.';
  const controls=card.querySelector('.inline');
  if(controls){
    const upload=controls.querySelector('button');if(upload)upload.textContent=info.present?'Replace':'Add file';
    let toggle=controls.querySelector('[data-doc-music-toggle]');
    if(info.present&&!toggle){toggle=document.createElement('button');toggle.type='button';toggle.dataset.docMusicToggle='1';toggle.onclick=()=>docToggleMusic();controls.appendChild(toggle)}
    if(toggle){if(info.present)toggle.textContent=info.enabled?'Off':'On';else toggle.remove()}
  }
 });if(P.render?.url&&!isCurrentRender(P.render))$('#content').insertAdjacentHTML('afterbegin','<div class="notice warn"><strong>Previous MP4, not current.</strong> It was made before the latest timeline or export changes. Resolve the checks below, then render again to include your changes.</div>')}
renderProject=function(){syncMonitorShape();syncAspectChip();renderEditor();if($('#manage-dialog').open)renderManagement();const briefBox=document.getElementById('doc-brief-readiness');if(briefBox&&P?.id&&P?.documentary_beat_review&&typeof loadDocumentaryReadiness==='function')loadDocumentaryReadiness(P.id,'doc-brief-readiness');requestEditorTick()};
const oldNewProduction=newProduction;newProduction=function(){pauseEditor();oldNewProduction()};
selectScene=i=>selectEditorScene(i);
const savedSplit=splitBeat,savedMerge=mergeBeat;
splitBeat=async function(){pauseEditor();await savedSplit();sourceScene='';renderProject()};mergeBeat=async function(){pauseEditor();await savedMerge();sourceScene='';renderProject()};
function tileLen(seconds){const t=Math.max(0,Math.round(seconds||0));return Math.floor(t/60)+':'+String(t%60).padStart(2,'0')}
let poolFilter='all';
function setPoolFilter(which){poolFilter=which;document.querySelectorAll('.pool-chip').forEach(b=>b.classList.toggle('is-on',b.dataset.poolFilter===which));renderMediaPool()}
/* One tile shape for every upload. Video and photographs show a poster frame;
   narration and captions get a plate in the same rhythm so the grid reads as a
   single list rather than two kinds of box. */
function mediaTileHTML(a){
  const poster=`/api/projects/${P?.id}/assets/${a.id}/poster?v=${encodeURIComponent(a.revision||a.id)}`;
  const isPhoto=a.kind==='image';
  const badge=a.reserve?'RESERVE':(isPhoto?'PHOTO':'VIDEO');
  const len=!isPhoto&&a.duration?tileLen(a.duration):'';
  // `current` is scoped to renderEditor, so read the selected scene directly.
  const sel=(scenes()[sceneIndex]||{}).asset_id===a.id?'selected':'';
  return {kind:isPhoto?'photo':'video',html:`<button type="button" class="pool-tile ${sel} ${isPhoto?'is-photo':''}" onclick="inspectAsset('${a.id.replace(/'/g,'')}')" title="${E(a.name)}"><span class="tile-shot"><img src="${poster}" alt="" loading="lazy" onerror="this.closest('.tile-shot').classList.add('no-poster')"><em>${badge}</em>${len?`<b>${len}</b>`:''}<i class="ready-dot ${a.verified?'':'missing'}"></i></span><span class="tile-name">${E(a.name.replace(/\.[^.]+$/,''))}</span></button>`};
}
function poolAudioTile(name,duration,isMusic=false){
  const bars=[38,62,84,48,72,96,58,80,44,68,92,54,76,60,88,46,70,94,56,82,50,74,66,90,52,78];
  const action=isMusic?'docPickMusic()':"manage('brief')";
  const title=isMusic?`Replace music: ${name}`:name;
  const wave=bars.map(height=>`<i style="height:${height}%"></i>`).join('');
  return {kind:'audio',html:`<button type="button" class="pool-tile pool-audio${isMusic?' pool-music':''}" onclick="${action}" title="${E(title)}" aria-label="${E(isMusic?title:'Audio: '+name)}"><span class="tile-shot"><span class="wave" aria-hidden="true">${wave}</span><em>${isMusic?'MUSIC':'AUDIO'}</em><b>${tileLen(duration)}</b></span><span class="tile-name">${E(name.replace(/\.[^.]+$/,''))}</span></button>`};
}
function poolSrtTile(srt){
  return {kind:'srt',html:`<button type="button" class="pool-tile pool-srt" onclick="manage('brief')" title="${E(srt.name||'captions')}"><span class="tile-shot"><span class="srt-plate" aria-hidden="true">SRT</span><em>TIMING</em><b>${srt.blocks.length}</b></span><span class="tile-name">${E((srt.name||'captions').replace(/\.[^.]+$/,''))}</span></button>`};
}
function renderMediaPool(){
 const requirement=P?.footage_requirements;
 const reqPool=$('#footage-requirements-pool');
 reqPool.textContent=requirement?.status==='found'?`${requirement.total} script file${requirement.total===1?'':'s'} · ${requirement.matched} matched · ${requirement.missing} missing${requirement.ambiguous?' · '+requirement.ambiguous+' duplicate':''}`:P?.production_script?'No video filenames recognized in script':'Upload a production script to see the footage count.';
 const isDocumentary=P?.edit_mode==='documentary';
 const music=isDocumentary&&docMusic?.file_present?docMusic:null;
 const musicButton=$('#pool-add-music');
 musicButton.hidden=!isDocumentary;
 musicButton.title=music?'Replace background music':'Add background music or SFX';
 musicButton.innerHTML=music?'<span aria-hidden="true">♪</span> Music':'<span aria-hidden="true">+</span> Add music';
 const visibleAssets=assets().filter(a=>!(P?.picture_policy==='clips_only'&&a.kind==='image'&&a.derived_from));
 const want=(typeof poolFilter==='string'?poolFilter:'all');
 const tiles=[];
 visibleAssets.forEach((a,i)=>{tiles.push(mediaTileHTML(a,i))});
 if(P?.voiceover)tiles.push(poolAudioTile(P.voiceover.name,P.voiceover.duration));
 if(P?.srt)tiles.push(poolSrtTile(P.srt));
 if(music)tiles.push(poolAudioTile(music.name||'Background music',music.duration_s,true));
 $('#source-count').textContent=tiles.length;
 // Filtering only hides tiles; the pool order never changes underneath.
 const shown=tiles.filter(t=>want==='all'||t.kind===want||(want==='audio'&&t.kind==='srt'));
 {const html=shown.map(t=>t.html).join(''),list=$('#media-list');if(list.dataset.html!==html){list.innerHTML=html;list.dataset.html=html}}  // unchanged pool: no rebuild, no image reloads
 if($('#pool-empty'))$('#pool-empty').hidden=shown.length>0;
 if(reqPool)reqPool.hidden=shown.length===0;
 // A quiet footer keeps narration and SRT timing visible without spending a
 // whole card on each: the same facts, one line.
 if($('#pool-foot')){
  const bits=[];
  if(P?.voiceover)bits.push(`<strong>${tileLen(P.voiceover.duration)}</strong> narration`);
  if(P?.srt)bits.push(`<strong>${P.srt.blocks.length}</strong> SRT blocks`);
  if(visibleAssets.length)bits.push(`<strong>${visibleAssets.length}</strong> source${visibleAssets.length===1?'':'s'}`);
  $('#pool-foot').hidden=!bits.length;
  $('#pool-foot').innerHTML=bits.join('<span aria-hidden="true">·</span>');
 }
}
function renderEditor(){
 const isDoc=P?.edit_mode==='documentary';if(window.ensureDocTimeline)window.ensureDocTimeline();document.body.classList.toggle('documentary-workspace',isDoc);$('#documentary-button').hidden=!isDoc;$('#documentary-timeline-label').hidden=!isDoc;$('#documentary-prepare-timeline').hidden=!isDoc;$('#doc-source-track').hidden=!isDoc;$('#doc-source-label').hidden=!isDoc;
 const setupButton=$('#setup-button');if(setupButton){const editing=!!(P&&scenes().length);setupButton.textContent=editing?'Edit':'Setup';setupButton.title=editing?'Edit the current production files and settings':'Set up production files and settings';setupButton.setAttribute('aria-label',setupButton.title)}
 const ss=scenes();if($('#frame-qc-button'))$('#frame-qc-button').hidden=!ss.length;selectedSlotIds=new Set([...selectedSlotIds].filter(id=>ss.some(s=>s.id===id)));// The header shows the production's own name and nothing else. The workspace type,
// scene count and approval tally used to sit under it; they are gone, and the name
// carries no "Documentary" suffix because that is a workspace, not a title.
// The header shows the production's own name, and nothing else when there is no
// production to name. "Storyboard editor" here read as though it were the name of a
// project, which is exactly what the bar must never imply.
$('#project-name').textContent=P?.title||'Untitled production';document.title=(P?.title||'Storyroom')+' · Timeline editor'; // Clicking a source opens it, so the pool carries that instruction on the list
 // itself. It used to be written through `.media-hint`, which matched the
 // footage-count line first and wiped that count on every render.
 const pool=$('#media-list');
 if(pool){
  const clickable=P?.script_moving_only||!scenes().length;
  pool.title=clickable?'Click a source to play the original file.':'';
 }
 renderMediaPool();
renderProgram();renderTimeline();renderInspector();renderChecks();renderExport();updateTrackMuteControls();updatePosition();
}
function missingVisualHTML(s){return s?.replacement_issue?`<strong>Replaced footage needs attention</strong><span>${E(s.replacement_issue)} No substitute was chosen.</span><button class="button secondary" onclick="goToNextVideo()">Go to next available video</button>`:s?.missing_video_out?`<strong>Still placement not shown in video review</strong><span>${E(s.plan_row?.shot_id||'This shot')} specifies a still or freeze. No screenshot, extracted frame or guessed video is being shown.</span><button class="button secondary" onclick="goToNextVideo()">Go to next available video</button>`:s?.plan_row?.strict_production?`<strong>Scripted video unavailable</strong><span>${E(s.plan_row.shot_id||'This shot')} requires ${E(s.plan_row.source_file||'a source file')} at ${E(mapClock(s.plan_row.source_in_ms))}–${E(mapClock(s.plan_row.source_out_ms))}. ${E((P?.script_application?.issues||[]).find(x=>x.startsWith('Beat '+s.plan_row.shot_id+':'))||'The file may be missing, too short, or overlap another shot.')} No substitute was chosen.</span><button class="button secondary" onclick="goToNextVideo()">Go to next available video</button>`:'<strong>No visual assigned to this scene</strong><span>Choose uploaded media in the shot inspector, or import case footage.</span><button class="button secondary" onclick="manage(\'assets\')">Import media</button>'}
function goToNextVideo(){const ss=scenes(),video=s=>assets().some(a=>a.id===s.asset_id&&a.kind==='video');let index=ss.findIndex((s,i)=>i>sceneIndex&&video(s));if(index<0)index=ss.findIndex(video);if(index>=0)selectEditorScene(index);else toast('No playable scripted video is available.') }
function isCurrentRender(r){const o=r?.options;if(!r?.current||!o)return false;if(P?.edit_mode==='documentary')return !!o.srt_subtitles===burnSrtOnExport&&o.enhance_picture!==true;return !!o.script_captions===exportScriptCaptions&&!!o.srt_subtitles===burnSrtOnExport&&o.enhance_picture!==true}
function renderProgram(){
 // The saved caption look is applied before anything is drawn, so the preview carries
 // the project's own style from the first frame rather than the stylesheet default.
 applyCaptionPreset();
 if(P?.edit_mode==='documentary'){docRenderProgram();return}
 const target=editorVideoMuted?(P?.render?.status==='done'&&isCurrentRender(P.render)?P.render.url:(P?.preview?.status==='done'?P.preview.url:'')):'';
 if(editorPlaying&&masterUrl!==target)return;
 const t=editorTime();
 if(target){
  if(masterUrl!==target){narrNode.pause();sourceNode.pause();masterUrl=target;editorMaster=true;masterNode.src=target;masterNode.load();const token=++masterSeekToken;masterNode.addEventListener('loadedmetadata',()=>{if(token===masterSeekToken&&masterNode.getAttribute('src')===target)masterNode.currentTime=Math.min(t,masterNode.duration||t)},{once:true})}
  editorMaster=true;masterNode.classList.add('is-active');sourceNode.classList.remove('is-active');imageNode.hidden=true;
 }else{
  if(masterUrl){masterNode.pause();masterNode.removeAttribute('src');masterNode.load();masterUrl=''}editorMaster=false;masterNode.classList.remove('is-active');
  const url=P?.voiceover?.url||'';if(narrNode.getAttribute('src')!==url){narrNode.pause();if(url){narrNode.src=url;narrNode.load()}else{narrNode.removeAttribute('src');narrNode.load()}}
  showSource(sceneIndex,t);
 }
 syncPictureScale();
 const assigned=scenes().length&&assets().some(a=>a.id===scenes()[sceneIndex]?.asset_id);$('#monitor-empty').hidden=!!scenes().length&&(editorMaster||assigned);if(scenes().length&&!assigned&&!editorMaster)$('#monitor-empty').innerHTML=missingVisualHTML(scenes()[sceneIndex]);else if(!scenes().length){if(P?.script_reading?.status==='read'){const r=P.script_reading;$('#monitor-empty').innerHTML=`<strong>Script read · storyboard not built</strong><span>${r.shots} shots found. Captions, stills and other script instructions need attention before an accurate edit can be assembled.</span><button class="button secondary" onclick="createScriptDraft()" ${buildDisabled()}>Build review timeline</button><button class="button secondary" onclick="manage('brief');showScriptReading()">Review the shot plan</button>`}else if(P&&assets().some(a=>a.kind==='video')){const count=assets().filter(a=>a.kind==='video').length;$('#monitor-empty').innerHTML=`<strong>${count} source video${count===1?'':'s'} uploaded</strong><span>${P.srt?'Your storyboard has not been built yet.':'Your SRT has not been imported into this project, so there is no timeline yet.'} You can play the uploaded videos now.</span><button class="button secondary" onclick="openFirstSourceFile()">Play an uploaded video</button><button class="button secondary" onclick="manage('brief')">Open setup</button>`}else {const missing=(P?.source_match_report||[]).filter(x=>!['matched','selected'].includes(x.status));$('#monitor-empty').innerHTML=missing.length?`<strong>Storyboard waiting for footage links</strong><span>Script filenames need matching uploads: ${missing.map(x=>E(x.source_file)).join(', ')}. Your imported files are still here.</span><button class="button secondary" onclick="manage('brief')">Resolve script filenames</button>`:P?.srt?'<strong>Storyboard not built yet</strong><span>Your SRT is imported. Build the storyboard in Setup to place picture beats on the MP4 track.</span><button class="button secondary" onclick="manage(\'brief\')">Open production setup</button>':'<strong>Keep the editor. Start a new story.</strong><span>Import narration, SRT and case media from Setup.</span><button class="button secondary" onclick="newProduction()">＋ New production</button>';}}$('#preview-mode').textContent=P?.script_moving_only?'REVIEW PLAYBACK · NOT FINAL':P?.review_only_draft?'REVIEW DRAFT · NOT FINAL':editorMaster?(target===P?.preview?.url?'SMOOTH PREVIEW':'CONTINUOUS MASTER'):(['queued','running'].includes(P?.preview?.status)?`PREPARING SMOOTH PREVIEW ${Math.floor(P.preview.progress||0)}%`:'SOURCE PREVIEW');
}
function effectivePictureScale(scene){return Number(scene?.picture_scale??P?.picture_scale??100)}
function selectedScenes(){return scenes().filter(s=>selectedSlotIds.has(s.id))}
function updatePictureScalePreview(){
 // In documentary mode the picture is a source <video> swapped per frame, so the
 // scale is shared with the timeline repaint (it would be wiped otherwise).
 if(P?.edit_mode==='documentary'&&typeof docApplyPictureScale==='function'){docApplyPictureScale();return}
 const scene=scenes()[sceneIndex],saved=effectivePictureScale(scene),desired=slotScalePreview?.ids.has(scene?.id)?slotScalePreview.value:saved;$('#picture-layer').style.transform=`scale(${editorMaster?desired/saved:desired/100})`}
function syncPictureScale(){updatePictureScalePreview()}
function previewSlotScale(value){const chosen=selectedScenes();if(!chosen.length)return;value=Math.max(100,Math.min(200,Math.round(Number(value)||100)));slotScalePreview={ids:new Set(chosen.map(s=>s.id)),value};for(const id of ['#slot-scale-range','#slot-scale-number']){const node=$(id);if(node)node.value=value}updatePictureScalePreview()}
async function saveSlotScale(value){const chosen=selectedScenes();if(!P||!chosen.length||pictureScaleSaving)return;const live=P.edit_mode==='documentary';/* a documentary applies scale live while it keeps playing */if(!live){if(!leave()){slotScalePreview=null;syncPictureScale();renderInspector();return}pauseEditor()}const id=P.id,ids=chosen.map(s=>s.id);value=value===null?null:Math.max(100,Math.min(200,Math.round(Number(value)||100)));if(value!==null)previewSlotScale(value);pictureScaleSaving=true;for(const x of ['#slot-scale-range','#slot-scale-number'])if($(x))$(x).disabled=true;renderExport();try{const updated=await api(`/api/projects/${id}/scenes/picture-scale?compact=1`,'PATCH',{scene_ids:ids,picture_scale:value});if(P?.id!==id)return;P.updated=updated.updated;for(const row of updated.scenes||[]){const scene=P.scenes.find(s=>s.id===row.id);if(scene){if(row.picture_scale==null)delete scene.picture_scale;else scene.picture_scale=row.picture_scale}}slotScalePreview=null;syncPictureScale();const status=$('#scene-save-status');if(status)status.textContent='Scale saved · No rebuild needed'}catch(e){slotScalePreview=null;toast(e.message)}finally{pictureScaleSaving=false;syncPictureScale();renderExport()}}
function clearPreparedSource(){
 prepareToken++;preparedScene='';preparedReady=false;nextSourceNode.pause();
 nextSourceNode.onloadedmetadata=nextSourceNode.onseeked=nextSourceNode.onloadeddata=nextSourceNode.onerror=null;
 nextSourceNode.removeAttribute('src');nextSourceNode.load();nextSourceNode.classList.remove('is-active');
}
function prepareNextSource(i,t){
 if(editorMaster||!editorPlaying||editorBuffering||!sourceReady)return;
 const current=scenes()[i],next=scenes()[i+1],asset=assets().find(a=>a.id===next?.asset_id);
 if(!current||!next||!asset||asset.kind!=='video'||current.frame_out/30-t>8)return;
 if(preparedScene===next.id)return;
 clearPreparedSource();preparedScene=next.id;const token=prepareToken,node=nextSourceNode,target=Number(next.in_s);
 const valid=()=>token===prepareToken&&preparedScene===next.id&&node===nextSourceNode;
 const ready=()=>{if(valid()&&!node.seeking&&node.readyState>=2&&Math.abs(node.currentTime-target)<.15)preparedReady=true};
 const seek=()=>{if(!valid()||node.readyState<1)return;if(!Number.isFinite(target)||target<0||target>node.duration+.034)return;try{node.currentTime=target;ready()}catch{}};
 node.onloadedmetadata=seek;node.onseeked=ready;node.onloadeddata=ready;node.onerror=()=>{if(valid())preparedReady=false};
 node.src=asset.url;node.load();
}
function usePreparedSource(s,a,t){
 if(preparedScene!==s.id||!preparedReady||nextSourceNode.getAttribute('src')!==a.url)return false;
 const offset=Math.max(0,t-s.frame_in/30);if(offset>.18)return false;
 sourceSeekToken++;sourceNode.pause();sourceNode.classList.remove('is-active');
 sourceNode.onloadedmetadata=sourceNode.onseeked=sourceNode.onloadeddata=sourceNode.onerror=null;
 const wasBuffering=editorBuffering;const old=sourceNode;sourceNode=nextSourceNode;nextSourceNode=old;prepareToken++;preparedScene='';preparedReady=false;
 sourceNode.onloadedmetadata=sourceNode.onseeked=sourceNode.onloadeddata=sourceNode.onerror=null;
 sourceReady=true;editorBuffering=false;clockAt=performance.now();sourceNode.playbackRate=1;sourceNode.muted=editorVideoMuted;nextSourceNode.muted=true;sourceNode.classList.add('is-active');imageNode.hidden=true;$('#monitor-empty').hidden=true;
 if(editorPlaying&&wasBuffering&&P?.voiceover){narrNode.muted=editorMuted;narrNode.play().catch(()=>pauseEditor())}
 if(editorPlaying)sourceNode.play().catch(()=>{if(sourceScene===s.id&&!editorMaster)seekSourceAtTimeline(s,a,editorTime())});
 return true;
}
function seekSourceAtTimeline(s,a,t){
 // Seek a second video element while the previous decoded picture stays visible.
 // Nothing is captured, saved, or added to the edit.
 const token=++sourceSeekToken;sourceReady=false;sourceNode.pause();sourceNode.muted=editorVideoMuted;sourceNode.playbackRate=1;
 prepareToken++;preparedScene='';preparedReady=false;const reuseActive=sourceNode.classList.contains('is-active')&&sourceNode.getAttribute('src')===a.url;const node=reuseActive?sourceNode:nextSourceNode;node.pause();node.muted=reuseActive?editorVideoMuted:true;node.playbackRate=1;
 editorBuffering=true;clockBase=t;clockAt=performance.now();narrNode.pause();
 const valid=()=>token===sourceSeekToken&&sourceScene===s.id&&!editorMaster&&node===(reuseActive?sourceNode:nextSourceNode);
 const desired=()=>Number(s.in_s)+Math.max(0,t-s.frame_in/30);
 const failed=()=>{if(token!==sourceSeekToken||sourceScene!==s.id||editorMaster)return;sourceReady=false;pauseEditor();$('#monitor-empty').hidden=false;$('#monitor-empty').innerHTML='<strong>Media preview unavailable</strong><span>Playback paused with the narration; no empty slot was played.</span>'};
 let readyDone=false;
 const seek=()=>{if(!valid()||node.readyState<1)return;const target=desired();if(!Number.isFinite(target)||target<0||target>node.duration+.034){failed();return}try{node.currentTime=target;if(!node.seeking&&node.readyState>=2)ready()}catch{failed()}};
 const ready=()=>{if(readyDone||!valid()||node.seeking||node.readyState<2)return;if(Math.abs(node.currentTime-desired())>.15){seek();return}readyDone=true;
  if(!reuseActive){const old=sourceNode;sourceNode=node;nextSourceNode=old;old.classList.remove('is-active');old.onloadedmetadata=old.onseeked=old.onloadeddata=old.onerror=null;}
  sourceNode.onloadedmetadata=sourceNode.onseeked=sourceNode.onloadeddata=sourceNode.onerror=null;sourceNode.muted=editorVideoMuted;sourceNode.classList.add('is-active');imageNode.hidden=true;
  sourceReady=true;editorBuffering=false;clockAt=performance.now();$('#monitor-empty').hidden=true;drawBackdrop();if(editorPlaying){const jobs=[sourceNode.play()];if(P?.voiceover){narrNode.muted=editorMuted;jobs.push(narrNode.play())}Promise.all(jobs).catch(()=>{if(token===sourceSeekToken&&editorPlaying&&!editorMaster)failed()})}};
 node.onloadedmetadata=seek;node.onseeked=ready;node.onloadeddata=ready;node.onerror=failed;
 if(node.getAttribute('src')!==a.url){node.src=a.url;node.load()}else if(node.readyState>=1)seek();
}

// If the active video actually starves, hold narration until decoding resumes.
for(const node of [sourceNode,nextSourceNode]){
 node.addEventListener('waiting',()=>{
  // Documentary review runs on an audio clock; a starving video must not pause it.
  if(P?.edit_mode==='documentary')return;
  if(node!==sourceNode||editorMaster||!editorPlaying||!sourceReady||editorBuffering)return;
  const now=editorTime();editorBuffering=true;clockBase=now;clockAt=performance.now();narrNode.pause();
 });
 node.addEventListener('playing',()=>{
  if(P?.edit_mode==='documentary')return;
  if(node!==sourceNode||editorMaster||!editorPlaying||!sourceReady||!editorBuffering)return;
  editorBuffering=false;clockAt=performance.now();
  if(P?.voiceover){narrNode.muted=editorMuted;narrNode.play().catch(()=>pauseEditor())}
 });
}

function showSource(i,t){
 if(editorMaster)return;const s=scenes()[i],a=assets().find(a=>a.id===s?.asset_id);if(!s||!a||s.missing_video_out){sourceSeekToken++;sourceReady=false;sourceNode.pause();sourceNode.classList.remove('is-active');if(sourceNode.getAttribute('src')){sourceNode.removeAttribute('src');sourceNode.load()}imageNode.hidden=true;sourceScene='';$('#blur-backdrop').getContext('2d').clearRect(0,0,960,540);if(s){if(editorPlaying)pauseEditor();$('#monitor-empty').hidden=false;$('#monitor-empty').innerHTML=missingVisualHTML(s)}return}
 const framedPhoto=a.kind==='image'||!!s.photo_frame_url;
 if(sourceScene!==s.id){
  $('#monitor-empty').hidden=true;sourceScene=s.id;
  if(framedPhoto){sourceNode.pause();sourceSeekToken++;sourceReady=false;editorBuffering=false;clockAt=performance.now();imageNode.style.transform='none';sourceNode.onloadedmetadata=sourceNode.onseeked=sourceNode.onloadeddata=sourceNode.onerror=null;imageNode.src=s.photo_frame_url||a.clean_url||a.url;imageNode.hidden=false;sourceNode.classList.remove('is-active')}
  else if(editorPlaying&&sourceReady&&!sourceNode.seeking&&sourceNode.getAttribute('src')===a.url&&Math.abs(sourceNode.currentTime-(Number(s.in_s)+Math.max(0,t-s.frame_in/30)))<.12){ /* Continuous interval in the same source: keep decoding without a seek. */ }
  else if(!usePreparedSource(s,a,t)){seekSourceAtTimeline(s,a,t)}
 }
 if(framedPhoto){applyImageMotion(s,Math.max(0,t-s.frame_in/30));}
 else if(editorPlaying&&sourceReady&&!sourceNode.seeking){
  // Small browser clock differences are normal. Correct them gradually rather than
  // repeatedly pausing narration and seeking the picture on every animation frame.
  const drift=sourceNode.currentTime-(Number(s.in_s)+Math.max(0,t-s.frame_in/30));
  sourceNode.playbackRate=s.plan_row?.strict_production?1:(Math.abs(drift)<.06?1:Math.max(.85,Math.min(1.15,1-drift*.12)));
 }
}

function applyImageMotion(s,elapsed){const m=s.motion_plan;if(!m)return;const p=Math.max(0,Math.min(1,elapsed/m.duration_s)),q=m.easing==='linear'?p:m.easing==='quick_settle'?(p<.08?p*p/.1472:p>.92?1-(1-p)*(1-p)/.1472:(p-.04)/.92):m.easing==='sine'?.5-.5*Math.cos(Math.PI*p):m.easing==='smootherstep'?p*p*p*(p*(p*6-15)+10):p*p*(3-2*p);const z=m.zoom_start+(m.zoom_end-m.zoom_start)*q,x=m.x_start+(m.x_end-m.x_start)*q,y=m.y_start+(m.y_end-m.y_start)*q;imageNode.style.transform=`translate(${(.5-x)*(z-1)*100}%,${(.5-y)*(z-1)*100}%) scale(${z})`}
let lastBackdropDraw=0;
function drawBackdrop(){if(editorMaster||(imageNode.hidden&&!sourceReady))return;const node=imageNode.hidden?sourceNode:imageNode,w=node.videoWidth||node.naturalWidth,h=node.videoHeight||node.naturalHeight;if(!w||!h)return;const now=performance.now();if(now-lastBackdropDraw<100)return;lastBackdropDraw=now;const c=$('#blur-backdrop'),scale=Math.max(c.width/w,c.height/h);try{c.getContext('2d').drawImage(node,(c.width-w*scale)/2,(c.height-h*scale)/2,w*scale,h*scale)}catch{}}
// Correct known UTF-8 decoding artifacts for display only; never rewrite uploaded text.
let captionMeasureKey='';const captionMeasureCanvas=document.createElement('canvas');
function captionLook(){
 const key=P?.caption_preset||captionCatalogue?.selected||'documentary';
 const list=captionCatalogue?.presets||[];
 const alias={clean:'documentary',lower_band:'boxed',kinetic:'bold_pop'};
 return list.find(x=>x.key===(alias[key]||key))||list[0]||null;
}
// The caption is sized from the monitor's HEIGHT, exactly as the export sizes it from
// the master's height, then shrunk to one line -- so the preview is the export.
function fitSrtCaption(cue,t){
 const overlay=$('#editor-captions'),textNode=$('#editor-caption-text');
 const look=captionLook();
 let text=String(cue?.text||'').replace(/\s*\n\s*/g,' ').trim();
 if(look?.upper)text=text.toUpperCase();
 const monitor=overlay.offsetParent||overlay.parentElement,height=monitor?.clientHeight||0,width=overlay.clientWidth;
 const words=text?text.split(' '):[];
 let active=-1;
 if(look?.highlight&&words.length>1&&cue&&Number.isFinite(t)){
  const ms=t*1000,a=cue.start_ms,b=cue.end_ms,weights=words.map(w=>w.length+1),total=weights.reduce((x,y)=>x+y,0);let done=0;
  for(let i=0;i<words.length;i++){const s0=a+(b-a)*done/total;done+=weights[i];const s1=a+(b-a)*done/total;if(ms>=s0&&ms<s1){active=i;break}}
 }
 const key=text+'|'+width+'|'+height+'|'+active+'|'+(look?.key||'')+'|'+(P?.caption_size||'');if(key===captionMeasureKey)return;
 captionMeasureKey=key;
 if(active>=0)textNode.innerHTML=words.map((w,i)=>i===active?`<span style="color:${look.highlight}">${E(w)}</span>`:E(w)).join(' ');
 else textNode.textContent=text;
 if(!text||!width||!height)return;
 const factor=(captionCatalogue?.sizes||[]).find(x=>x.key===(P?.caption_size||'medium'))?.factor||1;
 const em=height*(look?.size||50)*factor/1080;
 const ctx=captionMeasureCanvas.getContext('2d');
 ctx.font=`${em}px '${look?.font||'SR Inter SemiBold'}', Inter, system-ui, sans-serif`;
 const measured=ctx.measureText(text).width+em*.4;const scale=Math.min(1,(width*.92)/Math.max(1,measured));
 textNode.style.fontSize=Math.max(9,em*scale).toFixed(2)+'px';
}
function findActiveIntervalIndex(rows,time,startKey='start_ms',endKey='end_ms'){
 if(!Array.isArray(rows)||!rows.length)return -1;
 let index=intervalIndexCache.get(rows);
 if(!index){
  const starts=new Float64Array(rows.length),ends=new Float64Array(rows.length),prefixMaxEnds=new Float64Array(rows.length);let lastStart=-Infinity,maxEnd=-Infinity,sorted=true;
  for(let i=0;i<rows.length;i++){
   const start=Number(rows[i]?.[startKey]),end=Number(rows[i]?.[endKey]);
   if(!Number.isFinite(start)||!Number.isFinite(end)||start<lastStart)sorted=false;
   starts[i]=start;ends[i]=end;lastStart=start;maxEnd=Math.max(maxEnd,end);prefixMaxEnds[i]=maxEnd;
  }
  index={starts,ends,prefixMaxEnds,sorted};intervalIndexCache.set(rows,index);
 }
 // Keep the old scan for malformed or unsorted input. For normal ordered timelines,
 // find the first active interval in O(log n), including overlapping intervals.
 if(!index.sorted)return rows.findIndex(row=>time>=row[startKey]&&time<row[endKey]);
 let left=0,right=rows.length;
 while(left<right){const middle=(left+right)>>1;if(index.prefixMaxEnds[middle]<=time)left=middle+1;else right=middle}
 const first=left;left=0;right=rows.length;
 while(left<right){const middle=(left+right)>>1;if(index.starts[middle]<=time)left=middle+1;else right=middle}
 for(let i=first;i<left;i++)if(time<index.ends[i])return i;
 return -1;
}
function updatePosition(){if(P?.edit_mode==='documentary'){docUpdatePosition();return}updatePictureScalePreview();const t=editorTime();

 const readout=$('#source-clock');if(readout){const current=scenes()[sceneIndex],asset=assets().find(a=>a.id===current?.asset_id);readout.textContent=asset?.kind==='video'?(sourceReady?'Actual player source: '+sourceNode.currentTime.toFixed(3)+'s':'Seeking to the saved source interval…'):'Still candidate; image identity not automatically verified.'}setTimecode(fmt(t),fmt(totalTime()));movePlayhead(t*timelineZoom);setPlayheadAria(t,totalTime());const blocks=P?.srt?.blocks||[],index=findActiveIntervalIndex(blocks,t*1000),captions=P?.caption_phrases||[],cueIndex=findActiveIntervalIndex(captions,t*1000),cue=cueIndex>=0?captions[cueIndex]:null,overlay=$('#editor-captions');overlay.classList.toggle('captions-off',!editorCC||!cue||(editorMaster&&P?.render?.url===masterUrl&&P?.render?.options?.srt_subtitles));if(index!==activeSRT){document.querySelector('.caption-block.active')?.classList.remove('active');document.querySelector(`.caption-block[data-caption-index="${index}"]`)?.classList.add('active');activeSRT=index}fitSrtCaption(cue);if(cue){const fade=Math.min(.12,(cue.end_ms-cue.start_ms)/4000);overlay.style.opacity=fade?String(Math.max(0,Math.min(1,(t-cue.start_ms/1000)/fade,(cue.end_ms/1000-t)/fade))):'1'}}
function renderTimeline(){
 if(P?.edit_mode==='documentary'){clipNodesByScene=new Map();lastMarkedSceneIds=null;docRenderTimeline();return}
 activeSRT=-1;const ss=scenes(),duration=Math.max(totalTime(),Number(P?.voiceover?.duration)||0,(P?.srt?.blocks||[]).at(-1)?.end_ms/1000||0),width=Math.max(duration*timelineZoom,$('#timeline-scroll').clientWidth-2,600);$('#timeline-content').style.width=width+'px';$('#track-legend').textContent='';
 const step=timelineZoom<5?60:30;let ticks='';for(let t=0;t<=duration+step;t+=step)ticks+=`<span class="ruler-tick" style="left:${t*timelineZoom}px">${Math.floor(t/60).toString().padStart(2,'0')}:${String(t%60).padStart(2,'0')}</span>`;$('#ruler-track').innerHTML=ticks;
 $('#video-track').innerHTML=ss.map((s,i)=>{const a=assets().find(a=>a.id===s.asset_id),thumb=a&&P?`/api/projects/${P.id}/scenes/${s.id}/thumbnail?v=${encodeURIComponent(a.revision||a.id)}&in=${encodeURIComponent(s.in_s||0)}`:'';return `<div class="shot-clip ${selectedSlotIds.has(s.id)?'selected':''} ${a?.kind==='image'?'image-clip':''}" data-scene="${i}" role="button" tabindex="0" aria-pressed="${selectedSlotIds.has(s.id)}" title="${E(s.narration)}" style="left:${s.frame_in/30*timelineZoom}px;width:${Math.max(3,(s.frame_out-s.frame_in)/30*timelineZoom-1)}px" onclick="selectEditorScene(${i},event)" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();selectEditorScene(${i},event)}">${thumb?`<img class="clip-thumb" src="${thumb}" loading="lazy" alt="" onerror="this.hidden=true">`:''}<div class="clip-text"><strong>${E((s.plan_row?.shot_id||('SRT '+s.srt_blocks.join('–'))))} · ${E(a?.original_name||a?.name||s.plan_row?.source_file||'MEDIA NEEDED')}</strong><span>${((s.frame_out-s.frame_in)/30).toFixed(1)}s · ${E(s.purpose||s.focus)}</span></div>${s.transition==='dissolve'?'<i class="transition-mark"></i>':''}</div>`}).join('');
 const blocks=P?.srt?.blocks||[];
 $('#caption-track').innerHTML=blocks.map((b,i)=>`<div class="caption-block" data-caption-index="${i}" title="${E(b.text)}" style="left:${b.start_ms/1000*timelineZoom}px;width:${Math.max(2,(b.end_ms-b.start_ms)/1000*timelineZoom-1)}px" onclick="seekEditor(${b.start_ms/1000},true)">${E(b.text)}</div>`).join('')+'<span class="caption-note" style="left:8px">SRT REFERENCE · PHRASE TIMING ESTIMATED · ORIGINAL SRT UNCHANGED</span>';
 const voice=P?.voiceover, audioDuration=Number(voice?.duration)||0;
 $('#audio-track').innerHTML=voice&&audioDuration>0?`<div class="audio-clip" role="button" tabindex="0" title="${E(voice.name||'Narration')} · ${audioDuration.toFixed(3)} seconds. Click to seek." style="width:${Math.max(1,audioDuration*timelineZoom)}px" onclick="seekAudioTrack(event)" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();seekEditor(0,true)}"><canvas class="audio-waveform" aria-hidden="true"></canvas><div class="audio-label"><strong>♫ ${E(voice.name||'Narration')}</strong><span>${audioDuration.toFixed(3)}s · original narration</span></div></div>`:'<span class="audio-empty">No narration audio uploaded</span>';
 if(voice&&audioDuration>0)loadNarrationWaveform(voice);
 cacheClipNodes();
}
function drawNarrationWaveform(){
 if(P?.edit_mode==='documentary'){docDrawNarrationWaveforms();return}
 const canvas=$('#audio-track .audio-waveform');if(!canvas||!waveformPeaks)return;
 const width=Math.max(1,Math.min(8192,Math.ceil(canvas.clientWidth))),height=40;
 canvas.width=width;canvas.height=height;const ctx=canvas.getContext('2d');ctx.clearRect(0,0,width,height);ctx.fillStyle='rgba(180, 255, 227, .65)';
 for(let x=0;x<width;x++){const start=Math.floor(x*waveformPeaks.length/width),end=Math.max(start+1,Math.floor((x+1)*waveformPeaks.length/width));let peak=0;for(let i=start;i<end&&i<waveformPeaks.length;i++)peak=Math.max(peak,waveformPeaks[i]);if(peak>0){const h=Math.max(1,peak*(height-4));ctx.fillRect(x,(height-h)/2,1,h)}}
}
async function loadNarrationWaveform(voice){
 const key=voice.url;if(!key)return;if(waveformKey===key&&waveformPeaks){drawNarrationWaveform();return}if(waveformKey===key&&waveformPending)return;
 waveformKey=key;waveformPeaks=null;const task=(async()=>{let context;try{
  const response=await fetch(key,{cache:'no-store'});if(!response.ok)throw Error('Narration could not be loaded');const bytes=await response.arrayBuffer();
  context=new (window.AudioContext||window.webkitAudioContext)();const audio=await context.decodeAudioData(bytes);const channels=Array.from({length:audio.numberOfChannels},(_,i)=>audio.getChannelData(i));
  const bins=Math.min(50000,Math.max(1,Math.ceil(audio.duration*100))),peaks=new Float32Array(bins);
  for(let b=0;b<bins;b++){const start=Math.floor(b*audio.length/bins),end=Math.floor((b+1)*audio.length/bins);let peak=0;for(let i=start;i<end;i++)for(const channel of channels)peak=Math.max(peak,Math.abs(channel[i]));peaks[b]=peak}
  if(waveformKey===key){waveformPeaks=peaks;drawNarrationWaveform()}
 }catch(err){if(waveformKey===key){const canvas=$('#audio-track .audio-waveform');if(canvas)canvas.title='Waveform unavailable: '+err.message}}finally{if(context)context.close().catch(()=>{});if(waveformKey===key)waveformPending=null}})();waveformPending=task;
}
function seekAudioTrack(event){const rect=$('#audio-track').getBoundingClientRect();seekEditor((event.clientX-rect.left)/timelineZoom,true)}

/* ---- caption library ----------------------------------------------------
   Same shape as the transition library: a grid of real looks, one dialog, opened from
   the header. Picking a card saves the preset on the project, so the editor preview and
   the burned-in export are the same style rather than two similar ones. */
let captionCatalogue=null;

async function openCaptionLibrary(){
  if(!P){toast('Open a production first.');return}
  try{
    captionCatalogue=await api(`/api/captions?pid=${encodeURIComponent(P.id)}`);
  }catch(e){toast(e.message);return}
  renderCaptionLibrary();
  const dlg=$('#caption-dialog');
  if(dlg&&!dlg.open)dlg.showModal();
}
window.openCaptionLibrary=openCaptionLibrary;
window.closeCaptionLibrary=function(){const d=$('#caption-dialog');if(d?.open)d.close()};

function renderCaptionLibrary(){
  const body=$('#caption-body');if(!body||!captionCatalogue)return;
  const selected=captionLook()?.key||captionCatalogue.selected;
  body.innerHTML=captionCatalogue.presets.map(p=>`
    <button type="button" class="transition-card caption-card ${p.key===selected?'current':''}"
      onclick="chooseCaptionPreset('${p.key}')">
      <span class="caption-preview-stage"><span class="caption-preview" style="${p.css}">She called ${p.highlight?`<b style="color:${p.highlight};font-weight:inherit">911</b>`:'911'}</span></span>
      <strong>${E(p.label)}</strong><small>${E(p.detail)}</small>
      ${p.key===selected?'<em>In use</em>':''}
    </button>`).join('');
  const sizeSel=$('#caption-size'),posSel=$('#caption-position');
  if(sizeSel)sizeSel.innerHTML=(captionCatalogue.sizes||[]).map(x=>`<option value="${x.key}" ${x.key===(P?.caption_size||'medium')?'selected':''}>${E(x.label)}</option>`).join('');
  if(posSel)posSel.innerHTML=(captionCatalogue.positions||[]).map(x=>`<option value="${x.key}" ${x.key===(P?.caption_position||'bottom')?'selected':''}>${E(x.label)}</option>`).join('');
  installCaptionFonts();
  if($('#caption-burn'))$('#caption-burn').checked=P?.burn_captions===true;
  if($('#caption-preview'))$('#caption-preview').checked=!!editorCC;
}

async function chooseCaptionPreset(key){
  if(!P)return;
  try{
    P=await api(`/api/projects/${P.id}`,'PATCH',{caption_preset:key});
    applyCaptionPreset();
    renderCaptionLibrary();
    toast('Caption style saved.');
  }catch(e){toast(e.message)}
}
window.chooseCaptionPreset=chooseCaptionPreset;
async function setCaptionLayout(field,value){
  if(!P)return;
  const previous=P[field];P[field]=value;applyCaptionPreset();renderCaptionLibrary();
  try{const saved=await api(`/api/projects/${P.id}`,'PATCH',{[field]:value});P[field]=saved[field];P.updated=saved.updated;applyCaptionPreset();renderCaptionLibrary()}catch(e){P[field]=previous;applyCaptionPreset();renderCaptionLibrary();toast(e.message)}
}
window.setCaptionLayout=setCaptionLayout;

// Paint the preset the dialog just saved onto the live preview overlay. The export
// reads the same key from the project, so this is a preview of the real thing.
let captionFontsReady=false,captionLoading=null;
function loadCaptionLibraryQuietly(){
 if(captionCatalogue||captionLoading||!P)return;
 captionLoading=api(`/api/captions?pid=${encodeURIComponent(P.id)}`).then(c=>{captionCatalogue=c;captionMeasureKey='';applyCaptionPreset()}).catch(()=>{}).finally(()=>{captionLoading=null});
}
function installCaptionFonts(){
 if(captionFontsReady||!captionCatalogue?.fonts)return;captionFontsReady=true;
 const css=captionCatalogue.fonts.map(f=>`@font-face{font-family:'${f.family}';src:url('${f.url}');font-display:swap}`).join('');
 const tag=document.createElement('style');tag.id='caption-fonts';tag.textContent=css;document.head.appendChild(tag);
 if(document.fonts?.ready)document.fonts.ready.then(()=>{captionMeasureKey=''});
}
// Paint the saved caption look onto the live preview. The export reads the same
// project settings, so this is a preview of the real thing.
function applyCaptionPreset(){
 const overlay=$('#editor-captions'),textNode=$('#editor-caption-text');if(!overlay||!textNode)return;
 if(!captionCatalogue){loadCaptionLibraryQuietly();return}
 installCaptionFonts();
 const look=captionLook();
 const pos=(captionCatalogue.positions||[]).find(x=>x.key===(P?.caption_position||'bottom'))||{css:''};
 overlay.setAttribute('style','left:4%;right:4%;line-height:1.35;font-size:inherit;text-shadow:none;'+pos.css);
 textNode.setAttribute('style',(look?.css||'')+'display:inline-block;max-width:100%;white-space:nowrap;');
 captionMeasureKey='';
}

async function setCaptionBurn(on){
  if(!P)return;
  try{
    P=await api(`/api/projects/${P.id}`,'PATCH',{burn_captions:!!on});
    renderCaptionLibrary();renderProgram();
    toast(on?'Captions will be burned into the export.':'Captions will not be burned in.');
  }catch(e){toast(e.message)}
}
window.setCaptionBurn=setCaptionBurn;

function setCaptionPreview(on){setEditorCaptions(!!on);renderCaptionLibrary()}
window.setCaptionPreview=setCaptionPreview;

/* ---- transition library --------------------------------------------------
   One dialog, opened either from the transport bar (which acts on the scene in the
   inspector) or from the inspector's own transition row. It is the only place a
   transition is chosen, so there is one list to learn rather than a dropdown plus a
   grid that can disagree. The catalogue comes from the server, which means a card can
   never offer a transition the renderer cannot produce. */
let transitionCatalogue=null,transitionTarget=null;

async function loadTransitionCatalogue(){
  if(transitionCatalogue)return transitionCatalogue;
  try{transitionCatalogue=await api('/api/transitions')}catch(e){toast(e.message)}
  return transitionCatalogue;
}

function transitionLabel(key){
  const c=(transitionCatalogue?.transitions||[]).find(t=>t.key===key);return c?c.label:(key||'Cut');
}

async function openTransitionLibrary(sceneId){
  await loadTransitionCatalogue();
  if(!transitionCatalogue)return;
  if(!P){toast('Open a production first.');return}
  transitionTarget=sceneId||scenes()[sceneIndex]?.id||null;
  const dlg=$('#transition-dialog');
  renderTransitionLibrary();
  if(dlg&&!dlg.open)dlg.showModal();
}

window.openTransitionLibrary=openTransitionLibrary;
window.closeTransitionLibrary=function(){const d=$('#transition-dialog');if(d?.open)d.close()};

function renderTransitionLibrary(){
  const body=$('#transition-body');if(!body)return;
  if($('#transition-duration'))$('#transition-duration').value=transitionDuration;
  if($('#transition-intensity'))$('#transition-intensity').value=transitionIntensity;
  const scene=P?.scenes?.find(s=>s.id===transitionTarget);
  const current=scene?.transition||'cut';
  const index=P?.scenes?.findIndex(s=>s.id===transitionTarget);
  const lastIndex=(P?.scenes?.length||1)-1;
  const isLast=index===lastIndex;
  const isClean=P?.transition_policy==='clean_cuts_only';
  const target=$('#transition-target');
  if(target){
    if(!scene)target.textContent='Select a scene in the inspector, then choose its exit transition.';
    else if(isLast)target.textContent=`Scene ${index+1} is the last scene. There is nothing after it to blend into.`;
    else target.textContent=`Scene ${index+1} of ${P.scenes.length} · exit into scene ${index+2}`;
  }
  const grid=transitionCatalogue.transitions.map(t=>{
    const disabled=isClean&&t.overlaps;
    const isCurrent=t.key===current;
    return `<button type="button" class="transition-card ${isCurrent?'current':''} ${disabled?'disabled':''}"
      ${disabled?'disabled':''} onclick="chooseTransition('${t.key}')"
      ${disabled?'title="This production uses clean cuts only. Allow transitions first."':''}>
      <span class="transition-preview t-${t.key}"><span></span></span>
      <strong>${E(t.label)}</strong><small>${E(t.detail)}</small>
      ${isCurrent?'<em>In use</em>':''}
    </button>`;
  }).join('');
  body.innerHTML=grid;
}

async function chooseTransition(key,silent){
 if(!P||!transitionTarget)return;
 const scene=P.scenes.find(s=>s.id===transitionTarget);if(!scene)return;
 // Keep library selection responsive; the same autosave path drives the inspector.
 quickSceneEdit({dataset:{sceneId:scene.id}},'transition',key);
 renderTransitionLibrary();renderExport();
 if(!silent)toast(`${transitionLabel(key)} selected. The boundary saves automatically.`);
}
window.chooseTransition=chooseTransition;

let transitionDuration='standard',transitionIntensity='balanced';

function setTransitionDuration(key){
  transitionDuration=key;
  const scene=P?.scenes?.find(s=>s.id===transitionTarget);
  if(scene&&scene.transition&&scene.transition!=='cut')chooseTransition(scene.transition,true);
}
window.setTransitionDuration=setTransitionDuration;

function setTransitionIntensity(key){transitionIntensity=key}
window.setTransitionIntensity=setTransitionIntensity;

async function autoSuggestTransitions(){
  if(!P)return;
  // Documentary timelines use the story-aware director on real picture cuts only.
  if(P.edit_mode==='documentary'&&typeof window.docTrAuto==='function'){return window.docTrAuto()}
  try{
    const data=await api(`/api/projects/${P.id}/transition-suggest`,'POST',
      {intensity:transitionIntensity,duration:transitionDuration});
    P=data.project;
    renderInspector();renderProject?.();renderTransitionLibrary();closeTransitionLibrary();
    const parts=Object.entries(data.summary||{}).map(([k,v])=>`${v} ${transitionLabel(k)}`);
    toast(data.changed?`${data.changed} boundaries changed${parts.length?': '+parts.join(', '):''}.`:'Every boundary already fit its scene.');
  }catch(e){toast(e.message)}
}
window.autoSuggestTransitions=autoSuggestTransitions;

function renderInspector(force=false){const s=scenes()[sceneIndex];
 if(P?.edit_mode==='documentary'&&editorPlaying&&!force){$('#shot-number').textContent=s?(s.plan_row?.shot_id||'SRT '+s.srt_blocks.join('–')):'—';return}
 // Nothing here explains itself. A field says what it holds, a notice says what is
 // wrong, and everything else was removed: the inspector is a control surface, not a
 // manual. Where a sentence used to justify a value, the value now stands alone.
 if(!s){const missing=(P?.source_match_report||[]).filter(x=>!['matched','selected'].includes(x.status));$('#inspector-content').innerHTML=missing.length?`<div class="inspector-group"><label>Unlinked source files</label><p>${missing.map(x=>E(x.source_file)).join(', ')}</p><button type="button" onclick="manage('brief')">Resolve filenames</button></div>`:P?.srt?`<div class="inspector-group"><label>No picture beats</label><button type="button" onclick="manage('brief')">Open setup</button></div>` :'<div class="inspector-group"><label>No production open</label></div>';$('#inspector-content').insertAdjacentHTML('afterbegin',typeof brandingPanelHTML==='function'?brandingPanelHTML():'');return}
 const a=assets().find(a=>a.id===s.asset_id);
 const chosen=selectedScenes(),scaleTarget=chosen.find(x=>x.id===s.id)||chosen[0],scaleValue=scaleTarget?effectivePictureScale(scaleTarget):100,scaleMixed=new Set(chosen.map(effectivePictureScale)).size>1;
 const flow=s.picture_flow,cut=s.cut_sync;
 const flowLabel={already_inside_one_shot:'inside one shot',continuous_with_previous:'runs on from previous',continued_running_take:'continued take',slid_inside_a_shot:'conformed',slid_far_inside_a_shot:'moved far',repeats_recent_footage:'repeats footage',jump_cut_within_shot:'jump cut',no_single_shot_fits:'no shot fits',not_decoded:'not decoded'};
 const cutLabel={in_a_breath:'in a breath',on_a_block_boundary:'on a line break',over_speech:'over speech',between_blocks:'between blocks'};
 // Three terse fact rows. No prose, no tooltips that restate the label.
 const meta=`<div class="mini-meta"><span>SRT ${s.srt_blocks.join('–')}</span><span>${((s.frame_out-s.frame_in)/30).toFixed(3)}s</span></div><div class="mini-meta"><span>Timeline</span><span>${(s.frame_in/30).toFixed(3)} → ${(s.frame_out/30).toFixed(3)}s</span></div>${flow?`<div class="mini-meta"><span>Flow</span><span>${E(flowLabel[flow.status]||flow.status)}${flow.shot?` · ${flow.shot[0]}–${flow.shot[1]}s`:''}</span></div>`:''}${cut?`<div class="mini-meta"><span>Cut</span><span>${E(cutLabel[cut.quality]||cut.quality)}${cut.moved_from_s!=null?` · ${cut.moved_from_s}s`:''}</span></div>`:''}`;
 const transitionKey=s.transition||'cut';
 const transitionOptions=(transitionCatalogue?.transitions||[{key:'cut',label:'Cut'},{key:'fade',label:'Cross Fade'},{key:'dissolve',label:'Dissolve'}]).map(t=>[t.key,t.label]);
 $('#inspector-content').innerHTML=`<div class="slot-scale-control"><label for="slot-scale-range">Frame scale · ${chosen.length} selected${scaleMixed?' (mixed)':''}</label>
 <div class="slot-scale-row"><input id="slot-scale-range" type="range" min="100" max="200" value="${scaleValue}" ${chosen.length?'':'disabled'} oninput="previewSlotScale(this.value)" onchange="saveSlotScale(this.value)"><input id="slot-scale-number" type="number" min="100" max="200" value="${scaleValue}" ${chosen.length?'':'disabled'} oninput="previewSlotScale(this.value)" onchange="saveSlotScale(this.value)"><span>%</span></div>
 <button type="button" onclick="saveSlotScale(null)" ${!chosen.some(x=>x.picture_scale!=null)?'disabled':''}>Reset scale</button></div>
 ${docVolumeHTML()}
 <div class="inspector-group compact-scene-control"><label>Picture</label><select aria-label="Picture source" ${P.script_moving_only?'disabled title="Source is locked by production script; replace the source file in Setup"':''} data-scene-id="${s.id}" onchange="quickSceneEdit(this,'asset_id',this.value||null)">${options([['','Choose media'],...P.assets.filter(a=>!P.script_moving_only||a.kind==='video'||(s.plan_row?.uploaded_photo&&a.kind==='image'&&!a.derived_from)).map(a=>[a.id,(a.verified?'✓ ':'')+(a.original_name||a.name)])],s.asset_id||'')}</select></div>
 ${sourceTimingHTML(s,a)}
 ${s.plan_row?.uploaded_photo?'':`<label class="compact-scene-control">Source start (seconds)<input type="number" min="0" step=".001" value="${Number(s.in_s)||0}" ${P.script_moving_only?'disabled title="Timing is locked by production script"':''} data-scene-id="${s.id}" onchange="quickSceneEdit(this,'in_s',Number(this.value))"></label>`}
 <label class="compact-scene-control">Transition out<div class="transition-row"><select data-scene-id="${s.id}" onchange="quickSceneEdit(this,'transition',this.value)">${options(transitionOptions,transitionKey)}</select><button type="button" onclick="openTransitionLibrary('${s.id}')">More</button></div></label>
 <label class="check-label compact-scene-control"><input type="checkbox" data-scene-id="${s.id}" onchange="quickSceneEdit(this,'approved',this.checked)" ${s.approved?'checked':''}>Picture reviewed / approved</label>
 <p id="scene-save-status" class="scene-save-status" role="status" aria-live="polite">Changes save automatically · No rebuild needed</p>`;
 if(typeof brandingPanelHTML==='function')$('#inspector-content').insertAdjacentHTML('beforeend',brandingPanelHTML());
 if(!transitionCatalogue){loadTransitionCatalogue().then(()=>{if(P?.id&& !editorPlaying)renderInspector()})}

}
window.storyroomTimelineSaving=0;
// Small, independent timeline edits are optimistic and autosaved. No full page
// repaint, redraw of every thumbnail, or rebuild of audio/source Beat plans.
let quickSceneSaveChain=Promise.resolve();
function quickSceneStatus(message){const el=$('#scene-save-status');if(el)el.textContent=message}
function quickSceneEdit(node,field,value){
 if(!P)return;
 const id=P.id, sid=node.dataset.sceneId,scene=P.scenes.find(s=>s.id===sid);
 if(!scene)return;
 const before=scene[field];if(before===value)return;
 scene[field]=value;
 if((field==='asset_id'||field==='in_s')&&scene.approved){scene.approved=false;const check=document.querySelector('#inspector-content input[type=checkbox][data-scene-id]');if(check)check.checked=false}
 // A changed clip is a new picture, not permission to select another source.
 if(field==='asset_id'||field==='in_s'){
  if(P.edit_mode==='documentary'){window.docTimelineData&&(window.docTimelineData.detail='Picture changed; refreshing the review source.');}
  else{sourceScene='';renderProgram()}
 }
 if(field==='transition'){
  // The stored boundary marker/choice updates before the network request.
  const mark=document.querySelector(`.shot-clip[data-scene="${P.scenes.indexOf(scene)}"]`);
  if(mark){mark.dataset.transition=value;mark.classList.toggle('has-transition',value!=='cut')}
 }
 quickSceneStatus('Saving…');renderExport();window.storyroomTimelineSaving++;
 const payload={[field]:value};
 if(field==='transition')payload.transition_handle_frames=value==='cut'?0:15;
 quickSceneSaveChain=quickSceneSaveChain.catch(()=>{}).then(async()=>{
  const result=await api(`/api/projects/${id}/scenes/${sid}?compact=1`,'PATCH',payload);
  if(P?.id!==id)return;
  P.updated=result.updated;
  // Do not replace a newer pending value with an earlier request's response.
  if(scene[field]===value)Object.assign(scene,result.scene);
  quickSceneStatus('Saved · No rebuild needed');renderExport();
  if((field==='asset_id'||field==='in_s')&&typeof reloadDocTimeline==='function'&&P.edit_mode==='documentary'){
   // Re-read the playable scene map only; never invoke the Beat builder.
   reloadDocTimeline();
  }
 }).catch(e=>{
  if(P?.id===id){if(scene[field]===value)scene[field]=before;quickSceneStatus('Not saved: '+e.message);toast(e.message)}
 }).finally(()=>{window.storyroomTimelineSaving=Math.max(0,window.storyroomTimelineSaving-1)});
}
window.quickSceneEdit=quickSceneEdit;

function sourceTimingHTML(s,a){if(!a)return '';if(a.kind==='image'&&!a.derived_from)return `<div class="inspector-group"><label>Still · ${((s.frame_out-s.frame_in)/30).toFixed(3)}s</label><p>${E(a.original_name||a.name)}</p><p id="source-clock" class="small"></p></div>`;if(s.automatic_match)return `<div class="inspector-group"><label>Source</label><p>${E(a.original_name||a.name)} · SRT ${E(s.automatic_match.srt_block)}</p><p>${Number(s.in_s).toFixed(3)}s → ${(Number(s.in_s)+(s.frame_out-s.frame_in)/30).toFixed(3)}s</p><p id="source-clock" class="small"></p></div>`;const derived=a.derived_from,planned=s.plan_row;const actual=derived?derived.requested_time_ms/1000:Number(s.in_s);
 // The script's IN/OUT is only worth a line when it disagrees with what is saved.
 // On a conformed beat the two are identical, so printing both just invited the
 // reader to hunt for a difference that is not there.
 const plannedIn=planned?(planned.extracted_frame_ms??planned.source_in_ms)/1000:null;
 const plannedOut=planned?.source_out_ms!=null?planned.source_out_ms/1000:null;
 const moved=plannedIn!=null&&(Math.abs(plannedIn-actual)>0.0005||(plannedOut!=null&&Math.abs(plannedOut-(actual+(s.frame_out-s.frame_in)/30))>0.0005));
 return `<div class="inspector-group"><label>Source</label><p>${E(derived?.source_file||a.original_name||a.name)}</p><p>${actual.toFixed(3)}s${a.kind==='video'?' → '+(actual+(s.frame_out-s.frame_in)/30).toFixed(3)+'s':''}</p>${moved?`<p class="small">Script: ${plannedIn.toFixed(3)}s${plannedOut!=null?' → '+plannedOut.toFixed(3)+'s':''}</p>`:''}<p id="source-clock" class="small"></p></div>`}



// ---- Planning aids: shot index, feasibility, block-map template -----------------
// Everything here reads decoded facts. Nothing places a picture by itself.




// The shot inspector edits one shot, so it no longer carries a block of
// project-wide planning links. Those live in Setup now, next to the material
// they inspect. Kept as a function because the inspector still calls it.
// Three levels, in the order they sit in the mix: narration, then the audio
// carried by the footage, then the bed. They are saved with the project and
// applied on the next export, so a change never re-renders behind your back.
function docVolumeHTML(){
  if(!P || P.edit_mode!=='documentary' || !P.documentary_beat_review) return '';
  const v = docTrackVolume;
  // Labels only. Each fader says what it controls and nothing else.
  const mix = (label, key, value, max) => `<div class="doc-volume-row"><label for="doc-vol-${key}">${label}</label><input id="doc-vol-${key}" type="range" min="0" max="${max}" step="1" value="${Math.round(value)}" aria-label="${label} level percent" oninput="previewDocVolume('${key}',this.value)" onchange="saveDocVolume('${key}',this.value)"><input id="doc-vol-${key}-n" type="number" min="0" max="${max}" step="1" value="${Math.round(value)}" aria-label="${label} level percent" oninput="previewDocVolume('${key}',this.value)" onchange="saveDocVolume('${key}',this.value)"><span>%</span></div>`;
  return `<div class="doc-volume-control"><label>Audio</label>
  ${mix('Narration', 'narration', v.narration, 150)}
  ${mix('Clip audio', 'clip', v.clip, 150)}
  ${mix('Music', 'music', v.music, 100)}</div>`;
}

// The review preview is one already-mixed file: narration and the selected sound
// bites are level-matched and concatenated before the browser ever sees them, so
// there is no per-track node to turn down. Narration and clip levels therefore
// share that stream, and the quieter of the two is what can honestly be applied
// to it: raising one alone would lift the other with it. Music has its own layer
// and is unaffected. Nothing here touches the exported mix until the project is
// saved and rendered again.
function previewDocVolume(key, raw){
  const value = Math.max(0, Math.min(150, Number(raw) || 0));
  if(key==='music') docTrackVolume.music = value;
  else docTrackVolume[key] = value;
  const sync = document.querySelectorAll(`#doc-vol-${key}, #doc-vol-${key}-n`);
  sync.forEach(node => { if(Number(node.value)!==Math.round(value)) node.value = Math.round(value); });
  window.docApplyPreviewVolumes?.();
}

async function saveDocVolume(key, raw){
  if(!P) return;
  const value = Math.max(0, key==='music' ? Math.min(100, Number(raw) || 0) : Math.min(150, Number(raw) || 0));
  previewDocVolume(key, value);
  // Send only the fader that moved. Sending all three overwrote the music level
  // with the last value that happened to be in memory, which is how moving the
  // narration fader could quietly reset the bed.
  const keyName = {narration:'narration_percent', clip:'clip_percent', music:'volume_percent'}[key];
  const body = {[keyName]: key==='music' ? Math.max(1, Math.round(value)) : Math.round(value)};
  try{
    // The reply is the audio settings, not the production. Storing it as the project
    // (as this used to) lost the production's id, and every later action failed.
    const id = P.id;
    const state = await api(`/api/projects/${id}/documentary-audio-levels`, 'PATCH', body);
    if(P?.id !== id) return;
    P.documentary_audio_levels = {...(P.documentary_audio_levels||{}), narration_percent: state.narration_percent, clip_percent: state.clip_percent};
    P.documentary_music = {...(P.documentary_music||{}), volume_percent: state.volume_percent};
    if(typeof docMusic === 'object') Object.assign(docMusic, state);
    toast(`Saved. ${key==='music'?'Music':'Narration and clip'} level is applied on the next export.`);
  }catch(e){ toast(e.message); }
}


async function downloadMapTemplate(){
  if(!P) return;
  try{
    const r = await fetch(`/api/projects/${P.id}/block-map-template`);
    if(!r.ok){ const d = await r.json().catch(()=>({})); throw Error(d.error || 'The template could not be built.'); }
    const blob = await r.blob(); const url = URL.createObjectURL(blob);
    const a = document.createElement('a'); a.href = url; a.download = 'block-map-template.csv'; a.click();
    URL.revokeObjectURL(url);
    toast('Template downloaded. Clocks are filled; picture columns are blank on purpose.');
  }catch(e){ toast(e.message); }
}



// ---- Bulk approval and frame QC ----------------------------------------------
async function approveReadyScenes(){
  if(!P || !leave()) return;
  const unapproved = P.scenes.filter(s => !s.approved).length;
  if(!unapproved){ toast('Every picture beat is already approved.'); return; }
  if(!confirm(`Approve every picture beat that passes the same checks export readiness uses? ${unapproved} beat(s) are not approved. A beat with any blocking item is left unapproved and listed with its reason. This does not inspect or verify picture content or identity. You are attesting that you reviewed the pictures; this is not rights clearance.`)) return;
  try{
    const d = await api(`/api/projects/${P.id}/scenes/approve`, 'POST', {attested: true, scope: 'ready'});
    P = d; renderProject(); await list();
    const done = d.bulk_approval?.approved?.length || 0, skipped = d.bulk_approval?.skipped || [];
    if(skipped.length){
      const first = skipped[0];
      toast(`${done} beat(s) approved. ${skipped.length} left unapproved — Scene ${first.scene}: ${first.reasons[0]}`);
    } else toast(`${done} picture beat(s) approved. All others were already approved.`);
  }catch(e){ toast(e.message); }
}

let qcCache = {id: null, data: null};
let qcRequest = 0;
function qcPlayRange(id,start,end){
  const media=document.getElementById(id);if(!media)return;
  const play=()=>{media.currentTime=start;media.ontimeupdate=()=>{if(media.currentTime>=end){media.pause();media.ontimeupdate=null}};media.play().catch(()=>toast('Press play to start the selected interval.'))};
  if(media.readyState>=1)play();else media.addEventListener('loadedmetadata',play,{once:true});
}
async function openFrameQC(shot){
  if(!P)return;
  const n=Math.max(1,Math.min(Number(shot)||1,scenes().length));if(!scenes().length){toast('Build the storyboard first.');return}
  const request=++qcRequest, projectId=P.id;
  $('#plan-title').textContent='Shot-by-shot frame QC';
  $('#plan-body').innerHTML='<p class="small">Loading shot '+n+' and decoding its source frames…</p>';
  if(!$('#plan-dialog').open)$('#plan-dialog').showModal();
  try{
    const d=await api(`/api/projects/${projectId}/frame-qc?format=json&per_sheet=1&sheet=${n}`);
    if(request!==qcRequest||P?.id!==projectId)return;
    qcCache={id:projectId,data:d};
    const scene=scenes()[n-1], row=scene.plan_row||{}, asset=assets().find(a=>a.id===scene.asset_id), beat=d.beats[0];
    const blocks=[...new Set(row.srt_blocks||scene.srt_blocks||[])], srt=(P.srt?.blocks||[]).filter(b=>blocks.includes(b.number)).map(b=>b.text).join('\n');
    const start=Number(scene.in_s)||0,end=row.strict_production&&Number.isFinite(Number(row.source_out_ms))?Number(row.source_out_ms)/1000:start+(scene.frame_out-scene.frame_in)/30;
    const timeIn=scene.frame_in/30,timeOut=scene.frame_out/30;
    const note=row.continuity??row.match_reason??'';
    const caption=row.plain_cue&&!Object.prototype.hasOwnProperty.call(row,'continuity')?'Not specified separately in this older script':(row.required_caption||'None');
    $('#plan-body').innerHTML=`<div class="qc-review">
      <div class="qc-navigation"><button type="button" onclick="openFrameQC(${n-1})" ${n<=1?'disabled':''}>← Previous shot</button><label>Shot <select aria-label="Choose shot" onchange="openFrameQC(this.value)">${scenes().map((s,i)=>`<option value="${i+1}" ${i+1===n?'selected':''}>${i+1} · ${E(qcShotLabel(s,i))}</option>`).join('')}</select> of ${scenes().length}</label><button type="button" onclick="openFrameQC(${n+1})" ${n>=scenes().length?'disabled':''}>Next shot →</button></div>
      <h3>Shot ${n} · ${E(qcShotLabel(scene,n-1))}</h3>
      <p><strong>Original SRT narration:</strong> ${E(srt||scene.narration||'Not available')}</p>
      <p><strong>Script narration:</strong> ${E(row.script_narration||'Not specified')}</p>
      <p><strong>Visual direction:</strong> ${E(row.visible_content||'Not specified')}</p>
      <p><strong>Continuity note:</strong> ${E(note||'None')}</p><p><strong>On-screen caption:</strong> ${E(caption)}</p>
      <p><strong>Assigned source:</strong> ${E(asset?.original_name||asset?.name||'Unassigned')} · <strong>Script source:</strong> ${E(row.source_file||'Not specified')}<br><strong>Source interval:</strong> ${E(mapClock(start*1000))} → ${E(mapClock(end*1000))} (OUT exclusive) · <strong>Timeline:</strong> ${E(mapClock(timeIn*1000))} → ${E(mapClock(timeOut*1000))}</p>
      <h4>Boundary frames</h4><p>From left: 2 seconds before IN, IN, midpoint, last frame before OUT, and 2 seconds after OUT. Unavailable frames are marked. Review only: these extracted frames are never placed in the edit or exported as picture assets.</p>
      <div class="qc-image-scroll"><img src="${d.url}" alt="Five source inspection frames for shot ${n}"></div><p><a href="${d.url}" target="_blank" rel="noopener">Open full-size QC image</a></p>
      ${beat.samples.some(x=>!x.decoded)?'<p class="notice warn">One or more inspection frames are unavailable; a boundary may be outside the source or the frame could not be decoded.</p>':''}
      <h4>Play the full shot</h4>${asset?.kind==='video'?`<video id="qc-video" controls muted preload="metadata" src="${E(asset.url)}"></video><p><button type="button" onclick="qcPlayRange('qc-video',${start},${end})">Play selected source interval</button> Source audio is muted; use the controls to inspect nearby context.</p>`:asset?.kind==='image'?`<img class="qc-photo" src="${E(asset.url)}" alt="Assigned original photograph"><p>Original uploaded photograph. Verify who or what it shows.</p>`:'<p>No source is assigned to this shot.</p>'}
      ${P.voiceover?.url?`<h4>Listen to narration for this shot</h4><audio id="qc-audio" controls preload="metadata" src="${E(P.voiceover.url)}"></audio><p><button type="button" onclick="qcPlayRange('qc-audio',${timeIn},${timeOut})">Play shot narration</button></p>`:''}
      <div class="notice"><strong>Review checklist</strong><p>1. Inspect the boundary frames for unwanted cuts. 2. Play the whole interval against the narration and visual direction. 3. Independently confirm identities, source and date. 4. Correct unsuitable sources or ranges in the shot inspector. 5. Record any reuse decision separately.</p></div>
      <div class="qc-navigation"><button type="button" onclick="openFrameQC(${n-1})" ${n<=1?'disabled':''}>← Previous shot</button><button type="button" onclick="openFrameQC(${n+1})" ${n>=scenes().length?'disabled':''}>Next shot →</button></div>
    </div>`;
    $('#plan-body').scrollTop=0;
  }catch(e){if(request===qcRequest)$('#plan-body').innerHTML=`<div class="notice">${E(e.message)}</div>`;}
}


// Rebuild only the block range around the current beat, keeping approvals elsewhere.
// Documentary exports use a separate, guarded readiness check, not review-draft validation.
let documentaryCheck={key:null,state:'idle',result:null,error:null};
function ensureDocumentaryCheck(){
 const key=P?`${P.id}:${P.updated}`:null;if(!key||documentaryCheck.key===key)return documentaryCheck;
 const id=P.id,version=P.updated,state={key,state:'checking',result:null,error:null};documentaryCheck=state;
 async function poll(){try{const result=await api(`/api/projects/${id}/documentary-export-readiness`);if(documentaryCheck!==state||P?.id!==id||P?.updated!==version)return;state.result=result;state.state=result.status==='checking'?'checking':result.status==='ready'?'ready':'blocked';renderChecks();if(state.state==='checking')setTimeout(poll,1500);else setTimeout(()=>{if(documentaryCheck===state&&P?.id===id&&P?.updated===version){state.state='checking';state.result=null;renderChecks();poll()}},15000)}catch(e){if(documentaryCheck!==state||P?.id!==id||P?.updated!==version)return;state.state='error';state.error=e.message;renderChecks()}}
 poll();return state;
}
function retryDocumentaryCheck(){documentaryCheck.key=null;renderChecks()}
function renderDocumentaryChecks(){
 const state=ensureDocumentaryCheck(),errors=state.result?.errors||[],groups=typeof docCueGroups==='function'?docCueGroups():null;
 // Export-stage items are grouped so the count is meaningful: approvals and reuse
 // decisions are expected now, while timing or source problems are real blockers.
 const pending=errors.filter(x=>/editorial approval is pending|record explicit reuse-rights approval/i.test(x));
 const other=errors.filter(x=>!pending.includes(x));
 const summary=state.state==='checking'?'Checking documentary…':state.state==='error'?'Check unavailable':other.length?`${other.length} item${other.length===1?'':'s'} to review`:pending.length?`${pending.length} approval${pending.length===1?'':'s'} left`:state.state==='ready'?'Checks passed':'Export blocked';
 $('#validation-summary').textContent=summary;$('#validation-summary').style.color=state.state==='ready'?'var(--green)':'var(--amber)';
 $('#validation-list').innerHTML=`<div class="validation-item">${groups?`${groups.length} cue shots · `:''}${scenes().length} picture slots · original narration and SRT unchanged.</div>${other.slice(0,3).map(x=>`<div class="validation-item warning">△ ${E(x)}</div>`).join('')}${other.length>3?`<div class="validation-item">${other.length-3} more items under Review / export checks.</div>`:''}${pending.length?`<div class="validation-item">${pending.length} scene approval${pending.length===1?'':'s'} and reuse-rights decisions remain before export; the timeline is ready to review.</div>`:''}${state.state==='error'?`<div class="validation-item warning">△ ${E(state.error)} <button type="button" onclick="retryDocumentaryCheck()">Retry</button></div>`:''}${state.state==='ready'?'<div class="validation-item ok">✓ Source, timing and approval checks passed. Content, identity and rights still require your review.</div>':''}`;
}
function renderChecks(){if(P?.edit_mode==='documentary'&&P?.documentary_beat_review){renderDocumentaryChecks();return}const ss=scenes(),errors=P?.validation?.errors||[],unresolved=P?.script_application?.issues||[];$('#validation-summary').textContent=!P?'No production selected':errors.length?`${errors.length} item${errors.length===1?'':'s'} to review`:(P?.picture_policy==='clips_only'?'Ready · automatic checks passed':'Ready for review export');$('#validation-summary').style.color=errors.length?'var(--amber)':'var(--green)';$('#validation-list').innerHTML=P?`<div class="validation-item ok">✓ ${ss.length} picture beats · original narration / SRT timing preserved.</div>${unresolved.length?`<div class="validation-item warning">△ ${unresolved.length} unassigned script shots. Select a gap to see its required source and range.</div>`:''}${errors.slice(0,3).map(x=>`<div class="validation-item warning">△ ${E(x)}</div>`).join('')}${errors.length>3?`<div class="validation-item">${errors.length-3} more items under Review / export checks.</div>`:''}${!editorMaster&&ss.length?(P?.review_only_draft?'<div class="validation-item">Review-only timeline. Rendering remains blocked until outstanding checks are resolved.</div>':''):''}`:'<div class="validation-item">Create a new production, then import the voiceover, SRT and source MP4s.</div>'}
// One place reads the render state, so the button and its click handler can never
// disagree about what the button says.
function renderButtonState(){
 const r=P?.render||{},doc=P?.edit_mode==='documentary',beat=doc&&!!P?.documentary_beat_review;
 const busy=['running','queued'].includes(r.status);
 return {r,doc,beat,busy,
  downloading:!busy&&!!r.url&&isCurrentRender(r),
  failed:!busy&&r.status==='error',
  stale:!busy&&!!r.output&&!isCurrentRender(r)};
}
function renderExport(){
 const s=renderButtonState();
 const dialog=$('#render-dialog');
 if(dialog?.open)renderRenderPage();
 const button=$('#render-button');
 if(!button)return;
 // The button is never disabled by a render. During an export it is the only control
 // visible from anywhere in the editor that reports progress, and when the export
 // lands it turns into the download -- so "is it finished?" is answerable at a glance
 // without opening the export page first. Only an empty workspace disables it, because
 // there is genuinely nothing to export.
 button.disabled=!P;
 button.dataset.mode='page';
 if(s.busy){
  button.textContent=`Rendering ${Math.round(Number(s.r.progress)||0)}%`;
  button.dataset.mode='progress';
  button.title='Open the export page to follow this export or cancel it';
 }else if(s.downloading){
  button.textContent='⬇ Download MP4';
  button.dataset.mode='download';
  button.title='Download the finished MP4';
 }else if(s.failed){
  button.textContent='Render stopped';
  button.dataset.mode='error';
  button.title='The last export stopped. Open the export page for the reason.';
 }else if(s.stale){
  button.textContent='Render again';
  button.title='The timeline changed since the last MP4. Render again to include it.';
 }else{
  button.textContent='Render MP4';
  button.title='Open the export page and render a clean MP4';
 }
}
// Downloading from the top bar does not replace the export page: the page is where a
// resolution is chosen and a render started, so the toast names the way back to it
// rather than leaving the download button as a dead end.
function renderButtonClick(){
 if(!P){toast('Open or create a production first.');return}
 const s=renderButtonState();
 if(s.downloading&&s.r.url){
  const link=document.createElement('a');
  link.href=s.r.url+(s.r.url.includes('?')?'&':'?')+'download=1';
  link.download='';
  document.body.appendChild(link);link.click();link.remove();
  toast('Download started. Setup → Review & delivery can render again.');
  return;
 }
 // A Beat documentary renders straight away; while it runs, the button opens the
 // export page to follow its progress or cancel.
 // Always let the user select 1080p, 2K or 4K before a render starts.
 openRenderPage();
}
function openRenderPage(){
 if(!P)return;pauseEditor();
 const dialog=$('#render-dialog');renderRenderPage();if(!dialog.open)dialog.showModal();
}
function closeRenderPage(){const dialog=$('#render-dialog');if(dialog?.open)dialog.close()}
function renderRenderPage(){
 const box=$('#render-page-body');if(!box)return;
 const r=P?.render||{},doc=P?.edit_mode==='documentary',busy=['running','queued'].includes(r.status);
 const ready=!busy&&(doc?!!P?.documentary_beat_review:!!scenes().length)&&!pictureScaleSaving;
 const stage=r.output&&!isCurrentRender(r)&&!busy?'New edits — render again':r.stage||'Not rendered yet';
 const detail=r.error?'The last export needs attention. Details are below.':r.detail||(doc?'Narration and sound bites are mixed; the fade is omitted.':'Clean MP4 with the combined tracks.');
 const actions=doc
  ?`<button type="button" class="button primary" ${ready?'':'disabled'} onclick="renderFromEditor()">Render documentary MP4</button>`
  :`<button type="button" class="button primary" ${ready?'':'disabled'} onclick="renderFromEditor()">Render review MP4</button><button type="button" class="button" ${!P.validation?.can_export||busy?'disabled':''} onclick="startExport(true)">Render final MP4</button>`;
 const previous=r.url&&!isCurrentRender(r)?`<div class="notice warn"><strong>Previous MP4 — not current</strong><p>This file does not include your latest edits. Render again to include them.</p><video controls class="reference-video" src="${r.url}"></video><a class="download" href="${r.url}?download=1">↓ Download previous MP4</a></div>`:'';
 const current=r.url&&isCurrentRender(r)?`<div class="notice"><strong>Current MP4</strong><video controls class="reference-video" src="${r.url}"></video><a class="download" href="${r.url}?download=1">↓ Download current MP4</a> <a class="download" href="${r.url.replace(/\.mp4$/,'.srt')}?download=1">↓ Separate SRT</a></div>`:'';
 box.innerHTML=`
 <section class="card"><h3>Resolution</h3>${resolutionHTML()}</section>
 <section class="card"><h3>Subtitles</h3>${doc?`
   <label class="check-label"><input id="burn-srt-subtitles" type="checkbox" ${burnSrtOnExport?'checked':''} onchange="setBurnSrtOnExport(this.checked)"> Burn SRT subtitles permanently into the MP4</label>
   <p class="small">Off by default. Your original SRT remains unchanged and can still be downloaded separately. Use the CC button below the monitor to preview captions without burning them into the video.</p>
   <details class="subtitles-advanced"><summary>Optional on-screen script labels</summary><label class="check-label"><input id="burn-on-screen-captions" type="checkbox" ${P?.burn_captions===true?'checked':''} onchange="setBurnCaptions(this.checked)"> Burn explicit production-script on-screen labels</label><p class="small">Off by default; avoid showing duplicate narration subtitles. This option is for intentional lower thirds and source labels, not automatically transcribing every sentence.</p></details>`:
  `<label class="check-label"><input type="checkbox" id="burn-script-captions" ${exportScriptCaptions?'checked':''} onchange="setScriptCaptionExport(this.checked)"> Burn explicitly authored on-screen labels</label><label class="check-label"><input id="burn-srt-subtitles" type="checkbox" ${burnSrtOnExport?'checked':''} onchange="setBurnSrtOnExport(this.checked)"> Burn SRT subtitles into MP4</label>`}</section>
 ${doc?`<section class="card"><h3>Opening and closing</h3><label class="check-label"><input id="doc-fade-enabled" type="checkbox" ${(P?.documentary_fades?.enabled!==false)?'checked':''} onchange="setDocumentaryFades({enabled:this.checked})"> Follow the production script's opening/closing fade</label><p class="small">This setting affects picture fades only; transitions between scenes are chosen in the Transitions panel.</p></section>`:''}
 <section class="card"><h3>Export status</h3><p><strong>${E(stage)}</strong></p><p class="small">${E(detail)}</p><progress max="100" value="${Number(r.progress)||0}"></progress><p class="small">${Math.round(Number(r.progress)||0)}%</p>${r.status==='error'?`<div class="notice error">Export could not finish. The production is intact.</div><details><summary>Technical details</summary><pre style="white-space:pre-wrap;word-break:break-word;font-size:10px">${E(r.error)}</pre></details>${doc?'':'<button type="button" onclick="documentaryRetry()">Retry</button>'}`:''}${busy?'<button type="button" onclick="cancelExport()">Cancel export</button>':''}${current}${previous}</section>
 <section class="card"><h3>Checks &amp; files</h3><p><button type="button" class="text-button" onclick="closeRenderPage();manage('delivery')">Open review / export checks</button></p>${doc?'<p><a class="download" href="/api/projects/'+P.id+'/coverage-summary">↓ Download coverage summary</a></p>':''}</section>
 <div class="actionbar">${actions}</div>`;
}
function documentaryRetry(){if(!P)return;toast('Press Render MP4 (top right) to try the export again.')}

// The three resolutions the export page offers. The pixel pair shown is the one that
// belongs to this project's shape: a 9:16 film reads 1080x1920, never 1920x1080.
const EXPORT_RESOLUTIONS=[{key:'1080p',label:'1080p Full HD',w:1920,h:1080},{key:'2k',label:'2K QHD',w:2560,h:1440},{key:'4k',label:'4K UHD',w:3840,h:2160}];
function exportOrientation(){return P?.format==='portrait'}
function resolutionPixels(r){return exportOrientation()?[r.h,r.w]:[r.w,r.h]}
function currentResolutionKey(){const stored=P?.size||'1080p';const found=EXPORT_RESOLUTIONS.find(r=>r.key===stored||(stored==='1440p'&&r.key==='2k')||(stored==='4k'&&r.key==='4k'));return found?found.key:'1080p'}
// What a resolution costs this project, taken from the source dimensions the server
// recorded at upload. When nothing needs enlarging the line says so, because rendering
// an already-sharp film should not claim to have enhanced it.
function sourceSummary(r){
 const plan=P?.export_plan;if(!plan)return '';
 const [w,h]=resolutionPixels(r);const target=Math.min(w,h);
 const sources=(plan.sources||[]);
 if(!sources.length)return `<span class="small">${w} × ${h}</span>`;
 const short=s=>Math.min(s.width,s.height);
 const best=sources.reduce((a,b)=>short(a)>=short(b)?a:b,sources[0]);
 const factor=!short(best)||target<=short(best)?1:target<=short(best)*2?2:4;
 const stale=sources.filter(s=>!s.width).length;
 // Only claim AI when an AI engine is actually installed on this machine. Otherwise the
 // line says Lanczos, because a subtle label is better than a false one.
 const ai=typeof AI_UPSCALE!=='undefined'&&AI_UPSCALE.available&&P?.upscaler!=='lanczos';
 // AI upscalers work in ×2/×4 steps (then resize to fit); a plain resize is the real ratio.
 const ratio=short(best)?target/short(best):1;
 const label=factor===1?'No upscale needed':ai?`AI upscale ×${factor}, then fit`:`Resize ×${ratio.toFixed(ratio%1?1:0)}`;
 const engine=ai?'Real-ESRGAN':'Lanczos';
 return `<span class="small">${w} × ${h} · ${label}${factor>1?` · ${engine}`:''}${stale?` · ${stale} source(s) without recorded size`:''}</span>`
}
function resolutionHTML(){
 const key=currentResolutionKey();
 return `<div class="resolution-row" role="radiogroup" aria-label="Export resolution">${EXPORT_RESOLUTIONS.map(r=>{
  const [w,h]=resolutionPixels(r);
  return `<button type="button" class="resolution-choice${r.key===key?' is-on':''}" role="radio" aria-checked="${r.key===key}" onclick="setExportResolution('${r.key}')"><strong>${r.label}</strong><span>${w} × ${h}</span>${sourceSummary(r)}</button>`;
 }).join('')}</div><p class="small">The upscale factor is worked out from the source footage. Footage that already meets the target is not processed again.</p>`
}

async function saveExportSetting(patch){if(!P)return;try{P=await api('/api/projects/'+P.id,'PATCH',patch);renderRenderPage()}catch(e){toast(e.message)}}
function setExportResolution(key){if(!P)return;if(key===currentResolutionKey())return;saveExportSetting({size:key})}

// One click renders a Beat documentary. The server re-runs the cut check on the
// current production itself, so nothing here waits for a check or asks to confirm;
// the saved settings (captions, picture enhance, fade, music, transitions, caption
// style) all go into the file. A real problem is shown in plain words, in place --
// never by jumping to another page.
async function docRenderNow(){
 if(!P||!P.documentary_beat_review)return false;
 if(dirty){toast('Save or discard scene edits before rendering.');return true}
 const id=P.id,saved=window.documentaryExportSplits;
 const splits=saved&&saved.id===id&&saved.revision===window.docTimelineData?.revision?saved.splits||[]:[];
 const button=$('#render-button');if(button){button.textContent='Starting render…';button.disabled=true}
 pauseEditor();
 try{
  const response=await api(`/api/projects/${id}/render`,'POST',{final:true,strict_checked_version:P.updated,enhance_picture:false,srt_subtitles:burnSrtOnExport,subtitle_splits:splits});
  if(P?.id!==id)return true;P.render=response.render;renderProject();
  toast('Rendering started. Progress shows on the Render button; it turns into Download when the MP4 is ready.');
 }catch(e){
  if(button)button.disabled=false;renderExport();
  alert('The render could not start:\n\n'+(e.message||e));
 }
 return true;
}
window.docRenderNow=docRenderNow;
async function renderFromEditor(){
 if(!P)return;
 if(P.edit_mode==='documentary'){
  if(P.documentary_beat_review){await docRenderNow();return}
  if(!$('#render-dialog')?.open){openRenderPage();return}
  if(!P.documentary_beat_review){toast('Final export currently supports script-driven Beat storyboards only.');return}
  if(dirty){toast('Save or discard scene edits before rendering.');return}
  const id=P.id,version=P.updated;let status=ensureStrictStatus();toast('Checking documentary cue shots and source frames…');
  try{const checked=status.report||await status.promise;if(P?.id!==id||P?.updated!==version){toast('The project changed. Check the current timeline again.');return}if(!checked||checked.errors.length){await openStrictCutCheck(null);return}
   let splits=[];if(burnSrtOnExport){const saved=window.documentaryExportSplits;const crossing=(window.docTimelineData?.bites||[]).some(b=>(P.srt?.blocks||[]).some(c=>c.start_ms<b.pause_s*1000&&b.pause_s*1000<c.end_ms));if(crossing&&(!saved||saved.id!==id||saved.revision!==window.docTimelineData?.revision)){await openDocumentary();toast('Choose and confirm the subtitle split in Documentary tools before rendering with SRT.');return}splits=saved?.id===id&&saved.revision===window.docTimelineData?.revision?saved.splits:[]}
   const fades=P?.documentary_fades||{},useFade=fades.enabled!==false&&((Number(fades.in_s)||0)>0||(Number(fades.out_s)||0)>0);
   if(!confirm(`Render the documentary MP4? ${useFade?`The scripted fade will be included (${Number(fades.in_s)||0}s in${(Number(fades.out_s)||0)>0?`, ${Number(fades.out_s)}s out`:''})`: 'No fade will be applied'}. Source identity and rights attestations still require your review.`))return;
   pauseEditor();const response=await api(`/api/projects/${id}/render`,'POST',{final:true,strict_checked_version:version,omit_fade:!useFade,fade:useFade,enhance_picture:false,srt_subtitles:burnSrtOnExport,subtitle_splits:splits});if(P?.id!==id)return;P.render=response.render;renderProject();toast('Documentary export started. Please wait for it to finish.');
  }catch(e){toast(e.message);manage('delivery')}return
 }
 if(P.validation?.errors?.length){manage('delivery');await openStrictCutCheck(null);return}await startExport(false)
}
function inspectAsset(id){if(!leave())return;if((P?.script_moving_only||!scenes().length)&&assets().find(a=>a.id===id)?.kind==='video'){openSourceFile(id);return}const found=scenes().findIndex(s=>s.asset_id===id);if(found>=0){selectEditorScene(found);toast('Selected the first timeline scene using this asset.')}else manage('brief')}
function openFirstSourceFile(){const asset=assets().find(a=>a.kind==='video');if(asset)openSourceFile(asset.id);else toast('No source video is available.') }
function openSourceFile(id){
 const asset=assets().find(a=>a.id===id);if(!asset||asset.kind!=='video'){toast('This source video is unavailable.');return}
 pauseEditor();const dialog=$('#source-file-dialog'),video=$('#source-file-video');$('#source-file-title').textContent=asset.original_name||asset.name;video.pause();video.loop=false;video.muted=true;video.playbackRate=1;video.src=asset.url;video.load();if(!dialog.open)dialog.showModal();
}
function closeSourceFile(){const dialog=$('#source-file-dialog'),video=$('#source-file-video');video.pause();video.removeAttribute('src');video.load();if(dialog.open)dialog.close()}
$('#source-file-dialog').addEventListener('cancel',event=>{event.preventDefault();closeSourceFile()});
function selectEditorScene(i,event){if(P?.edit_mode==='documentary'){docSelectScene(i,event);return}if(!scenes().length)return;if(suppressClipClick){suppressClipClick=false;return}if(!leave())return;pauseEditor();i=Math.max(0,Math.min(scenes().length-1,i));const id=scenes()[i].id;if(event&&(event.ctrlKey||event.metaKey)){if(selectedSlotIds.has(id))selectedSlotIds.delete(id);else selectedSlotIds.add(id)}else selectedSlotIds=new Set([id]);selectionExplicitlyEmpty=!selectedSlotIds.size;slotScalePreview=null;sceneIndex=i;sourceScene='';seekEditor(scenes()[sceneIndex].frame_in/30,false);renderInspector();markSelected();syncPictureScale()}
function cacheClipNodes(){const byScene=new Map(),rows=scenes();for(const node of videoTrack.querySelectorAll('.shot-clip')){const id=rows[Number(node.dataset.scene)]?.id;if(!id)continue;let nodes=byScene.get(id);if(!nodes){nodes=[];byScene.set(id,nodes)}nodes.push(node);const active=selectedSlotIds.has(id);if(node.classList.contains('selected')!==active)node.classList.toggle('selected',active);const pressed=String(active);if(node.getAttribute('aria-pressed')!==pressed)node.setAttribute('aria-pressed',pressed)}clipNodesByScene=byScene;lastMarkedSceneIds=new Set(selectedSlotIds);if(marquee?.active){marquee.rows=rows;marquee.index=buildMarqueeIntervalIndex(rows);marquee.range={};marquee.clipNodes=Array.from(videoTrack.querySelectorAll('.shot-clip'));marquee.sceneIndexById=new Map(rows.map((scene,i)=>[scene.id,i]))}updateSelectAllButton()}
function markSelected(updateControls=true){if(!lastMarkedSceneIds){cacheClipNodes();return}const changed=new Set();for(const id of lastMarkedSceneIds)if(!selectedSlotIds.has(id))changed.add(id);for(const id of selectedSlotIds)if(!lastMarkedSceneIds.has(id))changed.add(id);if(changed.size){for(const id of changed){const active=selectedSlotIds.has(id);for(const node of clipNodesByScene.get(id)||[]){if(node.classList.contains('selected')!==active)node.classList.toggle('selected',active);const pressed=String(active);if(node.getAttribute('aria-pressed')!==pressed)node.setAttribute('aria-pressed',pressed)}}lastMarkedSceneIds=new Set(selectedSlotIds)}if(updateControls&&typeof updateSelectAllButton==='function')updateSelectAllButton()}
function videoSlotIds(){const video=new Set(assets().filter(a=>a.kind==='video').map(a=>a.id));return new Set(scenes().filter(s=>video.has(s.asset_id)).map(s=>s.id))}
function selectAllVideoSlots(){if(!P||!leave())return;if(P.edit_mode!=='documentary')pauseEditor();const all=videoSlotIds(),already=all.size>0&&[...all].every(id=>selectedSlotIds.has(id));selectedSlotIds=already?new Set():all;selectionExplicitlyEmpty=!selectedSlotIds.size;slotScalePreview=null;markSelected();renderInspector();syncPictureScale();updateSelectAllButton();toast(already?'Selection cleared.':`${selectedSlotIds.size} MP4 slot(s) selected.`)}
function updateSelectAllButton(){const b=$('#select-all-video');if(!b)return;const all=videoSlotIds(),all_on=all.size>0&&[...all].every(id=>selectedSlotIds.has(id));b.textContent=all_on?'Deselect all MP4':'Select all MP4';b.setAttribute('aria-pressed',String(all_on));b.title=all_on?'Clear the current selection':'Select every slot that uses MP4 footage'}
function seekEditor(t,select=true){if(P?.edit_mode==='documentary'){docSeekTimeline(t,select);return}if(!scenes().length)return;t=Math.max(0,Math.min(totalTime()-.001,t));if(select&&!leave())return;const previousScene=sceneIndex,was=editorPlaying;pauseEditor();clockBase=t;clockAt=performance.now();if(editorMaster){masterSeekToken++;try{masterNode.currentTime=t}catch{}}else if(P?.voiceover){try{narrNode.currentTime=t}catch{}}if(select){const i=findActiveIntervalIndex(scenes(),frameAt(t),'frame_in','frame_out');if(i>=0)sceneIndex=i}sourceScene='';if(!editorMaster)showSource(sceneIndex,t);if(sceneIndex!==previousScene){renderInspector();markSelected()}updatePosition();requestEditorTick();if(was)playEditor()}
// The transport shows the playhead in one colour and the programme length in
// another, like a deck: current / total. Both come from the same clock.
let timecodeStamp=0;
// During playback the readout updates about 12 times a second. Each text change
// makes the browser recompose the page, and at 60 per second that alone cost a
// visible share of the time the video needed to play smoothly.
function setTimecode(current,total){const now=performance.now();if(editorPlaying&&now-timecodeStamp<80)return;timecodeStamp=now;const a=$('#timecode-current'),b=$('#timecode-total');if(a&&a.textContent!==current)a.textContent=current;if(b&&b.textContent!==total)b.textContent=total}
// The playhead moves on its own compositor layer. Moving it with `left` re-laid out
// and repainted the whole timeline (hundreds of clips) on every frame, which used most
// of the browser's time during playback and made the video stutter and hang.
function movePlayhead(x){const p=$('#playhead');if(!p)return;x=Math.round(x*2)/2;if(p._x===x)return;p._x=x;if(p.style.left!=='0px')p.style.left='0px';p.style.transform=`translate3d(${x}px,0,0)`}
let ariaStamp=0;
function setPlayheadAria(t,total){const now=performance.now();if(editorPlaying&&now-ariaStamp<500)return;ariaStamp=now;const h=$('#playhead-handle');if(!h)return;h.setAttribute('aria-valuemax',total.toFixed(1));h.setAttribute('aria-valuenow',t.toFixed(1));h.setAttribute('aria-valuetext',fmt(t))}
// Monitor chrome. Full fit / aspect / fullscreen are view preferences only: they
// never touch the project, a render, or the stored picture scale.
let monitorFit='contain',monitorAspect='16:9';
document.addEventListener('fullscreenchange',()=>{const m=$('#monitor');const on=document.fullscreenElement===m;if(m)m.classList.toggle('is-fullscreen',on);const b=$('#monitor-fullscreen');if(b){b.setAttribute('aria-pressed',String(on));b.title=on?'Exit full screen (Esc)':'Full screen (Esc to return)'}
 // Name cards, the CTA and the watermark are placed from the frame's size: redraw them.
 requestAnimationFrame(()=>window.dispatchEvent(new Event('resize')))});
// v25: the button under the monitor. The browser's own Esc leaves full screen.
function toggleMonitorFullscreen(button){
 const m=$('#monitor');if(!m)return;
 if(document.fullscreenElement){document.exitFullscreen?.();return}
 if(!m.requestFullscreen){toast('Full screen is not available in this browser.');return}
 m.requestFullscreen({navigationUI:'hide'}).catch(e=>toast('Full screen was blocked: '+e.message));
 button?.blur();   // so Space plays and pauses instead of pressing the button again
}
// Chrome and Edge leave full screen on Esc by themselves; this covers any that pass Esc to the page.
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&document.fullscreenElement&&document.fullscreenElement===$('#monitor'))document.exitFullscreen?.()});
// The monitor is the project's frame, not a fixed 16:9 box. Portrait and 4:5 films
// get a tall frame and crop-to-fill, the same framing the renderer uses, so what is
// reviewed is what is exported. View preference only: never touches a stored edit.
const MONITOR_SHAPES={landscape:'16:9',portrait:'9:16',square:'1:1',vertical_4_5:'4:5',cinema:'239:100'};
// The shape switch lives beside the monitor, where you can see what it does. It
// writes the same project setting as Setup's Aspect ratio control, so the two can
// never disagree. Only an explicit click changes a production.
// Only the two shapes this workflow actually delivers: a 16:9 film for YouTube and
// a 9:16 reel for TikTok/Reels. Square and 4:5 were never used and only made the
// choice longer. The engine still knows those shapes for existing projects; they are
// simply no longer offered here.
const ASPECT_ORDER=['landscape','portrait'];
const ASPECT_LABEL={landscape:'16:9',portrait:'9:16',square:'1:1',vertical_4_5:'4:5',cinema:'2.39:1'};
const ASPECT_NAME={landscape:'Landscape',portrait:'Portrait'};
function syncAspectChip(){const chip=$('#aspect-toggle');if(!chip)return;const shape=MONITOR_SHAPES[P?.format]||'16:9';chip.textContent=ASPECT_LABEL[P?.format]||shape;chip.hidden=!P;chip.title='Frame shape · '+shape+'. Click to choose.'}
// A menu, not a cycle: clicking used to jump to the next shape, so reading the
// current one and choosing one were the same action and an accidental click moved
// the production. The menu lists every shape and marks the current one.
function aspectMenuOpen(){const m=$('#aspect-menu');return !!m&&!m.hidden}
function closeAspectMenu(){const m=$('#aspect-menu'),b=$('#aspect-toggle');if(m)m.hidden=true;if(b)b.setAttribute('aria-expanded','false')}
function buildAspectMenu(){const m=$('#aspect-menu');if(!m)return;
 m.innerHTML=ASPECT_ORDER.map(k=>`<button type="button" role="option" aria-selected="${P?.format===k}" data-format="${k}" class="${P?.format===k?'current':''}" onclick="chooseAspect('${k}')"><span class="aspect-size">${ASPECT_LABEL[k]}</span><span class="aspect-name">${ASPECT_NAME[k]}</span><span class="aspect-tick">${P?.format===k?'✓':''}</span></button>`).join('')}
// Positioned against the button, then flipped and clamped so it always lands on
// screen even though the transport itself clips its overflow.
function placeAspectMenu(){const m=$('#aspect-menu'),b=$('#aspect-toggle');if(!m||!b)return;
 const r=b.getBoundingClientRect();m.hidden=false;
 const w=m.offsetWidth||180,h=m.offsetHeight||150;
 let left=r.right-w;if(left<8)left=8;
 if(left+w>window.innerWidth-8)left=window.innerWidth-w-8;
 let top=r.top-h-8;if(top<8)top=r.bottom+8;
 m.style.left=Math.round(left)+'px';m.style.top=Math.round(top)+'px'}
function toggleAspectMenu(event){if(event&&event.stopPropagation)event.stopPropagation();if(!P)return;
 if(aspectMenuOpen()){closeAspectMenu();return}buildAspectMenu();placeAspectMenu();$('#aspect-toggle').setAttribute('aria-expanded','true')}
async function chooseAspect(format){closeAspectMenu();if(!P||P.format===format)return;if(typeof setFormat==='function')await setFormat(format);syncAspectChip()}
document.addEventListener('click',e=>{if(!aspectMenuOpen())return;if(e.target.closest&&e.target.closest('#aspect-menu,#aspect-toggle'))return;closeAspectMenu()});
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&aspectMenuOpen()){closeAspectMenu();$('#aspect-toggle')?.focus()}});
window.addEventListener('resize',()=>{if(aspectMenuOpen())placeAspectMenu()});
/* The production name sits on the monitor's centre line. That line is fixed by the
   grid, but the action buttons are wider than the inspector column, so on anything
   narrower than a wide desktop they reach back towards it. Rather than guess at the
   space in the stylesheet, measure it: the name is allowed exactly the room between
   the two boxes and the first button. A long title therefore ends in an ellipsis
   before it can run into the buttons, and the line itself never moves. */
function fitHeaderName(){
  const name=document.querySelector('#project-name'),head=name&&name.closest('.project-heading'),
        tools=document.querySelector('.head-tools'),actions=document.querySelector('.topbar>.top-actions');
  if(!name||!head||!tools||!actions)return;
  // The name is centred on the monitor's line, so its room is symmetric: twice the
  // smaller of the two gaps beside that line. Measuring min() rather than assuming
  // the buttons are the nearer neighbour means the name never overlaps either of them.
  name.style.removeProperty('--name-room');
  const centre=head.getBoundingClientRect().left + head.getBoundingClientRect().width/2;
  // The action group's own box starts one column to the left of its buttons (it spans
  // from the monitor column so that Render MP4 still ends at the window edge), and that
  // box is mostly empty. Measuring the box's left edge therefore reported no room at all
  // and the production name disappeared. Measure the first button that is actually
  // drawn, which is the real neighbour no matter how far the group's box reaches.
  const visible=[...actions.querySelectorAll('.button')]
    .map(b=>b.getBoundingClientRect()).filter(r=>r.width>0||r.height>0);
  if(!visible.length)return;
  const left=tools.getBoundingClientRect().right,
        right=Math.min(...visible.map(r=>r.left));
  const room=Math.max(0,Math.floor(2*Math.min(centre-left,right-centre)-24));
  name.style.setProperty('--name-room',room+'px');
}
window.addEventListener('resize',fitHeaderName);
document.addEventListener('DOMContentLoaded',fitHeaderName);
if(document.readyState!=='loading')fitHeaderName();
window.addEventListener('scroll',()=>{if(aspectMenuOpen())placeAspectMenu()},true);
function syncMonitorShape(){const box=$('#monitor');if(!box)return;const shape=MONITOR_SHAPES[P?.format]||'16:9';box.dataset.aspect=shape;box.dataset.fit=shape==='16:9'?'contain':'cover';
 // A vertical film gets a taller panel so the frame can be a useful size; leaving
 // portrait returns the grid to its default proportions untouched.
 const grid=box.closest('.editor-grid');if(grid)grid.classList.toggle('is-vertical',(P?.format||'landscape')!=='landscape')}
function updatePlaybackButton(){const button=$('#play-button');button.textContent=editorPlaying?'❚❚':'▶';button.title=editorPlaying?'Pause':'Play';button.setAttribute('aria-label',button.title)}
function toggleEditorPlayback(){if(editorPlaying)pauseEditor();else playEditor()}
async function playEditor(){if(P?.edit_mode==='documentary'){await docPlayTimeline();if(editorPlaying)requestEditorTick();return}if(!scenes().length){toast('Import SRT and build the storyboard first.');return}if(scenes()[sceneIndex]?.missing_video_out){toast('This still or freeze is not shown in the moving-video review.');return}if(dirty){toast('Save or discard scene edits before playing.');return}if(editorTime()>=totalTime()-.01)seekEditor(0,true);editorPlaying=true;updatePlaybackButton();requestEditorTick();clockAt=performance.now();try{if(editorMaster){masterNode.muted=editorMuted;await masterNode.play()}else{const s=scenes()[sceneIndex],a=assets().find(a=>a.id===s?.asset_id);if(a?.kind==='video'&&!sourceReady){seekSourceAtTimeline(s,a,editorTime());return}showSource(sceneIndex,editorTime());if(P?.voiceover){narrNode.muted=editorMuted;await narrNode.play()}if(a?.kind==='video'&&sourceReady&&sourceNode.readyState>=2)await sourceNode.play()}}catch(e){pauseEditor();toast('Playback could not start. Check the selected media or try again.')}}
function pauseEditor(){if(P?.edit_mode==='documentary')window.cancelDocPlay?.();const wasPlaying=editorPlaying;if(editorPlaying&&!editorMaster&&!P?.voiceover)clockBase=editorTime();editorPlaying=false;updatePlaybackButton();masterNode.pause();sourceNode.pause();narrNode.pause();clockAt=performance.now();if(wasPlaying&&P?.edit_mode==='documentary')setTimeout(()=>{if(!editorPlaying)renderInspector()},0)}
function updateTrackMuteControls(){
 if(P?.edit_mode==='documentary'){docUpdateMuteControls();return}
 const audio=$('#mute-audio'), video=$('#mute-mp4');
 if(audio){audio.textContent=editorMuted?'Muted':'On';audio.setAttribute('aria-pressed',String(editorMuted));audio.setAttribute('aria-label',(editorMuted?'Unmute':'Mute')+' narration track in preview');audio.title=editorMuted?'Narration muted in preview':'Narration on in preview'}
 if(video){video.textContent=editorVideoMuted?'Muted':'On';video.setAttribute('aria-pressed',String(editorVideoMuted));video.setAttribute('aria-label',(editorVideoMuted?'Unmute':'Mute')+' MP4 source audio for preview');video.title=editorVideoMuted?'MP4 source audio muted in preview':'MP4 source audio on in preview'}
}


// Cut Action fades are a project setting read by both the preview and the export.
async function setDocumentaryFades(patch){
 if(!P)return;
 const previous=JSON.parse(JSON.stringify(P.documentary_fades||{}));
 P.documentary_fades=Object.assign({},previous,patch);
 try{
  const updated=await api(`/api/projects/${P.id}`,'PATCH',{documentary_fades:patch});
  if(P?.id!==updated.id)return;
  P.documentary_fades=updated.documentary_fades||{};
  renderExport();toast(P.documentary_fades.enabled===false?'The export will not fade.':'The export will include the scripted fade.');
 }catch(e){P.documentary_fades=previous;renderExport();toast(e.message)}
}
// On-screen script captions are a project setting: the preview and the export
// read the same flag, so switching it never needs a rebuild of the timeline.
async function setBurnCaptions(enabled){
 if(!P)return;
 const previous=P.burn_captions===true;
 P.burn_captions=!!enabled;
 try{
  const updated=await api(`/api/projects/${P.id}`,'PATCH',{burn_captions:!!enabled});
  if(P?.id!==updated.id)return;
  P.burn_captions=updated.burn_captions===true;
  $('#editor-captions').classList.add('captions-off');
  renderProgram();updatePosition();toast(P.burn_captions?'On-screen captions will be burned in.':'On-screen text is off: clean picture, nothing burned in.');
 }catch(e){
  P.burn_captions=previous;const burnBox=$('#burn-on-screen-captions');if(burnBox)burnBox.checked=previous;toast(e.message);
 }
}
function setEditorCaptions(enabled){editorCC=!!enabled;$('#caption-toggle').textContent=editorCC?'CC On':'CC Off';$('#caption-toggle').setAttribute('aria-pressed',String(editorCC));renderProgram();updatePosition();if($('#manage-dialog').open)renderManagement()}
function setBurnSrtOnExport(enabled){burnSrtOnExport=!!enabled;renderExport();toast(burnSrtOnExport?'SRT captions will be permanently visible in the exported MP4.':'The exported MP4 will have clean picture; keep the separate SRT for optional captions.')}
function toggleEditorCaptions(){setEditorCaptions(!editorCC)}
// v19: dragging the zoom slider used to rebuild the whole timeline on every step
// (a quarter of a second each on an hour-long film). While the slider moves, the drawn
// timeline is stretched on the graphics card, which is instant; the real redraw
// happens once, a moment after the slider stops, keeping the playhead where it was.
let zoomRenderTimer=0,zoomDrawnAt=null;
function setEditorZoom(v,immediate=false){
 // The slider is the fine control; the two buttons beside it exist so the timeline can
 // be zoomed without dragging at all. Both write through the same value, so the slider
 // always shows the zoom the buttons reached.
 const next=Math.max(2,Math.min(35,Number(v)||12));
 const slider=$('#zoom');if(slider&&Number(slider.value)!==next)slider.value=next;
 const content=$('#timeline-content'),scroll=$('#timeline-scroll');
 if(zoomDrawnAt===null)zoomDrawnAt={zoom:timelineZoom,playheadX:editorTime()*timelineZoom-(scroll?.scrollLeft||0)};
 timelineZoom=next;
 const finish=()=>{clearTimeout(zoomRenderTimer);zoomRenderTimer=0;const anchor=zoomDrawnAt;zoomDrawnAt=null;
  if(content)content.style.transform='';renderTimeline();updatePosition();
  if(scroll&&anchor)scroll.scrollLeft=Math.max(0,editorTime()*timelineZoom-anchor.playheadX)};
 if(immediate||!content){finish();return}
 const ratio=timelineZoom/zoomDrawnAt.zoom;
 content.style.transformOrigin='0 0';content.style.transform=ratio===1?'':`scaleX(${ratio})`;
 clearTimeout(zoomRenderTimer);zoomRenderTimer=setTimeout(finish,140);
}
// A readable name for a shot: sound bites say so, narration shots name their SRT line
// and Beat, so two shots on the same line are no longer both called "Srt003".
function qcShotLabel(s,i){const r=s?.plan_row||{},beat=String(r.continuity||'').match(/beat\s+(\S+)/i)?.[1];
 if(r.bite_id)return `Sound bite${beat?' · Beat '+beat:''}${r.source_file?' · '+r.source_file:''}`;
 const lines=[...new Set(r.srt_blocks||s?.srt_blocks||[])];
 return `${lines.length?'SRT '+lines.join('–'):r.shot_id||'Scene '+(i+1)}${beat?' · Beat '+beat:''}${r.source_file?' · '+r.source_file:''}`}
function stepEditorZoom(direction){setEditorZoom(timelineZoom+(direction>0?2:-2),true)}
// Fit the whole film into the visible timeline (still readable on very long films).
function fitTimelineZoom(duration,render=true){
 const d=Number(duration)||Math.max(typeof totalTime==='function'?totalTime():0,Number(P?.voiceover?.duration)||0);
 const box=$('#timeline-scroll');if(!d||!box)return;
 const width=Math.max(300,box.clientWidth-28);
 timelineZoom=Math.max(2,Math.min(35,Math.floor(width/d*10)/10));
 const slider=$('#zoom');if(slider)slider.value=timelineZoom;
 if(render){renderTimeline();updatePosition()}
}
masterNode.addEventListener('ended',pauseEditor);narrNode.addEventListener('ended',pauseEditor);
$('#manage-dialog').addEventListener('cancel',e=>{e.preventDefault();closeManagement()});
// The ruler is draggable too; its pointer path uses the same lightweight scrub.

// Scrub the timeline without editing SRT, source ranges or narration.
let playheadDrag=null;
// A drag must never enqueue 30-60 video decoder seeks per second. The ruler and
// thumbnail respond immediately; a single frame-accurate media seek runs on drop.
const scrubPoster=document.createElement('div');scrubPoster.id='storyroom-scrub-poster';scrubPoster.hidden=true;
scrubPoster.innerHTML='<img alt="Approximate source thumbnail"><span>SCRUB · source thumbnail · exact frame on release</span>';
$('#monitor-frame').append(scrubPoster);
let scrubPosterKey='';
let scrubLookupCache={scenes:null,assets:null,sceneIds:null,assetIds:null};
function scrubLookups(){
 const ss=scenes(), aa=assets();
 if(scrubLookupCache.scenes!==ss || scrubLookupCache.assets!==aa){
  scrubLookupCache={scenes:ss,assets:aa,sceneIds:new Map(ss.map((s,i)=>[s.id,i])),assetIds:new Map(aa.map(a=>[a.id,a]))};
 }
 return scrubLookupCache;
}
// Bounded in-memory measurements, not synthetic speed claims.
const scrubTimings={ui:[],seek:[]};let seekMeasurementCancel=null;
function addScrubTiming(kind,elapsed){
 if(!Number.isFinite(elapsed) || elapsed<0)return;
 const list=scrubTimings[kind];list.push(elapsed);if(list.length>80)list.shift();
}
function scrubTimingSummary(){
 const stat=values=>{if(!values.length)return null;const v=[...values].sort((a,b)=>a-b);return {count:v.length,p50:v[Math.floor(.5*(v.length-1))],p95:v[Math.ceil(.95*v.length)-1]}};
 return {ui:stat(scrubTimings.ui),seek:stat(scrubTimings.seek)};
}
function beginSeekMeasurement(){
 if(seekMeasurementCancel)seekMeasurementCancel();
 const began=performance.now();let finished=false;
 // Select whichever media player owns the timeline clock. A seek event measures
 // the browser finishing its time jump; it does not certify that pixels decoded.
 const d=window.docTimelineData;
 const node=P?.edit_mode==='documentary' ? (d?.direct?narrNode:masterNode) : (editorMaster?masterNode:sourceNode);
 if(!node)return;
 let timer=null;
 const end=()=>{if(finished)return;finished=true;node.removeEventListener('seeked',end);clearTimeout(timer);seekMeasurementCancel=null;addScrubTiming('seek',performance.now()-began)};
 seekMeasurementCancel=()=>{finished=true;node.removeEventListener('seeked',end);clearTimeout(timer);seekMeasurementCancel=null};
 node.addEventListener('seeked',end);
 timer=setTimeout(()=>{if(seekMeasurementCancel)seekMeasurementCancel()},5000);
}
function previewScrubPosition(t){
 const d=window.docTimelineData,part=d?.direct&&typeof docDirectAt==='function'?docDirectAt(t):null;
 // Beat scene frames are on the programme clock even before the source schedule loads.
 const base=t;const lookups=scrubLookups();
 const index=part?.scene_id?(lookups.sceneIds.get(part.scene_id)??-1):findActiveIntervalIndex(scenes(),frameAt(base),'frame_in','frame_out');
 const scene=scenes()[index>=0?index:sceneIndex];const id=part?.asset_id||scene?.asset_id;
 const asset=lookups.assetIds.get(id);const key=(P?.id||'')+':'+(id||'');
 if(key!==scrubPosterKey){scrubPosterKey=key;const img=scrubPoster.querySelector('img');img.hidden=!asset;
  if(asset)img.src=`/api/projects/${P.id}/assets/${encodeURIComponent(asset.id)}/poster?v=${encodeURIComponent(asset.revision||asset.id)}`;
  else img.removeAttribute('src');
 }
 scrubPoster.hidden=false;movePlayhead(t*timelineZoom);setTimecode(fmt(t),fmt(totalTime()));setPlayheadAria(t,totalTime());
}
function clearScrubPreview(){scrubPoster.hidden=true;scrubPosterKey=''}
function scrubPlayhead(clientX,previous=null){
 const started=performance.now();
 const rect=$('#timeline-content').getBoundingClientRect(),duration=totalTime(),target=Math.max(0,Math.min(Math.max(0,duration-.001),(clientX-rect.left)/timelineZoom));
 const drag=playheadDrag||previous;if(drag&&drag.lastTarget!=null&&Math.abs(drag.lastTarget-target)<.001)return;
 if(drag)drag.lastTarget=target;previewScrubPosition(target);addScrubTiming('ui',performance.now()-started);
}

// Drag across the MP4 track to draw a selection. Ctrl/Command adds to it.
const videoTrack=$('#video-track');
function buildMarqueeIntervalIndex(rows){
 const starts=new Float64Array(rows.length),ends=new Float64Array(rows.length),prefixMaxEnds=new Float64Array(rows.length);let lastStart=-Infinity,maxEnd=-Infinity,sorted=true;
 for(let i=0;i<rows.length;i++){const start=Number(rows[i]?.frame_in),end=Number(rows[i]?.frame_out);if(!Number.isFinite(start)||!Number.isFinite(end)||start<lastStart)sorted=false;starts[i]=start;ends[i]=end;lastStart=start;maxEnd=Math.max(maxEnd,end);prefixMaxEnds[i]=maxEnd}
 return {starts,ends,prefixMaxEnds,sorted};
}
function marqueeSceneCandidateRange(index,left,right,zoom,range){
 if(!index?.sorted||!zoom)return null;
 const firstFrame=left*30/zoom,lastFrame=right*30/zoom;let low=0,high=index.starts.length;
 while(low<high){const middle=(low+high)>>1;if(index.prefixMaxEnds[middle]<=firstFrame)low=middle+1;else high=middle}
 const first=low;low=0;high=index.starts.length;
 while(low<high){const middle=(low+high)>>1;if(index.starts[middle]<lastFrame)low=middle+1;else high=middle}
 range=range||{};range.first=first;range.last=low;return range;
}
videoTrack.addEventListener('pointerdown',e=>{if(P?.edit_mode==='documentary')return;if(e.button!==0||!P||!scenes().length)return;const rect=videoTrack.getBoundingClientRect(),rows=scenes();marquee={id:e.pointerId,startX:e.clientX-rect.left,x:e.clientX,y:e.clientY,initial:new Set(selectedSlotIds),add:e.ctrlKey||e.metaKey,active:false,raf:0,rows,index:buildMarqueeIntervalIndex(rows),range:{},clipNodes:Array.from(videoTrack.querySelectorAll('.shot-clip')),sceneIndexById:new Map(rows.map((scene,i)=>[scene.id,i]))}});
function setMarqueeClipSelected(drag,id,active){const i=drag.sceneIndexById.get(id),node=drag.clipNodes[i];if(!node)return;node.classList.toggle('selected',active);node.setAttribute('aria-pressed',String(active))}
function updateMarquee(){if(!marquee?.active)return;const drag=marquee,scroll=$('#timeline-scroll'),viewport=scroll.getBoundingClientRect();if(drag.x>viewport.right-30)scroll.scrollLeft+=Math.min(18,Math.max(0,(drag.x-viewport.right+30)/2));else if(drag.x<viewport.left+30)scroll.scrollLeft-=Math.min(18,Math.max(0,(viewport.left+30-drag.x)/2));const rect=videoTrack.getBoundingClientRect(),end=drag.x-rect.left,left=Math.min(drag.startX,end),right=Math.max(drag.startX,end),zoom=timelineZoom,rows=drag.rows,selected=selectedSlotIds;let box=videoTrack.querySelector('.selection-marquee');if(!box){box=document.createElement('div');box.className='selection-marquee';videoTrack.append(box)}box.style.left=left+'px';box.style.width=(right-left)+'px';for(const id of selected){if(drag.add&&drag.initial.has(id))continue;const i=drag.sceneIndexById.get(id),scene=rows[i];if(!scene||scene.frame_in/30*zoom>=right||scene.frame_out/30*zoom<=left){selected.delete(id);setMarqueeClipSelected(drag,id,false)}}const range=marqueeSceneCandidateRange(drag.index,left,right,zoom,drag.range),first=range?range.first:0,last=range?range.last:rows.length;for(let i=first;i<last;i++){const scene=rows[i];if(scene.frame_in/30*zoom<right&&scene.frame_out/30*zoom>left&&!selected.has(scene.id)){selected.add(scene.id);setMarqueeClipSelected(drag,scene.id,true)}}selectionExplicitlyEmpty=!selected.size;drag.raf=requestAnimationFrame(updateMarquee)}
videoTrack.addEventListener('pointermove',e=>{if(!marquee||marquee.id!==e.pointerId)return;marquee.x=e.clientX;marquee.y=e.clientY;const rect=videoTrack.getBoundingClientRect();if(!marquee.active&&Math.abs(e.clientX-rect.left-marquee.startX)>5){if(!leave()){marquee=null;return}pauseEditor();slotScalePreview=null;marquee.active=true;videoTrack.setPointerCapture(e.pointerId);updateMarquee()}if(marquee?.active)e.preventDefault()});
function finishMarquee(e){if(!marquee||marquee.id!==e.pointerId)return;const was=marquee.active;if(was){const drag=marquee;cancelAnimationFrame(drag.raf);videoTrack.querySelector('.selection-marquee')?.remove();if(e.type==='pointercancel'){const previous=selectedSlotIds;selectedSlotIds=drag.initial;for(const id of previous)if(!selectedSlotIds.has(id))setMarqueeClipSelected(drag,id,false);for(const id of selectedSlotIds)if(!previous.has(id))setMarqueeClipSelected(drag,id,true);selectionExplicitlyEmpty=!selectedSlotIds.size}else{const first=scenes().findIndex(s=>selectedSlotIds.has(s.id));if(first>=0){sceneIndex=first;sourceScene='';seekEditor(scenes()[first].frame_in/30,false)}}markSelected();renderInspector();syncPictureScale();suppressClipClick=true;setTimeout(()=>{suppressClipClick=false},0)}marquee=null}
videoTrack.addEventListener('pointerup',finishMarquee);videoTrack.addEventListener('pointercancel',finishMarquee);
$('#timeline-scroll').addEventListener('keydown',e=>{if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='a'){e.preventDefault();selectAllVideoSlots()}});
function beginTimelineDrag(e){
 if(e.button!==0||!scenes().length||!leave())return;
 e.preventDefault();const wasPlaying=editorPlaying;pauseEditor();
 playheadDrag={pointerId:e.pointerId,x:e.clientX,wasPlaying,last:0,raf:0,origin:editorTime()};
 e.currentTarget.setPointerCapture(e.pointerId);e.currentTarget.classList.add('dragging');
 const step=now=>{
  const d=playheadDrag;if(!d)return;
  const scroll=$('#timeline-scroll'),rect=scroll.getBoundingClientRect(),edge=32;
  if(d.x<rect.left+edge)scroll.scrollLeft-=Math.min(24,(rect.left+edge-d.x)*.6);
  else if(d.x>rect.right-edge)scroll.scrollLeft+=Math.min(24,(d.x-(rect.right-edge))*.6);
  if(now-d.last>=16){scrubPlayhead(d.x);d.last=now}
  d.raf=requestAnimationFrame(step);
 };playheadDrag.raf=requestAnimationFrame(step);
 scrubPlayhead(e.clientX);
}
function moveTimelineDrag(e){if(playheadDrag?.pointerId===e.pointerId)playheadDrag.x=e.clientX}

function endPlayheadDrag(e){
 const d=playheadDrag;if(!d||d.pointerId!==e.pointerId)return;
 cancelAnimationFrame(d.raf);playheadDrag=null;e.currentTarget.classList.remove('dragging');
 // The user sees the exact final time instantly; only now touch the decoder.
 d.lastTarget=null;scrubPlayhead(e.clientX,d);const target=d.lastTarget;
 clearScrubPreview();if(e.type==='pointercancel')seekEditor(d.origin,false);
 else {beginSeekMeasurement();seekEditor(target,true);}
 if(d.wasPlaying&&e.type!=='pointercancel')playEditor();
}
for(const target of [$('#playhead-handle'),$('#ruler-track')]){
 target.addEventListener('pointerdown',beginTimelineDrag);
 target.addEventListener('pointermove',moveTimelineDrag);
 target.addEventListener('pointerup',endPlayheadDrag);
 target.addEventListener('pointercancel',endPlayheadDrag);
}
$('#playhead-handle').addEventListener('keydown',e=>{let t=editorTime(),step=e.shiftKey?5:1;if(e.key==='ArrowLeft')t-=step;else if(e.key==='ArrowRight')t+=step;else if(e.key==='Home')t=0;else if(e.key==='End')t=totalTime();else return;e.preventDefault();seekEditor(t,true)});

document.addEventListener('input',e=>{if(e.target.closest('#scene-form')&&editorPlaying&&P?.edit_mode!=='documentary')pauseEditor()});
document.addEventListener('keydown',e=>{if(e.code==='Space'&&!(window.homeVisible&&homeVisible())&&!document.querySelector('dialog[open]')&&!['INPUT','TEXTAREA','SELECT','BUTTON'].includes(document.activeElement.tagName)){e.preventDefault();editorPlaying?pauseEditor():playEditor()}});
function requestEditorTick(){if(!editorTickHandle)editorTickHandle=requestAnimationFrame(tickEditor)}
function tickEditor(){editorTickHandle=0;if(P?.edit_mode==='documentary'){if(editorPlaying)docTick();updatePosition()}else{if(editorPlaying){const t=editorTime();if(t>=totalTime())pauseEditor();else{const i=findActiveIntervalIndex(scenes(),frameAt(t),'frame_in','frame_out');if(i>=0&&i!==sceneIndex){sceneIndex=i;if(!editorMaster)showSource(i,t);renderInspector();markSelected()}if(!editorMaster){showSource(sceneIndex,t);prepareNextSource(sceneIndex,t);drawBackdrop()}}}else if(!editorMaster)drawBackdrop();updatePosition()}if(typeof updateChannelCTA==='function'){const d=window.docTimelineData;updateChannelCTA(P?.edit_mode==='documentary'?(d?.status==='ready'?(d.direct?(narrNode.currentTime||0):(masterNode.currentTime||0)):0):editorTime())}if(typeof updateWatermark==='function')updateWatermark();if(editorPlaying)requestEditorTick()}
// Every 3 s ask only whether anything changed (a few hundred bytes). The full project, with
// every check re-run on the server, is fetched only when the version or a job's progress moved.
// Nothing is polled while the window is hidden.
let pollBusy=false;
setInterval(async()=>{if(!P||dirty||uploading||editorPlaying||document.hidden||pollBusy||window.storyroomTimelineSaving||deletingProjects.has(P.id))return;const id=P.id;pollBusy=true;try{const beat=await api('/api/projects/'+id+'/heartbeat');if(P?.id!==id||deletingProjects.has(id))return;const same=(a,b)=>(a?.status??null)===(b?.status??null)&&(a?.progress??null)===(b?.progress??null)&&(a?.output||null)===(b?.output||null);const autoNow=beat.auto||{},autoWas=P.auto_build||{};if(autoNow.status!==autoWas.status||autoNow.reason!==autoWas.reason||autoNow.progress!==autoWas.progress){P.auto_build={...autoWas,...autoNow};if(!editorPlaying)renderProject()}
if(beat.updated===P.updated&&same(beat.render,P.render)&&same(beat.preview,P.preview)&&same(beat.scene_exports,P.scene_exports))return;const next=await api('/api/projects/'+id);if(P?.id!==id||deletingProjects.has(id))return;if(next.updated!==P.updated||next.render?.status!==P.render?.status||next.render?.progress!==P.render?.progress||next.render?.output!==P.render?.output||next.preview?.status!==P.preview?.status||next.preview?.progress!==P.preview?.progress||next.scene_exports?.status!==P.scene_exports?.status||next.scene_exports?.progress!==P.scene_exports?.progress){P=next;sceneIndex=Math.min(sceneIndex,Math.max(0,P.scenes.length-1));renderProject()}}catch(e){if(P?.id===id&&!deletingProjects.has(id))toast(e.message)}finally{pollBusy=false}},3000);
(async()=>{try{await list();const id=location.hash.match(/^#\/production\/([a-f0-9]{16})$/);if(id)await openProject(id[1]);else{renderEditor();if(window.showHomePage)showHomePage()}requestEditorTick()}catch(e){toast(e.message);renderEditor();requestEditorTick()}})();

// Manual block-map authoring. Only the visible fields are changed; other imported
// production instructions stay on the row. A draft remains in memory until Save.
let mapDraft=null;
function mapValue(row,key){
 if(Object.hasOwn(row,'_edit_'+key))return row['_edit_'+key];
 if(key==='beat')return row.parent_beat_id??row.beat??'1';
 if(key==='media_file')return row.source_file??row.media_file??'';
 if(key==='source_in')return row.source_in??(row.source_in_ms==null?'':mapClock(row.source_in_ms));
 if(key==='source_out')return row.source_out??(row.source_out_ms==null?'':mapClock(row.source_out_ms));
 if(key==='status')return row.status??row.visual_status??'';
 return row[key]??'';
}
function mapClock(ms){const n=Math.round(Number(ms)),h=Math.floor(n/3600000),m=Math.floor(n/60000)%60,s=Math.floor(n/1000)%60;return `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}.${String(n%1000).padStart(3,'0')}`}
function renderMapEditor(){
 const d=mapDraft,r=d.rows[d.index],block=P.srt?.blocks.find(b=>Number(b.number)===Number(r.block??r.srt_blocks?.[0]));
 const field=(label,key,placeholder='')=>`<label>${label}<input data-map-field="${key}" value="${E(mapValue(r,key))}" placeholder="${E(placeholder)}"></label>`;
 $('#map-editor-body').innerHTML=`<p class="small">Save the map, then rebuild the storyboard; saving resets existing approvals.</p>
 <div class="inline"><button type="button" onclick="mapStep(-1)" ${d.index===0?'disabled':''}>← Previous</button><label>Block <select onchange="mapGo(this.value)">${d.rows.map((row,i)=>`<option value="${i}" ${i===d.index?'selected':''}>${E(row.block??row.srt_blocks?.[0]??i+1)}${mapValue(row,'media_file')?'':' · gap'}</option>`).join('')}</select></label><button type="button" onclick="mapStep(1)" ${d.index===d.rows.length-1?'disabled':''}>Next →</button></div>
 <div class="notice"><strong>${E(block?.start_ms!=null?mapClock(block.start_ms):r.start)} → ${E(block?.end_ms!=null?mapClock(block.end_ms):r.end)}</strong><p>${E(block?.text||'Narration not found for this block; review the map against the SRT.')}</p></div>
 <form id="map-row-form" onsubmit="event.preventDefault();saveBlockMap()"><div class="two">${field('Parent beat number','beat','1')}<label>Source filename<input data-map-field="media_file" list="map-source-files" value="${E(mapValue(r,'media_file'))}" placeholder="Select or type original filename"></label>${field('Source IN','source_in','00:00:00.000')}${field('Source OUT (exclusive)','source_out','00:00:04.000')}${field('Status (optional)','status','VIDEO, STILL or CTX')}${field('Footage group (optional)','footage_group','Same label for the same shot')}</div>${field('Picture description (optional)','visible_content','What the picture should show')}<label>Gap note (required if no source)<textarea data-map-field="gap_note" rows="2">${E(mapValue(r,'gap_note'))}</textarea></label><datalist id="map-source-files">${P.assets.map(a=>`<option value="${E(a.original_name||a.name)}"></option>`).join('')}</datalist><div id="map-save-error" class="notice warn" role="alert" hidden></div><div class="dialog-actions"><button type="button" onclick="closeBlockMapEditor()">Cancel</button><button class="new" type="submit">Save block map</button></div></form>`;
 $('#map-row-form').addEventListener('input',e=>{
  const key=e.target.dataset.mapField;if(!key)return;
  r['_edit_'+key]=e.target.value;d.changed=true;dirty=true;
 });
 // Show in-memory changes when returning to a row.
 $('#map-row-form').querySelectorAll('[data-map-field]').forEach(el=>{const k=el.dataset.mapField;if(Object.hasOwn(r,'_edit_'+k))el.value=r['_edit_'+k]});
}
function mapGo(i){mapDraft.index=Number(i);renderMapEditor()}
function mapStep(delta){mapGo(mapDraft.index+delta)}
function closeBlockMapEditor(){if(mapDraft?.changed&&!confirm('Discard unsaved block-map edits?'))return;mapDraft=null;dirty=false;$('#map-editor-dialog').close()}
$('#map-editor-dialog').addEventListener('cancel',e=>{e.preventDefault();closeBlockMapEditor()});
function mapSaveRows(rows){
 return rows.map(original=>{
  const r={...original},value=k=>r['_edit_'+k]??mapValue(r,k);
  const file=value('media_file').trim(),inside=value('source_in').trim(),out=value('source_out').trim(),beat=value('beat').trim(),status=value('status').trim();
  const description=value('visible_content'),group=value('footage_group'),gap=value('gap_note');
  // Normalized imports contain aliases and derived millisecond values. Remove them
  // before re-parsing edited clocks, otherwise the old values conflict with the edits.
  for(const key of Object.keys(r))if(key.startsWith('_edit_'))delete r[key];
  for(const key of ['beat_id','scene','local_file','media_filename','media','file','source','source_file_name','media_file_name','in','out','source_in_time','source_out_time','source_in_ms','source_out_ms','source_out_excl','source_in_ms_planned','source_out_ms_excl_planned'])delete r[key];
  r.beat=beat;r.media_file=file;r.source_file=file;r.source_in=inside;r.source_out=out;
  r.status=status;r.visual_status=status;r.visible_content=description;if('required_visual' in r)r.required_visual=description;r.footage_group=group;r.gap_note=gap;
  return r;
 });
}
async function saveBlockMap(){
 const d=mapDraft;if(!d||!P||P.id!==d.id)return;
 if(P.scenes.length&&!confirm('Saving the map resets storyboard approvals. Rebuild to apply the changes. Continue?'))return;
 const form=$('#map-row-form'),button=form.querySelector('button[type=submit]'),error=$('#map-save-error');button.disabled=true;error.hidden=true;
 try{
  const data=new FormData();data.append('kind','srt_block_map');data.append('expected_srt_signature',d.signature);
  data.append('file',new Blob([JSON.stringify(mapSaveRows(d.rows))],{type:'application/json'}),'authored-block-map.json');
  const result=await api(`/api/projects/${d.id}/upload`,'POST',data);
  if(P?.id===d.id)P=result;
  mapDraft=null;dirty=false;$('#map-editor-dialog').close();renderProject();toast('Block map saved. Rebuild the storyboard to apply it.');
 }catch(e){error.textContent=e.message;error.hidden=false;button.disabled=false}
}

let understandingTarget='',understandingTimer=null;
function understandingSources(){return [...(P?.voiceover?[['narration','Narration · '+P.voiceover.name]]:[]),...(P?.assets||[]).filter(a=>a.kind==='video').map(a=>[a.id,'Video · '+a.name])];}
async function openUnderstanding(){
 if(!P||!leave())return;
 understandingTarget=understandingSources()[0]?.[0]||'';
 $('#understanding-dialog').showModal();await refreshUnderstanding();
}
function closeUnderstanding(){clearTimeout(understandingTimer);$('#understanding-dialog').close()}
$('#understanding-dialog').addEventListener('close',()=>clearTimeout(understandingTimer));
async function refreshUnderstanding(){
 clearTimeout(understandingTimer);if(!P||!understandingTarget)return;
 const id=P.id,target=understandingTarget,body=$('#understanding-body');
 try{
  const [cap,result]=await Promise.all([api('/api/local-understanding/capabilities'),api(`/api/projects/${id}/understanding/${target}`)]);
  if(!$('#understanding-dialog').open||!P||id!==P.id||target!==understandingTarget)return;
  const stages=result.stages||{};
  const stage=(key,label,render)=>{const x=stages[key];if(!x)return '';return `<section class="card"><h3>${E(label)} · ${E(x.status)}</h3>${x.detail?`<p class="small">${E(x.detail)}</p>`:''}${x.result&&['complete','partial','running'].includes(x.status)?render(x.result):''}</section>`};
  body.innerHTML=`${footageReviewHTML(id,target,stages.transcript?.status==="complete" && !result.timing_warning)}
   <label>Media <select id="understanding-source" onchange="understandingTarget=this.value;refreshUnderstanding()">${understandingSources().map(([k,v])=>`<option value="${E(k)}" ${k===target?'selected':''}>${E(v)}</option>`).join('')}</select></label>
   <p class="small">Whisper: ${cap.whisper_model_ready&&cap.faster_whisper?'local model available':'local model or package missing'} · PySceneDetect: ${cap.scenedetect?'installed':'missing'} · Librosa: ${cap.librosa?'installed':'missing'} · vision: ${E(cap.vision_model)} on local Ollama (availability checked when run) · sound events: ${cap.sound_classifier?'local model configured':'optional model not configured'} · diarization: ${cap.speaker_diarization?'local pipeline configured':'optional pipeline not configured'}.</p>
   <p>Status: <strong>${E(result.status)}</strong> ${result.detail?E(result.detail):''}</p>${result.timing_warning?`<p class="small">${E(result.timing_warning)}</p>`:''}<button type="button" onclick="runUnderstanding()" ${['queued','running'].includes(result.status)?'disabled':''}>${result.status==='not_started'?'Analyse locally':'Run analysis again'}</button>
   ${result.status!=='not_started'?`<a class="button" href="/api/projects/${E(id)}/understanding/${E(target)}" target="_blank" rel="noopener">Open JSON report</a>`:''}
   ${cap.sound_classifier&&['complete','partial'].includes(result.status)?'<button type="button" onclick="runSoundEvents()">Analyse sound events only</button>':''}
   ${target!=='narration'&&['complete','partial'].includes(result.status)&&stages.scene_changes?.status==='complete'?'<button type="button" onclick="runVisualOnly()">Analyse video frames only</button>':''}
   ${stage('transcript','Transcript',r=>`<p class="small">Language: ${E(r.language)} · Review transcription before use; downloading does not change the project SRT.</p>${r.segments?.length?`<a class="button" href="/api/projects/${E(id)}/understanding/${E(target)}/transcript.srt" download>Download ${stages.transcript.status==='complete'?'':'partial '}SRT</a>`:''}${target==='narration'&&stages.transcript.status==='complete'&&r.segments?.length?'<button type="button" onclick="applyNarrationTranscript()">Use as project SRT</button>':''}${(r.segments||[]).map(x=>`<p><strong>${Number(x.start_s).toFixed(2)}–${Number(x.end_s).toFixed(2)}s</strong> ${x.speaker?`<span>${E(x.speaker)} · </span>`:''}${E(x.text)}</p>`).join('')||'<p>No speech detected.</p>'}`)}
   ${stage('scene_changes','Scene changes',r=>`<p>${r.length} detected spans</p><p class="small">${r.map(x=>`${Number(x.start_s).toFixed(2)}–${Number(x.end_s).toFixed(2)}s`).join(' · ')}</p>`)}
   ${stage('visual','Visual observations',r=>`<p class="small">${E(r.note)} ${r.sampled_frames} frames across ${r.total_scenes} detected scenes.</p>${r.observations.map(x=>`<p><strong>Frame ${Number(x.frame_time_s).toFixed(2)}s</strong> ${E(x.description)}</p>`).join('')}`)}
   ${stage('audio_features','Audio signal',r=>`<p class="small">${E(r.note)}</p>${(r.low_energy_intervals||[]).length?`<p>Low-energy intervals: ${r.low_energy_intervals.map(x=>`${Number(x.start_s).toFixed(1)}–${Number(x.end_s).toFixed(1)}s`).join(' · ')}</p>`:''}${r.windows.map(x=>`<p>${Number(x.start_s).toFixed(1)}–${Number(x.end_s).toFixed(1)}s · RMS ${x.rms} · centroid ${x.spectral_centroid_hz} Hz${x.low_energy?' · low energy':''}</p>`).join('')}`)}
   ${stage('sound_events','Sound events & music',r=>`<p class="small">${E(r.note)}</p>${r.windows.map(x=>`<p><strong>${Number(x.start_s).toFixed(2)}–${Number(x.end_s).toFixed(2)}s</strong> ${x.predictions.map(p=>`${E(p.label)} (${Number(p.score).toFixed(2)})`).join(' · ')||(x.too_short?'Too short to classify':'No strong prediction')}</p>`).join('')}`)}
   ${stage('speakers','Speakers',r=>`<p class="small">${E(r.note)}</p>${r.turns.map(x=>`<p>${Number(x.start_s).toFixed(2)}–${Number(x.end_s).toFixed(2)}s · ${E(x.speaker)}</p>`).join('')}`)}`;
  bindFootageReview(id,target);
  if(['queued','running'].includes(result.status))understandingTimer=setTimeout(refreshUnderstanding,3000);
 }catch(e){body.textContent='Could not load local analysis: '+e.message}
}
async function runUnderstanding(){
 const id=P.id,target=understandingTarget;
 try{await api(`/api/projects/${id}/understanding/${target}`,'POST');await refreshUnderstanding()}catch(e){toast(e.message)}
}

async function applyNarrationTranscript(){
 if(!P||understandingTarget!=='narration'||uploading)return;
 const id=P.id, replacing=!!(P.srt||P.scenes.length);
 const warning=replacing
  ? 'This machine transcript is unverified. Applying it replaces the existing SRT and clears the storyboard and its approvals. A ready automatic build may start. Continue?'
  : 'This machine transcript is unverified. Use it as the project SRT? A ready automatic build may start. Review the text and timing before export.';
 if(!confirm(warning))return;
 uploading=true;
 try{
  const updated=await api(`/api/projects/${id}/understanding/narration/apply-srt`,'POST',{confirm_generated:true,confirm_replace:replacing});
  if(P?.id!==id)return;
  P=updated;clearTimeout(understandingTimer);$('#understanding-dialog').close();renderProject();await list();
  toast('Machine transcript applied as SRT. Review text and timing before export.');
 }catch(e){toast(e.message)}finally{uploading=false}
}

async function runSoundEvents(){
 if(!P||!understandingTarget)return;
 const id=P.id,target=understandingTarget;
 try{await api(`/api/projects/${id}/understanding/${target}/sound-events`,'POST');await refreshUnderstanding()}catch(e){toast(e.message)}
}

async function runVisualOnly(){
 if(!P||!understandingTarget||understandingTarget==='narration')return;
 const id=P.id,target=understandingTarget;
 try{await api(`/api/projects/${id}/understanding/${target}/visual`,'POST');await refreshUnderstanding()}catch(e){toast(e.message)}
}

// Only the documentary music bed has volume steppers. Narration and MP4 audio
// keep their preview on/off buttons.
window.stepTrackVolume=function(track,delta){
 if(P?.edit_mode==='documentary'&&window.docStepVolume)return window.docStepVolume(track,delta);
 if(track==='music'&&window.docStepVolume)return window.docStepVolume('music',delta);
};

/* ---------------------------------------------------------------------------
   Processing and storage. One panel for the queue, the machine and the cache,
   so the user can always answer "what is it doing and why is it slow".
--------------------------------------------------------------------------- */
let perfTimer=null;
function openPerformance(){
 const d=$('#performance-dialog');if(!d)return;
 d.showModal();
 if(!$('#performance-body').innerHTML.trim())$('#performance-body').innerHTML='<p class="small">Reading what the computer is doing…</p>';
 refreshPerformance();
 clearInterval(perfTimer);perfTimer=setInterval(refreshPerformance,2000);
}
function closePerformance(){
 const d=$('#performance-dialog');if(!d)return;
 clearInterval(perfTimer);perfTimer=null;d.close();
}
function fmtBytes(n){
 if(n==null)return '–';
 if(n<1024)return n+' B';
 if(n<1024**2)return (n/1024).toFixed(0)+' KB';
 if(n<1024**3)return (n/1024**2).toFixed(1)+' MB';
 return (n/1024**3).toFixed(2)+' GB';
}
// Graphics, in the three states that actually differ: a card we can name and read,
// a card we can name but whose memory the driver will not report, and no card found.
// Memory is only shown when it is real -- a made-up zero would read as an idle GPU.
function gpuRow(sys,caps){
 const gpu=(caps&&caps.gpu)||{};
 const name=gpu.name||sys.gpu_name||'';
 if(!name)return '';
 const total=gpu.vram_mb||sys.vram_total_mb;
 const used=sys.vram_used_mb;
 let detail='';
 if(total&&used!=null)detail=`${(used/1024).toFixed(1)} of ${(total/1024).toFixed(1)} GB in use`;
 else if(total)detail=`${(total/1024).toFixed(1)} GB`;
 else detail='memory not reported by the driver';
 const pct=total&&used!=null?Math.min(100,used*100/total):0;
 return `<div class="perf-row"><span>Graphics</span><span>${E(name)}</span></div>
   ${total&&used!=null?`<div class="perf-bar"><i style="width:${pct}%"></i></div>`:''}
   <p class="small">${E(detail)}</p>`;
}
function fmtTime(seconds){
 if(seconds==null)return '';
 if(seconds<60)return Math.max(1,Math.round(seconds))+'s left';
 const m=Math.floor(seconds/60),s=Math.round(seconds%60);
 return m+'m '+s+'s left';
}
let perfBusy=false;
async function refreshPerformance(){
 if(!$('#performance-dialog')?.open||perfBusy)return;   // never stack polls behind a slow answer
 perfBusy=true;
 try{
  const s=await api('/api/system/status');
  try{s.speech=await api('/api/speech/setup')}catch{s.speech=null}
  P&&(P.system_status=s);
  $('#performance-body').innerHTML=performanceHTML(s);
 }catch(e){$('#performance-body').innerHTML=`<p class="small">${E(e.message)}</p>`}
 finally{perfBusy=false}
}
function timelineMeasurementHTML(){
 const d=scrubTimingSummary();
 const row=(label,v)=>v?`<div class="perf-row"><span>${label}</span><span>p50 ${v.p50.toFixed(1)} ms · p95 ${v.p95.toFixed(1)} ms (${v.count} samples)</span></div>`:`<div class="perf-row"><span>${label}</span><span>Not measured yet</span></div>`;
 return row('Playhead UI update (work only)',d.ui)+row('Browser seeked event',d.seek)+
  '<p class="small">Local browser measurements after dragging. UI timings exclude paint; seeked does not guarantee a decoded preview frame. Test using actual source files on this PC.</p>';
}
function performanceHTML(s){
 const q=s.queue,sys=s.queue.system||{},caps=s.encoders||{};
 const bar=v=>`<div class="perf-bar"><i style="width:${Math.max(0,Math.min(100,v||0))}%"></i></div>`;
 const job=j=>`<div class="perf-job">
   <div class="perf-job-top"><strong>${E(j.title)}</strong>
    <span class="perf-state ${j.status}">${E(j.status)}</span></div>
   ${j.detail?`<p class="small">${E(j.detail)}</p>`:''}
   ${j.status==='running'||j.status==='paused'?bar(j.progress):''}
   <p class="small">${j.status==='running'?Math.round(j.progress)+'%':''}
    ${fmtTime(j.remaining_seconds)?' · '+fmtTime(j.remaining_seconds):''}
    ${j.error?' · '+E(j.error):''}</p>
   <div class="perf-actions">
    ${j.status==='running'?`<button type="button" class="btn-quiet" onclick="queueAction('pause',${JSON.stringify(j.id)})">Pause</button>`:''}
    ${j.status==='paused'?`<button type="button" class="btn-quiet" onclick="queueAction('resume',${JSON.stringify(j.id)})">Resume</button>`:''}
    ${['failed','cancelled','interrupted'].includes(j.status)?`<button type="button" class="btn-quiet" onclick="queueAction('retry',${JSON.stringify(j.id)})">Retry</button>`:''}
    ${['running','queued','paused'].includes(j.status)?`<button type="button" class="btn-quiet" onclick="queueAction('cancel',${JSON.stringify(j.id)})">Cancel</button>`:''}
   </div></div>`;
 const running=q.running.concat(q.queued).map(job).join('')||'<p class="small">Nothing is processing.</p>';
 const finished=(q.finished||[]).slice(0,6).map(job).join('');
 const cache=(s.cache||{}),kinds=cache.kinds||{};
 // Only kinds that hold something: a list of dashes tells the user nothing.
 const cacheRows=Object.entries(kinds).filter(([,v])=>v.files)
   .map(([,v])=>`<div class="perf-row"><span>${E(v.label)}</span><span>${fmtBytes(v.bytes)}</span></div>`).join('')
   ||`<p class="small">${cache.checking?'Measuring the cache…':'Nothing cached yet.'}</p>`;
 const hw=caps.checking?'checking…':(caps.hardware||[]).map(h=>h.vendor).join(', ');
 return `<section class="perf-section">
   <h3>Now${q.paused?' · paused':''}</h3>
   ${q.paused?`<button type="button" class="btn-quiet" onclick="queueAction('resume')">Resume all</button>`:`<button type="button" class="btn-quiet" onclick="queueAction('pause')">Pause all</button>`}
   ${running}
  </section>
  <section class="perf-section">
   <h3>This computer</h3>
   <div class="perf-row"><span>Processor</span><span>${Math.round(sys.cpu_percent||0)}%</span></div>${bar(sys.cpu_percent)}
   <div class="perf-row"><span>Memory</span><span>${Math.round(sys.memory_percent||0)}% · ${fmtBytes((sys.memory_available_mb||0)*1024*1024)} free</span></div>${bar(sys.memory_percent)}
   <div class="perf-row"><span>Load</span><span>${E(sys.pressure||'')}</span></div>
   ${sys.disk_free_gb!=null?`<div class="perf-row"><span>Disk</span><span>${sys.disk_free_gb} GB free</span></div>`:''}
   ${gpuRow(sys,caps)}
   <p class="small">${hw?`Hardware encoding available: ${E(hw)}. Used for editing copies only; delivery always uses the software encoder.`:'No hardware encoder detected; processing uses the processor.'}</p>
  </section>
  <section class="perf-section">
   <h3>Timeline seek measurements</h3>
   ${timelineMeasurementHTML()}
  </section>
  <section class="perf-section">
   <h3>Editing copies</h3>
   <label>Quality<select onchange="savePerfSetting({proxy_quality:this.value})">
     ${['540p','720p'].map(v=>`<option value="${v}"${s.settings.proxy_quality===v?' selected':''}>${v}</option>`).join('')}
   </select></label>
   <label class="perf-check"><input type="checkbox" ${s.settings.proxies_enabled?'checked':''} onchange="savePerfSetting({proxies_enabled:this.checked})"> Use editing copies for playback</label>
  </section>
  <section class="perf-section">
   <h3>Storage</h3>
   <label>Cache folder<input value="${E(s.settings.cache_root||'')}" placeholder="${E(s.settings.cache_root_resolved||'')}" onchange="savePerfSetting({cache_root:this.value})"></label>
   <p class="small">${E(s.settings.cache_detail||'')}</p>
   <div class="perf-row"><span>Free on that drive</span><span>${s.disk&&s.disk.free_gb!=null?s.disk.free_gb+' GB':'–'}</span></div>
   ${cacheRows}
   <div class="perf-row"><span>Total cached</span><span>${fmtBytes(cache.total_bytes||0)}</span></div>
   <div class="perf-actions">
    <button type="button" class="btn-quiet" onclick="cacheAction(false)">Clean unused</button>
    <button type="button" class="btn-quiet" onclick="cacheAction(true)">Clear cache</button>
   </div>
   <p class="small">Only cached copies are removed. Original footage and project files are never touched.</p>
  </section>
  ${speechSection(s.speech)}
  <section class="perf-section"><h3>Local media tools</h3><p class="small">Check download, FFprobe, scene detection and speech packages, or install missing tools without leaving Storyroom.</p><button type="button" onclick="openMediaTools()">Open Media Tools</button></section>
  ${finished?`<section class="perf-section"><h3>Finished</h3>${finished}</section>`:''}`;
}
function speechSection(sp){
 if(!sp)return '';
 const prog=sp.progress||{};
 const busy=prog.status==='running';
 const label=sp.step==='both'?'Install both':'Install the '+({package:'package',model:'model'}[sp.step]||'rest');
 return `<section class="perf-section">
  <h3>Speech recognition</h3>
  <p class="small">${E(sp.message)}</p>
  ${busy?`<div class="perf-row"><span>${E(prog.detail||'Installing')}</span><span>…</span></div>`:''}
  ${sp.ready?'':`<div class="perf-actions"><button type="button" class="btn-quiet" onclick="installSpeech()" ${busy?'disabled':''}>${E(label)}</button></div>`}
  ${prog.status==='failed'?`<p class="small">${E(prog.detail||'')}</p>`:''}
  <p class="small">Runs on this computer. Nothing is uploaded.</p>
 </section>`;
}
async function queueAction(action,id){
 try{await api('/api/queue/'+action,'POST',id?{id}:{})}catch(e){toast(e.message)}
 refreshPerformance();
}
async function savePerfSetting(patch){
 try{await api('/api/settings','PATCH',patch);toast('Saved.')}catch(e){toast(e.message)}
 refreshPerformance();
}
async function installSpeech(){
 try{await api('/api/speech/setup','POST',{kind:'auto'});toast('Installing. This can take a few minutes.')}
 catch(e){toast(e.message)}
 refreshPerformance();
}
async function cacheAction(all){
 const label=all?'Clear every cached copy? Originals are untouched.':'Remove cached copies that have not been used recently?';
 if(!confirm(label))return;
 try{const r=await api('/api/cache/cleanup','POST',{all:!!all});toast('Removed '+fmtBytes(r.removed.bytes)+'.')}
 catch(e){toast(e.message)}
 refreshPerformance();
}
