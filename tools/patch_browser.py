#!/usr/bin/env python3
"""Adapt the pinned source port's browser shell for the native (no-emulation) port.

This is the source of truth for every change we make to `BattleShip/web/index.html`:
the shell ships upstream, and the patch is applied at build time by tools/build.py.
Each edit is declared as an (upstream, patched) pair; the script first reverts any
of our own markers that are already in the file and then applies the pairs, so it
converges whether the checkout is pristine or already patched.

What it does, in order:
  * keeps the mouse cursor visible (there is no parent site's custom cursor),
  * makes KBM a first-class native controller: mouse buttons feed the same pad
    sampler the engine reads, Alt gives a walk-magnitude stick, and held keys are
    released on blur so a stuck button can never survive a tab switch,
  * assigns native controller ports so a keyboard-only session is player 1 and a
    pad the player picks up first takes port 1 too (1P mode is fixed to it),
  * makes the keyboard map changeable: the pad map becomes data (DEFAULT_BINDINGS)
    that the launcher's control editor replaces through ?binds= and re-sends over
    postMessage while the game runs (web/bindings.js is the editor's copy of that
    table; tests/bindings.cjs fails if the two drift),
  * makes the gamepad's buttons changeable too, per pad: the standard mapping
    becomes DEFAULT_PAD_BINDINGS, keyed by Gamepad.id, and travels in the same
    ?binds= plan (web/bindings.js holds the editor's copy),
  * hands the port sampler a real view of the wasm heap (LOCAL_HEAP_VIEW), so the
    samples it produces actually reach the game,
  * restores the game's SRAM from browser storage before main().
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / 'BattleShip/web/index.html'

# ---------------------------------------------------------------------------
# Shell edits: (upstream, patched)
# ---------------------------------------------------------------------------

CURSOR = (
    "  html.is-embedded, html.is-embedded body, html.is-embedded body * { cursor: none !important; }",
    "  html.is-embedded, html.is-embedded body, html.is-embedded body * { cursor: default !important; }",
)

ENGAGED = (
    "  let engaged = false;",
    "  let engaged = false;\n"
    "  // LOCAL_PAD_FIRST: true once a bound key is pressed, so a pad that appears\n"
    "  // before then can still claim port 1.\n"
    "  let keyboardUsed = false;",
)

PLAN = (
    """  // Default rules, matching the site's planControllerPorts
  // (shared/controller-ports.js) with every port on automatic.
  function plan(pads) {
    const next = [null, null, null, null];
    let n = 0;
    for (const g of pads.sort((a, b) => a.index - b.index)) {
      if (n < 4) next[n++] = padEntry(g);
    }
    if (n === 0) next[0] = { kind: 'keyboard' };
    return next;
  }

  function ensureSomeone() {
    if (!ports.some(isDevice)) {
      const slot = Math.max(0, freePort());
      ports[slot] = { kind: 'keyboard' };
    }
  }
""",
    """  // LOCAL_PORTS: gamepads take ports 1..n in index order and the keyboard
  // always holds a port too, so a keyboard + mouse session needs no setup and
  // both input methods work side by side in local multiplayer. Port 1 is the
  // one 1P mode is fixed to, so a pad the player reaches for *before* touching
  // the keyboard takes it over (see gamepadconnected). The site's
  // planControllerPorts (shared/controller-ports.js) still wins when the shell
  // is given ?ports=.
  function plan(pads) {
    const next = [null, null, null, null];
    let n = 0;
    for (const g of pads.sort((a, b) => a.index - b.index)) {
      if (n < 4) next[n++] = padEntry(g);
    }
    return next;
  }

  function mapKeyboard(slot) {
    if (slot < 0 || ports.some((p) => p && p.kind === 'keyboard')) return;
    ports[slot] = { kind: 'keyboard' };
  }

  function ensureSomeone() {
    // The keyboard is always mapped: the engine spawns one character-select
    // cursor per mapped port, and a KBM player must never have to claim one.
    if (!ports.some(isDevice)) mapKeyboard(0);
    mapKeyboard(freePort());
  }
""",
)

GAMEPAD_CONNECTED = (
    """    const slot = freePort();
    if (slot < 0) return;
    ports[slot] = padEntry(g);
    notify();
  });
