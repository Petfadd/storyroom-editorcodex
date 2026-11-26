/* Separate, non-destructive documentary handoff planning. This is not an export. */
let docPlan=null,docPid=null,docRun=0,docTimer=null,docSpeechBusy='';
const docTime=n=>Number(n).toFixed(3)+' s';
function stopDocumentaryPreview(){docRun++;clearInterval(docTimer);docTimer=null;for(const id of ['#doc-narration','#doc-source'])$(id)?.pause();const s=$('#doc-preview-status');if(s)s.textContent='Preview stopped.'}
function closeDocumentary(){stopDocumentaryPreview();clearTimeout(docAudioPoll);$('#documentary-dialog').close()}
$('#documentary-dialog').addEventListener('cancel',()=>stopDocumentaryPreview());
async function openDocumentary(){
 if(!P)return;pauseEditor();pauseManagementMedia();docPid=P.id;docPlan=null;$('#documentary-body').innerHTML='<p>Loading the separate sound-bite plan…</p>';if(!$('#documentary-dialog').open)$('#documentary-dialog').showModal();
 try{const data=await api(`/api/projects/${docPid}/documentary-bites`);if(P?.id!==docPid||!$('#documentary-dialog').open)return;docPlan=data;renderDocumentary();pollDocumentaryAudio()}catch(e){$('#documentary-body').innerHTML=`<p class="notice warn">${E(e.message)}</p>`}
}
async function loadStrictBeatReview(){
 const box=$('#strict-beat-review');if(!box||!docPid)return;
 box.innerHTML='<p class="small">Checking the saved script, exact sources and review records…</p>';
 try{
  const state=await api(`/api/projects/${docPid}/documentary-beat-review`);
  if(P?.id!==docPid||!$('#strict-beat-review'))return;
  box.innerHTML=strictBeatReviewHTML(state);
  box.querySelectorAll('[data-strict-review]').forEach(button=>button.addEventListener('click',()=>{
   const mode=button.dataset.strictReview,label=button.dataset.beat;
   let detail='';
   if(mode==='wrong')detail=prompt(`What is wrong with the visual in Beat ${label}?`,'')||'';
   else if(mode==='exception'){
    detail=prompt(`What specific exception are you approving for Beat ${label}?`,'')||'';
    if(detail&&!confirm('Record this as an explicit user-approved exception for this Beat?'))return;
   }
   if(mode==='wrong'||mode==='exception')if(!detail.trim())return;
   saveStrictBeatReview(label,mode,detail);
  }));
 }catch(e){box.innerHTML=`<p class="notice warn">${E(e.message)}</p>`}
}
function strictBeatReviewHTML(state){
 const statusClass=s=>s==='VISUAL REVIEWED'?'':s==='USER-APPROVED EXCEPTION'?'warn':'warn';
 const items=(state.beats||[]).map((b,i)=>{
  const review=b.review||{},fr=b.frame_range||{},assetUrl=b.asset_id?`/api/projects/${encodeURIComponent(docPid)}/assets/${encodeURIComponent(b.asset_id)}/source-file`:'';
  const src=assetUrl?`${assetUrl}#t=${(b.source_in_ms/1000).toFixed(3)},${(b.source_out_ms/1000).toFixed(3)}`:'';
  const cues=(b.srt_cues||[]).map(c=>`<li>${E(docTime(c.start_ms/1000))}–${E(docTime(c.end_ms/1000))} · ${E(c.text)}</li>`).join('');
  const dialogue=b.kind==='sound_bite'?`<p><strong>Declared speaker:</strong> ${E(b.speaker||'Missing')} ${b.speaker_role?`· ${E(b.speaker_role)}`:''}</p><p><strong>Exact spoken dialogue:</strong> ${E(b.exact_dialogue||'Not supplied')}</p><p class="small">Listen and watch this exact interval to confirm the declared speaker is visibly speaking. Storyroom does not identify people automatically.</p>`:'';
  const frame=fr.frame_aligned_in_ms!=null?`<p class="small">Nearest source-frame interval: ${(fr.frame_aligned_in_ms/1000).toFixed(3)}–${(fr.frame_aligned_out_ms/1000).toFixed(3)}s · IN ${fr.in_delta_ms>=0?'+':''}${fr.in_delta_ms.toFixed(1)}ms · OUT ${fr.out_delta_ms>=0?'+':''}${fr.out_delta_ms.toFixed(1)}ms</p>`:'<p class="small">Source-frame quantisation details are unavailable.</p>';
  return `<details class="notice ${statusClass(b.status)}" ${i===0?'open':''}>
   <summary><strong>Beat ${E(b.label)}</strong> · ${E(b.validation_status||'')} · ${E(b.status)} · ${E(b.source_file)}</summary>
   <p><strong>Type:</strong> ${E(b.kind==='narration'?'VOICE OVER':'DOCUMENTARY SOUND BITE')} · <strong>Visual ID:</strong> ${E(b.visual_id||'Not specified')}</p>
   ${b.kind==='narration'?`<p><strong>Narration clock:</strong> ${E(docTime(b.narration_in_ms/1000))}–${E(docTime(b.narration_out_ms/1000))}</p><p><strong>SRT cue text:</strong></p><ul>${cues||'<li>No SRT cues cover this Beat.</li>'}</ul>`:''}
   <p><strong>Visual direction:</strong> ${E(b.direction||'Not specified')}</p><p><strong>Continuity note:</strong> ${E(b.continuity_note||'Not specified')} ${b.anchor_id?`· <strong>Anchor ID:</strong> ${E(b.anchor_id)}`:''}</p>
   <p><strong>Exact source:</strong> ${E(b.source_file)} · <strong>Source IN/OUT:</strong> ${E(docTime(b.source_in_ms/1000))}–${E(docTime(b.source_out_ms/1000))} · <strong>Duration:</strong> ${E(docTime((b.source_out_ms-b.source_in_ms)/1000))}</p>${frame}
   ${dialogue}${src?`<video controls preload="metadata" ${b.kind==='narration'?'muted':''} style="width:min(100%,620px);max-height:360px;background:#111" src="${E(src)}"></video>`:'<p class="notice warn">Exact source preview is unavailable.</p>'}
   ${review.detail?`<p><strong>Review note:</strong> ${E(review.detail)}</p>`:''}
   ${b.frame_adjustment?`<p class="notice warn"><strong>USER-APPROVED FRAME EXCEPTION:</strong> ${E(b.frame_adjustment.detail)} · ${E(b.frame_adjustment.delta_frames>0?'+1 source frame':'−1 source frame')} · ${new Date(b.frame_adjustment.approved_at*1000).toLocaleString()}</p>`:''}
   <p><button type="button" data-strict-review="reviewed" data-beat="${E(b.label)}">Mark visual reviewed</button> <button type="button" data-strict-review="wrong" data-beat="${E(b.label)}">Flag as wrong</button> <button type="button" data-strict-review="exception" data-beat="${E(b.label)}">Approve exception</button></p>
  </details>`;
 }).join('');
 const invalidated=state.invalidated_frame_decisions;
 return `<p class="small">Technical validation confirms the named file and timing. It does not verify identity, location, action or context; review each playable source interval yourself. Soundbite video retains source audio; narration previews are muted.</p>${state.stale?'<p class="notice warn">The script or source changed after review. Rebuild the storyboard and review every Beat again.</p>':''}${invalidated?.changes?.length?`<p class="notice warn">A rebuild invalidated ${invalidated.changes.length} prior frame approval(s). Review the current frame ranges and approve any one-frame exception again.</p>`:''}${state.issues?.length?`<ul class="issues">${state.issues.map(x=>`<li>${E(x)}</li>`).join('')}</ul>`:''}${items||'<p>No documentary Beat storyboard has been built.</p>'}`;
}
async function saveStrictBeatReview(label,status,detail){
 try{
  await api(`/api/projects/${docPid}/documentary-beat-review/${encodeURIComponent(label)}`,'POST',{status,detail});
  await loadStrictBeatReview();
  loadDocumentaryReadiness(docPid);
 }catch(e){toast(e.message)}
}
function documentaryTimelineNotice(){
 const bites=docPlan?.bites||[],stale=bites.some(b=>b.stale_reasons?.length),timeline=window.docTimelineData;
 const current=timeline?.id===P?.id&&timeline?.version===P?.updated&&timeline?.revision===docPlan?.revision;
 const count=bites.length?`${bites.length} saved sound bite${bites.length===1?'':'s'}.`:'No sound bites are saved.';
 let preview=!current||timeline?.loading?'Timeline preview status is loading.':stale?'A sound bite needs review because its source or narration changed.':timeline?.status==='ready'&&timeline.url?(timeline.direct?'Browser timeline preview is ready; cuts are approximate.':'Timeline preview is ready.'):['queued','running'].includes(timeline?.status)?'Timeline preview is being prepared.':timeline?.status==='error'?`Timeline preview could not be prepared: ${timeline.detail||'unknown error'}.`:'Prepare the timeline preview to play it.';
 const exportText=P?.documentary_beat_review?'Use Render MP4 after the source, timing and approval checks.':'Final MP4 export is not available for this storyboard type.';
 return `<div id="doc-timeline-notice" class="notice ${stale||timeline?.status==='error'?'warn':''}" role="status"><strong>Documentary timeline.</strong> ${E(count)} ${E(preview)} ${E(exportText)}</div>`;
}
window.updateDocumentaryTimelineNotice=function(){const el=$('#doc-timeline-notice');if(el&&P?.id===docPid&&docPlan)el.outerHTML=documentaryTimelineNotice()};
function renderDocumentary(){
 if(!P||!docPlan)return;
 $('#documentary-body').innerHTML=`${documentaryTimelineNotice()}
 ${P?.documentary_beat_review?.strict_execution?'<section class="card"><h3>Production script visual review</h3><p>Each Beat keeps its script source range. Preview it here, then record a human review decision.</p><div id="strict-beat-review"><p class="small">Loading strict Beat review…</p></div></section>':''}
 <section class="card" id="doc-cutaway-editor"><h3>Interview picture cutaways</h3>
 <p class="small">Keep the original interview audio continuous. Upload a reviewed CUTAWAY-### ledger to switch to authentic source video or still photographs, then return to the speaker automatically. Film times use the finished-video clock, not narrator SRT time.</p>
 <div class="inline"><input type="file" id="doc-cutaway-file" accept=".json,.md,.txt,application/json,text/markdown,text/plain" onchange="docLoadCutawayFile(this)"><button type="button" onclick="docSaveCutawayLedger()">Import cutaway plan</button></div>
 <label>Paste cutaway ledger (JSON or Markdown table)<textarea id="doc-cutaway-ledger" rows="5" placeholder='{"version":1,"cutaways":[{"id":"CUTAWAY-001","soundbite_beat":"028","timeline_in":"00:02:50.000","timeline_out":"00:03:00.000","picture_source":"S04.mp4","source_in":"00:00:20.000","source_out":"00:00:30.000","reason":"Reviewed evidence shot"}]}'></textarea></label>
 <div id="doc-cutaway-status" role="status">Loading cutaway review…</div></section>
 <section class="card"><h3>Documentary audio preview</h3><p>Prepare a separate WAV with narration and the saved sound bites. The original files remain unchanged.</p><button type="button" onclick="prepareDocumentaryAudio()">Prepare documentary audio preview</button><div id="doc-audio-status"><p>Checking audio status…</p></div></section><section class="card"><h3>Adjusted subtitles</h3><p>Download a separate SRT shifted around the saved bites. If a pause crosses a cue, listen and choose the last word spoken before that pause. The original SRT is untouched.</p>${docSubtitleSplitHTML()}<button type="button" onclick="saveDocumentaryExportSplits()">Use these reviewed splits for MP4 export</button> <button type="button" onclick="downloadDocumentarySrt()">Download adjusted SRT</button></section><section class="card"><h3>Saved sound bites (${docPlan.bites.length})</h3><p>Each bite can show captions of what is actually said in that footage. Speech is transcribed locally from the saved source IN/OUT; nothing is uploaded, and the original SRT and narration are untouched.</p><p class="small">Machine transcription, not identity verification. Listen to each bite before publishing. The scripted caption stays available as a label.</p><div id="bite-speech-status"><p class="small">Checking the local speech model…</p></div>${docPlan.bites.length?docPlan.bites.map(b=>docBiteSpeechRow(b)).join(''):'<p>No sound bites saved.</p>'}</section>`;
 checkBiteSpeech();docRefreshCutaways();if(P?.documentary_beat_review?.strict_execution)loadStrictBeatReview();
}
function docBiteSpeechRow(b){
 const speech=b.speech||[],busy=docSpeechBusy===b.id;
 return `<div class="notice ${b.stale_reasons?.length?'warn':''}" data-bite-speech="${E(b.id)}"><strong>Pause at ${docTime(b.pause_s)}</strong> · ${E(b.asset_name)} ${docTime(b.source_in_s)}–${docTime(b.source_out_s)}${b.stale_reasons?.length?`<p>${b.stale_reasons.map(E).join(' ')}</p>`:''}
 <p class="small">Scripted caption: ${E(b.script_caption&&!['none','n/a','na','—','-'].includes(String(b.script_caption).trim().toLowerCase())?b.script_caption:'none')}</p>
 ${speech.length?`<details open><summary>Spoken words (${speech.length} line${speech.length===1?'':'s'})</summary>${speech.map(x=>`<p>“${E(x.text)}”</p>`).join('')}</details><button type="button" ${busy?'disabled':''} onclick="transcribeBiteSpeech('${E(b.id)}')">${busy?'Transcribing…':'Transcribe again'}</button> <button type="button" ${busy?'disabled':''} onclick="removeBiteSpeech('${E(b.id)}')">Remove spoken caption</button>`:`<button type="button" ${busy?'disabled':''} title="Transcribe this bite's own audio on this computer" onclick="transcribeBiteSpeech('${E(b.id)}')">${busy?'Transcribing…':'Add spoken-word caption'}</button>`}</div>`}
