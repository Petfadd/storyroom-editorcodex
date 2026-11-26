// v26: adjusting the CTA shows it for a few seconds only; it no longer hangs on the
// monitor outside its CTA window, and playing always shows the real timing.
const assert=require('assert'),fs=require('fs'),vm=require('vm'),path=require('path');
const frame={clientWidth:1280,clientHeight:720,children:[],insertBefore(n){this.children.push(n)},appendChild(n){this.children.push(n)}};
const img={id:'channel-cta-preview',style:{},dataset:{},naturalWidth:1280,naturalHeight:720};
const elements={'monitor-frame':frame,'channel-cta-preview':img};
const document={querySelector:s=>s==='#monitor-frame'?frame:null,getElementById:id=>elements[id]||null,
 createElement(tag){const n={tagName:tag,style:{},dataset:{},children:[],classList:{contains(){return false},toggle(){},remove(){}},setAttribute(){},appendChild(c){this.children.push(c)},addEventListener(){}};Object.defineProperty(n,'id',{get(){return this._id},set(id){this._id=id;elements[id]=this}});return n}};
const P={id:'s',edit_mode:'documentary',channel_cta_report:{settings:{enabled:true,opacity:.7,width:.5,center_x:.5,center_y:.5,motion_style:'dissolve',fade_s:0},present:true,url:'/c.png',windows:[{start_ms:56360,end_ms:66320,motion_style:'dissolve'}]}};
let now=1000;const timers=[];
const ctx={P,document,window:{docTimelineData:null},console,Number,Math,performance:{now:()=>now},setTimeout:(f,ms)=>{timers.push(f);return timers.length},clearTimeout:()=>{},editorPlaying:false,brandSetValue:()=>{},api:async()=>({}),toast:()=>{}};
vm.createContext(ctx);vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/channel_cta.js'),'utf8'),ctx);
const shown=()=>Number(img.style.opacity)>0;
ctx.updateChannelCTA(20);assert(!shown(),'hidden outside the SRT-called window');
ctx.updateChannelCTA(60);assert(shown(),'shown inside the window');
// press + on the size while parked at 20 s: the card shows so you can see the change …
ctx.ctaStep('width',1);ctx.updateChannelCTA(20);assert(shown(),'visible while adjusting');
// … and 3 s later it goes away again (this used to stay on for good)
now+=3100;timers.forEach(f=>f());assert(!shown(),'hidden again after adjusting');
// playing never shows it outside the window, even straight after an adjustment
ctx.ctaStep('width',1);ctx.editorPlaying=true;ctx.updateChannelCTA(20);assert(!shown(),'playing uses the real timing');
ctx.updateChannelCTA(60);assert(shown(),'and still shows it inside the window');
// "Move on video" mode also ends when you press play
ctx.editorPlaying=false;ctx.toggleChannelCTAAdjust();ctx.updateChannelCTA(20);assert(shown());
ctx.editorPlaying=true;ctx.updateChannelCTA(20);assert(!shown()&&!vm.runInContext('channelCTAEditing',ctx));
console.log('cta peek v26 ok');
