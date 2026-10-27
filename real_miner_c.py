#!/usr/bin/env python3
"""Real miner, C-accelerated version.

Same safety and tip-aware logic as real_miner.py, but the nonce
loop runs in C (c_miner, OpenSSL SHA256 with SHA-NI, no Python
loop overhead). Python only builds templates, checks tips,
and records state — hashing itself is in C.

- Coinbase pays public address on file in real-mainnet-candidate.json.
- Tip-aware: C run is capped at 30 s, then Python checks live tip
  and switches immediately on a new block.
- NO auto-submit: if c_miner exits 10 (VALID_FOUND), this wrapper
  stops, records VALID_FOUND in state/log, and waits for Sanath's
  explicit go-ahead. A valid hash alone is not submission.
- Stop via /tmp/real-miner-c.stop, or Sanath saying stop.
- Plain background process, dies on VM replacement.
"""
import json, os, subprocess, sys, time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))
from app.services.bitcoin_real_submission import fetch_live_tip, build_real_template

CANDIDATE = os.path.expanduser("~/workspace/mirofish/real-mainnet-candidate.json")
STATE = os.path.expanduser("~/workspace/mirofish/real-miner-state.json")
LOG = "/tmp/real-miner.log"
STOP = "/tmp/real-miner-c.stop"
C_MINER = os.path.join(os.path.dirname(__file__), "c_miner")

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
    log("REAL MINER (C) STARTED. Coinbase pays public address on file. No auto-submit. C loop + SHA-NI, Python only for templates/tips.")
    total = 0
    round_no = 0
    nonce_offset = 0
    while not os.path.exists(STOP):
        round_no += 1
        try:
            tip = fetch_live_tip()
        except Exception as e:
            log(f"tip fetch failed ({e}); retrying in 60s")
            time.sleep(60)
            continue
        tpl = build_real_template(wallet, tip=tip)
        height = tpl["height"]
        target_hex = format(int(tpl["network_target"]), "064x")
        log(f"ROUND {round_no} (C): height {height} prev {tpl['prev_hash'][:16]}... merkle {tpl['merkle_root'][:16]}... difficulty {float(tpl['network_difficulty']):.0f}")
        # C run: 30 s, nonce range starting at offset, so we do not
        # re-hash the same nonces on every tip check. On tip change,
        # Python breaks to a new round (new template, offset reset).
        args = [C_MINER, str(tpl["version"]), tpl["prev_hash"], tpl["merkle_root"],
                str(tpl["timestamp"]), str(tpl["bits"]), target_hex, "30", str(nonce_offset)]
        try:
            out = subprocess.run(args, capture_output=True, text=True, timeout=40)
        except Exception as e:
            log(f"C miner run failed ({e}); retrying")
            time.sleep(5)
            continue
        if out.returncode == 10:
            log(f"VALID_FOUND in C output: {out.stdout.strip()}")
            save_state({"status": "VALID_FOUND", "height": height, "output": out.stdout.strip(), "total_hashes": total})
            return
        # Parse: hashed N in T s = R H/s ; best nonce X ; best hash Y
        hashed = 0
        best_nonce = 0
        best_hash = None
        rate = 0
        for line in out.stdout.splitlines():
            if line.startswith("hashed "):
                try:
                    parts = line.split()
                    hashed = int(parts[1])
                    rate = float(parts[6]) if len(parts) > 6 else 0
                except Exception:
                    pass
            if line.startswith("best nonce "):
                try: best_nonce = int(line.split()[-1])
                except Exception: pass
            if line.startswith("best hash "):
                best_hash = line.split()[-1]
        total += hashed
        nonce_offset += hashed
        # Best difficulty approx, from template difficulty * target / hash value
        try:
            diff = float(tpl["network_difficulty"]) * int(tpl["network_target"]) / int(best_hash, 16) if best_hash else 0
        except Exception:
            diff = 0
        log(f"  height {height}: {hashed:,} this C run, {total:,} total, {rate:,.0f} H/s, best diff {diff:.6f} (nonce {best_nonce})")
        save_state({"status": "mining", "height": height, "total_hashes": total,
                    "best": {"hash": best_hash, "difficulty": diff, "nonce": best_nonce, "height": height},
                    "round": round_no, "engine": "C"})
        # Tip check: if tip moved, new round with new template.
        # nonce_offset resets on new height, otherwise continues.
        try:
            cur = fetch_live_tip()
            if int(cur["height"]) != height - 1:
                log(f"  TIP CHANGED: live tip now {cur['height']}, switching to {int(cur['height']) + 1}")
                nonce_offset = 0
        except Exception:
            pass
    log("REAL MINER (C) STOPPED via stop file.")
    save_state({"status": "stopped", "total_hashes": total})

if __name__ == "__main__":
    main()
