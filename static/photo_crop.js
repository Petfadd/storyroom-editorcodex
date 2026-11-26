/* Adjust crop (v17).

   Every still (person photos and cutaway pictures) is cleaned automatically: the side
   panels of a news screen grab, channel logos sitting on them and black bars are cut
   away, and the clean photo is centred over a blur of itself. When the automatic cut
   is wrong, this window lets the person draw the box by hand, or keep the whole picture.
   Only the selection is saved; the uploaded file is never changed. */

let cropState=null;

function cropTargetQuery(t){return t.person?`person=${encodeURIComponent(t.person)}&index=${t.index||0}`:`asset=${encodeURIComponent(t.asset)}`}

async function openPhotoCrop(target){
 let info;
 try{info=await api(`/api/projects/${P.id}/photo-crop?${cropTargetQuery(target)}`)}catch(e){toast(e.message);return}
 let dlg=document.getElementById('photo-crop-dialog');
 if(!dlg){dlg=document.createElement('dialog');dlg.id='photo-crop-dialog';dlg.className='photo-crop-dialog';document.body.appendChild(dlg)}
 cropState={target,info,box:(info.box||[0,0,1,1]).slice(),mode:info.mode||'auto'};
 dlg.innerHTML=`<form method="dialog" class="crop-head"><h3>Adjust crop</h3><button value="close" aria-label="Close">✕</button></form>
  <p class="small">Drag the box to keep only the real photo. Everything outside it (news panels, channel logos, black bars) is cut away. The photo is then centred over a blur of itself. Your original file is not changed.</p>
  <div class="crop-columns">
   <div><h4>Original</h4><div class="crop-stage" id="crop-stage"><img id="crop-img" alt="Original photo" draggable="false" src="${E(info.original_url)}">
    ${info.auto_box?'<div class="crop-auto" id="crop-auto" title="Automatic cut"></div>':''}
    <div class="crop-box" id="crop-box" tabindex="0" aria-label="Crop box. Arrow keys move it, Shift + arrows resize it.">
     <i data-h="nw"></i><i data-h="ne"></i><i data-h="sw"></i><i data-h="se"></i></div></div>
    <p class="small" id="crop-status"></p></div>
   <div><h4>Result</h4><img id="crop-after" class="crop-after" alt="Result" src="${E(info.after_url)}"></div>
  </div>
  <div class="inline crop-actions">
   <button type="button" onclick="savePhotoCrop('auto')" title="Let Storyroom find the photo (recommended)">Automatic</button>
   <button type="button" onclick="savePhotoCrop('none')" title="Use the whole picture, nothing cut">Whole picture</button>
   <button type="button" class="primary" onclick="savePhotoCrop('manual')">Save my crop</button>
  </div>`;
 if(!dlg.open)dlg.showModal();
 const img=dlg.querySelector('#crop-img');
 const ready=()=>{cropDraw();cropBind()};
 if(img.complete&&img.naturalWidth)ready();else img.onload=ready;
 cropStatus();
}

function cropStatus(){
 const s=cropState,el=document.getElementById('crop-status');if(!s||!el)return;
 const label={auto:s.info.cropped?'Automatic: news panels / bars found and cut away.':'Automatic: nothing to cut, the whole picture is used.',
  manual:'Your own crop.',none:'Whole picture (nothing cut).'}[s.mode]||'';
 el.textContent=label+(s.info.auto_box?'':' The dashed box is not shown because nothing was detected.');
}

function cropDraw(){
 const s=cropState,img=document.getElementById('crop-img');if(!s||!img)return;
 const W=img.clientWidth,H=img.clientHeight,b=s.box,box=document.getElementById('crop-box');
 Object.assign(box.style,{left:b[0]*W+'px',top:b[1]*H+'px',width:(b[2]-b[0])*W+'px',height:(b[3]-b[1])*H+'px'});
 const auto=document.getElementById('crop-auto'),a=s.info.auto_box;
 if(auto&&a)Object.assign(auto.style,{left:a[0]*W+'px',top:a[1]*H+'px',width:(a[2]-a[0])*W+'px',height:(a[3]-a[1])*H+'px'});
}

