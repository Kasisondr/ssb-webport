#pragma once

#include <cstddef>
#include <cstdint>
#include <vector>

namespace Fast {

// Reuse the largest decoded texture, rather than reserving 256 MiB for an
// 8192x8192 texture at renderer startup. Hi-res replacement uploads have their
// own buffers and do not need that space here.
class TextureUploadBuffer {
  public:
    bool Ensure(uint32_t width, uint32_t height) {
        // Preserve the renderer's 8K limit and bound the multiplication on
        // 32-bit targets. Invalid dimensions must never reach the decode loop.
        if (width == 0 || height == 0 || width > 8192 || height > 8192) return false;
        const size_t bytes = static_cast<size_t>(width) * height * 4;
        return EnsureBytes(bytes);
    }

    bool EnsureBytes(size_t bytes) {
        if (bytes == 0 || bytes > size_t{8192} * 8192 * 4) return false;
        if (bytes > mBytes.size()) mBytes.resize(bytes);
        return true;
    }

    uint8_t* Data() { return mBytes.data(); }
    size_t Size() const { return mBytes.size(); }
    void Clear() { std::vector<uint8_t>().swap(mBytes); }

  private:
    std::vector<uint8_t> mBytes;
};

} // namespace Fast
