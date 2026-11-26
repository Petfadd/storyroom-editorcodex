/* v26 Stickers.
   Header › Stickers opens the library. Clicking a sticker puts it on the film at the
   playhead (4 s) and selects it; the Shot Inspector then shows − / + for its size,
   place, opacity, start and length. Drag a selected sticker on the monitor to move it.
   The monitor draws stickers with the same timing, size and place the MP4 uses
   (stickers.py), so what you see is what renders. */
let stickerLib=null,stickerLibFor=null,stickerSel=null,stickerGroup='Subscribe',stickerSaveTimers={},stickerDrag=null;
const STICKER_FADE=.2;

function stickerRows(){return Array.isArray(P?.stickers)?P.stickers:[]}
function stickerById(id){return stickerRows().find(s=>s.id===id)||null}
function stickerKind(key){return (stickerLib||[]).find(k=>k.id===key)||null}
function stickerNow(){return typeof channelCTAMonitorTime==='function'?channelCTAMonitorTime():(typeof editorTime==='function'?editorTime():0)}
function stickerTime(s){const n=Math.max(0,Number(s)||0),m=Math.floor(n/60);return `${m}:${(n%60).toFixed(1).padStart(4,'0')}`}
async function loadStickerLibrary(force=false){
 if(!P)return [];
 if(!force&&stickerLib&&stickerLibFor===P.id)return stickerLib;
 const d=await api(`/api/projects/${P.id}/stickers/library`);
 stickerLib=d.stickers||[];stickerLibFor=P.id;
 for(const k of stickerLib)for(const f of k.frames||[]){const i=new Image();i.src=f}   // ready to draw
 return stickerLib;
}

