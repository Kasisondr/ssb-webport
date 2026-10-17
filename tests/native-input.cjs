const {test}=require('node:test');const assert=require('node:assert/strict');const vm=require('node:vm');const fs=require('node:fs');
// Runs the engine shell's real controllerPorts block (KeyMap, gamepad sampling,
// port assignment) in a VM with the browser APIs it touches faked.
function sampler(gamepads=[],search=''){
 const html=fs.readFileSync(__dirname+'/../BattleShip/web/index.html','utf8');const start=html.indexOf('window.controllerPorts = (() => {');const end=html.indexOf('\n})();',start)+7;assert.ok(start>=0&&end>start);
 const handlers={};const window={addEventListener:(type,fn)=>(handlers[type]??=[]).push(fn)};const doc={addEventListener:()=>{},hidden:false,getElementById:()=>({addEventListener:(type,fn)=>(handlers[type]??=[]).push(fn),focus:()=>{}})};
 const heap=new Int32Array(16);const Module={HEAP32:heap};
 vm.runInNewContext(html.slice(start,end),{window,navigator:{getGamePadsUnused:()=>[],getGamepads:()=>gamepads},document:doc,location:{search},URLSearchParams,localStorage:{getItem:()=>null},Module,console});
 const fire=(type,event)=>{for(const fn of handlers[type]||[])fn(event);};
 const key=(code,down=true)=>fire(down?'keydown':'keyup',{code,key:'',preventDefault:()=>{}});const mouse=(button,down=true)=>fire(down?'pointerdown':'pointerup',{pointerType:'mouse',button,preventDefault:()=>{}});
 // A pad with `buttons` standard-mapping buttons, all released.
 const connect=(id,index,buttons=1)=>{const g={id,index,connected:true,mapping:'standard',axes:[0,0,0,0],buttons:Array.from({length:buttons},()=>({pressed:false,value:0}))};gamepads[index]=g;fire('gamepadconnected',{gamepad:g});return g;};
 const disconnect=(id,index)=>{const g=gamepads[index];g.connected=false;fire('gamepaddisconnected',{gamepad:g});};
 // What the engine reads for one port this tick.
 const sample=port=>{window.controllerPorts.readPorts(0);return {kind:heap[port*4],button:heap[port*4+1],sx:heap[port*4+2],sy:heap[port*4+3]};};
 return {key,mouse,connect,disconnect,sample,pad:window.controllerPorts,heap,gamepads};
}
// Leaves button `i` pressed or released on a pad the harness handed back.
const hold=(g,i,down=true)=>{g.buttons[i]={pressed:down,value:down?1:0};};
const padPlan=pads=>'?binds='+encodeURIComponent(JSON.stringify({v:1,actions:{},pads}));
test('native pad maps mouse to A/B/Z and keyboard to C-up/R/Start',()=>{const {key,mouse,pad}=sampler();mouse(0);assert.equal(pad.sampleKeyboard().button,0x8000);mouse(0,false);mouse(2);assert.equal(pad.sampleKeyboard().button,0x4000);mouse(2,false);mouse(1);assert.equal(pad.sampleKeyboard().button,0x2000);mouse(1,false);key('Space');key('ShiftLeft');key('Enter');assert.equal(pad.sampleKeyboard().button,0x1018);});
test('native stick directions normalize and Alt reduces magnitude',()=>{const{key,pad}=sampler();key('KeyW');key('KeyD');let s=pad.sampleKeyboard();assert.ok(Math.hypot(s.sx,s.sy)<=81);assert.ok(s.sx>0&&s.sy>0);key('AltLeft');s=pad.sampleKeyboard();assert.ok(s.sx<30&&s.sy<30);pad.releaseKeyboard();assert.equal(pad.sampleKeyboard().sx,0);assert.equal(pad.sampleKeyboard().button,0);});

test('keyboard-only session owns player 1',()=>{const{pad}=sampler();const ports=pad.snapshot();assert.equal(ports[0].kind,'keyboard');assert.equal(ports[1],null);});

test('a gamepad used before the keyboard takes player 1',()=>{
 const{connect,pad,gamepads,heap}=sampler();
 const g=connect('test-pad',0);
 const ports=pad.snapshot();
 assert.equal(ports[0].kind,'gamepad');
 assert.equal(ports[1].kind,'keyboard','keyboard slides to the next port so both stay playable');
 g.buttons[0]={pressed:true};
 pad.readPorts(0);
 assert.equal(heap[0],3,'port 1 reports a native gamepad');
 assert.equal(heap[1],0x8000,'gamepad A reaches the engine button word');
 assert.equal(heap[4],2,'port 2 reports the keyboard');
 assert.equal(gamepads.length,1);
});

test('a keyboard used first keeps player 1 when a pad arrives',()=>{
 const{key,connect,pad}=sampler();
 key('KeyJ');
 assert.equal(pad.keyboardUsed(),true);
 connect('late-pad',0);
 const ports=pad.snapshot();
 assert.equal(ports[0].kind,'keyboard');
 assert.equal(ports[1].kind,'gamepad');
});

