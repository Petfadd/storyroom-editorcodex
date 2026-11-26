const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const base=path.join(__dirname,'..');
const editor=fs.readFileSync(path.join(base,'static/editor.js'),'utf8');
const doc=fs.readFileSync(path.join(base,'static/documentary_timeline.js'),'utf8');
const text=fs.readFileSync(path.join(base,'static/documentary_transitions.js'),'utf8');
assert.match(editor,/function scrubPlayhead\(/);
const scrub=editor.split('function scrubPlayhead(')[1].split('// Drag across the MP4 track')[0];
assert.doesNotMatch(scrub,/seekEditor\(/,'Pointer movement must not seek media');
const onDrop=editor.split('function endPlayheadDrag(')[1].split('for(const target of')[0];
assert.match(onDrop,/seekEditor\(target,true\)/,'One final precise seek on release');
assert.match(editor,/\$\('#ruler-track'\)/); // ensure the ruler receives the same drag mechanism
assert.match(doc,/function docDirectIndex\(/);
assert.match(doc,/function docUpdateTransitionBadge\(/);
assert.match(doc,/function docTransitionAt\(/);
// Execute the actual transition resolver, not a reimplementation.
const resolverCode=doc.match(/function docTransitionAt\(previous,incoming,playing\)\{[\s\S]*?\n\}/)[0];
const resolveCtx={window:{docTransitionPreviewOverride:null},scenes:()=>[{id:'a',transition:'fade',transition_handle_frames:18},{id:'b',transition:'cut'}]};
vm.createContext(resolveCtx);vm.runInContext(resolverCode,resolveCtx);
const oldClip={scene_id:'a',timeline_out_ms:5000},nextClip={scene_id:'b',timeline_in_ms:5000};
assert.equal(resolveCtx.docTransitionAt(oldClip,nextClip,true).key,'fade');
resolveCtx.window.docTransitionPreviewOverride={scene_id:'a',at_s:5,key:'fadeblack',frames:12};
assert.equal(resolveCtx.docTransitionAt(oldClip,nextClip,true).key,'fadeblack');
assert.equal(resolveCtx.docTransitionAt(oldClip,nextClip,false),null);
assert.equal(resolveCtx.docTransitionAt({scene_id:'a'}, {scene_id:'a',timeline_in_ms:5000},true),null);
let reads=0,writes=0,seeks=[],played=0;
const controls={dataset:{},innerHTML:'',parentNode:{insertBefore(){}},nextElementSibling:null};
const body={innerHTML:'',nextElementSibling:null,parentNode:{insertBefore(){}},after(){}};
const target={innerHTML:''};
const dialog={open:false,showModal(){this.open=true}};
const dollar=selector=>({'#transition-body':body,'#transition-target':target,'#transition-dialog':dialog}[selector]);
const scope={
  P:{id:'test',edit_mode:'documentary',documentary_beat_review:true,scenes:[{id:'s1'},{id:'s2'}]},
  window:{openTransitionLibrary(){}},
  $:dollar,document:{querySelector(){return controls}},
  api:async (url,method,payload)=>{
    if(method==='POST'){writes++;scope.lastPayload=payload;return {project:scope.P,cuts:[{scene_index:0,scene_id:'s1',at_s:5,transition:payload.key||'cut',suggested:'fade',suggested_frames:15,source:'manual',from:'A',to:'B'}],summary:{fade:1}}}
    reads++;
    return {cuts:[{scene_index:0,scene_id:'s1',at_s:5,transition:'cut',suggested:'fade',suggested_frames:15,source:'',from:'A',to:'B'}],
      catalogue:{transitions:[{key:'cut',label:'Cut',detail:'Hard cut'},{key:'fade',label:'Cross Fade',detail:'A smooth blend'}],durations:[{key:'standard',label:'Standard'}]},
      styles:[{key:'balanced',label:'Balanced'},{key:'subtle',label:'Subtle'}]};
  },
  scenes:()=>scope.P.scenes,sceneIndex:0,E:s=>String(s),toast(){},
  closeTransitionLibrary(){dialog.open=false},pauseEditor(){},docSeekTimeline:t=>seeks.push(t),
  docPlayTimeline:()=>{played++},renderInspector(){},renderProject(){},
  setTimeout(fn){fn();return 1},Math,encodeURIComponent,console,
};
scope.window.window=scope.window;
vm.createContext(scope);
vm.runInContext(text,scope);
(async()=>{
 await scope.window.openTransitionLibrary('s1');
 assert.match(target.innerHTML,/Applied:.*Cut/);
 assert.match(target.innerHTML,/Suggested:.*Cross Fade/);
 assert.match(body.innerHTML,/APPLIED/);
 assert.match(body.innerHTML,/SUGGESTED · Not applied/);
 assert.equal(writes,0,'Open dialog must not save a transition');
 scope.window.docTrPreview('suggested');
 assert.equal(scope.window.docTransitionPreviewOverride.key,'fade');
 assert.equal(writes,0,'Preview must not save the suggestion');
 assert.ok(seeks.length===1&&played===1,'Preview must seek and play');
 await scope.window.docTrApplySuggestion();
 assert.equal(writes,1,'Applying suggestion must save one transition');
 assert.equal(scope.lastPayload.key,'fade');
 assert.equal(scope.window.docTransitionPreviewOverride,null,'Save ends temporary preview');
 await scope.window.docTrStyle('subtle');assert.ok(reads>=3);
 console.log('PASS: deferred scrub, live preview labels, suggestion not saved until Apply, source code syntax checks');
})().catch(err=>{console.error(err);process.exit(1)});
