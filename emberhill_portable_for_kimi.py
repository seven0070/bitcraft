#!/usr/bin/env python3
"""
Emberhill — portable simulation, built to run inside Kimi
the same way it runs inside Muse (Atlas).

This is a SELF-CONTAINED, stdlib-only copy of the Emberhill
Minecraft-like world + Blockforge Mega Mine logic.
No backend, no venv, no database, no wallet, no private keys,
no real Bitcoin mining, no pool submission.
SIMULATION ONLY: sim blocks, sim BTC tally, sim machines,
sim power — never real BTC, never a real block.

How to run (in Kimi, or anywhere with Python 3):
  python3 emberhill_portable_for_kimi.py [years]
  default years = 100
  prints a summary every 10 years, and a final JSON state.

Rules copied from Emberhill (Muse version):
- Terrain: 64x64, seeded "mirofish", biomes ocean/beach/plains/
  forest/desert/mountains/snow (deterministic, simplified).
- Time: 1 advance = 1 sim year (Muse live runner: 1 real sec = 1 sim year).
- Villagers: 12 + Steve (Miner) + Alex (Lumberjack), roles
  Farmer/Builder/Explorer/Trader/Engineer/Guard/Villager.
  Giant aging: +0.1 giant-year/year, die at 80, 25% risk from 70.
  Generations: +5% output per generation, capped at 2x.
  Births every year if houses > alive (2 if houses-alive >= 10).
- Mega mine: 1 simulated U3S23H per real Bitcoin block at genesis:
  972,801 machines, 1,160 TH/s, 11,020 W each.
  Yearly: 52,560 sim blocks/year, fleet share = fleet EH /
  (fleet EH + rest EH, rest capped at 10,000 EH/s),
  fleet blocks = share * 52,560, machines += fleet blocks,
  subsidy starts 3.125 BTC, halving every 210,000 sim blocks,
  cap 21,000,000 BTC asserted immutable (builders may change
  only hashrate/power/cooling/uptime, never cap/subsidy/schedule).
- World Builders (simulated representations, not real people):
  Adam Back / Jihan Wu / Micree Zhan / Elon Musk / Jensen Huang /
  Pieter Wuille — bonuses x1.17 hashrate, x0.93 power.
- Gen2 hardware (simulated): x1.25 hashrate, x0.85 power.
- Real anchor (fixed, for a portable run): real difficulty
  140.58T, real network 1,006.3 EH/s, real subsidy era 3.125,
  next halving 1,050,000. This is a reference only; sim
  difficulty is computed from sim total hashrate, not copied
  from real difficulty.
"""
import sys, json, hashlib, random

SEED = "mirofish"
BLOCKS_PER_YEAR = 52560
CAP_BTC = 21_000_000
HALVING_INTERVAL = 210_000
START_SUBSIDY = 3.125
REST_CAP_EH = 10_000.0
MACHINE_TH_S = 1160.0
MACHINE_W = 11020.0
BUILDER_HASH = 1.17
BUILDER_POWER = 0.93
GEN2_HASH = 1.25
GEN2_POWER = 0.85