function checkBiteSpeech(){fetch(`/api/projects/${docPid}/documentary-bite-speech`).then(r=>r.json()).then(d=>{const box=$('#bite-speech-status');if(!box)return;box.innerHTML=d.available?`<p class="small">Local speech model: <strong>${E(d.model)}</strong> · CPU only, no upload.</p>`:`<p class="notice warn">${E(d.detail)}</p>`}).catch(e=>{const box=$('#bite-speech-status');if(box)box.innerHTML=`<p class="notice warn">${E(e.message)}</p>`})}
async function transcribeBiteSpeech(id){
 if(!docPlan||docSpeechBusy)return;const bite=docPlan.bites.find(b=>b.id===id);if(!bite)return;
 if(bite.stale_reasons?.length){toast('Review this stale sound bite before transcribing it.');return}
 docSpeechBusy=id;renderDocumentary();
 try{const data=await api(`/api/projects/${docPid}/documentary-bites/${id}/speech`,'POST',{revision:docPlan.revision});if(P?.id!==docPid)return;
  docPlan=await api(`/api/projects/${docPid}/documentary-bites`);
  toast(`${data.segments.length} spoken caption line(s) saved. Listen to the bite before publishing.`);reloadDocTimeline();
 }catch(e){toast(e.message)}finally{docSpeechBusy='';if(P?.id===docPid&&docPlan)renderDocumentary()}
}
async function removeBiteSpeech(id){
 if(!docPlan)return;
 try{await api(`/api/projects/${docPid}/documentary-bites/${id}/speech`,'DELETE');
  docPlan=await api(`/api/projects/${docPid}/documentary-bites`);toast('Spoken caption removed; the scripted caption is used again.');reloadDocTimeline()
 }catch(e){toast(e.message)}finally{if(P?.id===docPid&&docPlan)renderDocumentary()}
}
function documentaryDeliveryHTML(){
 const beat=!!P.documentary_beat_review,r=P.render||{},running=['queued','running'].includes(r.status);
 $('#crumb').textContent=P.title;$('#manage-title').textContent='Documentary delivery';$('#content').innerHTML=`<div class="notice ${beat?'':'warn'}"><strong>${beat?'Documentary MP4 export':'Final documentary MP4 is not available for this storyboard'}</strong><p>${beat?'Render MP4 checks the cue shots, source frames and approvals. Subtitles and on-screen script labels are optional in the Render page. The script and SRT timing remain unchanged.':'This export path supports script-driven Beat storyboards.'}</p><div id="doc-delivery-readiness">Checking saved project…</div>${running?`<progress max="100" value="${r.progress||0}"></progress><p>${E(r.stage)} · ${E(r.detail||'')}</p><button type="button" onclick="cancelExport()">Cancel export</button>`:''}${r.error?`<p class="notice warn">${E(r.error)}</p>`:''}${r.url?`<p><a class="download" href="${E(r.url)}?download=1">↓ Download ${isCurrentRender(r)?'current':'previous'} MP4</a>${r.adjusted_srt_url?` · <a class="download" href="${E(r.adjusted_srt_url)}?download=1">↓ Adjusted SRT</a>`:''}</p>`:''}<button type="button" onclick="approveDocumentaryScenes()" ${P.scenes.some(s=>!s.approved)?'':'disabled'}>Approve all ready scenes</button><p class="small">Approve only after reviewing picture, identity, context and source. Your attestation is not independent verification or reuse-rights approval.</p><div id="doc-approval-result" role="status"></div><button type="button" onclick="openDocumentary()">Documentary audio and subtitles</button></div>`;loadDocumentaryReadiness(P.id);
}
async function approveDocumentaryScenes(){
 if(!P||P.edit_mode!=='documentary'||!leave())return;
 const id=P.id,count=P.scenes.filter(s=>!s.approved).length;
 if(!count){toast('Every scene is already approved.');return}
 if(!confirm(`Approve all technically ready scenes? ${count} scene(s) are currently unapproved. Confirm only if you personally reviewed each picture, identity, context and source. This does not verify rights; final export requires separate checks. Scenes with technical blockers will be skipped; existing approvals with blockers may be reset.`))return;
 const button=document.querySelector('#content button[onclick="approveDocumentaryScenes()"]');if(button)button.disabled=true;
 try{const result=await api(`/api/projects/${id}/scenes/approve`,'POST',{attested:true,scope:'ready'});if(P?.id!==id)return;P=result;renderProject();await list();const box=$('#doc-approval-result'),approved=result.bulk_approval?.approved||[],skipped=result.bulk_approval?.skipped||[];if(box)box.innerHTML=`<p>${approved.length} scene(s) approved. ${skipped.length} scene(s) skipped.</p>${skipped.length?`<ul>${skipped.map(x=>`<li>Scene ${E(x.scene)}: ${x.reasons.map(E).join(' ')}</li>`).join('')}</ul>`:''}`;toast(`${approved.length} scene(s) approved; ${skipped.length} skipped.`);loadDocumentaryReadiness(id);loadDocumentaryReadiness(id,'doc-brief-readiness')}catch(e){toast(e.message);if(button?.isConnected)button.disabled=false}
}
async function loadDocumentaryReadiness(id,boxId='doc-delivery-readiness'){
 try{const state=await api(`/api/projects/${id}/documentary-export-readiness`);const box=document.getElementById(boxId);if(!box||P?.id!==id)return;
 const approved=P?.scenes?P.scenes.filter(x=>x.approved).length:null,total=P?.scenes?P.scenes.length:null; const countText=total?(approved===total?` All ${total} picture slots reviewed.`:` ${approved} of ${total} picture slots marked reviewed (optional — review is your own check, export does not require it).`):''; const heading=state.status==='checking'?'Checking source frames and timing…':state.errors.length?`${state.errors.length} export blocker(s) need attention`:'Ready to export: timing and source checks passed.';
 const quant=state.frame_preflight?.report?.quantization||[];
 const quantHTML=quant.length?`<details open><summary>Frame quantisation details (${quant.length})</summary><p class="small">The script timecodes remain saved unchanged. These are the nearest decoded source frames. A one-frame adjustment requires an explicit written approval; larger differences require a script correction.</p>${quant.map(q=>`<div class="notice warn"><strong>Beat ${E(q.label)} · ${E(q.source)}</strong><p>${q.requested_start_frame}–${q.requested_end_frame_exclusive} source frames · output needs ${q.output_frames} · difference ${q.difference_frames>0?'+':''}${q.difference_frames} frame(s). Nearest source range ${(q.actual_start_ms/1000).toFixed(3)}–${(q.actual_end_ms/1000).toFixed(3)}s.</p>${q.status==='user approved'?`<p>USER-APPROVED EXCEPTION: ${q.approved_delta_frames>0?'+1':'−1'} source frame.</p>`:Math.abs(q.difference_frames)===1?`<button type="button" data-frame-decision="${E(q.label)}" data-delta="${q.difference_frames}">Review and approve this one-frame exception</button>`:'<p>Correct the exact production-script source range; this difference is too large for a one-frame exception.</p>'}</div>`).join('')}</details>`:'';
 box.innerHTML=`<p><strong>${E(heading)}</strong>${E(countText)}</p>${state.errors.length?`<ul class="issues">${state.errors.map(x=>`<li>${E(x)}</li>`).join('')}</ul>`:''}${quantHTML}${state.warnings.length?`<details><summary>Review notes (${state.warnings.length})</summary><ul class="issues">${state.warnings.map(x=>`<li>${E(x)}</li>`).join('')}</ul></details>`:''}<p class="small">These checks do not independently verify content, identity or rights.</p>`;
 box.querySelectorAll('[data-frame-decision]').forEach(button=>button.addEventListener('click',()=>approveStrictFrameDecision(button.dataset.frameDecision,Number(button.dataset.delta))));
 if(state.status==='checking')setTimeout(()=>{if(P?.id===id&&document.getElementById(boxId))loadDocumentaryReadiness(id,boxId)},1500)
 }catch(e){const box=document.getElementById(boxId);if(box&&P?.id===id)box.textContent='Export readiness unavailable: '+e.message}}

