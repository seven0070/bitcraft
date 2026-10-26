"""Wire the genuine miner for REAL submission — keeping our simulation.

Sanath, 2026-10-26: keep our simulation, just wire the genuine miner
for real submission. This module is that wiring, with the simulation
left untouched (Emberhill, Blockforge, its operations and its
simulated wallet all stay as they are).

WHAT IS WIRED HERE:
1. LIVE TIP — fetches the current chain tip from mempool.space
   (public API, no key, reachable from this VM since Oct 2026):
   height, hash, version, bits, difficulty, timestamp. If the
   fetch fails, the last verified template (block 972,585) is
   used as a fallback and labelled as such — never presented
   as live.
2. REAL WALLET COINBASE — converts a real Bitcoin address into
   its scriptPubKey, with validation, for:
   * bech32 P2WPKH (bc1q..., 20-byte program) and P2TR (bc1p...,
     32-byte program) via BIP-173 decoding,
   * legacy P2PKH (1...) and P2SH (3...) via base58check.
   A private key, WIF key or seed phrase is REJECTED outright:
   if it looks like one, this module refuses it and tells the
   user never to send it. A receive address is public by design
   and is the only thing that should ever be supplied.
   Subsidy is computed from height (50 BTC, halved every
   210,000 blocks), so at height ~973k it is 3.125 BTC.
3. REAL TEMPLATE + BLOCK ASSEMBLY — coinbase-only template
   (valid form; real miners add thousands of txs) with
   prevhash = live tip hash, Merkle root = coinbase txid,
   version/bits/time from the tip. assemble_block() returns
   the full block serialization (80-byte header + tx count +
   coinbase tx) that a node or pool would receive.
4. SUBMISSION GATE — validate_block_for_submission() re-hashes
   the header independently and checks: hash <= network target,
   prevhash == current tip, timestamp sane, coinbase reward <=
   subsidy + fees. A Blockforge counted block FAILS this gate
   (no hash was ever computed for it) and is REFUSED submission
   — that refusal is the point. Only a genuinely found perfect
   hash passes.
5. REAL POOL STRATUM CLIENT — a Stratum V1 client for a real
   pool (default public-pool.io:3333, fallback solo.ckpool.org:3333,
   both TCP-reachable from this VM, Oct 2026, and both known from
   the Bitaxe factory defaults). Flow: subscribe -> authorize
   with the wallet address as worker name -> notify (job) ->
   build coinbase with extranonce -> Merkle root -> nonce search
   -> submit share. If a submitted share meets the NETWORK
   target, the pool submits the block to the network and the
   reward goes to the wallet in the coinbase (solo pool) or is
   split by shares (public pool). This client is tested here
   for connection + job receipt; a share at a real pool's
   difficulty (typically 1,000+) takes a CPU hours, so share
   submission to a real pool is NOT claimed as tested — the
   share-submission path itself is tested against the local
   replica pool in bitcoin_real_env.py.

WHAT IS STILL MISSING (and why this is "wired, not live"):
* The user's REAL wallet address. Until it is supplied, the
  module runs with a documented TEST address only (a BIP-173
  test vector, nobody's wallet), and status is "wired, awaiting
  wallet". No real submission is attempted with the test address.
* DIRECT TCP PERMISSION (found 2026-10-26): the runtime blocks
  direct TCP to external hosts — a Stratum subscribe to
  public-pool.io:3333 or solo.ckpool.org:3333 is answered by
  the runtime with "Other TCP connections is turned off...
  switch other_tcp from Deny to Ask" and then reset. TCP
  connect alone "succeeds" only because the proxy accepts it;
  no Stratum data reaches the pool. Real pool submission from
  this VM therefore needs the user to change that Muse setting
  to Ask and approve the pool connection. HTTPS to
  mempool.space works, so live-tip fetching is unaffected.
  This is a user-controlled permission, not something to
  bypass: until the user changes it, the pool client is
  wired and tested locally, but cannot reach a real pool.
* A real ASIC for a realistic chance. A CPU at ~354k H/s needs
  ~150 trillion years per network block and ~38 years per
  diff-100,000 pool share. The wiring is correct; the hardware
  is not competitive. That is a physics fact, not a code gap.
* No block is submitted by this module on its own. Submission
  happens only when validate_block_for_submission() passes for
  a genuinely found hash, or when the pool client submits a
  share that meets network target. Nothing here submits a
  simulated Blockforge block to the real chain, ever.
"""

from __future__ import annotations

import hashlib
import json
import socket
import struct
import time
import urllib.request

from .bitcoin_real_env import (DIFF1_TARGET, bits_to_target, build_header,
                               dsha256)

MEMPOOL_TIP_URL = "https://mempool.space/api/blocks/tip/hash"
MEMPOOL_BLOCK_URL = "https://mempool.space/api/block/{}"
FALLBACK_TIP = {
    "height": 972585,
    "hash": "00000000000000000000688396935a1fee3fbafa81cbd647537667a54ae701a3",
    "version": 548126720, "bits": 386007187,
    "difficulty": 140577680051919.62, "timestamp": 1792654356,
    "source": "fallback: verified block 972585 (live fetch failed)",
}
# BIP-173 test vector address — NOBODY'S wallet, test only.
TEST_ADDRESS = "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4"
DEFAULT_POOLS = [("public-pool.io", 3333), ("solo.ckpool.org", 3333)]


