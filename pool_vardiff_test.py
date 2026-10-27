#!/usr/bin/env python3
"""Long vardiff test for public-pool.io:3333.
Connects with Sanath's real public address (from candidate file, never printed),
authorizes, then logs every mining.set_difficulty and mining.notify for 15 minutes.
Goal: does pool lower difficulty from 100,000 on its own when no shares are submitted?
Safe: no shares submitted, no block submission, no mining work, just listening.
Log: ~/workspace/mirofish/pool-vardiff-test.log
"""
import socket, json, time, sys, os
cand_path = os.path.expanduser("~/workspace/mirofish/real-mainnet-candidate.json")
wallet = json.load(open(cand_path))["template"]["wallet_address"]
log_path = os.path.expanduser("~/workspace/mirofish/pool-vardiff-test.log")
def log(msg):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S IST', time.localtime())} {msg}"
    print(line, flush=True)
    with open(log_path, "a") as f:
        f.write(line + "\n")
log("VARDIFF TEST STARTED. Pool public-pool.io:3333, wallet as username (not printed), no shares, listening only.")
s = socket.create_connection(("public-pool.io", 3333), timeout=20)
s.settimeout(5)
buf = b""
def send(o):
    s.sendall((json.dumps(o) + "\n").encode())
def readline():
    global buf
    while b"\n" not in buf:
        try:
            chunk = s.recv(4096)
        except socket.timeout:
            return None
        if not chunk:
            return ""
        buf += chunk
    line, buf = buf.split(b"\n", 1)
    return line.decode()
send({"id": 1, "method": "mining.subscribe", "params": ["AtlasVardiffTest/1.0"]})
log(f"subscribe: {readline()[:200]}")
send({"id": 2, "method": "mining.authorize", "params": [wallet, "x"]})
log(f"authorize: {readline()[:200]}")
start = time.time()
duration = 900  # 15 minutes
while time.time() - start < duration:
    line = readline()
    if line is None:
        continue
    if line == "":
        log("connection closed by pool"); break
    try:
        j = json.loads(line)
    except Exception:
        continue
    if j.get("method") == "mining.set_difficulty":
        log(f"SET_DIFFICULTY {j['params']} at +{int(time.time()-start)}s")
    elif j.get("method") == "mining.notify":
        p = j["params"]
        log(f"NOTIFY job {p[0]} clean={p[8]} at +{int(time.time()-start)}s")
    elif "result" in j or "error" in j:
        log(f"response id={j.get('id')} result={j.get('result')} error={j.get('error')}")
log("VARDIFF TEST DONE (15 min).")
s.close()
