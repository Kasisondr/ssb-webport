const $ = id => document.getElementById(id);
// ROM regions this engine build can extract. The game code is a US build; the
// European version is supported because yamls/eu maps every US asset name onto
// the European reloc file id that holds it (see tools/eu_reloc_map.py).
const SUPPORTED_ROMS = [
  { sha1: 'e2929e10fccc0aa84e5776227e798abc07cedabf', label: 'US v1.0',
    saveKey: 'smash64.native.sram.us' },
  { sha1: '6ee8a41fef66280ce3e3f0984d00b96079442fb9', label: 'Europe (En,Fr,De)',
    saveKey: 'smash64.native.sram.eu' },
];
const SUPPORTED_LABELS = SUPPORTED_ROMS.map(rom => rom.label).join(' or ');
function normalizeRom(bytes) {
  const magic = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength).getUint32(0);
  if (magic === 0x37804012) for (let i=0;i<bytes.length;i+=2) [bytes[i],bytes[i+1]]=[bytes[i+1],bytes[i]];
  else if (magic === 0x40123780) for (let i=0;i<bytes.length;i+=4) [bytes[i],bytes[i+1],bytes[i+2],bytes[i+3]]=[bytes[i+3],bytes[i+2],bytes[i+1],bytes[i]];
  else if (magic !== 0x80371240) throw Error('Choose a valid N64 ROM.');
  return bytes;
}
async function storeRom(file) {
  const bytes = normalizeRom(new Uint8Array(await file.arrayBuffer()));
  const digest = await crypto.subtle.digest('SHA-1',bytes);
  const sha1 = Array.from(new Uint8Array(digest),v=>v.toString(16).padStart(2,'0')).join('');
  const region = SUPPORTED_ROMS.find(rom => rom.sha1 === sha1);
  if (!region) throw Error(`This native build needs the ${SUPPORTED_LABELS} ROM.`);
  const db = await new Promise((resolve,reject)=>{
    const r=indexedDB.open('opensmash-rom',1);
    r.onupgradeneeded=()=>{for(const [name,keyPath] of [['roms','sha1'],['archives','key'],['meta','key']]) if(!r.result.objectStoreNames.contains(name))r.result.createObjectStore(name,{keyPath});};
    r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);
  });
  await new Promise((resolve,reject)=>{const tx=db.transaction(['roms','meta'],'readwrite');tx.objectStore('roms').put({sha1,size:bytes.length,name:file.name,region:region.label,bytes:bytes.buffer,storedAt:Date.now()});tx.objectStore('meta').put({key:'current',sha1});tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error);});
  db.close();
  return region;
}
let cachedRom = null;
function unlockAudio() {
  const Audio = window.AudioContext || window.webkitAudioContext;
  if (Audio && !window.__openSmashAudioContext) window.__openSmashAudioContext = new Audio();
  if (window.__openSmashAudioContext) void window.__openSmashAudioContext.resume();
}
async function startEngine() {
  $('launch').disabled=true;
  unlockAudio();
  const region = cachedRom || SUPPORTED_ROMS[0];
  const frame=document.createElement('iframe');frame.id='engine';frame.title='Native Smash 64';frame.allow='autoplay; fullscreen';
  // savekey namespaces the browser SRAM per region (see the engine shell's
  // LOCAL_SRAM_RESTORE block), so saves never cross regions. SSB64_* parameters
  // on the launcher URL are forwarded so the engine's diagnostics
  // (SSB64_LOG_INFO, SSB64_DUMP_FILE_ID, ...) can be switched on from a link.
  const engineParams=new URLSearchParams({SSB64_RENDER_SIZE:$('resolution').value,savekey:region.saveKey});
  // `capture=1` is the shell's readable-canvas mode for capture runs (see its
  // getContext patch and captureFrame helper); everything else prefixed SSB64_
  // is a port diagnostic.
  for(const [key,value] of new URLSearchParams(location.search)) if(key.startsWith('SSB64_')||key==='capture') engineParams.set(key,value);
  // Changeable controls: the launcher owns the saved plan (see bindings.js), so
  // the engine boots into the player's key map, its per-controller button
  // tables and its port layout instead of the shipped defaults. Edits made
  // while the game runs arrive over postMessage.
  engineParams.set('binds',JSON.stringify(planFor(controls)));
  const plan=portPlan();if(plan)engineParams.set('ports',JSON.stringify(plan));
  frame.src='/engine/index.html?'+engineParams;
  $('welcome').style.display='none';$('stage').appendChild(frame);
  $('status').textContent='Extracting assets and starting…';
  frame.onload=()=>{frame.contentWindow.focus();const timer=setInterval(()=>{const text=frame.contentDocument?.getElementById('status')?.textContent;$('status').textContent=text || 'Native engine running';},1000);frame.addEventListener('error',()=>clearInterval(timer));};
}
$('launch').onclick=()=>{unlockAudio();if(cachedRom)startEngine().catch(error=>{$('status').textContent=error.message;$('launch').disabled=false;});else $('rom-file').click();};
$('rom-file').onchange=async event=>{
  const file=event.target.files[0];if(!file)return;
  $('launch').disabled=true;$('status').textContent='Checking ROM…';
  try{cachedRom=await storeRom(file);await startEngine();}
  catch(error){$('status').textContent=error.message;$('launch').disabled=false;}
};
async function hasSavedRom() {
  const db = await new Promise((resolve,reject)=>{
    const request=indexedDB.open('opensmash-rom',1);
    request.onupgradeneeded=()=>{for(const [name,keyPath] of [['roms','sha1'],['archives','key'],['meta','key']]) if(!request.result.objectStoreNames.contains(name))request.result.createObjectStore(name,{keyPath});};
    request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error);
  });
  for (const region of SUPPORTED_ROMS) {
    const found=await new Promise((resolve,reject)=>{const request=db.transaction('roms','readonly').objectStore('roms').get(region.sha1);request.onsuccess=()=>resolve(!!request.result?.bytes);request.onerror=()=>reject(request.error);});
    if (found) { db.close(); return region; }
  }
  db.close();return null;
}
$('fullscreen').onclick=async()=>{document.fullscreenElement?await document.exitFullscreen():await $('stage').requestFullscreen();$('engine')?.contentWindow.focus();};
(async()=>{try{const response=await fetch('/engine/manifest.json',{method:'HEAD'});if(!response.ok)throw Error('The native engine is still being built.');cachedRom=await hasSavedRom();$('status').textContent=cachedRom?`Ready · ${cachedRom.label} ROM saved`:`Ready · ${SUPPORTED_LABELS} ROM required`;$('launch').textContent=cachedRom?`Play game ↗ · ${cachedRom.label}`:'Choose ROM ↗';$('launch').disabled=false;}catch(error){$('status').textContent=error.message;}})();

