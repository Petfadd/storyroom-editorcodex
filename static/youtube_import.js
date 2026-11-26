// YouTube Footage Importer: upload a Markdown sheet of source IDs and YouTube links;
// each video downloads in the background and arrives as S01.mp4, S02.mp4 ...
// The card updates itself in place while downloads run, so the rest of Setup (and
// anything typed in it) is never re-rendered by the progress updates.

window.ytData=null;window.ytDataFor=null;window.ytTimer=null;window.ytWatching=null;window.ytBusy=false;

const YT_LABEL={waiting:'Waiting',downloading:'Downloading',retrying:'Retrying',completed:'Completed',failed:'Failed',exists:'Already in project',cancelled:'Stopped',interrupted:'Interrupted'};
function ytBytes(n){return n?readableBytes(n):''}

function youtubeCardHTML(){
 return `<section class="card setup-card setup-footage" id="youtube-card">${ytInnerHTML()}</section>`;
}
function ytInnerHTML(){
 const d=window.ytDataFor===P?.id?window.ytData:null;
 if(!d){ytRefresh();return '<div class="setup-card-heading"><span class="setup-step">06</span><h3>Footage &amp; Photo Importer</h3><span class="setup-status">Loading…</span></div>'}
 const s=d.state,sum=d.summary,tool=d.tool||{},inst=d.install||{};
 const opts=s?.options||{},running=d.running,job=s?.job||{};
 const toolLine=tool.available?`<span class="small">yt-dlp ${E(tool.version)} ready</span> <button type="button" onclick="ytInstall()" ${inst.status==='running'?'disabled':''}>${inst.status==='running'?'Updating…':'Update yt-dlp'}</button>`
  :`<span class="yt-warn">${E(tool.detail||'yt-dlp is not installed.')}</span> <button class="new" type="button" onclick="ytInstall()" ${inst.status==='running'?'disabled':''}>${inst.status==='running'?'Installing…':'Install yt-dlp'}</button>`;
 const installLog=inst.status==='running'||inst.status==='error'?`<pre class="yt-log">${E((inst.log||[]).join('\n'))}${inst.error?'\n'+E(inst.error):''}</pre>`:'';
 const sel=(name,values,current,label)=>`<label>${label}<select ${running?'disabled':''} onchange="ytOption('${name}',this.value)">${values.map(([v,t])=>`<option value="${v}"${String(v)===String(current)?' selected':''}>${t}</option>`).join('')}</select></label>`;
 const options=s?`<div class="inline yt-options">
   ${sel('quality',[['720','Up to 720p'],['1080','Up to 1080p'],['best','Best available']],opts.quality||'1080','Quality')}
   ${sel('concurrency',[[1,'1'],[2,'2'],[3,'3'],[4,'4']],opts.concurrency||4,'At a time')}
   ${sel('cookies_from_browser',(d.options?.browsers||['']).map(b=>[b,b?b[0].toUpperCase()+b.slice(1):'No sign-in']),opts.cookies_from_browser||'','Use sign-in from')}
   <label class="check"><input type="checkbox" ${opts.auto_start===false?'':'checked'} ${running?'disabled':''} onchange="ytOption('auto_start',this.checked)"> Start downloading as soon as a sheet is uploaded</label>
  </div>`:'';
 const head=`<div class="setup-card-heading"><span class="setup-step">06</span><h3>Footage &amp; Photo Importer</h3><span class="setup-status ${sum&&sum.total&&sum.done===sum.total?'ready':''}">${sum?`${sum.done}/${sum.total} files downloaded`:'No sheet'}</span></div>
  <p>Upload a Markdown (.md) sheet listing each source ID and its link (for example <code>| SRC-01 | … | https://youtu.be/… |</code>). Every video downloads into this production and is saved under its source: SRC-01 → <strong>S01.mp4</strong>, SRC-02 → <strong>S02.mp4</strong>, in sheet order. Titles are never used as filenames. Any link works: YouTube, other video sites, or a direct file.</p>
  <p><strong>Photos of people</strong> go in the same sheet, one row each, with the person's name and role: <code>| P01 | Jane Doe | Victim | https://… |</code>. A photo is saved as <strong>P01.jpg</strong> (or the filename you write), and kept in Photos. Only explicitly classified victims, survivors, suspects and relevant family members named in the production script or SRT are eligible for automatic featured-photo suggestions; supporting people remain authentic video clips. You can also upload people's photos directly in 07, and check every line that names them there. The link can be a photo, a news page with the photo, a Drive or Dropbox share, or a YouTube video (its thumbnail).</p>
  <p><strong>B-roll and base pictures</strong> (locations, streets, CCTV, houses, apartments, police cars, maps, backgrounds) go in the sheet too, with what they show: <code>| B01 | Apartment complex exterior | 0:43–0:52 | https://youtu.be/… |</code>. A video is saved as <strong>B01.mp4</strong> in Footage (only the window, when one is given); a picture as <strong>B02.jpg</strong> in Photos; a YouTube link with <code>&amp;t=</code> and an image filename gives that frame. <code>BASE-01</code> rows keep their name. If the production script names the file, it is used exactly there; otherwise it is kept in the media pool, ready to place.</p>
  <div class="inline">${toolLine}</div>${installLog}`;
 const upload=`<label><input id="yt-analyse-sheet" type="checkbox" ${(opts.analyse??d.options?.analyse_default)?"checked":""} ${running?"disabled":""}> Analyse newly downloaded videos from the next sheet</label><div class="inline yt-actions"><label class="file-button${running?' disabled':''}">${s?'Upload a new sheet':'Upload footage sheet (.md)'}<input type="file" accept=".md,.markdown,.txt" ${running?'disabled':''} onchange="ytUpload(this)"></label>
   ${running?`<button type="button" onclick="ytCancel()" ${job.status==='cancelling'?'disabled':''}>${job.status==='cancelling'?'Stopping…':'Stop downloads'}</button>`:''}
   ${!running&&s&&sum&&sum.waiting&&job.status==='ready'?`<button class="new" type="button" onclick="ytStart()">Download Footages</button>`:''}
   ${!running&&sum&&(sum.failed||sum.stopped)?`<button class="new" type="button" onclick="ytStart()">${sum.stopped?'Resume':'Retry failed'} (${sum.failed+sum.stopped})</button>`:''}
   ${!running&&sum&&sum.done?`<button type="button" onclick="ytContinue()">Continue to footage →</button>`:''}
   ${!running&&s?`<button type="button" onclick="ytClear()">Clear list</button>`:''}
  </div><p class="small">Storyroom preserves the original source link and filename. Media-use permissions remain the producer’s responsibility; no extra approval screen is required for importing.</p>`;
 if(!s)return head+upload;
 const issues=(s.issues||[]).filter(i=>i.kind!=='missing_link');
 const bar=sum.total?Math.round(100*sum.done/sum.total):0;
 const overall=`<div class="yt-overall"><div><strong>${sum.done}/${sum.total} files downloaded</strong>${sum.failed?` · <span class="yt-bad">${sum.failed} failed</span>`:''}${sum.existing?` · ${sum.existing} already in project`:''}${sum.invalid?` · <span class="yt-bad">${sum.invalid} not downloadable</span>`:''}${sum.active?` · ${sum.active} downloading`:''}${sum.waiting?` · ${sum.waiting} waiting`:''}</div><progress max="100" value="${bar}"></progress>${job.message?`<p class="small">${E(job.message)}</p>`:''}</div>`;
 const rows=s.rows.map(r=>{
  const status=r.valid?(YT_LABEL[r.status]||r.status):r.problem==='No link in the sheet.'?'No link':String(r.problem||'').startsWith('Duplicate')?'Duplicate':'Not a link';
  const phase=r.status==='downloading'&&r.phase==='merging'?' · merging':r.status==='downloading'&&r.phase==='checking'?' · checking':r.status==='downloading'&&r.phase==='copying'?' · copying':'';
  const pct=r.status==='completed'?100:r.progress!=null?r.progress:0;
  const size=r.status==='completed'?ytBytes(r.size):r.downloaded_bytes?`${ytBytes(r.downloaded_bytes)}${r.total_bytes?' / '+ytBytes(r.total_bytes):''}`:'';
  const action=!running&&r.status==='exists'?`<button type="button" onclick="ytReplace('${r.source_id}')">Replace</button>`:!running&&r.valid&&['failed','cancelled','interrupted'].includes(r.status)?`<button type="button" onclick="ytStart('${r.source_id}')">Retry</button>`:'';
  return `<tr class="yt-${r.status}${r.valid?'':' yt-invalid'}"><td><strong>${E(r.source_id)}</strong>${r.media==='photo'?`<br><span class="yt-person">Photo${r.person||r.role?' · '+E([r.person,r.role].filter(Boolean).join(', ')):r.description?' · '+E(r.description.slice(0,60)):''}</span>`:r.media==='broll'?`<br><span class="yt-person">B-roll${r.description?' · '+E(r.description.slice(0,60)):''}</span>`:''}</td><td class="yt-title">${r.title?E(r.title):r.url?`<a href="${E(r.url)}" target="_blank" rel="noopener">${E(r.url.replace('https://www.',''))}</a>`:'—'}</td>
   <td><span class="yt-state">${E(status)}${phase}</span></td><td class="yt-progress">${['downloading','retrying'].includes(r.status)||r.status==='completed'?`<progress max="100" value="${pct}"></progress> ${Math.round(pct)}%`:''}</td>
   <td>${size}</td><td><code>${E(r.filename)}</code></td><td class="yt-error">${r.error?E(r.error):r.note?`<span class="yt-note">${E(r.note)}</span>`:''} ${action}</td></tr>`}).join('');
 const c=d.script_check;
 const check=c?`<div class="notice ${c.missing.length||c.short.length?'warn':''} yt-check"><strong>Production script check</strong> · the script names ${c.script_files.length} video file${c.script_files.length===1?'':'s'}; ${c.ready.length} ${c.ready.length===1?'is':'are'} in the project and long enough.
   ${c.missing.length?`<br>Not in the sheet or the project: ${c.missing.map(E).join(', ')}. Add a row for each to the sheet.`:''}
   ${c.short.length?`<br>Too short for the script (the link may be a shorter version of the video):<ul class="issues">${c.short.map(x=>`<li>${E(x.filename)} is ${x.duration_s.toFixed(1)}s; the script uses it up to ${x.needs_s.toFixed(1)}s</li>`).join('')}</ul>`:''}
   ${c.unused.length?`<br><span class="small">In the sheet but not named in the script: ${c.unused.map(E).join(', ')}.</span>`:''}
   <br><span class="small">Videos are downloaded whole from 0:00, so the script's Source IN/OUT times refer to the file as it is.</span></div>`:'';
 return head+options+upload+overall+check+(issues.length?`<details${sum.done?'':' open'}><summary>Sheet notes (${issues.length})</summary><ul class="issues">${issues.map(i=>`<li>${E(i.text)}</li>`).join('')}</ul></details>`:'')+
  `<div class="yt-table-wrap"><table class="yt-table"><thead><tr><th>Source</th><th>Title</th><th>Status</th><th>Progress</th><th>Size</th><th>Saved as</th><th>Notes</th></tr></thead><tbody>${rows}</tbody></table></div>`+
  (!running&&sum.failed&&sum.done?`<div class="notice warn"><strong>${sum.failed} source${sum.failed>1?'s':''} did not download.</strong> ${s.rows.filter(r=>r.valid&&r.status==='failed').map(r=>E(r.source_id)).join(', ')} — retry them, or continue with the ${sum.done} that are ready.</div>`:'');
}

