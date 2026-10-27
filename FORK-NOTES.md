# Fork notes — Atlas modifications to MiroFish

This repository is a modified fork of [666ghj/MiroFish](https://github.com/666ghj/MiroFish)
(AGPL-3.0, see LICENSE). The original code is unchanged except where noted below.
Modifications were made in October 2026 by Atlas for Sanath, and are listed here
as required by the AGPL-3.0 licence (prominent notice of modifications).

## What changed

- **No-Zep backend (no Zep Cloud key required):** Zep is now optional in
  `backend/app/config.py`. Without `ZEP_API_KEY`, a local JSON graph store
  (`backend/app/services/local_graph.py`, `backend/app/utils/local_zep_client.py`)
  is used instead; with a key, the original Zep Cloud path is unchanged.
  `backend/app/services/graph_builder.py` gained a synchronous local batch path
  and creates no fake entity on LLM failure.
- **Needle (cactus-compute/needle) via embeddings:** `backend/app/utils/needle_client.py`
  (keyword score primary, Needle cosine tiebreak only, never adds a hit).
  Needle does NOT replace the LLM — it generates no free text.
- **Clef (Cloudflare/clef) decision endpoints, disabled by default:**
  `backend/app/utils/clef_client.py`, `backend/app/api/decision.py`,
  `CLEF_ENABLED=false` by default. No Cloudflare credentials are stored here.
- **Minecraft-like world simulation (new, alongside the social sim):**
  `backend/app/services/minecraft_world.py`, `backend/app/api/minecraft.py`,
  `backend/app/static/minecraft_viewer.html`, `backend/run_minecraft_live.py`.
  Rule-based, no OASIS/LLM per tick. This is Minecraft-*like*, not actual
  Minecraft, and is not connected to a real Minecraft server.
- **Blockforge Mega Mine (simulation only):**
  `backend/app/services/bitcoin_mega_miner.py` (one U3S23H per real block,
  aggregate arithmetic only, no real hashing, no real BTC),
  `backend/app/services/bitcoin_mine_operations.py` (simulated wallet, staff,
  breakdowns, economics parameters — all simulated, not market data),
  `backend/app/services/bitcoin_real_env.py` (local replica pool, genuine
  double-SHA-256 hashing on CPU, local only, no mainnet/testnet),
  `backend/app/services/bitcoin_real_submission.py` (live tip via mempool.space,
  real wallet address → scriptPubKey, submission gate; wired, not live —
  needs a real wallet address and a direct-TCP pool permission to go live).
- **Other new files:** `seed-future-world.md` (draft, unconfirmed scenario),
  `test-nozep.sh`, `backend/run_real_env_test.py`.

## Improvements since the 2026-10-26 push (2026-10-26–27)

- **World Builders (simulated representations only):** `backend/app/services/world_builders.py`
  — renowned brains as simulated representations (not the real people, no
  affiliation, endorsement, or participation), with hashrate/power/cooling/
  repair/uptime bonuses only. Bitcoin constants are immutable in sim
  (`assert_bitcoin_immutable`: 21M cap, 210,000 halving interval, 3.125
  starting subsidy, 52,560 blocks/year).
- **Gen2 simulated hardware:** hashrate ×1.25/machine, power ×0.85/machine,
  Bitcoin constants untouched.
- **Live real-world anchor:** sim Bitcoin law is anchored to the live chain
  via mempool.space (height, difficulty, subsidy era, next halving), throttled
  and with fallback; sim subsidy tally stays sim-era by design, so it does
  not rewind the sim chronology or break the 21M cap.
- **Real blocks tracked in sim:** `advance_mine_year` records genuine CPU
  mining attempts in `mega_mine.real_block_mining`, kept separate from
  sim-generated blocks, never merged. Sim fleet does NOT genuinely hash
  real blocks.
- **Giant aging / generations:** villagers age in giant-years, reproduce
  with a generation output multiplier, instead of dying on human timescales.
- **Time-travel rebuild:** Year 32 checkpoint rebuilt and verified to
  reproduce Year 33 exactly (mine numbers), after a rest-network
  compounding stall was fixed with a 10,000 EH/s rest cap (a model fix,
  not a Bitcoin change).
- **C midstate miner:** `midstate_miner.c` (hand-rolled SHA-256, 2
  compressions/nonce instead of 3), verified identical to Python on the
  same template, plus `c_miner.c` (OpenSSL) as a backup. `miner_structs.h`
  is kept only with a warning — its 112-byte struct is NOT cache-aligned
  and is NOT used by any live miner.
- **Kimi / Atlas division (workflow, not code control):** `kimi-atlas-division.md`,
  `kimi-sim-ledger.json`, `emberhill_portable_for_kimi.py` (stdlib-only
  portable sim, no wallet, no real mining). Kimi runs portable sim batches;
  Atlas controls the live world and verifies Kimi output against local runs.
  Kimi is NOT inside Atlas and does NOT control real mining.
- **Live pool mining (HashedMax, CPU):** `pool_live_miner.py`,
  `pool_share_test.py`, `pool_vardiff_test.py` — Stratum to
  `btc.hmpool.io:3337`, address as username, proven recipe (prevhash
  word-swapped per 4-byte word, merkle branches as-is, nonce as big-endian
  hex). Public-pool vardiff was also proven to drop 100,000 → 1 over
  15 minutes for a silent miner. Pool shares are proof/PPLNS only;
  no real block has been found from this code, and no real BTC has been
  received from mining.
- **Ops price cap (model fix, not Bitcoin law):** `bitcoin_mine_operations.py`
  now caps the simulated BTC price at $10^12, after 3%/yr compounding over
  ~23,600 sim years overflowed float max and crashed the sim.

## What is NOT in this repository (by design)

- `.env` (contains API keys — gitignored, never committed)
- `backend/app/uploads/` (runtime world state, e.g. Emberhill) and
  `backend/uploads/` (local graphs, simulations) — runtime state, not source
- `backend/.venv/`, `node_modules/`, `frontend/dist/` (build artefacts)
- Binary images from the upstream repo (logos/screenshots) — omitted from
  this snapshot push; the code that references them is unchanged.
- Compiled miner binaries (`c_miner`, `midstate_miner`) — build from the
  `.c` sources in this repo; binaries are not committed.
- Wallet / runtime state: `real-mainnet-candidate.json` (contains a public
  receive address), `real-miner-state.json`, `pool-live-state.json`,
  `pool-share-test-state.json`, `kimi-year*-state.json` — runtime state,
  not source, and the wallet address is not published here.

## Honest limits (from the build)

- The social simulation's start is blocked by a FastMCP import error
  (`mcp` 2.3.0 vs `camel-ai` 0.2.78); prepare succeeded, start failed at round 0.
- The Minecraft world, Blockforge mine, and its wallet/BTC are simulations.
  The only genuine hashing in this repo is the local replica miner and the
  real-submission template code, both CPU-speed, not ASIC-speed.
- No block has been submitted to the real Bitcoin chain from this code.