// ---- changeable controls --------------------------------------------------
// The launcher owns the saved control plan and the engine shell in the iframe
// consumes it (see the LOCAL_KBM_MAP block in the shell's controllerPorts, and
// web/bindings.js for the action table both sides agree on). A remap is saved in
// localStorage, pushed into the running game over postMessage, and handed to the
// next session through ?binds=. The engine answers with the ports and bindings it
// is actually reading, which is what the status lines below report.
const BINDING_STORE='smash64.native.bindings';
const PORT_STORE='smash64.native.ports';
const B=window.Smash64Bindings;
const readSaved=key=>{try{const raw=localStorage.getItem(key);return raw?JSON.parse(raw):null;}catch(error){return null;}};
const writeSaved=(key,value)=>{try{localStorage.setItem(key,JSON.stringify(value));}catch(error){/* private mode: the session still works */}};
const el=(tag,className,text)=>{const node=document.createElement(tag);if(className)node.className=className;if(text!=null)node.textContent=text;return node;};
let controls=B.normalize(readSaved(BINDING_STORE))||B.defaults();
let ports=normalizePorts(readSaved(PORT_STORE));
let capturing=null;
let padCapture=null;
let padWatch=0;
let selectedPad=null;
let statusTimer=null;
// The plan the engine reads: both tables travel together in ?binds= and in
// every live update, because they are one answer to "what does the player press".
const planFor=source=>({v:1,actions:source.actions,pads:source.pads});

