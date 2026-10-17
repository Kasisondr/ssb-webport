import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';

const source = await readFile(new URL('../port/port.cpp', import.meta.url), 'utf8');
const start = source.indexOf('EM_ASYNC_JS(void, port_yield_for_catchup, (), {');
const body = source.slice(source.indexOf('{', start) + 1, source.indexOf('\n});', start));

test('catch-up yields to a browser task and reuses its channel without timer waits', async () => {
  const messages = [];
  let channels = 0;
  const context = vm.createContext({
    Module: {},
    MessageChannel: class {
      constructor() {
        channels++;
        this.port1 = {};
        this.port2 = { postMessage: () => messages.push(() => this.port1.onmessage()) };
      }
    },
    setTimeout() { throw new Error('Catch-up must not wait for a timer'); },
  });
  vm.runInContext('async function yieldFrame() {' + body + '\n}', context);
  let complete = false;
  const first = context.yieldFrame().then(() => { complete = true; });
  await Promise.resolve();
  assert.equal(complete, false);
  assert.equal(messages.length, 1);
  messages.shift()();
  await first;
  assert.equal(complete, true);
  const order = [];
  const second = context.yieldFrame().then(() => order.push(2));
  const third = context.yieldFrame().then(() => order.push(3));
  assert.equal(channels, 1);
  messages.shift()();
  await second;
  assert.deepEqual(order, [2]);
  messages.shift()();
  await third;
  assert.deepEqual(order, [2, 3]);
});
