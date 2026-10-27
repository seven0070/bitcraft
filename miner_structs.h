/* Step 1 struct as supplied, tested 2026-10-26.
 * TEST RESULT: sizeof=112, align=1, NOT cache-aligned (112 mod 64 = 48),
 * and 32 bytes larger than a Bitcoin header (80 bytes).
 * Do NOT use this as a Bitcoin header buffer — it does not map to
 * version/prevhash/merkle/timestamp/bits/nonce, and packed align=1
 * forces unaligned access, which is slower, not faster, on x86.
 * Kept here for reference only, not used by live miners.
 */
#include <stdint.h>
#pragma pack(push, 1)
typedef struct {
    uint8_t  segment_1[32];
    uint8_t  junction;
    uint8_t  segment_2[79];
} __attribute__((packed)) AsicSpatialStructure_t;
#pragma pack(pop)