async function approveStrictFrameDecision(label,delta){
 const explanation=prompt(`Beat ${label} needs ${delta>0?'one additional source frame':'one fewer source frame'} to match the output slot. Explain why you approve this exact frame adjustment.`,'');
 if(!explanation?.trim())return;
 if(!confirm(`Record an explicit exception for Beat ${label}? The production script timecodes will remain saved; the renderer will use the listed frame-aligned range.`))return;
 try{await api(`/api/projects/${docPid}/documentary-frame-decisions/${encodeURIComponent(label)}`,'POST',{detail:explanation});P=await api(`/api/projects/${docPid}`);await loadDocumentaryReadiness(P.id);if(P?.documentary_beat_review?.strict_execution)loadStrictBeatReview();toast(`Frame exception recorded for Beat ${label}.`)}catch(e){toast(e.message)}
}



let docAudioPoll=null;
async function prepareDocumentaryAudio(){try{const id=P.id;const result=await api(`/api/projects/${id}/documentary-audio`,'POST');if(P?.id!==id)return;showDocumentaryAudio(result);pollDocumentaryAudio()}catch(e){toast(e.message)}}
function showDocumentaryAudio(state){const box=$('#doc-audio-status');if(!box)return;const text=state.status==='done'?'Documentary audio preview is ready.':state.detail||'Not prepared.';box.innerHTML=`<p>${E(text)}</p>${state.status==='done'?`<p class="small">Audio only · ${docTime(state.duration_s)}. This is not the documentary MP4 or a retimed SRT.</p><audio controls preload="metadata" src="${E(state.url)}"></audio><p><a class="download" href="${E(state.url)}?download=1">Download documentary audio preview (WAV)</a></p>`:''}`}
async function pollDocumentaryAudio(){clearTimeout(docAudioPoll);if(!P||P.edit_mode!=='documentary'||!$('#documentary-dialog').open)return;const id=P.id;try{const state=await api(`/api/projects/${id}/documentary-audio`);if(P?.id!==id||!$('#documentary-dialog').open)return;showDocumentaryAudio(state);if(['queued','running'].includes(state.status))docAudioPoll=setTimeout(pollDocumentaryAudio,1500)}catch(e){const box=$('#doc-audio-status');if(box)box.textContent=e.message}}

