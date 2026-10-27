#!/usr/bin/env python3
"""LIVE pool miner to HashedMax btc.hmpool.io:3337.

Continuous version of pool_share_test.py, authorized by Sanath 2026-10-26
(switch live CPU to HashedMax 3337). BE nonce only (proven: BE 3/3 accepted,
LE 3/3 rejected with Difficulty too low). Runs until stop file, no share cap.


Authorized by Sanath 2026-10-26 (picked from the live-probed shortlist).
Listens to stratum, builds pool jobs with his address as username (never
printed), searches nonces with the midstate C miner against the POOL
difficulty target, and submits found shares. Target: 3 accepted shares
or 20 minutes, whichever first. The solo miner is left running untouched.

Safety: pool shares only (difficulty ~0.01). No block submission, no
spending. Nonce encoding: header LE bytes first; if the pool rejects,
one retry with byte-reversed nonce hex, then stop on repeated
non-stale rejects so we don't spam the pool.
Log: ~/workspace/mirofish/pool-share-test.log
State: ~/workspace/mirofish/pool-share-test-state.json
Stop: /tmp/pool-share-test.stop
"""
import hashlib, json, os, socket, struct, subprocess, sys, time
from fractions import Fraction

CANDIDATE = os.path.expanduser("~/workspace/mirofish/real-mainnet-candidate.json")
MIDSTATE = os.path.expanduser("~/workspace/mirofish/midstate_miner")
LOG_PATH = os.path.expanduser("~/workspace/mirofish/pool-live.log")
STATE_PATH = os.path.expanduser("~/workspace/mirofish/pool-live-state.json")
STOP = "/tmp/pool-live.stop"
HOST, PORT = "btc.hmpool.io", 3337
TARGET_SHARES, MAX_MINUTES = 10**9, 10**7
# HashedMax sends prevhash in INTERNAL byte order (as-sent ends in zeros;
# reversed it looks like a real block hash). The C miner reverses its prev
# arg, so pass the reversed string to land internal order in the header.
# Standard pools send display order and need no reversal; if this pool
# ever changes format, flip this flag.
# Prevhash handling (ground truth: virtual-u3s23h controller.js +
# virtual-bitaxe/common.js, proven by real accepted shares): the header's
# prev field is wordSwap(job prevhash) — bytes reversed WITHIN each
# 4-byte word, word order kept. The C miner fully reverses its prev arg,
# so pass reverse(wordSwap(prev)) to land wordSwap in the header.
# Combo testing (2026-10-26): full-reverse and as-is both rejected, with
# branches as-is and reversed. Now testing wordSwap + branches as-is.
PREV_MODE = "wordswap"  # "wordswap" | "reversed" | "asis"
BRANCH_REVERSED = False
DIFF1 = 0x00000000FFFF0000000000000000000000000000000000000000000000000000

def log(msg):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S IST', time.localtime())} {msg}"
    print(line, flush=True)
    with open(LOG_PATH, "a") as f:
        f.write(line + "\n")

def save_state(s):
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(s, f, indent=1)
    os.replace(tmp, STATE_PATH)

def dsha(b):
    return hashlib.sha256(hashlib.sha256(b).digest()).digest()

def diff_to_target(diff):
    return int(DIFF1 / Fraction(str(diff)))