test('extra pads fill the remaining free ports without evicting the keyboard',()=>{
 const{connect,pad}=sampler();
 connect('pad-a',1);connect('pad-b',0);connect('pad-c',2);
 const kinds=Array.from(pad.snapshot(),p=>p&&p.kind);
 assert.deepEqual(kinds,['gamepad','keyboard','gamepad','gamepad']);
});

test('a disconnected pad holds its port and reads as unplugged until it returns',()=>{
 const{connect,disconnect,pad,heap}=sampler();
 connect('pad',0);
 disconnect('pad',0);
 assert.equal(pad.snapshot()[0].lost,true,'the port stays owned by the same pad');
 pad.readPorts(0);
 assert.equal(heap[0],1,'a lost pad reads as no device, so no fighter changes hands');
});

test('the shipped gamepad map is the one the engine reads',()=>{
 const{connect,sample}=sampler();
 const g=connect('pad',0,17);
 assert.equal(sample(0).kind,3,'the pad owns a port');
 const read=i=>{hold(g,i);const button=sample(0).button;hold(g,i,false);return button;};
 assert.equal(read(0),0x8000,'A');assert.equal(read(1),0x4000,'B');
 assert.equal(read(2),0x0008,'X is C-up');assert.equal(read(3),0x0008,'Y is C-up too');
 assert.equal(read(4),0x0020,'LB is L');assert.equal(read(5),0x0010,'RB is R');assert.equal(read(7),0x0010,'RT is R too');
 assert.equal(read(6),0x2000,'LT is Z');assert.equal(read(9),0x1000,'Start');
 assert.equal(read(12),0x0800,'D-pad up');assert.equal(read(13),0x0400,'D-pad down');
 assert.equal(read(14),0x0200,'D-pad left');assert.equal(read(15),0x0100,'D-pad right');
 assert.equal(read(8),0,'Back is unmapped, as it shipped');
});

test('a pad plan remaps the buttons the engine reads, on that pad alone',()=>{
 const{connect,sample,pad}=sampler([],padPlan({'pad-a':{A:[8]}}));
 const a=connect('pad-a',0,17),b=connect('pad-b',1,17);
 // Which port a pad lands on depends on what was plugged in when: ask the
 // live map instead of assuming the order.
 const portOf=g=>pad.snapshot().findIndex(entry=>entry&&entry.kind==='gamepad'&&entry.id===g.id);
 assert.ok(portOf(a)>=0&&portOf(b)>=0,'both pads hold a port');
 assert.notEqual(portOf(a),portOf(b),'on ports of their own');
 hold(a,8);hold(b,8);
 assert.equal(sample(portOf(a)).button,0x8000,'pad-a attacks with the button the plan named');
 assert.equal(sample(portOf(b)).button,0,'while pad-b keeps the shipped mapping');
 hold(a,8,false);hold(b,8,false);hold(a,0);hold(b,0);
 assert.equal(sample(portOf(a)).button,0,'the button A left no longer attacks there');
 assert.equal(sample(portOf(b)).button,0x8000,'and it still attacks on the pad the plan did not name');
});

test('a pad button can hold the walk modifier',()=>{
 const{connect,sample}=sampler([],padPlan({pad:{WALK:[11]}}));
 const g=connect('pad',0,17);
 g.axes[0]=1;
 assert.equal(sample(0).sx,80,'a full tilt is a full stick');
 hold(g,11);
 const walk=sample(0);
 assert.ok(walk.sx>0&&walk.sx<45,`holding the walk button reduces the stick (got ${walk.sx})`);
 assert.equal(walk.button,0,'and presses nothing');
 hold(g,11,false);
 assert.equal(sample(0).sx,80,'as does releasing it');
});

test('a pad button bound to a stick direction is the digital fallback',()=>{
 const{connect,sample}=sampler([],padPlan({pad:{LEFT:[8]}}));
 const g=connect('pad',0,17);
 hold(g,8);
 assert.equal(sample(0).sx,-80,'the button drives the stick full left');
 assert.equal(sample(0).sy,0,'with nothing on the other axis');
 g.axes[0]=1;
 assert.equal(sample(0).sx,80,'a deflected analog stick wins over the button');
 g.axes[0]=0;
 assert.equal(sample(0).sx,-80,'until it returns to center');
});

test('a plan that carries only pad tables still leaves the keyboard shipped',()=>{
 const{key,mouse,pad,connect}=sampler([],padPlan({pad:{A:[8]}}));
 connect('pad',0,17);
 key('KeyJ');
 assert.equal(pad.sampleKeyboard().button,0x8000,'J still attacks');
 key('KeyJ',false);mouse(2);
 assert.equal(pad.sampleKeyboard().button,0x4000,'and right click is still B');
});
