#!/bin/bash
# Test MiroFish backend in NO-ZEP local-graph mode.
# Prerequisites (do NOT run while pip install is still writing .venv):
#   - ~/workspace/mirofish/backend/.venv with requirements installed (Python 3.11)
#   - ~/workspace/mirofish/.env with LLM_* set, NO ZEP_API_KEY value
#   - No server already running on 5001
# This script prints only API responses (project/graph/task IDs, counts) -
# it never prints .env contents or any API key.
set -u
# httpx (used by the OpenAI client) fails to parse the VM's default NO_PROXY
# list, which contains bracketed IPv6 entries like [::1] - it raises
# InvalidURL "Invalid port: ':1]'". Keep egress proxy vars for NVIDIA,
# but narrow NO_PROXY to plain localhost entries for this test server.
export NO_PROXY=localhost,127.0.0.1
export no_proxy=localhost,127.0.0.1
cd ~/workspace/mirofish/backend || exit 1
if [ ! -x .venv/bin/python ]; then echo "FAIL: .venv/bin/python missing - pip install not finished"; exit 1; fi
if grep -q '^ZEP_API_KEY=[^ ]' ../.env 2>/dev/null; then echo "FAIL: ZEP_API_KEY value present in .env - this test is for no-Zep mode"; exit 1; fi
echo "== 1. Start backend =="
.venv/bin/python run.py > /tmp/mirofish-test-server.log 2>&1 &
SRVPID=$!
trap 'kill $SRVPID 2>/dev/null; echo "server stopped"' EXIT
for i in $(seq 1 60); do
  if curl -s http://127.0.0.1:5001/health | python3 -c "import sys,json; sys.exit(0 if json.load(sys.stdin).get('status')=='ok' else 1)" 2>/dev/null; then echo "HEALTH OK"; break; fi
  sleep 2
  if [ "$i" = "60" ]; then echo "FAIL: backend did not become healthy"; tail -100 /tmp/mirofish-test-server.log; exit 1; fi
done
echo "== 2. Ontology generate (future world seed) =="
RESP=$(curl -s -F "files=@../seed-future-world.md" \
  -F "simulation_requirement=What does everyday life, work, and public conversation look like in Bangalore, India in 2035 where AI agents, creators, and automated earning are normal, and what trajectories and tensions emerge?" \
  -F "project_name=Future World 2035 Test" \
  http://127.0.0.1:5001/api/graph/ontology/generate)
echo "$RESP" | head -c 2000; echo
PROJ=$(echo "$RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('project_id',''))" 2>/dev/null)
if [ -z "$PROJ" ]; then echo "FAIL: no project_id from ontology generate"; exit 1; fi
echo "PROJECT=$PROJ"
echo "== 3. Graph build =="
RESP2=$(curl -s -X POST -H 'Content-Type: application/json' -d "{\"project_id\": \"$PROJ\"}" http://127.0.0.1:5001/api/graph/build)
echo "$RESP2" | head -c 2000; echo
TASK=$(echo "$RESP2" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('task_id',''))" 2>/dev/null)
if [ -z "$TASK" ]; then echo "FAIL: no task_id from graph build"; exit 1; fi
for i in $(seq 1 90); do
  T=$(curl -s "http://127.0.0.1:5001/api/graph/task/$TASK")
  echo "task poll $i: $(echo "$T" | head -c 500)"
  TSTATUS=$(echo "$T" | python3 -c "import sys,json; print(json.load(sys.stdin).get('data',{}).get('status',''))" 2>/dev/null)
  if [ "$TSTATUS" = "completed" ]; then break; fi
  if [ "$TSTATUS" = "failed" ]; then echo "FAIL: graph build failed"; exit 1; fi
  sleep 5
done
GRAPH=$(echo "$T" | python3 -c "import sys,json; d=json.load(sys.stdin); r=d.get('data',{}).get('result',{}) or d.get('data',{}); print(r.get('graph_id',''))" 2>/dev/null)
if [ -z "$GRAPH" ]; then GRAPH=$(curl -s "http://127.0.0.1:5001/api/graph/project/$PROJ" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('graph_id',''))" 2>/dev/null); fi
echo "GRAPH=$GRAPH"
echo "== 4. Graph data =="
if [ -n "$GRAPH" ]; then
  curl -s "http://127.0.0.1:5001/api/graph/data/$GRAPH" | python3 -c "import sys,json; d=json.load(sys.stdin); data=d.get('data',{}); print('nodes=', data.get('node_count'), 'edges=', data.get('edge_count')); print('node names=', [n.get('name') for n in data.get('nodes',[])][:20])"
  ls -lh uploads/local_graphs/ 2>/dev/null | head -20
else
  echo "WARN: graph_id not recovered from task/project - check server log"
fi
echo "== DONE (server log: /tmp/mirofish-test-server.log) =="
