/* Storyroom local media setup: explicit, opt-in installations only.
   Status checks are read-only; no model or binary is fetched unless a button is clicked. */
let mediaToolsPolling = null;
let mediaToolsRequestRunning = false;
const MEDIA_TOOL_ROWS = [
  ['python', 'Python', 'Existing Storyroom runtime', false],
  ['ffmpeg', 'FFmpeg', 'Already used for video processing and rendering', false],
  ['ffprobe', 'FFprobe', 'Video/audio codec, frame-rate and duration information', true],
  ['yt-dlp', 'yt-dlp + challenge solver', 'Download S01, S02, etc. from the footage sheet', true],
  ['youtube-runtime', 'YouTube JavaScript runtime (Deno)', 'Helps yt-dlp handle current YouTube challenges', true],
  ['scenedetect', 'PySceneDetect', 'Detect scene boundaries without editing your footage', true],
  ['faster-whisper', 'faster-whisper package', 'CPU dialogue transcription in Storyroom', true],
  ['whisper-model', 'Whisper speech model', 'One-time download; required for offline transcription', true],
  ['whisperx', 'WhisperX', 'Advanced alignment deferred; not required for core setup', false],
];
function openMediaTools(){
 const dlg=document.querySelector('#media-tools-dialog');
 if(!dlg)return;
 if(!dlg.open)dlg.showModal();
 const b=document.querySelector('#media-tools-body');
 if(b)b.innerHTML='<p class="small">Checking locally installed tools…</p>';
 refreshMediaTools(true);
 if(mediaToolsPolling)clearInterval(mediaToolsPolling);
 mediaToolsPolling=setInterval(()=>{if(dlg.open)refreshMediaTools(false);else closeMediaTools()},2500);
}
function closeMediaTools(){
 if(mediaToolsPolling)clearInterval(mediaToolsPolling);
 mediaToolsPolling=null;
 const d=document.querySelector('#media-tools-dialog');if(d?.open)d.close();
}
function mediaToolRows(data){
 const busy=data.install?.status==='running';
 const progress=data.install||{};
 const rows=MEDIA_TOOL_ROWS.map(([id,label,desc,canInstall])=>{
  const x=data.tools?.[id]||{};
  const ready=x.ready===true;
  const can=canInstall && !ready && !(id==='ffprobe'&&data.platform!=='win32') && id!=='whisperx';
  const unavailable=(id==='ffprobe'&&data.platform!=='win32');
  const state=ready?'Installed':id==='whisperx'?'Deferred':unavailable?'System setup required':'Not ready';
  const vers=x.version?`<span class="small" style="display:block;overflow-wrap:anywhere">${E(x.version)}</span>`:'';
  const hint=x.detail?`<span class="small" style="display:block;overflow-wrap:anywhere">${E(x.detail)}</span>`:'';
  return `<div class="perf-row" style="align-items:center;gap:10px;border-bottom:1px solid var(--border,#ddd);padding:10px 0">
    <div style="flex:1;min-width:0"><strong>${E(label)}</strong><p class="small">${E(desc)}</p>${vers}${hint}</div>
    <div style="text-align:right;min-width:110px"><strong>${E(state)}</strong>
      ${can?`<div style="margin-top:6px"><button type="button" class="btn-quiet" onclick="installMediaTool('${id}')" ${busy?'disabled':''}>Install</button></div>`:''}
    </div></div>`;
 }).join('');
 const progressPanel=progress.status==='running'?`<div class="notice"><strong>Installing ${E(progress.tool||'tool')}…</strong><p>${E(progress.detail||'Processing')}</p></div>`:
    progress.status==='failed'?`<div class="notice warn"><strong>${E(progress.tool||'Tool')} installation failed</strong><p>${E(progress.error||progress.detail||'Unknown error')}</p></div>`:
    progress.status==='done'?`<div class="notice"><strong>Installation complete:</strong> ${E(progress.tool||'tool')}</div>`:'';
 const recent=(progress.log||[]).slice(-6);
 return `<div class="perf-section"><p>Install only the tools you need. Downloads happen on this PC when you click Install; models and executables are kept in Storyroom's local folder. Nothing is installed by opening this window.</p>
 <p class="small">Python and FFmpeg are existing core dependencies. The Deno helper is recommended for recent yt-dlp YouTube support. WhisperX remains optional and is not included in this setup.</p>
 ${progressPanel}${rows}<div class="perf-actions"><button type="button" onclick="refreshMediaTools(true)">Refresh status</button></div>
 ${recent.length?`<details><summary>Recent install messages</summary><pre style="white-space:pre-wrap;word-break:break-word">${recent.map(E).join('\n')}</pre></details>`:''}
 <p class="small">If installation fails, check your internet connection and Python version, then use the displayed error. Storyroom's existing projects and source media are not deleted or modified.</p>
 </div>`;
}
async function refreshMediaTools(force){
 if(mediaToolsRequestRunning)return;
 const dlg=document.querySelector('#media-tools-dialog');if(!dlg?.open)return;
 mediaToolsRequestRunning=true;
 try{
  const data=await api('/api/media-tools'+(force?'?refresh=1':''));
  if(dlg.open)document.querySelector('#media-tools-body').innerHTML=mediaToolRows(data);
 }catch(e){
  const b=document.querySelector('#media-tools-body');if(b)b.innerHTML=`<div class="notice warn">Media tool check failed: ${E(e.message)}</div>`;
 }finally{mediaToolsRequestRunning=false;}
}
async function installMediaTool(tool){
 if(!confirm('Install '+tool+' locally inside Storyroom? This may download software or model files to your computer.'))return;
 try{
  await api('/api/media-tools/install','POST',{tool});
  toast('Installing '+tool+' in the background.');
  refreshMediaTools(true);
 }catch(e){toast(e.message)}
}

