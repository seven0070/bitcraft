# Kimi mines, Atlas controls — division of labour (agreed 2026-10-26)

## Roles
- **Kimi (sim miner):** runs the portable Emberhill sim in batches.
  Runs only the file Atlas gives it, with the parameters Atlas gives it.
  Reports year summaries + final state JSON, nothing else.
  No real Bitcoin, no wallet, no pool, no real mining, no submission.
- **Atlas (controller / organiser):** controls the live Emberhill world here,
  verifies every Kimi run against a local run of the same code + same
  starting state, keeps the ledger, and decides what (if anything) gets
  ported back to the live world.
  Controls the real midstate miner separately. Kimi never controls
  real submission, spending, pool choice, or live world state.
- **Sanath:** approves anything consequential (real submission, pool
  change, spending, live world law changes, GitHub push, etc.).

## Boundaries (hard)
- Kimi is NOT the engine inside Atlas. Atlas is Muse Spark (Meta).
  Kimi is Moonshot's Kimi, external, via kimi.ai chat only.
- Kimi output is input, not authority. Atlas verifies, then acts.
- No wallet address, private key, seed phrase, or personal data
  goes to Kimi, ever. Portable sim contains no wallet.
- Sim BTC is tally only. Real BTC only comes from a real valid
  hash + Sanath-approved submission, which has not happened (0 found).

## Workflow for each Kimi batch
1. Atlas prepares portable sim + starting state file (if resuming).
2. Atlas sends both to Kimi via browser, with a single prompt:
   run X years, show summaries + final state, simulation only,
   if you cannot execute, say so plainly.
3. Atlas runs the same code + same starting state locally.
4. Atlas compares: year summaries and final state must match exactly
   (deterministic code). If they differ, the Kimi run is flagged,
   not trusted, and not ported.
5. Atlas records the run in kimi-sim-ledger.json (below), with
   Kimi chat URL, local verification result, and live world state
   at that time. Live world is NOT overwritten by Kimi runs unless
   Sanath explicitly orders a port, with the exact change named.

## Ledger format
See kimi-sim-ledger.json. Each entry: run_id, engine (Kimi),
code_file, start_year, end_year, kimi_final_state, local_final_state,
match (true/false), chat_url, verified_by (Atlas), live_world_year_at_run.
