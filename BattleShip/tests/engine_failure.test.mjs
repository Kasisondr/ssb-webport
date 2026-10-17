import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';

const html = await readFile(new URL('../web/index.html', import.meta.url), 'utf8');
const source = html.slice(html.indexOf('window.__lastError = null;'), html.indexOf('// ---- stall watch'));
function harness() {
  const listeners = {};
  const status = { textContent: 'assets ready (cached)' };
  const window = { addEventListener: (name, handler) => { listeners[name] = handler; } };
  const context = vm.createContext({ window, document: { getElementById: () => status } });
  vm.runInContext(source, context);
  return { context, window, status, listeners };
}
test('wasm allocation rejection replaces the stale asset status', () => {
  const { listeners, status, window } = harness();
  listeners.unhandledrejection({ reason: new RangeError('WebAssembly.instantiate(): Out of memory: Cannot allocate Wasm memory for new instance') });
  assert.match(status.textContent, /Not enough browser memory/);
  assert.match(window.__lastError, /RangeError/);
});
test('runtime errors are visible and retain their diagnostic stack', () => {
  const { listeners, status, window } = harness();
  const error = new Error('table index is out of bounds');
  listeners.error({ error });
  assert.equal(status.textContent, 'Game failed: table index is out of bounds');
  assert.equal(window.__lastError, error.stack);
});
test('engine aborts are visible, while navigation failures are ignored', () => {
  const { context, status, window } = harness();
  vm.runInContext("reportEngineFailure('Could not download the game engine.')", context);
  assert.match(status.textContent, /Could not download/);
  window.__shellUnloading = true;
  vm.runInContext("reportEngineFailure('aborted fetch')", context);
  assert.match(status.textContent, /Could not download/);
});
