/* Channel watermark: an edge logo (always solid) and an optional faint middle logo, on
   every frame of the film. The preview places both on the video picture with the same
   fractions the exporter uses (watermark.py), so what you see is what renders. */
function wmData(){return P?.watermark_report||{settings:{},present:false}}
let wmPanelOpen=true,wmLive=null,wmLiveProject=null;
const WM_LABELS={top_left:'Top left',top_right:'Top right',bottom_left:'Bottom left',bottom_right:'Bottom right',top_center:'Top centre',bottom_center:'Bottom centre'};

/* v18: CTA and watermark sit side by side in one short row of the Shot Inspector, so
   the frame scale and the music volume above stay in view. */
function brandingPanelHTML(){
 if(P?.edit_mode!=='documentary')return '';
 const cta=typeof channelCTAInspectorHTML==='function'?channelCTAInspectorHTML('bottom'):'';
 return `<div class="brand-pair">${cta}${watermarkInspectorHTML()}</div>`;
}
// One − value + row. Hold a button to keep stepping.
function brandStepperHTML(label,id,value,minus,plus,disabled=false,atMin=false,atMax=false){
 return `<div class="brand-step${disabled?' is-off':''}"><span>${label}</span>
 <button type="button" aria-label="${label}: less" ${disabled?'disabled':''} onpointerdown="brandHold(event,()=>{${minus}})" onclick="if(event.detail===0){${minus}}">−</button>
 <output id="${id}-value">${value}%</output>
 <button type="button" aria-label="${label}: more" ${disabled?'disabled':''} onpointerdown="brandHold(event,()=>{${plus}})" onclick="if(event.detail===0){${plus}}">+</button></div>`;
}
function brandSetValue(id,value){const el=document.getElementById(id+'-value');if(el)el.textContent=`${value}%`}
let brandHoldTimer=null;
function brandHold(ev,fn){
 if(ev.button!==undefined&&ev.button!==0)return;
 ev.preventDefault();const target=ev.currentTarget;
 fn();clearTimeout(brandHoldTimer);
 const stop=()=>{clearTimeout(brandHoldTimer);brandHoldTimer=null;['pointerup','pointerleave','pointercancel'].forEach(e=>target.removeEventListener(e,stop))};
 ['pointerup','pointerleave','pointercancel'].forEach(e=>target.addEventListener(e,stop));
 const again=delay=>{brandHoldTimer=setTimeout(()=>{if(target.disabled)return stop();fn();again(70)},delay)};
 again(420);
}

