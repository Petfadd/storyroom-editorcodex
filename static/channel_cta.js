/* Channel CTA card: a project-wide overlay drawn on the finished film clock.

   Geometry is stored as three fractions of the OUTPUT picture:
     width    – card width / picture width (0.20 … 1.00)
     center_x – card centre / picture width (0 … 1)
     center_y – card centre / picture height (0 … 1)
   The card never leaves the picture and never exceeds its height. The preview measures
   against the video picture inside the monitor (not the letterboxed monitor box), and
   saves exactly the placement that is on screen, so export matches what you see. */
function ctaData(){return P?.channel_cta_report||{settings:{},windows:[],present:false}}
function ctaTime(s){const n=Math.max(0,Number(s)||0),m=Math.floor(n/60);return `${m}:${String(Math.floor(n%60)).padStart(2,'0')}.${String(Math.round((n%1)*1000)).padStart(3,'0')}`}

// Backend defaults (channel_cta.DEFAULTS). Kept in one place so every fallback agrees.
const CTA_DEFAULTS={opacity:.70,width:.97,center_x:.5,center_y:.5,slide_s:.55,fade_s:.25,motion_style:'auto_varied'};
const CTA_MIN_WIDTH=.20,CTA_MAX_WIDTH=1.0;
// v26: the card shows outside its CTA window only for a few seconds after you adjust it
// (−/+, upload, drag). It used to stay switched on for good, so the card hung over the
// whole film in the monitor. Playing always shows the real timing.
let channelCTAPreviewUntil=0,ctaPeekTimer=0;
const ctaNow=()=>typeof performance!=='undefined'?performance.now():Date.now();
const CTA_PEEK_MS=3000;
function ctaPeek(ms=CTA_PEEK_MS){
 channelCTAPreviewUntil=ctaNow()+ms;clearTimeout(ctaPeekTimer);
 ctaPeekTimer=setTimeout(()=>updateChannelCTA(channelCTAMonitorTime()),ms+40);
}
function ctaPlaying(){return typeof editorPlaying!=='undefined'&&!!editorPlaying}
let channelCTALiveOpacity=null;
let channelCTAEditing=false;
let channelCTADraft=null;
let channelCTADrag=null;
let channelCTAKeyTimer=null;
const ctaClamp=(v,lo,hi)=>Math.max(lo,Math.min(hi,v));
const ctaNum=(v,fallback)=>Number.isFinite(Number(v))&&v!==null&&v!==''?Number(v):fallback;
function ctaSettings(){return {...CTA_DEFAULTS,...(ctaData().settings||{})}}

/* The output picture's rectangle inside the monitor frame (the frame may be wider or
   taller than the film when the panel is resized; the video is letterboxed inside it). */
function ctaPictureRect(frame){
 const fw=frame.clientWidth||0,fh=frame.clientHeight||0;
 const shape=(typeof MONITOR_SHAPES!=='undefined'&&MONITOR_SHAPES[P?.format])||'16:9';
 const [a,b]=String(shape).split(':').map(Number);const ratio=a>0&&b>0?a/b:16/9;
 let pw=fw,ph=fw/ratio;if(ph>fh){ph=fh;pw=fh*ratio}
 return {ox:(fw-pw)/2,oy:(fh-ph)/2,pw,ph,fw,fh};
}
function ctaCardRatio(img){return img&&img.naturalWidth>0&&img.naturalHeight>0?img.naturalWidth/img.naturalHeight:16/9}

