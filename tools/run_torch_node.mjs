// run_torch_node.mjs — run the packaged Torch wasm extractor under Node.
//
// Same code path the browser package uses (torch-worker.js): stage the recipe
// tree into MEMFS, call torch_extract_o2r with the player's ROM, then derive
// the port stages' CSS art. Node can host the module because the build is
// ENVIRONMENT_IS_NODE-aware and touches no DOM, which makes extraction easy to
// debug and diff without a browser.
//
// Usage: node tools/run_torch_node.mjs <rom> [out-dir] [--region us|eu]
import { readFileSync, writeFileSync, mkdirSync, readdirSync, existsSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const ENGINE = join(ROOT, 'BattleShip');
const args = process.argv.slice(2);
const romPath = args.find((a) => !a.startsWith('--'));
const outDir = args.filter((a) => !a.startsWith('--'))[1];
if (!romPath || !outDir) {
  console.error('usage: node tools/run_torch_node.mjs <rom> <out-dir>');
  process.exit(2);
}
const region = (args.find((a) => a.startsWith('--region')) || '').split('=')[1] || 'eu';

const createTorchModule = (await import(join(ENGINE, 'torch/build-wasm/torch.js'))).default;
const rom = new Uint8Array(readFileSync(romPath));
let lines = 0;
const Module = await createTorchModule({
  locateFile: (path) => join(ENGINE, 'torch/build-wasm', path),
  print: (text) => { lines += 1; console.log(text); },
  printErr: (text) => console.error(`stderr: ${text}`),
});
const FS = Module.FS;
FS.mkdirTree('/src');
FS.mkdirTree('/out');
FS.mkdirTree('/src/yamls/' + region);
FS.writeFile('/src/config.yml', new Uint8Array(readFileSync(join(ENGINE, 'config.yml'))));
const yamlDir = join(ENGINE, 'yamls', region);
for (const name of readdirSync(yamlDir)) {
  FS.writeFile(`/src/yamls/${region}/${name}`, new Uint8Array(readFileSync(join(yamlDir, name))));
}

const ptr = Module._malloc(rom.length);
Module.HEAPU8.set(rom, ptr);
const started = Date.now();
let rc;
try {
  rc = Module.ccall('torch_extract_o2r', 'number',
    ['number', 'number', 'string', 'string'], [ptr, rom.length, '/src', '/out']);
} finally {
  Module._free(ptr);
}
const archive = FS.readFile('/out/BattleShip.o2r');
mkdirSync(outDir, { recursive: true });
writeFileSync(join(outDir, 'BattleShip.o2r'), archive);
console.log(`rc=${rc} lines=${lines} bytes=${archive.length} ms=${Date.now() - started}`);
console.log(`wrote ${join(outDir, 'BattleShip.o2r')}`);

const ptr2 = Module._malloc(rom.length);
Module.HEAPU8.set(rom, ptr2);
let derived = -1;
try {
  derived = Module.ccall('torch_derive_stage_assets', 'number',
    ['number', 'number', 'string'], [ptr2, rom.length, '/out']);
} finally {
  Module._free(ptr2);
}
console.log(`stage assets derived: ${derived}`);
const pngDir = '/out/assets/css_icons';
if (existsSync(pngDir)) {
  mkdirSync(join(outDir, 'css_icons'), { recursive: true });
  for (const name of readdirSync(pngDir)) {
    writeFileSync(join(outDir, 'css_icons', name), FS.readFile(`${pngDir}/${name}`));
  }
  console.log(`css icons: ${readdirSync(pngDir).join(', ')}`);
}
