# Native Smash 64 browser port

This project uses the decompiled Smash 64 game compiled to WebAssembly through the BattleShip source port. Game C/C++ executes directly; there is no N64 CPU interpreter, JIT, EmulatorJS, Mupen64Plus, or ROM execution in this native package. The ROM is used only to extract assets. Graphics use libultraship's Fast3D-to-WebGL2 renderer; audio and platform services use the native port's browser backends.

## ROM requirement

One US-code engine build now plays two ROM regions:

- **US v1.0** — SHA-1 `e2929e10fccc0aa84e5776227e798abc07cedabf` (`NALE`)
- **Europe (En,Fr,De)** — SHA-1 `6ee8a41fef66280ce3e3f0984d00b96079442fb9` (`NALP`)

The European build has no decompilation of its own, so its assets are extracted with the US code base. `tools/eu_reloc_map.py` recovers which EU reloc file id holds each US asset: the EU table carries **2149** files against the US **2132** (17 released-language variants inserted next to the files they localise), and the mapping is recovered by a monotone alignment over decompressed sizes and reloc-pointer fingerprints, then validated against both. `tools/generate_eu_recipe.py` turns that into `BattleShip/yamls/eu/` plus `BattleShip/torch/src/factories/ssb64/RelocEuFileMap.h`, so Torch extracts the European ROM under the engine's US resource names and translates external reloc references back into US file ids. Japanese ROMs are not handled this way: they need a JP engine build (`cmake -DSSB64_VERSION=jp`).

Once `BattleShip/web-dist/manifest.json` exists, double-click `Play.command` and choose your ROM. The launcher runs on http://127.0.0.1:8005, separate from the emulator launcher on port 8004.

## Running from a clone

`BattleShip/web-dist/` ships with the repo, so a clone is playable without a build: `python3 tools/serve.py --open` (or double-click `Play.command` on macOS), then choose a US v1.0 or European ROM in the launcher. To rebuild, point `SDK` in `tools/build.py` at an Emscripten checkout (with `emcmake`, CMake and Ninja) and keep the Python dependencies in `.venv`; a source change only reaches the browser once `tools/build.py` repackages `web-dist/`.

## KBM controls

WASD/arrows move; Space jumps; Enter starts/pauses; left click/J attacks/selects; right click/K is special/back; Shift or L shields; I is L on the N64 pad; E/middle click grabs; TFGH is the D-pad; Alt reduces stick magnitude for walking and precise aiming. The shell keeps the pointer visible and releases every held key on blur, tab hide, and pointer cancel, so a stuck button cannot survive a window switch.

Every one of those bindings is changeable from the launcher's **Your controls** panel: click a key, press the one you want, and the running game picks it up immediately. A physical key belongs to one action, so mapping one away takes it off whatever held it before; an action takes up to four keys, mouse buttons included; Escape cancels a capture and **Reset keys to defaults** restores the table above, leaving every controller's buttons alone. The editor labels each key with the character your own layout prints there, so a Dvorak player sees the letters actually under their fingers. Bindings are saved per browser under `smash64.native.bindings` in `web/bindings.js` — the editor's copy of the table the engine reads (`DEFAULT_BINDINGS` in `BattleShip/web/index.html`, one entry per N64 action plus `WALK` for the stick modifier). The launcher hands the saved plan to the engine as `?binds=<json>` and re-sends it over `postMessage` on every edit, so a remap never needs a reload, and `tests/bindings.cjs` fails if the two copies of that table drift apart.