// A saved port plan only carries what the player chose; an untouched port stays
// "automatic" (null) and the engine plans it natively.
function normalizePorts(saved){
  if(!Array.isArray(saved))return[null,null,null,null];
  return[0,1,2,3].map(index=>{
    const entry=saved[index];
    if(!entry||typeof entry!=='object')return null;
    if(entry.kind==='keyboard')return{kind:'keyboard'};
    if(entry.kind==='none')return{kind:'none'};
    if(entry.kind==='gamepad'&&typeof entry.id==='string')return{kind:'gamepad',id:entry.id,index:Number(entry.index)||0};
    return null;
  });
}
function portPlan(){return ports.some(entry=>entry)?ports.map(entry=>entry||null):null;}
function gamepads(){return navigator.getGamepads?Array.from(navigator.getGamepads()).filter(pad=>pad&&pad.connected):[];}
const padKey=pad=>`pad:${pad.index}:${pad.id}`;
const padLabel=pad=>`Gamepad ${pad.index+1} · ${String(pad.id).slice(0,28)}`;

function setStatus(message,keep){
  $('bind-status').textContent=message;
  if(statusTimer)clearTimeout(statusTimer);
  if(keep)return;
  statusTimer=setTimeout(()=>{$('bind-status').textContent=summary();},6000);
}
function countChanged(table,defaults){
  return B.ACTIONS.filter(action=>String(table[action])!==String(defaults[action])).length;
}
function summary(){
  const keys=countChanged(controls.actions,B.DEFAULTS);
  const pads=Object.keys(controls.pads).length;
  const parts=[keys?`${keys} of ${B.ACTIONS.length} keys customised`:'default keys'];
  if(pads)parts.push(pads===1?'1 controller remapped':`${pads} controllers remapped`);
  return parts.join(' · ')+' · saved in this browser';
}
// One group of action rows. The keyboard and gamepad tables differ only in what
// a chip reads, writes and calls itself, so they share this.
function groupRows(group,spec){
  const section=el('div','bind-group');
  const head=el('div','bind-group-title');
  head.append(el('h3',null,group.title),el('span',null,group.hint));
  section.append(head);
  for(const entry of group.actions){
    const row=el('div','bind-row');
    row.dataset.action=entry.action;
    const name=el('div','bind-name');
    name.append(el('b',null,entry.action),el('span',null,entry.label));
    const keys=el('div','bind-keys');
    const codes=spec.keys(entry.action);
    codes.forEach((code,index)=>keys.append(spec.chip(entry.action,code,index)));
    if(codes.length<spec.max)keys.append(spec.add(entry.action,codes.length));
    row.append(name,keys);
    section.append(row);
  }
  return section;
}
function renderControls(){
  const list=$('bind-list');list.textContent='';
  for(const group of B.GROUPS)list.append(groupRows(group,{
    keys:action=>controls.actions[action]||[],
    max:B.MAX_KEYS,
    chip:(action,code,index)=>keyChip(action,code,index),
    add:(action,index)=>addChip(action,index),
  }));
}
function isCapturing(action,index){return!!capturing&&capturing.action===action&&capturing.index===index;}
function keyChip(action,code,index){
  const label=B.keyLabel(code,controls.printed[code]);
  const wrap=el('span','key-wrap'+(isCapturing(action,index)?' key-capturing':''));
  const chip=el('button','key',isCapturing(action,index)?'Press a key…':label);
  chip.title=`Change ${B.actionMeta(action).label} — click, then press the key you want`;
  chip.onclick=()=>startCapture(action,index);
  const remove=el('button','key-x','×');
  remove.title=`Remove ${label} from ${B.actionMeta(action).label}`;
  remove.onclick=event=>{event.stopPropagation();clearKey(action,index);};
  wrap.append(chip,remove);
  return wrap;
}
function addChip(action,index){
  const chip=el('button','key key-add',isCapturing(action,index)?'Press a key…':'+');
  chip.title=`Add another key for ${B.actionMeta(action).label}`;
  chip.onclick=()=>startCapture(action,index);
  return chip;
}
function startCapture(action,index){
  capturing={action,index};
  padCapture=null;
  stopPadWatch();
  renderControls();renderPads();
  setStatus(`Press the key you want for ${B.actionMeta(action).label}… (Escape cancels)`,true);
}
function stopPadWatch(){if(padWatch)cancelAnimationFrame(padWatch);padWatch=0;}
function cancelCapture(){
  capturing=null;padCapture=null;stopPadWatch();
  renderControls();renderPads();
  setStatus('Nothing changed.');
}
function commit(message){
  for(const action of B.ACTIONS)controls.actions[action]=controls.actions[action].slice(0,B.MAX_KEYS);
  controls=B.normalize(controls)||B.defaults();
  capturing=null;padCapture=null;stopPadWatch();
  writeSaved(BINDING_STORE,controls);
  renderControls();renderPads();
  engineMessage({type:'smash64:bindings',bindings:planFor(controls)});
  setStatus(message);
}
// One physical key belongs to one action: mapping a key that is already in use
// takes it away from the action that held it, which is what the status line says.
function assign(action,index,code,printed){
  const takenFrom=[];
  for(const other of B.ACTIONS){
    if(other===action)continue;
    const keys=controls.actions[other]||[];
    if(!keys.includes(code))continue;
    controls.actions[other]=keys.filter(key=>key!==code);
    takenFrom.push(B.actionMeta(other).label);
  }
  const keys=controls.actions[action].slice();
  if(index<keys.length)keys[index]=code;else keys.push(code);
  controls.actions[action]=keys.filter((key,position)=>keys.indexOf(key)===position).slice(0,B.MAX_KEYS);
  if(printed)controls.printed[code]=printed;
  commit(`${B.keyLabel(code,printed)} is now ${B.actionMeta(action).label}${takenFrom.length?` (taken from ${takenFrom.join(', ')})`:''}.`);
}
function clearKey(action,index){
  const code=controls.actions[action][index];
  controls.actions[action]=controls.actions[action].filter((key,position)=>position!==index);
  commit(`${B.keyLabel(code,controls.printed[code])} released from ${B.actionMeta(action).label}.`);
}
// ---- gamepad buttons ------------------------------------------------------
// Same editor, second table. A pad's buttons are saved per controller
// (Gamepad.id), so the layout follows the controller you plug in rather than
// the port it lands on, and a button is captured by pressing it on the pad.
const padDown=(pad,index)=>{
  const button=pad&&pad.buttons?pad.buttons[index]:null;
  return!!button&&(button.pressed||button.value>0.5);
};
const padKeys=(id,action)=>{
  const table=controls.pads[id];
  return(table&&table[action])||B.PAD_DEFAULTS[action];
};
// The editable table for a pad. A pad the player has not touched has no entry,
// so the first edit copies the shipped table rather than starting from empty.
function padTable(id){
  if(!controls.pads[id])controls.pads[id]=B.padDefaults();
  return controls.pads[id];
}
function padSummary(id){
  const table=controls.pads[id];
  const changed=table?countChanged(table,B.PAD_DEFAULTS):0;
  return changed?`${changed} of ${B.ACTIONS.length} buttons customised`:'standard buttons';
}
function isPadCapturing(action,index){return!!padCapture&&padCapture.action===action&&padCapture.index===index;}
function padChip(action,code,index,editable){
  const label=B.padButtonLabel(code);
  const wrap=el('span','key-wrap'+(isPadCapturing(action,index)?' key-capturing':''));
  const chip=el('button','key',isPadCapturing(action,index)?'Press a button…':label);
  chip.title=`Button ${code} on the standard gamepad mapping — ${B.actionMeta(action).label}. Click, then press the pad button you want.`;
  chip.disabled=!editable;
  chip.onclick=()=>startPadCapture(action,index);
  const remove=el('button','key-x','×');
  remove.title=`Remove ${label} from ${B.actionMeta(action).label}`;
  remove.onclick=event=>{event.stopPropagation();clearPadKey(action,index);};
  wrap.append(chip,remove);
  return wrap;
}
function padAdd(action,index,editable){
  const chip=el('button','key key-add',isPadCapturing(action,index)?'Press a button…':'+');
  chip.title=`Add another button for ${B.actionMeta(action).label}`;
  chip.disabled=!editable;
  chip.onclick=()=>startPadCapture(action,index);
  return chip;
}
function renderPads(){
  const pads=gamepads();
  const ids=[];
  for(const pad of pads)if(!ids.includes(pad.id))ids.push(pad.id);
  // A saved table for a controller that is not plugged in stays listed, so a
  // player can see (or clear) the layout waiting for it.
  for(const id of Object.keys(controls.pads))if(!ids.includes(id))ids.push(id);
  if(!selectedPad||!ids.includes(selectedPad))selectedPad=ids[0]||null;
  const pad=pads.find(entry=>entry.id===selectedPad)||null;

  const pick=$('pad-pick');pick.textContent='';
  if(ids.length>1||(!pad&&selectedPad)){
    const select=document.createElement('select');
    select.title='Which controller you are editing';
    for(const id of ids){
      const live=pads.find(entry=>entry.id===id);
      const option=document.createElement('option');
      option.value=id;
      option.textContent=live?padLabel(live):`${id.slice(0,28)} (not connected)`;
      if(id===selectedPad)option.selected=true;
      select.append(option);
    }
    select.onchange=()=>{selectedPad=select.value;renderPads();};
    pick.append(select);
  }

  const status=$('pad-status');
  const list=$('pad-list');list.textContent='';
  if(!selectedPad){
    status.textContent='No controller connected.';
    list.append(el('p','pad-note','Plug in a controller and its buttons appear here. Until then the shipped standard mapping is what the game plays with.'));
    return;
  }
  const count=pad&&pad.buttons?pad.buttons.length:0;
  status.textContent=pad
    ?`${padLabel(pad)} · ${count} buttons · ${padSummary(selectedPad)}`
    :`${selectedPad.slice(0,28)} · not connected · ${padSummary(selectedPad)}`;
  if(!pad)list.append(el('p','pad-note','Connect this controller to change its buttons. The table below is what it will use when it comes back.'));
  for(const group of B.GROUPS)list.append(groupRows(group,{
    keys:action=>padKeys(selectedPad,action),
    max:B.MAX_PAD_BUTTONS,
    chip:(action,code,index)=>padChip(action,code,index,!!pad),
    add:(action,index)=>padAdd(action,index,!!pad),
  }));
}
function startPadCapture(action,index){
  const pad=gamepads().find(entry=>entry.id===selectedPad);
  if(!pad){setStatus('Connect that controller to change its buttons.',true);return;}
  capturing=null;
  // A button already held when the capture starts is the player's business and
  // not an answer, so only a button pressed *after* this point counts.
  const stale=new Set();
  for(let i=0;i<(pad.buttons?pad.buttons.length:0);i++)if(padDown(pad,i))stale.add(i);
  padCapture={action,index,id:selectedPad,stale};
  renderControls();renderPads();
  setStatus(`Press the button you want for ${B.actionMeta(action).label} on ${padLabel(pad)}… (Escape cancels)`,true);
  stopPadWatch();
  padWatch=requestAnimationFrame(watchPad);
}
// A gamepad is only readable when the page asks for it, so a capture polls the
// pad until a button goes down.
function watchPad(){
  if(!padCapture)return;
  const pad=gamepads().find(entry=>entry.id===padCapture.id);
  if(!pad){cancelCapture();setStatus('That controller went away — nothing changed.');return;}
  const count=pad.buttons?pad.buttons.length:0;
  for(let i=0;i<count;i++){
    if(!padDown(pad,i)){padCapture.stale.delete(i);continue;}
    if(padCapture.stale.has(i))continue;
    assignPad(padCapture.action,padCapture.index,i);
    return;
  }
  padWatch=requestAnimationFrame(watchPad);
}
// One button drives one action, exactly like a key: mapping a button that is
// already in use takes it away from whichever action held it.
function assignPad(action,index,button){
  const table=padTable(selectedPad);
  const takenFrom=[];
  for(const other of B.ACTIONS){
    if(other===action)continue;
    const buttons=table[other]||[];
    if(!buttons.includes(button))continue;
    table[other]=buttons.filter(entry=>entry!==button);
    takenFrom.push(B.actionMeta(other).label);
  }
  const buttons=table[action].slice();
  if(index<buttons.length)buttons[index]=button;else buttons.push(button);
  table[action]=buttons.filter((entry,position)=>buttons.indexOf(entry)===position).slice(0,B.MAX_PAD_BUTTONS);
  commit(`${B.padButtonLabel(button)} is now ${B.actionMeta(action).label}${takenFrom.length?` (taken from ${takenFrom.join(', ')})`:''}.`);
}
function clearPadKey(action,index){
  const table=padTable(selectedPad);
  const button=table[action][index];
  table[action]=table[action].filter((entry,position)=>position!==index);
  commit(`${B.padButtonLabel(button)} released from ${B.actionMeta(action).label}.`);
}
function engineMessage(message){
  const target=$('engine');
  if(!target||!target.contentWindow)return;
  try{target.contentWindow.postMessage(message,location.origin);}
  catch(error){try{target.contentWindow.postMessage(message,'*');}catch(again){/* the frame is gone */}}
}
function renderPorts(){
  const list=$('port-list');list.textContent='';
  const pads=gamepads();
  ports.forEach((entry,index)=>{
    const row=el('div','port-row');
    row.append(el('span','port-name',`Player ${index+1}`));
    const select=document.createElement('select');
    select.dataset.port=String(index);
    const options=[['auto','Automatic',null],['keyboard','Keyboard + mouse',{kind:'keyboard'}],['none','Closed',{kind:'none'}]];
    for(const pad of pads)options.push([padKey(pad),padLabel(pad),{kind:'gamepad',id:pad.id,index:pad.index}]);
    if(entry&&entry.kind==='gamepad'&&!pads.some(pad=>pad.id===entry.id))options.push([padKey(entry),`${padLabel(entry)} (not seen yet)`,entry]);
    for(const [value,label,plan] of options){
      const option=document.createElement('option');
      option.value=value;option.textContent=label;option.dataset.kind=plan?plan.kind:'auto';
      if(plan&&typeof plan.index==='number')option.dataset.index=String(plan.index);
      if(plan&&plan.id)option.dataset.id=plan.id;
      if(samePort(entry,plan))option.selected=true;
      select.append(option);
    }
    select.onchange=()=>{
      const chosen=select.selectedOptions[0];
      const kind=chosen?.dataset.kind||'auto';
      ports[index]=kind==='auto'?null:{kind,id:chosen.dataset.id,index:Number(chosen.dataset.index)||0};
      renderPorts();
      commitPorts();
    };
    row.append(select,el('span','port-live',livePort(index)));
    list.append(row);
  });
}
function samePort(entry,plan){
  if(!entry&&!plan)return true;
  if(!entry||!plan)return false;
  if(entry.kind!==plan.kind)return false;
  return entry.kind!=='gamepad'||(entry.id===plan.id&&entry.index===plan.index);
}
let livePorts=[];
function livePort(index){
  const entry=livePorts[index];
  if(!entry)return livePorts.length?'free':'—';
  if(entry.kind==='keyboard')return 'keyboard';
  if(entry.kind==='none')return 'closed';
  return entry.lost?'gamepad (unplugged)':'gamepad';
}
function commitPorts(){
  writeSaved(PORT_STORE,ports);
  const plan=portPlan();
  if(plan)engineMessage({type:'smash64:ports',ports:plan});
  setStatus('Player ports saved.');
}
// Pad tables compare by controller, sorted by id, because the plan's key order
// is an accident of which controller the player edited first.
function samePads(a,b){
  const mine=Object.keys(a||{}).sort();
  const theirs=Object.keys(b||{}).sort();
  if(mine.length!==theirs.length||mine.some((id,index)=>id!==theirs[index]))return false;
  return mine.every(id=>JSON.stringify((a||{})[id])===JSON.stringify((b||{})[id]));
}
function showEngineState(data){
  if(Array.isArray(data.ports))livePorts=data.ports;
  const kinds=livePorts.map((entry,index)=>`P${index+1} ${livePort(index)}`).join(' · ');
  const live=(data.bindings&&data.bindings.actions)?B.normalize(data.bindings.actions):null;
  const inSync=!!live&&JSON.stringify(live.actions)===JSON.stringify(controls.actions);
  // The engine reports the pad tables it adopted as well, so the line says
  // whether the controllers are playing the buttons this page saved.
  const padsInSync=!data.padBindings||samePads(data.padBindings.pads,controls.pads);
  $('ports-status').textContent=`Engine ${data.version||''} · ${kinds}${inSync&&padsInSync?' · controls in sync':' · controls differ'}`.trim();
  const keyboard=livePorts.findIndex(entry=>entry&&entry.kind==='keyboard');
  $('controls-scope').textContent=keyboard>=0?`PLAYER ${keyboard+1} · KEYBOARD`:'KEYBOARD · NO PORT';
  renderPorts();
}
window.addEventListener('message',event=>{
  const target=$('engine');
  if(!target||event.source!==target.contentWindow)return;
  if(event.data&&event.data.type==='smash64:state')showEngineState(event.data);
});
window.addEventListener('keydown',event=>{
  if(!capturing&&!padCapture)return;
  event.preventDefault();event.stopPropagation();
  if(event.repeat)return;
  const code=B.codeOf(event);
  if(code==='Escape'){cancelCapture();return;}
  // A gamepad capture is listening to the pad, not to the keyboard.
  if(!capturing)return;
  assign(capturing.action,capturing.index,code,B.printedOf(event));
},true);
// Whether a pointer event belongs to the editor itself. The path is captured as
// the event is dispatched, so it still names the row that was clicked even
// though starting a capture re-renders it (a detached target has no ancestors).
const inEditor=event=>(typeof event.composedPath==='function'?event.composedPath():[])
  .some(node=>node&&node.id==='controls');