/* ---------- library window ---------- */
async function openStickers(){
 if(!P){toast('Open a project first.');return}
 const dlg=document.getElementById('stickers-dialog');if(!dlg)return;
 try{await loadStickerLibrary()}catch(e){toast(e.message);return}
 renderStickerLibrary();dlg.showModal();
}
function setStickerGroup(g){stickerGroup=g;renderStickerLibrary()}
function renderStickerLibrary(){
 const body=document.getElementById('stickers-body');if(!body)return;
 const groups=['Subscribe','Arrows & shapes','Yours'];
 const tabs=groups.map(g=>`<button type="button" class="sticker-tab${g===stickerGroup?' is-on':''}" onclick="setStickerGroup('${g}')">${g}</button>`).join('');
 const rows=(stickerLib||[]).filter(k=>k.group===stickerGroup);
 const tiles=rows.map(k=>`<div class="sticker-tile-wrap"><button type="button" class="sticker-tile" onclick="pickSticker('${E(k.id)}')" title="Add “${E(k.name)}” at the playhead">
   <img src="${E(k.url)}" alt="" loading="lazy" ${k.frames?.length>1?`data-frames='${E(JSON.stringify(k.frames))}'`:''}>
   ${k.animation!=='static'?'<span class="sticker-anim">Animated</span>':''}<span class="sticker-name">${E(k.name)}</span></button>
   ${k.group==='Yours'?`<button type="button" class="sticker-del" title="Remove from your stickers" aria-label="Remove ${E(k.name)}" onclick="deleteStickerUpload('${E(k.id)}')">×</button>`:''}</div>`).join('');
 const upload=stickerGroup==='Yours'?`<label class="sticker-tile sticker-upload" title="Upload a PNG (transparent background works best)"><input type="file" accept="image/png,image/webp,image/jpeg" onchange="uploadSticker(this)"><span>＋</span><span class="sticker-name">Upload sticker</span></label>`:'';
 body.innerHTML=`<div class="sticker-tabs">${tabs}</div><div class="sticker-grid">${upload}${tiles||(stickerGroup==='Yours'?'':'<p class="small">No stickers here.</p>')}</div>
  <p class="small sticker-hint">Click a sticker to add it at the playhead (${stickerTime(stickerNow())}). Then adjust it with − / + in the Shot Inspector.</p>`;
 stickerAnimateTiles();
}
let stickerTileTimer=0;
function stickerAnimateTiles(){
 clearInterval(stickerTileTimer);let k=0;
 stickerTileTimer=setInterval(()=>{
  const dlg=document.getElementById('stickers-dialog');if(!dlg?.open){clearInterval(stickerTileTimer);return}
  k++;dlg.querySelectorAll('img[data-frames]').forEach(img=>{try{const f=JSON.parse(img.dataset.frames);img.src=f[k%f.length]}catch{}});
 },700);
}
async function pickSticker(key){
 if(!P)return;
 try{
  const d=await api(`/api/projects/${P.id}/stickers`,'POST',{sticker:key,start_s:Math.round(stickerNow()*1000)/1000});
  const id=d.added_sticker;delete d.added_sticker;P=d;
  document.getElementById('stickers-dialog')?.close();
  selectSticker(id,false);
  toast('Sticker added. Adjust it with − / + in the Shot Inspector, or drag it on the video.');
 }catch(e){toast(e.message)}
}
async function uploadSticker(input){
 const file=input.files?.[0];if(!file||!P)return;
 const form=new FormData();form.append('file',file);
 try{const d=await api(`/api/projects/${P.id}/stickers/upload`,'POST',form);delete d.uploaded_sticker;P=d;await loadStickerLibrary(true);stickerGroup='Yours';renderStickerLibrary();toast('Added to your stickers. Click it to put it on the film.')}
 catch(e){toast(e.message)}finally{input.value=''}
}
async function deleteStickerUpload(id){
 const used=stickerRows().filter(s=>s.sticker===id).length;
 if(!confirm(used?`Remove this sticker from your library? It is used ${used} time${used===1?'':'s'} in the film and will be removed there too.`:'Remove this sticker from your library?'))return;
 try{P=await api(`/api/projects/${P.id}/stickers/upload/${id}`,'DELETE');if(stickerSel&&!stickerById(stickerSel))stickerSel=null;await loadStickerLibrary(true);renderStickerLibrary();stickerRefresh()}
 catch(e){toast(e.message)}
}

