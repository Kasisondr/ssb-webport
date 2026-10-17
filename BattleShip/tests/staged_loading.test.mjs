import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';

const html = await readFile(new URL('../web/index.html', import.meta.url), 'utf8');
const source = html.slice(html.indexOf('const stageCache ='), html.indexOf('\nvar Module ='));
function harness() {
  const files = new Map(), requests = [];
  const context = {
    window: {}, console: { warn() {} }, performance,
    Module: { __stageUrls: { '/a.bin': '/a', '/b.bin': '/b' } },
    FS: { analyzePath: path => ({ exists: files.has(path) }), mkdirTree() {}, writeFile: (path, bytes) => files.set(path, bytes) },
    fetch: url => new Promise((resolve, reject) => requests.push({ url, resolve, reject })),
  };
  vm.createContext(context);
  vm.runInContext(source, context);
  const succeed = (index, bytes = [7, 8]) => requests[index].resolve({ ok: true, arrayBuffer: async () => Uint8Array.from(bytes).buffer });
  return { context, files, requests, succeed };
}

test('demand joins an in-flight prefetch without blocking and stages bytes once ready', async () => {
  const { context: c, files, requests, succeed } = harness();
  c.prefetchStaged(['/a.bin']);
  let done = false;
  const staged = c.ensureStaged('/a.bin').then(value => { done = true; return value; });
  await new Promise(resolve => setTimeout(resolve, 10));
  assert.equal(done, false);
  assert.equal(files.size, 0);
  assert.equal(requests.length, 1);
  succeed(0);
  assert.equal(await staged, true);
  assert.deepEqual(Array.from(files.get('/a.bin')), [7, 8]);
  assert.equal(await c.ensureStaged('/a.bin'), true);
  assert.equal(requests.length, 1);
  assert.equal(c.window.__stageStats.async, 1);
});

test('completed prefetch is consumed without another request', async () => {
  const { context: c, requests, succeed } = harness();
  c.prefetchStaged(['/a.bin']);
  succeed(0);
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(await c.ensureStaged('/a.bin'), true);
  assert.equal(requests.length, 1);
  assert.equal(c.window.__stageStats.cached, 1);
});

test('failed requests can retry, unknown paths do not fetch, and stageNow shares demand loads', async () => {
  const { context: c, requests, succeed } = harness();
  const first = c.ensureStaged('/a.bin');
  requests[0].resolve({ ok: false, status: 503 });
  assert.equal(await first, false);
  const retry = c.ensureStaged('/a.bin');
  const boot = c.stageNow('/a.bin');
  assert.equal(requests.length, 2);
  succeed(1);
  assert.equal(await retry, true);
  assert.equal(await boot, true);
  assert.equal(await c.ensureStaged('/unknown'), false);
  assert.equal(requests.length, 2);
});