def make_world():
    rnd = random.Random(SEED)
    terrain = []
    for y in range(64):
        row = []
        for x in range(64):
            h = hashlib.sha256(f"{SEED}-{x}-{y}".encode()).digest()[0] / 255.0
            biome = "ocean" if h < 0.20 else "beach" if h < 0.28 else "plains" if h < 0.55 else "forest" if h < 0.70 else "desert" if h < 0.80 else "mountains" if h < 0.92 else "snow"
            row.append(biome)
        terrain.append(row)
    agents = []
    roles = ["Farmer", "Builder", "Explorer", "Trader", "Engineer", "Guard", "Villager", "Villager", "Villager", "Villager", "Villager", "Villager"]
    names = ["Maya", "Arjun", "Noor", "Leo", "Ira", "Kabir", "Zoe", "Ravi", "Asha", "Dev", "Lena", "Omar"]
    for i, role in enumerate(roles):
        agents.append({"name": names[i], "role": role, "age": 2.5, "generation": 1, "alive": True})
    agents.append({"name": "Steve", "role": "Miner", "age": 2.5, "generation": 1, "alive": True})
    agents.append({"name": "Alex", "role": "Lumberjack", "age": 2.5, "generation": 1, "alive": True})
    mine = {
        "machines": 972801,
        "fleet_blocks_found": 0,
        "sim_blocks_mined": 0,
        "fleet_btc_earned": 0.0,
        "years_run": 0,
    }
    return {"year": 0, "terrain": terrain, "agents": agents,
            "houses": 12, "farms": 1, "mineshafts": 1, "workshops": 1,
            "stats": {"mined": 6, "wood": 10, "wheat": 24, "built": 12, "crafted": 2, "explored": 113, "trades": 0},
            "mega_mine": mine, "seed": SEED}

def gen_mult(gen):
    return min(2.0, 1 + 0.05 * (gen - 1))

def advance_year(w):
    # Villagers: outputs, aging, births, deaths
    alive = [a for a in w["agents"] if a["alive"]]
    rnd = random.Random(f"{SEED}-{w['year']}")
    for a in alive:
        m = gen_mult(a["generation"])
        if a["role"] == "Miner": w["stats"]["mined"] += round(57 * m)
        elif a["role"] == "Lumberjack": w["stats"]["wood"] += round(80 * m)
        elif a["role"] == "Farmer": w["stats"]["wheat"] += round(200 * m)
        elif a["role"] == "Builder": w["stats"]["built"] += round(3 * m); w["houses"] += round(3 * m)
        elif a["role"] == "Explorer": w["stats"]["explored"] += round(10 * m)
        elif a["role"] == "Trader": w["stats"]["trades"] += round(5 * m)
        elif a["role"] == "Engineer": w["stats"]["crafted"] += round(2 * m)
    # Aging / deaths (giant years)
    for a in alive:
        a["age"] += 0.1
        if a["age"] >= 80 or (a["age"] >= 70 and rnd.random() < 0.25):
            a["alive"] = False
    alive = [a for a in w["agents"] if a["alive"]]
    # Births
    if w["houses"] > len(alive):
        n = 2 if w["houses"] - len(alive) >= 10 else 1
        max_gen = max([a["generation"] for a in w["agents"]], default=1)
        for i in range(n):
            w["agents"].append({"name": f"Gen{max_gen+1}-{i}", "role": "Villager", "age": 1.8, "generation": max_gen + 1, "alive": True})
    # Mega mine
    mine = w["mega_mine"]
    eff_th = MACHINE_TH_S * GEN2_HASH * BUILDER_HASH
    fleet_eh = mine["machines"] * eff_th / 1e6  # TH/s -> EH/s: 1 EH = 1e6 TH
    # Rest of network: +2%/yr, capped at 10,000 EH/s (reaches cap after ~115 years)
    rest_eh = min(REST_CAP_EH, 1006.3 * (1.02 ** mine["years_run"]))
    total_eh = fleet_eh + rest_eh
    share = fleet_eh / total_eh if total_eh else 0
    fleet_blocks = round(share * BLOCKS_PER_YEAR)
    before = mine["sim_blocks_mined"]
    after = before + BLOCKS_PER_YEAR
    # Subsidy with halving, overflow-safe (0 after 1024 halvings)
    halvings_before = before // HALVING_INTERVAL
    halvings_after = after // HALVING_INTERVAL
    if halvings_before >= 1024:
        subsidy = 0.0
    else:
        subsidy = START_SUBSIDY / (2 ** halvings_before)
    # BTC for fleet blocks this year, split at halving if needed
    if halvings_after == halvings_before:
        btc = fleet_blocks * subsidy
    else:
        split = (halvings_before + 1) * HALVING_INTERVAL - before
        frac = split / BLOCKS_PER_YEAR if BLOCKS_PER_YEAR else 0
        btc = fleet_blocks * frac * subsidy
        if halvings_after < 1024:
            btc += fleet_blocks * (1 - frac) * (START_SUBSIDY / (2 ** halvings_after))
    # Cap guard
    if mine["fleet_btc_earned"] + btc > CAP_BTC:
        btc = max(0.0, CAP_BTC - mine["fleet_btc_earned"])
    mine["sim_blocks_mined"] = after
    mine["fleet_blocks_found"] += fleet_blocks
    mine["fleet_btc_earned"] = round(mine["fleet_btc_earned"] + btc, 3)
    mine["machines"] += fleet_blocks
    mine["years_run"] += 1
    mine["fleet_hashrate_eh_s"] = round(fleet_eh, 1)
    mine["rest_hashrate_eh_s"] = round(rest_eh, 1)
    mine["share"] = round(share, 4)
    mine["difficulty_t"] = round(total_eh * 1e18 * 600 / (2 ** 32) / 1e12, 2)
    mine["power_gw"] = round(mine["machines"] * MACHINE_W / 1e9 * BUILDER_POWER * GEN2_POWER, 2)
    mine["subsidy_btc"] = subsidy
    w["year"] += 1
    return w

