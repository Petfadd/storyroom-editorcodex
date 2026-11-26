/* Source-clock observations stay outside the production timeline. */
function footageReviewHTML(pid, target, speechReady) {
  const asset = P.assets.find(a => a.id === target);
  if (!asset || asset.kind !== 'video') return '';
  const cues = P.srt?.blocks || [];
  return `<section class="card"><h3>Review source footage</h3>
    <video id="research-player" controls preload="none" style="max-width:100%;max-height:260px"
      src="${E(asset.url)}"></video>
    <p><button type="button" id="research-still">Save frame at playhead (PNG)</button></p>
    ${speechReady ? `<label>Narration cue <select id="research-cue"><option value="">All soundbites in source order</option>
      ${cues.map((c,i)=>`<option value="${i}">${E(c.number)} · ${E(c.text.slice(0,100))}</option>`).join('')}</select></label>
      <button type="button" id="research-find">Find soundbites</button>
      <div id="research-results" aria-live="polite"></div>` : '<p>Run local speech analysis to match spoken words to narration cues.</p>'}
    </section>`;
}

function bindFootageReview(pid, target) {
  const player = document.getElementById('research-player');
  if (!player) return;
  const base = '/api/projects/'+encodeURIComponent(pid)+'/understanding/'+encodeURIComponent(target);
  let stop = null, serial = 0;
  player.ontimeupdate = () => {
    if (stop !== null && player.currentTime >= stop) { player.pause(); stop = null; }
  };
  document.getElementById('research-still').onclick = async () => {
    try {
      const response = await fetch(base+'/frame.png?ms='+Math.floor(player.currentTime*1000));
      if (!response.ok) throw Error((await response.json()).error);
      const link = document.createElement('a');
      link.href = URL.createObjectURL(await response.blob());
      link.download = (response.headers.get('Content-Disposition') || '').match(/filename="([^"]+)"/)?.[1] || 'source-frame.png';
      link.click();
      setTimeout(()=>URL.revokeObjectURL(link.href),60000);
    } catch (error) { toast(error.message); }
  };
  const find = document.getElementById('research-find');
  if (!find) return;
  const cue = document.getElementById('research-cue'), results = document.getElementById('research-results');
  async function page(offset) {
    const request = ++serial;
    results.textContent = 'Finding soundbites…';
    try {
      const args = new URLSearchParams({offset});
      if (cue.value !== '') args.set('cue',cue.value);
      const data = await api(base+'/soundbites?'+args);
      if (request !== serial || !results.isConnected) return;
      results.replaceChildren();
      const label = document.createElement('p');
      label.textContent = data.total ? data.total+' candidate(s). Listen to verify machine transcript boundaries.' : 'No matching spoken words in this source.';
      results.append(label);
      for (const row of data.items) {
        const line = document.createElement('p'), button = document.createElement('button');
        button.type='button';
        button.textContent = (row.in_ms/1000).toFixed(3)+'–'+(row.out_ms/1000).toFixed(3)+' s ▶';
        button.onclick = async () => {
          try { player.currentTime=row.in_ms/1000; stop=row.out_ms/1000; await player.play(); }
          catch(error) { toast(error.message); }
        };
        line.append(button, ' '+row.text); results.append(line);
      }
      for (const [name,next] of [['Previous',offset-25],['Next',offset+25]]) {
        if (next<0 || next>=data.total) continue;
        const button=document.createElement('button'); button.type='button'; button.textContent=name;
        button.onclick=()=>page(next); results.append(button);
      }
    } catch (error) { if (request===serial) results.textContent=error.message; }
  }
  find.onclick = cue.onchange = ()=>page(0);
}