/* Turn stored fractions into on-screen pixels, clamped exactly like the exporter. */
function ctaLayout(rect,ratio,g){
 let w=rect.pw*ctaClamp(ctaNum(g.width,CTA_DEFAULTS.width),CTA_MIN_WIDTH,CTA_MAX_WIDTH);
 if(w/ratio>rect.ph)w=rect.ph*ratio;
 const h=w/ratio;
 const x=ctaClamp(ctaNum(g.center_x,.5)*rect.pw-w/2,0,Math.max(0,rect.pw-w));
 const y=ctaClamp(ctaNum(g.center_y,.5)*rect.ph-h/2,0,Math.max(0,rect.ph-h));
 return {w,h,x,y,cx:(x+w/2)/rect.pw,cy:(y+h/2)/rect.ph,width:w/rect.pw};
}
function ctaGeometry(frame,img,config){
 const rect=ctaPictureRect(frame),g={...CTA_DEFAULTS,...config,...(channelCTADraft||{})};
 const L=ctaLayout(rect,ctaCardRatio(img),g);
 return {...L,fw:rect.fw,fh:rect.fh,pw:rect.pw,ph:rect.ph,ox:rect.ox,oy:rect.oy,left:rect.ox+L.x,top:rect.oy+L.y};
}
/* What is saved = what is seen: centre and width after clamping. */
function ctaVisiblePatch(geo){
 const r=v=>Math.round(v*10000)/10000;
 return {width:r(ctaClamp(geo.width,CTA_MIN_WIDTH,CTA_MAX_WIDTH)),center_x:r(ctaClamp(geo.cx,0,1)),center_y:r(ctaClamp(geo.cy,0,1))};
}

function ctaEditBox(frame){
 let box=document.getElementById('channel-cta-edit-box');
 if(!box){
   box=document.createElement('div');box.id='channel-cta-edit-box';box.className='channel-cta-edit-box';
   box.setAttribute('aria-label','CTA card. Drag to move, drag a corner to resize. Arrow keys move, plus and minus resize.');
   box.setAttribute('role','application');box.tabIndex=0;
   for(const corner of ['nw','ne','sw','se']){
     const handle=document.createElement('div');handle.className='channel-cta-resize';handle.dataset.corner=corner;
     handle.title='Drag to make the card bigger or smaller';box.appendChild(handle);
   }
   const label=document.createElement('div');label.className='channel-cta-size-badge';label.id='channel-cta-size-badge';box.appendChild(label);
   frame.appendChild(box);
   box.addEventListener('pointerdown',ctaPointerStart);
   box.addEventListener('pointermove',ctaPointerMove);box.addEventListener('pointerup',ctaPointerEnd);
   box.addEventListener('pointercancel',ctaPointerCancel);
   if(box.addEventListener)box.addEventListener('keydown',ctaKeyDown);
 }
 return box;
}
function toggleChannelCTAAdjust(){
 channelCTAEditing=!channelCTAEditing;channelCTADraft=null;
 const b=document.getElementById('cta-adjust-button');if(b){b.textContent=channelCTAEditing?'Done adjusting':'Move / resize on video';b.classList?.toggle('is-on',channelCTAEditing)}
 updateChannelCTA(channelCTAMonitorTime());
 if(channelCTAEditing){const box=document.getElementById('channel-cta-edit-box');try{box?.focus?.({preventScroll:true})}catch{}}
}
function resetChannelCTAGeometry(){channelCTADraft=null;saveChannelCTA({width:CTA_DEFAULTS.width,center_x:.5,center_y:.5});}
function ctaSyncControls(g){
 const pct=v=>Math.round(v*100);
 const set=(id,v)=>{const el=document.getElementById(id);if(el&&document.activeElement!==el)el.value=v};
 const text=(id,v)=>{const el=document.getElementById(id);if(el)el.textContent=v};
 set('cta-size-range',pct(g.width));text('cta-size-label',`${pct(g.width)}%`);
 set('cta-x-range',pct(g.center_x));text('cta-x-label',`${pct(g.center_x)}%`);
 set('cta-y-range',pct(g.center_y));text('cta-y-label',`${pct(g.center_y)}%`);
 text('channel-cta-size-badge',`${pct(g.width)}%`);
 if(typeof brandSetValue==='function'){brandSetValue('cta-width',pct(g.width));brandSetValue('cta-center_x',pct(g.center_x));brandSetValue('cta-center_y',pct(g.center_y))}
}
function previewChannelCTAWidth(value){
 ctaPeek();
 channelCTADraft={...(channelCTADraft||{}),width:ctaClamp(Number(value)/100,CTA_MIN_WIDTH,CTA_MAX_WIDTH)};
 updateChannelCTA(channelCTAMonitorTime());
}
function previewChannelCTAPosition(axis,value){
 ctaPeek();
 channelCTADraft={...(channelCTADraft||{}),[axis]:ctaClamp(Number(value)/100,0,1)};
 updateChannelCTA(channelCTAMonitorTime());
}
function ctaCommitDraft(){
 const frame=document.getElementById('monitor-frame'),img=document.getElementById('channel-cta-preview');
 const s=ctaSettings();
 let patch;
 if(frame&&img&&(frame.clientWidth||0)>0)patch=ctaVisiblePatch(ctaGeometry(frame,img,s));
 else patch={width:ctaNum(channelCTADraft?.width,s.width),center_x:ctaNum(channelCTADraft?.center_x,s.center_x),center_y:ctaNum(channelCTADraft?.center_y,s.center_y)};
 channelCTADraft=null;saveChannelCTA(patch);
}