def summary(w):
    m = w["mega_mine"]
    alive = sum(1 for a in w["agents"] if a["alive"])
    return (f"Year {w['year']}: {alive}/{len(w['agents'])} alive, {w['houses']} houses, "
            f"mined {w['stats']['mined']}, mega mine {m['machines']:,} machines, "
            f"{m['fleet_blocks_found']:,} fleet blocks, {m['fleet_btc_earned']:,.3f} sim BTC, "
            f"share {m.get('share', 0):.1%}, difficulty {m.get('difficulty_t', 0):,.2f}T, "
            f"power {m.get('power_gw', 0):,.2f} GW")

def load_full_state(path):
    with open(path) as f:
        s = json.load(f)
    w = make_world()
    # Overwrite with saved full state (agents, houses, stats, mine, year)
    # Terrain is regenerated deterministically from seed, same as original.
    for k in ("year", "agents", "houses", "farms", "mineshafts", "workshops", "stats", "mega_mine"):
        if k in s:
            w[k] = s[k]
    return w

def full_state(w):
    return {"year": w["year"], "agents": w["agents"], "houses": w["houses"],
            "farms": w["farms"], "mineshafts": w["mineshafts"], "workshops": w["workshops"],
            "stats": w["stats"], "mega_mine": w["mega_mine"], "seed": SEED,
            "alive": sum(1 for a in w["agents"] if a["alive"])}

def main():
    # Usage: python3 emberhill_portable_for_kimi.py [years] [--resume state.json] [--save out.json]
    args = sys.argv[1:]
    years = 100
    resume = None
    save = None
    i = 0
    while i < len(args):
        if args[i] == "--resume" and i + 1 < len(args):
            resume = args[i + 1]; i += 2
        elif args[i] == "--save" and i + 1 < len(args):
            save = args[i + 1]; i += 2
        else:
            try: years = int(args[i])
            except ValueError: pass
            i += 1
    if resume:
        w = load_full_state(resume)
        print(f"Emberhill portable sim — RESUMED from Year {w['year']} (file {resume}). SIMULATION ONLY, not real Bitcoin.")
    else:
        w = make_world()
        print("Emberhill portable sim — SIMULATION ONLY, not real Bitcoin.")
        print(f"Seed {SEED}, start: 972,801 machines, 12+2 villagers, 12 houses.")
    for i in range(years):
        advance_year(w)
        if (i + 1) % 10 == 0 or i == 0:
            print(summary(w))
    print("FINAL_STATE_JSON:")
    fs = full_state(w)
    print(json.dumps(fs, indent=1))
    if save:
        with open(save, "w") as f:
            json.dump(fs, f, indent=1)
        print(f"Saved full state to {save}")

if __name__ == "__main__":
    main()
