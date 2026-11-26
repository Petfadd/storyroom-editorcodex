// People on screen: a photo appears over the playing picture when the narration names
// someone. Timing comes from the SRT; the same image is used by the monitor and the export.

function personOverlayData(){return P?.person_overlays||{windows:[],people:[],notes:[],settings:{},moments:{}}}
function personMs(ms){const s=Math.max(0,ms/1000),m=Math.floor(s/60);return `${m}:${String(Math.floor(s-m*60)).padStart(2,'0')}`}
// Build long SRT-match lists only when their person is expanded; never build
// thousands of checkbox nodes on initial Setup paint or after a photo upload.
const personMomentData=new Map();
function mountPersonMoments(details,id){
 if(!details.open)return;
 const list=details.querySelector('ul');if(!list||list.dataset.ready)return;
 const item=personMomentData.get(id);if(!item)return;
 const {person,mentions}=item;
 const highlight=(text,said)=>{const i=String(text).toLowerCase().indexOf(String(said).toLowerCase());return i<0?E(text):E(text.slice(0,i))+'<mark>'+E(text.slice(i,i+said.length))+'</mark>'+E(text.slice(i+said.length))};
 list.innerHTML=mentions.map(m=>{
  const off=m.blocked==='turned off for this line',other=m.blocked&&!off;
  return `<li class="${m.blocked?'person-moment-off':''}">
   <label class="check"><input type="checkbox" ${m.blocked?'':'checked'} ${other?'disabled':''} onchange="togglePersonLine('${person.id}',${m.cue},this.checked)"></label>
   <span class="small">line ${m.cue} · ${personMs(m.ms)}</span> “${highlight(m.text,m.said)}”
   ${m.blocked?'':m.footage?'<span class="person-flag warn">scripted footage has priority — photo not shown</span>':'<span class="person-flag">photo candidate</span>'}
   ${m.via?`<span class="person-flag">about ${E(m.via)}'s ${E(person.role||'relative').toLowerCase()}</span>`:''}
   ${m.short&&!m.blocked?'<span class="person-flag warn">first name or surname only: check it is them</span>':''}
   ${other?`<span class="person-flag">${E(m.blocked)}</span>`:''}</li>`}).join('');
 list.dataset.ready='1';
}
const PERSON_ROLES=['Survivor','Family member','Relative','Victim','Suspect','Mother','Father','Brother','Sister','Grandmother','Grandfather','Boyfriend','Girlfriend','Wife','Husband','Son','Daughter','Aunt','Uncle','Cousin','Witness','Detective','Lawyer'];

// People on screen. A person's photo is shown whenever the narration says their name.
// Add people here (or with P-rows in the footage sheet). Every line that names them is
// listed under them, so the right person can be checked line by line before export.
function peopleCardHTML(){
 if(P?.edit_mode!=='documentary')return '';
 personMomentData.clear();
 const data=personOverlayData(),conf=data.settings||{},allPeople=P.people||[],moments=data.moments||{};
 const featuredIds=new Set((data.people||[]).map(p=>p.id));
 const people=allPeople.filter(p=>featuredIds.has(p.id));
 const supporting=allPeople.filter(p=>!featuredIds.has(p.id));
 const info=Object.fromEntries((data.people||[]).map(x=>[x.id,x]));
 const opt=(value,label,current)=>`<option value="${value}"${value===current?' selected':''}>${label}</option>`;
 const mark=(text,said)=>{const i=text.toLowerCase().indexOf(String(said).toLowerCase());return i<0?E(text):E(text.slice(0,i))+'<mark>'+E(text.slice(i,i+said.length))+'</mark>'+E(text.slice(i+said.length))};
 const rows=people.map(person=>{
  const i=info[person.id]||{},gallery=(Array.isArray(person.photos)&&person.photos.length?person.photos:[person.photo].filter(Boolean)).slice(0,5),photo=!!(gallery.length&&i.has_photo),list=moments[person.id]||[];
  const shown=Number(i.windows||0),check=list.filter(m=>m.short&&!m.blocked).length;
  const same=(i.same_photo_as||[]);
  const status=!photo?'<span class="person-status warn">No photo</span>':(conf.enabled!==true||person.show!==true)?'<span class="person-status">Off · approval needed</span>':shown?`<span class="person-status ready">${shown} photo placement${shown===1?'':'s'} planned</span>`:'<span class="person-status warn">0 photo placements · check video priority</span>';
  const sameNote=photo&&same.length?`<p class="person-flag warn">Same photo as ${E(same.join(', '))}: this is a group picture, not ${E(person.name)}'s own. Replace it with their own photo, or untick Show photo.</p>`:'';
  personMomentData.set(person.id,{person,mentions:list});
  const thumbnails=gallery.map((pic,index)=>`<div class="person-gallery-entry">
   <img loading="lazy" src="/api/projects/${P.id}/people/${person.id}/photo?index=${index}&v=${encodeURIComponent(pic.uploaded||'')}" alt="${E(person.name)} photo ${index+1}">
   <span>${index+1} / ${gallery.length}</span>
   <button type="button" title="Cut away news panels, logos or black bars" onclick="openPhotoCrop({person:'${person.id}',index:${index}})">Adjust crop</button>
   <button type="button" title="Remove this photo only" onclick="removePersonPhoto('${person.id}',${index})">Remove</button>
  </div>`).join('');
  return `<div class="person-row" data-person-id="${person.id}">
   <div class="person-thumb">${photo?`<img loading="lazy" src="/api/projects/${P.id}/people/${person.id}/photo?index=0&v=${encodeURIComponent(gallery[0].uploaded||'')}" alt="">`:'<span>No photo</span>'}</div>
   <form class="person-form" onsubmit="savePerson(event,'${person.id}')">
    <div class="person-head"><strong>${E(person.name)}</strong>${person.role?` <span class="small">${E(person.role)}</span>`:''} ${status}<label class="check person-quick-toggle"><input type="checkbox" ${person.show===true?'checked':''} onchange="quickPersonToggle('${person.id}',this.checked)"> Show</label></div>
    ${sameNote}
    <div class="person-gallery-bar">
     <strong>${gallery.length} of 5 photos</strong>
     <label class="file-button ${gallery.length>=5?'is-disabled':''}">＋ Add photo
       <input type="file" accept="image/*,.heic,.heif,.avif" ${gallery.length>=5?'disabled':''} onchange="addPersonPhoto(this,'${person.id}')">
     </label>
     <label class="file-button">${photo?'Replace first photo':'Upload first photo'}
       <input type="file" name="photo" accept="image/*,.heic,.heif,.avif" onchange="savePersonForm(this.form,'${person.id}')">
     </label>
     ${gallery.length>1?'<span class="small">Auto rotate · no immediate repeat until all photos are used</span>':''}
    </div>
    ${gallery.length?`<details class="person-gallery-details"><summary>View / remove ${gallery.length} photos</summary><div class="person-gallery-strip">${thumbnails}</div></details>`:''}
    <details class="person-detail-options"><summary>Change primary photo, name or matching rules</summary>
   <div class="person-fields">
     <label>Name<input name="name" value="${E(person.name)}" required></label>
     <label>Role<input name="role" list="person-roles" value="${E(person.role||'')}" placeholder="Victim, Suspect, Mother…"></label>
     <label class="wide">Approved complete-name aliases <span class="small">(comma separated; enter only verified spellings)</span><input name="aliases" value="${E((person.aliases||[]).join(', '))}"></label>
     ${(person.suggested_aliases||[]).length?`<p class="small wide">SRT spelling suggestions (review before copying into aliases): ${E((person.suggested_aliases||[]).join(', '))}</p>`:''}
     <label class="wide">Not this person <span class="small">(phrases to ignore, e.g. Harris County)</span><input name="exclude" value="${E((person.exclude||[]).join(', '))}"></label>
    </div>
    <div class="inline">
     <label class="check"><input type="checkbox" name="show" ${person.show===true?'checked':''} onchange="savePersonForm(this.form,'${person.id}')"> Show photo</label>
     <label class="check" title="Optional override for this person; core-case people get narration priority automatically when Automatic is on."><input type="checkbox" name="photo_over_video" ${person.photo_over_video===true?'checked':''} onchange="savePersonForm(this.form,'${person.id}')"> Always prefer this approved photo in narration (optional)</label>
     <label class="check"><input type="checkbox" name="short_names" ${(person.short_names===true)?'checked':''} onchange="savePersonForm(this.form,'${person.id}')"> Allow short-name/one-word aliases (manual opt-in)</label>
     <button type="submit">Save</button>
     <button type="button" onclick="findPersonSpellings('${person.id}')">Find SRT spellings</button>
     ${photo?`<button type="button" onclick="previewPersonCard('${person.id}')">Preview portrait</button>`:''}
     <button type="button" onclick="removePerson('${person.id}')">Remove</button>
    </div>
   </details>
    ${list.length?`<details class="person-moments" ontoggle="mountPersonMoments(this,'${person.id}')"><summary>${list.length} line${list.length===1?'':'s'} name ${E(person.name)}${check?` · <span class="warn">${check} to check</span>`:''} — untick a line to keep the photo off it</summary><ul></ul></details>`:'<p class="small">The narration never names them yet. Check the spelling against your SRT.</p>'}
   </form></div>`}).join('');
 const notes=(data.notes||[]).map(n=>`<li>${E(n)}</li>`).join('');
 // Every planned photo: who, which subtitle lines, and the film-master IN/OUT.
 const report=(data.window_report||[]);
 const windowList=report.length?`<details class="photo-window-list"><summary>${report.length} photo window${report.length===1?'':'s'} on the film — person, lines, IN → OUT</summary><table class="photo-window-table"><thead><tr><th>Person</th><th>Lines</th><th>IN</th><th>OUT</th><th>Name</th></tr></thead><tbody>${report.map(r=>`<tr><td>${E(r.name)}</td><td>${E(r.cues.length>1?r.cues[0]+'–'+r.cues.at(-1):String(r.cues[0]))}</td><td>${E(r.in)}</td><td>${E(r.out)}</td><td>${r.name_shown?'shown':''}</td></tr>`).join('')}</tbody></table></details>`:'';
 const total=(data.windows||[]).length;
 return `<section class="card setup-card setup-footage people-card"><div class="setup-card-heading"><span class="setup-step">07</span><h3>Featured case people · photographs</h3><span class="setup-status ${total?'ready':''}">${total} photo${total===1?'':'s'} on screen</span></div>
  <p>Upload or select a case photo, assign its verified subject and role, and switch on automatic photo storytelling once. Victims and suspects receive priority; long interviews and protected minors remain protected. No changes to picture/audio source timing.</p>
  <p class="small">Portraits are OFF by default for source-only documentaries. Enable both the project overlay and an individual verified person before any automatic photo appears. Cinematic person introductions show only the verified name at the first approved photo appearance; no role or allegation is added. You confirm who is in each photo and that you may use it. The editor does not check identity, source or publication rights.</p>
  <div class="smart-photo-director">
   <label class="check"><input type="checkbox" ${conf.smart_photo_mode===true?'checked':''}
     onchange="toggleSmartPhotoStory(this.checked)">
     <strong>Automatic photo storytelling</strong> · recommended</label>
   <p class="small">Every still visual gets restrained professional movement: uploaded photographs, approved P## photo-carrier clips, and verified static-image intervals inside source clips. Moves vary without resetting at subtitle boundaries. Approved photos appear in narration only; never across genuine interview audio. Source media and interview audio remain unchanged.</p>
  </div>
  ${personAssetPickerHTML()}
  <details class="smart-photo-advanced"><summary>Still & photo motion director</summary>
  <div class="inline person-settings">
   <label class="check"><input type="checkbox" ${conf.enabled===true?'checked':''} onchange="savePersonSettings({enabled:this.checked})"> Show photos in preview and export</label>
   <label>Show photo<select onchange="savePersonSettings({style:this.value})">${opt('full','Full screen',conf.style)}${opt('card','Corner card',conf.style)}</select></label>
   <label>For<select onchange="savePersonSettings({timing:this.value})">${opt('cue','The whole SRT line',conf.timing)}${opt('fixed','A fixed time',conf.timing)}</select></label>
   ${conf.timing==='fixed'?`<label>Stays up<select onchange="savePersonSettings({hold_ms:Number(this.value)})">${[2500,3500,5000,7000].map(v=>opt(v,(v/1000)+' s',conf.hold_ms)).join('')}</select></label>`:''}
   <label>Motion style<select onchange="savePersonSettings({photo_style:this.value})">${opt('moves','Professional reveals, pushes & holds',conf.photo_style||'moves')}</select></label>
   <p class="small">Names show at each person's <strong>first introduction only</strong>. Photos are always centred, with news panels and logos cut away.</p>
   <label class="check"><input type="checkbox" ${conf.pair_photos!==false?'checked':''} onchange="savePersonSettings({pair_photos:this.checked})"> Two people named in one line: show them side by side</label>
   ${(conf.photo_style||'moves')==='moves'?`<label>Motion direction<select onchange="savePersonSettings({photo_motion:this.value})">${opt('auto_story','Automatic edited variety (recommended)',conf.photo_motion||'auto_story')}${opt('portrait_reveal','Portrait reveal · close, wide, emphasis',conf.photo_motion)}${opt('push_left','Diagonal push left, then hold',conf.photo_motion)}${opt('push_right','Diagonal push right, then hold',conf.photo_motion)}${opt('reveal_left','Reveal left, then hold',conf.photo_motion)}${opt('reveal_right','Reveal right, then hold',conf.photo_motion)}${opt('zoom_in','Clean push in, then hold',conf.photo_motion)}${opt('zoom_out','Clean pull back, then hold',conf.photo_motion)}${opt('drift_up_right','Short diagonal rise, then hold',conf.photo_motion)}${opt('drift_down_left','Short diagonal drop, then hold',conf.photo_motion)}</select></label>
   <label>Motion energy<select onchange="savePersonSettings({photo_motion_intensity:this.value})">${opt('subtle','Controlled · settles in about 3 seconds',conf.photo_motion_intensity||'medium')}${opt('medium','Standard · settles in about 2.25 seconds (recommended)',conf.photo_motion_intensity||'medium')}${opt('strong','Bold · settles in about 1.6 seconds',conf.photo_motion_intensity)}</select></label>
   <p class="small">These two controls apply immediately to featured-photo overlays, uploaded stills, P## photo-carrier clips and verified static-image intervals. The move finishes, then holds a composed frame—no endless slow dragging.</p>`:''}
   <label class="check"><input type="checkbox" ${conf.cinematic_name_intro!==false?'checked':''} onchange="savePersonSettings({cinematic_name_intro:this.checked})"> Cinematic name introduction (first appearance only)</label>
   ${P.visual_plan_applied?`<label class="check"><input type="checkbox" ${conf.with_visual_plan?'checked':''} onchange="savePersonSettings({with_visual_plan:this.checked})"> Also show name cards with the visual plan</label>`:''}
  </div>
  </details>
  ${windowList}
  ${notes?`<details><summary>Notes (${(data.notes||[]).length}) — skipped or delayed mentions</summary><ul class="issues">${notes}</ul></details>`:''}
  ${rows||'<p class="muted">No featured portrait subjects yet. Video speakers remain available in Footage.</p>'}
  ${supporting.length?`<details><summary>Supporting people · clips only (${supporting.length})</summary><p class="small">These people remain available through their authentic video clips; they do not receive automatic portrait overlays. Existing photos have not been deleted.</p><p class="small">${supporting.map(p=>E(p.name)).join(' · ')}</p></details>`:''}
  <datalist id="person-roles">${PERSON_ROLES.map(r=>`<option value="${r}">`).join('')}</datalist>
  <form class="person-row person-add" onsubmit="addPerson(event)">
   <div class="person-fields">
    <label>Name as the narration says it<input name="name" required placeholder="Full name"></label>
    <label>Role<input name="role" list="person-roles" placeholder="Victim, Suspect, Mother…"></label>
    <label class="wide">Photo <span class="small">(any photo file)</span><input type="file" name="photo" accept="image/*,.heic,.heif,.avif"></label>
   </div>
   <div class="inline"><button class="new" type="submit">＋ Add person</button></div>
  </form>
 </section>`;
}

let featuredAssetPick='';
function personAssetPickerHTML(){
 const photos=(P.assets||[]).filter(a=>a.kind==='image'&&!a.derived_from);
 if(!photos.length)return `<p class="small">No imported photos yet. Upload photos in Case footage & photos above, then assign them here.</p>`;
 const known=(P.people||[]).filter(p=>p.id);
 return `<form id="person-media-assign" class="person-media-assign" onsubmit="assignProjectPhoto(event)">
  <strong>Use a photo already in your project</strong>
  <div class="person-media-controls">
   <label>Photo<select name="asset_id" required>${photos.map(a=>`<option value="${E(a.id)}" ${featuredAssetPick===a.id?'selected':''}>${E(a.original_name||a.name)}</option>`).join('')}</select></label>
   <label>Person<select name="person_id" onchange="personAssignMode(this.form)"><option value="">＋ New person</option>${known.map(p=>`<option value="${E(p.id)}">${E(p.name)} · ${E(p.role||'Unclassified')}</option>`).join('')}</select></label>
   <label class="person-new-field">Full verified name<input name="name" placeholder="Full name from narration"></label>
   <label class="person-new-field">Role<select name="role"><option value="Victim">Victim</option><option value="Suspect">Suspect</option><option value="Mother">Mother</option><option value="Father">Father</option><option value="Grandmother">Grandmother</option><option value="Family member">Family member</option><option value="Witness">Witness</option><option value="Other">Other (no automatic photo)</option></select></label>
  </div>
  <label class="check"><input type="checkbox" name="identity_confirmed" required> I verified the person shown and have reviewed whether this photo may be used.</label>
  <button class="new" type="submit">Assign photo to person</button>
  <p class="small">Photos stay in the media library too. Assigning a picture does not automatically establish identity, rights, or permission to publish. Never assign protected children automatically.</p>
 </form>`;
}
function personAssignMode(form){
 const existing=!!form.elements.person_id.value;
 form.querySelectorAll('.person-new-field').forEach(el=>el.hidden=existing);
}
function openFeaturedPhotoPicker(assetId){
 featuredAssetPick=assetId;
 changeTab('brief');
 const root=document.querySelector('#person-media-assign');
 if(!root){toast('Open Setup to assign a photo.');return}
 root.elements.asset_id.value=assetId;
 root.scrollIntoView({block:'center',behavior:'smooth'});
 root.classList.add('photo-assign-highlight');setTimeout(()=>root.classList.remove('photo-assign-highlight'),1700);
}
async function assignProjectPhoto(event){
 event.preventDefault();const form=event.currentTarget;
 featuredAssetPick=form.elements.asset_id.value;
 const id=form.elements.person_id.value,person=(P.people||[]).find(p=>p.id===id);
 const name=person?person.name:form.elements.name.value.trim();
 if(!name){toast('Enter a verified person name.');return}
 if(!form.elements.identity_confirmed.checked){toast('Confirm the photo’s identity and publication review.');return}
 const fd=new FormData();
 if(id)fd.set('id',id);
 fd.set('name',name);fd.set('asset_id',form.elements.asset_id.value);
 fd.set('identity_confirmed','1');
 if(!person)fd.set('role',form.elements.role.value);
 fd.set('show','1');
 if(person)fd.set('photo_action','add');
 if(person){fd.set('short_names',person.short_names?'1':'0');fd.set('photo_over_video',person.photo_over_video?'1':'0')}
 if(await personRequest(`/api/projects/${P.id}/people`,'POST',fd))toast('Photo assigned. Automatic narration placements are ready for review.');
}

function updatePeopleCardOnly(){
 // Updating a portrait or checkbox must not rebuild the timeline or repaint the
 // entire Setup dialog. Preserve open details and current scroll position.
 const old=document.querySelector('#manage-dialog .people-card');
 if(!old){return}
 const expanded=[...old.querySelectorAll('details[open]')].map(d=>({person:d.closest('[data-person-id]')?.dataset.personId||'',cls:d.className}));
 const target=document.querySelector('#content');const scroll=target?.scrollTop||0;
 const holder=document.createElement('div');holder.innerHTML=peopleCardHTML();
 const fresh=holder.firstElementChild;
 if(!fresh)return;
 old.replaceWith(fresh);
 for(const it of expanded){
  const scope=it.person?fresh.querySelector(`[data-person-id="${it.person}"]`):fresh;
  const detail=scope&&[...scope.querySelectorAll('details')].find(x=>x.className===it.cls);
  if(detail)detail.open=true;
 }
 if(target)target.scrollTop=scroll;
}
async function personRequest(url,method,body){
 try{
  const next=await api(url,method,body);
  if(!P||P.id!==next.id)return false;
  P=next;
  if(document.querySelector('#manage-dialog .people-card'))updatePeopleCardOnly();
  else if(typeof renderManagement==='function')renderManagement();
  if(typeof requestEditorTick==='function')requestEditorTick();
  return true;
 }catch(e){toast(e.message);return false}
}
async function addPersonPhoto(input,id){
 const file=input?.files?.[0];if(!file)return;
 const person=(P?.people||[]).find(p=>p.id===id);if(!person)return;
 const fd=new FormData();fd.set('id',id);fd.set('name',person.name);
 fd.set('photo_action','add');fd.set('photo',file);
 input.disabled=true;
 const ok=await personRequest(`/api/projects/${P.id}/people`,'POST',fd);
 if(ok)toast('Photo added. Storyroom rotates approved photos across planned appearances.');
 else input.disabled=false;
}
async function removePersonPhoto(id,index){
 if(!confirm('Remove this one photo from the person’s photo set?'))return;
 const ok=await personRequest(`/api/projects/${P.id}/people/${id}/photos/${index}`,'DELETE');
 if(ok)toast('Photo removed; remaining photos automatically rotate.');
}
function personFormData(form,id){
 const f=new FormData();if(id)f.append('id',id);
 for(const key of ['name','role','aliases','exclude']){const el=form.elements[key];if(el)f.append(key,el.value)}
 for(const key of ['show','short_names','photo_over_video']){const el=form.elements[key];if(el)f.append(key,el.checked?'1':'0')}
 const file=form.elements.photo?.files?.[0];if(file)f.append('photo',file);
 return f;
}
async function quickPersonToggle(id,on){
 const person=(P.people||[]).find(p=>p.id===id);if(!person)return;
 const fd=new FormData();fd.set('id',id);fd.set('name',person.name);fd.set('show',on?'1':'0');
 await personRequest(`/api/projects/${P.id}/people`,'POST',fd);
}
async function savePerson(event,id){event.preventDefault();if(await personRequest(`/api/projects/${P.id}/people`,'POST',personFormData(event.target,id)))toast('Saved.')}
function savePersonForm(form,id){return personRequest(`/api/projects/${P.id}/people`,'POST',personFormData(form,id))}
async function addPerson(event){event.preventDefault();const form=event.target;if(!form.elements.photo.files.length&&!confirm('Add this person without a photo? Nothing can show until you upload one.'))return;if(await personRequest(`/api/projects/${P.id}/people`,'POST',personFormData(form,'')))toast('Added. Their lines are listed under them.')}
async function removePerson(id){const person=(P.people||[]).find(x=>x.id===id);if(!confirm(`Remove ${person?.name||'this person'} and their photo from this production?`))return;await personRequest(`/api/projects/${P.id}/people/${id}`,'DELETE')}
async function toggleSmartPhotoStory(on){
 const alreadyEnabled=P?.person_overlays?.settings?.enabled===true;
 const ok=await personRequest(`/api/projects/${P.id}`,'PATCH',
   {person_overlay_settings:{smart_photo_mode:on,enabled:on||alreadyEnabled,style:'full',photo_style:'moves',photo_motion:'auto_story',photo_motion_intensity:'medium'}});
 if(!ok||!on)return;
 if(!P?.scenes?.length){toast('Automatic photo storytelling enabled. New Beat builds will animate uploaded photos, photo-carrier clips and verified static clip intervals.');return}
 try{
  // One click applies the existing cinematic transition engine as well as
  // photo movement. Manually chosen/locked cuts are preserved by the API.
  const result=await api(`/api/projects/${P.id}/documentary-transitions`,'POST',
    {action:'auto',style:'cinematic',duration:'standard'});
  P=result.project;
  if(typeof renderProject==='function')renderProject();
  toast('Photo motion applied to uploaded images and still imagery carried inside clips. Existing manual cuts are preserved.');
 }catch(e){toast('Photo motion enabled, but automatic cuts were not applied: '+e.message)}
}
function savePersonSettings(change){return personRequest(`/api/projects/${P.id}`,'PATCH',{person_overlay_settings:change})}
function previewPersonCard(id){window.open(`/api/projects/${P.id}/people/${id}/card.png?v=${Date.now()}`,'_blank')}
function togglePersonLine(id,cue,on){
 const person=(P.people||[]).find(x=>x.id===id);if(!person)return;
 const skip=new Set((person.skip_cues||[]).map(Number));if(on)skip.delete(cue);else skip.add(cue);
 const f=new FormData();f.append('id',id);f.append('name',person.name);f.append('skip_cues',[...skip].join(','));
 return personRequest(`/api/projects/${P.id}/people`,'POST',f);
}
function findPersonSpellings(id){
 const person=(P.people||[]).find(x=>x.id===id);if(!person)return;
 const f=new FormData();f.append('id',id);f.append('name',person.name);f.append('find_spellings','1');
 return personRequest(`/api/projects/${P.id}/people`,'POST',f).then(ok=>ok&&toast('SRT spelling suggestions found. Review and approve aliases manually.'));
}

function personOverlayAt(t){
 const data=personOverlayData();if(data.settings?.enabled===false)return null;
 const windows=data.windows||[],ms=t*1000;
 // Planning windows are on the film clock and ordered by start. A binary lookup
 // avoids rescanning hundreds of appearances at every animation frame.
 let low=0,high=windows.length;
 while(low<high){const mid=(low+high)>>1;
  if(windows[mid].start_ms<=ms)low=mid+1;else high=mid;
 }
 const active=windows[low-1];
 return active&&ms<active.end_ms?active:null;
}
function updatePersonOverlay(t){
 const frame=$('#monitor-frame');if(!frame)return;
 let node=$('#person-overlay');
 if(!node){node=document.createElement('img');node.id='person-overlay';node.alt='';node.className='person-overlay';
  const captions=$('#editor-captions');frame.insertBefore(node,captions||null)}
 const w=(window.docTimelineData?.status==='ready')?personOverlayAt(t):null,g=personOverlayData().geometry;
 const motion=w?.motion||{};
 const fadeFor=w&&personOverlayData().settings?.smart_photo_mode?Math.min(220,(w.end_ms-w.start_ms)/3):0;
 const op=w?personPhotoOpacity(w,t,fadeFor):1;
 const cam=w&&window.Cinematic?(w.camera!==undefined?w.camera:(personOverlayData().cameras||{})[w.person_id]):null;
 const layered=!!(w&&(cam||w.name_intro||w.partner_id||w.partner_name_intro));
 personMotionOverlay(frame,w,g,cam,t,op);
 // This runs on every frame: touch the page only when something actually changes,
 // or each frame repaints the monitor and the video stutters.
 if(!w||!g||layered){if(node.classList.contains('on'))node.classList.remove('on');return}
 const src=`/api/projects/${P.id}/people/${w.person_id}/card.png?index=${w.photo_index||0}&intro=${w.name_intro?1:0}&v=${encodeURIComponent(personOverlayData().updated||'')}`;
 if(node.dataset.src!==src){node.dataset.src=src;node.src=src}
 const fw=frame.clientWidth,fh=frame.clientHeight,aspect=g.aspect||16/9;
 const full=g.left===0&&g.top===0&&g.width===1&&g.height===1;
 const pw=full?fw:Math.min(fw,fh*aspect),ph=full?fh:pw/aspect;
 const ox=(fw-pw)/2,oy=(fh-ph)/2;
 const bounds=full?['0','0','100%','100%']:
  [ox+g.left*pw,oy+g.top*ph,g.width*pw,g.height*ph].map(value=>value.toFixed(1)+'px');
 const box=bounds.join('|');
 if(node._box!==box){
  node._box=box;
  const [left,top,width,height]=bounds;
  Object.assign(node.style,{left,top,width,height});
 }
 const slide=personPhotoSlide(w,t,g.left*pw,g.top*ph,g.width*pw,g.height*ph,pw,ph);
 if(node.style.transform!==slide)node.style.transform=slide;
 if(node.style.opacity!==String(op))node.style.opacity=String(op);if(!node.classList.contains('on'))node.classList.add('on');
}

// A moving full-screen photo: the photo layer is moved with the same camera arithmetic
// as the export (static/cinematic.js); the name label is a separate, still layer.
// Two people named in one line are shown side by side (v17); the server draws both.
function personPairQuery(w){
 return w?.partner_id?`&with=${encodeURIComponent(w.partner_id)}&with_index=${w.partner_index||0}&with_intro=${w.partner_name_intro?1:0}&pair_style=framed-v29`:'';
}
function personMotionOverlay(frame,w,g,cam,t,op=1){
 let box=$('#person-motion');
 const names=!!(w&&(w.name_intro||w.partner_name_intro));
 if(!w||!g||(!cam&&!names&&!w.partner_id)){if(box&&box.classList.contains('on'))box.classList.remove('on');return}
 if(!box){box=document.createElement('div');box.id='person-motion';box.className='person-motion';
  box.innerHTML='<img class="pm-photo" alt=""><img class="pm-label" alt="">';frame.insertBefore(box,$('#editor-captions')||null)}
 const v=encodeURIComponent(personOverlayData().updated||''),base=`/api/projects/${P.id}/people/${w.person_id}/card.png?index=${w.photo_index||0}&intro=${w.name_intro?1:0}${personPairQuery(w)}&v=${v}`;
 const photo=box.querySelector('.pm-photo'),label=box.querySelector('.pm-label');
 if(photo.dataset.src!==base+'&layer=photo'){photo.dataset.src=base+'&layer=photo';photo.src=photo.dataset.src;
  label.dataset.src=base+'&layer=label';label.src=label.dataset.src;label.onerror=()=>{label.style.display='none'};label.onload=()=>{label.style.display=''}}
 const pw=frame.clientWidth,ph=frame.clientHeight;
 const slide=personPhotoSlide(w,t,0,0,pw,ph,pw,ph);
 if(box.style.transform!==slide)box.style.transform=slide;
 const next=cam?Cinematic.camTransform(cam,Cinematic.slotProgress(w.start_ms,w.end_ms,t,30)):'none';
 if(photo.style.transform!==next)photo.style.transform=next;
 const elapsed=Math.max(0,t*1000-w.start_ms),remaining=Math.max(0,w.end_ms-t*1000);
 // The name stays for the whole photo window; it arrives and leaves with the photo.
 const labelAlpha=names?1:0;
 if(label.style.opacity!==String(labelAlpha))label.style.opacity=String(labelAlpha);
 if(box.style.opacity!==String(op))box.style.opacity=String(op);if(!box.classList.contains('on'))box.classList.add('on');
}

/* Photo entrances, matching person_overlays.render_filters / photo_motion.py:
   fade in, or slide in from off-picture and settle (ease-out cubic); fade out at the
   end unless the next photo takes over directly. */
function personPhotoOpacity(w,t,legacyFade){
 const m=w.motion||{},ms=t*1000,len=Math.max(1,w.end_ms-w.start_ms);
 let a=1;
 if(m.entrance==='fade'&&m.enter_ms)a=Math.min(a,(ms-w.start_ms)/Math.min(m.enter_ms,len/3));
 else if(!m.entrance&&legacyFade)a=Math.min(a,(ms-w.start_ms)/legacyFade);
 if(m.exit==='fade'&&m.exit_ms)a=Math.min(a,(w.end_ms-ms)/Math.min(m.exit_ms,len/4));
 else if(!m.exit&&legacyFade)a=Math.min(a,(w.end_ms-ms)/legacyFade);
 return Math.max(0,Math.min(1,a));
}
function personPhotoSlide(w,t,x,y,cw,ch,pw,ph){
 const m=w?.motion||{};if(!m.enter_ms||!['left','right','top','bottom'].includes(m.entrance))return 'none';
 const p=Math.max(0,Math.min(1,(t*1000-w.start_ms)/m.enter_ms));if(p>=1)return 'none';
 const rest=Math.pow(1-p,3);   // 1 - easeOutCubic
 const dx=m.entrance==='left'?-(x+cw):m.entrance==='right'?pw-x:0;
 const dy=m.entrance==='top'?-(y+ch):m.entrance==='bottom'?ph-y:0;
 return `translate3d(${(dx*rest).toFixed(1)}px,${(dy*rest).toFixed(1)}px,0)`;
}
