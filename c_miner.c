/* C real-block miner, algorithmic optimisation, no new hardware.
 *
 * What is optimised vs the Python miner (same CPU, same candidate):
 *  1. No Python loop overhead: no struct.pack, no hashlib object
 *     creation, no int() conversion per nonce. One tight C loop.
 *  2. OpenSSL SHA256, which uses SHA-NI on this AMD EPYC CPU when
 *     available (the Python miner also uses OpenSSL, but pays
 *     Python overhead on top of every call).
 *  3. Midstate: the first 64-byte block of the first SHA256
 *     (version + prevhash + first 28 bytes of merkle) is constant
 *     per template, so its compression is done once, not per
 *     nonce. Per nonce we only compress: second block of first
 *     SHA + single block of second SHA = 2 compressions instead
 *     of 3, a 33% saving in compression work, on top of (1).
 *
 * Midstate implementation: we use OpenSSL's low-level SHA256
 * context and copy it. SHA256_Init sets the initial state;
 * SHA256_Transform is not public in all OpenSSL versions, so
 * instead we do the standard trick: we cannot easily copy a
 * midstate with the public API alone, so this version does
 * the full double-SHA via SHA256() calls in C (still 3
 * compressions, but in C with SHA-NI, no Python overhead).
 * The midstate gain is therefore NOT claimed here — the gain
 * measured is C loop + SHA-NI vs Python loop. A future step
 * could add a hand-rolled SHA256 with explicit midstate for
 * a further ~33% — see README in code comments below.
 *
 * Safety, same as Python miner:
 *  - No auto-submit. If a hash meets target, print VALID_FOUND
 *    and exit 10, so a wrapper can stop and wait for go-ahead.
 *  - Coinbase / wallet are already in the merkle root supplied
 *    as an argument; this program never sees a private key.
 *
 * Usage:
 *   c_miner <version> <prevhash_hex> <merkle_hex> <timestamp>
 *           <bits> <target_hex_or_decimal> <seconds> [nonce_start]
 * Header is built exactly as in Python:
 *   version LE, prevhash LE (reversed bytes), merkle LE,
 *   timestamp LE, bits LE, nonce LE. Hash = double-SHA256,
 *   reversed, compared as big-endian integer to target.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <time.h>
#include <openssl/sha.h>

static int hexval(int c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}
static int hex_to_bytes(const char *hex, unsigned char *out, size_t n) {
    for (size_t i = 0; i < n; i++) {
        int hi = hexval((unsigned char)hex[2*i]);
        int lo = hexval((unsigned char)hex[2*i+1]);
        if (hi < 0 || lo < 0) return -1;
        out[i] = (unsigned char)((hi << 4) | lo);
    }
    return 0;
}
static void reverse_bytes(unsigned char *b, size_t n) {
    for (size_t i = 0; i < n/2; i++) {
        unsigned char t = b[i]; b[i] = b[n-1-i]; b[n-1-i] = t;
    }
}
/* Compare reversed hash (big-endian) to target given as 32-byte
 * big-endian array. Returns 1 if hash < target. */
static int hash_lt_target(const unsigned char *hash_rev, const unsigned char *target_be) {
    for (int i = 0; i < 32; i++) {
        if (hash_rev[i] < target_be[i]) return 1;
        if (hash_rev[i] > target_be[i]) return 0;
    }
    return 0; /* equal is not < */
}
/* Difficulty approximation: diff = network_difficulty * target / hash_value.
 * We compute it only for the best hash, in Python wrapper style, so
 * this program prints best hash and lets the caller compute diff.
 * Here we just track best by integer comparison (bytewise, since
 * hash_rev is big-endian, lexicographic == integer comparison). */
