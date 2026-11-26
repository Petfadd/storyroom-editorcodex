// v14 CTA editing: four corner handles resize about the centre in every direction,
// the dragged corner follows the pointer, the saved placement equals what is on
// screen, and geometry is measured on the letterboxed picture, not the monitor box.
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const path = require('path');

function harness(frameW, frameH, settings) {
  const frame = {clientWidth: frameW, clientHeight: frameH, children: [], insertBefore(n){this.children.push(n)}, appendChild(n){this.children.push(n)}};
  const img = {id: 'channel-cta-preview', style: {}, dataset: {}, naturalWidth: 1280, naturalHeight: 720};
  const elements = {'monitor-frame': frame, 'channel-cta-preview': img};
  const document = {
    activeElement: null,
    querySelector(sel){return sel === '#monitor-frame' ? frame : null},
    getElementById(id){return elements[id] || null},
    createElement(tag){
      const n = {tagName: tag, style: {}, dataset: {}, children: [], className: '',
        classList: {contains(v){return n.className.split(' ').includes(v)}, toggle(){}},
        setAttribute(){}, appendChild(c){this.children.push(c)}, addEventListener(){}, setPointerCapture(){}};
      Object.defineProperty(n, 'id', {get(){return this._id}, set(id){this._id = id; elements[id] = this}});
      return n;
    }
  };
  const P = {id: 'p', edit_mode: 'documentary', format: 'landscape', channel_cta_report: {
    settings: {enabled: true, opacity: .7, width: .97, center_x: .5, center_y: .5, motion_style: 'dissolve', ...settings},
    present: true, url: '/x.png', windows: [{start_ms: 0, end_ms: 9000, motion_style: 'dissolve'}]}};
  const ctx = {P, document, window: {docTimelineData: null}, console, Number, Math, String, Object, setTimeout, clearTimeout,
    MONITOR_SHAPES: {landscape: '16:9', portrait: '9:16'}};
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../static/channel_cta.js'), 'utf8'), ctx);
  ctx.updateChannelCTA(1);
  ctx.toggleChannelCTAAdjust();
  const box = elements['channel-cta-edit-box'];
  const handle = c => box.children.find(h => h.dataset && h.dataset.corner === c);
  let saved = null; ctx.saveChannelCTA = patch => {saved = patch};
  const px = v => parseFloat(v);
  const rect = () => ({x: px(img.style.left), y: px(img.style.top), w: px(img.style.width), h: px(img.style.height)});
  const ev = (x, y, target) => ({button: 0, pointerId: 7, clientX: x, clientY: y, target, currentTarget: box, preventDefault(){}, stopPropagation(){}});
  function drag(target, from, to) {
    ctx.ctaPointerStart(ev(from[0], from[1], target));
    ctx.ctaPointerMove(ev(to[0], to[1], target));
    const during = rect();
    ctx.ctaPointerEnd(ev(to[0], to[1], target));
    const patch = saved; saved = null;
    ctx.P.channel_cta_report.settings = {...ctx.P.channel_cta_report.settings, ...patch};
    ctx.updateChannelCTA(1);
    return {during, patch, after: rect()};
  }
  return {ctx, box, handle, rect, drag, img};
}

// 1. All four corners exist.
{
  const h = harness(1280, 720, {});
  for (const c of ['nw', 'ne', 'sw', 'se']) assert(h.handle(c), `missing ${c} handle`);
}

// 2. Dragging the SE corner straight LEFT shrinks the card (v13 could not).
{
  const h = harness(1280, 720, {width: .8});
  const r = h.rect();
  const {patch, after} = h.drag(h.handle('se'), [r.x + r.w, r.y + r.h], [r.x + r.w - 200, r.y + r.h]);
  assert(patch.width < .8 - .1, `left drag must shrink, got ${patch.width}`);
  assert(Math.abs((after.x + after.w / 2) - 640) < 1.5, 'shrinks evenly about the centre');
}

// 3. Dragging the SE corner straight UP shrinks too.
{
  const h = harness(1280, 720, {width: .8});
  const r = h.rect();
  const {patch} = h.drag(h.handle('se'), [r.x + r.w, r.y + r.h], [r.x + r.w, r.y + r.h - 120]);
  assert(patch.width < .75, `up drag must shrink, got ${patch.width}`);
}

// 4. NW corner dragged outward grows the card; corner stays near the pointer.
{
  const h = harness(1280, 720, {width: .5});
  const r = h.rect();
  const target = [r.x - 100, r.y - 56.25];
  const {during, patch} = h.drag(h.handle('nw'), [r.x, r.y], target);
  assert(patch.width > .6, `outward drag must grow, got ${patch.width}`);
  assert(Math.abs(during.x - target[0]) < 2 && Math.abs(during.y - target[1]) < 2, 'NW corner must follow the pointer');
}

// 5. Corner can take the card to the full frame width (100%).
{
  const h = harness(1280, 720, {width: .9});
  const r = h.rect();
  const {patch} = h.drag(h.handle('ne'), [r.x + r.w, r.y], [r.x + r.w + 400, r.y - 300]);
  assert(Math.abs(patch.width - 1) < 1e-6, `must reach 100%, got ${patch.width}`);
}

// 6. Moving a large card past the edge saves the position that is on screen.
{
  const h = harness(1280, 720, {width: .97});
  const r = h.rect();
  const {patch} = h.drag(h.box, [r.x + 300, r.y + 200], [r.x + 300 - 500, r.y + 200 - 400]);
  assert(Math.abs(patch.center_x - .5) < .02 && Math.abs(patch.center_y - .5) < .02,
    `a 97% card can barely move, so the saved centre must stay near 0.5, got ${patch.center_x},${patch.center_y}`);
}

// 7. Letterboxed monitor (frame taller than 16:9): geometry follows the picture.
{
  const h = harness(640, 400, {width: 1});
  const r = h.rect();
  assert(Math.abs(r.w - 640) < 1 && Math.abs(r.h - 360) < 1, 'full-width card = picture width');
  assert(Math.abs(r.y - 20) < 1, 'card sits on the picture, below the 20px letterbox bar');
}

// 8. Keyboard nudges and resizes.
{
  const h = harness(1280, 720, {width: .6});
  const key = k => ({key: k, shiftKey: false, preventDefault(){}, stopPropagation(){}});
  h.ctx.ctaKeyDown(key('ArrowRight'));
  h.ctx.ctaKeyDown(key('-'));
  assert(h.ctx.channelCTADraft === undefined || true);
  const draft = vm.runInContext('channelCTADraft', h.ctx);
  assert(draft.center_x > .5 && draft.width < .6, 'arrow / minus keys adjust the draft');
}

console.log('CTA v14 corners, even resize, pointer tracking, 100%, visible save, letterbox, keys: PASS');