async function inspectAssetMetadata(assetId){
 try{
  const d=await api(`/api/projects/${P.id}/assets/${encodeURIComponent(assetId)}/media-info`);
  const lines=(d.streams||[]).map(x=>[x.type,x.codec,
    x.width&&x.height?`${x.width}×${x.height}`:'',
    x.fps?`FPS ${x.fps}`:'',x.sample_rate?`${x.sample_rate} Hz`:''].filter(Boolean).join(' · '));
  alert([d.filename, d.duration_s?`Duration ${Number(d.duration_s).toFixed(3)}s`:'',...lines].filter(Boolean).join('\n'));
 }catch(e){toast(e.message)}
}

/* Required-library banner. When a library Storyroom needs (for example PyAV) is
   missing, say which one and what it does, and offer a one-click repair that installs
   it into Storyroom's own Python environment. No restart is needed afterwards. */
let dependencyPoll=null;
function dependencyBanner(){
 let bar=document.getElementById('dependency-banner');
 if(!bar){bar=document.createElement('div');bar.id='dependency-banner';bar.className='dependency-banner';bar.setAttribute('role','alert');document.body.prepend(bar)}
 return bar;
}
function renderDependencyBanner(state){
 const bar=dependencyBanner();
 if(!state||state.ok&&state.repair?.status!=='running'){bar.hidden=true;return}
 const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const names=(state.missing||[]).map(m=>`<strong>${esc(m.package)}</strong> (${esc(m.used_for)})`).join('; ');
 const job=state.repair||{};
 const busy=job.status==='running';
 const failed=job.status==='error';
 bar.hidden=false;
 bar.innerHTML=`<span>${busy?'Installing missing libraries… this can take a few minutes.':`Storyroom is missing: ${names}.`}${failed?' The last repair did not finish — check the internet connection and try again.':''}</span>
  <button type="button" ${busy?'disabled':''} onclick="repairDependencies()">${busy?'Installing…':'Repair now'}</button>
  ${failed&&job.log?`<details><summary>Details</summary><pre>${esc(job.log)}</pre></details>`:''}`;
}
async function checkDependencies(){
 try{const r=await fetch('/api/dependencies');const state=await r.json();renderDependencyBanner(state);
  clearTimeout(dependencyPoll);
  if(state.repair?.status==='running')dependencyPoll=setTimeout(checkDependencies,3000);
  else if(state.ok&&state.repair?.status==='done'&&!window.__dependencyReloaded){window.__dependencyReloaded=true;toast('Libraries installed. Reloading the editor…');setTimeout(()=>location.reload(),1200)}
  return state}catch{return null}
}
async function repairDependencies(){
 try{const r=await fetch('/api/dependencies/repair',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});renderDependencyBanner(await r.json());clearTimeout(dependencyPoll);dependencyPoll=setTimeout(checkDependencies,2000)}catch(e){toast('Repair could not start: '+e.message)}
}
setTimeout(checkDependencies,400);

// Header build label comes from the running server, so it always names the real build.
(async()=>{try{const r=await fetch('/api/build-info');const d=await r.json();for(const el of document.querySelectorAll('#editor-build-label,#home-build-label'))
 if(d.build){const m=String(d.build).match(/-v(\d+)$/);el.textContent=m?`V${m[1]}`:d.build;el.title=`Installed build: ${d.build}`}}catch{}})();
