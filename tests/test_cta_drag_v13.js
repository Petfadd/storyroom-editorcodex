const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const path = require('path');
const frame={clientWidth:1280,clientHeight:720,children:[],insertBefore(n){this.children.push(n)},appendChild(n){this.children.push(n)}};
const img={id:'channel-cta-preview',style:{},dataset:{},naturalWidth:1280,naturalHeight:720};
const elements={'monitor-frame':frame,'channel-cta-preview':img};
const document={
 querySelector(selector){return selector==='#monitor-frame'?frame:null},
 getElementById(id){return elements[id]||null},
 createElement(tag){const n={tagName:tag,style:{},dataset:{},children:[],classList:{contains(value){return value==='channel-cta-resize'&&n.className==='channel-cta-resize'}},setAttribute(){},appendChild(child){this.children.push(child)},addEventListener(){},setPointerCapture(){}};Object.defineProperty(n,'id',{get(){return this._id},set(id){this._id=id;elements[id]=this}});return n;}
};
const P={id:'sample', edit_mode:'documentary',channel_cta_report:{settings:{enabled:true,opacity:.7,width:.97,center_x:.5,center_y:.5,motion_style:'dissolve'},present:true,url:'/fake/cta.png',windows:[{start_ms:1000,end_ms:6000,motion_style:'dissolve'}]}};
const ctx={P,document,window:{docTimelineData:null},console,Number,Math,setTimeout:()=>0,clearTimeout:()=>{}};
vm.createContext(ctx);vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/channel_cta.js'),'utf8'),ctx);
ctx.updateChannelCTA(3);
assert(+img.style.width.slice(0,-2)>1200,'default CTA should span nearly the whole 1280px frame');
assert(Math.abs(+img.style.left.slice(0,-2)-19)<3,'default CTA should be centered');
ctx.toggleChannelCTAAdjust();
const box=elements['channel-cta-edit-box'];
assert(box.style.display==='block','drag frame must be visible in edit mode');
// Shrink then move: verify direct interaction updates UI immediately and one save on release.
vm.runInContext('channelCTADraft={width:.45,center_x:.5,center_y:.5}',ctx);
ctx.updateChannelCTA(3);
const originX=parseFloat(img.style.left);
const event=(x,y,target=box)=>({button:0,pointerId:1,clientX:x,clientY:y,target,currentTarget:box,preventDefault(){},stopPropagation(){}});
ctx.ctaPointerStart(event(300,250));
ctx.ctaPointerMove(event(470,330));
assert(parseFloat(img.style.left)>originX+100,'card must move immediately during drag');
let saved=null;ctx.saveChannelCTA=patch=>{saved=patch};
ctx.ctaPointerEnd(event(470,330));
assert(saved&&saved.center_x>.6&&saved.center_y>.6,'manual geometry must be persisted');
// A manual width change should persist and remain user editable.
// v18/v19: the slider became − / + buttons; the same draft-then-commit path saves the width.
ctx.previewChannelCTAWidth('60');ctx.ctaCommitDraft();assert(Math.abs(saved.width-.6)<.011,'size control must persist width');
console.log('CTA browser geometry, drag, save, and size controls: PASS');