""",
    """    // LOCAL_PAD_FIRST: a pad that shows up before the keyboard has been used
    // takes port 1 (1P mode is fixed to it); the keyboard slides to the lowest
    // free port so both devices stay playable.
    if (!keyboardUsed && !ports.some((p) => p && p.kind === 'gamepad') &&
        ports[0] && ports[0].kind === 'keyboard') {
      ports[0] = padEntry(g);
      mapKeyboard(freePort());
      notify();
      return;
    }
    const slot = freePort();
    if (slot < 0) return;
    ports[slot] = padEntry(g);
    notify();
  });
""",
)

BINDINGS = (
    """  // Keyboard -> N64 pad, resolved in JS. Binds by PHYSICAL key (event.code)
  // so the right-hand cluster stays under the fingers on every layout;
  // the site's tutorial labels each position with what that layout prints
  // there (Dvorak sees C V P G S where QWERTY sees J K L I O; Chromium only, QWERTY caps elsewhere). Mirrors
  // libultraship's defaults: WASD/arrows stick, J=A K=B L=Z I=L O=R,
  // Space/Enter=Start, U=C-up, TFGH=D-pad, Ctrl=A Alt=B Shift=Z.
  const KEY_MAP = {
    KeyJ: 'A', ControlLeft: 'A', ControlRight: 'A', KeyK: 'B', AltLeft: 'B', AltRight: 'B',
    KeyL: 'Z', ShiftLeft: 'Z', ShiftRight: 'Z', KeyI: 'L', KeyO: 'R',
    Space: 'START', Enter: 'START', NumpadEnter: 'START', KeyU: 'CUP',
    KeyT: 'DUP', KeyG: 'DDOWN', KeyF: 'DLEFT', KeyH: 'DRIGHT',
    KeyW: 'UP', ArrowUp: 'UP', KeyS: 'DOWN', ArrowDown: 'DOWN',
    KeyA: 'LEFT', ArrowLeft: 'LEFT', KeyD: 'RIGHT', ArrowRight: 'RIGHT',
  };