function watermarkInspectorHTML(){
 if(P?.edit_mode!=='documentary')return '';
 const d=wmData(),s={...(d.settings||{}),...(wmLive||{})};
 const pct=v=>Math.round(Number(v||0)*100);
 const opts=(d.positions||Object.keys(WM_LABELS)).map(k=>`<option value="${k}" ${k===s.edge_position?'selected':''}>${WM_LABELS[k]||k}</option>`).join('');
 const off=!d.present;
 const step=(label,key,value,min,max,on)=>brandStepperHTML(label,'wm-'+key,value,`wmStep('${key}',-1)`,`wmStep('${key}',1)`,off||!on,value<=min,value>=max);
 return `<section class="brand-col" id="wm-inspector" aria-label="Channel watermark">
 <header class="brand-head"><span class="brand-title">Watermark</span></header>
 <label class="brand-upload" title="${d.present?'Replace the watermark logo':'Upload a logo (transparent PNG is best)'}"><input type="file" accept="image/png,image/webp,image/jpeg" onchange="uploadWatermark(this)">${d.present?`<img src="${d.url}" alt="Watermark logo">`:'<span>＋ Upload</span>'}</label>
 ${d.present&&d.has_alpha===false?'<p class="brand-status is-warn">No transparency · use a PNG</p>':''}
 <div class="brand-sub"><label class="brand-toggle"><input type="checkbox" ${s.edge_enabled?'checked':''} ${off?'disabled':''} onchange="saveWatermark({edge_enabled:this.checked})"> Edge</label>
 <select aria-label="Edge logo position" onchange="saveWatermark({edge_position:this.value})" ${off||!s.edge_enabled?'disabled':''}>${opts}</select></div>
 ${step('Size','edge_size',pct(s.edge_size),4,40,s.edge_enabled)}
 ${brandStepperHTML('Gap','wm-edge_margin',(Number(s.edge_margin||0)*100).toFixed(1).replace(/\.0$/,''),"wmStep('edge_margin',-1)","wmStep('edge_margin',1)",off||!s.edge_enabled,Number(s.edge_margin||0)<=0,Number(s.edge_margin||0)>=.1)}
 <div class="brand-sub"><label class="brand-toggle"><input type="checkbox" ${s.middle_enabled?'checked':''} ${off?'disabled':''} onchange="saveWatermark({middle_enabled:this.checked})"> Middle</label></div>
 ${step('Size','middle_size',pct(s.middle_size),10,95,s.middle_enabled)}
 ${step('Opacity','middle_opacity',pct(s.middle_opacity),0,100,s.middle_enabled)}
 <label class="wm-position"><span>Up ↕ down</span>
 <input type="range" min="0" max="100" step="1" value="${pct(s.middle_y??.5)}" aria-label="Middle watermark vertical position" ${off||!s.middle_enabled?'disabled':''}
 oninput="previewWatermark('middle_y',this.value);brandSetValue('wm-middle_y',this.value)" onchange="commitWatermark('middle_y',this.value)">
 <output id="wm-middle_y-value">${pct(s.middle_y??.5)}%</output></label>
 <details class="brand-more"><summary>More</summary>
 <label>Owner name in the MP4 file (optional)<input type="text" maxlength="120" value="${E(s.owner||'')}" placeholder="Your channel name" onchange="saveWatermark({owner:this.value})"></label>
 <p class="brand-note">The edge logo is always solid. Both logos show on every frame, under subtitles.</p>
 ${d.present?'<div class="brand-buttons"><button type="button" class="cta-btn subtle" onclick="removeWatermark()">Remove logo</button></div>':''}
 </details>
 </section>`;
}
// − / + for the watermark (values in percent of the picture width / opacity).
const WM_STEPS={edge_size:[1,4,40],edge_margin:[.5,0,10],middle_size:[2,10,95],middle_opacity:[2,0,100]};
let wmStepTimers={};
function wmStep(key,dir){
 const d=wmData(),s={...(d.settings||{}),...(wmLive||{})},[by,lo,hi]=WM_STEPS[key];
 const cur=Number(s[key]||0)*100,v=Math.round(Math.max(lo,Math.min(hi,cur+dir*by))*10)/10;
 previewWatermark(key,v);
 brandSetValue('wm-'+key,key==='edge_margin'?String(v).replace(/\.0$/,''):Math.round(v));
 const id=P?.id;
 clearTimeout(wmStepTimers[key]);wmStepTimers[key]=setTimeout(()=>{if(P?.id===id)commitWatermark(key,v)},500);
}
function previewWatermark(key,value){
 if(!P)return;
 if(wmLiveProject!==P.id){wmLive=null;wmLiveProject=P.id}
 const v=Number(value)/100;wmLive={...(wmLive||{}),[key]:v};
 const label=document.getElementById(`wm-${key.replace('_','-')}-label`);
 if(label)label.textContent=key==='edge_margin'?`${Number(value).toFixed(1)}%`:`${Math.round(Number(value))}%`;
 updateWatermark(true);
}
function commitWatermark(key,value){const v=Number(value)/100;saveWatermark({[key]:v})}
async function saveWatermark(change){
 if(!P)return;const id=P.id;
 try{const saved=await api(`/api/projects/${id}/watermark`,'POST',change);if(P?.id!==id)return;
  P.watermark_report=saved.watermark_report;P.watermark=saved.watermark;P.updated=saved.updated;wmLive=null;
  updateWatermark(true);if(typeof renderExport==='function')renderExport();
  // Sliders update themselves; anything else (position, ticks, owner) redraws the panel.
  const sliderOnly=Object.keys(change).every(k=>['edge_size','middle_size','middle_opacity','middle_y','edge_margin'].includes(k));
  if(!sliderOnly&&typeof renderInspector==='function')renderInspector(true);
 }catch(e){toast(e.message)}
}
async function uploadWatermark(input){
 const file=input.files?.[0];if(!file||!P)return;const form=new FormData();form.append('file',file);
 try{P=await api(`/api/projects/${P.id}/watermark/upload`,'POST',form);renderProject();updateWatermark(true);toast('Watermark logo uploaded. It now shows on every frame.')}catch(e){toast(e.message)}
}
async function removeWatermark(){
 if(!confirm('Remove the watermark logo from this project?'))return;
 try{P=await api(`/api/projects/${P.id}/watermark`,'DELETE');renderProject();updateWatermark(true)}catch(e){toast(e.message)}
}
// The picture's rectangle inside the monitor (the frame may be letterboxed).
function wmPictureRect(frame){
 if(typeof ctaPictureRect==='function')return ctaPictureRect(frame);
 const fw=frame.clientWidth,fh=frame.clientHeight;let pw=fw,ph=fw*9/16;if(ph>fh){ph=fh;pw=fh*16/9}
 return {ox:(fw-pw)/2,oy:(fh-ph)/2,pw,ph,fw,fh};
}
function dragMiddleWatermark(event){
 if(event.button!==0||!P)return;
 const id=P.id,img=event.currentTarget,rect=wmPictureRect(img.parentNode);
 const travel=rect.ph-img.offsetHeight;
 if(travel<=0)return;
 event.preventDefault();
 const initialY=event.clientY;
 const initial=100*(wmLive?.middle_y??wmData().settings.middle_y??.5);
 let value=initial;
 img.setPointerCapture(event.pointerId);
 const move=e=>{
  if(P?.id!==id)return;
  value=Math.round(Math.max(0,Math.min(100,initial+(e.clientY-initialY)*100/travel)));
  previewWatermark('middle_y',value);
  brandSetValue('wm-middle_y',value);
  const slider=document.querySelector('.wm-position input');
  if(slider)slider.value=value;
 };
 const finish=e=>{
  img.removeEventListener('pointermove',move);
  img.removeEventListener('pointerup',finish);
  img.removeEventListener('pointercancel',finish);
  if(P?.id!==id)return;
  if(e.type==='pointercancel'){wmLive=null;updateWatermark(true);renderInspector(true);return}
  if(value!==initial)commitWatermark('middle_y',value);
 };
 img.addEventListener('pointermove',move);
 img.addEventListener('pointerup',finish);
 img.addEventListener('pointercancel',finish);
}
function updateWatermark(force=false){
 if(wmLiveProject!==P?.id){wmLive=null;wmLiveProject=P?.id}
 const frame=document.getElementById('monitor-frame');if(!frame)return;
 const layers={};
 for(const name of ['middle','edge']){
  let img=document.getElementById(`wm-${name}`);
  if(!img){img=document.createElement('img');img.id=`wm-${name}`;img.className=`wm-layer-img wm-${name}`;img.alt='';
   frame.insertBefore(img,document.getElementById('editor-captions')||null);img.onload=()=>updateWatermark(true);
   if(name==='middle'){img.draggable=false;img.title='Drag the middle watermark up or down';img.onpointerdown=dragMiddleWatermark}}
  layers[name]=img;
 }
 const d=wmData(),s={...(d.settings||{}),...(wmLive||{})},timeline=window.docTimelineData;
 // The export-matched low-res preview already has the watermark burned in.
 const burned=timeline&&!timeline.direct&&timeline.renderer==='export_matched_lowres';
 const show=!!(P&&d.present&&P.edit_mode==='documentary'&&!burned);
 const r=wmPictureRect(frame);
 const key=[show,d.url,JSON.stringify(s),r.pw.toFixed(1),r.ph.toFixed(1),r.ox.toFixed(1),r.oy.toFixed(1)].join('|');
 if(!force&&frame._wmKey===key)return;frame._wmKey=key;
 for(const [name,img] of Object.entries(layers)){
  const on=show&&(name==='edge'?s.edge_enabled:s.middle_enabled&&Number(s.middle_opacity)>0);
  if(!on){img.style.display='none';continue}
  if(img.dataset.url!==d.url){img.dataset.url=d.url;img.src=d.url}
  const ratio=img.naturalWidth&&img.naturalHeight?img.naturalWidth/img.naturalHeight:1;
  let w,h,x,y;
  if(name==='edge'){
   w=r.pw*Number(s.edge_size);h=w/ratio;if(h>r.ph*.45){h=r.ph*.45;w=h*ratio}
   const m=r.pw*Number(s.edge_margin||0),pos=s.edge_position||'top_right';
   x=pos.endsWith('left')?m:pos.endsWith('right')?r.pw-w-m:(r.pw-w)/2;
   y=pos.startsWith('top')?m:r.ph-h-m;
   img.style.opacity='1';
  }else{
   w=r.pw*Number(s.middle_size);h=w/ratio;if(h>r.ph*.95){h=r.ph*.95;w=h*ratio}
   x=(r.pw-w)/2;y=(r.ph-h)*Number(s.middle_y??.5);img.style.opacity=String(Number(s.middle_opacity));
  }
  Object.assign(img.style,{display:'block',left:`${r.ox+Math.max(0,x)}px`,top:`${r.oy+Math.max(0,y)}px`,width:`${w}px`,height:`${h}px`});
 }
}
window.addEventListener('resize',()=>updateWatermark(true));
