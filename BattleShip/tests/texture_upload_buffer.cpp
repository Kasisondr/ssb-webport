#include "fast/texture_upload_buffer.h"
#include <cassert>
#include <cstdint>

int main() {
    Fast::TextureUploadBuffer buffer;
    assert(buffer.Size() == 0);
    assert(buffer.Ensure(32, 32));
    assert(buffer.Size() == 4096);
    auto* first = buffer.Data();
    first[4095] = 123;
    assert(buffer.Ensure(16, 16));
    assert(buffer.Data() == first);
    assert(buffer.Size() == 4096);
    assert(buffer.Data()[4095] == 123);
    assert(buffer.Ensure(512, 256));
    assert(buffer.Size() == 512 * 256 * 4);
    buffer.Data()[buffer.Size() - 1] = 45;
    assert(!buffer.Ensure(0, 32));
    assert(!buffer.Ensure(32, 0));
    assert(!buffer.Ensure(UINT32_MAX, UINT32_MAX));
    assert(!buffer.Ensure(8193, 1));
    assert(buffer.Size() == 512 * 256 * 4);
    assert(buffer.Ensure(8192, 1));
    assert(buffer.EnsureBytes(600000));
    assert(buffer.Size() == 600000);
    assert(!buffer.EnsureBytes(SIZE_MAX));
    assert(!buffer.EnsureBytes(0));
    buffer.Clear();
    assert(buffer.Size() == 0);
    assert(buffer.Ensure(8, 8));
    assert(buffer.Size() == 256);
}