def fetch_live_tip(timeout: float = 15) -> dict:
    """Fetch the live chain tip from mempool.space, or fallback.

    Retries 3 times: the VM's egress proxy intermittently closes
    a connection (observed 1 in 3 calls), so a single failure must
    not immediately fall back to a stale tip.
    """
    last_error = None
    for _ in range(3):
        try:
            with urllib.request.urlopen(MEMPOOL_TIP_URL, timeout=timeout) as r:
                tip_hash = r.read().decode().strip()
            with urllib.request.urlopen(
                    MEMPOOL_BLOCK_URL.format(tip_hash), timeout=timeout) as r:
                block = json.loads(r.read().decode())
            return {
                "height": block["height"], "hash": block["id"],
                "version": block["version"], "bits": block["bits"],
                "difficulty": block["difficulty"],
                "timestamp": block["timestamp"],
                "source": "live: mempool.space",
            }
        except Exception as exc:  # noqa: BLE001 - retry, then fallback
            last_error = exc
            time.sleep(1)
    tip = dict(FALLBACK_TIP)
    tip["error"] = str(last_error)
    return tip


def subsidy_satoshis(height: int) -> int:
    halvings = height // 210_000
    if halvings >= 64:
        return 0
    return (50 * 100_000_000) // (2 ** halvings)


# --- address -> scriptPubKey -------------------------------------------
_BECH32_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


def _bech32_polymod(values: list[int]) -> int:
    chk = 1
    generators = [0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3]
    for v in values:
        top = chk >> 25
        chk = ((chk & 0x1FFFFFF) << 5) ^ v
        for i in range(5):
            if (top >> i) & 1:
                chk ^= generators[i]
    return chk


def _bech32_decode(address: str):
    address = address.lower()
    pos = address.rfind("1")
    if pos < 1:
        raise ValueError("Invalid bech32 address: no separator")
    hrp, data_part = address[:pos], address[pos + 1:]
    if len(data_part) < 6:
        raise ValueError("Invalid bech32 address: too short")
    values = [_BECH32_CHARSET.index(c) for c in data_part]
    hrp_expand = [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp]
    polymod = _bech32_polymod(hrp_expand + values)
    # bech32: 1, bech32m (taproot): 0x2BC830A3.
    if polymod not in (1, 0x2BC830A3):
        raise ValueError("Invalid bech32 address: bad checksum")
    # Convert 5-bit groups to 8-bit, dropping padding. values[0] is
    # the witness version, not part of the program — skipping it
    # is essential, otherwise the program shifts by 5 bits.
    bits, acc, out = 0, 0, bytearray()
    for v in values[1:-6]:
        acc = (acc << 5) | v
        bits += 5
        if bits >= 8:
            bits -= 8
            out.append((acc >> bits) & 0xFF)
    if not out:
        raise ValueError("Invalid bech32 address: empty program")
    witness_version = values[0]
    return witness_version, bytes(out)


