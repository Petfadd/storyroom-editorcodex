/* v22 Storyroom home page.
   The first thing you see: Create project (the same New production setup as before) and
   your recent videos. The editor header's back arrow and Home button both
   come back here. Nothing on this page edits a project except Rename and Delete. */
let homeSort='updated',homeQuery='',homeShowAll=false,homeHealthAt=0;
const HOME_RECENT=10;

function homeVisible(){const h=document.getElementById('home-page');return !!h&&!h.hidden}
function showHomePage(){
 const h=document.getElementById('home-page');if(!h)return;
 h.hidden=false;document.body.classList.add('at-home');
 renderHome();refreshHomeHealth();
 list().catch(e=>toast(e.message));
}
function hideHomePage(){
 const h=document.getElementById('home-page');if(!h)return;
 h.hidden=true;document.body.classList.remove('at-home');closeHomeMenu();
}
function goHome(){
 if(homeVisible())return;
 if(!leave())return;
 pauseEditor();closeTools();
 history.replaceState(null,'','#/home');
 showHomePage();
}
function openProjects(){goHome()}
showHome=goHome;

function homeLength(s){
 s=Math.floor(Number(s)||0);if(!s)return '';
 const h=Math.floor(s/3600),m=Math.floor(s%3600/60),r=String(s%60).padStart(2,'0');
 return h?`${h}:${String(m).padStart(2,'0')}:${r}`:`${m}:${r}`;
}
function homeAgo(ts){
 const d=Math.max(0,Date.now()/1000-(Number(ts)||0));
 if(d<60)return 'just now';
 if(d<3600)return `${Math.floor(d/60)} min ago`;
 if(d<86400){const h=Math.floor(d/3600);return `${h} h ago`}
 const days=Math.floor(d/86400);
 if(days===1)return 'yesterday';
 if(days<7)return `${days} days ago`;
 if(days<30){const w=Math.floor(days/7);return w===1?'1 week ago':`${w} weeks ago`}
 const mo=Math.floor(days/30);return mo<=1?'1 month ago':`${mo} months ago`;
}
function homeShown(){
 const q=homeQuery.trim().toLowerCase();
 let rows=(projects||[]).filter(p=>!q||String(p.title||'').toLowerCase().includes(q));
 if(homeSort==='title')rows=rows.slice().sort((a,b)=>String(a.title).localeCompare(String(b.title),undefined,{sensitivity:'base'}));
 else if(homeSort==='length')rows=rows.slice().sort((a,b)=>(b.length_s||0)-(a.length_s||0));
 else rows=rows.slice().sort((a,b)=>(b.updated||0)-(a.updated||0));
 return rows;
}
const HOME_CHIPS={exported:'<span class="home-chip is-exported">✓ Exported</span>',editing:'<span class="home-chip is-editing">● Editing</span>',setup:'<span class="home-chip is-setup">Needs setup</span>'};
function homeCardHTML(p){
 const portrait=p.format==='portrait',len=homeLength(p.length_s),cover=p.cover_url?E(p.cover_url):'';
 const picture=cover
  ?`<div class="home-blur" style="background-image:url('${cover}')"></div><img class="home-cover ${portrait?'is-portrait':''}" src="${cover}" alt="" loading="lazy" onerror="this.parentNode.classList.add('no-cover')">`
  :`<div class="home-empty">No footage yet<br>Add script, SRT &amp; narration</div>`;
 const when=(p.status==='setup'?'Created ':'Edited ')+homeAgo(p.updated);
 return `<article class="home-card" data-id="${E(p.id)}"><button type="button" class="home-thumb" onclick="homeOpen('${E(p.id)}')" aria-label="Open ${E(p.title)}">${picture}${HOME_CHIPS[p.status]||''}${len?`<span class="home-len">${len}</span>`:''}<span class="home-open">Open project</span></button>`+
  `<button type="button" class="home-more" aria-label="More for ${E(p.title)}" aria-haspopup="menu" onclick="openHomeMenu(event,'${E(p.id)}')">⋯</button>`+
  `<div class="home-meta"><strong title="${E(p.title)}">${E(p.title)}</strong><span>${portrait?'9:16':'16:9'} · ${when}</span></div></article>`;
}
function renderHome(){
 const grid=document.getElementById('home-grid');if(!grid)return;
 const all=homeShown(),rows=homeShowAll||homeQuery.trim()?all:all.slice(0,HOME_RECENT);
 const total=(projects||[]).length;
 document.getElementById('home-heading').textContent=homeShowAll?'All projects':'Recent videos';
 document.getElementById('home-count').textContent=total===1?'1 project':`${total} projects`;
 document.querySelectorAll('[data-home-nav]').forEach(b=>b.classList.toggle('is-on',(b.dataset.homeNav==='all')===homeShowAll));
 const more=document.getElementById('home-more-all');
 if(more){more.hidden=homeShowAll||!!homeQuery.trim()||all.length<=HOME_RECENT;more.textContent=`Show all ${all.length} projects`}
 const html=rows.map(homeCardHTML).join('')||(total?'<p class="home-none">No project matches that search.</p>':'<p class="home-none">No projects yet. Click <b>Create project</b> to start your first film.</p>');
 if(grid.dataset.html!==html){grid.innerHTML=html;grid.dataset.html=html}
}
function setHomeView(all){homeShowAll=!!all;renderHome();document.getElementById('home-main')?.scrollTo?.({top:0})}
function setHomeSort(v){homeSort=v;renderHome()}
function setHomeQuery(v){homeQuery=String(v||'');renderHome()}
async function homeOpen(id){
 closeHomeMenu();
 try{await openProject(id)}catch(e){toast(e.message);return}
 if(P?.id===id)hideHomePage();
}
function homeCreate(){closeHomeMenu();newProduction()}

