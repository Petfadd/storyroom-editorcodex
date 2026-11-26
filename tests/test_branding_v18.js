// v18: CTA + watermark side by side, small upload tiles, − / + steppers, no sliders.
const fs=require('fs'),path=require('path'),assert=require('assert');
const root=path.join(__dirname,'..');
const saved=[];let previewed=[];
global.E=s=>String(s);global.document={getElementById:()=>null,addEventListener(){}};global.window={addEventListener(){}};
global.P={edit_mode:'documentary',watermark_report:{present:true,url:'/wm.png',settings:{edge_enabled:true,edge_position:'top_right',edge_size:.14,edge_margin:.025,middle_enabled:false,middle_size:.45,middle_opacity:.12}}};
global.setTimeout=(fn)=>{fn();return 1};global.clearTimeout=()=>{};
global.api=async(url,method,body)=>{if(method==='POST')saved.push(Object.entries(body)[0]);return {watermark_report:P.watermark_report}};
new Function(fs.readFileSync(path.join(root,'static/watermark.js'),'utf8')+'\nglobal.__wm={watermarkInspectorHTML,brandStepperHTML,wmStep,brandingPanelHTML};')();
const {watermarkInspectorHTML,wmStep,brandingPanelHTML}=global.__wm;
const html=watermarkInspectorHTML();
assert(!/type="range"/.test(html),'no long sliders');
assert.strictEqual((html.match(/class="brand-step/g)||[]).length,4,'four − / + rows');
assert(/class="brand-upload"/.test(html)&&/type="file"/.test(html),'small upload tile opens the folder');
assert(/Watermark/.test(html));
// middle logo off: its steppers are disabled
assert(/Opacity<\/span>\s*<button type="button" aria-label="Opacity: less" disabled/.test(html));
// steps clamp to the limits and save
for(let i=0;i<60;i++)wmStep('edge_size',1);
assert.deepStrictEqual(saved.at(-1),['edge_size',.4]);
for(let i=0;i<60;i++)wmStep('edge_margin',-1);
assert.deepStrictEqual(saved.at(-1),['edge_margin',0]);
assert.strictEqual(saved.length,120,'each press saves (timers run at once in this test)');
// the pair wraps both columns
global.channelCTAInspectorHTML=()=>'<section id="cta-inspector">CTA</section>';
const pair=brandingPanelHTML();
assert(/^<div class="brand-pair"><section id="cta-inspector">CTA<\/section><section class="brand-col" id="wm-inspector"/.test(pair));
// the CTA column: no sliders either
const cta=fs.readFileSync(path.join(root,'static/channel_cta.js'),'utf8');
const start=cta.indexOf('function channelCTAInspectorHTML'),end=cta.indexOf('function channelCTAMonitorTime');
assert(!/type="range"/.test(cta.slice(start,end)),'CTA panel has no sliders');
assert(/brand-upload/.test(cta.slice(start,end)));
// the header no longer has "+ New" (Projects > + New production does that)
const page=fs.readFileSync(path.join(root,'templates/index.html'),'utf8');
assert(!/onclick="newProduction\(\)">＋ New</.test(page));
assert(/＋ New production/.test(page));
console.log('ok');