document.addEventListener('mousedown',event=>{
  if(!capturing)return;
  // Clicks inside the editor are how a player picks another action to change.
  if(inEditor(event))return;
  event.preventDefault();event.stopPropagation();
  assign(capturing.action,capturing.index,'Mouse'+event.button,'');
},true);
window.addEventListener('contextmenu',event=>{if(capturing)event.preventDefault();},true);
document.addEventListener('click',event=>{
  if((capturing||padCapture)&&!inEditor(event))cancelCapture();
});
window.addEventListener('gamepadconnected',()=>{renderPorts();renderPads();});
window.addEventListener('gamepaddisconnected',()=>{renderPorts();renderPads();});
// Resetting the keys resets the keys. Every controller has a table of its own
// and a reset of its own below, so a player who mapped three controllers does
// not lose them by clearing a keyboard table they had stopped using.
$('bind-reset').onclick=()=>{
  const pads=controls.pads;
  controls=B.defaults();
  controls.pads=pads;
  commit('Keys reset to the defaults. Controller tables are untouched.');
};
// Resetting one controller drops its table rather than writing the shipped
// buttons back: a table we do not carry is the shipped one, on both sides.
// Nothing here touches `actions`, which is why the two resets stay separate.
$('pad-reset').onclick=()=>{
  if(!selectedPad)return;
  delete controls.pads[selectedPad];
  commit(`Reset ${selectedPad.slice(0,28)} to the shipped buttons.`);
};
renderControls();
renderPads();
renderPorts();
$('bind-status').textContent=summary();
