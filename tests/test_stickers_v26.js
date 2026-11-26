// v26: Stickers button replaces Home; animation frames on the monitor match stickers.py.
const fs=require('fs'),path=require('path'),assert=require('assert');
const root=path.join(__dirname,'..');
const html=fs.readFileSync(path.join(root,'templates/index.html'),'utf8');
assert(!/head-home/.test(html),'Home button removed from the header');
assert(/<button type="button" class="head-tool head-stickers" onclick="openStickers\(\)"[^]*?Stickers<\/button><button type="button" class="head-tool" onclick="openCaptionLibrary\(\)">Caption/.test(html),'Stickers sits where Home was, beside Caption');
assert(/class="head-back" onclick="goHome\(\)"/.test(html),'the back arrow still goes home');
assert(/<dialog id="stickers-dialog"/.test(html)&&/static\/stickers\.js/.test(html));
assert(/rel="icon" href="\/static\/favicon\.svg"/.test(html),'tab icon');
global.window={addEventListener(){}};global.document={getElementById:()=>null,querySelector:()=>null};global.setInterval=()=>0;
global.P={edit_mode:'documentary',stickers:[]};global.editorPlaying=false;
new Function(fs.readFileSync(path.join(root,'static/stickers.js'),'utf8')+'\nglobal.__s={stickerFrameIndex,stickerStep,stickerById};')();
const {stickerFrameIndex}=global.__s;
const once={frames:['a','b'],animation:'once',at:[0,.5]},loop={frames:['on','off'],animation:'loop',period:1};
const s={start_s:10,duration_s:4};
assert.deepStrictEqual([9.9,10,11.99,12,13.9].map(t=>stickerFrameIndex(once,s,t)),[0,0,0,1,1]);
assert.deepStrictEqual([10,10.49,10.5,11.2,11.7].map(t=>stickerFrameIndex(loop,s,t)),[0,0,1,0,1]);
assert.strictEqual(stickerFrameIndex({frames:['x'],animation:'static'},s,11),0);
console.log('stickers v26 ok');
