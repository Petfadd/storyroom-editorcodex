// v25: full-screen button under the monitor; Esc returns.
const fs=require('fs'),path=require('path'),assert=require('assert');
const root=path.join(__dirname,'..');
const html=fs.readFileSync(path.join(root,'templates/index.html'),'utf8');
assert(/id="transition-library-button"[^>]*>Transitions<\/button><button type="button" id="monitor-fullscreen"[^>]*onclick="toggleMonitorFullscreen\(this\)"/.test(html),'button sits after Transitions, under the monitor');
const js=fs.readFileSync(path.join(root,'static/editor.js'),'utf8');
const start=js.indexOf('function toggleMonitorFullscreen'),end=js.indexOf('\n}',start)+2;
const src=js.slice(start,end);
let requested=0,exited=0,blurred=0;const monitor={requestFullscreen:()=>{requested++;return Promise.resolve()}};
global.document={fullscreenElement:null,exitFullscreen:()=>{exited++}};global.$=s=>s==='#monitor'?monitor:null;global.toast=()=>{};
new Function(src+'\nglobal.__t=toggleMonitorFullscreen;')();
__t({blur(){blurred++}});assert.strictEqual(requested,1);assert.strictEqual(blurred,1,'focus leaves the button so Space plays');
document.fullscreenElement=monitor;__t(null);assert.strictEqual(exited,1,'second press leaves full screen');
assert(/key==='Escape'&&document\.fullscreenElement&&document\.fullscreenElement===\$\('#monitor'\)\)document\.exitFullscreen/.test(js),'Esc returns');
const css=fs.readFileSync(path.join(root,'static/editor.css'),'utf8');
assert(/\.monitor\.is-fullscreen \.monitor-frame,\.monitor\.is-fullscreen\[data-aspect\] \.monitor-frame\{[^}]*height:min\(100vh,calc\(100vw \/ var\(--ar\)\)\)/.test(css),'frame keeps its shape in full screen');
console.log('fullscreen v25 ok');