**Gamepad buttons are changeable too, and per controller.** A connected pad gets its own row set in the same panel: click a button chip, then press the button you want on the pad itself (the editor watches the controller for the press; one already held when you click doesn't count). Each table is keyed by the browser's `Gamepad.id`, so a remap follows the controller you plug in rather than the port it happens to land on — two pads of one model share a table, because the browser gives us nothing finer than the id and the index changes every session. The shipped table is `DEFAULT_PAD_BINDINGS`: A, B, X/Y = C-up (jump), LB = L, RB and RT = R, LT = Z, Start, D-pad, right stick = C buttons. Nothing rebinds a stick — the left stick is the N64 stick and the right stick keeps its C buttons — but a button bound to a stick direction acts as a digital fallback that only applies while the analog stick is idle, and `WALK` is bindable here too, so an analog stick can still walk for precise aiming. **Reset this controller** drops one controller's table back to the shipped buttons without touching the keyboard, and **Reset keys to defaults** is scoped the other way, so neither button can throw away the other table. Both tables travel together in the same plan (boot `?binds=`, then the live `postMessage` on every edit), and the engine reports back the buttons it actually adopted, which is what the *Player ports* line means by "controls in sync".

## Native controller support

Gamepads feed the same 4-port native controller sampler as the keyboard, using the standard mapping in `BattleShip/web/index.html` (A/B, X/Y=C-up, LB=L, RB/RT=R, LT=Z, Start, D-pad, left stick, right stick=C). Every one of those buttons is remappable per controller from the launcher's **Your controls** panel. Ports are assigned so either device can be player 1:

- gamepads take ports 1..n in browser index order;
- the keyboard always holds a port, so a keyboard + mouse session needs no setup;
- a pad that shows up before the keyboard has been used takes port 1, because 1P mode is fixed to port 1 (the keyboard slides to the lowest free port);
- a disconnected pad leaves its port unplugged and takes it back on reconnect.

The launcher's **Player ports** panel overrides that per port: *Automatic* keeps the rules above, *Keyboard* or a detected gamepad pins the port, and *Closed* refuses it. A pad the plan does not name keeps playing (it takes the lowest free port), so editing one row never unplugs another controller, and a closed port stays closed across reconnections.

Online multiplayer is not implemented by this integration.

## Saves

Native SRAM is persisted per ROM region: the launcher passes `?savekey=` to the shell (`LOCAL_SRAM_RESTORE` in `tools/patch_browser.py`), and the shell restores that key and hands it to `port/port_save.cpp`, which persists under the same key. The US key stays `smash64.native.sram.us` so existing saves keep loading, and Europe gets its own key, so one region's save is never loaded by the other. The game keeps its original save structure.

## Source and rebuild

`BattleShip/` is the full native engine checkout, including pinned decomp, libultraship, and Torch submodules. Our browser shell changes live in `tools/patch_browser.py` (the source of truth for `BattleShip/web/index.html`) and the launcher is in `web/`. Edit game logic in `BattleShip/decomp/src/`, port rendering/platform features in `BattleShip/port/`, and the EU recipe with the two tools above.

The Emscripten SDK is reused from `../supersponge-web/vendor/emsdk`. Build dependencies are isolated in `.venv` (CMake, Ninja, PyYAML, Pillow).

```sh
.venv/bin/python tools/build.py                     # patch + engine + torch + package
.venv/bin/python tools/build.py --only torch,package # extractor/recipe change only
node --test tests/*.cjs             # unit suites (no browser)
node tests/e2e/launcher-browser.cjs  # E2E: needs Playwright, serve.py and a ROM
python3 tools/serve.py --open
```

The browser package includes the Torch WebAssembly asset extractor and the US and EU recipe metadata (`TORCH_REGIONS` in `BattleShip/scripts/package_web.sh`). Your ROM and derived assets are stored locally in browser IndexedDB. No ROM is distributed with the code. The launcher offers 320×240 through 1920×1440 render sizes.

## Provenance

- Native browser foundation: https://github.com/turtlesoupy/BattleShip at `81489fae817fc08cd4dbad43a61713db8339491e`, forked from https://github.com/JRickey/BattleShip
- Game decomp fork: `eddd0c9ba8ce0b9e80a225929ce466adc2e999fe`
- libultraship browser fork: `eb96ccd1059ce6a905b16e1f9884c51b22e85f35`
- Torch browser fork: `296f8abf1c543ebef936a6d3d661947b5ead30dd`

Retain upstream license files and notices. This integration does not claim authorship of the upstream source port.

The initial compiler audit of the separately supplied decompilation is retained under `build/compile-report.json`; `tools/prepare_source.py` and `tools/compile_game.py` reproduce it. The audit is not a full linked game build. The native engine uses BattleShip's already ported decomp fork instead, because it handles endian conversion, asset relocation, graphics and threading.
