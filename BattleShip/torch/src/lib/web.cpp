#ifdef __EMSCRIPTEN__
// web.cpp — Emscripten entry point for in-browser asset extraction.
//
// The standalone CLI (main.cpp) is compiled out under __EMSCRIPTEN__; the
// browser drives Torch through this single C export instead, mirroring
// BattleShip's Android bridge: construct a Companion over the ROM bytes,
// register factories via Init, then run Process manually (Init skips it on
// Emscripten so the caller controls when the heavy work happens).
//
// The source dir must hold config.yml + the recipe yamls; the destination
// dir receives the archive named by config.yml's output.binary. Both live in
// MEMFS — the caller stages them and reads the result back out.
#include "Companion.h"

#include <emscripten.h>
#include <spdlog/spdlog.h>

#include <atomic>
#include <cstdint>
#include <exception>
#include <string>
#include <vector>

#ifdef TORCH_WEB_STAGE_ASSETS
#include "stage_assets_derive.h"
#endif

extern "C" {

// Derive the port-added stages' CSS wallpaper/thumbnail PNGs into
// <dst_dir>/assets/css_icons/. Returns the number of stages derived, or -1
// when the module was built without the host derivation source.
EMSCRIPTEN_KEEPALIVE
int torch_derive_stage_assets(const uint8_t* rom, int rom_len, const char* dst_dir) {
#ifdef TORCH_WEB_STAGE_ASSETS
    try {
        return ssb64_derive_css_stage_assets(rom, (size_t)rom_len, dst_dir);
    } catch (const std::exception& e) {
        SPDLOG_ERROR("torch_derive_stage_assets: {}", e.what());
        return 0;
    }
#else
    (void)rom; (void)rom_len; (void)dst_dir;
    return -1;
#endif
}


// Returns 0 on success, 1 on a std::exception, 2 on an unknown exception.
// A recognised-but-unsupported ROM returns 0 with no archive written (Process
// logs the reason), so callers must also check the output file exists.
EMSCRIPTEN_KEEPALIVE
int torch_extract_o2r(const uint8_t* rom, int rom_len, const char* src_dir, const char* dst_dir) {
    Companion* instance = nullptr;
    try {
        std::vector<uint8_t> data(rom, rom + rom_len);
        instance = new Companion(std::move(data), ArchiveType::O2R, /*debug=*/false,
                                 /*modding=*/false, std::string(src_dir), std::string(dst_dir));
        Companion::Instance = instance;
        std::atomic<size_t> assetCount{ 0 };
        instance->Init(ExportType::Binary, assetCount);
        instance->Process(assetCount);
        Companion::Instance = nullptr;
        delete instance;
        return 0;
    } catch (const std::exception& e) {
        SPDLOG_ERROR("torch_extract_o2r: {}", e.what());
    } catch (...) {
        SPDLOG_ERROR("torch_extract_o2r: unknown exception");
        Companion::Instance = nullptr;
        delete instance;
        return 2;
    }
    Companion::Instance = nullptr;
    delete instance;
    return 1;
}

}
#endif
