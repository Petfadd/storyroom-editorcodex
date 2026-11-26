// v23: Documentary tools › cutaways: tick rows / Select all, then Approve selected.
const fs=require('fs'),path=require('path'),assert=require('assert');
const root=path.join(__dirname,'..');
const box={innerHTML:''},all={indeterminate:false};
global.document={getElementById:id=>id==='doc-cutaway-status'?box:id==='doc-cutaway-all'?all:null,querySelector:()=>null,addEventListener(){}};
global.window=global;const stub={addEventListener(){},innerHTML:'',open:false,showModal(){},close(){}};global.$=()=>stub;
global.E=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let toasts=[],confirms=0,posts=[];
global.toast=m=>toasts.push(m);global.confirm=()=>{confirms++;return true};global.reloadDocTimeline=()=>{};
let server=[1,2,3,4].map(n=>({id:`CUTAWAY-00${n}`,soundbite_beat:'060',picture_source:`B0${n}.jpg`,timeline_in_ms:n*10000,timeline_out_ms:n*10000+3000,approved:false,reason:'why'}));
global.api=async(url,method,body)=>{
 if(url.endsWith('/documentary-cutaways'))return {cutaways:JSON.parse(JSON.stringify(server))};
 if(url.endsWith('/approve')){posts.push(body);const rejected={};
  for(const r of server)if(body.ids.includes(r.id)){if(body.approved&&r.id==='CUTAWAY-003')rejected[r.id]='picture range is 3.000s but film window is 5.000s; correct IN/OUT.';else r.approved=body.approved}
  return {cutaways:server,rejected}}
 return {id:'p'};
};
const src=fs.readFileSync(path.join(root,'static/documentary.js'),'utf8');
new Function(src.replace(/^let docPlan=null,docPid=null/m,'let docPlan=null,docPid="p"')+'\nglobal.__c={docRefreshCutaways,docTickCutaway,docSelectAllCutaways,docApproveCutaways,docCutawaySel};')();
const c=global.__c;
(async()=>{
 await c.docRefreshCutaways();
 assert(/Select all/.test(box.innerHTML),'Select all box');
 assert(/Approve selected<\/button>/.test(box.innerHTML)&&/onclick="docApproveCutaways\(true\)" disabled/.test(box.innerHTML),'Approve disabled until something is ticked');
 assert(!/Activate all reviewed/.test(box.innerHTML));
 assert.strictEqual((box.innerHTML.match(/Not active/g)||[]).length,4);
 c.docTickCutaway('CUTAWAY-002',true);
 assert(/Approve selected \(1\)/.test(box.innerHTML)&&/ 1 ticked/.test(box.innerHTML));
 assert.strictEqual(all.indeterminate,true);
 c.docSelectAllCutaways(true);
 assert(/Approve selected \(4\)/.test(box.innerHTML));assert.strictEqual(all.indeterminate,false);
 await c.docApproveCutaways(true);
 assert.strictEqual(confirms,1,'one confirmation for all rows');
 assert.deepStrictEqual(posts[0],{ids:['CUTAWAY-001','CUTAWAY-002','CUTAWAY-003','CUTAWAY-004'],approved:true});
 assert.strictEqual((box.innerHTML.match(/>ACTIVE</g)||[]).length,3);
 assert(/Could not approve: picture range is 3.000s/.test(box.innerHTML),'reason shown under the row');
 assert.deepStrictEqual([...c.docCutawaySel],['CUTAWAY-003'],'the failed row stays ticked');
 assert(/3 approved · 1 could not be approved/.test(toasts.at(-1)));
 // turn off
 c.docSelectAllCutaways(true);await c.docApproveCutaways(false);
 assert.strictEqual(posts.at(-1).approved,false);
 assert.strictEqual((box.innerHTML.match(/>ACTIVE</g)||[]).length,0);
 assert.strictEqual(c.docCutawaySel.size,0);
 console.log('cutaway select v23 ok');
})().catch(e=>{console.error(e);process.exit(1)});
