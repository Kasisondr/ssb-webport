# Browser controller ports (gamepads + keyboard per N64 port)

Added 2026-09-01. The browser build routes each logical N64 port to a
device chosen by the web shell instead of libultraship's SDL auto-assign.

## Why

The game's own multiplayer logic keys everything off "is a controller
plugged into port N" (`osContGetQuery` errno / `OSContPad.errno`):
`mnPlayersVSUpdateGate` spawns and ejects the per-port hand cursor on the
VS character select every frame, `mnPlayersVSInitPlayer` closes a human
slot whose port has no pad, menus accept input from any connected port,
and `scmanager.c` sends you to the no-controller screen when none are.
The port previously hard-wired all four ports as connected
(`port/stubs/n64_stubs.c`), so the select screen always showed four
idle cursors and only port 1 (keyboard) ever moved. libultraship also
pins keyboard mappings to port 1, so a keyboard player could never be P2.

## Pieces

| Layer | File | Role |
|-------|------|------|
| Shell | `web/index.html` (`window.controllerPorts`) | Owns the port map. Reads `?ports=<json>` (the site's plan: per port `{kind:'gamepad',id,index}`, `{kind:'keyboard'}`, `{kind:'none'}` = explicitly closed, or `null` = free); without it auto-plans (gamepads by index, keyboard only when no gamepad). A plan that names only some ports leaves the rest automatic: `fillUnnamed` gives every live pad the plan does not mention the lowest free port, so editing one port never unplugs another controller. Handles `gamepadconnected`/`disconnected` (sticky: a lost pad leaves its port unplugged and takes it back on return; a new pad takes the lowest free port, never a closed one). `Module.readPorts(ptr)` fills 4 x `{kind, button, stick_x, stick_y}` int32 per game tick, through the wasm heap view it resolves itself (see below). `apply(plan)` swaps in a new plan live from the site's Advanced panel. |
| Shell | `web/index.html` (`DEFAULT_BINDINGS`, `setBindings`, `bindings`) | Owns the key map as data instead of the old `KEY_MAP` literal. Reads `?binds=<json>` (`{actions:{A:['KeyJ','Mouse0'],...}}`, one entry per N64 action plus `WALK`) and replaces it live from `postMessage` (`{type:'smash64:bindings'}`), reporting back `{type:'smash64:state'}` with the ports and bindings it is actually reading. |
| Shell | `web/index.html` (`DEFAULT_PAD_BINDINGS`, `setPadBindings`, `padBindings`) | The same contract for gamepad buttons, one table per pad keyed by `Gamepad.id`: `{pads:{'<id>':{A:[0],R:[5,7],...}}}` with button indices on the standard mapping. Travels inside the same `?binds=` plan, is replaced by the same `smash64:bindings` message (each table validated on its own, so an unreadable pad table still leaves the key map applied) and is reported back as `padBindings` in the state message. A pad with no table of its own plays the shipped buttons; the sticks are axes, not buttons, so they are not in the table. |
| Port | `port/web_input.cpp` | `port_input_apply_pads()` runs right after `osContGetReadData` in `syControllerReadDeviceData`: kind NONE → zeroed pad + `CONT_NO_RESPONSE_ERROR`; KEYBOARD and GAMEPAD → shell sample (the shell binds by physical `event.code` through the data table above, one entry per action; the launcher's editor labels each position with what the player's own layout prints there, and the site's tutorial does the same from `navigator.keyboard.getLayoutMap()` (Chromium; QWERTY caps elsewhere), so a Dvorak player keeps the home-row cluster and sees C V P G S). Also parks every SDL gamepad in every port's ignore set so SDL and the shell never both drive a port. `port_input_port_connected()` feeds `osContGetQuery`. No-op on native, when the shell is not engaged, and under `SSB64_REPLAY_PLAY`. |
| Game | `decomp/src/sc/scmanager.c` | `SSB64_BOOT_HUMANS=<1..4>`: ports below the count are human slots in the `SSB64_BOOT_BATTLE` preset (fkind -1 = live pick). Also disables the eval-only deviations (no items, CP tags) that `p2kind==0` used to imply. |
| Site | `pipeline/web-prototype` (`shared/controller-ports.js`, `src/gamepads.js`, `launch-options.js`, Advanced panel) | Detects pads, shows the header badge and the Input section at the top of Advanced: one dropdown per port (P1..P4) offering the keyboard and each connected controller, each device on one port at most, with unfillable ports disabled ("Connect a controller to enable"). Choices persist per port as `auto`/`none`/`keyboard`/`gamepad:<index>`; defaults put controllers first and the keyboard on P1 only when there is no controller. Emits the `ports` plan to the shell. **Double select**: with two or more human ports the roster grid collects one pick per port (tiles are stamped 1P/2P, a prompt says who is up, clicking a stamped tile takes it back), then boots straight into the match with `SSB64_BOOT_HUMANS=n`, humans on ports 1..n and CPUs filling the rest; extra humans' custom fighters ride the per-player `inject_player` rows. A launch without picks (VS Character Select boot mode) opens the in-game select with `SSB64_START_SCENE=16` instead. The How-to-play step accepts gamepad input and shows the pad's button names; the keyboard legend is the shell's `KEY_MAP` (J K L I O + WASD). |

## Gamepad → N64 mapping (standard layout)

Shipped (and now the contents of `DEFAULT_PAD_BINDINGS`): A=A, B=B,
X/Y=C-up (jump), LB=L, RB or RT=R, LT=Z, Start=Start, D-pad=D-pad,
right stick=C buttons (0.5 threshold), left stick=stick (radial deadzone
0.15, scaled to ±80). The buttons are data the player can change per
controller (see below); the two sticks stay on their axes, because a
stick is not a button. A button a player binds to a stick direction is
the digital fallback for that axis and only applies while the analog
stick is idle, so the stick always wins.

## Changeable controls (native launcher)

Added 2026-10-15. The native package's launcher is the site for this
build, so it owns the map the shell used to hard-code:

- `web/bindings.js` (launcher) holds `ACTIONS`, `DEFAULTS` and the
  editor's groups; `BattleShip/web/index.html` holds the same table as
  `DEFAULT_BINDINGS`. `tests/bindings.cjs` fails when they drift, and
  also proves the plan the editor writes is the plan the engine plays
  (validation, conflict order, `WALK`, the live `postMessage` path).
- The launcher's **Your controls** panel captures a physical
  `KeyboardEvent.code` (or `Mouse<n>`) per action, up to four per
  action, and takes a key away from whichever action held it before.
  `printed` records the character the player's layout shows, so the
  chips read correctly on Dvorak/AZERTY too.
- A remap is written to `localStorage` (`smash64.native.bindings`),
  pushed into the running game over `postMessage`, and handed to the
  next session as `?binds=`. The engine validates every value
  (`KEY_CODE`), drops duplicates, caps the list, and falls back to the
  shipped keys for an action it cannot read, so a corrupt plan can
  never leave a player unable to press start.
- `web/bindings.js` also holds `PAD_DEFAULTS` against the shell's
  `DEFAULT_PAD_BINDINGS`, one table per `Gamepad.id`, and the same
  panel edits them: a pad is captured by pressing its button, and a
  button already held when the capture starts is ignored until it is
  released. What a player picks is validated by the same rules
  (`Number.isInteger`, `0..MAX_BUTTON_INDEX`, no duplicates, four per
  action) and an action whose list cannot be read keeps the shipped
  buttons, so `pads` in a plan is as safe as `actions`. A table we do
  not carry is the shipped one on both sides — that is why **Reset
  this controller** deletes the entry instead of restating the
  defaults, and why the two reset buttons are scoped to their own
  table: **Reset keys to defaults** carries `controls.pads` across
  (`bind-reset` swaps in `B.defaults()` and puts the saved tables
  back) while **Reset this controller** drops one entry, so a player
  who mapped three pads cannot lose them by clearing a keyboard they
  had stopped using. It follows that a key-only plan (no `pads` key
  at all) leaves the controllers alone: `setPadBindings` refuses an unreadable table
  rather than treating it as empty, while a readable empty one
  (`{"pads":{}}`) does mean "every controller back to the shipped
  buttons".

## The heap handoff (why a sampler that writes nothing looks fine)

Added 2026-10-15. `port/web_input.cpp` hands the shell the address of its
`sSamples` buffer and the shell fills it through a 32-bit view of the wasm
heap. That view is the entire interface, and `readPorts` returning early
is silent: the port kinds stay `AUTO`, `port_input_apply_pads` leaves
libultraship's own pad data alone, and the game plays through SDL and its
built-in keyboard mappings. Everything upstream of it still looks
correct — `snapshot()` shows the plan, `bindings()` shows the player's
map, the editor says "controls in sync" — because the shell's own state
is not the game's input. A remap could therefore be verified as working
and never reach a single frame of gameplay.

The glue keeps its memory views in module scope and publishes only what
the build asks for (`-sEXPORTED_RUNTIME_METHODS=FS,callMain`), so
`Module.HEAP32` is undefined in this build and the shell's old guard
returned on the first tick of every session. `LOCAL_HEAP_VIEW` resolves
the view the build actually publishes: `Module.HEAP32` first, then the
glue's own `HEAP32` global, which stays live across heap growth because
the glue reassigns it before any tick can run. If a future build
publishes neither (a modularized glue behind an IIFE would do that), add
`HEAP32` to `EXPORTED_RUNTIME_METHODS`, relink, and keep the fallback.

Two tests hold this: `tests/bindings.cjs` runs the real sampler against
both forms (a global-only build and a `Module.HEAP32` build) and fails if
the rows stop reaching the heap, and `tests/e2e/launcher-browser.cjs`
captures the pointer the engine passes, remaps a key and a pad button in
the launcher, and reads the resulting four rows back out of the engine's
own buffer.

## Testing without hardware

Fake pads in the page or the engine iframe:

```js
navigator.getGamepads = () => pads;              // [{index,id,connected:true,mapping:'standard',buttons:[...17],axes:[0,0,0,0]}]
const e = new Event('gamepadconnected'); Object.defineProperty(e, 'gamepad', { value: pads[0] }); window.dispatchEvent(e);
```

`window.controllerPorts.snapshot()` in the iframe shows the live map;
`port_log` prints `web input owns routing (kinds a,b,c,d)` once engaged.

The same stub drives the pad editor: a pad injected into the
*launcher's* document appears in **Your controls → Gamepad buttons**,
and pressing one of its buttons while a chip is capturing is exactly
what a real controller would do. `tests/native-input.cjs` runs the
shipped sampler this way (the full default table, a per-pad remap, the
walk modifier, the digital stick fallback) and `tests/e2e/launcher-browser.cjs`
remaps a button in the real browser and reads the pad word the engine
produced from it.
