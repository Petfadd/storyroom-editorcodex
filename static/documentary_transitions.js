/* Transitions for Beat-built documentaries.

   A Beat timeline can be split at every subtitle line, so most scene boundaries are not
   picture cuts. This dialog works on the REAL cuts only -- where the footage changes --
   and lets you choose appropriate edits on actual picture changes, or
   request restrained script-aware recommendations (not random variety). The script's own "Cut action" lines can be
   re-applied at any time. Timing never changes: a transition overlaps the outgoing
   shot onto the first frames of the next one. */
(function(){
 const isBeatDoc=()=>P?.edit_mode==='documentary'&&!!P?.documentary_beat_review&&(P.scenes||[]).length>0;
 let docTr={cuts:[],catalogue:null,styles:[],index:0,scope:'one',style:'cinematic',duration:'standard'};

 function fmtAt(s){s=Math.max(0,s||0);const m=Math.floor(s/60),x=Math.floor(s%60);return `${m}:${String(x).padStart(2,'0')}`}
 function labelOf(key){const t=(docTr.catalogue?.transitions||[]).find(x=>x.key===key);return t?t.label:key}

 // The cut that closes the shot holding the selected scene.
 function cutForScene(id){
  const i=(P.scenes||[]).findIndex(s=>s.id===id);if(i<0)return 0;
  const n=docTr.cuts.findIndex(c=>c.scene_index>=i);return n<0?Math.max(0,docTr.cuts.length-1):n;
 }

 async function load(){
  const data=await api(`/api/projects/${P.id}/documentary-transitions?style=${encodeURIComponent(docTr.style)}`);
  docTr.cuts=data.cuts||[];docTr.catalogue=data.catalogue;docTr.styles=data.styles||[];
 }

 function posterForScene(id){
  const scene=(P?.scenes||[]).find(s=>s.id===id),a=(P?.assets||[]).find(a=>a.id===scene?.asset_id);
  return a?`/api/projects/${encodeURIComponent(P.id)}/assets/${encodeURIComponent(a.id)}/poster?v=${encodeURIComponent(a.revision||a.id)}`:'';
 }
 function previewPictures(c){
  const from=posterForScene(c.scene_id),to=posterForScene(c.next_scene_id);
  const style=`--out-photo:url(&quot;${E(from)}&quot;);--in-photo:url(&quot;${E(to)}&quot;)`;
  return `<div class="doc-tr-stages"><div><strong>APPLIED · ${E(labelOf(c.transition||'cut'))}</strong><span class="transition-preview t-${c.transition||'cut'} doc-tr-real" style="${style}"><span></span></span></div>
   <div><strong>SUGGESTED · ${E(labelOf(c.suggested||'cut'))}</strong><span class="transition-preview t-${c.suggested||'cut'} doc-tr-real" style="${style}"><span></span></span><small>Preview only — not applied</small></div></div>`;
 }
 function render(){
  const body=$('#transition-body'),target=$('#transition-target'),controls=document.querySelector('#transition-dialog .transition-controls');
  if(!body||!target||!controls)return;
  // Auto and the bulk actions belong above the 24 cards, where they are seen first.
  if(controls.nextElementSibling!==body)body.parentNode.insertBefore(controls,body);
  const cut=docTr.cuts[docTr.index];
  const used={};docTr.cuts.forEach(c=>{if(c.transition!=='cut')used[c.transition]=(used[c.transition]||0)+1});
  const summary=Object.keys(used).length?Object.entries(used).map(([k,v])=>`${v} ${labelOf(k)}`).join(' · '):'all hard cuts';
  target.innerHTML=docTr.cuts.length?`
   <div class="doc-tr-head">
    <div class="doc-tr-nav">
     <button type="button" onclick="docTrStep(-1)" ${docTr.index>0?'':'disabled'} aria-label="Previous cut">◀</button>
     <strong>Cut ${docTr.index+1} of ${docTr.cuts.length}</strong>
     <button type="button" onclick="docTrStep(1)" ${docTr.index<docTr.cuts.length-1?'':'disabled'} aria-label="Next cut">▶</button>
     <span>at ${fmtAt(cut.at_s)} · ${E(cut.from)} → ${E(cut.to)}${cut.into_speaker?' · into a sound bite':''}</span>
     <button type="button" onclick="docTrPreview('applied')">▶ Watch applied transition</button>
    </div>
    <div class="doc-tr-comparison" aria-live="polite">
     <span>Applied: <strong>${E(labelOf(cut.transition||'cut'))}</strong> (${E(cut.source==='auto'?'Auto':cut.source==='script'?'Script':cut.source==='manual'?'Manual':'Default')})</span>
     <span class="doc-tr-suggest">Suggested: <strong>${E(labelOf(cut.suggested||'cut'))}</strong> (not applied)</span>
    </div>
    <p class="small doc-tr-reason">${cut.suggested_moment?`<span class="doc-tr-moment">${E(String(cut.suggested_moment).replace(/_/g,' '))}</span> `:''}<strong>Why:</strong> ${E(cut.suggested_reason||'No scene evidence yet; use a hard cut.')}</p>
    ${previewPictures(cut)}
    <div class="doc-tr-actions">
     <button type="button" onclick="docTrPreview('applied')">▶ Preview applied</button>
     <button type="button" onclick="docTrPreview('suggested')">▶ Preview suggested</button>
     <button type="button" onclick="docTrApplySuggestion()" ${cut.suggested===cut.transition?'disabled':''}>Apply suggestion to this cut</button>
    </div>
    <div class="doc-tr-scope">
     <label><input type="radio" name="doc-tr-scope" value="one" ${docTr.scope==='one'?'checked':''} onchange="docTrScope('one')"> This cut</label>
     <label><input type="radio" name="doc-tr-scope" value="all" ${docTr.scope==='all'?'checked':''} onchange="docTrScope('all')"> Every cut (${docTr.cuts.length})</label>
     <span class="small">${docTr.cuts.length} picture cuts · Applied across the film: ${E(summary)}</span>
    </div>
   </div>`:'This timeline has no picture cuts to put a transition on.';
  const current=cut?.transition||'cut',suggested=cut?.suggested||'cut';
  body.innerHTML=(docTr.catalogue?.transitions||[]).map(t=>`
   <button type="button" class="transition-card t-${t.key} ${docTr.scope==='one'&&t.key===current?'current':''} ${docTr.scope==='one'&&t.key===suggested?'recommended':''}" onclick="docTrChoose('${t.key}')" aria-label="${E(t.label)}${t.key===current?', applied':''}${t.key===suggested?', suggested':''}">
    <span class="transition-preview t-${t.key}"><span></span></span>
    <strong>${E(t.label)}</strong><small>${E(t.detail)}</small>
    ${docTr.scope==='one'&&t.key===current?`<span class="tr-state">APPLIED · ${cut?.source==='script'?'Script':cut?.source==='auto'?'Auto':cut?.source==='manual'?'Manual':'Default'}</span>`:''}
    ${docTr.scope==='one'&&t.key===suggested?'<span class="tr-state suggested">SUGGESTED · Not applied</span>':''}
   </button>`).join('');
  controls.innerHTML=`
   <label>Length<select onchange="docTrDuration(this.value)">
    ${(docTr.catalogue?.durations||[]).map(d=>`<option value="${d.key}" ${d.key===docTr.duration?'selected':''}>${E(d.label)}</option>`).join('')}
   </select></label>
   <label>Documentary style<select onchange="docTrStyle(this.value)">
    ${docTr.styles.map(s=>`<option value="${s.key}" ${s.key===docTr.style?'selected':''}>${E(s.label)}</option>`).join('')}
   </select></label>
   <button type="button" class="new" onclick="docTrAuto(this)">Auto Suggest · every cut</button>
   <button type="button" onclick="docTrApply({action:'script'})">Use the script's Cut actions</button>
   <button type="button" onclick="docTrApply({action:'clear'})">All hard cuts</button>
   ${docTr.applied?`<p class="doc-tr-applied" style="flex-basis:100%;margin:0">✓ ${E(docTr.applied)}</p>`:''}
   <p class="small" style="flex-basis:100%;margin:0">Auto Suggest reads each cut: who is speaking, what the narration says next (time jumps, places, reveals, grief, danger), whether a photo arrives, and where it falls in the film. It picks a fitting transition for each moment and never repeats the one just used. Cuts you set by hand or from the script are kept. Timing, audio and the SRT do not change.</p>`;
 }

 window.docTrState=()=>docTr;
 window.docTrStep=d=>{docTr.index=Math.max(0,Math.min(docTr.cuts.length-1,docTr.index+d));render()};
 window.docTrScope=s=>{docTr.scope=s;render()};
 window.docTrStyle=async s=>{docTr.style=s;try{await load();render()}catch(e){toast(e.message)}};
 window.docTrDuration=d=>{docTr.duration=d};
 // Monitor preview uses genuine outgoing/incoming clips when the source player
 // can decode them; it never saves the suggested effect until Apply is clicked.
 window.docTrPreview=kind=>{
  const c=docTr.cuts[docTr.index];if(!c)return;
  const suggested=kind==='suggested',key=suggested?(c.suggested||'cut'):(c.transition||'cut');
  window.docTransitionPreviewOverride=suggested?{scene_id:c.scene_id,at_s:c.at_s,key,frames:c.suggested_frames||15}:null;
  window.docTransitionPreviewInfo={kind:suggested?'Suggested':'Applied',at_s:c.at_s,label:labelOf(key)};
  closeTransitionLibrary();pauseEditor();
  if(typeof docSeekTimeline==='function'){
   docSeekTimeline(Math.max(0,c.at_s-1.6),false);
   setTimeout(()=>{if(P?.edit_mode==='documentary'&&typeof docPlayTimeline==='function')docPlayTimeline()},180);
  }
 };
 window.docTrSeek=()=>window.docTrPreview('applied');
 window.docTrApplySuggestion=()=>{
  const c=docTr.cuts[docTr.index];if(!c)return;
  return window.docTrApply({action:'set',scene_id:c.scene_id,key:c.suggested||'cut',frames:Math.max(4,c.suggested_frames||15)});
 };
 window.docTrChoose=key=>{
  const cut=docTr.cuts[docTr.index];
  if(docTr.scope==='all')return window.docTrApply({action:'all',key,duration:docTr.duration});
  if(!cut)return;return window.docTrApply({action:'set',key,scene_id:cut.scene_id,duration:docTr.duration});
 };
 // Storyroom applies stable choices for the same script; pressing again is idempotent.
 window.docTrAuto=async function(button){
  if(button){button.disabled=true;button.textContent='Reading each moment…'}
  const style=docTr.style,label=(docTr.styles.find(x=>x.key===style)||{}).label||style;
  await window.docTrApply({action:'auto',style,duration:docTr.duration,camera_auto:false});
  docTr.applied=`Auto Suggest applied · ${label}: ${docTr.cuts.filter(c=>c.transition!=='cut').length} of ${docTr.cuts.length} cuts now have a transition. Hand-picked and script cuts were kept.`;
  render();
 };
window.docTrApply=async function(body){
  try{
   const data=await api(`/api/projects/${P.id}/documentary-transitions`,'POST',body);
   P=data.project;docTr.cuts=data.cuts||[];if(body.action!=='auto')docTr.applied='';
   window.docTransitionPreviewOverride=null;window.docTransitionPreviewInfo=null;
   await load();
   const parts=Object.entries(data.summary||{}).map(([k,v])=>`${v} ${labelOf(k)}`);
   toast(body.action==='auto'?`Story-led transitions applied; manual/script decisions protected.`:parts.length?`Transitions set: ${parts.join(', ')}.`:'Every cut is a hard cut.');
   render();renderInspector?.();renderProject?.();
  }catch(e){toast(e.message)}
 };

 // Take over the existing Transitions button for Beat documentaries only.
 const generalOpen=window.openTransitionLibrary;
 window.openTransitionLibrary=async function(sceneId){
  const controls=document.querySelector('#transition-dialog .transition-controls');
  if(controls&&!controls.dataset.general)controls.dataset.general=controls.innerHTML;
  if(!isBeatDoc()){
   if(controls&&controls.dataset.general)controls.innerHTML=controls.dataset.general;
   const body=$('#transition-body');if(controls&&body&&body.nextElementSibling!==controls)body.after(controls);
   return generalOpen(sceneId)}
  try{await load()}catch(e){toast(e.message);return}
  docTr.index=cutForScene(sceneId||scenes()[sceneIndex]?.id);
  render();
  const dlg=$('#transition-dialog');if(dlg&&!dlg.open)dlg.showModal();
 };
})();