/* Pointer editing. Moving keeps the card inside the picture. A corner handle resizes
   about the card's centre, so the card grows or shrinks evenly on both sides and the
   dragged corner stays under the pointer (projection onto the corner's diagonal). */
function ctaPointerStart(ev){
 if(!channelCTAEditing||ev.button!==0)return;
 const box=ev.currentTarget,frame=document.getElementById('monitor-frame'),img=document.getElementById('channel-cta-preview');
 if(!frame||!img)return;
 ev.preventDefault();ev.stopPropagation();
 const g=ctaGeometry(frame,img,ctaSettings());
 const target=ev.target,corner=target?.dataset?.corner||(target?.classList?.contains('channel-cta-resize')?'se':null);
 channelCTADrag={pointerId:ev.pointerId,startX:ev.clientX,startY:ev.clientY,corner,g,ratio:ctaCardRatio(img),
   // Pointer position relative to the card centre at the start, in picture pixels.
   ox:0,oy:0};
 if(corner){
   const sx=corner.includes('e')?1:-1,sy=corner.includes('s')?1:-1;
   channelCTADrag.dir={x:sx*g.w/2,y:sy*g.h/2};
 }
 try{box.setPointerCapture(ev.pointerId)}catch{}
 try{box.focus?.({preventScroll:true})}catch{}
}
function ctaPointerMove(ev){
 const drag=channelCTADrag;
 if(!drag||drag.pointerId!==ev.pointerId)return;
 ev.preventDefault();ev.stopPropagation();
 const g=drag.g,dx=ev.clientX-drag.startX,dy=ev.clientY-drag.startY;
 if(drag.corner){
   // Vector from the card centre to the pointer = original corner vector + movement.
   const vx=drag.dir.x+dx,vy=drag.dir.y+dy;
   const d2=drag.dir.x*drag.dir.x+drag.dir.y*drag.dir.y||1;
   const scale=Math.max(0,(vx*drag.dir.x+vy*drag.dir.y)/d2);
   let w=g.w*scale;
   w=Math.min(w,g.pw*CTA_MAX_WIDTH,g.ph*drag.ratio);
   w=Math.max(w,g.pw*CTA_MIN_WIDTH);
   channelCTADraft={width:w/g.pw,center_x:g.cx,center_y:g.cy};
 } else {
   channelCTADraft={width:g.width,center_x:ctaClamp(g.cx+dx/g.pw,0,1),center_y:ctaClamp(g.cy+dy/g.ph,0,1)};
 }
 updateChannelCTA(channelCTAMonitorTime());
}
function ctaPointerEnd(ev){
 if(!channelCTADrag||channelCTADrag.pointerId!==ev.pointerId)return;
 ev.preventDefault();ev.stopPropagation();channelCTADrag=null;
 if(channelCTADraft&&Object.keys(channelCTADraft).length)ctaCommitDraft();
}
function ctaPointerCancel(){channelCTADrag=null;channelCTADraft=null;updateChannelCTA(channelCTAMonitorTime())}

