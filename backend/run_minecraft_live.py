"""Live Minecraft runner: 1 real second = 1 in-game year.

Usage:
    NO_PROXY=localhost,127.0.0.1 .venv/bin/python run_minecraft_live.py <world_id> [seconds]

The runner loops: load the world, advance one year, save, sleep 1
second. Stop it with Ctrl+C, or by creating the stop file
``/tmp/minecraft-live-<world_id>.stop`` — the runner checks for it
every second and exits cleanly. It is a plain background process, not
a cron: a VM replacement stops it, and it must be restarted by hand.

This is the honest version of "1 second = 1 year": each second is one
aggregated year (see MinecraftWorld.advance_year), not 8,760 hourly
ticks — the hourly engine could never run a full year per second.
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1")
os.environ.setdefault("no_proxy", "localhost,127.0.0.1")

from app.services.minecraft_world import MinecraftWorld  # noqa: E402


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: run_minecraft_live.py <world_id> [seconds]")
        return 2
    world_id = sys.argv[1]
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    stop_file = f"/tmp/minecraft-live-{world_id}.stop"
    if os.path.exists(stop_file):
        os.remove(stop_file)
    print(f"Live mode: world {world_id}, 1 second = 1 year. "
          f"Stop file: {stop_file}")
    elapsed = 0
    while True:
        world = MinecraftWorld.load(world_id)
        if world is None:
            print(f"World not found: {world_id}")
            return 1
        summary = world.advance_year(1)
        alive = sum(1 for a in summary["agents"] if a["alive"])
        mine = summary.get("mega_mine")
        mine_txt = (f", mega mine {mine['machines']:,} machines, "
                    f"{mine['fleet_blocks_found']:,} blocks, "
                    f"{mine['fleet_btc_earned']:,.0f} BTC" if mine else "")
        print(f"Year {summary['year']}: {alive}/{len(summary['agents'])} "
              f"alive, {summary['structures']['houses']} houses, "
              f"mined {summary['stats']['mined']}{mine_txt}", flush=True)
        elapsed += 1
        if limit and elapsed >= limit:
            break
        time.sleep(1)
        if os.path.exists(stop_file):
            print("Stop file seen, exiting live mode.")
            break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
