const {test}=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');const vm=require('node:vm');
test('ROM byte-order normalization accepts z64/v64/n64 consistently',()=>{
 const text=fs.readFileSync(__dirname+'/../web/launcher.js','utf8');const a=text.indexOf('function normalizeRom(');const b=text.indexOf('async function storeRom(',a);const context={DataView,Uint8Array};vm.createContext(context);vm.runInContext(text.slice(a,b),context);
 const canonical=[0x80,0x37,0x12,0x40,1,2,3,4];for(const raw of [canonical,[0x37,0x80,0x40,0x12,2,1,4,3],[0x40,0x12,0x37,0x80,4,3,2,1]])assert.deepEqual([...context.normalizeRom(Uint8Array.from(raw))],canonical);
 assert.throws(()=>context.normalizeRom(Uint8Array.from([0,0,0,0])),/valid N64 ROM/);
});
test('native SRAM browser storage preserves every byte',()=>{
 const cpp=fs.readFileSync(__dirname+'/../BattleShip/port/port_save.cpp','utf8');const a=cpp.indexOf('EM_JS(void, local_web_persist_sram');const start=cpp.indexOf('{',a)+1;const end=cpp.indexOf('\n});',start);assert.ok(a>=0&&end>start);
 const bytes=Uint8Array.from({length:32768},(_,i)=>i%256);const store=new Map();const context={FS:{readFile:()=>bytes},UTF8ToString:()=>'/ssb64_save.bin',path:0,localStorage:{setItem:(k,v)=>store.set(k,v)},btoa:text=>Buffer.from(text,'binary').toString('base64'),console};vm.runInNewContext(cpp.slice(start,end),context);
 assert.deepEqual(Buffer.from(store.get('smash64.native.sram.us'),'base64'),Buffer.from(bytes));
});
