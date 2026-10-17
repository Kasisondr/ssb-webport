#include <cstdint>
#include <cstdlib>
#include <vector>
#include <algorithm>
#include "port_log.h"
#include "../third_party/meshoptimizer/meshoptimizer.h"

// Cost for the actual display-list builder: each window discards all loaded
// vertices when the next triangle would exceed its 64-vertex capacity.
static size_t WindowVertexCount(const std::vector<unsigned int>& indices, size_t vertices) {
    std::vector<unsigned int> seen(vertices, 0);
    unsigned int window = 1, count = 0;
    size_t loaded = 0;
    for (size_t i = 0; i < indices.size(); i += 3) {
        unsigned int need = 0;
        for (size_t k = 0; k < 3; ++k) need += seen[indices[i+k]] != window;
        if (count + need > 64) { loaded += count; count = 0; ++window; }
        for (size_t k = 0; k < 3; ++k) {
            auto index = indices[i+k];
            if (seen[index] != window) { seen[index] = window; ++count; }
        }
    }
    return loaded + count;
}

extern "C" void port_optimize_mesh_cache(uint16_t* triangles, uint32_t triangleCount, uint32_t vertexCount) {
    // Reordering can change a few pixels at overlapping surfaces/MSAA edges.
    // Set SSB64_MESH_CACHE_ORDER=0 for source-order rendering. Visual, exact
    // pixel and semantic comparisons accompany the performance measurements.
    const char* setting = std::getenv("SSB64_MESH_CACHE_ORDER");
#ifdef __EMSCRIPTEN__
    if (setting && setting[0] == '0') return;
#else
    if (!setting || setting[0] != '1') return;
#endif
    if (!triangles || triangleCount < 2 || vertexCount == 0) return;
    std::vector<unsigned int> source(size_t(triangleCount) * 3);
    for (size_t i = 0; i < triangleCount; ++i) {
        for (size_t k = 0; k < 3; ++k) {
            auto index = triangles[i*4+k];
            if (index >= vertexCount) return;
            source[i*3+k] = index;
        }
    }
    std::vector<unsigned int> fifo(source.size()), adaptive(source.size());
    meshopt_optimizeVertexCacheFifo(fifo.data(), source.data(), source.size(), vertexCount, 64);
    meshopt_optimizeVertexCache(adaptive.data(), source.data(), source.size(), vertexCount);
    size_t originalCost = WindowVertexCount(source, vertexCount);
    size_t fifoCost = WindowVertexCount(fifo, vertexCount);
    size_t adaptiveCost = WindowVertexCount(adaptive, vertexCount);
    const auto& best = fifoCost < adaptiveCost ? fifo : adaptive;
    size_t bestCost = std::min(fifoCost, adaptiveCost);
    if (bestCost >= originalCost) return;
    // Preserve all oriented triangles and their vertex attributes. The fourth
    // u16 in each OSB triangle record is unused by the display-list builder.
    for (size_t i = 0; i < triangleCount; ++i)
        for (size_t k = 0; k < 3; ++k) triangles[i*4+k] = uint16_t(best[i*3+k]);
    port_log("MESH CACHE: %u triangles, window vertices %zu -> %zu\n", triangleCount, originalCost, bestCost);
}