function docSubtitleSplitHTML(){
 const blocks=P?.srt?.blocks||[],seen=new Set(),items=[];
 for(const bite of docPlan.bites){const ms=Math.round(bite.pause_s*1000),block=blocks.find(b=>b.start_ms<ms&&ms<b.end_ms),key=block&&`${block.number}:${ms}`;if(!block||seen.has(key))continue;seen.add(key);const words=block.text.split(/\s+/);items.push(`<label>Original cue ${E(block.number)} · pause ${docTime(bite.pause_s)}<span class="small">${E(block.text)}</span><select class="doc-subtitle-split" data-cue="${block.number}" data-pause="${ms}"><option value="">Choose the last word spoken before the pause</option>${words.slice(0,-1).map((w,i)=>`<option value="${i+1}">After: ${E(words.slice(0,i+1).join(' '))}</option>`).join('')}</select></label>`)}
 return items.join('');
}
window.documentaryExportSplits=null;
async function saveDocumentaryExportSplits(){
 try{const splits=[...document.querySelectorAll('.doc-subtitle-split')].map(el=>({cue:Number(el.dataset.cue),pause_ms:Number(el.dataset.pause),words_before:Number(el.value)}));if(splits.some(x=>!x.words_before))throw Error('Choose where every crossing cue splits first. Listen to the narration to verify it.');if(splits.length&&!confirm('Have you listened and checked which words are spoken before each pause? The split uses your choices, not automatic word alignment.'))return;const response=await fetch(`/api/projects/${docPid}/documentary-subtitles`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision:docPlan.revision,splits})});if(!response.ok){const e=await response.json();throw Error(e.error||'Could not validate the subtitle split.')}window.documentaryExportSplits={id:docPid,revision:docPlan.revision,splits};toast('Reviewed subtitle split saved for this export session.');}catch(e){toast(e.message)}
}
async function downloadDocumentarySrt(){
 try{const splits=[...document.querySelectorAll('.doc-subtitle-split')].map(el=>({cue:Number(el.dataset.cue),pause_ms:Number(el.dataset.pause),words_before:Number(el.value)}));if(splits.some(x=>!x.words_before))throw Error('Choose where every crossing cue splits first. Listen to the narration to verify it.');if(splits.length&&!confirm('Have you listened and checked which words are spoken before each pause? The split uses your choices; it is not automatic word alignment.'))return;const r=await fetch(`/api/projects/${docPid}/documentary-subtitles`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision:docPlan.revision,splits})});if(!r.ok){const e=await r.json();throw Error(e.error||'Could not adjust subtitles.')}const blob=await r.blob(),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='documentary-adjusted.srt';a.click();setTimeout(()=>URL.revokeObjectURL(url),10000)}catch(e){toast(e.message)}
}



