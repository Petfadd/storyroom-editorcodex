/* Project-scoped design review for narration-synchronised graphics.
   It saves style choices but cannot place a graphic on the timeline. */
let cinematicGraphicsState=null;

function cgOptions(values,current){return values.map(value=>`<option value="${E(value)}" ${value===current?'selected':''}>${E(value.replaceAll('_',' '))}</option>`).join('')}
function cgCueText(block){return String(block?.text||block?.caption||block?.line||'').replace(/<[^>]+>/g,'').trim()}
function cgPreviewItems(){
 const blocks=P?.srt?.blocks||[],seen=new Set(),items=[];
 for(const block of blocks){const text=cgCueText(block);if(!text||seen.has(text))continue;seen.add(text);items.push({text,start:Number(block.start_ms||0)});if(items.length===3)break}
 if(!items.length&&P?.title)items.push({text:P.title,start:0});
 return items;
}
function cgClock(ms){const seconds=Math.max(0,Math.round(ms/1000));return String(Math.floor(seconds/60)).padStart(2,'0')+':'+String(seconds%60).padStart(2,'0')}

async function openCinematicGraphics(){
 if(!P)return;
 const dialog=$('#cinematic-graphics-dialog'),body=$('#cinematic-graphics-body');
 body.innerHTML='<p>Loading the saved design…</p>';if(!dialog.open)dialog.showModal();
 try{cinematicGraphicsState=await api(`/api/projects/${P.id}/cinematic-graphics`);cgRenderEditor()}
 catch(error){body.innerHTML=`<p class="notice warn">${E(error.message)}</p>`}
}
function closeCinematicGraphics(){$('#cinematic-graphics-dialog').close()}

function cgRenderEditor(){
 const state=cinematicGraphicsState,settings=state.settings,design=settings.design,preview=settings.preview,cat=state.catalogue;
 $('#cinematic-graphics-body').innerHTML=`
  <div class="notice"><strong>Review-only design</strong><p>Changes are saved to this project. Automatic timeline placement and final export are locked until the animation quality is approved.</p></div>
  <div class="cg-workspace">
   <section class="cg-preview-panel">
    <div class="cg-stage-shell"><div class="cg-stage" id="cg-stage"><div class="cg-backdrop"></div><div class="cg-content"><div class="cg-rule"></div><div class="cg-kicker">${E(P.title||'')}</div><h3 id="cg-preview-title"></h3><p id="cg-preview-subtitle"></p><div id="cg-preview-items" class="cg-preview-items"></div></div></div></div>
    <div class="cg-preview-actions"><button type="button" class="button secondary" onclick="cgReplay()">↻ Replay motion</button><span id="cg-readability" class="cg-readability"></span></div>
   </section>
   <section class="cg-controls" oninput="cgUpdatePreview()" onchange="cgUpdatePreview()">
    <fieldset><legend>Words</legend><label>Title<input id="cg-title" maxlength="90" value="${E(preview.title)}" placeholder="Uses the project title when blank"></label><label>Subtitle · optional<input id="cg-subtitle" maxlength="140" value="${E(preview.subtitle)}" placeholder="Leave blank to show no underneath text"></label></fieldset>
    <fieldset><legend>Motion</legend><div class="cg-control-grid"><label>Style<select id="cg-motion">${cgOptions(cat.motions,design.motion)}</select></label><label>Speed <output id="cg-speed-out"></output><input id="cg-speed" type="range" min="0.65" max="1.65" step="0.05" value="${design.speed}"></label><label>Background movement <output id="cg-bg-motion-out"></output><input id="cg-bg-motion" type="range" min="0" max="1.5" step="0.05" value="${design.background_motion}"></label></div></fieldset>
    <fieldset><legend>Background and colour</legend><div class="cg-control-grid"><label>Background<select id="cg-background">${cgOptions(cat.backgrounds,design.background)}</select></label><label>Accent<input id="cg-accent" type="color" value="${design.accent}"></label><label>Text<input id="cg-text" type="color" value="${design.text}"></label><label>Secondary text<input id="cg-muted" type="color" value="${design.muted}"></label></div></fieldset>
    <fieldset><legend>Typography</legend><div class="cg-control-grid"><label>Headline font<select id="cg-display-font">${cgOptions(cat.display_fonts,design.display_font)}</select></label><label>Body font<select id="cg-body-font">${cgOptions(cat.body_fonts,design.body_font)}</select></label><label>Headline size <output id="cg-title-scale-out"></output><input id="cg-title-scale" type="range" min="0.75" max="1.35" step="0.05" value="${design.title_scale}"></label><label>Body size <output id="cg-body-scale-out"></output><input id="cg-body-scale" type="range" min="0.75" max="1.30" step="0.05" value="${design.body_scale}"></label></div></fieldset>
    <div class="cg-actions"><button type="button" class="button secondary" onclick="cgReset()">Reset design</button><button type="button" class="button primary" id="cg-save" onclick="cgSave()">Save design</button></div>
   </section>
  </div>`;
 cgUpdatePreview();
}

