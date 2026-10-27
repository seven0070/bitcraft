#!/usr/bin/env python3
"""
Continuous real-mainnet candidate miner, like a real miner should:
- Loads the candidate template from real-mainnet-candidate.json (built with
  Sanath's public receive address in the coinbase).
- Hashes the full 2^32 nonce range for that header, genuinely, one nonce at a time.
- When the nonce range is exhausted (or a new tip arrives), it refreshes the
  template from the live tip, rebuilds the coinbase with the same public
  address, and keeps going. Timestamp is refreshed on each new template.
- TIP-AWARE (2026-10-26, Sanath: mine on all those blocks): every 30 s
  it checks the live tip. If a new block has arrived, it drops the
  current candidate immediately and starts mining the next height —
  so it mines on every new block in turn, as it appears, instead of
  mining stale for up to 10 min. Mining past blocks in parallel would
  NOT help: a block for an old height would be rejected as a
  duplicate/stale fork, and splitting CPU across headers does not
  increase total hashes/sec, which is what actually determines
  the chance of finding a valid hash.
- Logs progress and best hash to /tmp/real-miner.log and state to
  ~/workspace/mirofish/real-miner-state.json.
- NEVER auto-submits. If a hash ever meets the network target, it stops and
  writes VALID_FOUND to the log/state and waits for Sanath's explicit
  go-ahead (a valid hash alone is not enough: submission also needs the
  TCP pool permission he has not changed).
- Stops cleanly on /tmp/real-miner.stop, or on Sanath saying stop.
- This is a plain background process: it dies on VM replacement, like the
  other runners. Restart it after a restart if he wants it to continue.
"""
import hashlib, json, os, struct, sys, time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))
from app.services.bitcoin_real_submission import fetch_live_tip, build_real_template

CANDIDATE = os.path.expanduser("~/workspace/mirofish/real-mainnet-candidate.json")
STATE = os.path.expanduser("~/workspace/mirofish/real-miner-state.json")
LOG = "/tmp/real-miner.log"
STOP = "/tmp/real-miner.stop"

def log(msg):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S IST', time.localtime())} {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")

def save_state(state):
    tmp = STATE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=1)
    os.replace(tmp, STATE)

def main():
    if os.path.exists(STOP):
        os.remove(STOP)
    with open(CANDIDATE) as f:
        cand = json.load(f)
    wallet = cand["template"]["wallet_address"]
    log("REAL MINER STARTED. Coinbase pays public address on file (not shown in log). No auto-submit.")
    total_hashes = 0
    best = {"hash": None, "difficulty": 0, "nonce": 0, "height": None}
    best_val = None
    round_no = 0
    while not os.path.exists(STOP):
        round_no += 1
        # Best hash is per-round (per header): a best hash from an
        # old tip/height must not be reported as best for a new tip.
        best = {"hash": None, "difficulty": 0, "nonce": 0, "height": None}
        best_val = None
        try:
            tip = fetch_live_tip()
        except Exception as e:
            log(f"tip fetch failed ({e}); retrying in 60s with last template")
            time.sleep(60)
            continue
        tpl = build_real_template(wallet, tip=tip)
        height = tpl["height"]
        version = int(tpl["version"])
        prev = bytes.fromhex(tpl["prev_hash"])[::-1]
        merk = bytes.fromhex(tpl["merkle_root"])[::-1]
        ts = int(tpl["timestamp"])
        bits = int(tpl["bits"])
        target = int(tpl["network_target"])
        diff = float(tpl["network_difficulty"])
        log(f"ROUND {round_no}: height {height} prev {tpl['prev_hash'][:16]}... merkle {tpl['merkle_root'][:16]}... difficulty {diff:.0f}")
        start = time.time()
        last_tip_check = start
        nonce = 0
        round_hashes = 0
        # Full nonce range, like a real miner. Check live tip every
        # 30 s and switch immediately on a new block, so we mine
        # on every new block in turn. Fallback: refresh after 10 min
        # even if tip has not changed, for a fresh timestamp.
        while nonce < 2**32 and not os.path.exists(STOP):
            hdr = struct.pack("<I", version) + prev + merk + struct.pack("<III", ts, bits, nonce)
            h = hashlib.sha256(hashlib.sha256(hdr).digest()).digest()[::-1]
            v = int.from_bytes(h, "big")
            round_hashes += 1
            total_hashes += 1
            if v < target:
                log(f"VALID_FOUND height={height} nonce={nonce} hash={h.hex()}")
                save_state({"status": "VALID_FOUND", "height": height, "nonce": nonce,
                            "hash": h.hex(), "total_hashes": total_hashes})
                return
            # Best-hash tracking (compare integers, no hex conversion per hash)
            if best_val is None or v < best_val:
                best_val = v
                best = {"hash": h.hex(), "difficulty": diff * target / v if v else 0,
                        "nonce": nonce, "height": height}
            nonce += 1
            if round_hashes % 500000 == 0:
                elapsed = time.time() - start
                log(f"  height {height}: {round_hashes:,} this round, {total_hashes:,} total, "
                    f"{round_hashes/elapsed:,.0f} H/s, best diff {best['difficulty']:.6f} "
                    f"(nonce {best['nonce']}, {best['hash'][:18]}...)")
                save_state({"status": "mining", "height": height, "total_hashes": total_hashes,
                            "best": best, "round": round_no})
            if time.time() - last_tip_check > 30:
                last_tip_check = time.time()
                try:
                    cur_tip = fetch_live_tip()
                    if int(cur_tip["height"]) != height - 1:
                        log(f"  TIP CHANGED: live tip now {cur_tip['height']}, "
                            f"dropping candidate {height} and switching to {int(cur_tip['height']) + 1}")
                        break
                except Exception:
                    pass  # keep mining current candidate on fetch failure
            if time.time() - start > 600:
                log("  10 min on this template; refreshing tip (like a miner on a new block)")
                break
        if os.path.exists(STOP):
            break
        log(f"ROUND {round_no} done: {round_hashes:,} hashes, nonce range exhausted or template refreshed")
    log("REAL MINER STOPPED via stop file.")
    save_state({"status": "stopped", "total_hashes": total_hashes, "best": best})

if __name__ == "__main__":
    main()