function cropClamp(b){
 const min=.05;let [x0,y0,x1,y1]=b;
 x0=Math.max(0,Math.min(x0,1-min));y0=Math.max(0,Math.min(y0,1-min));
 x1=Math.min(1,Math.max(x1,x0+min));y1=Math.min(1,Math.max(y1,y0+min));
 return [x0,y0,x1,y1];
}

function cropBind(){
 const box=document.getElementById('crop-box'),img=document.getElementById('crop-img');
 if(!box||box._bound)return;box._bound=true;
 box.addEventListener('pointerdown',e=>{
  e.preventDefault();box.setPointerCapture(e.pointerId);
  const handle=e.target.dataset?.h||'move',start=[e.clientX,e.clientY],from=cropState.box.slice();
  const W=img.clientWidth,H=img.clientHeight;
  const move=ev=>{
   const dx=(ev.clientX-start[0])/W,dy=(ev.clientY-start[1])/H;let b=from.slice();
   if(handle==='move'){const w=from[2]-from[0],h=from[3]-from[1];b[0]=Math.max(0,Math.min(1-w,from[0]+dx));b[1]=Math.max(0,Math.min(1-h,from[1]+dy));b[2]=b[0]+w;b[3]=b[1]+h}
   else{if(handle.includes('w'))b[0]=from[0]+dx;if(handle.includes('e'))b[2]=from[2]+dx;if(handle.includes('n'))b[1]=from[1]+dy;if(handle.includes('s'))b[3]=from[3]+dy;b=cropClamp(b)}
   cropState.box=b;cropState.mode='manual';cropDraw();cropStatus();
  };
  const up=()=>{box.removeEventListener('pointermove',move);box.removeEventListener('pointerup',up);box.removeEventListener('pointercancel',up)};
  box.addEventListener('pointermove',move);box.addEventListener('pointerup',up);box.addEventListener('pointercancel',up);
 });
 box.addEventListener('keydown',e=>{
  const step=e.altKey?.002:.01,k={ArrowLeft:[-step,0],ArrowRight:[step,0],ArrowUp:[0,-step],ArrowDown:[0,step]}[e.key];if(!k)return;
  e.preventDefault();let b=cropState.box.slice();
  if(e.shiftKey){b[2]+=k[0];b[3]+=k[1];b=cropClamp(b)}
  else{const w=b[2]-b[0],h=b[3]-b[1];b[0]=Math.max(0,Math.min(1-w,b[0]+k[0]));b[1]=Math.max(0,Math.min(1-h,b[1]+k[1]));b[2]=b[0]+w;b[3]=b[1]+h}
  cropState.box=b;cropState.mode='manual';cropDraw();cropStatus();
 });
 window.addEventListener('resize',cropDraw);
}

async function savePhotoCrop(mode){
 const s=cropState;if(!s)return;
 const crop=mode==='manual'?{mode:'manual',box:s.box}:{mode};
 const body=Object.assign({crop},s.target.person?{person:s.target.person,index:s.target.index||0}:{asset:s.target.asset});
 let res;
 try{res=await api(`/api/projects/${P.id}/photo-crop`,'POST',body)}catch(e){toast(e.message);return}
 if(res.project&&P&&res.project.id===P.id){
  P=res.project;
  if(document.querySelector('#manage-dialog .people-card')&&typeof updatePeopleCardOnly==='function')updatePeopleCardOnly();
  else if(typeof renderManagement==='function'&&document.querySelector('#manage-dialog[open]'))renderManagement();
  if(typeof requestEditorTick==='function')requestEditorTick();
 }
 s.info=res.crop;s.mode=res.crop.mode;s.box=(res.crop.box||[0,0,1,1]).slice();
 const after=document.getElementById('crop-after');if(after)after.src=res.crop.after_url+(res.crop.after_url.includes('?')?'&':'?')+'t='+Date.now();
 cropDraw();cropStatus();
 toast(mode==='auto'?'Automatic crop restored.':mode==='none'?'Whole picture will be used.':'Crop saved. Preview and export use it.');
}