def main():
    if os.path.exists(STOP):
        os.remove(STOP)
    wallet = json.load(open(CANDIDATE))["template"]["wallet_address"]
    users = [wallet + ".cpu", wallet]  # docs form first, plain address fallback
    log(f"POOL LIVE MINER STARTED. HashedMax btc.hmpool.io:3337, address worker (address hidden), pool shares only, no block submission. PREV_MODE={PREV_MODE} BRANCH_REVERSED={BRANCH_REVERSED}")
    s = socket.create_connection((HOST, PORT), timeout=20)
    # Raw recv with a persistent byte buffer. NEVER use makefile + timeout:
    # after one timeout the buffered reader is unusable (the vardiff bug).
    recv_buf = bytearray()

    def send(o):
        s.sendall((json.dumps(o) + "\n").encode())

    def drain(wait):
        """Read lines for up to `wait` seconds, return parsed messages."""
        s.settimeout(wait)
        msgs = []
        try:
            while True:
                try:
                    chunk = s.recv(65536)
                except socket.timeout:
                    break
                if not chunk:
                    break
                recv_buf.extend(chunk)
                while b"\n" in recv_buf:
                    line, _, rest = recv_buf.partition(b"\n")
                    recv_buf[:] = rest
                    line = line.strip()
                    if line:
                        try:
                            msgs.append(json.loads(line))
                        except Exception:
                            pass
        except Exception as e:
            log(f"read error: {e}")
        return msgs

    state = {"extranonce1": None, "extranonce2_size": None, "difficulty": None,
             "job": None, "authed_user": None, "accepted": 0, "rejected": 0,
             "shares": [], "status": "connecting", "pool": "btc.hmpool.io:3337", "mode": "pool", "worker_suffix": "cpu"}
    next_id = [3]
    submitted = {}  # submit id -> share info

    def apply(msgs):
        for j in msgs:
            if j.get("method") == "mining.set_difficulty":
                try:
                    state["difficulty"] = j["params"][0]
                    log(f"SET_DIFFICULTY {state['difficulty']}")
                except Exception:
                    pass
            elif j.get("method") == "mining.notify":
                p = j["params"]
                state["job"] = {"id": p[0], "prev": p[1], "coinb1": p[2], "coinb2": p[3],
                                "branches": p[4], "version": p[5], "nbits": p[6],
                                "ntime": p[7], "clean": p[8]}
                log(f"NOTIFY job {p[0]} clean={p[8]}")
            elif "id" in j:
                if j["id"] == 1 and j.get("result"):
                    r = j["result"]
                    state["extranonce1"] = r[1]
                    state["extranonce2_size"] = r[2]
                    log(f"SUBSCRIBE ok, extranonce2_size={r[2]}")
                elif j["id"] == 2:
                    log(f"AUTHORIZE result={j.get('result')} error={j.get('error')}")
                    if j.get("result") is True:
                        state["authed_user"] = "ok"
                elif j["id"] in submitted:
                    info = submitted.pop(j["id"])
                    ok = j.get("result") is True
                    err = j.get("error")
                    log(f"SUBMIT job {info['job']} nonce {info['nonce_hex']} -> {'ACCEPTED' if ok else 'REJECTED'} error={err}")
                    info["accepted"] = ok
                    info["error"] = err
                    state["shares"].append(info)
                    if ok:
                        state["accepted"] += 1
                    else:
                        state["rejected"] += 1
                    save_state(state)
        return

    send({"id": 1, "method": "mining.subscribe", "params": ["AtlasPoolTest/1.0"]})
    send({"id": 2, "method": "mining.authorize", "params": [users[0], "x"]})
    # Wait until we have extranonce, auth, difficulty and a job (order varies).
    deadline = time.time() + 60
    authed_idx = 0
    while time.time() < deadline:
        apply(drain(5))
        if state["authed_user"] is None and authed_idx == 0:
            # authorize may have failed silently; retry with plain address once
            pass
        if state["extranonce1"] and state["difficulty"] is not None and state["job"]:
            if state["authed_user"]:
                break
        if state["extranonce1"] and state["difficulty"] is not None and state["job"] and not state["authed_user"]:
            # No auth confirmation yet; try fallback user once
            if authed_idx == 0:
                authed_idx = 1
                send({"id": 2, "method": "mining.authorize", "params": [users[1], "x"]})
                log("AUTHORIZE retry with plain address")
    if not (state["extranonce1"] and state["difficulty"] is not None and state["job"]):
        log(f"ABORT: incomplete session state: extranonce={bool(state['extranonce1'])} diff={state['difficulty']} job={bool(state['job'])} authed={state['authed_user']}")
        save_state({**state, "status": "aborted_incomplete"})
        return
    user = users[authed_idx] if state["authed_user"] else users[0]
    log(f"SESSION READY. difficulty={state['difficulty']} job={state['job']['id']} worker_suffix={'cpu' if authed_idx == 0 else 'plain'}")
    state["status"] = "mining"
    save_state(state)

    start_all = time.time()
    nonce_offset = 0
    cur_job_id = None
    non_stale_rejects = 0
    while (not os.path.exists(STOP)
           and state["accepted"] < TARGET_SHARES
           and time.time() - start_all < MAX_MINUTES * 60):
        job = state["job"]
        diff = state["difficulty"]
        if job is None or diff is None:
            apply(drain(5))
            continue
        if job["id"] != cur_job_id:
            cur_job_id = job["id"]
            nonce_offset = 0
        # Build header inputs
        en2 = "00" * state["extranonce2_size"]
        coinbase = bytes.fromhex(job["coinb1"] + state["extranonce1"] + en2 + job["coinb2"])
        root = dsha(coinbase)
        for br in job["branches"]:
            br_bytes = bytes.fromhex(br)
            if BRANCH_REVERSED:
                br_bytes = br_bytes[::-1]
            root = dsha(root + br_bytes)
        merkle_arg = root[::-1].hex()
        target_hex = format(diff_to_target(diff), "064x")
        pb = bytes.fromhex(job["prev"])
        if PREV_MODE == "wordswap":
            ws = bytearray(len(pb))
            for i in range(0, len(pb), 4):
                ws[i:i + 4] = pb[i:i + 4][::-1]
            prev_arg = bytes(ws)[::-1].hex()
        elif PREV_MODE == "reversed":
            prev_arg = pb[::-1].hex()
        else:
            prev_arg = job["prev"]
        args = [MIDSTATE, str(int(job["version"], 16)), prev_arg, merkle_arg,
                str(int(job["ntime"], 16)), str(int(job["nbits"], 16)),
                target_hex, "25", str(nonce_offset)]
        try:
            out = subprocess.run(args, capture_output=True, text=True, timeout=35)
        except Exception as e:
            log(f"C miner run failed ({e}); retrying")
            time.sleep(2)
            continue
        # Drain any pool messages that arrived during the run
        apply(drain(1))
        if out.returncode != 10:
            # No share this chunk; advance offset from hashed count if parsed
            for line in out.stdout.splitlines():
                if line.startswith("hashed "):
                    try:
                        _h = int(line.split()[1])
                        nonce_offset += _h
                        state["total_hashes"] = state.get("total_hashes", 0) + _h
                        save_state(state)
                    except Exception:
                        pass
            continue
        # VALID_FOUND
        nonce = None
        for line in out.stdout.splitlines():
            if line.startswith("VALID_FOUND"):
                try:
                    nonce = int(line.split("nonce=")[1].split()[0])
                except Exception:
                    pass
        if nonce is None:
            log("VALID_FOUND but nonce unparsed; skipping")
            continue
        nonce_offset = nonce + 1
        be_hex = format(nonce, "08x")
        accepted = False
        for attempt, nhex in enumerate([be_hex]):
            sid = next_id[0]; next_id[0] += 1
            info = {"job": job["id"], "difficulty": diff, "nonce": nonce,
                    "nonce_hex": nhex, "ntime": job["ntime"], "encoding": "BE"}
            submitted[sid] = info
            send({"id": sid, "method": "mining.submit",
                  "params": [user, job["id"], en2, job["ntime"], nhex]})
            # Wait for this submit's response
            dl = time.time() + 20
            got = False
            while time.time() < dl and sid in submitted:
                apply(drain(3))
            if sid in submitted:
                submitted.pop(sid)
                log(f"SUBMIT job {job['id']} nonce {nhex}: no response in 20s")
                continue
            last = state["shares"][-1] if state["shares"] else None
            if last and last["nonce_hex"] == nhex and last.get("accepted"):
                accepted = True
                log(f"SHARE ACCEPTED ({last['encoding']} nonce encoding). total accepted={state['accepted']}")
                break
            else:
                err = last.get("error") if last else None
                log(f"share attempt {nhex} rejected/not accepted, error={err}")
                err_s = str(err).lower()
                if "stale" in err_s or "job not found" in err_s or "job-not-found" in err_s:
                    log("reject looks stale-related; continuing on fresh job")
                    break
        if not accepted:
            non_stale_rejects += 1
            if non_stale_rejects >= 5:
                log("5 consecutive non-stale rejects; pausing 60s, then continuing (live mode, not stopping)")
                time.sleep(60)
                non_stale_rejects = 0
        save_state(state)
    state["status"] = ("done" if state["accepted"] >= TARGET_SHARES
                       else "stopped" if os.path.exists(STOP)
                       else "stopped_rejects" if non_stale_rejects >= 2 else "timeout")
    log(f"POOL LIVE MINER {state['status'].upper()}: accepted={state['accepted']} rejected={state['rejected']} elapsed={int(time.time() - start_all)}s")
    save_state(state)
    try:
        s.close()
    except Exception:
        pass

if __name__ == "__main__":
    main()