function ytPaint(){const node=$('#youtube-card');if(node)node.innerHTML=ytInnerHTML()}
async function ytRefresh(){
 if(!P||window.ytBusy)return;window.ytBusy=true;
 try{const id=P.id,d=await api(`/api/projects/${id}/youtube`);if(P?.id!==id)return;const was=window.ytData;window.ytData=d;window.ytDataFor=id;ytPaint();ytAfter(was,d)}
 catch(e){}finally{window.ytBusy=false}
 ytSchedule();
}
function ytSchedule(){clearTimeout(window.ytTimer);const d=window.ytData;if(d&&(d.running||d.install?.status==='running'))window.ytTimer=setTimeout(ytRefresh,1000)}
// When a run this page watched finishes cleanly, open the footage it imported.
function ytAfter(was,d){
 const s=d?.state;if(!s)return;const key=s.id;
 if(d.running){window.ytWatching=key;return}
 if(window.ytWatching!==key)return;
 window.ytWatching=null;
 const sum=d.summary;
 api('/api/projects/'+P.id).then(p=>{P=p;
  if(typeof resetDocTimeline==='function')resetDocTimeline();
  if(typeof renderProject==='function')renderProject();
  else if(typeof renderProgram==='function')renderProgram();
  if(s.job.status==='complete'&&!sum.invalid&&!sum.failed){toast(`${sum.done}/${sum.total} videos downloaded. Opening your footage.`);manage('assets')}
  else{if(tab==='brief')renderManagement();toast(s.job.status==='cancelled'?'Downloads stopped.':`${sum.done}/${sum.total} videos downloaded. Check the sources that did not download.`)}
 }).catch(()=>{});
}
async function ytCall(url,method='POST',body){
 try{const d=await api(url,method,body);window.ytData=d;window.ytDataFor=P.id;if((d.running||d.started)&&d.state)window.ytWatching=d.state.id;ytPaint();ytSchedule();return d}
 catch(e){toast(e.message);ytRefresh()}
}
async function ytUpload(input){
 const file=input.files?.[0];if(!file)return;const f=new FormData();f.append('file',file);f.append('analyse',document.getElementById('yt-analyse-sheet')?.checked?'1':'0');
 const d=await ytCall(`/api/projects/${P.id}/youtube/sheet`,'POST',f);
 if(d&&!d.started){toast(d.not_started_reason||`Sheet read: ${d.summary.total} sources. Review the list, then click Download Footages.`)}
 else if(d)toast(`Sheet read: ${d.summary.total} sources. Downloading…`);
}
function ytStart(source){return ytCall(`/api/projects/${P.id}/youtube/start`,'POST',source?{source_id:source}:{})}
function ytCancel(){return ytCall(`/api/projects/${P.id}/youtube/cancel`)}
function ytReplace(source){if(!confirm(`Download ${source} again and replace the file already in this production? Storyboard slots that use it will be marked for review.`))return;return ytCall(`/api/projects/${P.id}/youtube/replace/${encodeURIComponent(source)}`)}
function ytOption(name,value){const body={};body[name]=name==='concurrency'?Number(value):value;return ytCall(`/api/projects/${P.id}/youtube/options`,'POST',body)}
function ytClear(){if(!confirm('Clear the download list? Videos already downloaded stay in the production.'))return;return ytCall(`/api/projects/${P.id}/youtube`,'DELETE')}
async function ytInstall(){try{await api('/api/youtube/install','POST');toast('Installing yt-dlp…');window.ytData={...(window.ytData||{}),install:{status:'running',log:[]}};ytPaint();setTimeout(ytRefresh,800)}catch(e){toast(e.message)}}
async function ytContinue(){try{P=await api('/api/projects/'+P.id);if(typeof renderProgram==='function')renderProgram()}catch{}manage('assets')}