/* Keyboard: arrows move 0.5% (Shift 5%), + / - resize 1% (Shift 5%), Enter or Esc finish. */
function ctaKeyDown(ev){
 if(!channelCTAEditing)return;
 const s=ctaSettings(),base={width:s.width,center_x:s.center_x,center_y:s.center_y,...(channelCTADraft||{})};
 const step=ev.shiftKey?.05:.005,size=ev.shiftKey?.05:.01;
 const k=ev.key;let handled=true;
 if(k==='ArrowLeft')base.center_x=ctaClamp(base.center_x-step,0,1);
 else if(k==='ArrowRight')base.center_x=ctaClamp(base.center_x+step,0,1);
 else if(k==='ArrowUp')base.center_y=ctaClamp(base.center_y-step,0,1);
 else if(k==='ArrowDown')base.center_y=ctaClamp(base.center_y+step,0,1);
 else if(k==='+'||k==='=')base.width=ctaClamp(base.width+size,CTA_MIN_WIDTH,CTA_MAX_WIDTH);
 else if(k==='-'||k==='_')base.width=ctaClamp(base.width-size,CTA_MIN_WIDTH,CTA_MAX_WIDTH);
 else if(k==='Enter'||k==='Escape'){toggleChannelCTAAdjust();handled=true}
 else handled=false;
 if(!handled)return;
 ev.preventDefault();ev.stopPropagation();
 if(k==='Enter'||k==='Escape')return;
 channelCTADraft=base;updateChannelCTA(channelCTAMonitorTime());
 clearTimeout(channelCTAKeyTimer);channelCTAKeyTimer=setTimeout(ctaCommitDraft,450);
}

