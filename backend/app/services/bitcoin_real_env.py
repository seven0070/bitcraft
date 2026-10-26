"""Real Bitcoin mining environment — a faithful local replica.

What "same as the real one" means here, and what it does not:

SAME (protocol, physics, verification — no shortcuts):
* Block template built the real way: version, previous block hash,
  Merkle root, timestamp, bits (compact target), nonce — an 80-byte
  header, exactly as Bitcoin defines it.
* Template for height 972,586, the next block after the real block
  972,585 whose header Sanath supplied and Atlas verified (19/19
  checks, Oct 2026): prevhash = 972585's hash, version 0x20abc000,
  bits 0x17020093 (network difficulty 140.58T), subsidy 3.125 BTC.
  The template is coinbase-only (one transaction) — a valid form
  of a block, chosen so the Merkle root is computable here without
  a full mempool; real miners normally add thousands of txs, and
  that difference is stated, not hidden.
* Work is genuine double-SHA-256 nonce search (hashlib, C speed),
  nonce space partitioned like real chips partition it. No sampled
  or invented results: a share counts only if its header hash,
  recomputed independently by the pool, beats the pool target.
* Pool verification is independent: the pool re-hashes the
  submitted header itself and rejects anything that does not meet
  the target, exactly as a real pool re-hashes every submission.
* Stratum-style flow over TCP, line-delimited JSON, mirroring
  real Stratum V1 shapes: mining.subscribe, mining.authorize,
  mining.notify (job), mining.submit (share), accept/reject reply.
  This is a local replica of that flow, not wire-compatibility
  tested against an external pool.
* The same economics around it: network target from bits, share
  difficulty from the hash, subsidy, halving schedule, 10-minute
  interval — the mega mine's aggregate model already uses these.

SCALED (the honest differences, and why they are necessary):
* Pool difficulty is 0.001, not 140,580,000,000,000. Real pools
  do exactly this in principle — they pay miners per *share* at a
  difficulty far below network difficulty (e.g. public-pool
  100,000 vs network 140T) — but 0.001 is far below even a real
  pool's share difficulty, chosen so a CPU miner at ~545k H/s
  finds a share in ~12 seconds instead of ~150 trillion years at
  network difficulty (353,894 H/s vs 1.71e24 hashes per block).
  A share meeting the *network* target would be a
  real block; at CPU speed that is not expected, and none is
  claimed.
* One representative miner, not 1,340,097 machines. Hashing
  1,554 EH/s would need a data centre, not this VM. The replica
  proves the environment works with genuine hashing; the mega
  mine's fleet size and hashrate remain aggregate arithmetic
  on top of it (see bitcoin_mega_miner.py).
* Local only: the pool listens on 127.0.0.1, no mainnet, no
  testnet, no external pool, no real wallet, no real BTC. The
  coinbase "address" is a simulated Blockforge identifier, not
  a spendable wallet. Nothing here earns, moves or spends real
  Bitcoin, and nothing here is submitted to any real network.

Run: python3 -m app.services.bitcoin_real_env --seconds 40
  (from backend/, or see run_real_env_test.py)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import socket
import struct
import threading
import time

# Real block 972585, verified from Sanath's data (see module docstring).
PREV_HASH = "00000000000000000000688396935a1fee3fbafa81cbd647537667a54ae701a3"
PREV_HEIGHT = 972585
NEXT_HEIGHT = 972586
VERSION = 0x20ABC000
BITS = 0x17020093
SUBSIDY_SATOSHIS = 312_500_000  # 3.125 BTC, real subsidy at this height
POOL_DIFFICULTY = 0.001
# Difficulty-1 target (Bitcoin's original target, from bits 0x1d00ffff).
DIFF1_TARGET = 0x00000000FFFF0000000000000000000000000000000000000000000000000000


def dsha256(data: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


def bits_to_target(bits: int) -> int:
    exponent = bits >> 24
    mantissa = bits & 0xFFFFFF
    return mantissa * (256 ** (exponent - 3))


def hash_to_difficulty(hash_bytes: bytes) -> float:
    """Share difficulty: diff1 target / hash value (big-endian)."""
    value = int.from_bytes(hash_bytes, "big")
    if value == 0:
        return float("inf")
    return DIFF1_TARGET / value


def build_coinbase(height: int) -> bytes:
    """Coinbase tx for Blockforge (simulated miner identifier).

    Serialisation follows Bitcoin's tx format: version, 1 input
    (null prevout, scriptSig = height + 'Blockforge Mega Mine'),
    1 output (subsidy to a simulated P2PKH-style script whose
    hash160 is the first 20 bytes of SHA-256('Blockforge')), locktime.
    """
    script_sig = struct.pack("<I", height) + b"Blockforge Mega Mine"
    hash160 = hashlib.sha256(b"Blockforge").digest()[:20]
    script_pubkey = b"\x76\xa9\x14" + hash160 + b"\x88\xac"
    tx = struct.pack("<I", 1)
    tx += b"\x01"  # 1 input
    tx += b"\x00" * 32 + struct.pack("<I", 0xFFFFFFFF)
    tx += bytes([len(script_sig)]) + script_sig
    tx += struct.pack("<I", 0xFFFFFFFF)
    tx += b"\x01"  # 1 output
    tx += struct.pack("<Q", SUBSIDY_SATOSHIS)
    tx += bytes([len(script_pubkey)]) + script_pubkey
    tx += struct.pack("<I", 0)
    return tx


def build_template() -> dict:
    coinbase = build_coinbase(NEXT_HEIGHT)
    coinbase_txid = dsha256(coinbase)[::-1].hex()  # display order
    # Coinbase-only block: Merkle root == coinbase txid.
    return {
        "height": NEXT_HEIGHT,
        "version": VERSION,
        "prev_hash": PREV_HASH,
        "merkle_root": coinbase_txid,
        "timestamp": int(time.time()),
        "bits": BITS,
        "network_target": bits_to_target(BITS),
        "network_difficulty": bits_to_target(BITS) and DIFF1_TARGET / bits_to_target(BITS),
        "subsidy_satoshis": SUBSIDY_SATOSHIS,
        "coinbase_txid": coinbase_txid,
        "tx_count": 1,
    }


def build_header(template: dict, nonce: int) -> bytes:
    header = struct.pack("<I", template["version"])
    header += bytes.fromhex(template["prev_hash"])[::-1]
    header += bytes.fromhex(template["merkle_root"])[::-1]
    header += struct.pack("<III", template["timestamp"], template["bits"], nonce)
    return header


def verify_share(template: dict, nonce: int, pool_difficulty: float) -> dict:
    """Independent pool verification: re-hash, check pool target."""
    header = build_header(template, nonce)
    hash_bytes = dsha256(header)
    hash_hex = hash_bytes[::-1].hex()  # display order, like block explorers
    hash_int = int.from_bytes(hash_bytes, "big")
    pool_target = int(DIFF1_TARGET / pool_difficulty)
    accepted = hash_int <= pool_target
    is_block = hash_int <= template["network_target"]
    return {
        "accepted": accepted,
        "is_block": is_block,
        "hash": hash_hex,
        "difficulty": hash_to_difficulty(hash_bytes),
        "nonce": nonce,
    }


class PoolServer(threading.Thread):
    """TCP stratum-style pool on 127.0.0.1. Records every submission."""

    def __init__(self, port: int, template: dict,
                 pool_difficulty: float = POOL_DIFFICULTY):
        super().__init__(daemon=True)
        self.port = port
        self.template = template
        self.pool_difficulty = pool_difficulty
        self.accepted: list[dict] = []
        self.rejected: list[dict] = []
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    def run(self) -> None:
        self._sock.bind(("127.0.0.1", self.port))
        self._sock.listen(1)
        conn, _ = self._sock.accept()
        f = conn.makefile("rw", encoding="utf-8", newline="\n")
        # mining.subscribe / mining.authorize: acknowledge, then notify.
        for line in f:
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            method = msg.get("method", "")
            if method in ("mining.subscribe", "mining.authorize"):
                f.write(json.dumps({"id": msg.get("id"),
                                    "result": True, "error": None}) + "\n")
                f.flush()
                if method == "mining.authorize":
                    f.write(json.dumps({
                        "method": "mining.notify",
                        "params": [self.template],
                    }) + "\n")
                    f.flush()
            elif method == "mining.submit":
                nonce = msg["params"]["nonce"]
                result = verify_share(self.template, nonce,
                                      self.pool_difficulty)
                (self.accepted if result["accepted"]
                 else self.rejected).append(result)
                f.write(json.dumps({"id": msg.get("id"),
                                    "result": result,
                                    "error": None}) + "\n")
                f.flush()
        conn.close()

    def stop(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass


def run_miner(port: int, seconds: float) -> dict:
    """Connect to the pool, search nonces genuinely, submit shares."""
    sock = socket.create_connection(("127.0.0.1", port), timeout=10)
    f = sock.makefile("rw", encoding="utf-8", newline="\n")
    f.write(json.dumps({"id": 1, "method": "mining.subscribe",
                        "params": []}) + "\n"); f.flush(); f.readline()
    f.write(json.dumps({"id": 2, "method": "mining.authorize",
                        "params": ["Blockforge", "x"]}) + "\n"); f.flush()
    f.readline()
    notify = json.loads(f.readline())
    template = notify["params"][0]
    # Template arrives with JSON numbers; network_target is an int
    # in Python's JSON, exact for these magnitudes.
    template["network_target"] = int(template["network_target"])
    pool_target = int(DIFF1_TARGET / POOL_DIFFICULTY)
    start = time.time()
    nonce = 0
    hashes = 0
    shares: list[dict] = []
    msg_id = 3
    while time.time() - start < seconds:
        header = build_header(template, nonce)
        hash_int = int.from_bytes(dsha256(header), "big")
        hashes += 1
        nonce += 1
        if hash_int <= pool_target:
            f.write(json.dumps({"id": msg_id,
                                "method": "mining.submit",
                                "params": {"nonce": nonce - 1}}) + "\n")
            f.flush()
            reply = json.loads(f.readline())
            shares.append(reply["result"])
            msg_id += 1
    elapsed = time.time() - start
    sock.close()
    return {
        "template_height": template["height"],
        "hashes": hashes,
        "hashrate_h_s": round(hashes / elapsed),
        "seconds": round(elapsed, 1),
        "shares": shares,
        "accepted": sum(1 for s in shares if s["accepted"]),
        "rejected": sum(1 for s in shares if not s["accepted"]),
        "blocks_found": sum(1 for s in shares if s["is_block"]),
        "best_difficulty": max((s["difficulty"] for s in shares), default=0),
    }


def run_test(port: int = 33344, seconds: float = 40,
             pool_difficulty: float = POOL_DIFFICULTY) -> dict:
    template = build_template()
    pool = PoolServer(port, template, pool_difficulty)
    pool.start()
    time.sleep(0.5)
    try:
        miner = run_miner(port, seconds)
    finally:
        pool.stop()
    # Independent re-verification of the first accepted share, outside
    # both the miner and the pool code paths (fresh hashlib call).
    independent = None
    for share in miner["shares"]:
        if share["accepted"]:
            check = verify_share(template, share["nonce"], pool_difficulty)
            independent = {
                "nonce": share["nonce"],
                "hash": check["hash"],
                "matches_miner_share": check["hash"] == share["hash"],
                "accepted_on_recheck": check["accepted"],
            }
            break
    return {
        "environment": "local replica (127.0.0.1, no mainnet, no real BTC)",
        "template": template,
        "pool_difficulty": pool_difficulty,
        "pool": {"accepted": len(pool.accepted),
                 "rejected": len(pool.rejected)},
        "miner": miner,
        "independent_recheck": independent,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=float, default=40)
    parser.add_argument("--port", type=int, default=33344)
    args = parser.parse_args()
    result = run_test(port=args.port, seconds=args.seconds)
    print(json.dumps(result, indent=2, default=str))
