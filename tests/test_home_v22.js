// v22: home page helpers (length, "edited … ago", search/sort, card markup) and navigation.
const fs=require('fs'),path=require('path'),assert=require('assert');
const root=path.join(__dirname,'..');
const els={};
const el=id=>els[id]||(els[id]={id,hidden:false,textContent:'',innerHTML:'',dataset:{},classList:{add(){},remove(){},toggle(){}},scrollTo(){}});
global.document={getElementById:el,querySelectorAll:()=>[],addEventListener(){},body:{classList:{add(){},remove(){}}}};
global.E=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
global.toast=()=>{};global.leave=()=>true;global.pauseEditor=()=>{};global.closeTools=()=>{};
const calls=[];global.history={replaceState:(a,b,u)=>calls.push(u)};
global.list=async()=>({});global.showHome=null;global.P=null;
const now=Date.now()/1000;
global.projects=[
 {id:'a',title:'Zed <b>',format:'landscape',updated:now-600,length_s:899.97,status:'exported',cover_url:'/api/projects/a/cover.jpg?v=1'},
 {id:'b',title:'alpha',format:'portrait',updated:now-3*86400,length_s:58,status:'editing',cover_url:'/c.jpg'},
 {id:'c',title:'Middle',format:'landscape',updated:now-60,length_s:3725,status:'setup',cover_url:null},
];
new Function(fs.readFileSync(path.join(root,'static/home.js'),'utf8')+'\nglobal.__h={homeLength,homeAgo,homeShown,homeCardHTML,renderHome,goHome,setHomeSort,setHomeQuery,showHomePage,hideHomePage,homeVisible};')();
const h=global.__h;
assert.strictEqual(h.homeLength(899.97),'14:59');
assert.strictEqual(h.homeLength(58),'0:58');
assert.strictEqual(h.homeLength(3725),'1:02:05');
assert.strictEqual(h.homeLength(0),'');
assert.strictEqual(h.homeAgo(now-10),'just now');
assert.strictEqual(h.homeAgo(now-600),'10 min ago');
assert.strictEqual(h.homeAgo(now-86400*1.5),'yesterday');
assert.strictEqual(h.homeAgo(now-86400*3),'3 days ago');
assert.strictEqual(h.homeAgo(now-86400*14),'2 weeks ago');
// default: most recently edited first
assert.deepStrictEqual(h.homeShown().map(p=>p.id),['c','a','b']);
h.setHomeSort('title');assert.deepStrictEqual(h.homeShown().map(p=>p.id),['b','c','a']);
h.setHomeSort('length');assert.deepStrictEqual(h.homeShown().map(p=>p.id),['c','a','b']);
h.setHomeSort('updated');h.setHomeQuery('ALP');assert.deepStrictEqual(h.homeShown().map(p=>p.id),['b']);
h.setHomeQuery('');
// cards
const a=h.homeCardHTML(projects[0]);
assert(/Exported/.test(a)&&/14:59/.test(a)&&/16:9 · Edited 10 min ago/.test(a));
assert(a.includes('Zed &lt;b&gt;')&&!a.includes('Zed <b>'),'titles are escaped');
assert(/homeOpen\('a'\)/.test(a)&&/openHomeMenu\(event,'a'\)/.test(a));
const b=h.homeCardHTML(projects[1]);
assert(/9:16/.test(b)&&/home-cover is-portrait/.test(b)&&/Editing/.test(b));
const c=h.homeCardHTML(projects[2]);
assert(/Needs setup/.test(c)&&/No footage yet/.test(c)&&/Created/.test(c)&&!/<img/.test(c));
// grid render
els['home-page'].hidden=false;h.renderHome();
assert.strictEqual(els['home-count'].textContent,'3 projects');
assert.strictEqual((els['home-grid'].innerHTML.match(/class="home-card"/g)||[]).length,3);
// navigation: Home / back arrow from the editor
els['home-page'].hidden=true;h.goHome();
assert.strictEqual(els['home-page'].hidden,false);assert.strictEqual(calls.at(-1),'#/home');
// unsaved changes the user does not want to leave -> stay in the editor
els['home-page'].hidden=true;global.leave=()=>false;h.goHome();
assert.strictEqual(els['home-page'].hidden,true);
// markup: back arrow + Home in the editor header, Projects goes home, old switcher gone
const html=fs.readFileSync(path.join(root,'templates/index.html'),'utf8');
assert(/<div class="head-left"><button type="button" class="head-back" onclick="goHome\(\)"/.test(html),'back arrow first in the header');
// v26: the Home button became Stickers; the back arrow and Projects still go home.
assert(/onclick="goHome\(\)">Projects<\/button>/.test(html));
assert(!/projects-dialog/.test(html));
assert(/onclick="homeCreate\(\)"/.test(html)&&/static\/home\.js/.test(html));
const ed=fs.readFileSync(path.join(root,'static/editor.js'),'utf8');
assert(/else\{renderEditor\(\);if\(window\.showHomePage\)showHomePage\(\)\}/.test(ed),'start-up shows home unless a project link was opened');
console.log('home v22 ok');