function channelCTAInspectorHTML(placement='top'){
 if(P?.edit_mode!=='documentary')return '';
 const d=ctaData(),s=ctaSettings(),w=d.windows||[];
 const g={width:ctaNum(channelCTADraft?.width,s.width),center_x:ctaNum(channelCTADraft?.center_x,s.center_x),center_y:ctaNum(channelCTADraft?.center_y,s.center_y)};
 const opacity=channelCTALiveOpacity??s.opacity;
 const pct=v=>Math.round(v*100);
 const option=(key,label,selected)=>`<option value="${key}" ${key===selected?'selected':''}>${label}</option>`;
 const found=d.detected||w,clock=ms=>{const t=Math.max(0,ms)/1000,h=Math.floor(t/3600),m=Math.floor(t%3600/60),sec=t%60;return `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${sec.toFixed(3).padStart(6,'0')}`};
 const many=found.length>1&&s.mode!=='manual';
 const warn=many?`<div class="cta-inspector-status is-warn"><strong>${found.length} CTA moments found.</strong> ${s.occurrences==='all'?'All of them show the card.':'Only the first shows the card.'}
   <label class="cta-check" style="margin-top:6px"><input type="checkbox" ${s.occurrences==='all'?'checked':''} onchange="saveChannelCTA({occurrences:this.checked?'all':'first'})"> Show the card at every moment</label></div>`:'';
 const matched=(found||[]).flatMap((x,n)=>(x.matches||[]).filter(m=>m.trigger).map(m=>({...m,n})));
 const matchList=matched.length?`<details class="cta-matches"><summary>Narration lines that trigger the card (${matched.length})</summary><ul>${matched.map(m=>`<li><span>${m.cue!=null?'SRT '+E(String(m.cue)):'Beat '+E(String(m.beat||''))}${found.length>1?` · moment ${m.n+1}${m.n>0&&s.occurrences!=='all'?' (not shown)':''}`:''}</span><span>${clock(m.start_ms)} → ${clock(m.end_ms)}</span><em>${E(m.text)}</em></li>`).join('')}</ul></details>`:'';
 // v18: a short column beside the watermark. A small upload tile opens the folder,
 // and − / + buttons replace the long sliders. Everything else sits under "More".
 const step=(label,key,value,min,max)=>brandStepperHTML(label,'cta-'+key,value,`ctaStep('${key}',-1)`,`ctaStep('${key}',1)`,!d.present,value<=min,value>=max);
 const status=!d.present?'':!s.enabled?'<p class="brand-status">Off</p>':
   w.length?`<p class="brand-status is-ok" title="${E(w.map(x=>ctaTime(x.start_ms/1000)+'–'+ctaTime(x.end_ms/1000)).join(', '))}">Shows at ${ctaTime(w[0].start_ms/1000)}${w.length>1?` +${w.length-1}`:''}</p>`:
   '<p class="brand-status is-warn">No CTA line found · set times under More</p>';
 return `<section class="brand-col" id="cta-inspector" aria-label="Channel CTA card">
 <header class="brand-head"><span class="brand-title">CTA</span><label class="brand-toggle" title="Show the CTA card"><input type="checkbox" ${s.enabled?'checked':''} onchange="saveChannelCTA({enabled:this.checked})"> On</label></header>
 <label class="brand-upload" title="${d.present?'Replace the CTA card':'Upload a CTA card (PNG, WebP or JPG)'}"><input id="cta-inspector-upload" type="file" accept="image/png,image/webp,image/jpeg" onchange="uploadChannelCTA(this)">${d.present?`<img src="${d.url}" alt="CTA card">`:'<span>＋ Upload</span>'}</label>
 ${status}
 ${step('Opacity','opacity',pct(opacity),0,100)}
 ${step('Size','width',pct(g.width),Math.round(CTA_MIN_WIDTH*100),Math.round(CTA_MAX_WIDTH*100))}
 ${step('Left ↔ right','center_x',pct(g.center_x),0,100)}
 ${step('Up ↕ down','center_y',pct(g.center_y),0,100)}
 <details class="brand-more"><summary>More</summary>
 ${warn}${matchList}
 <div class="brand-buttons"><button type="button" class="cta-btn${channelCTAEditing?' is-on':''}" id="cta-adjust-button" onclick="toggleChannelCTAAdjust()" ${d.present?'':'disabled'}>${channelCTAEditing?'Done':'Move on video'}</button><button type="button" class="cta-btn" onclick="resetChannelCTAGeometry()" ${d.present?'':'disabled'}>Large &amp; centre</button><button type="button" class="cta-btn" id="cta-preview-toggle" onclick="toggleChannelCTAPreview()" ${d.present?'':'disabled'}>${ctaNow()<channelCTAPreviewUntil?'Hide preview':'Preview'}</button>${w.length?'<button type="button" class="cta-btn" onclick="jumpToChannelCTA()">Jump to CTA</button>':''}</div>
 <label>Timing<select onchange="saveChannelCTA({mode:this.value})">${option('auto','Auto · narrator SRT / script',s.mode||'auto')}${option('manual','Manual · film clock',s.mode)}</select></label>
 ${s.mode==='manual'?`<label>Start (s)<input type="number" min="0" step=".001" value="${s.manual_in_s??''}" onchange="saveChannelCTA({manual_in_s:this.value===''?null:Number(this.value)})"></label><label>End (s)<input type="number" min="0" step=".001" value="${s.manual_out_s??''}" onchange="saveChannelCTA({manual_out_s:this.value===''?null:Number(this.value)})"></label>`:''}
 <label>Motion<select onchange="saveChannelCTA({motion_style:this.value})">${option('auto_varied','Automatic variety',s.motion_style||'auto_varied')}${option('top_down','Top in · bottom out',s.motion_style)}${option('left_right','Left in · right out',s.motion_style)}${option('right_left','Right in · left out',s.motion_style)}${option('dissolve','Gentle dissolve',s.motion_style)}</select></label>
 <label>Slide in (s)<input type="number" min="0" max="2" step=".05" value="${s.slide_s}" onchange="saveChannelCTA({slide_s:Number(this.value)})"></label>
 <label>Fade (s)<input type="number" min="0" max="2" step=".05" value="${s.fade_s}" onchange="saveChannelCTA({fade_s:Number(this.value)})"></label>
 ${d.present?'<div class="brand-buttons"><button type="button" class="cta-btn subtle" onclick="removeChannelCTA()">Remove card</button></div>':''}
 </details>
 </section>`;
}
// − / + for the CTA: the card moves on the monitor at once; the change is saved a
// moment after the last press, so holding a button does not send a save per step.
let ctaStepTimers={};
function ctaStep(key,dir){
 const s=ctaSettings(),stepBy={opacity:5,width:2,center_x:2,center_y:2}[key]||1;
 if(key==='opacity'){
  const cur=Math.round((channelCTALiveOpacity??s.opacity)*100),v=Math.max(0,Math.min(100,cur+dir*stepBy));
  previewChannelCTAOpacity(v);brandSetValue('cta-opacity',v);
  clearTimeout(ctaStepTimers.opacity);ctaStepTimers.opacity=setTimeout(()=>commitChannelCTAOpacity(v),500);return;
 }
 const cur=Math.round(ctaNum(channelCTADraft?.[key],s[key])*100);
 const lo=key==='width'?Math.round(CTA_MIN_WIDTH*100):0,hi=key==='width'?Math.round(CTA_MAX_WIDTH*100):100;
 const v=Math.max(lo,Math.min(hi,cur+dir*stepBy));
 if(key==='width')previewChannelCTAWidth(v);else previewChannelCTAPosition(key,v);
 brandSetValue('cta-'+key,v);
 clearTimeout(ctaStepTimers.geom);ctaStepTimers.geom=setTimeout(ctaCommitDraft,500);
}
function channelCTAMonitorTime(){const d=window.docTimelineData;return d?.status==='ready'?(d.direct?(typeof narrNode!=='undefined'?narrNode?.currentTime||0:0):(typeof masterNode!=='undefined'?masterNode?.currentTime||0:0)):(typeof editorTime==='function'?editorTime():0)}
function previewChannelCTAOpacity(value){
 channelCTALiveOpacity=Math.max(0,Math.min(1,Number(value)/100));
 const label=document.getElementById('cta-opacity-label');if(label)label.textContent=`${Math.round(channelCTALiveOpacity*100)}%`;if(typeof brandSetValue==='function')brandSetValue('cta-opacity',Math.round(channelCTALiveOpacity*100));
 updateChannelCTA(channelCTAMonitorTime());
}
async function commitChannelCTAOpacity(value){
 const v=Math.max(0,Math.min(1,Number(value)/100));
 try{await saveChannelCTA({opacity:v});channelCTALiveOpacity=null}catch(e){toast(e.message)}
}
function toggleChannelCTAPreview(){
 const on=ctaNow()<channelCTAPreviewUntil;
 if(on){channelCTAPreviewUntil=0}else ctaPeek(5000);
 const button=document.querySelector('#cta-preview-toggle');if(button)button.textContent=on?'Preview':'Hide preview';
 updateChannelCTA(channelCTAMonitorTime());
}
function ctaAfterSave(saved){
 // The save returns the whole project, including whether the last MP4 still matches.
 if(saved?.render)P.render=saved.render;
 if(typeof renderExport==='function')renderExport();
}
async function saveChannelCTA(change){if(!P)return;const id=P.id;try{const saved=await api(`/api/projects/${id}/channel-cta`,'POST',change);if(P?.id!==id)return;P.channel_cta_report=saved.channel_cta_report;P.channel_cta=saved.channel_cta;P.updated=saved.updated;channelCTALiveOpacity=null;updateChannelCTA(channelCTAMonitorTime());ctaAfterSave(saved);const status=typeof $==='function'?$('#scene-save-status'):null;if(status)status.textContent='CTA saved · Render again to update the MP4';if(!('opacity' in change)&&typeof renderInspector==='function')renderInspector(true);}catch(e){toast(e.message)}}
async function uploadChannelCTA(input){const file=input.files?.[0];if(!file)return;const form=new FormData();form.append('file',file);try{P=await api(`/api/projects/${P.id}/channel-cta/upload`,'POST',form);ctaPeek(5000);renderManagement();renderProject();toast('Channel CTA card uploaded. It starts large and centred — drag or resize it on the video.')}catch(e){toast(e.message)}}
async function removeChannelCTA(){if(!confirm('Remove the channel CTA card from this project?'))return;try{P=await api(`/api/projects/${P.id}/channel-cta`,'DELETE');channelCTAEditing=false;renderManagement();renderProject()}catch(e){toast(e.message)}}

