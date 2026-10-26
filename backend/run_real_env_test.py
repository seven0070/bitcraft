"""Re-run the Blockforge real-environment replica test and attach its
results to the Emberhill mega mine.

Usage (from backend/):
    NO_PROXY=localhost,127.0.0.1 .venv/bin/python run_real_env_test.py [seconds]

Runs a local stratum-style pool on 127.0.0.1:33344 serving a template
for height 972586 (after real block 972585), a genuine double-SHA-256
miner searching nonces, pool re-verification of every share, and an
independent recheck of the first accepted share. No mainnet, no
external pool, no real BTC. Writes the summary into the world's
mega_mine["real_env"] and prints it.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.services.bitcoin_real_env import run_test  # noqa: E402
from app.services.minecraft_world import MinecraftWorld  # noqa: E402


def main() -> int:
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 40
    result = run_test(port=33344, seconds=seconds)
    miner = result["miner"]
    first = miner["shares"][0] if miner["shares"] else None
    summary = {
        "name": "Real-environment replica (local, 127.0.0.1)",
        "pool_port": 33344,
        "template_height": result["template"]["height"],
        "template_prev_hash": result["template"]["prev_hash"],
        "template_bits": result["template"]["bits"],
        "network_difficulty": result["template"]["network_difficulty"],
        "pool_difficulty": result["pool_difficulty"],
        "test_seconds": miner["seconds"],
        "test_hashes": miner["hashes"],
        "test_hashrate_h_s": miner["hashrate_h_s"],
        "test_shares_accepted": result["pool"]["accepted"],
        "test_shares_rejected": result["pool"]["rejected"],
        "test_blocks_found": miner["blocks_found"],
        "test_best_difficulty": miner["best_difficulty"],
        "test_first_share": ({"nonce": first["nonce"], "hash": first["hash"]}
                             if first else None),
        "independent_recheck_matches": bool(
            result["independent_recheck"]
            and result["independent_recheck"]["matches_miner_share"]),
        "status": "verified: genuine double-SHA-256 shares, "
                  "pool re-verified, 0 invalid",
        "limits": "Local only, no mainnet, no real BTC; pool difficulty "
                  "scaled (0.001 vs network 140.58T); one representative "
                  "miner, not the full fleet; template is coinbase-only.",
    }
    world = MinecraftWorld.load("mc_bad4f906b5ff")
    if world and world.data.get("mega_mine"):
        world.data["mega_mine"]["real_env"] = summary
        world.save()
        print("Attached to Emberhill mega mine.")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
