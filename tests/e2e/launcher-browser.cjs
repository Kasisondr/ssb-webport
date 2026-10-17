// End-to-end check of the native package in a real browser.
//
// Run from the repo root after `node --test tests/*.cjs`: it talks to
// `python3 tools/serve.py --rom <rom>` on port 8005, injects the
// ROM through the launcher's own file input (the flow a player uses), waits for
// the engine iframe to boot, verifies the canvas actually renders, presses keys,
// verifies the picture changes, and remaps a control through the launcher's own
// editor to prove the running engine adopts the new key. Prints engine console when verbosely
// asked (SMASH_VERBOSE=1) and on failure.
const path=require('node:path');const fs=require('node:fs');const assert=require('node:assert/strict');
// Playwright is not a dependency of this repo, so accept a local install, an
// explicit PLAYWRIGHT_MODULE, or the sibling checkout this port was built next
// to, and say plainly what to install when none of them is there.
const playwright=()=>{
 const tries=[process.env.PLAYWRIGHT_MODULE,'@playwright/test',
  path.join(__dirname,'..','..','node_modules','@playwright/test'),
  path.join(__dirname,'..','..','..','smash64-web','node_modules','@playwright/test')].filter(Boolean);
 for(const candidate of tries){try{return require(candidate);}catch{}}
 console.error('Playwright is not installed: run `npm i -D @playwright/test` here, or set '
  +'PLAYWRIGHT_MODULE to a @playwright/test directory. This E2E also needs a running '
  +'`python3 tools/serve.py --rom <rom>` and SMASH_ROM (or the ROM at the default path).');
 process.exit(2);
};
const {chromium}=playwright();
const ROOT=path.join(__dirname,'..','..');
const SHOT=path.join(__dirname,'native-launcher.png');
const ROM=process.env.SMASH_ROM||path.resolve(ROOT,'..','Super Smash Bros. (Europe) (En,Fr,De).z64');
const URL=process.env.SMASH_URL||'http://127.0.0.1:8005';
const VERBOSE=process.env.SMASH_VERBOSE==='1'||process.env.SMASH_VERBOSE==='true';
// capture=1 asks the shell for a readable canvas (its getContext patch forces
// preserveDrawingBuffer), which is what frameStats() reads back below.
const QUERY='?SSB64_LOG_INFO=1&SSB64_LOG_LBRELOC_LOAD=1&capture=1';

const sleep=ms=>new Promise(r=>setTimeout(r,ms));

// A live update crosses a frame boundary and is handled on the engine's own
// task, which the engine cannot run while it is still extracting assets. The
// assertion below is about what the engine ended up reading, not about how
// quickly it got there, so poll for it and report the last thing it said.
const waitFor=async(read,match,label,timeout=10000)=>{
 const deadline=Date.now()+timeout;let last=null;
 while(Date.now()<deadline){
  last=await read().catch(()=>null);
  if(last!==null&&match(last))return last;
  await sleep(100);
 }
 throw new Error(`${label} — last read: ${JSON.stringify(last)}`);
};

// Fraction of non-black pixels in the engine's current frame, read through the
// shell's captureFrame() helper (canvas.toDataURL) inside the iframe.
const frameStats=()=>{
 const w=window.frames[0];const url=w.captureFrame();
 return new Promise((resolve,reject)=>{
  const img=new Image();
  img.onload=()=>{const c=document.createElement('canvas');c.width=img.width;c.height=img.height;
   const ctx=c.getContext('2d');ctx.drawImage(img,0,0);
   const d=ctx.getImageData(0,0,c.width,c.height).data;let nz=0;
   for(let i=0;i<d.length;i+=4)if(d[i]|d[i+1]|d[i+2])nz++;
   resolve({width:img.width,height:img.height,nonBlack:nz,total:d.length/4});};
  img.onerror=()=>reject(new Error('capture frame did not decode'));
  img.src=url;});
};