function ctaMotionOffset(direction,geo,phaseIn,phaseOut){
 // Same path as the exporter: slides start/end fully outside the picture.
 const inX={left_right:-(geo.x+geo.w+3),right_left:geo.pw-geo.x+3}[direction]||0;
 const outX={left_right:geo.pw-geo.x+3,right_left:-(geo.x+geo.w+3)}[direction]||0;
 const inY=direction==='top_down'?-(geo.y+geo.h+3):0;
 const outY=direction==='top_down'?geo.ph-geo.y+3:0;
 return {dx:inX*phaseIn+outX*phaseOut,dy:inY*phaseIn+outY*phaseOut};
}
function updateChannelCTA(t){
 const frame=document.querySelector('#monitor-frame');if(!frame)return;
 let img=document.getElementById('channel-cta-preview');
 if(!img){img=document.createElement('img');img.id='channel-cta-preview';img.className='channel-cta-preview';img.alt='';frame.insertBefore(img,document.getElementById('editor-captions')||null);
   img.onload=()=>updateChannelCTA(channelCTAMonitorTime());}
 const box=ctaEditBox(frame);
 const d=ctaData(),s=ctaSettings();
 if(!P||!d.present||P?.edit_mode!=='documentary'||(!s.enabled&&!channelCTAEditing)){
   img.style.opacity='0';box.style.display='none';return;
 }
 if(ctaPlaying()){
   // Playing shows the card only inside its CTA window, exactly like the export.
   channelCTAPreviewUntil=0;
   if(channelCTAEditing&&!channelCTADrag){channelCTAEditing=false;const b=document.getElementById('cta-adjust-button');if(b){b.textContent='Move on video';b.classList?.remove('is-on')}}
 }
 const editingView=channelCTAEditing||ctaNow()<channelCTAPreviewUntil;
 const timeline=window.docTimelineData;
 // The export-matched low-res preview already has the card burned in; only show the
 // live card there while it is being adjusted.
 if(!editingView&&timeline&&!timeline.direct&&timeline.renderer==='export_matched_lowres'){
   img.style.opacity='0';box.style.display='none';return;
 }
 const w=(d.windows||[]).find(x=>t>=x.start_ms/1000&&t<x.end_ms/1000);
 if(!w&&!editingView){img.style.opacity='0';box.style.display='none';return;}
 if(img.dataset.url!==d.url){img.dataset.url=d.url;img.src=d.url;}
 const g=ctaGeometry(frame,img,s);
 img.style.width=`${g.w}px`;img.style.height=`${g.h}px`;
 img.style.left=`${g.left}px`;img.style.top=`${g.top}px`;img.style.right='auto';img.style.bottom='auto';
 box.style.left=`${g.left}px`;box.style.top=`${g.top}px`;
 box.style.width=`${g.w}px`;box.style.height=`${g.h}px`;
 box.style.display=channelCTAEditing?'block':'none';
 ctaSyncControls({width:g.width,center_x:g.cx,center_y:g.cy});
 const wStart=w?w.start_ms/1000:t,wEnd=w?w.end_ms/1000:t+5;
 const direction=w?.motion_style||s.motion_style||'top_down';
 const duration=Math.max(.001,wEnd-wStart);
 const smooth=x=>{const u=ctaClamp(x,0,1);return u*u*(3-2*u)};
 const animate=!editingView&&!!w;
 const elapsed=t-wStart;
 // Caps match channel_cta.render_filters: slide ≤ window/3, fade ≤ window/5.
 const slideSec=animate&&direction!=='dissolve'?Math.min(s.slide_s,duration/3):0;
 const entering=slideSec&&elapsed<slideSec?1-smooth(elapsed/slideSec):0;
 const exiting=slideSec&&t>wEnd-slideSec?smooth((t-(wEnd-slideSec))/slideSec):0;
 const off=ctaMotionOffset(direction,g,entering,exiting);
 img.style.transform=`translate3d(${off.dx}px,${off.dy}px,0)`;
 const fade=animate?Math.min(s.fade_s,duration/5):0;
 const alpha=Math.min(1,fade?elapsed/fade:1,fade?(wEnd-t)/fade:1);
 img.style.opacity=String(Math.max(0,alpha*(channelCTALiveOpacity??s.opacity)));
}

function jumpToChannelCTA(){const w=ctaData().windows?.[0];if(!w){toast('No CTA interval is available yet.');return}if(P?.edit_mode==='documentary'){document.querySelector('#manage-dialog')?.close();docSeekTimeline(w.start_ms/1000,true);toast('Jumped to CTA. Press play to review the slide-in.')}else toast('Open a documentary timeline first.')}
