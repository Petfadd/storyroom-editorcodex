/**
 * Intelligent Cinematic Motion Graphics — editor UI.
 *
 * Adds a Motion button + dialog to the editor. The dialog:
 *   - shows enable/disable and auto/manual mode
 *   - runs context analysis on demand
 *   - presents ranked suggestions with one-click accept
 *   - previews each sequence (rendered video) with playback/seeking
 *   - lets the user edit heading/body text, accept, reject or remove
 *   - never modifies narration, footage, SRT or timestamps
 */
(function () {
  'use strict';

  const TEMPLATES = {
    investigative_findings: 'Investigative Findings',
    chronological_timeline: 'Chronological Timeline',
    contradictory_statements: 'Contradictory Statements',
    legal_outcome: 'Legal Outcome',
  };

  let _state = null;   // last GET response
  let _analysis = null;
  let _selectedId = null;

  function _pid() {
    const m = (location.pathname || '').match(/\/editor\/([a-f0-9]{16})/);
    return m ? m[1] : null;
  }

  function _url(suffix) {
    return '/api/projects/' + _pid() + '/motion-graphics' + (suffix || '');
  }

  async function _fetchJSON(url, options) {
    const res = await fetch(url, Object.assign({ headers: { 'Content-Type': 'application/json' } }, options || {}));
    if (!res.ok) {
      const text = await res.text();
      throw new Error(text || ('HTTP ' + res.status));
    }
    return res.json();
  }

  // ---------- open / close ----------

  window.openMotionGraphics = async function openMotionGraphics() {
    const dialog = document.getElementById('motion-graphics-dialog');
    if (!dialog) return;
    dialog.showModal();
    await _load();
  };

  window.closeMotionGraphics = function closeMotionGraphics() {
    const dialog = document.getElementById('motion-graphics-dialog');
    if (dialog) dialog.close();
  };

  async function _load() {
    try {
      _state = await _fetchJSON(_url());
      _render();
    } catch (err) {
      _body().innerHTML = '<div class="mg-status error">Could not load motion graphics: ' + _escape(String(err)) + '</div>';
    }
  }

  function _body() { return document.getElementById('motion-graphics-body'); }

  // ---------- render ----------

  function _render() {
    const s = _state.settings;
    const body = _body();
    const enabled = !!s.enabled;
    const mode = s.mode || 'auto';
    const design = s.design || {};
    const seqs = (s.sequences || []).slice();
    const suggestions = (s.suggestions || []);

    body.innerHTML = `
      <div class="mg-workspace">
        <div>
          <fieldset class="mg-controls" style="margin-bottom:14px">
            <legend>Motion graphics</legend>
            <label style="flex-direction:row;align-items:center;gap:10px;font-size:12px;text-transform:none;letter-spacing:0;color:#eef2f7">
              <input type="checkbox" id="mg-enabled" ${enabled ? 'checked' : ''}>
              Enable motion graphics (optional; disabled by default)
            </label>
            <label style="margin-top:10px">
              Mode
              <select id="mg-mode">
                <option value="auto" ${mode === 'auto' ? 'selected' : ''}>Automatic — analyse the documentary</option>
                <option value="manual" ${mode === 'manual' ? 'selected' : ''}>Manual — place sequences by hand</option>
              </select>
            </label>
          </fieldset>

          ${enabled ? `
          <div class="mg-actions" style="margin-bottom:14px">
            <button class="button primary" id="mg-analyse">Analyse documentary</button>
            <button class="button secondary" id="mg-add-manual">Add manually</button>
          </div>
          <div id="mg-analysis-box"></div>
          <div id="mg-suggestions-box"></div>
          <h3 style="font-size:12px;letter-spacing:.1em;text-transform:uppercase;color:#aab4c2;margin:14px 0 8px">Approved sequences (${seqs.length})</h3>
          <div id="mg-sequences-box"></div>` : '<div class="mg-status">Motion graphics are disabled. Enable to begin.</div>'}
        </div>

        <div class="mg-preview-panel">
          ${enabled ? `
          <div class="mg-stage-shell">
            <div class="mg-stage">
              <video id="mg-preview-video" controls preload="metadata"></video>
              <div class="mg-empty" id="mg-preview-empty">Select a sequence to preview</div>
            </div>
          </div>
          <div class="mg-controls" style="margin-top:14px">
            <fieldset>
              <legend>Design</legend>
              <label>Background
                <select id="mg-bg">
                  ${['charcoal', 'midnight', 'warm', 'neutral'].map(b => `<option value="${b}" ${design.background === b ? 'selected' : ''}>${b[0].toUpperCase() + b.slice(1)}</option>`).join('')}
                </select>
              </label>
              <div class="mg-control-grid" style="margin-top:10px">
                <label>Accent colour
                  <input type="color" id="mg-accent" value="${design.accent_color || '#DC656C'}">
                </label>
                <label>Text colour
                  <input type="color" id="mg-text" value="${design.text_color || '#F1F1EF'}">
                </label>
              </div>
              <label style="margin-top:10px">Motion
                <select id="mg-motion">
                  ${['adaptive', 'mask', 'rise', 'slide', 'soft'].map(m => `<option value="${m}" ${design.motion === m ? 'selected' : ''}>${m[0].toUpperCase() + m.slice(1)}</option>`).join('')}
                </select>
              </label>
            </fieldset>
            <div class="mg-actions" style="margin-top:10px">
              <button class="button secondary" id="mg-save-design">Save design</button>
            </div>
          </div>` : ''}
        </div>
      </div>`;

    // Wire up events
    const en = document.getElementById('mg-enabled');
    if (en) en.addEventListener('change', () => _patch({ enabled: en.checked }));
    const mo = document.getElementById('mg-mode');
    if (mo) mo.addEventListener('change', () => _patch({ mode: mo.value }));
    const an = document.getElementById('mg-analyse');
    if (an) an.addEventListener('click', _analyse);
    const am = document.getElementById('mg-add-manual');
    if (am) am.addEventListener('click', _addManual);
    const sd = document.getElementById('mg-save-design');
    if (sd) sd.addEventListener('click', _saveDesign);

    // Render approved sequences
    if (enabled) {
      _renderSequences(seqs);
      _renderAnalysis();
      _renderSuggestions(suggestions);
    }
  }

  function _renderSequences(seqs) {
    const box = document.getElementById('mg-sequences-box');
    if (!box) return;
    if (!seqs.length) {
      box.innerHTML = '<div class="mg-status">No sequences approved yet. Analyse the documentary or add one manually.</div>';
      return;
    }
    box.innerHTML = seqs.map(seq => {
      const content = seq.content || {};
      const title = content.title || content.kicker || TEMPLATES[seq.template] || seq.template;
      const bodyText = content.findings ? content.findings.join(' · ') :
                       content.events ? content.events.map(e => e.date + ': ' + e.event).join(' · ') :
                       content.verified || content.charges && content.charges.join(', ') || '';
      const dur = (seq.end_s - seq.start_s).toFixed(1);
      const active = seq.id === _selectedId ? ' active' : '';
      return `
        <div class="mg-sequence${active}" data-id="${seq.id}">
          <small>${TEMPLATES[seq.template] || seq.template} · ${_formatTime(seq.start_s)} – ${_formatTime(seq.end_s)} (${dur}s)</small>
          <h4>${_escape(title)}</h4>
          <div class="mg-body-text">${_escape(bodyText)}</div>
          <div class="mg-seq-actions">
            <button data-act="preview" data-id="${seq.id}">Preview</button>
            <button data-act="edit" data-id="${seq.id}">Edit</button>
            <button class="danger" data-act="remove" data-id="${seq.id}">Remove</button>
          </div>
        </div>`;
    }).join('');
    box.querySelectorAll('button[data-act]').forEach(btn => {
      btn.addEventListener('click', () => _seqAction(btn.dataset.act, btn.dataset.id));
    });
  }

  function _renderSuggestions(suggestions) {
    const box = document.getElementById('mg-suggestions-box');
    if (!box) return;
    if (!suggestions.length) { box.innerHTML = ''; return; }
    box.innerHTML = `
      <h3 style="font-size:12px;letter-spacing:.1em;text-transform:uppercase;color:#aab4c2;margin:14px 0 8px">Suggestions (${suggestions.length})</h3>
      ${suggestions.map(sug => {
        const content = sug.content || {};
        const title = content.title || content.kicker || TEMPLATES[sug.template] || sug.template;
        const dur = (sug.end_s - sug.start_s).toFixed(1);
        return `
          <div class="mg-sequence" data-id="${sug.id}">
            <small>${TEMPLATES[sug.template] || sug.template} · ${_formatTime(sug.start_s)} – ${_formatTime(sug.end_s)} (${dur}s) · score ${sug.score}</small>
            <h4>${_escape(title)}</h4>
            <div class="mg-seq-actions">
              <button class="primary" data-act="accept" data-id="${sug.id}">Accept</button>
              <button data-act="preview" data-id="${sug.id}">Preview</button>
              <button data-act="reject" data-id="${sug.id}">Reject</button>
            </div>
          </div>`;
      }).join('')}`;
    box.querySelectorAll('button[data-act]').forEach(btn => {
      btn.addEventListener('click', () => _sugAction(btn.dataset.act, btn.dataset.id));
    });
  }

  function _renderAnalysis() {
    const box = document.getElementById('mg-analysis-box');
    if (!box) return;
    const analysis = _state.analysis;
    if (!analysis) { box.innerHTML = ''; return; }
    const s = analysis.summary || {};
    box.innerHTML = `
      <div class="mg-analysis">
        <b>${s.narration_beats || 0}</b> narration beats ·
        <b>${s.candidates || 0}</b> candidates ·
        <b>${s.excluded || 0}</b> excluded ·
        Acts: ${(s.acts || []).join(', ') || '—'} ·
        Signature: <code>${_state.signature || ''}</code>
      </div>`;
  }

  // ---------- actions ----------

  async function _patch(values) {
    try {
      _state = await _fetchJSON(_url(), { method: 'PATCH', body: JSON.stringify(values) });
      _render();
    } catch (err) {
      _toast('Could not save: ' + err.message);
    }
  }

  async function _analyse() {
    const btn = document.getElementById('mg-analyse');
    if (btn) { btn.disabled = true; btn.textContent = 'Analysing…'; }
    try {
      const data = await _fetchJSON(_url('/analyse'), { method: 'POST' });
      _state.analysis = data.analysis;
      _state.settings.suggestions = data.suggestions;
      _render();
    } catch (err) {
      _toast('Analysis failed: ' + err.message);
      if (btn) { btn.disabled = false; btn.textContent = 'Analyse documentary'; }
    }
  }

  async function _seqAction(act, id) {
    if (act === 'preview') return _previewSequence(id);
    if (act === 'remove') {
      if (!confirm('Remove this motion graphics sequence? Original footage is preserved.')) return;
      const seqs = (_state.settings.sequences || []).filter(s => s.id !== id);
      await _patch({ sequences: seqs });
      if (_selectedId === id) _selectedId = null;
      return;
    }
    if (act === 'edit') return _editSequence(id);
  }

  async function _sugAction(act, id) {
    const suggestions = _state.settings.suggestions || [];
    const seq = suggestions.find(s => s.id === id);
    if (!seq) return;
    if (act === 'accept') {
      const accepted = { ...seq };
      delete accepted.score; delete accepted.beat; delete accepted.act;
      const current = _state.settings.sequences || [];
      await _patch({ sequences: current.concat([accepted]) });
      return;
    }
    if (act === 'reject') {
      await _patch({ suggestions: suggestions.filter(s => s.id !== id) });
      return;
    }
    if (act === 'preview') return _previewSequence(id, suggestions);
  }

  async function _previewSequence(id, pool) {
    const seqs = pool || (_state.settings.sequences || []).concat(_state.settings.suggestions || []);
    const seq = seqs.find(s => s.id === id);
    if (!seq) return;
    try {
      const result = await _fetchJSON(_url('/preview'), { method: 'POST', body: JSON.stringify({ id }) });
      _selectedId = id;
      _pollPreview(result.url);
    } catch (err) {
      _toast('Preview failed: ' + err.message);
    }
  }

  function _pollPreview(url) {
    const video = document.getElementById('mg-preview-video');
    const empty = document.getElementById('mg-preview-empty');
    if (!video) return;
    let attempts = 0;
    const tick = async () => {
      attempts++;
      try {
        const head = await fetch(url, { method: 'HEAD' });
        if (head.ok) {
          video.src = url + '?t=' + Date.now();
          video.style.display = 'block';
          if (empty) empty.style.display = 'none';
          return;
        }
      } catch (_) { /* ignore */ }
      if (attempts < 40) setTimeout(tick, 800);
      else if (empty) { empty.textContent = 'Preview timed out'; empty.style.display = 'flex'; }
    };
    if (empty) { empty.textContent = 'Rendering preview…'; empty.style.display = 'flex'; }
    video.style.display = 'none';
    tick();
  }

  function _editSequence(id) {
    const seq = (_state.settings.sequences || []).find(s => s.id === id);
    if (!seq) return;
    const content = seq.content || {};
    const newTitle = prompt('Edit title:', content.title || content.kicker || '');
    if (newTitle === null) return;
    const seqs = (_state.settings.sequences || []).map(s => {
      if (s.id !== id) return s;
      const copy = JSON.parse(JSON.stringify(s));
      if (copy.content.title !== undefined) copy.content.title = newTitle;
      if (copy.content.kicker !== undefined) copy.content.kicker = newTitle;
      return copy;
    });
    _patch({ sequences: seqs });
  }

  function _addManual() {
    const template = prompt('Template (investigative_findings, chronological_timeline, contradictory_statements, legal_outcome):', 'investigative_findings');
    if (!template || !TEMPLATES[template]) return;
    const start_s = parseFloat(prompt('Start time (seconds from film start):', '60') || '60');
    const end_s = parseFloat(prompt('End time (seconds from film start):', '75') || '75');
    if (!(start_s >= 0 && end_s > start_s + 3)) { _toast('Invalid time range.'); return; }
    const title = prompt('Heading/title:', 'Manual entry') || 'Manual entry';
    const id = 'mg_' + Math.random().toString(16).slice(2, 14);
    const seq = {
      id, template, start_s, end_s,
      content: { title, kicker: TEMPLATES[template], findings: ['Finding 1', 'Finding 2'],
                 events: [{ date: 'Date', event: 'Event' }],
                 verified: 'Verified statement', conflicting: 'Conflicting statement',
                 charges: ['Charge as filed'], verdict: '', sentencing: '' },
    };
    const current = _state.settings.sequences || [];
    _patch({ sequences: current.concat([seq]) });
  }

  async function _saveDesign() {
    const bg = document.getElementById('mg-bg').value;
    const accent = document.getElementById('mg-accent').value;
    const text = document.getElementById('mg-text').value;
    const motion = document.getElementById('mg-motion').value;
    await _patch({ design: { background: bg, accent_color: accent, text_color: text, motion } });
  }

  // ---------- helpers ----------

  function _formatTime(s) {
    s = Math.max(0, Math.floor(s));
    const m = Math.floor(s / 60); const sec = s % 60;
    return m + ':' + String(sec).padStart(2, '0');
  }

  function _escape(s) {
    return String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  function _toast(msg) {
    if (window.showToast) window.showToast(msg);
    else console.warn('[motion-graphics]', msg);
  }
})();