/* ---------- selection and the inspector panel ---------- */
function selectSticker(id,seek=true){
 stickerSel=id;const s=stickerById(id);
 if(s&&seek){const t=s.start_s+Math.min(1,s.duration_s/2);if(P?.edit_mode==='documentary'&&typeof docSeekTimeline==='function')docSeekTimeline(t,true);else if(typeof seekEditor==='function')seekEditor(t,false)}
 stickerRefresh();
}
function deselectSticker(){stickerSel=null;stickerRefresh()}
function stickerRefresh(){
 if(typeof renderInspector==='function')renderInspector(true);else stickerInjectPanel();
 updateStickers(stickerNow());
}
function stickerStepHTML(label,key,value,unit){
 const shown=unit==='s'?Number(value).toFixed(1):Math.round(value);
 return `<div class="brand-step"><span>${label}</span>
 <button type="button" aria-label="${label}: less" onpointerdown="brandHold(event,()=>stickerStep('${key}',-1))" onclick="if(event.detail===0)stickerStep('${key}',-1)">−</button>
 <output id="stk-${key}-value">${shown}${unit}</output>
 <button type="button" aria-label="${label}: more" onpointerdown="brandHold(event,()=>stickerStep('${key}',1))" onclick="if(event.detail===0)stickerStep('${key}',1)">+</button></div>`;
}
function stickerPanelHTML(){
 const rows=stickerRows();if(!rows.length&&!stickerSel)return '';
 const s=stickerSel?stickerById(stickerSel):null;
 const list=rows.slice().sort((a,b)=>a.start_s-b.start_s).map(r=>{const k=stickerKind(r.sticker);return `<button type="button" class="sticker-row${r.id===stickerSel?' is-on':''}" onclick="selectSticker('${r.id}')"><img src="${E(k?.url||'')}" alt=""><span>${E(k?.name||'Sticker')}</span><small>${stickerTime(r.start_s)}</small></button>`}).join('');
 let controls='';
 if(s){
  const k=stickerKind(s.sticker);
  controls=`<div class="sticker-adjust"><div class="sticker-adjust-head"><img src="${E(k?.url||'')}" alt=""><strong>${E(k?.name||'Sticker')}</strong><button type="button" class="sticker-x" title="Done" aria-label="Done adjusting" onclick="deselectSticker()">✓</button></div>
   ${stickerStepHTML('Size','width',s.width*100,'%')}
   ${stickerStepHTML('Left ↔ right','center_x',s.center_x*100,'%')}
   ${stickerStepHTML('Up ↕ down','center_y',s.center_y*100,'%')}
   ${stickerStepHTML('Opacity','opacity',(s.opacity??1)*100,'%')}
   ${stickerStepHTML('Starts at','start_s',s.start_s,'s')}
   ${stickerStepHTML('Length','duration_s',s.duration_s,'s')}
   <div class="brand-buttons"><button type="button" class="cta-btn" onclick="selectSticker('${s.id}')">Jump to it</button><button type="button" class="cta-btn" onclick="centreSticker()">Centre</button><button type="button" class="cta-btn subtle" onclick="removeSticker('${s.id}')">Remove</button></div>
   <p class="small" id="sticker-save-status">Drag it on the video to move it.</p></div>`;
 }
 return `<section class="sticker-panel" id="sticker-panel"><header class="brand-head"><span class="brand-title">Stickers</span><button type="button" class="sticker-add" onclick="openStickers()">＋ Add</button></header>${controls}${rows.length?`<div class="sticker-list">${list}</div>`:''}</section>`;
}
function stickerInjectPanel(force=true){
 // Called after every inspector render. While playing the inspector is not redrawn, so
 // the panel already there stays (no flicker, buttons keep working).
 if(!force&&document.getElementById('sticker-panel'))return;
 document.getElementById('sticker-panel')?.remove();
 const host=document.getElementById('inspector-content');if(!host||P?.edit_mode!=='documentary')return;
 const html=stickerPanelHTML();if(html)host.insertAdjacentHTML('afterbegin',html);
}
const STICKER_STEP={width:.01,center_x:.01,center_y:.01,opacity:.05,start_s:.1,duration_s:.5};
const STICKER_LIMIT={width:[.03,1],center_x:[0,1],center_y:[0,1],opacity:[.05,1],start_s:[0,4*3600],duration_s:[.2,600]};
function stickerStep(key,dir){
 const s=stickerById(stickerSel);if(!s)return;
 const [lo,hi]=STICKER_LIMIT[key];let v=Math.round(((s[key]??(key==='opacity'?1:0))+dir*STICKER_STEP[key])*1000)/1000;v=Math.max(lo,Math.min(hi,v));
 s[key]=v;
 const out=document.getElementById(`stk-${key}-value`);if(out)out.textContent=key.endsWith('_s')?`${v.toFixed(1)}s`:`${Math.round(v*100)}%`;
 if(key==='start_s'&&typeof docSeekTimeline==='function'&&!editorPlaying)docSeekTimeline(v+.05,true);
 updateStickers(stickerNow());stickerQueueSave(s.id,{[key]:v});
}
function centreSticker(){const s=stickerById(stickerSel);if(!s)return;s.center_x=.5;s.center_y=.5;stickerRefresh();stickerQueueSave(s.id,{center_x:.5,center_y:.5})}
function stickerQueueSave(id,patch){
 const t=stickerSaveTimers[id]||(stickerSaveTimers[id]={patch:{},timer:0});
 Object.assign(t.patch,patch);clearTimeout(t.timer);
 t.timer=setTimeout(async()=>{const body=t.patch;delete stickerSaveTimers[id];
  try{const d=await api(`/api/projects/${P.id}/stickers/${id}`,'PATCH',body);P.stickers=d.stickers;P.updated=d.updated;const st=document.getElementById('sticker-save-status');if(st)st.textContent='Saved · Render again to update the MP4'}
  catch(e){toast(e.message)}},450);
}
async function removeSticker(id){
 try{P=await api(`/api/projects/${P.id}/stickers/${id}`,'DELETE');if(stickerSel===id)stickerSel=null;stickerRefresh();toast('Sticker removed.')}catch(e){toast(e.message)}
}