function cgRead(){return {approved:false,automatic_placement:false,design:{
 motion:$('#cg-motion').value,background:$('#cg-background').value,
 accent:$('#cg-accent').value,text:$('#cg-text').value,muted:$('#cg-muted').value,
 display_font:$('#cg-display-font').value,body_font:$('#cg-body-font').value,
 title_scale:Number($('#cg-title-scale').value),body_scale:Number($('#cg-body-scale').value),
 speed:Number($('#cg-speed').value),background_motion:Number($('#cg-bg-motion').value),
 },preview:{title:$('#cg-title').value.trim(),subtitle:$('#cg-subtitle').value.trim()}}}

function cgUpdatePreview(){
 const settings=cgRead(),d=settings.design,stage=$('#cg-stage'),title=settings.preview.title||P.title||'',subtitle=settings.preview.subtitle;
 const fonts={bahnschrift:'Storyroom Bahnschrift, Bahnschrift, sans-serif',inter:'Storyroom Inter, Inter, sans-serif',montserrat:'Storyroom Montserrat, Montserrat, sans-serif',poppins:'Storyroom Poppins, Poppins, sans-serif',lora:'Storyroom Lora, Lora, serif'};
 stage.dataset.background=d.background;stage.dataset.motion=d.motion;
 stage.style.setProperty('--cg-accent',d.accent);stage.style.setProperty('--cg-text',d.text);stage.style.setProperty('--cg-muted',d.muted);
 stage.style.setProperty('--cg-display-font',fonts[d.display_font]);stage.style.setProperty('--cg-body-font',fonts[d.body_font]);
 stage.style.setProperty('--cg-title-scale',d.title_scale);stage.style.setProperty('--cg-body-scale',d.body_scale);
 stage.style.setProperty('--cg-duration',(0.68/d.speed).toFixed(3)+'s');stage.style.setProperty('--cg-bg-shift',(d.background_motion*1.6).toFixed(2)+'%');
 $('#cg-preview-title').textContent=title;$('#cg-preview-subtitle').textContent=subtitle;$('#cg-preview-subtitle').hidden=!subtitle;
 $('#cg-preview-items').innerHTML=cgPreviewItems().map((item,index)=>`<div class="cg-preview-item" style="--cg-order:${index}"><b>${cgClock(item.start)}</b><span>${E(item.text)}</span></div>`).join('');
 $('#cg-speed-out').textContent=d.speed.toFixed(2)+'×';$('#cg-bg-motion-out').textContent=d.background_motion.toFixed(2)+'×';
 $('#cg-title-scale-out').textContent=Math.round(d.title_scale*100)+'%';$('#cg-body-scale-out').textContent=Math.round(d.body_scale*100)+'%';
 const contrast=cgContrast(d.text,cgBackgroundRGB(d.background));$('#cg-readability').textContent=contrast>=7?'Strong text contrast':contrast>=4.5?'Readable text contrast':'Increase text contrast';$('#cg-readability').classList.toggle('warn',contrast<4.5);
 cgReplay();
}
function cgBackgroundRGB(name){return {charcoal:[16,17,20],midnight:[9,17,31],warm:[31,20,17],neutral:[23,23,24],transparent:[16,17,20]}[name]}
function cgContrast(hex,bg){const rgb=[1,3,5].map(i=>parseInt(hex.slice(i,i+2),16)),lum=v=>{v/=255;return v<=.03928?v/12.92:Math.pow((v+.055)/1.055,2.4)},L=a=>.2126*lum(a[0])+.7152*lum(a[1])+.0722*lum(a[2]);const x=L(rgb),y=L(bg);return (Math.max(x,y)+.05)/(Math.min(x,y)+.05)}
function cgReplay(){const stage=$('#cg-stage');if(!stage)return;stage.classList.remove('cg-play');void stage.offsetWidth;stage.classList.add('cg-play')}

function cgReset(){
 cinematicGraphicsState.settings={approved:false,automatic_placement:false,design:{motion:'adaptive',background:'charcoal',accent:'#DC656C',text:'#F1F1EF',muted:'#C0C3C9',display_font:'bahnschrift',body_font:'inter',title_scale:1,body_scale:1,speed:1,background_motion:1},preview:{title:'',subtitle:''}};cgRenderEditor();
}
async function cgSave(){const button=$('#cg-save');button.disabled=true;button.textContent='Saving…';try{const result=await api(`/api/projects/${P.id}/cinematic-graphics`,'PATCH',cgRead());cinematicGraphicsState.settings=result.settings;P=result.project;button.textContent='Saved';toast('Cinematic graphics design saved to this project. Automatic placement remains off.');setTimeout(()=>{if(button.isConnected){button.disabled=false;button.textContent='Save design'}},900)}catch(error){button.disabled=false;button.textContent='Save design';toast(error.message)}}
