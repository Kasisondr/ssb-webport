// Build with port/staged_file.c and port/coroutine_emscripten.cpp under
// Emscripten (-sASYNCIFY=1 -sFORCE_FILESYSTEM=1), then run with Node.
#include "coroutine.h"
#include "staged_file.h"
#include <emscripten.h>
#include <assert.h>
#include <stdint.h>
#include <stdio.h>

extern "C" { uint32_t gPortProfSwaps = 0; }
static int completed = 0;

static void read_asset(void *) {
    int stack_value = 12345;
    FILE *file = port_fopen_staged("/delayed.bin", "rb");
    assert(file && fgetc(file) == 42);
    fclose(file);
    assert(stack_value == 12345);
    // Existing files must bypass JS, including the asynchronous boundary.
    file = port_fopen_staged("/delayed.bin", "rb");
    assert(file && fgetc(file) == 42);
    fclose(file);
    assert(port_fopen_staged("/missing.bin", "rb") == NULL);
    assert(port_fopen_staged("/rejected.bin", "rb") == NULL);
    port_coroutine_yield();
    assert(stack_value == 12345);
    completed++;
}

static void outer(void *) {
    auto *inner = port_coroutine_create(read_asset, nullptr, 65536);
    port_coroutine_resume(inner);
    assert(!port_coroutine_is_finished(inner));
    port_coroutine_resume(inner);
    assert(port_coroutine_is_finished(inner));
    port_coroutine_destroy(inner);
}

int main() {
    EM_ASM({
        globalThis.window = globalThis;
        window.ticks = 0;
        window.loads = 0;
        window.timer = setInterval(() => window.ticks++, 2);
        Module.ensureStaged = async (path) => {
            window.loads++;
            await new Promise(resolve => setTimeout(resolve, 30));
            if (path === '/missing.bin') return false;
            if (path === '/rejected.bin') throw new Error('expected test failure');
            FS.writeFile(path, new Uint8Array([42]));
            return true;
        };
    });
    port_coroutine_init_main();
    auto *fiber = port_coroutine_create(outer, nullptr, 65536);
    port_coroutine_resume(fiber);
    assert(port_coroutine_is_finished(fiber));
    port_coroutine_destroy(fiber);
    assert(completed == 1);
    EM_ASM({
        clearInterval(window.timer);
        if (window.ticks < 3 || window.loads !== 3) throw new Error('staging blocked or reloaded a cached file');
        console.log('PASS: nested fibers resume after async staging; event loop stays responsive');
    });
    return 0;
}
