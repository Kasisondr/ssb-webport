// Compile with the normal port C++ include paths; this includes the real reader.
#include <cassert>
#include "../port/port_dl_ranges.cpp"
namespace Fast {
void RegisterDLBoundsCheck(DLBoundsCheckFn) {}
void RegisterAddressClassifier(AddressClassifierFn) {}
void RegisterDLRangeHooks(DLRangeRegisterFn, DLRangeUnregisterFn) {}
}
int main() {
    auto ptr = [](uintptr_t value) { return reinterpret_cast<void*>(value); };
    port_dl_range_register(ptr(100000), 100, "a");
    port_dl_range_register(ptr(300000), 100, "b");
    assert(port_dl_check_addr(0) == PORT_DL_UNKNOWN);
    assert(port_dl_check_addr(100001) == PORT_DL_IN_RANGE);
    assert(port_dl_check_addr(200000) == PORT_DL_UNKNOWN); // populate a gap
    assert(port_dl_check_addr(100100) == PORT_DL_WALKED_PAST); // same gap, different outcome
    assert(port_dl_check_addr(299999) == PORT_DL_UNKNOWN);
    assert(port_dl_check_addr(300001) == PORT_DL_IN_RANGE); // changes last hit
    assert(port_dl_check_addr(100100) == PORT_DL_UNKNOWN); // don't cache WALKED_PAST
    port_dl_range_register(ptr(200000), 100, "inside-gap");
    assert(port_dl_check_addr(200001) == PORT_DL_IN_RANGE); // invalidates negative cache
    port_dl_range_unregister(ptr(200000));
    assert(port_dl_check_addr(200001) == PORT_DL_UNKNOWN); // invalidates positive cache
    port_dl_range_register(ptr(100000), 150000, "resized");
    assert(port_dl_check_addr(200001) == PORT_DL_IN_RANGE);
    assert(port_dl_check_addr(250000) == PORT_DL_WALKED_PAST);
    assert(port_dl_check_addr(300000) == PORT_DL_IN_RANGE);
    port_dl_range_register(ptr(UINTPTR_MAX-100), 100, "top");
    assert(port_dl_check_addr(UINTPTR_MAX-1) == PORT_DL_IN_RANGE);
    assert(port_dl_check_addr(UINTPTR_MAX) == PORT_DL_WALKED_PAST);
    puts("PASS: gap cache preserves boundaries, last-hit semantics and registry invalidation");
}