""",
    r"""  // Keyboard -> N64 pad, resolved in JS. Binds by PHYSICAL key (event.code)
  // so the right-hand cluster stays under the fingers on every layout; the
  // launcher's control editor labels each position with the character the
  // player's own layout prints there (Dvorak sees C V P G S where QWERTY
  // sees J K L I O). Mirrors libultraship's defaults — WASD/arrows stick,
  // J=A K=B L=Z I=L O=R, Space/Enter=Start, U=C-up, TFGH=D-pad — plus the
  // mouse buttons the shell feeds into the same pad sampler.
  //
  // LOCAL_KBM_MAP: the map is data, not code, so a player can change it. The
  // launcher's control editor owns the saved plan; it arrives here as
  // ?binds=<json> and is re-sent over postMessage when a key changes
  // mid-session, so a remap never needs a reload. web/bindings.js is the
  // editor's copy of the table below; tests/bindings.cjs fails if the two
  // ever drift apart.
  const ACTIONS = ['A', 'B', 'Z', 'L', 'R', 'START',
                   'CUP', 'CDOWN', 'CLEFT', 'CRIGHT',
                   'DUP', 'DDOWN', 'DLEFT', 'DRIGHT',
                   'UP', 'DOWN', 'LEFT', 'RIGHT', 'WALK'];
  const MODIFIERS = { WALK: true };  // WALK is the stick modifier, not a button
  const MAX_KEYS_PER_ACTION = 4;
  const DEFAULT_BINDINGS = {
    "A": ["KeyJ", "Mouse0"],
    "B": ["KeyK", "Mouse2"],
    "Z": ["KeyE", "Mouse1"],
    "L": ["KeyI"],
    "R": ["ShiftLeft", "ShiftRight", "KeyL"],
    "START": ["Enter", "NumpadEnter"],
    "CUP": ["Space", "KeyU"],
    "CDOWN": [],
    "CLEFT": [],
    "CRIGHT": [],
    "DUP": ["KeyT"],
    "DDOWN": ["KeyG"],
    "DLEFT": ["KeyF"],
    "DRIGHT": ["KeyH"],
    "UP": ["KeyW", "ArrowUp"],
    "DOWN": ["KeyS", "ArrowDown"],
    "LEFT": ["KeyA", "ArrowLeft"],
    "RIGHT": ["KeyD", "ArrowRight"],
    "WALK": ["AltLeft", "AltRight"]
  };
  const KEY_CODE = /^(?:Mouse[0-4]|[^\s"<>]{1,24})$/;
  const defaultsFor = (action) => DEFAULT_BINDINGS[action].slice();

  // A saved plan can be stale, hand-edited or truncated: a value that is not a
  // physical key code is dropped, and an action whose list we cannot read at
  // all falls back to its shipped keys, so a bad plan can never leave a player
  // unable to press start.
  function normalizeBindings(spec) {
    const source = spec && typeof spec === 'object' && spec.actions && typeof spec.actions === 'object'
      ? spec.actions : spec;
    if (!source || typeof source !== 'object' || Array.isArray(source)) return null;
    const actions = {};
    for (const action of ACTIONS) {
      const raw = source[action];
      const keys = [];
      if (Array.isArray(raw)) {
        for (const key of raw) {
          if (KEY_CODE.test(key) && !keys.includes(key) && keys.length < MAX_KEYS_PER_ACTION) keys.push(key);
        }
      }
      actions[action] = Array.isArray(raw) ? keys : defaultsFor(action);
    }
    return { v: 1, actions };
  }

  const parseBindPlan = (raw) => {
    if (typeof raw !== 'string' || !raw) return null;
    try { return JSON.parse(raw); } catch (e) { console.warn('controllerPorts: bad ?binds=', e); return null; }
  };

  let bindings = normalizeBindings(parseBindPlan(params.get('binds'))) || normalizeBindings(DEFAULT_BINDINGS);
  let KEY_MAP = {};
  let WALK_KEYS = [];
  let boundKeys = new Set();
  function rebuildKeyMap() {
    KEY_MAP = {};
    for (const action of ACTIONS) {
      if (MODIFIERS[action]) continue;
      for (const key of bindings.actions[action]) if (!(key in KEY_MAP)) KEY_MAP[key] = action;
    }
    WALK_KEYS = bindings.actions.WALK.slice();
    boundKeys = new Set([...Object.keys(KEY_MAP), ...WALK_KEYS]);
  }
  // The launcher's editor owns the saved plan; this is its live end. It also
  // reports the new map back (notify -> postState) so the editor shows what the
  // engine actually reads rather than what it hoped to write.
  function setBindings(spec) {
    const next = normalizeBindings(spec);
    if (!next) return false;
    bindings = next;
    rebuildKeyMap();
    notify();
    return true;
  }
  function bindingSpec() {
    const actions = {};
    for (const action of ACTIONS) actions[action] = bindings.actions[action].slice();
    return { v: 1, actions };
  }
  rebuildKeyMap();
""",
)

PAD_STATE = (
    "  const held = new Set();",
    """  // LOCAL_PAD_MAP: the buttons each pad drives, as data instead of a fixed
  // mapping. web/bindings.js holds the editor's copy of DEFAULT_PAD_BINDINGS
  // and tests/bindings.cjs fails if the two drift apart. A table is keyed by
  // Gamepad.id, so a remap follows the controller rather than the port it
  // happened to land on, and two pads of one model share a table — the browser
  // gives us no finer identity than the id (the index changes every session).
  const DEFAULT_PAD_BINDINGS = {
    "A": [0], "B": [1], "Z": [6], "L": [4], "R": [5, 7], "START": [9],
    "CUP": [2, 3], "CDOWN": [], "CLEFT": [], "CRIGHT": [],
    "DUP": [12], "DDOWN": [13], "DLEFT": [14], "DRIGHT": [15],
    "UP": [], "DOWN": [], "LEFT": [], "RIGHT": [], "WALK": []
  };
  const MAX_BUTTONS_PER_ACTION = 4;
  const MAX_PADS = 16;
  const MAX_BUTTON_INDEX = 31;
  const padDefaultsFor = (action) => DEFAULT_PAD_BINDINGS[action].slice();

  // Read the way the key table is: a value that is not a button index is
  // dropped, duplicates collapse, the list is capped, and an action we cannot
  // read at all keeps the shipped buttons.
  function normalizePadActions(spec) {
    if (!spec || typeof spec !== 'object' || Array.isArray(spec)) return null;
    const actions = {};
    for (const action of ACTIONS) {
      const raw = spec[action];
      const buttons = [];
      if (Array.isArray(raw)) {
        for (const button of raw) {
          if (Number.isInteger(button) && button >= 0 && button <= MAX_BUTTON_INDEX &&
              !buttons.includes(button) && buttons.length < MAX_BUTTONS_PER_ACTION) buttons.push(button);
        }
      }
      actions[action] = Array.isArray(raw) ? buttons : padDefaultsFor(action);
    }
    return actions;
  }

  function normalizePadBindings(spec) {
    if (!spec || typeof spec !== 'object' || Array.isArray(spec)) return null;
    const table = new Map();
    for (const id of Object.keys(spec)) {
      if (typeof id !== 'string' || !id || id.length > 64) continue;
      const actions = normalizePadActions(spec[id]);
      if (actions) table.set(id, actions);
      if (table.size >= MAX_PADS) break;
    }
    return table;
  }

  // Button index -> action for one pad. The sampler asks for this on every game
  // tick, so it is built once per table and rebuilt only when that table
  // changes. A saved table is always complete, so an action a player emptied
  // stays empty; only a pad we have no entry for falls back to the defaults.
  function buildPadMap(actions) {
    const map = new Map();
    for (const action of ACTIONS) {
      for (const button of actions[action]) if (!map.has(button)) map.set(button, action);
    }
    return map;
  }
  const defaultPadMap = buildPadMap(DEFAULT_PAD_BINDINGS);
  const parsedPlan = parseBindPlan(params.get('binds'));
  let padBindings = normalizePadBindings(parsedPlan && parsedPlan.pads) || new Map();
  let padMaps = new Map();
  function padMapFor(id) {
    const saved = padBindings.get(id);
    if (!saved) return defaultPadMap;
    let map = padMaps.get(id);
    if (!map) { map = buildPadMap(saved); padMaps.set(id, map); }
    return map;
  }
  // The live end of the editor's pad table. A plan that carries no pad table
  // leaves the current one alone, so remapping a key can never wipe a
  // controller's buttons.
  function setPadBindings(spec) {
    const next = normalizePadBindings(spec);
    if (!next) return false;
    padBindings = next;
    padMaps = new Map();
    notify();
    return true;
  }
  function padBindingSpec() {
    const pads = Object.create(null);
    for (const [id, actions] of padBindings) {
      const copy = {};
      for (const action of ACTIONS) copy[action] = actions[action].slice();
      pads[id] = copy;
    }
    return { v: 1, pads };
  }
  const held = new Set();""",
)

PAD_SAMPLE = (
    """  // Standard-mapping Gamepad -> N64 pad. Mirrors libultraship's SDL
  // defaults (A/B, LB=L, RT=R, LT=Z, Start, D-pad, right stick=C) plus
  // X/Y=C-up (jump) and RB=R (shield) for comfort.
  function sample(g) {
    const pressed = (i) => { const b = g.buttons[i]; return !!b && (b.pressed || b.value > 0.5); };
    const axis = (i) => { const v = g.axes[i]; return typeof v === 'number' ? v : 0; };
    let button = 0;
    if (pressed(0)) button |= BTN.A;
    if (pressed(1)) button |= BTN.B;
    if (pressed(2) || pressed(3)) button |= BTN.CUP;
    if (pressed(4)) button |= BTN.L;
    if (pressed(5) || pressed(7)) button |= BTN.R;
    if (pressed(6)) button |= BTN.Z;
    if (pressed(9)) button |= BTN.START;
    if (pressed(12)) button |= BTN.DUP;
    if (pressed(13)) button |= BTN.DDOWN;
    if (pressed(14)) button |= BTN.DLEFT;
    if (pressed(15)) button |= BTN.DRIGHT;
    const rx = axis(2), ry = axis(3);
    if (ry < -C_STICK_THRESHOLD) button |= BTN.CUP;
    if (ry > C_STICK_THRESHOLD) button |= BTN.CDOWN;
    if (rx < -C_STICK_THRESHOLD) button |= BTN.CLEFT;
    if (rx > C_STICK_THRESHOLD) button |= BTN.CRIGHT;
    let x = axis(0), y = axis(1);
    const len = Math.hypot(x, y);
    if (len < STICK_DEADZONE) { x = 0; y = 0; }
    else { const s = Math.min(1, (len - STICK_DEADZONE) / (1 - STICK_DEADZONE)) / len; x *= s; y *= s; }
    return { button, sx: Math.round(x * STICK_MAX), sy: Math.round(-y * STICK_MAX) };
  }
""",
    """  // Standard-mapping Gamepad -> N64 pad, with the buttons resolved through
  // the player's own table (see LOCAL_PAD_MAP). The two sticks are not
  // remappable and never were: a stick is an axis, so the left stick is the N64
  // stick and the right stick keeps its C buttons whatever a player does to the
  // buttons. A button bound to a stick direction is the digital fallback for a
  // pad with a broken stick, and only applies while the analog stick is idle,
  // so the stick always wins.
  function sample(g) {
    const map = padMapFor(g.id);
    const pressed = (i) => { const b = g.buttons[i]; return !!b && (b.pressed || b.value > 0.5); };
    const axis = (i) => { const v = g.axes[i]; return typeof v === 'number' ? v : 0; };
    let button = 0, dx = 0, dy = 0, walk = false;
    const count = (g.buttons && g.buttons.length) || 0;
    for (let i = 0; i < count; i++) {
      if (!pressed(i)) continue;
      const action = map.get(i);
      if (!action) continue;
      if (action === 'UP') dy += 1; else if (action === 'DOWN') dy -= 1;
      else if (action === 'LEFT') dx -= 1; else if (action === 'RIGHT') dx += 1;
      else if (action === 'WALK') walk = true;
      else button |= BTN[action];
    }
    const rx = axis(2), ry = axis(3);
    if (ry < -C_STICK_THRESHOLD) button |= BTN.CUP;
    if (ry > C_STICK_THRESHOLD) button |= BTN.CDOWN;
    if (rx < -C_STICK_THRESHOLD) button |= BTN.CLEFT;
    if (rx > C_STICK_THRESHOLD) button |= BTN.CRIGHT;
    let x = axis(0), y = axis(1);
    const len = Math.hypot(x, y);
    if (len < STICK_DEADZONE) { x = 0; y = 0; }
    else { const s = Math.min(1, (len - STICK_DEADZONE) / (1 - STICK_DEADZONE)) / len; x *= s; y *= s; }
    // WALK is the port's walk modifier here too, so a pad button can hold it.
    const walkScale = walk ? 0.42 : 1;
    if (x || y) {
      return { button, sx: Math.round(x * walkScale * STICK_MAX), sy: Math.round(-y * walkScale * STICK_MAX) };
    }
    const mag = walkScale * STICK_MAX / (dx && dy ? Math.SQRT2 : 1);
    return { button, sx: Math.round(Math.sign(dx) * mag), sy: Math.round(Math.sign(dy) * mag) };
  }
""",
)

HEAP_VIEW = (
    """  // Engine entry point: fill 4 x {kind, button, stick_x, stick_y} int32s.
  function readPorts(ptr) {
    if (!engaged) return;
    const H = Module.HEAP32;
    if (!H) return;
    const base = ptr >> 2;
""",
    """  // LOCAL_HEAP_VIEW: the glue hands this shell the pointer its C++ sample
  // buffer lives at, so writing through a 32-bit view of the wasm heap is how
  // every input in this document reaches the game. The glue keeps those views
  // in module scope and only publishes the ones the build asks it to
  // (CMakeLists exports FS,callMain), so `Module.HEAP32` alone is undefined
  // here and the sampler used to return before writing a single byte — the
  // ports then read as unplugged and the game played through its own SDL and
  // keyboard mappings instead. Ask for the view this build actually publishes:
  // the module first, then the glue's own global, which is live even after the
  // heap grows because the glue reassigns it before any tick can run. A missing
  // view means the engine is not up yet; the port keeps reading as unplugged
  // until it is.
  const heapView = () => {
    if (typeof Module !== 'undefined' && Module && Module.HEAP32) return Module.HEAP32;
    if (typeof HEAP32 !== 'undefined' && HEAP32) return HEAP32;
    return null;
  };

  // Engine entry point: fill 4 x {kind, button, stick_x, stick_y} int32s.
  function readPorts(ptr) {
    if (!engaged) return;
    const H = heapView();
    if (!H) return;
    const base = ptr >> 2;
""",
)

KEY_LISTENERS = (
    """  window.addEventListener('keydown', (e) => { held.add(keyName(e)); }, true);
  window.addEventListener('keyup', (e) => { held.delete(keyName(e)); }, true);
""",
    """  window.addEventListener('keydown', (e) => {
    const name = keyName(e);
    held.add(name);
    if (KEY_MAP[name]) keyboardUsed = true;
  }, true);
  window.addEventListener('keyup', (e) => { held.delete(keyName(e)); }, true);
  // LOCAL_KBM_INPUT: mouse state enters the same native controller sampler, so
  // left/right/middle click are A/B/Z on player 1 without any emulator layer.
  // boundKeys is rebuilt with the map, so a rebound key is still swallowed
  // before the browser can scroll or focus something with it.
  window.addEventListener('keydown', e => { if (boundKeys.has(e.code)) e.preventDefault(); }, true);
  document.getElementById('canvas').addEventListener('pointerdown', e => {
    if (e.pointerType !== 'mouse') return;
    e.preventDefault(); held.add('Mouse' + e.button);
    document.getElementById('canvas').setPointerCapture?.(e.pointerId);
    document.getElementById('canvas').focus();
  });
  window.addEventListener('pointerup', e => {
    if (e.pointerType === 'mouse') held.delete('Mouse' + e.button);
  });
  window.addEventListener('pointercancel', releaseKeyboard);
""",
)

STICK = (
    """    return { button, sx: virtualStick ? virtualStick.x : x * STICK_MAX,
                     sy: virtualStick ? virtualStick.y : y * STICK_MAX };""",
    """    // WALK is the port's walk modifier: a reduced stick magnitude still walks
    // in game while tap-and-hold reaches a full dash. It is remappable, so ask
    // the live map instead of naming a key.
    let walk = false;
    for (const key of WALK_KEYS) if (held.has(key)) { walk = true; break; }
    const magnitude = (walk ? 0.42 : 1) * STICK_MAX / (x && y ? Math.SQRT2 : 1);
    return { button, sx: virtualStick ? virtualStick.x : Math.round(x * magnitude),
                     sy: virtualStick ? virtualStick.y : Math.round(y * magnitude) };""",
)

FILL_HELPER = (
    """  // A plan from the site: keep the live state of pads we already track.
  function adopt(parsed) {
""",
    """  // LOCAL_PORTS_AUTO: a pad the plan does not name is not a pad the player
  // wants gone. An automatic port (or a plan that names only some ports) must
  // not unplug, or fail to show, a controller that is already connected, so
  // every live pad the plan leaves out takes the lowest free port. Closed
  // ports stay closed.
  function fillUnnamed(next, live) {
    for (const g of live.slice().sort((a, b) => a.index - b.index)) {
      if (next.some((p) => p && p.kind === 'gamepad' && p.id === g.id && p.index === g.index)) continue;
      const slot = next.findIndex((p) => p === null);
      if (slot < 0) break;
      next[slot] = padEntry(g);
    }
    return next;
  }

  // A plan from the site: keep the live state of pads we already track.
  function adopt(parsed) {
""",
)

INIT_FILL = (
    "    ports = Array.isArray(parsed) ? adopt(parsed) : plan(livePads());",
    "    ports = Array.isArray(parsed) ? fillUnnamed(adopt(parsed), livePads()) : plan(livePads());",
)

APPLY_FILL = (
    "    ports = adopt(parsed);",
    "    ports = fillUnnamed(adopt(parsed), livePads());",
)

MESSAGE_BRIDGE = (
    """  init();
  return {
    readPorts,
""",
    """  // LOCAL_KBM_MAP live channel: the launcher owns the saved controls, so it
  // re-sends a plan when the player edits a key mid-session, and this shell
  // reports back the ports, key map and per-pad button tables it is actually
  // reading. One message carries both tables, and each is validated on its own,
  // so a pad table the shell cannot read still leaves the key map applied.
  function postState() {
    try {
      if (window.parent && window.parent !== window) {
        window.parent.postMessage({ type: 'smash64:state', version: 'BUILD_VERSION',
                                    ports: snapshot(), bindings: bindingSpec(),
                                    padBindings: padBindingSpec() }, '*');
      }
    } catch (e) { /* nobody is listening */ }
  }
  window.addEventListener('message', (e) => {
    const data = e && e.data;
    if (!data || (window.parent && window.parent !== window && e.source !== window.parent)) return;
    if (data.type === 'smash64:bindings') {
      setBindings(data.bindings);
      setPadBindings(data.bindings && data.bindings.pads);
    }
    else if (data.type === 'smash64:ports') apply(data.ports);
  });
  listeners.add(postState);
  init();
  return {
    readPorts,
""",
)

EXPORT = (
    """    setVirtualStick,
    snapshot,""",
    """    setVirtualStick,
    releaseKeyboard,
    keyboardUsed: () => keyboardUsed,
    snapshot,
    // Changeable controls: the launcher reads and writes the live map through
    // these (see web/bindings.js for the editor's copy of the same table).
    setBindings,
    bindings: bindingSpec,""",
)

SAVE_AND_ENV = (
    """      // The ROM-derived archive is not part of the package: build it in the""",
    """      // LOCAL_ENV_FORWARD: any ?SSB64_* query parameter becomes an environment
      // variable for the port, so the engine's own diagnostics (SSB64_LOG_INFO,
      // SSB64_RENDER_DIAG, SSB64_DUMP_FILE_ID, ...) work from a URL without
      // editing the shell.
      if (typeof ENV !== 'undefined') {
        for (const [key, value] of params) if (key.startsWith('SSB64_')) ENV[key] = value;
      }

      // LOCAL_SRAM_RESTORE: restore the native game's SRAM file before main().
      // The key is namespaced per ROM region (?savekey=, set by the launcher)
      // and mirrored into globalThis so port_save.cpp's EM_JS persists the
      // save under the same key: a European save is never restored by the US
      // game, and vice versa.
      const saveKey = params.get('savekey') || 'smash64.native.sram.us';
      globalThis.__smash64SramKey = saveKey;
      if (typeof ENV !== 'undefined') ENV.SSB64_SAVE_PATH = '/ssb64_save.bin';
      const savedSram = localStorage.getItem(saveKey);
      if (savedSram) {
        const raw = atob(savedSram);
        FS.writeFile('/ssb64_save.bin', Uint8Array.from(raw, c => c.charCodeAt(0)));
      }

      // The ROM-derived archive is not part of the package: build it in the""",
)

# Earlier revisions of this script left a third state on disk (keyboard pinned
# to port 1, no keyboardUsed export). Fold those back to upstream too, so a
# checkout patched by an older build still converges to the current edits.
LEGACY_REVERTS = [
    # The pad button tables joined the state message, so the previous revision's
    # postState and its single-branch payload go back to upstream first.
    ("""  // LOCAL_KBM_MAP live channel: the launcher owns the saved controls, so it
  // re-sends a plan when the player edits a key mid-session, and this shell
  // reports back the ports and bindings that are actually live.
  function postState() {
    try {
      if (window.parent && window.parent !== window) {
        window.parent.postMessage({ type: 'smash64:state', version: 'BUILD_VERSION',
                                    ports: snapshot(), bindings: bindingSpec() }, '*');
      }
    } catch (e) { /* nobody is listening */ }
  }
  window.addEventListener('message', (e) => {
    const data = e && e.data;
    if (!data || (window.parent && window.parent !== window && e.source !== window.parent)) return;
    if (data.type === 'smash64:bindings') setBindings(data.bindings);
    else if (data.type === 'smash64:ports') apply(data.ports);
  });
  listeners.add(postState);
  init();
  return {
    readPorts,
""",
     """  init();
  return {
    readPorts,
"""),
    ("""      // LOCAL_SRAM_RESTORE: restore the native game's SRAM file before main().
      if (typeof ENV !== 'undefined') ENV.SSB64_SAVE_PATH = '/ssb64_save.bin';
      const savedSram = localStorage.getItem('smash64.native.sram.us');
      if (savedSram) {
        const raw = atob(savedSram);
        FS.writeFile('/ssb64_save.bin', Uint8Array.from(raw, c => c.charCodeAt(0)));
      }

""",
     ""),
    ("    const next = [{ kind: 'keyboard' }, null, null, null];\n    let n = 1;",
     "    const next = [null, null, null, null];\n    let n = 0;"),
    ("    setVirtualStick,\n    releaseKeyboard,\n    snapshot,",
     "    setVirtualStick,\n    snapshot,"),
    # The pad map became data (BINDINGS), so every region an earlier revision
    # patched in place is reverted to its upstream form first.
    ("""  // Space=C-up, Enter=Start, J/mouse-left=A, K/mouse-right=B, Shift=R, E/mouse-middle=Z.
  const KEY_MAP = {
    KeyJ: 'A', Mouse0: 'A', KeyK: 'B', Mouse2: 'B',
    KeyE: 'Z', Mouse1: 'Z', ShiftLeft: 'R', ShiftRight: 'R', KeyL: 'R', KeyI: 'L',
    Enter: 'START', NumpadEnter: 'START', Space: 'CUP', KeyU: 'CUP',
""",
     """  // Space/Enter=Start, U=C-up, TFGH=D-pad, Ctrl=A Alt=B Shift=Z.
  const KEY_MAP = {
    KeyJ: 'A', ControlLeft: 'A', ControlRight: 'A', KeyK: 'B', AltLeft: 'B', AltRight: 'B',
    KeyL: 'Z', ShiftLeft: 'Z', ShiftRight: 'Z', KeyI: 'L', KeyO: 'R',
    Space: 'START', Enter: 'START', NumpadEnter: 'START', KeyU: 'CUP',
"""),
    ("""  window.addEventListener('keydown', (e) => {
    const name = keyName(e);
    held.add(name);
    if (KEY_MAP[name]) keyboardUsed = true;
  }, true);
  window.addEventListener('keyup', (e) => { held.delete(keyName(e)); }, true);
  // LOCAL_KBM_INPUT: mouse state enters the same native controller sampler, so
  // left/right/middle click are A/B/Z on player 1 without any emulator layer.
  const boundKeys = new Set([...Object.keys(KEY_MAP), 'AltLeft', 'AltRight']);
  window.addEventListener('keydown', e => { if (boundKeys.has(e.code)) e.preventDefault(); }, true);
  document.getElementById('canvas').addEventListener('pointerdown', e => {
    if (e.pointerType !== 'mouse') return;
    e.preventDefault(); held.add('Mouse' + e.button);
    document.getElementById('canvas').setPointerCapture?.(e.pointerId);
    document.getElementById('canvas').focus();
  });
  window.addEventListener('pointerup', e => {
    if (e.pointerType === 'mouse') held.delete('Mouse' + e.button);
  });
  window.addEventListener('pointercancel', releaseKeyboard);
""",
     """  window.addEventListener('keydown', (e) => { held.add(keyName(e)); }, true);
  window.addEventListener('keyup', (e) => { held.delete(keyName(e)); }, true);
"""),
    ("""    // Alt is the port's walk modifier: a reduced stick magnitude still walks
    // in game while tap-and-hold reaches a full dash.
    const walk = held.has('AltLeft') || held.has('AltRight');
    const magnitude = (walk ? 0.42 : 1) * STICK_MAX / (x && y ? Math.SQRT2 : 1);
    return { button, sx: virtualStick ? virtualStick.x : Math.round(x * magnitude),
                     sy: virtualStick ? virtualStick.y : Math.round(y * magnitude) };
""",
     """    return { button, sx: virtualStick ? virtualStick.x : x * STICK_MAX,
                     sy: virtualStick ? virtualStick.y : y * STICK_MAX };
"""),
    ("    setVirtualStick,\n    releaseKeyboard,\n    keyboardUsed: () => keyboardUsed,\n    snapshot,\n    apply,",
     "    setVirtualStick,\n    snapshot,\n    apply,"),
    ("""  window.addEventListener('keydown', (e) => { held.add(keyName(e)); }, true);
  window.addEventListener('keyup', (e) => { held.delete(keyName(e)); }, true);
  // LOCAL_KBM_INPUT: Mouse state enters the same native controller sampler.
  const boundKeys = new Set([...Object.keys(KEY_MAP), 'AltLeft', 'AltRight']);
  window.addEventListener('keydown', e => { if (boundKeys.has(e.code)) e.preventDefault(); }, true);
  document.getElementById('canvas').addEventListener('pointerdown', e => {
    if (e.pointerType !== 'mouse') return;
    e.preventDefault(); held.add('Mouse' + e.button);
    document.getElementById('canvas').setPointerCapture?.(e.pointerId);
    document.getElementById('canvas').focus();
  });
  window.addEventListener('pointerup', e => held.delete('Mouse' + e.button));
  window.addEventListener('pointercancel', releaseKeyboard);
""",
     """  window.addEventListener('keydown', (e) => { held.add(keyName(e)); }, true);
  window.addEventListener('keyup', (e) => { held.delete(keyName(e)); }, true);
"""),
]

EDITS = [CURSOR, ENGAGED, PLAN, FILL_HELPER, INIT_FILL, APPLY_FILL, GAMEPAD_CONNECTED,
         BINDINGS, PAD_STATE, HEAP_VIEW, KEY_LISTENERS, STICK, PAD_SAMPLE, MESSAGE_BRIDGE,
         EXPORT, SAVE_AND_ENV]


def main():
    text = INDEX.read_text()
    # Revert our own edits first so the script converges from either state.
    for patched, upstream in LEGACY_REVERTS:
        text = text.replace(patched, upstream)
    for upstream, patched in EDITS:
        text = text.replace(patched, upstream)
    for upstream, patched in EDITS:
        if upstream not in text:
            raise SystemExit(f'patch_browser: anchor not found in {INDEX}:\n{upstream[:160]}')
        text = text.replace(upstream, patched)
    INDEX.write_text(text)
    print('Patched native browser shell:', INDEX)


if __name__ == '__main__':
    main()
