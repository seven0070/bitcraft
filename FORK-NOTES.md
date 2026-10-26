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

## What is NOT in this repository (by design)

- `.env` (contains API keys — gitignored, never committed)
- `backend/app/uploads/` (runtime world state, e.g. Emberhill) and
  `backend/uploads/` (local graphs, simulations) — runtime state, not source
- `backend/.venv/`, `node_modules/`, `frontend/dist/` (build artefacts)
- Binary images from the upstream repo (logos/screenshots) — omitted from
  this snapshot push; the code that references them is unchanged.

## Honest limits (from the build)

- The social simulation's start is blocked by a FastMCP import error
  (`mcp` 2.3.0 vs `camel-ai` 0.2.78); prepare succeeded, start failed at round 0.
- The Minecraft world, Blockforge mine, and its wallet/BTC are simulations.
  The only genuine hashing in this repo is the local replica miner and the
  real-submission template code, both CPU-speed, not ASIC-speed.
- No block has been submitted to the real Bitcoin chain from this code.