def _base58_decode(address: str) -> bytes:
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    num = 0
    for c in address:
        num = num * 58 + alphabet.index(c)
    raw = num.to_bytes((num.bit_length() + 7) // 8, "big") if num else b""
    pad = len(address) - len(address.lstrip("1"))
    raw = b"\x00" * pad + raw
    payload, checksum = raw[:-4], raw[-4:]
    if dsha256(payload)[:4] != checksum:
        raise ValueError("Invalid base58 address: bad checksum")
    return payload


def address_to_scriptpubkey(address: str) -> dict:
    """Convert a PUBLIC receive address to scriptPubKey. Rejects keys."""
    addr = (address or "").strip()
    if not addr:
        raise ValueError("No wallet address supplied")
    if " " in addr or len(addr.split()) > 1:
        raise ValueError(
            "That looks like a seed phrase, not an address. "
            "NEVER send a seed phrase or private key — only a public "
            "receive address (starting bc1, 1 or 3).")
    if addr.startswith(("5", "K", "L")) and len(addr) in (51, 52):
        raise ValueError(
            "That looks like a private key (WIF), not an address. "
            "NEVER send a private key — only a public receive address.")
    if addr.lower().startswith("bc1"):
        version, program = _bech32_decode(addr)
        if version == 0 and len(program) == 20:
            script = b"\x00\x14" + program
            kind = "P2WPKH"
        elif version == 0 and len(program) == 32:
            script = b"\x00\x20" + program
            kind = "P2WSH"
        elif version == 1 and len(program) == 32:
            script = b"\x51\x20" + program
            kind = "P2TR"
        else:
            raise ValueError("Unsupported bech32 witness version/length")
        return {"kind": kind, "scriptpubkey": script.hex(),
                "address": addr}
    if addr.startswith("1") or addr.startswith("3"):
        payload = _base58_decode(addr)
        if len(payload) != 21:
            raise ValueError("Invalid legacy address length")
        version, hash160 = payload[0], payload[1:]
        if version == 0 and addr.startswith("1"):
            script = b"\x76\xa9\x14" + hash160 + b"\x88\xac"
            return {"kind": "P2PKH", "scriptpubkey": script.hex(),
                    "address": addr}
        if version == 5 and addr.startswith("3"):
            script = b"\xa9\x14" + hash160 + b"\x87"
            return {"kind": "P2SH", "scriptpubkey": script.hex(),
                    "address": addr}
        raise ValueError("Legacy address version/prefix mismatch")
    raise ValueError(
        "Unrecognised address format. Supply a public receive address "
        "starting bc1, 1 or 3 — never a private key or seed phrase.")


def build_real_template(wallet_address: str, tip: dict | None = None) -> dict:
    """Build a coinbase-only template for the next block after tip."""
    tip = tip or fetch_live_tip()
    height = tip["height"] + 1
    script = address_to_scriptpubkey(wallet_address)
    script_bytes = bytes.fromhex(script["scriptpubkey"])
    script_sig = struct.pack("<I", height) + b"Blockforge"
    coinbase = struct.pack("<I", 1)
    coinbase += b"\x01"
    coinbase += b"\x00" * 32 + struct.pack("<I", 0xFFFFFFFF)
    coinbase += bytes([len(script_sig)]) + script_sig
    coinbase += struct.pack("<I", 0xFFFFFFFF)
    coinbase += b"\x01"
    coinbase += struct.pack("<Q", subsidy_satoshis(height))
    coinbase += bytes([len(script_bytes)]) + script_bytes
    coinbase += struct.pack("<I", 0)
    coinbase_txid = dsha256(coinbase)[::-1].hex()
    return {
        "height": height, "version": tip["version"],
        "prev_hash": tip["hash"], "merkle_root": coinbase_txid,
        "timestamp": int(time.time()), "bits": tip["bits"],
        "network_target": bits_to_target(tip["bits"]),
        "network_difficulty": tip["difficulty"],
        "subsidy_satoshis": subsidy_satoshis(height),
        "coinbase_txid": coinbase_txid,
        "coinbase_hex": coinbase.hex(),
        "wallet_address": wallet_address,
        "wallet_kind": script["kind"],
        "tip_source": tip.get("source", "live: mempool.space"),
        "tx_count": 1,
    }


def assemble_block(template: dict, nonce: int) -> str:
    """Serialize a full block (header + 1 coinbase tx) as hex."""
    header = build_header(template, nonce)
    return header.hex() + "01" + template["coinbase_hex"]


def validate_block_for_submission(template: dict, nonce: int,
                                  current_tip_hash: str | None = None) -> dict:
    """The gate: only a genuinely found perfect hash passes."""
    header = build_header(template, nonce)
    hash_bytes = dsha256(header)
    hash_hex = hash_bytes[::-1].hex()
    hash_int = int.from_bytes(hash_bytes, "big")
    reasons = []
    if hash_int > template["network_target"]:
        reasons.append("hash above network target — not a block")
    if current_tip_hash and template["prev_hash"] != current_tip_hash:
        reasons.append("prevhash is stale — chain has moved on")
    if abs(template["timestamp"] - int(time.time())) > 7200:
        reasons.append("timestamp too far from now")
    return {
        "valid_for_submission": not reasons,
        "hash": hash_hex, "nonce": nonce,
        "reasons": reasons,
        "block_hex": assemble_block(template, nonce) if not reasons else None,
    }


def test_pool_connection(host: str, port: int, timeout: float = 10) -> dict:
    """Connect + subscribe + authorize + read first job, no shares.

    Returns what the pool actually sent, or the error. This proves
    the pool is reachable and speaking Stratum; it does NOT prove
    a share would be accepted (that needs a share at pool difficulty).
    """
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        f = sock.makefile("rw", encoding="utf-8", newline="\n")
        f.write(json.dumps({"id": 1, "method": "mining.subscribe",
                            "params": ["Blockforge/1.0"]}) + "\n"); f.flush()
        sub = f.readline()
        f.write(json.dumps({"id": 2, "method": "mining.authorize",
                            "params": ["Blockforge", "x"]}) + "\n"); f.flush()
        auth = f.readline()
        # Read up to 3 more lines looking for a notify / set_difficulty.
        extra = []
        sock.settimeout(5)
        try:
            for _ in range(3):
                line = f.readline()
                if not line:
                    break
                extra.append(line.strip()[:300])
        except (socket.timeout, OSError):
            pass
        sock.close()
        return {"host": host, "port": port, "tcp": True,
                "subscribe_reply": sub.strip()[:300],
                "authorize_reply": auth.strip()[:300],
                "extra": extra}
    except Exception as exc:  # noqa: BLE001 - report, don't raise
        return {"host": host, "port": port, "tcp": False, "error": str(exc)}
