import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';
const html = await readFile(new URL('../web/index.html', import.meta.url), 'utf8');
const source = html.slice(html.indexOf('window.controllerPorts = (() => {'), html.indexOf('// ---- on-demand roster staging'));
// The shell registers several listeners per event (held keys, prevent-default,
// release-on-blur), so the harness keeps them all and fires them in order.
function harness() {
  const events = {}, documentEvents = {}, canvasEvents = {}, pads = [];
  const listen = (store, type, callback) => { (store[type] ??= []).push(callback); };
  const canvas = { addEventListener: (type, callback) => listen(canvasEvents, type, callback),
    focus() {}, setPointerCapture() {} };
  const window = { addEventListener: (type, callback) => listen(events, type, callback) };
  const document = { hidden: false, addEventListener: (type, callback) => listen(documentEvents, type, callback),
    getElementById: () => canvas };
  const Module = { HEAP32: new Int32Array(16) };
  vm.runInNewContext(source, { window, document, Module, navigator: { getGamepads: () => pads },
    location: { search: '' }, URLSearchParams, localStorage: { getItem: () => null, setItem() {} },
    console: { log() {}, warn() {} } });
  const ports = window.controllerPorts;
  const fire = (store) => (type, event = {}) => {
    for (const callback of store[type] ?? []) callback({ preventDefault() {}, ...event });
  };
  return { ports, events, documentEvents, pads, document,
    fire: fire(events), fireDocument: fire(documentEvents),
    key: (code, down = true) => fire(events)(down ? 'keydown' : 'keyup', { code, key: '' }),
    sample() { ports.readPorts(0); return Array.from(Module.HEAP32.slice(0, 4)); } };
}
test('analog values override digital directions without losing action buttons', () => {
  const h = harness();
  h.key('KeyD'); h.key('KeyJ');
  assert.deepEqual(h.sample(), [2, 0x8000, 80, 0]);
  h.ports.setVirtualStick({ x: 24, y: -12 });
  assert.deepEqual(h.sample(), [2, 0x8000, 24, -12]);
  h.ports.setVirtualStick({ x: 0, y: 0 });
  assert.deepEqual(h.sample(), [2, 0x8000, 0, 0], 'center must not fall back to a held direction key');
  h.ports.setVirtualStick({ x: -24, y: 0 });
  assert.deepEqual(h.sample(), [2, 0x8000, -24, 0], 'a stale compatibility key must not oppose analog input');
  h.ports.setVirtualStick(null);
  assert.deepEqual(h.sample(), [2, 0x8000, 80, 0]);
});
test('the shell copies and bounds axes, and clears input on interruption', () => {
  const h = harness(); const axes = { x: 123, y: -200 };
  h.ports.setVirtualStick(axes); axes.x = 0;
  assert.deepEqual(h.sample(), [2, 0, 80, -80]);
  for (const release of [() => h.fire('blur'), () => h.fire('pagehide'), () => {
    h.document.hidden = true; h.fireDocument('visibilitychange');
  }]) {
    h.ports.setVirtualStick({ x: 40, y: 0 }); h.key('KeyD');
    release(); assert.deepEqual(h.sample(), [2, 0, 0, 0]);
  }
  h.ports.setVirtualStick({ x: NaN, y: Infinity });
  assert.deepEqual(h.sample(), [2, 0, 0, 0]);
});
test('virtual stick only affects the keyboard port, not physical gamepads', () => {
  const h = harness();
  h.pads.push({ id: 'pad', index: 0, connected: true, axes: [0, 0, 0, 0], buttons: [] });
  h.ports.apply([{ kind: 'gamepad', id: 'pad', index: 0 }]);
  h.ports.setVirtualStick({ x: -80, y: 80 });
  assert.deepEqual(h.sample(), [3, 0, 0, 0]);
});
