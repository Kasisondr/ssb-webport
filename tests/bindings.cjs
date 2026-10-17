// Changeable controls: the launcher's editor (web/bindings.js) and the engine
// shell's live map (BattleShip/web/index.html) are two copies of one contract.
// These tests keep them in step, and prove the plan the editor writes is the
// plan the engine actually plays with.
const {test}=require('node:test');const assert=require('node:assert/strict');const vm=require('node:vm');const fs=require('node:fs');const path=require('node:path');
const ROOT=path.join(__dirname,'..');
const SHELL=fs.readFileSync(path.join(ROOT,'BattleShip/web/index.html'),'utf8');
const LAUNCHER=fs.readFileSync(path.join(ROOT,'web/bindings.js'),'utf8');
const LAUNCHER_JS=fs.readFileSync(path.join(ROOT,'web/launcher.js'),'utf8');

// --- reading the two tables -------------------------------------------------
// Literal after `marker`, scanned to its matching bracket so a value containing
// braces cannot end it early. The engine's table is written as JSON for exactly
// this reason.
function literalAfter(source, marker) {
  const start = source.indexOf(marker);
  assert.ok(start >= 0, `${marker} not found`);
  const open = source.indexOf('{', start);
  const close = source.indexOf('[', start);
  const from = close >= 0 && (open < 0 || close < open) ? '[' : '{';
  const until = from === '[' ? ']' : '}';
  let depth = 0, quote = null;
  for (let i = source.indexOf(from, start); i < source.length; i++) {
    const ch = source[i];
    if (quote) { if (ch === '\\') i++; else if (ch === quote) quote = null; continue; }
    if (ch === '"' || ch === "'") { quote = ch; continue; }
    if (ch === from) depth++;
    else if (ch === until) { depth--; if (depth === 0) return source.slice(source.indexOf(from, start), i + 1); }
  }
  throw new Error(`unbalanced ${from} after ${marker}`);
}
const asJson = (literal) => JSON.parse(literal.replace(/'/g, '"'));
// Values read out of a VM belong to another realm, and deepStrictEqual compares
// prototypes, so hand the assertions plain host-realm copies.
const plain = (value) => JSON.parse(JSON.stringify(value));
const engineActions = () => asJson(literalAfter(SHELL, 'const ACTIONS ='));
const engineMaxKeys = () => Number(/const MAX_KEYS_PER_ACTION = (\d+);/.exec(SHELL)[1]);
const engineDefaults = () => JSON.parse(literalAfter(SHELL, 'const DEFAULT_BINDINGS ='));
const enginePadDefaults = () => JSON.parse(literalAfter(SHELL, 'const DEFAULT_PAD_BINDINGS ='));
const enginePadCaps = () => ({
  buttons: Number(/const MAX_BUTTONS_PER_ACTION = (\d+);/.exec(SHELL)[1]),
  pads: Number(/const MAX_PADS = (\d+);/.exec(SHELL)[1]),
  index: Number(/const MAX_BUTTON_INDEX = (\d+);/.exec(SHELL)[1]),
});
const launcher = () => { const context = { window: {} }; vm.runInNewContext(LAUNCHER, context); return context.window.Smash64Bindings; };

// --- gamepads ---------------------------------------------------------------
// A standard-shaped pad, with `down` listing the buttons that read as pressed.
const fakePad = (id, index, buttons, down = []) => ({
  id, index, connected: true, mapping: 'standard', axes: [0, 0, 0, 0],
  buttons: Array.from({ length: buttons }, (unused, i) => ({ pressed: down.includes(i), value: down.includes(i) ? 1 : 0 })),
});
// Leaves exactly the named buttons held, so a test never depends on what it
// pressed a moment ago.
const press = (pad, ...held) => {
  pad.buttons.forEach((button, i) => { button.pressed = held.includes(i); button.value = held.includes(i) ? 1 : 0; });
  return pad;
};
const bindSearch = (plan) => '?binds=' + encodeURIComponent(JSON.stringify(plan));

// --- running the engine's real controller block -----------------------------
// `globalHeap` models the build the shell ships against, whose glue keeps its
// memory views in module scope and publishes HEAP32 as a plain global rather
// than on Module; `Module.HEAP32` is the other form a build could publish.
function shell({ search = '', pads = [], globalHeap = false } = {}) {
  const start = SHELL.indexOf('window.controllerPorts = (() => {');
  const end = SHELL.indexOf('\n})();', start) + 7;
  assert.ok(start >= 0 && end > start, 'controllerPorts block not found');
  const handlers = {};
  const canvas = { addEventListener: () => {}, focus() {}, setPointerCapture() {} };
  const window = { addEventListener: (type, fn) => (handlers[type] ??= []).push(fn) };
  const document = { addEventListener: () => {}, hidden: false, getElementById: () => canvas };
  const heap = new Int32Array(16);
  const Module = globalHeap ? {} : { HEAP32: heap };
  const warned = [];
  vm.runInNewContext(SHELL.slice(start, end), { window, document, Module, heap, HEAP32: heap,
    navigator: { getGamepads: () => pads }, location: { search }, URLSearchParams,
    console: { log: () => {}, warn: (...args) => warned.push(args.join(' ')) } });
  const fire = (type, event) => { for (const fn of handlers[type] || []) fn(event); };
  return {
    pad: window.controllerPorts, heap, pads, warned,
    key: (code, down = true) => fire(down ? 'keydown' : 'keyup', { code, key: '', preventDefault() {} }),
    message: (data) => fire('message', { data, source: window }),
    plan: (actions) => search + '?binds=' + encodeURIComponent(JSON.stringify({ v: 1, actions })),
    // What the engine's own sampler reads for each of the four ports.
    live: () => {
      window.controllerPorts.readPorts(0);
      return [0, 1, 2, 3].map((port) => ({ kind: heap[port * 4], button: heap[port * 4 + 1],
                                          sx: heap[port * 4 + 2], sy: heap[port * 4 + 3] }));
    },
  };
}
const binds = (actions, search = '') => shell({ search: '?binds=' + encodeURIComponent(JSON.stringify({ v: 1, actions })) });

test('the engine and the launcher agree on the actions and their default keys', () => {
  const api = launcher();
  assert.deepEqual(engineActions(), plain(api.ACTIONS), 'action list');
  assert.deepEqual(engineDefaults(), plain(api.DEFAULTS), 'default key map');
  assert.equal(engineMaxKeys(), api.MAX_KEYS, 'key cap per action');
  const grouped = plain(api.GROUPS).flatMap(group => group.actions.map(entry => entry.action));
  assert.deepEqual(grouped.slice().sort(), plain(api.ACTIONS).slice().sort(), 'the editor shows every action exactly once');
  assert.equal(grouped.length, new Set(grouped).size, 'no action is listed twice');
});

test('every shipped binding survives both validators and reaches the engine', () => {
  const api = launcher();
  const defaults = plain(api.DEFAULTS);
  assert.deepEqual(plain(api.normalize(api.DEFAULTS).actions), defaults, 'the editor accepts its own defaults');
  const engine = binds(defaults);
  assert.deepEqual(plain(engine.pad.bindings().actions), defaults, 'the engine accepts the plan the editor writes');
  assert.deepEqual(plain(engine.pad.bindings().actions), engineDefaults(), 'and reads back what the shipped table holds');
});

test('the engine plays the remapped key and releases the one it replaced', () => {
  const engine = binds({ A: ['KeyQ'] });
  engine.key('KeyQ');
  assert.equal(engine.pad.sampleKeyboard().button, 0x8000, 'Q is now the attack button');
  engine.key('KeyQ', false);
  engine.key('KeyJ');
  assert.equal(engine.pad.sampleKeyboard().button, 0, 'the key attack left no longer presses anything');
  engine.key('KeyJ', false);
});

test('a plan that is missing, duplicated or malformed still leaves a playable pad', () => {
  const api = launcher();
  // Missing actions keep their shipped keys, so a partial plan cannot strand a player.
  const partial = binds({ A: ['KeyQ'] });
  assert.deepEqual(plain(partial.pad.bindings().actions.START), plain(api.DEFAULTS).START, 'unmentioned actions keep their defaults');
  partial.key('Enter');
  assert.equal(partial.pad.sampleKeyboard().button & 0x1000, 0x1000, 'start still works');
  // Junk values, repeats and overflow are dropped rather than trusted.
  const junk = binds({ A: ['KeyQ', 'KeyQ', '', 'no spaces here', 'x'.repeat(40), 'KeyW', 'KeyD', 'KeyE'] });
  assert.deepEqual(plain(junk.pad.bindings().actions.A), ['KeyQ', 'KeyW', 'KeyD', 'KeyE'], 'junk dropped, duplicates collapsed, four keys kept');
  // Unreadable plans fall all the way back instead of half-applying.
  for (const search of ['?binds=', '?binds=not json', '?binds=%5B1%2C2%5D', '?binds=null']) {
    const fallback = shell({ search });
    assert.deepEqual(plain(fallback.pad.bindings().actions), engineDefaults(), `${search} falls back to the shipped map`);
  }
  // A key claimed twice resolves the same way on both sides: the earlier action wins.
  const clash = binds(Object.fromEntries(Object.entries({ ...api.DEFAULTS, B: ['KeyJ'] })));
  clash.key('KeyJ');
  assert.equal(clash.pad.sampleKeyboard().button, 0x8000, 'the first action in engine order keeps the key');
});

test('WALK is remappable too, and the old modifier stops walking', () => {
  const engine = binds({ WALK: ['KeyC'] });
  engine.key('KeyD'); engine.key('KeyC');
  const walk = engine.pad.sampleKeyboard();
  assert.ok(walk.sx > 0 && walk.sx < 45, `holding C reduces the stick (got ${walk.sx})`);
  engine.key('KeyC', false); engine.key('AltLeft');
  assert.equal(engine.pad.sampleKeyboard().sx, 80, 'the modifier it replaced is no longer a walk key');
});

test('a live remap over postMessage reaches the running game', () => {
  const engine = shell();
  assert.deepEqual(plain(engine.pad.bindings().actions.A), engineDefaults().A);
  assert.equal(engine.pad.setBindings({ actions: { A: ['KeyP'] } }), true, 'the engine accepts a live plan');
  engine.key('KeyP');
  assert.equal(engine.pad.sampleKeyboard().button, 0x8000, 'P attacks after the update');
  engine.key('KeyP', false);
  assert.equal(engine.pad.setBindings('not a plan'), false, 'junk is refused');
  engine.message({ type: 'smash64:bindings', bindings: { actions: { A: ['KeyQ'] } } });
  engine.key('KeyQ');
  assert.equal(engine.pad.sampleKeyboard().button, 0x8000, 'the launcher channel applies the plan');
  assert.equal(engine.pad.setBindings({ actions: { A: ['KeyZ'] } }), true);
  engine.key('KeyP');
  assert.equal(engine.pad.sampleKeyboard().button, 0, 'the previous live key is released');
});

test('the engine and the launcher agree on the pad table and its limits', () => {
  const api = launcher();
  assert.deepEqual(enginePadDefaults(), plain(api.PAD_DEFAULTS), 'shipped gamepad button map');
  const caps = enginePadCaps();
  assert.equal(caps.buttons, api.MAX_PAD_BUTTONS, 'buttons per action');
  assert.equal(caps.pads, api.MAX_PADS, 'tables the plan may carry');
  assert.equal(caps.index, api.MAX_BUTTON_INDEX, 'highest button index a table may name');
  for (const [action, buttons] of Object.entries(plain(api.PAD_DEFAULTS))) {
    assert.ok(buttons.length <= api.MAX_PAD_BUTTONS, `${action} is within the per-action cap`);
    for (const button of buttons) {
      assert.ok(api.isButton(button), `${action} names a real button index (${button})`);
      assert.ok(api.padButtonLabel(button).length > 0, `button ${button} has a name a player can read`);
    }
  }
});

test('the sampler writes through whichever heap view the build publishes', () => {
  // The shell says "here are the four ports" by writing into the buffer the
  // C++ side points it at, so a shell that cannot find a heap view samples
  // nothing at all: every port reads as unplugged and no remap ever reaches the
  // game, whatever the map or the editor says.
  const pad = fakePad('pad', 0, 17);
  for (const globalHeap of [false, true]) {
    const engine = shell({ pads: [pad], globalHeap });
    const where = globalHeap ? 'the glue\'s own global' : 'Module';
    press(pad, 0);
    const live = engine.live();
    assert.equal(live[0].kind, 3, `a sampled port reaches the heap published on ${where}`);
    assert.equal(live[0].button, 0x8000, `and carries the action word (${where})`);
    press(pad);
    assert.equal(engine.live()[0].button, 0, `a released button clears it (${where})`);
  }
});

test('a pad table the editor writes is the table the engine plays', () => {
  const api = launcher();
  const pads = plain(api.normalizePads({ pad: api.PAD_DEFAULTS }));
  assert.deepEqual(pads.pad, plain(api.PAD_DEFAULTS), 'the editor accepts its own shipped table');
  const pad = fakePad('pad', 0, 17);
  const engine = shell({ search: bindSearch({ v: 1, actions: {}, pads }), pads: [pad] });
  assert.equal(engine.live()[0].kind, 3, 'the pad owns a port');
  press(pad, 0);
  assert.equal(engine.live()[0].button, 0x8000, 'and the shipped table still attacks with button 0');
});

test('a remapped pad button reaches the engine, and only on the pad it names', () => {
  const mine = fakePad('pad-a', 0, 17), other = fakePad('pad-b', 1, 17);
  // Button 8 is unmapped in the shipped table, so nothing but the remap can
  // answer for it.
  const engine = shell({ search: bindSearch({ v: 1, actions: {}, pads: { 'pad-a': { A: [8] } } }), pads: [mine, other] });
  assert.deepEqual(engine.live().map((port) => port.kind).slice(0, 2), [3, 3], 'both pads hold a port');
  press(mine, 8); press(other, 8);
  const remapped = engine.live();
  assert.equal(remapped[0].button, 0x8000, 'the remapped button attacks on the pad the table names');
  assert.equal(remapped[1].button, 0, 'while the other pad keeps the shipped mapping');
  press(mine, 0); press(other, 0);
  const swapped = engine.live();
  assert.equal(swapped[0].button, 0, 'and the button it replaced no longer attacks there');
  assert.equal(swapped[1].button, 0x8000, 'though it still does on the pad the table does not name');
});

test('a junk pad table falls back instead of stranding a player', () => {
  const pad = fakePad('pad', 0, 17);
  const table = { A: 'x', START: 'x', B: [99, -1, 1.5, '2'], Z: [6, 6], WALK: [9, 10, 11, 12, 13] };
  const engine = shell({ search: bindSearch({ v: 1, actions: {}, pads: { pad: table } }), pads: [pad] });
  press(pad, 0);
  assert.equal(engine.live()[0].button, 0x8000, 'an action we cannot read keeps its shipped button');
  press(pad, 9);
  assert.equal(engine.live()[0].button, 0x1000, 'so does start');
  press(pad, 6);
  assert.equal(engine.live()[0].button, 0x2000, 'duplicates collapse to one button');
  press(pad, 1);
  assert.equal(engine.live()[0].button, 0, 'and an action the player emptied stays empty');
  press(pad, 12);
  assert.equal(engine.live()[0].button & 0x0800, 0x0800, 'the first four of an over-long list drive the action');
});

test('a live pad table arrives over postMessage, and a plan without one leaves it alone', () => {
  const pad = fakePad('pad', 0, 17);
  const engine = shell({ pads: [pad] });
  press(pad, 0);
  assert.equal(engine.live()[0].button, 0x8000, 'boots on the shipped pad table');
  engine.message({ type: 'smash64:bindings', bindings: { v: 1, actions: {}, pads: { pad: { A: [8] } } } });
  press(pad, 8);
  assert.equal(engine.live()[0].button, 0x8000, 'the running game adopts the new table');
  // An older save, or an edit that only touched a key, carries no pad table and
  // must not wipe the controller's buttons.
  engine.pad.setBindings({ actions: { A: ['KeyQ'] } });
  press(pad, 8);
  assert.equal(engine.live()[0].button, 0x8000, 'a key-only plan leaves the pad table alone');
  assert.ok(plain(engine.pad.bindings().actions.A).includes('KeyQ'), 'and still applies the key map');
  engine.message({ type: 'smash64:bindings', bindings: { pads: 'nope' } });
  press(pad, 8);
  assert.equal(engine.live()[0].button, 0x8000, 'an unreadable table is refused, not half-applied');
  engine.message({ type: 'smash64:bindings', bindings: { pads: {} } });
  press(pad, 8);
  assert.equal(engine.live()[0].button, 0, 'a readable but empty table puts every controller back on the defaults');
  press(pad, 0);
  assert.equal(engine.live()[0].button, 0x8000);
});

test('a port plan leaves closed ports closed and keeps unlisted pads connected', () => {
  const pads = [{ id: 'pad-a', index: 0, connected: true }, { id: 'pad-b', index: 1, connected: true }];
  const named = shell({ search: '?ports=' + encodeURIComponent(JSON.stringify([{ kind: 'keyboard' }, { kind: 'none' }, null, null])), pads });
  const kinds = Array.from(named.pad.snapshot(), entry => entry && entry.kind);
  assert.equal(kinds[0], 'keyboard', 'the plan named the keyboard for port 1');
  assert.equal(kinds[1], 'none', 'an explicitly closed port stays closed');
  assert.deepEqual(kinds.slice(2), ['gamepad', 'gamepad'], 'a pad the plan did not name is not unplugged');
  // A live re-plan behaves the same way, so editing one port cannot drop the rest.
  const live = shell({ pads });
  live.pad.apply([{ kind: 'keyboard' }, null, null, null]);
  const after = Array.from(live.pad.snapshot(), entry => entry && entry.kind);
  assert.deepEqual(after.slice(0, 3), ['keyboard', 'gamepad', 'gamepad']);
  assert.equal(after[3], null, 'the last free port is left for a pad that shows up later');
});

test('the launcher hands the saved plan to the engine and keeps it after a remap', () => {
  assert.match(LAUNCHER_JS, /engineParams\.set\('binds'/, 'the plan travels in the engine URL');
  assert.match(LAUNCHER_JS, /engineParams\.set\('ports'/, 'so does the port layout');
  assert.match(LAUNCHER_JS, /type:'smash64:bindings'/, 'and a live remap goes over postMessage');
  assert.match(LAUNCHER_JS, /type:'smash64:ports'/);
  assert.match(LAUNCHER_JS, /writeSaved\(BINDING_STORE/, 'every change is saved for the next session');
  assert.match(SHELL, /listeners\.add\(postState\)/, 'the engine reports back what it is reading');
});

test('the launcher saves both tables in one plan and checks what the engine adopted', () => {
  assert.match(LAUNCHER_JS, /const planFor=source=>\(\{v:1,actions:source\.actions,pads:source\.pads\}\)/, 'one plan carries both tables');
  assert.match(LAUNCHER_JS, /engineParams\.set\('binds',JSON\.stringify\(planFor\(controls\)\)\)/, 'and is what the engine is booted with');
  assert.match(LAUNCHER_JS, /bindings:planFor\(controls\)/, 'a live edit re-sends the same plan');
  assert.match(LAUNCHER_JS, /if\(!controls\.pads\[id\]\)controls\.pads\[id\]=B\.padDefaults\(\)/, 'the first edit copies the shipped table');
  assert.match(LAUNCHER_JS, /delete controls\.pads\[selectedPad\]/, 'resetting a controller drops its table rather than restating the defaults');
  assert.match(LAUNCHER_JS, /data\.padBindings/, 'the editor reads back the pad tables the engine adopted');
  assert.match(SHELL, /padBindings: padBindingSpec\(\)/, 'which the state message carries');
  assert.match(SHELL, /setPadBindings\(data\.bindings && data\.bindings\.pads\)/, 'and the live channel applies');
});
// Reads what the launcher's handler does right after a selector it names.
const after = (source, needle, window = 300) => source.slice(source.indexOf(needle), source.indexOf(needle) + window);

test('each table has its own reset, and the keys reset spares the controllers', () => {
  // The two resets own different tables: clearing a keyboard a player stopped
  // using must not drop the controllers they mapped, and a controller reset
  // must not touch the keys.
  assert.ok(after(LAUNCHER_JS, "$('bind-reset').onclick").includes('controls.pads=pads;'),
    'the keys reset carries the saved controller tables across instead of dropping them');
  assert.ok(after(LAUNCHER_JS, "$('pad-reset').onclick").includes('delete controls.pads[selectedPad]'),
    'and the controller reset drops exactly the controller it names');
});