/* ⋯ menu: Open · Rename · Open export folder · Delete */
function closeHomeMenu(){document.getElementById('home-menu')?.remove()}
function openHomeMenu(e,id){
 e.stopPropagation();
 const had=document.getElementById('home-menu')?.dataset.id===id;closeHomeMenu();if(had)return;
 const p=(projects||[]).find(x=>x.id===id);if(!p)return;
 const card=e.currentTarget.closest('.home-card');
 const m=document.createElement('div');m.id='home-menu';m.className='home-menu';m.dataset.id=id;m.setAttribute('role','menu');
 m.innerHTML=`<button type="button" role="menuitem" onclick="homeOpen('${E(id)}')">Open</button>`+
  `<button type="button" role="menuitem" onclick="homeRename('${E(id)}')">Rename</button>`+
  `<button type="button" role="menuitem" onclick="homeExportFolder('${E(id)}')" ${p.has_export?'':'disabled title="No export yet"'}>Open export folder</button>`+
  `<button type="button" role="menuitem" class="is-danger" onclick="homeDelete('${E(id)}')">Delete…</button>`;
 card.appendChild(m);m.querySelector('button')?.focus();
}
async function homeRename(id){
 closeHomeMenu();const p=(projects||[]).find(x=>x.id===id);if(!p)return;
 const name=prompt('Rename project',p.title);if(name===null)return;
 const title=name.trim();if(!title){toast('A project name is required.');return}
 if(title===p.title)return;
 try{
  await api('/api/projects/'+id,'PATCH',{title});
  if(P?.id===id){P.title=title;const el=document.getElementById('project-name');if(el)el.textContent=title}
  await list();toast('Project renamed.');
 }catch(e){toast(e.message)}
}
async function homeExportFolder(id){
 closeHomeMenu();
 try{const d=await api(`/api/projects/${id}/open-export-folder`,'POST',{});if(!d.opened)toast('Exports are in: '+d.path)}
 catch(e){toast(e.message)}
}
async function homeDelete(id){closeHomeMenu();await deleteProduction(id);if(homeVisible())renderHome()}

/* Small status box: is this computer ready to edit and render? */
async function refreshHomeHealth(){
 const box=document.getElementById('home-health');if(!box)return;
 if(Date.now()-homeHealthAt<15000&&box.dataset.ready)return;
 try{
  const r=await fetch('/api/media-tools');const all=await r.json();const d=all.tools||all;homeHealthAt=Date.now();
  const py=d.python?.version||'',ff=!!d.ffmpeg?.ready,fw=!!d['faster-whisper']?.ready;
  const [maj,min]=py.split('.').map(Number),tooNew=maj===3&&min>=15;
  const item=(ok,label)=>`<span class="${ok?'ok':'warn'}">${E(label)} ${ok?'✓':'✕'}</span>`;
  const head=ff?'<b class="ok">● Ready to edit</b>':'<b class="warn">● FFmpeg missing</b>';
  const note=!fw&&tooNew?`<small>Python ${E(py)} is too new for speech recognition. Rebuild the editor with Python 3.12.</small>`:'';
  box.innerHTML=`${head}${item(ff,'FFmpeg')}${item(!tooNew,'Python '+py)}${item(fw,'Speech recognition')}${note}`;
  box.dataset.ready='1';
 }catch{box.innerHTML='<b class="warn">● Status unavailable</b>'}
}

(function(){
 const before=list;
 list=async function(){const d=await before();if(homeVisible())renderHome();return d};
 document.addEventListener('click',e=>{if(!e.target.closest?.('#home-menu,.home-more'))closeHomeMenu()});
 document.addEventListener('keydown',e=>{if(e.key==='Escape'&&document.getElementById('home-menu')){closeHomeMenu();e.stopPropagation()}});
 if(homeVisible())document.body.classList.add('at-home');
})();
