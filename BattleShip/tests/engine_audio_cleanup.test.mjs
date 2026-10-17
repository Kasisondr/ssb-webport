import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';

const html = await readFile(new URL('../web/index.html', import.meta.url), 'utf8');
const source = html.slice(html.indexOf('function releaseEngineAudio()'), html.indexOf('window.__engineManifest ='));
for (const shared of [false, true]) {
  test(`unloading disconnects SDL audio and ${shared ? 'preserves shared' : 'closes private'} context`, () => {
    let disconnected = 0, closed = 0;
    const timers = [], listeners = {};
    const node = { onaudioprocess() {}, disconnect() { disconnected++; } };
    const context = { state: 'running', close() { closed++; this.state = 'closed'; return Promise.resolve(); } };
    const audio = { scriptProcessorNode: node, silenceTimer: 42, silenceBuffer: {}, currentOutputBuffer: {} };
    const window = { Module: { SDL2: { audio, audioContext: context } }, parent: { __openSmashAudioContext: shared ? context : undefined } };
    vm.runInNewContext(source, { window, clearInterval: id => timers.push(id), addEventListener: (name, callback) => { listeners[name] = callback; } });
    listeners.beforeunload();
    listeners.pagehide();
    assert.equal(node.onaudioprocess, null);
    assert.equal(disconnected, 1);
    assert.equal(audio.scriptProcessorNode, undefined);
    assert.equal(audio.currentOutputBuffer, undefined);
    assert.equal(audio.silenceBuffer, undefined);
    assert.ok(timers.includes(42));
    assert.equal(closed, shared ? 0 : 1);
    assert.equal(window.__shellUnloading, true);
  });
}