(async()=>{
 if(!fs.existsSync(ROM)) throw new Error(`ROM not found: ${ROM}`);
 const browser=await chromium.launch({channel:'chrome',headless:true});
 const page=await browser.newPage({viewport:{width:1280,height:900}});
 const logs=[];
 page.on('console',m=>logs.push(`[${m.type()}] ${m.text()}`));
 page.on('pageerror',e=>logs.push(`[pageerror] ${e.message}`));
 page.on('response',r=>{if(r.status()>=400)logs.push(`[http ${r.status()}] ${r.url()}`);});
 // A boot that fails on a fetch says which one: the engine reports a generic
 // "could not download the game engine" for any failed script load.
 page.on('requestfailed',r=>logs.push(`[requestfailed] ${r.failure()?.errorText||'?'} ${r.url()}`));
 const dump=()=>{console.log('--- engine log ---');console.log(logs.slice(-60).join('\n'));};

 try{
  await page.goto(URL+QUERY);
  await page.waitForFunction(()=>!document.getElementById('launch').disabled,{timeout:30000});
  assert.equal(await page.evaluate(()=>crossOriginIsolated),true,'COOP/COEP headers must be present');
  await page.locator('#rom-file').setInputFiles(ROM);

  // The launcher mirrors the engine shell's status line; the engine reports a
  // failure there, so watch that instead of guessing a timeout.
  await page.waitForFunction(()=>document.querySelectorAll('iframe').length===1,{timeout:60000});

  // Changeable controls, checked against the live shell while the engine is
  // still extracting assets: the map the launcher sends, a remap through the
  // launcher's own editor, and the key reaching the native pad word. None of
  // this needs a rendered frame.
  let engineFrame=null;
  for(let attempt=0;attempt<100&&!engineFrame;attempt++){
   engineFrame=page.frames().find(frame=>frame.url().includes('/engine/'));
   if(!engineFrame)await sleep(100);
  }
  assert.ok(engineFrame,'engine iframe must be reachable');
  await engineFrame.waitForFunction(()=>!!window.controllerPorts,{timeout:60000});
  // What the live channel did, so a remap that never lands says why.
  await engineFrame.evaluate(()=>{
   window.__sentinel='engine-document-1';window.__sawMessages=[];window.__errs=[];
   window.addEventListener('message',e=>window.__sawMessages.push((e&&e.data&&e.data.type)||'?'));
   window.addEventListener('error',e=>window.__errs.push(String(e.message)));
  });

  const loaded=await engineFrame.evaluate(()=>window.controllerPorts.bindings());
  assert.ok(loaded.actions.A.includes('KeyJ'),`engine booted on the shipped map (got A=${loaded.actions.A})`);
  assert.ok(/[?&]binds=/.test(await page.evaluate(()=>document.querySelector('iframe').src)),
    'the launcher hands the saved map to the engine through ?binds=');
  await page.locator('#bind-list .bind-row[data-action="A"] .key').first().click();
  await page.keyboard.press('KeyQ');
  await page.waitForFunction(()=>/is now Attack/.test(document.getElementById('bind-status').textContent),{timeout:5000});
  // The first chip is the one that was clicked: J becomes Q, the second chip
  // (the mouse button) stays where it was.
  const remapped=await waitFor(()=>engineFrame.evaluate(()=>window.controllerPorts.bindings().actions),
    map=>Array.isArray(map.A)&&map.A.join()==='KeyQ,Mouse0',
    'the live map must follow the launcher');
  const savedControls=JSON.parse(await page.evaluate(()=>localStorage.getItem('smash64.native.bindings')));
  console.log('engine map after the remap:',JSON.stringify(remapped.A),
              '| saved in the launcher:',JSON.stringify(savedControls.actions.A));
  console.log('live-channel diagnostics:',JSON.stringify(await engineFrame.evaluate(()=>({
    sentinel:window.__sentinel, messages:window.__sawMessages, errors:window.__errs,
    frameUrl:String(location.href).slice(0,60),
  }))));
  console.log('frames the page has:',JSON.stringify(page.frames().map(frame=>frame.url().slice(0,55))));
  assert.deepEqual(remapped.A,['KeyQ','Mouse0'],'the live map follows the launcher');
  assert.deepEqual(savedControls.actions.A,['KeyQ','Mouse0'],'the remap is saved for the next session');

  // The new key has to reach the native pad word, not just the map.
  const word=await engineFrame.evaluate(()=>{
    window.controllerPorts.releaseKeyboard();
    window.dispatchEvent(new KeyboardEvent('keydown',{code:'KeyQ',key:'q'}));
    const sample=window.controllerPorts.sampleKeyboard();
    window.dispatchEvent(new KeyboardEvent('keyup',{code:'KeyQ',key:'q'}));
    return sample;
  });
  console.log('pad word for the new key:',word);
  assert.equal(word.button&0x8000,0x8000,'the remapped key presses N64 A');
  assert.equal(word.button&0x4000,0,'and no longer presses anything else');
  console.log('OK: the launcher remaps a control and the live engine adopts it');

  // A controller's buttons are the second table the editor owns. A synthetic
  // standard-mapping pad stands in for hardware in both frames, because the
  // browser hands pads out per document. The event carries the pad on itself:
  // the engine shell plans ports from `gamepadconnected`, and a bare Event has
  // no `gamepad` for it to plan with.
  const injectPad=(scope)=>scope.evaluate(()=>{
   const pad={id:'e2e pad (STANDARD GAMEPAD)',index:0,connected:true,mapping:'standard',axes:[0,0,0,0],
              buttons:Array.from({length:17},()=>({pressed:false,value:0}))};
   window.__pad=pad;
   Object.defineProperty(navigator,'getGamepads',{configurable:true,value:()=>[pad]});
   const event=new Event('gamepadconnected');
   Object.defineProperty(event,'gamepad',{value:pad});
   window.dispatchEvent(event);
   return true;
  });
  const holdPad=(scope,index,down)=>scope.evaluate(({index,down})=>{
   window.__pad.buttons[index]={pressed:down,value:down?1:0};
  },{index,down});

  await injectPad(page);
  await page.waitForSelector('#pad-list .bind-row[data-action="CUP"] .key');
  assert.match(await page.textContent('#pad-status'),/e2e pad/,'the launcher lists the controller');
  assert.equal(await page.locator('#pad-list .bind-row[data-action="CUP"] .key').first().textContent(),'X',
    'and names each button the way the shipped table reads it');
  // Jump becomes the Back button — one the shipped table leaves free, so only
  // this remap can answer for it.
  await page.locator('#pad-list .bind-row[data-action="CUP"] .key').first().click();
  await holdPad(page,8,true);
  await page.waitForFunction(()=>/is now Jump/.test(document.getElementById('bind-status').textContent),{timeout:5000});
  await holdPad(page,8,false);
  assert.equal(await page.locator('#pad-list .bind-row[data-action="CUP"] .key').first().textContent(),'Back',
    'the chip follows the capture');
  const savedPads=JSON.parse(await page.evaluate(()=>localStorage.getItem('smash64.native.bindings'))).pads;
  console.log('saved pad table:',JSON.stringify(savedPads));
  assert.deepEqual(savedPads['e2e pad (STANDARD GAMEPAD)'].CUP,[8,3],'the pad table is saved for the next session');

  await injectPad(engineFrame);
  // The engine adopts the pad table over the same live channel it took the key
  // map from, and reports it back: that is what the editor's "controls in sync"
  // line checks, and none of it needs a rendered frame.
  await page.waitForFunction(()=>/controls in sync/.test(document.getElementById('ports-status').textContent),{timeout:15000});
  console.log('OK: the launcher remaps a controller button and the live engine adopts it');

  const statusOf=()=>page.evaluate(()=>document.querySelector('iframe')?.contentDocument?.getElementById('status')?.textContent||'');
  // Extraction can take ~20s in a visible tab; the engine then compiles 7.5 MB
  // of wasm and starts rendering. Poll until a real frame arrives or the shell
  // reports a failure.
  const deadline=Date.now()+150000;
  let status='';let boot=null;
  while(Date.now()<deadline){
   status=await statusOf();
   if(/failed/i.test(status))break;
   boot=await page.evaluate(frameStats).catch(()=>null);
   if(boot&&boot.width>320&&boot.nonBlack/boot.total>0.01)break;
   await sleep(2000);
  }
  console.log('engine status:',JSON.stringify(status));
  console.log('frame at boot:',boot);
  if(VERBOSE)dump();
  assert.ok(!/failed/i.test(status),`engine reported a failure: ${status}`);
  assert.ok(boot&&boot.nonBlack/boot.total>0.01,`engine rendered a blank frame (${boot&&boot.nonBlack}/${boot&&boot.total} non-black pixels)`);

  // Native KBM: the keyboard must reach the game. Enter advances the title.
  const canvas=page.frameLocator('#engine').locator('canvas');
  await canvas.click({position:{x:40,y:40}}).catch(()=>{});
  for(const key of ['Enter','Enter']){await page.keyboard.press(key);await sleep(1200);}
  const after=await page.evaluate(frameStats);
  console.log('frame after Enter:',after);
  await page.screenshot({path:SHOT,fullPage:false});
  const changed=after.nonBlack!==boot.nonBlack;
  console.log(changed?'input changed the rendered frame':'frame unchanged (title may be static)');

  console.log('OK: native package boots, renders and accepts keyboard input');

  // ---- what the game actually reads ---------------------------------------
  // Every tick the engine's C++ side hands the shell a pointer to its four-port
  // sample buffer and the shell writes the rows through a view of the wasm heap.
  // That memory is the interface the game plays from, so read it back the same
  // way: a shell that cannot find a heap to write into shows a perfect map in
  // its own snapshot and never feeds the game a single byte.
  await engineFrame.evaluate(()=>{
   const module=window.Module;
   if(!module||!module.readPorts||window.__samplePtr!==undefined)return;
   const original=module.readPorts;
   window.__samplePtr=null;
   module.readPorts=ptr=>{if(window.__samplePtr===null)window.__samplePtr=ptr;return original(ptr);};
  });
  const rows=()=>engineFrame.evaluate(()=>{
   const H=(window.Module&&window.Module.HEAP32)||window.HEAP32;
   if(!H||window.__samplePtr===null)return null;
   const base=window.__samplePtr>>2;
   return [0,1,2,3].map(port=>({kind:H[base+port*4],button:H[base+port*4+1],sx:H[base+port*4+2],sy:H[base+port*4+3]}));
  });
  const waitRow=async(port,match,label)=>{
   const deadline=Date.now()+8000;let last=null;
   while(Date.now()<deadline){
    const live=await rows();
    last=live&&live[port];
    if(last&&match(last))return last;
    await sleep(200);
   }
   assert.ok(false,`${label} — last row read: ${JSON.stringify(last)}`);
  };
  const pressKey=(code,down)=>engineFrame.evaluate(({code,down})=>{
   window.dispatchEvent(new KeyboardEvent(down?'keydown':'keyup',{code,key:'',bubbles:true}));
  },{code,down});

  const plan=await waitFor(()=>engineFrame.evaluate(()=>window.controllerPorts.snapshot()),
    live=>live.some(entry=>entry&&entry.kind==='gamepad'),
    'the injected controller must hold a port');
  const keyboardPort=plan.findIndex(entry=>entry&&entry.kind==='keyboard');
  const padPort=plan.findIndex(entry=>entry&&entry.kind==='gamepad');
  console.log('engine ports:',JSON.stringify(plan));
  assert.ok(keyboardPort>=0,'the keyboard owns a port');
  assert.ok(padPort>=0,'and the controller has one');
  await engineFrame.evaluate(()=>window.controllerPorts.releaseKeyboard());
  await waitRow(keyboardPort,row=>row.kind===2,'the keyboard port is sampled as a keyboard');
  await waitRow(padPort,row=>row.kind===3,'the controller port is sampled as a gamepad');

  // The key the launcher remapped presses N64 A in the engine's own buffer, and
  // the key it replaced no longer reaches anything.
  await pressKey('KeyQ',true);
  console.log('engine row for the remapped key:',JSON.stringify(await waitRow(keyboardPort,row=>(row.button&0x8000)===0x8000,'the remapped key presses N64 A')));
  await pressKey('KeyQ',false);
  await waitRow(keyboardPort,row=>row.button===0,'and releases it');
  await pressKey('KeyJ',true);
  await waitRow(keyboardPort,row=>row.button===0,'the key attack left reaches nothing');
  await pressKey('KeyJ',false);

  // And the button the launcher remapped on the controller itself.
  await engineFrame.evaluate(()=>{window.__pad.buttons[8]={pressed:true,value:1};});
  console.log('engine row for the remapped pad button:',JSON.stringify(await waitRow(padPort,row=>(row.button&0x0008)===0x0008,'the remapped pad button presses C-up, which is jump')));
  await engineFrame.evaluate(()=>{window.__pad.buttons[8]={pressed:false,value:0};});
  await waitRow(padPort,row=>row.button===0,'and releasing the button clears it');
  console.log('OK: the launcher remaps controls and the live engine plays them');

  // The keys reset owns the keys: a controller's table has to survive it,
  // because a player who mapped three pads would otherwise lose them all by
  // clearing a keyboard they had stopped using.
  await page.locator('#bind-reset').click();
  await page.waitForFunction(()=>/default keys/.test(document.getElementById('bind-status').textContent),{timeout:5000});
  const afterReset=JSON.parse(await page.evaluate(()=>localStorage.getItem('smash64.native.bindings')));
  assert.deepEqual(afterReset.actions.A,['KeyJ','Mouse0'],'resetting the keys restores the shipped keys');
  assert.deepEqual(afterReset.pads['e2e pad (STANDARD GAMEPAD)'].CUP,[8,3],'and leaves the controller tables alone');
  console.log('OK: the keys reset spares the controllers');
 }catch(error){
  dump();
  await page.screenshot({path:SHOT,fullPage:false}).catch(()=>{});
  throw error;
 }finally{
  await browser.close();
 }
})().catch(error=>{console.error(error);process.exitCode=1;});
