// clang++ -std=c++17 tests/mesh_cache.cpp third_party/meshoptimizer/{allocator,vcacheoptimizer}.cpp -o /tmp/mesh-cache-test
#include <array>
#include <cassert>
#include <random>
#include <cstdarg>
#include "../port/mesh_cache.cpp"
extern "C" void port_log(const char*, ...) {}
static std::vector<std::array<uint16_t,3>> Faces(const std::vector<uint16_t>& raw) {
    std::vector<std::array<uint16_t,3>> result;
    for (size_t i=0; i<raw.size(); i+=4) result.push_back({raw[i],raw[i+1],raw[i+2]});
    std::sort(result.begin(),result.end());
    return result;
}
int main() {
    setenv("SSB64_MESH_CACHE_ORDER","1",1);
    std::vector<std::array<uint16_t,3>> faces;
    for (unsigned y=0;y<20;++y) for(unsigned x=0;x<20;++x) {
        uint16_t a=y*21+x,b=a+1,c=a+21,d=c+1;
        faces.push_back({a,b,c}); faces.push_back({b,d,c});
    }
    std::mt19937 random(1234); std::shuffle(faces.begin(),faces.end(),random);
    std::vector<uint16_t> raw;
    for(auto face:faces) {raw.insert(raw.end(),face.begin(),face.end());raw.push_back(0xbeef);}
    auto original=raw;
    port_optimize_mesh_cache(raw.data(),faces.size(),441);
    assert(Faces(raw)==Faces(original)); // no drops, duplicates, winding or vertex changes
    for(size_t i=3;i<raw.size();i+=4) assert(raw[i]==0xbeef);
    assert(raw!=original); // scrambled input really exercises the optimizer
    auto valid=raw; raw[0]=500; auto invalid=raw;
    port_optimize_mesh_cache(raw.data(),faces.size(),441); assert(raw==invalid);
    raw=valid; setenv("SSB64_MESH_CACHE_ORDER","0",1);
    port_optimize_mesh_cache(raw.data(),faces.size(),441); assert(raw==valid);
    puts("PASS: mesh reordering preserves all oriented triangles, padding, invalid-input fallback and opt-out");
}