int main(int argc, char **argv) {
    if (argc < 8) {
        fprintf(stderr, "usage: %s version prevhash merkle timestamp bits target seconds [nonce_start]\n", argv[0]);
        return 2;
    }
    uint32_t version = (uint32_t)strtoul(argv[1], NULL, 0);
    unsigned char prev[32], merk[32];
    if (hex_to_bytes(argv[2], prev, 32) || hex_to_bytes(argv[3], merk, 32)) {
        fprintf(stderr, "bad hex\n"); return 2;
    }
    uint32_t ts = (uint32_t)strtoul(argv[4], NULL, 0);
    uint32_t bits = (uint32_t)strtoul(argv[5], NULL, 0);
    /* target: either 64-char hex (big-endian) or decimal string */
    unsigned char target[32];
    memset(target, 0, 32);
    if (strlen(argv[6]) == 64) {
        if (hex_to_bytes(argv[6], target, 32)) { fprintf(stderr, "bad target hex\n"); return 2; }
    } else {
        /* decimal -> big-endian bytes, via simple repeated division by 256 using string? */
        /* For our use target is always passed as hex from Python, so decimal path is not needed. */
        fprintf(stderr, "target must be 64-char hex\n"); return 2;
    }
    double seconds = atof(argv[7]);
    uint64_t nonce_start = (argc > 8) ? strtoull(argv[8], NULL, 0) : 0;
    uint64_t nonce_end = (argc > 9) ? strtoull(argv[9], NULL, 0) : 0xffffffffULL;
    int has_end = (argc > 9);

    reverse_bytes(prev, 32);
    reverse_bytes(merk, 32);

    unsigned char hdr[80];
    /* version LE */
    hdr[0] = version & 0xff; hdr[1] = (version >> 8) & 0xff; hdr[2] = (version >> 16) & 0xff; hdr[3] = (version >> 24) & 0xff;
    memcpy(hdr+4, prev, 32);
    memcpy(hdr+36, merk, 32);
    hdr[68] = ts & 0xff; hdr[69] = (ts >> 8) & 0xff; hdr[70] = (ts >> 16) & 0xff; hdr[71] = (ts >> 24) & 0xff;
    hdr[72] = bits & 0xff; hdr[73] = (bits >> 8) & 0xff; hdr[74] = (bits >> 16) & 0xff; hdr[75] = (bits >> 24) & 0xff;
    /* nonce at 76..79, updated per iteration */

    unsigned char best_rev[32];
    uint64_t best_nonce = 0;
    int have_best = 0;
    uint64_t count = 0;
    time_t t0 = time(NULL);
    double start = (double)t0;
    /* Use monotonic clock for elapsed */
    struct timespec ts0, tsn;
    clock_gettime(CLOCK_MONOTONIC, &ts0);
    for (uint64_t nonce = nonce_start; ; nonce++) {
        hdr[76] = nonce & 0xff; hdr[77] = (nonce >> 8) & 0xff; hdr[78] = (nonce >> 16) & 0xff; hdr[79] = (nonce >> 24) & 0xff;
        unsigned char h1[32], h2[32], hrev[32];
        SHA256(hdr, 80, h1);
        SHA256(h1, 32, h2);
        memcpy(hrev, h2, 32);
        reverse_bytes(hrev, 32);
        count++;
        if (!have_best || memcmp(hrev, best_rev, 32) < 0) {
            memcpy(best_rev, hrev, 32);
            best_nonce = nonce;
            have_best = 1;
        }
        if (hash_lt_target(hrev, target)) {
            char hex[65];
            for (int i = 0; i < 32; i++) sprintf(hex+2*i, "%02x", hrev[i]);
            hex[64] = 0;
            printf("VALID_FOUND nonce=%llu hash=%s count=%llu\n", (unsigned long long)nonce, hex, (unsigned long long)count);
            fflush(stdout);
            return 10;
        }
        if ((count & 0x7ffff) == 0) {
            clock_gettime(CLOCK_MONOTONIC, &tsn);
            double el = (tsn.tv_sec - ts0.tv_sec) + (tsn.tv_nsec - ts0.tv_nsec) / 1e9;
            if (el >= seconds) break;
        }
        if (has_end && nonce >= nonce_end) break;
        if (nonce == 0xffffffffULL) break;
    }
    clock_gettime(CLOCK_MONOTONIC, &tsn);
    double el = (tsn.tv_sec - ts0.tv_sec) + (tsn.tv_nsec - ts0.tv_nsec) / 1e9;
    (void)start; (void)t0;
    char hex[65];
    for (int i = 0; i < 32; i++) sprintf(hex+2*i, "%02x", best_rev[i]);
    hex[64] = 0;
    printf("hashed %llu in %.1f s = %.0f H/s\n", (unsigned long long)count, el, count / (el > 0 ? el : 1));
    printf("best nonce %llu\n", (unsigned long long)best_nonce);
    printf("best hash %s\n", hex);
    printf("meets target? False\n");
    return 0;
}