/* ---------- drawing on the monitor ---------- */
function stickerPictureRect(frame){
 if(typeof ctaPictureRect==='function')return ctaPictureRect(frame);
 const fw=frame.clientWidth||0,fh=frame.clientHeight||0;let pw=fw,ph=fw*9/16;if(ph>fh){ph=fh;pw=fh*16/9}return {ox:(fw-pw)/2,oy:(fh-ph)/2,pw,ph,fw,fh};
}
function stickerFrameIndex(kind,s,t){
 const n=kind?.frames?.length||1;if(n<2||kind.animation==='static')return 0;
 const a=s.start_s,b=a+s.duration_s;
 if(kind.animation==='once'){const at=kind.at||[...Array(n).keys()].map(i=>i/n);let k=0;for(let i=0;i<n;i++)if(t>=a+(b-a)*at[i])k=i;return k}
 const period=kind.period||1,step=period/n;return Math.min(n-1,Math.floor(((t-a)%period+period)%period/step));
}
function updateStickers(t){
 const frame=document.getElementById('monitor-frame');if(!frame)return;
 let layer=document.getElementById('sticker-layer');
 if(!layer){layer=document.createElement('div');layer.id='sticker-layer';layer.className='sticker-layer';frame.insertBefore(layer,document.getElementById('editor-captions')||null)}
 if(!P||P.edit_mode!=='documentary'||!stickerLib||stickerLibFor!==P.id){layer.innerHTML='';if(P?.edit_mode==='documentary'&&stickerRows().length&&stickerLibFor!==P?.id)loadStickerLibrary().then(()=>updateStickers(stickerNow())).catch(()=>{});return}
 const r=stickerPictureRect(frame),tl=window.docTimelineData;
 // The export-matched preview already has stickers burned in; draw only the one being adjusted.
 const burned=tl&&!tl.direct&&tl.renderer==='export_matched_lowres';
 const seen=new Set();
 for(const s of stickerRows()){
  const kind=stickerKind(s.sticker);if(!kind)continue;
  const a=s.start_s,b=a+s.duration_s,inside=t>=a&&t<b,selected=s.id===stickerSel;
  if(!(inside||(selected&&!editorPlaying))||(burned&&!selected))continue;
  let el=layer.querySelector(`[data-sid="${s.id}"]`);
  if(!el){el=document.createElement('img');el.dataset.sid=s.id;el.className='sticker-live';el.alt='';el.draggable=false;
   el.addEventListener('pointerdown',stickerPointerDown);el.addEventListener('pointermove',stickerPointerMove);el.addEventListener('pointerup',stickerPointerUp);el.addEventListener('pointercancel',stickerPointerUp);layer.appendChild(el)}
  seen.add(s.id);
  const src=kind.frames[stickerFrameIndex(kind,s,Math.max(a,Math.min(t,b-.001)))]||kind.url;if(el.getAttribute('src')!==src)el.src=src;
  const nat=el.naturalWidth&&el.naturalHeight?el.naturalHeight/el.naturalWidth:.3;
  let w=Math.max(4,s.width*r.pw),h=w*nat;if(h>r.ph){h=r.ph;w=h/nat}
  const x=Math.min(Math.max(0,s.center_x*r.pw-w/2),Math.max(0,r.pw-w)),y=Math.min(Math.max(0,s.center_y*r.ph-h/2),Math.max(0,r.ph-h));
  Object.assign(el.style,{left:`${r.ox+x}px`,top:`${r.oy+y}px`,width:`${w}px`,height:`${h}px`});
  const fade=Math.min(STICKER_FADE,s.duration_s/4);
  let alpha=inside?Math.min(1,fade?(t-a)/fade:1,fade?(b-t)/fade:1):.55;
  // The sticker you are adjusting is always fully visible while paused (it would be
  // invisible on its first frame, which is where the playhead sits after adding it).
  if(selected&&!editorPlaying)alpha=inside?1:.55;
  el.style.opacity=String(Math.max(0,alpha*(s.opacity??1)));
  el.classList.toggle('is-selected',selected);
 }
 for(const el of [...layer.children])if(!seen.has(el.dataset.sid))el.remove();
}
function stickerPointerDown(ev){
 const id=ev.currentTarget.dataset.sid;if(ev.button!==0)return;
 if(stickerSel!==id){stickerSel=id;stickerRefresh()}
 const s=stickerById(id),frame=document.getElementById('monitor-frame');if(!s||!frame)return;
 ev.preventDefault();ev.stopPropagation();
 stickerDrag={id,pointer:ev.pointerId,x:ev.clientX,y:ev.clientY,cx:s.center_x,cy:s.center_y,r:stickerPictureRect(frame)};
 try{ev.currentTarget.setPointerCapture(ev.pointerId)}catch{}
}
function stickerPointerMove(ev){
 const d=stickerDrag;if(!d||d.pointer!==ev.pointerId)return;
 const s=stickerById(d.id);if(!s)return;
 s.center_x=Math.max(0,Math.min(1,Math.round((d.cx+(ev.clientX-d.x)/d.r.pw)*1000)/1000));
 s.center_y=Math.max(0,Math.min(1,Math.round((d.cy+(ev.clientY-d.y)/d.r.ph)*1000)/1000));
 updateStickers(stickerNow());
 for(const k of ['center_x','center_y']){const o=document.getElementById(`stk-${k}-value`);if(o)o.textContent=`${Math.round(s[k]*100)}%`}
}
function stickerPointerUp(ev){
 const d=stickerDrag;if(!d||d.pointer!==ev.pointerId)return;stickerDrag=null;
 const s=stickerById(d.id);if(s&&(s.center_x!==d.cx||s.center_y!==d.cy))stickerQueueSave(s.id,{center_x:s.center_x,center_y:s.center_y});
}

/* ---------- hooks: draw with the monitor, show the panel with the inspector ---------- */
(function(){
 if(typeof updateChannelCTA==='function'){const before=updateChannelCTA;updateChannelCTA=function(t){before(t);try{updateStickers(t)}catch(e){console.error(e)}}}
 if(typeof renderInspector==='function'){const before=renderInspector;renderInspector=function(...a){const out=before.apply(this,a);try{stickerInjectPanel(false)}catch(e){console.error(e)}return out}}
 window.addEventListener('resize',()=>updateStickers(stickerNow()));
 // While paused nothing ticks, so seeking, scrubbing and stepping would leave stickers
 // where they were. A light check redraws them when the time or the stickers change.
 let lastKey='';
 setInterval(()=>{
  if(typeof editorPlaying!=='undefined'&&editorPlaying)return;
  if(!P||P.edit_mode!=='documentary'||(!stickerRows().length&&!document.querySelector('#sticker-layer *')))return;
  const t=stickerNow(),key=`${P.id}|${t.toFixed(3)}|${stickerSel}|${JSON.stringify(stickerRows())}|${stickerLibFor}`;
  if(key===lastKey&&!stickerDrag)return;lastKey=key;updateStickers(t);
 },200);
})();
