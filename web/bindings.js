// Changeable controls: the action list the launcher's control editor renders,
// and the key map it starts from.
//
// This is the launcher's half of one contract. The engine shell spells the same
// defaults out in its own DEFAULT_BINDINGS (BattleShip/web/index.html, generated
// by tools/patch_browser.py) and accepts a plan from this editor through
// ?binds= and through postMessage while the game runs. tests/bindings.cjs fails
// if the two copies ever drift apart, so the editor can never offer a key the
// engine does not understand.
//
// A binding names a PHYSICAL key (KeyboardEvent.code) or "Mouse<n>" — the same
// names the shell listens for — so a remap stays under the same finger on a
// Dvorak/AZERTY layout. The editor labels each key with the character the
// player's own layout prints there (see keyLabel), which is why the saved plan
// carries a `printed` table alongside the codes.
//
// The second half is the same contract for gamepads: PAD_DEFAULTS gives, per
// N64 action, the button indices of the standard gamepad mapping that drive it
// (the shell spells the same table out in its DEFAULT_PAD_BINDINGS). One table
// per pad, keyed by the browser's Gamepad.id, so a remap follows the controller
// and not the port it happened to land on.
(function (global) {
  'use strict';

  // Flat order matches the shell's action order. It only matters when two
  // actions somehow claim one key: first action wins. The editor removes the
  // duplicate instead, so the plan it writes is always unambiguous.
  const ACTIONS = ['A', 'B', 'Z', 'L', 'R', 'START',
                   'CUP', 'CDOWN', 'CLEFT', 'CRIGHT',
                   'DUP', 'DDOWN', 'DLEFT', 'DRIGHT',
                   'UP', 'DOWN', 'LEFT', 'RIGHT', 'WALK'];

  // The shipping layout: libultraship's defaults, plus the mouse buttons the
  // shell feeds into the same pad sampler. WALK is the port's walk-magnitude
  // modifier, not an N64 button. Keep in sync with the shell (tests/bindings.cjs).
  const DEFAULTS = {
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

  // How the editor groups the actions, and what each one does in Super Smash
  // Bros. (the pad word the engine reads, in the player's words).
  const GROUPS = [
    { id: 'stick', title: 'Movement', hint: 'N64 stick · use WALK for precise aiming',
      actions: [
        { action: 'UP', label: 'Up / aim up' },
        { action: 'DOWN', label: 'Down / aim down' },
        { action: 'LEFT', label: 'Left / aim left' },
        { action: 'RIGHT', label: 'Right / aim right' },
        { action: 'WALK', label: 'Walk / precise aim (hold)' },
      ] },
    { id: 'buttons', title: 'Buttons', hint: 'N64 A · B · Z · L · R · Start',
      actions: [
        { action: 'A', label: 'Attack / select' },
        { action: 'B', label: 'Special / back' },
        { action: 'Z', label: 'Grab' },
        { action: 'L', label: 'Shield (L)' },
        { action: 'R', label: 'Shield (R)' },
        { action: 'START', label: 'Start / pause' },
      ] },
    { id: 'cbuttons', title: 'C buttons', hint: 'Jumps',
      actions: [
        { action: 'CUP', label: 'Jump (C-up)' },
        { action: 'CDOWN', label: 'Jump (C-down)' },
        { action: 'CLEFT', label: 'Jump (C-left)' },
        { action: 'CRIGHT', label: 'Jump (C-right)' },
      ] },
    { id: 'dpad', title: 'D-pad', hint: 'Taunt',
      actions: [
        { action: 'DUP', label: 'Taunt (D-up)' },
        { action: 'DDOWN', label: 'Taunt (D-down)' },
        { action: 'DLEFT', label: 'Taunt (D-left)' },
        { action: 'DRIGHT', label: 'Taunt (D-right)' },
      ] },
  ];

  // --- gamepad buttons -------------------------------------------------------
  // The pad sibling of DEFAULTS. Values are button indices on the browser's
  // standard gamepad mapping, which is the mapping the shell samples: 0 is the
  // bottom face button an Xbox pad prints A on. The shipped table is the
  // shell's own DEFAULT_PAD_BINDINGS — libultraship's SDL defaults (A/B,
  // LB=L, RB/RT=R, LT=Z, Start, D-pad, right stick=C) plus X/Y=C-up and RB=R
  // for comfort. No stick is in here: a stick is an axis, so the left stick is
  // the N64 stick and the right stick keeps its C buttons whatever a player
  // does to the buttons.
  const PAD_DEFAULTS = {
    "A": [0], "B": [1], "Z": [6], "L": [4], "R": [5, 7], "START": [9],
    "CUP": [2, 3], "CDOWN": [], "CLEFT": [], "CRIGHT": [],
    "DUP": [12], "DDOWN": [13], "DLEFT": [14], "DRIGHT": [15],
    "UP": [], "DOWN": [], "LEFT": [], "RIGHT": [], "WALK": []
  };
  const MAX_PAD_BUTTONS = 4;   // buttons per action, the key cap's sibling
  const MAX_PADS = 16;         // saved pads; bounds the size of ?binds=
  const MAX_BUTTON_INDEX = 31; // highest button index a plan may name

  // Standard-mapping button names. Every browser models a pad with this layout,
  // so the index is what the engine samples while the name is what a player
  // reads; a Nintendo pad prints different letters on the same buttons, which
  // is why each chip also carries the index in its tooltip.
  const PAD_BUTTON_LABELS = {
    0: 'A', 1: 'B', 2: 'X', 3: 'Y', 4: 'LB', 5: 'RB', 6: 'LT', 7: 'RT',
    8: 'Back', 9: 'Start', 10: 'L3', 11: 'R3',
    12: 'D-pad up', 13: 'D-pad down', 14: 'D-pad left', 15: 'D-pad right',
    16: 'Guide', 17: 'Extra',
  };
  const padButtonLabel = (index) => PAD_BUTTON_LABELS[index] || `Button ${index}`;
  const isButton = (value) => Number.isInteger(value) && value >= 0 && value <= MAX_BUTTON_INDEX;

  // One pad's table, read exactly the way the key table is: a value that is not
  // a button index is dropped, duplicates collapse, the list is capped, and an
  // action we cannot read at all keeps the shipped buttons, so a corrupt table
  // can never leave a player unable to press start.
  function normalizePadActions(spec) {
    if (!spec || typeof spec !== 'object' || Array.isArray(spec)) return null;
    const actions = {};
    for (const action of ACTIONS) {
      const raw = spec[action];
      const buttons = [];
      if (Array.isArray(raw)) {
        for (const button of raw) {
          if (isButton(button) && !buttons.includes(button) && buttons.length < MAX_PAD_BUTTONS) buttons.push(button);
        }
      }
      actions[action] = Array.isArray(raw) ? buttons : PAD_DEFAULTS[action].slice();
    }
    return actions;
  }

  // Per-pad tables, keyed by the browser's Gamepad.id. Two pads of one model
  // report the same id and so share a table — which is what a player means by
  // "my controller" anyway, and the browser gives us nothing finer to key on
  // (the index changes every session). The container has no prototype, so a pad
  // that happens to call itself __proto__ still gets an entry of its own.
  function normalizePads(spec) {
    if (!spec || typeof spec !== 'object' || Array.isArray(spec)) return null;
    const pads = Object.create(null);
    let count = 0;
    for (const id of Object.keys(spec)) {
      if (typeof id !== 'string' || !id || id.length > 64) continue;
      const actions = normalizePadActions(spec[id]);
      if (!actions) continue;
      pads[id] = actions;
      if (++count >= MAX_PADS) break;
    }
    return pads;
  }

  function padDefaults() {
    const actions = {};
    for (const action of ACTIONS) actions[action] = PAD_DEFAULTS[action].slice();
    return actions;
  }

  const MAX_KEYS = 4;
  // Keys the browser names for us but that no player thinks of by that name.
  const KEY_LABELS = {
    Space: 'Space', Enter: 'Enter', NumpadEnter: 'Num Enter', Tab: 'Tab',
    Backspace: 'Backspace', Escape: 'Esc', CapsLock: 'Caps Lock',
    ShiftLeft: 'Shift (L)', ShiftRight: 'Shift (R)',
    ControlLeft: 'Ctrl (L)', ControlRight: 'Ctrl (R)',
    AltLeft: 'Alt (L)', AltRight: 'Alt (R)', AltGraph: 'AltGr', MetaLeft: 'Cmd (L)', MetaRight: 'Cmd (R)',
    ArrowUp: '↑', ArrowDown: '↓', ArrowLeft: '←', ArrowRight: '→',
    Insert: 'Insert', Delete: 'Delete', Home: 'Home', End: 'End',
    PageUp: 'Page Up', PageDown: 'Page Down',
    Backquote: '`', Minus: '-', Equal: '=', BracketLeft: '[', BracketRight: ']',
    Backslash: '\\', Semicolon: ';', Quote: "'", Comma: ',', Period: '.', Slash: '/',
    NumpadAdd: 'Num +', NumpadSubtract: 'Num -', NumpadMultiply: 'Num *',
    NumpadDivide: 'Num /', NumpadDecimal: 'Num .',
    Mouse0: 'Left click', Mouse1: 'Middle click', Mouse2: 'Right click',
    Mouse3: 'Mouse 4', Mouse4: 'Mouse 5',
  };

  // Physical codes the shell accepts: a few printable characters for
  // synthetic-key fallbacks, then the browser's own code names.
  const CODE = /^(?:Mouse[0-4]|[^\s"<>]{1,24})$/;
  const isCode = (value) => typeof value === 'string' && CODE.test(value);

  function defaults() {
    const actions = {};
    for (const action of ACTIONS) actions[action] = DEFAULTS[action].slice();
    return { v: 1, actions, printed: {}, pads: Object.create(null) };
  }

  // Anything that reaches the engine comes through here first: a saved plan can
  // be stale (an action that no longer exists), hand-edited, or truncated. An
  // action we cannot read falls back to the shipped keys rather than going
  // silently unmapped.
  function normalize(spec) {
    const source = spec && typeof spec === 'object' && spec.actions && typeof spec.actions === 'object'
      ? spec.actions : spec;
    if (!source || typeof source !== 'object' || Array.isArray(source)) return null;
    const actions = {};
    for (const action of ACTIONS) {
      const raw = source[action];
      const keys = [];
      if (Array.isArray(raw)) {
        for (const key of raw) if (isCode(key) && !keys.includes(key) && keys.length < MAX_KEYS) keys.push(key);
      }
      actions[action] = Array.isArray(raw) ? keys : DEFAULTS[action].slice();
    }
    const printed = {};
    const labels = spec && typeof spec.printed === 'object' && spec.printed ? spec.printed : {};
    for (const key of Object.keys(labels)) if (isCode(key) && typeof labels[key] === 'string') printed[key] = labels[key].slice(0, 3);
    // A plan with no pad table keeps none, rather than inventing one: the
    // engine holds the shipped buttons for a pad it has no entry for.
    return { v: 1, actions, printed, pads: normalizePads(spec && spec.pads) || Object.create(null) };
  }

  // What the player's keyboard prints on this key, if we know it; otherwise the
  // browser's own name for the code.
  function keyLabel(code, printed) {
    const shown = printed && printed[code];
    if (shown) return shown;
    if (KEY_LABELS[code]) return KEY_LABELS[code];
    const letter = /^Key([A-Z])$/.exec(code);
    if (letter) return letter[1];
    const digit = /^Digit([0-9])$/.exec(code);
    if (digit) return digit[1];
    if (/^Numpad[0-9]$/.test(code)) return 'Num ' + code.slice(6);
    return code;
  }

  // Physical code of a captured event. Real browsers always set `code`; the
  // fallback keeps synthetic events (tests, odd browsers) usable.
  function codeOf(event) {
    if (event && typeof event.code === 'string' && event.code) return event.code;
    const key = event && typeof event.key === 'string' ? event.key : '';
    if (key === ' ') return 'Space';
    if (key.length === 1) return /[a-z]/i.test(key) ? 'Key' + key.toUpperCase() : key;
    return key;
  }

  // The character this layout prints on the key: 'c' on Dvorak where QWERTY
  // prints 'j'. Only single-character keys have one worth showing.
  function printedOf(event) {
    const key = event && typeof event.key === 'string' ? event.key : '';
    return key.length === 1 && key !== ' ' ? key.toUpperCase() : '';
  }

  function actionMeta(action) {
    for (const group of GROUPS) for (const entry of group.actions) if (entry.action === action) return entry;
    return { action, label: action };
  }

  global.Smash64Bindings = { ACTIONS, GROUPS, DEFAULTS, PAD_DEFAULTS, MAX_KEYS, MAX_PAD_BUTTONS, MAX_PADS,
                              MAX_BUTTON_INDEX, isCode, isButton, padButtonLabel,
                              normalize, normalizePadActions, normalizePads, defaults, padDefaults,
                              keyLabel, codeOf, printedOf, actionMeta };
})(window);