/* ---- Beat picture plan: proposed before anything is written ---- */
let beatProposal=null,beatProposalFocus=null;
// The plan used to hard-code Beat 007 whenever anything needed a decision, so a
// problem in Beat 010 pointed the replacement picker at the wrong Beat.
// v19: a sound bite cannot be re-pointed at another video (that would play someone else's
// voice), and the server ignores such a choice, so the picker is only offered for
// narration Beats; a blocked bite gets the two things that actually fix it.
function beatBlockerBeat(d){const label=beatBlocker();return label?(d?.beats||[]).find(b=>String(b.label)===String(label)):null}
function beatBlockerIsBite(d){const b=beatBlockerBeat(d);return !!b&&b.kind!=='narration'}
function beatBlockerFile(d){return beatBlockerBeat(d)?.source_file||'source video'}
function beatBlocker(){const first=(beatProposal?.issues||[]).find(x=>/^Beat \d+/.test(x))||'';return (first.match(/^Beat (\d+)/)||[])[1]||''}
function strictBeatProposalHTML(d){
 const rows=(d.beats||[]).map(b=>{
  const issue=d.issues.find(x=>x.startsWith(`Beat ${b.label}:`)),f=d.frame_ranges?.[b.label]||{};
  const asset=b.asset_id?`/api/projects/${encodeURIComponent(P.id)}/assets/${encodeURIComponent(b.asset_id)}/source-file`:'';
  const preview=asset?`<video controls preload="metadata" ${b.kind==='narration'?'muted':''} style="width:min(100%,520px);max-height:300px;background:#111" src="${E(asset)}#t=${(b.source_in_ms/1000).toFixed(3)},${(b.source_out_ms/1000).toFixed(3)}"></video>`:'<p class="notice warn">The exact source preview is unavailable.</p>';
  const state=issue?'BLOCKED':'SCRIPT ASSIGNMENT VALID';
  const narrative=b.kind==='narration'?`<p><strong>Narration:</strong> ${docTime(b.narration_in_ms/1000)}–${docTime(b.narration_out_ms/1000)} · ${E(b.srt_text||'No SRT cue text')}</p>`:`<p><strong>Soundbite:</strong> ${E(b.speaker||'Speaker missing')} · pause ${docTime(b.pause_ms/1000)} · “${E(b.exact_dialogue||'No exact dialogue supplied')}”</p>`;
  const quantized=f.frame_aligned_in_ms!=null?`<p class="small">Nearest source frames: ${(f.frame_aligned_in_ms/1000).toFixed(3)}–${(f.frame_aligned_out_ms/1000).toFixed(3)}s; boundary deltas ${f.in_delta_ms>=0?'+':''}${f.in_delta_ms.toFixed(1)} / ${f.out_delta_ms>=0?'+':''}${f.out_delta_ms.toFixed(1)} ms.</p>`:'';
  return `<details class="notice ${issue?'warn':''}"><summary><strong>Beat ${E(b.label)}</strong> · ${state} · ${E(b.source_file)}</summary>${narrative}<p><strong>Visual ID:</strong> ${E(b.visual_id||'Not specified')} · <strong>Visual direction:</strong> ${E(b.direction||'Not specified')}</p><p><strong>Continuity:</strong> ${E(b.continuity_note||'Not specified')}</p><p><strong>Exact source range:</strong> ${docTime(b.source_in_ms/1000)}–${docTime(b.source_out_ms/1000)} (${docTime((b.source_out_ms-b.source_in_ms)/1000)})</p>${quantized}${preview}${issue?`<p class="notice warn">${E(issue)}</p>`:''}</details>`;
 }).join('');
 return `<p class="notice"><strong>Exact documentary Beat execution.</strong> The production script supplies every source and timestamp. Storyroom will use these ranges as written. It will not fit, trim, extend, shift, replace or fill a Beat.</p>
 ${d.replaces_beat_timeline?`<p class="notice warn"><strong>This rebuild replaces the saved Beat timeline.</strong> Confirm only if you intend to rebuild from the current exact script.</p>`:''}
 ${d.issues.length?`<div class="notice warn"><strong>${d.issues.length} blocking issue(s)</strong><ul class="issues">${d.issues.map(x=>`<li>${E(x)}</li>`).join('')}</ul><p>Correct the production script or upload its exact source files, then review the proposal again. No alternate source is offered.</p></div>`:'<p class="notice"><strong>Script assignments and timings pass technical validation.</strong> Visual content and identity still require human review after build.</p>'}
 ${rows?`<details><summary>Exact script Beats (${(d.beats||[]).length})</summary>${rows}</details>`:''}
 ${d.consecutive_bites.length?`<details open><summary>Consecutive soundbites</summary><p>Beats ${d.consecutive_bites.map(p=>p.map(x=>`Beat ${E(x)}`).join(' and ')).join('; ')} stay in script order at the same pause point with no narration or unrelated picture inserted.</p><label class="check-label"><input type="checkbox" id="beat-consecutive-confirm" ${d.issues.length?'disabled':''}> I approve this exact consecutive soundbite sequence.</label></details>`:''}
 <label class="check-label"><input type="checkbox" id="beat-confirm" ${d.issues.length?'disabled':''}> I have reviewed the exact source assignments and timing report.</label>
 <div id="beat-build-state" aria-live="polite"></div><p><button type="button" onclick="buildBeatStoryboard()" ${d.issues.length?'disabled':''}>${d.replaces_beat_timeline?'Rebuild exact Beat timeline':'Build exact Beat timeline'}</button> <button type="button" onclick="openDocumentary()">Open documentary tools</button></p>`;
}
function beatProposalHTML(){
 const d=beatProposal;if(!d)return '<p>Loading the Beat picture plan…</p>';
 if(d.strict_execution)return strictBeatProposalHTML(d);
 return `<p class="small">Every scripted Beat keeps its own narration clock. Where the scripted picture range cannot cover that clock, the change is listed below and saved with the storyboard. Nothing is re-used outside the file the script names unless you choose it.</p>
 <p>Film length: <strong>${((d.narration_ms+(d.bites_ms||0))/60000).toFixed(2)} min</strong> · narration ${(d.narration_ms/60000).toFixed(2)} min + ${(d.beats||[]).filter(b=>b.kind!=='narration').length} sound bites ${((d.bites_ms||0)/60000).toFixed(2)} min</p>
 ${d.narration_length?.decoded_s!=null?`<p class="small">Narration length: <strong>${Number(d.narration_length.decoded_s).toFixed(3)} s decoded</strong>${d.narration_length.container_s!=null?` · file reports ${Number(d.narration_length.container_s).toFixed(3)} s`:''}${d.narration_length.start_offset_s?` · encoder start offset ${Number(d.narration_length.start_offset_s).toFixed(3)} s`:''}${d.narration_length.clock_s!=null?` · narration clock ${Number(d.narration_length.clock_s).toFixed(3)} s`:''}. A pause within one frame (0.033 s) of the end is clamped to it and listed.</p>`:''}
 ${d.replaces_beat_timeline?`<div class="notice warn"><strong>This replaces the saved Beat timeline.</strong><p class="small">${d.beat_timeline_stale?'The production script changed after that timeline was built, which is why it can no longer be played or exported.':'The saved timeline is being rebuilt for the current script.'} Building replaces its saved sound bites and its picture slots; the script, narration, SRT and footage are not changed.</p></div>`:''}
 ${d.issues.length?`<div class="notice warn"><strong>${d.issues.length} blocking script/picture issue(s)</strong><ul class="issues">${d.issues.map(x=>`<li>${E(x)}</li>`).join('')}</ul>
 ${beatBlockerIsBite(d)?`<p class="small"><strong>Beat ${E(beatBlocker())} is a sound bite.</strong> Its words come from that exact file and time, so a different video cannot stand in. Upload the full ${E(beatBlockerFile(d))} again with the same file name (it replaces the old one), or correct this Beat's Source IN/OUT in the production script. Then press Recheck inputs.</p>`:beatBlocker()?`<label>Use a different uploaded video for Beat ${E(beatBlocker())}<select onchange="beatPickSource(this.value)"><option value="">Choose a video…</option>${d.assets.map(a=>`<option value="${E(a.name)}" ${beatProposalFocus===a.name?'selected':''}>${E(a.name)} · ${a.duration.toFixed(1)}s</option>`).join('')}</select></label>`:`<p class="small">Correct the unassigned narration coverage in the production script; there is no safe substitute clip to choose here.</p>`}</div>`:
 `<div class="notice"><strong>Every Beat fits inside an uploaded file.</strong><p class="small">Review the adjustments below, then build.</p></div>`}
 ${(d.pause_clock_reconciliations||[]).length?`<details open><summary>Narration clock corrections (${d.pause_clock_reconciliations.length})</summary><p class="small">These exact Beat PAUSED labels use the film-master clock. Storyroom mapped them to the narrator-only clock only where the script's two clocks prove the same boundary. Review before building; the original script is preserved.</p><ul class="issues">${d.pause_clock_reconciliations.map(x=>`<li>${E(x)}</li>`).join('')}</ul></details>`:''}
 ${(d.narration_gaps||[]).length?`<details open><summary>Narration with no Beat (${d.narration_gaps.length})</summary><p class="small">No source has been assigned to these narration intervals. Storyroom will NOT select unused footage automatically. Add a correctly mapped Beat in the production script and review again.</p><ul class="issues">${d.narration_gaps.map(g=>`<li>${(g.narration_in_ms/1000).toFixed(3)}–${(g.narration_out_ms/1000).toFixed(3)}s · UNASSIGNED — add an exact source and IN/OUT in the production script</li>`).join('')}</ul></details>`:''}
 <details ${d.adjustments.length?'open':''}><summary>Picture range changes (${d.adjustments.length})</summary><ul class="issues">${d.adjustments.map(x=>`<li>${E(x)}</li>`).join('')||'<li>None.</li>'}</ul></details>
 <details><summary>Reused footage — allowed (${d.repeated_ranges.length} pair${d.repeated_ranges.length===1?'':'s'})</summary><p class="small">The same original video interval may appear in multiple Beats, including hook/main-story replay. This is not a build blocker. Check that every reuse serves the narration.</p><ul class="issues">${d.repeated_ranges.map(p=>`<li>Beat ${p[0]} and Beat ${p[1]}</li>`).join('')||'<li>None.</li>'}</ul></details>
 ${d.consecutive_bites.length?`<details open><summary>Sound bites with no narration between them</summary><p class="small">Beat ${d.consecutive_bites.map(p=>p.join(' and ')).join(', ')} sit at the same pause. They will play back to back.</p></details>`:''}
 <label class="check-label"><input type="checkbox" id="beat-confirm" ${d.issues.length?'disabled':''}> I have reviewed the source and picture-range assignments.</label>
 <div id="beat-build-state" aria-live="polite"></div>
 <p><button type="button" onclick="buildBeatStoryboard()" ${d.issues.length?'disabled':''}>${d.replaces_beat_timeline?'Rebuild the Beat timeline':'Build the Beat timeline'}</button> <button type="button" onclick="openDocumentary()">Open the documentary tools</button></p>
 <p class="small">This builds a review timeline only. Content, identity, speaker and reuse rights still need your review, and nothing is exported yet.</p>`;
}
async function openBeatProposal(){
 if(!P||P.edit_mode!=='documentary')return;
 // Always fetch current inputs first: a completed footage-sheet download or a
 // replacement script may have changed the project since the last UI render.
 const pid=P.id;
 try{P=await api(`/api/projects/${pid}`);if(P.id!==pid)return}
 catch(e){toast('Could not read the latest uploaded sources: '+e.message);return}

 $('#plan-title').textContent='Beat picture plan';$('#plan-body').innerHTML='<p>Reading the scripted Beats…</p>';
 if(!$('#plan-dialog').open)$('#plan-dialog').showModal();
 try{
  const focusBeat=beatBlocker();
  const query=(beatProposalFocus&&focusBeat)?`?scripted_review_beat=${encodeURIComponent(focusBeat)}&scripted_review_source=${encodeURIComponent(beatProposalFocus)}`:'';
  beatProposal=await api(`/api/projects/${P.id}/documentary-beat-proposal${query}`);
  $('#plan-body').innerHTML=beatProposalHTML();
 }catch(e){$('#plan-body').innerHTML=`<p class="notice warn">${E(e.message)}</p>`}
}
function beatPickSource(name){
 if(!beatProposal)return;beatProposalFocus=name||null;openBeatProposal();
}
// The build decodes every source up to its last used frame, which takes minutes on a
// real production. It runs as a job so this dialog can show what it is doing instead
// of leaving a disabled button as the only evidence that anything was asked for.
let beatBuildTimer=null;
function beatBuildHTML(job){
 const pct=Math.max(0,Math.min(100,Math.round(job.percent||0)));
 return `<div class="build-progress">
  <div class="progress-track"><i class="progress-fill" style="width:${pct}%"></i></div>
  <p class="small"><strong>${pct}%</strong> · ${E(job.detail||'Building…')}</p>
 </div>`;
}
function stopBeatBuildPolling(){clearTimeout(beatBuildTimer);beatBuildTimer=null}
async function pollBeatBuild(){
 beatBuildTimer=null;
 if(!P?.id)return;
 let job;
 try{job=await api(`/api/projects/${P.id}/documentary-beat-storyboard`)}
 catch(e){$('#beat-build-state').innerHTML=`<p class="notice warn">${E(e.message)}</p>`;return}
 if(!$('#beat-build-state'))return;   // the dialog was closed while we were asking
 if(job.status==='done'){
  const built=job.project||{};
  P=built;beatProposal=null;beatProposalFocus=null;
  // Old audio and picture schedules must never continue playing after a rebuild.
  if(typeof cancelDocPlay==='function')cancelDocPlay();
  if(typeof resetDocTimeline==='function')resetDocTimeline();
  sceneIndex=0;
  stopBeatBuildPolling();
  $('#plan-dialog').close();
  toast(`${(built.scenes||[]).length} picture slots built. Review the timeline, then check the pictures.`);
  renderProject();list().catch(()=>{});
  return;
 }
 if(job.status==='error'){
  const msg=job.error||'The build could not finish.';
  // A pause past the narration end can be clamped to it -- only after the user reads why.
  const offerClamp=/Clamp to narration end/.test(msg);
  $('#beat-build-state').innerHTML=`<p class="notice warn">${E(msg)}</p>
   <p><button type="button" onclick="buildBeatStoryboard()">Try again</button>${offerClamp?` <button type="button" onclick="buildBeatStoryboard({clamp:true})">Clamp to narration end and build</button>`:''}</p>`;
  return;
 }
 if(job.status==='cancelled'){
  $('#beat-build-state').innerHTML='<p class="small">Build cancelled. Nothing was changed.</p>';
  return;
 }
 $('#beat-build-state').innerHTML=beatBuildHTML(job)+
  '<p><button type="button" class="text-button danger" onclick="cancelBeatBuild()">Stop building</button></p>';
 beatBuildTimer=setTimeout(pollBeatBuild,700);
}
async function cancelBeatBuild(){
 stopBeatBuildPolling();
 try{await api(`/api/projects/${P.id}/documentary-beat-storyboard/cancel`,'POST',{})}catch{}
 $('#beat-build-state').innerHTML='<p class="small">Stopping after the current step…</p>';
 beatBuildTimer=setTimeout(pollBeatBuild,700);
}
async function buildBeatStoryboard(options={}){
 if(!beatProposal)return;
 if(options.clamp&&!confirm('Move every pause that sits after the end of the narration to the narration end? The script file is not changed; each clamp is listed in the build record.'))return;
 if(!$('#beat-confirm')?.checked){toast('Read and confirm the picture-range changes first.');return}
 if(beatProposal.strict_execution&&beatProposal.consecutive_bites.length&&!$('#beat-consecutive-confirm')?.checked){toast('Explicitly approve the consecutive soundbite sequence first.');return}
 const button=document.querySelector('#plan-body button[onclick="buildBeatStoryboard()"]');if(button)button.disabled=true;
 stopBeatBuildPolling();
 const holder=$('#beat-build-state');
 if(holder)holder.innerHTML=beatBuildHTML({percent:0,detail:'Reading the scripted Beats'});
 try{
  const payload={
   confirmed:true,project_version:beatProposal.project_version,plan_revision:beatProposal.plan_revision||0,script_sha256:beatProposal.script_sha256,
   replace_beat_timeline:beatProposal.replaces_beat_timeline===true,
   approved_gaps:[],
   approved_overlaps:beatProposal.strict_execution?[]:beatProposal.repeated_ranges,
   allow_silent_tail:false,
   approve_consecutive_bites:beatProposal.strict_execution?!!$('#beat-consecutive-confirm')?.checked:beatProposal.consecutive_bites.length>0,
   strict_execution:beatProposal.strict_execution===true,
   scripted_review_beat:beatProposal.strict_execution?null:((beatProposal.issues.length?beatBlocker():null)||null),
   scripted_review_source:beatProposal.strict_execution?null:(beatProposal.issues.length?beatProposalFocus:null),
   clamp_pauses_to_narration_end:options.clamp===true};
  const job=await api(`/api/projects/${P.id}/documentary-beat-storyboard`,'POST',payload);
  if(holder)holder.innerHTML=beatBuildHTML(job);
  beatBuildTimer=setTimeout(pollBeatBuild,400);
 }catch(e){
  if(holder)holder.innerHTML=`<p class="notice warn">${E(e.message)}</p>${/Clamp to narration end/.test(e.message)?'<p><button type="button" onclick="buildBeatStoryboard({clamp:true})">Clamp to narration end and build</button></p>':''}`;
  else toast(e.message);
  if(button?.isConnected)button.disabled=false;
 }
}

// Cutaway picture changes are independent of both Beat rebuilds and audio edits.
async function docLoadCutawayFile(input){
 const file=input.files?.[0];if(!file)return;
 if(file.size>512*1024){toast('Cutaway ledger is too large.');return}
 try{const data=await file.text();const field=document.getElementById('doc-cutaway-ledger');if(field)field.value=data}
 catch(e){toast('Cannot read cutaway file: '+e.message)}
}
// v23: tick rows (or Select all), then Approve selected. Each row that passes the checks
// is approved; a row that cannot be is left off with its reason shown under it.
const docCutawaySel=new Set();let docCutawayRejected={};
async function docRefreshCutaways(){
 const box=document.getElementById('doc-cutaway-status');if(!box||!docPid)return;
 try{const state=await api(`/api/projects/${docPid}/documentary-cutaways`);if(!document.getElementById('doc-cutaway-status'))return;
  window.docCutawayState=state.cutaways||[];
  const ids=new Set(docCutawayState.map(x=>x.id));for(const id of [...docCutawaySel])if(!ids.has(id))docCutawaySel.delete(id);
  docRedrawCutaways();
 }catch(e){box.textContent='Cutaway status unavailable: '+e.message}
}
function docCutawayListHTML(){
 const rows=window.docCutawayState||[],active=rows.filter(x=>x.approved).length,n=docCutawaySel.size;
 if(!rows.length)return '<p><strong>0 planned · 0 active</strong></p>';
 const all=n===rows.length,some=n>0&&!all;
 return `<div class="cutaway-bar"><label class="check-label cutaway-all"><input type="checkbox" id="doc-cutaway-all" ${all?'checked':''} onchange="docSelectAllCutaways(this.checked)"> Select all</label>
  <strong>${rows.length} planned · ${active} active${n?` · ${n} ticked`:''}</strong><span class="cutaway-spacer"></span>
  <button type="button" class="new" onclick="docApproveCutaways(true)" ${n?'':'disabled'}>Approve selected${n?` (${n})`:''}</button>
  <button type="button" class="secondary" onclick="docApproveCutaways(false)" ${rows.some(x=>x.approved&&docCutawaySel.has(x.id))?'':'disabled'}>Turn off selected</button>
  <button type="button" class="secondary" onclick="docClearCutaways()">Clear cutaway plan</button></div>
  <p class="small">Check each picture against what the speaker is saying, then approve. The interview audio is never changed.</p>
  ${rows.map(x=>{const why=docCutawayRejected[x.id];return `<div class="notice cutaway-row ${x.approved?'is-active':''} ${why?'is-rejected':''}" style="margin:6px 0"><label class="check-label"><input type="checkbox" ${docCutawaySel.has(x.id)?'checked':''} onchange="docTickCutaway('${E(x.id)}',this.checked)">
  <strong>${E(x.id)}</strong> · Beat ${E(x.soundbite_beat)} · ${E(x.picture_source)} · ${(x.timeline_in_ms/1000).toFixed(3)}–${(x.timeline_out_ms/1000).toFixed(3)}s <span class="cutaway-pill">${x.approved?'ACTIVE':'Not active'}</span></label>
  <p class="small">${E(x.reason||'No editorial evidence supplied')}</p>${why?`<p class="small cutaway-why">Could not approve: ${E(why)}</p>`:''}</div>`}).join('')}`;
}
function docRedrawCutaways(){const box=document.getElementById('doc-cutaway-status');if(!box)return;box.innerHTML=docCutawayListHTML();const all=document.getElementById('doc-cutaway-all');if(all){const n=docCutawaySel.size,t=(window.docCutawayState||[]).length;all.indeterminate=n>0&&n<t}}
function docTickCutaway(id,on){on?docCutawaySel.add(id):docCutawaySel.delete(id);docRedrawCutaways()}
function docSelectAllCutaways(on){docCutawaySel.clear();if(on)for(const x of window.docCutawayState||[])docCutawaySel.add(x.id);docRedrawCutaways()}
async function docApproveCutaways(approved){
 const ids=[...docCutawaySel];if(!ids.length){toast('Tick at least one cutaway.');return}
 if(approved&&!confirm(`Approve ${ids.length} cutaway${ids.length===1?'':'s'}? Each one shows its picture while the speaker keeps talking. Approve only pictures you have checked.`))return;
 try{
  const d=await api(`/api/projects/${docPid}/documentary-cutaways/approve`,'POST',{ids,approved});
  docCutawayRejected=approved?(d.rejected||{}):{};
  const bad=Object.keys(docCutawayRejected).length,done=ids.filter(id=>!(id in docCutawayRejected)).length;
  // Approved rows are unticked; rows that could not be approved stay ticked with their reason.
  for(const id of ids)if(!approved||!(id in docCutawayRejected))docCutawaySel.delete(id);
  P=await api(`/api/projects/${docPid}`);await docRefreshCutaways();reloadDocTimeline();
  toast(approved?(bad?`${done} approved · ${bad} could not be approved (reason shown under each).`:`${done} cutaway${done===1?'':'s'} approved. Render a short preview to check them.`):`${ids.length} turned off; the speaker picture returns there.`);
 }catch(e){toast(e.message);docRefreshCutaways()}
}
async function docSaveCutawayLedger(){
 const field=document.getElementById('doc-cutaway-ledger');if(!field?.value.trim()){toast('Choose or paste a cutaway ledger.');return}
 if(!confirm('Import this cutaway ledger? It replaces the previous cutaway plan. The interview AUDIO and original Beat timeline remain unchanged.'))return;
 try{await api(`/api/projects/${docPid}/documentary-cutaways`,'POST',{ledger:field.value});
  docCutawaySel.clear();docCutawayRejected={};P=await api(`/api/projects/${docPid}`);await docRefreshCutaways();reloadDocTimeline();toast('Cutaway plan imported. Tick the rows (or Select all), then Approve selected.');
 }catch(e){toast('Cutaway import rejected: '+e.message)}
}
async function docClearCutaways(){
 if(!confirm('Remove the cutaway schedule? All interviews return to their original speaker picture.'))return;
 try{await api(`/api/projects/${docPid}/documentary-cutaways`,'POST',{cutaways:[]});
  docCutawaySel.clear();docCutawayRejected={};P=await api(`/api/projects/${docPid}`);await docRefreshCutaways();reloadDocTimeline();toast('Cutaway schedule cleared.');
 }catch(e){toast(e.message)}
}

/* Setup › 08 Interview picture cutaways. The same import as Documentary tools: a
   [CASE]_CUTAWAY_PICTURE_HANDOFF.json (or the Markdown table) uploaded after the Beat
   storyboard is built. Rows arrive unapproved; approval stays in Documentary tools. The
   format, checks and the interview audio are unchanged. */
function cutawaySetupCardHTML(){
 // v20: the file can be chosen at any time. Before the Beat timeline is built it is
 // checked and kept, then applied automatically by the build.
 const built=!!P?.documentary_beat_review?.fitted_beats;
 const rows=P?.documentary_cutaways||[],active=rows.filter(x=>x.approved).length,pending=P?.documentary_cutaways_pending;
 const status=pending?(pending.error?'Needs attention':'Waiting for the Beat build'):rows.length?`${rows.length} planned · ${active} active`:'Optional';
 return `<section class="card setup-card" id="cutaway-setup-card"><div class="setup-card-heading"><span class="setup-step">08</span><h3>Interview picture cutaways</h3><span class="setup-status ${rows.length||(pending&&!pending.error)?'ready':''}">${E(status)}</span></div>
  <p>Upload the cutaway handoff (JSON or the Markdown table) to show authentic footage or photos while a speaker keeps talking. The interview audio and the production script are not changed.</p>
  <label class="cta-upload-button"><input type="file" accept=".json,.md,.txt,application/json,text/markdown,text/plain" onchange="setupUploadCutaways(this)"><span>${rows.length||pending?'Replace cutaway file':'Upload cutaway JSON or Markdown'}</span></label>
  ${pending?`<p class="small">${E(pending.name||'Cutaway file')} · ${pending.rows} row${pending.rows===1?'':'s'} · ${pending.error?`<span class="warn-text">Could not be applied after the build: ${E(pending.error)}</span>`:built?'applies on the next Beat build':'kept until the Beat timeline is built, then applied automatically'}</p>`:''}
  ${rows.length?`<p class="small">${rows.slice(0,6).map(x=>`${E(x.id)} · Beat ${E(x.soundbite_beat)} · ${E(x.picture_source)} · ${(x.timeline_in_ms/1000).toFixed(3)}–${(x.timeline_out_ms/1000).toFixed(3)}s · ${x.approved?'active':'not approved'}`).join('<br>')}${rows.length>6?`<br>…and ${rows.length-6} more`:''}</p>
   <p class="small">Review and approve each row in <button type="button" class="text-button" onclick="closeManagement();openDocumentary()">Documentary tools › Interview picture cutaways</button>.</p>`:''}
 </section>`;
}
async function setupUploadCutaways(input){
 const file=input.files?.[0];input.value='';if(!file||!P)return;
 if(file.size>512*1024){toast('Cutaway file is too large (512 KB limit).');return}
 if(((P.documentary_cutaways||[]).length||P.documentary_cutaways_pending)&&!confirm('Replace the current cutaway plan with this file? The interview audio and Beat timeline stay unchanged.'))return;
 try{
  const ledger=await file.text();
  const res=await api(`/api/projects/${P.id}/documentary-cutaways`,'POST',{ledger,name:file.name});
  P=await api(`/api/projects/${P.id}`);
  renderManagement();if(typeof reloadDocTimeline==='function')reloadDocTimeline();
  if(res.pending){toast(`${res.rows} cutaway row${res.rows===1?'':'s'} saved. They are applied automatically when the Beat timeline is built.`);return}
  const n=(P.documentary_cutaways||[]).length;
  toast(`${n} cutaway row${n===1?'':'s'} imported, not approved yet. Approve them in Documentary tools.`);
 }catch(e){toast('Cutaway import rejected: '+e.message)}
}
