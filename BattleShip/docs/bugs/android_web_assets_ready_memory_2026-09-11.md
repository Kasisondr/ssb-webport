# Android WebView stuck at assets ready

Reproduced on the connected Saga running Android 16, Jelly, and Android
WebView 152.0.7977.64 against smash.fun (engine package c1527d7384eb).

The archive was successfully read from IndexedDB. WebAssembly instantiation
then failed with `Out of memory: Cannot allocate Wasm memory for new instance`.
Both streaming and ArrayBuffer instantiation failed. The shell had no abort
handler, so its last status remained `assets ready (cached)`.

The build requested 512 MiB of initial linear memory. Reducing that to 256 MiB
allowed instantiation but exposed another allocation failure: renderer startup
allocated `min(8192, maxTextureSize)^2 * 4` bytes for its decode scratch buffer.
On this device that is 256 MiB, independent of the actual textures. The unchecked
malloc failure allowed the decode loop to write through null, corrupting the
Wasm heap and eventually trapping with `table index is out of bounds` in
`Interpreter::ImportTextureRgba16`.

## Changes

- Start Wasm memory at 256 MiB, retaining growth on demand.
- Allocate and reuse scratch storage for the largest texture actually decoded.
  Cover RGBA, IA, I, CI, raw-copy, and mask paths. Bound dimensions and raw-copy
  sizes; limit the final raw-copy chunk to its remaining bytes.
- Surface aborts, uncaught errors, rejected promises, and engine script download
  failures in the shell instead of leaving stale loading text.

## Validation

Tested the rebuilt local JS/Wasm and updated shell using CDP response overrides
on the physical phone. No production files were deployed. Selecting Marilyn
Monroe through the normal site launched a visible four-player match.

One 15-second gameplay sample at a 1280x960 canvas recorded:

- 903 completed game ticks, 60.07 ticks/second.
- Median tick interval 15.3 ms, p95 25.0 ms, maximum 37.5 ms.
- No intervals above 50 ms and no engine exception.
- Wasm heap capacity 256 MiB; sbrk high-water mark 70.29 MiB.
- Runtime initialization at 3.04 seconds after iframe navigation (cached ROM
  archive). This is runtime readiness, not a first-frame measurement.

Game ticks are simulation completions, not a measurement of displayed FPS.
This is a short smoke sample, not a sustained thermal/performance benchmark.

Also passed the native performance unit runner (DL ranges, mesh, and texture
buffer), the texture buffer test under ASan/UBSan, six JS shell/loading tests,
and the release Wasm build.

The renderer changes live in the libultraship submodule and must be included
alongside the parent build/shell changes when committing and packaging.

## Follow-up: game-frame restart allocation failure

The user hit the allocation error again after playing/changing matches. A full
page reload recovered, but reloading the engine frame with its SDL audio context
owned by the parent reproduced the failure. The Android WebView package reports
`primaryCpuAbi=armeabi-v7a`, so this device's browser also has limited address
space despite the phone having much more physical RAM.

The shell now explicitly disconnects SDL playback/capture processor nodes,
clears their callbacks and silence timers, and releases output buffers during
unload. It preserves a parent-owned audio context and closes a private one.
Five consecutive same-page engine starts using the shared context succeeded
on the phone with this change (256 MiB heap each), without forced collection.
The audio cleanup tests cover repeated unload events and shared/private ownership.
This is separate from the initial renderer scratch allocation fix above.

An additional packaged-engine check passed three consecutive shared-context
starts, and a touch-launched match also booted through the normal audio unlock
path. An experimental parent display pacer used in that check did not reliably
improve first-press hitches and was subsequently removed.

## Diagnostic-recorder interference found during follow-up

A later memory failure happened while the user changed fighters during a
movement recording. The temporary parent-page recorder retained the old
`Module.readPorts` callback, and its cleanup looked up the *current* iframe
rather than the recorded instance. That could keep old Wasm state alive and
restore an old callback into a replacement engine. The recorder was removed,
and a full page reload cleared its references. Its replacement installs and
cleans callbacks inside the engine realm on pagehide; the parent stores only
numeric samples. The repeated-start results above do not establish that all
memory failures are fixed; this tooling bug confounds earlier conclusions.
