#include <cstdint>

struct Widget {
    int id;
};

uint32_t calculateWidgetChecksum(const Widget& w) {
    uint32_t acc = static_cast<uint32_t>(w.id);
    for (int i = 0; i < 8; ++i) {
        acc ^= static_cast<uint32_t>(w.id + i) * 0x9E3779B9u;
    }
    return acc;
}
