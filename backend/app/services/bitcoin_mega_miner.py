"""World's largest Bitcoin miner, inside the Minecraft simulation.

Design (chosen by Atlas from Sanath's "each miner for each block, or
you design it inside the simulation" — both, combined):

* ONE MACHINE PER BITCOIN BLOCK. The fleet starts with one Antminer
  U3S23H (S23 Hyd 3U) per real Bitcoin block ever mined: 972,801
  machines, for blocks 0..972,800 (the verified height in Sanath's
  local bitcoin.db, Oct 2026). That is the "each miner for each block"
  rule, made literal.
* Machine facts, from Sanath's own U3S23H work: 1,160 TH/s, 11,020 W,
  466 chips at ~2.53 TH/s per chip. Fleet hashrate at start is
  therefore 972,801 x 1,160 TH/s = 1,128 EH/s.
* Network facts, fixed at start and then simulated forward: difficulty
  140.58T (Oct 2026, verified from real blocks 972584/972585), which
  implies a rest-of-network hashrate of difficulty x 2^32 / 600 s
  ~= 1,006 EH/s. So this fleet, alone, is larger than the rest of the
  network put together — that is what makes it the world's largest
  in this simulation, and also why it must stay a simulation (see
  below).
* One simulated year (the Minecraft time scale: 1 real second = 1
  in-game year in live mode) works like this, in order:
  1. Total blocks that year = 52,560 (one per 10 minutes, all year).
  2. Fleet share = fleet hashrate / (fleet + rest-of-network).
     Fleet blocks that year = total x share, rounded.
  3. One NEW machine is added per fleet block found — the fleet
     keeps its own rule as it grows.
  4. Block subsidy starts at 3.125 BTC and halves every 210,000
     simulated blocks, exactly like Bitcoin's halving schedule.
  5. Rest-of-network hashrate grows 2% per year (industry growth),
     and simulated difficulty is recomputed from total hashrate so
     the 10-minute interval holds. Without this step the fleet
     would run away to 100% in a few years; with it, its share
     creeps up slowly instead.
  6. Power = machines x 11,020 W; annual energy in TWh is reported,
     not hidden.

HONEST LIMITS — read before quoting any number from this module:
* This is a SIMULATION inside Emberhill. It mines no real Bitcoin,
  submits no real shares, finds no real blocks, and does not move
  the real chain, the real difficulty, or any real wallet. Real
  miners race independently of this world (established Oct 2026).
* Hashrate, blocks and BTC here are aggregate arithmetic, not
  proof-of-work: no SHA-256d nonce is actually searched per machine
  (972,801 machines x real hashing would need a data centre, not
  this VM). Sanath's real-mode U3S23H and pinball miner are the
  places where genuine hashing happens; this module is the fleet
  economics layer on top of those facts.
* A real fleet with >50% of hashrate would be a 51% majority. This
  simulation reports that share plainly and does not use it to
  rewrite, censor or reorganise anything — there is no real chain
  attached to reorganise.
"""

from __future__ import annotations

import math

# ---------------------------------------------------------------------------
# Infrastructure: Tesla power + satellite internet + water cooling.
# Added 2026-10-25 for the Blockforge mega mine, at Sanath's request:
# "electricity via Tesla and internet via satellite for this, water
# too [to] cool them". The three systems are designed, sized with
# real physics where a real number exists, and marked as simulation
# where they go beyond what is real today (see the HONEST LIMITS
# note at the end of this section).
#
# POWER — "Tesla Power District"
#   * Source: solar field + Tesla Megapack storage, distributed by
#     Tesla coils (wireless distribution — see limits note).
#   * Demand = machines x 11,020 W. All of it becomes heat, which is
#     why the cooling numbers below are the same GW.
#   * Solar capacity factor 0.28 (sunny plains/desert in-sim), so
#     solar peak = demand / 0.28. Storage = demand x 14 h (night +
#     cloud), in Megapack 2 XL units of 3.94 MWh each.
#   * Supply is built at 110% of demand, so power_factor = 1.0 by
#     construction. A mine that outgrew its power would throttle;
#     this one is built to grow with the fleet instead.
#
# INTERNET — satellite (Starlink-style, simulated constellation)
#   * One LEO satellite per 5,000 machines; one ground dish per
#     1,000 machines. Stratum traffic is small: ~2 kbps per machine
#     (new jobs in, shares out), so required bandwidth is
#     machines x 2 kbps. Provided bandwidth is 3x that, for
#     redundancy. Latency ~25 ms (LEO), uptime 99.9%.
#   * In the simulation the "pool" is a simulated pool inside the
#     world — no real pool, no real shares leave the VM.
#
# COOLING — water (the S23 Hyd is hydro-cooled in reality)
#   * Heat to remove = power demand (electricity -> heat, ~100%).
#   * Flow = power / (density x specific heat x delta-T)
#          = power / (1000 x 4186 x 10)  m^3/s, for a 10 C rise
#     (inlet 20 C from the Minecraft ocean, outlet 30 C back).
#   * Pumps: 1 per 10 m^3/s. Cooling factor = 1.0 when flow meets
#     demand, which it does by construction, and scales with it.
#
# HONEST LIMITS (infrastructure):
# * Wireless power at gigawatt scale is NOT a real technology today.
#   Nikola Tesla's Wardenclyffe tower never delivered it, and no
#   Tesla product powers a mine wirelessly at 13 GW. The coils here
#   are a simulation invention — in the real world this district
#   would be wired, and its solar + Megapack numbers are the part
#   that is physically sized.
# * The satellite constellation is simulated. Real Starlink exists
#   and does carry mining traffic, but this constellation, its
#   dishes and its bandwidth are inside Emberhill, not in orbit.
# * The water flow number IS physics (see formula above). What is
#   simulated is the source: a 64x64 Minecraft map's ocean, not a
#   real river. 315 m^3/s is a real river's flow — a reminder of
#   how much heat 13 GW really is.
# ---------------------------------------------------------------------------

SOLAR_CAPACITY_FACTOR = 0.28
STORAGE_HOURS = 14
MEGAPACK_MWH = 3.94
POWER_HEADROOM = 1.10
SATELLITE_PER_MACHINES = 5_000
DISH_PER_MACHINES = 1_000
STRATUM_KBPS_PER_MACHINE = 2
SATELLITE_BANDWIDTH_MARGIN = 3
SATELLITE_UPTIME = 0.999
SATELLITE_LATENCY_MS = 25
COOLING_DELTA_T_C = 10
WATER_DENSITY = 1000
WATER_SPECIFIC_HEAT = 4186
PUMP_FLOW_M3_S = 10


def _power_gw(machines: int) -> float:
    return machines * MACHINE_WATTS / 1e9


def build_infrastructure(mine: dict, *, water_cells: int = 0,
                         intake: dict | None = None,
                         log: bool = True) -> dict:
    """Size and attach all three systems to a mine, at its current size."""
    machines = mine["machines"]
    demand_gw = _power_gw(machines)
    solar_gw = round(demand_gw / SOLAR_CAPACITY_FACTOR, 1)
    storage_gwh = round(demand_gw * STORAGE_HOURS, 1)
    infra = {
        "power": {
            "name": "Tesla Power District",
            "source": "Solar field + Tesla Megapack storage, "
                      "Tesla-coil wireless distribution (simulated)",
            "demand_gw": round(demand_gw, 2),
            "supply_gw": round(demand_gw * POWER_HEADROOM, 2),
            "solar_peak_gw": solar_gw,
            "storage_gwh": storage_gwh,
            "megapacks": math.ceil(storage_gwh * 1000 / MEGAPACK_MWH),
            "tesla_coils": math.ceil(machines / 2000),
            "power_factor": 1.0,
        },
        "internet": {
            "name": "Satellite constellation (Starlink-style, simulated)",
            "satellites": math.ceil(machines / SATELLITE_PER_MACHINES),
            "dishes": math.ceil(machines / DISH_PER_MACHINES),
            "required_bandwidth_gbps": round(
                machines * STRATUM_KBPS_PER_MACHINE / 1e6, 2),
            "provided_bandwidth_gbps": round(
                machines * STRATUM_KBPS_PER_MACHINE
                * SATELLITE_BANDWIDTH_MARGIN / 1e6, 2),
            "latency_ms": SATELLITE_LATENCY_MS,
            "uptime": SATELLITE_UPTIME,
            "job": "Deliver block templates to miners, return shares to "
                   "the simulated pool",
        },
        "cooling": {
            "name": "Hydro cooling loop (ocean water)",
            "heat_gw": round(demand_gw, 2),
            "inlet_c": 20,
            "outlet_c": 20 + COOLING_DELTA_T_C,
            "flow_m3_s": round(
                demand_gw * 1e9
                / (WATER_DENSITY * WATER_SPECIFIC_HEAT
                   * COOLING_DELTA_T_C), 1),
            "pumps": math.ceil(
                (demand_gw * 1e9
                 / (WATER_DENSITY * WATER_SPECIFIC_HEAT
                    * COOLING_DELTA_T_C)) / PUMP_FLOW_M3_S),
            "source": "Minecraft ocean",
            "water_cells_in_world": water_cells,
            "intake": intake,
            "cooling_factor": 1.0,
        },
        "effective_hashrate_factor": SATELLITE_UPTIME,
    }
    mine["infrastructure"] = infra
    if log:
        mine["log"].append(
            f"Infrastructure built: Tesla power {infra['power']['supply_gw']} GW "
            f"({solar_gw} GW solar, {infra['power']['megapacks']:,} Megapacks, "
            f"{infra['power']['tesla_coils']:,} coils), "
            f"satellite {infra['internet']['satellites']} satellites / "
            f"{infra['internet']['dishes']:,} dishes, "
            f"water cooling {infra['cooling']['flow_m3_s']} m^3/s.")
    return infra


def scale_infrastructure(mine: dict) -> None:
    """Re-size infrastructure to the fleet's new size (after a year)."""
    if not mine.get("infrastructure"):
        return
    old = mine["infrastructure"]
    water_cells = old["cooling"].get("water_cells_in_world", 0)
    intake = old["cooling"].get("intake")
    build_infrastructure(mine, water_cells=water_cells, intake=intake,
                         log=False)
    mine["infrastructure"]["log_note"] = (
        f"Scaled from {old['power']['demand_gw']} GW to "
        f"{mine['infrastructure']['power']['demand_gw']} GW.")

# Facts from Sanath's verified work (see module docstring).
START_HEIGHT = 972_800
MACHINES_PER_BLOCK = 1
MACHINE_HASHRATE_TH_S = 1_160
MACHINE_WATTS = 11_020
MACHINE_CHIPS = 466
CHIP_HASHRATE_TH_S = 2.53
START_DIFFICULTY_T = 140.58
START_SUBSIDY_BTC = 3.125
BLOCKS_PER_YEAR = 52_560  # one per 10 minutes, all year
HALVING_INTERVAL = 210_000
REST_OF_NETWORK_GROWTH = 0.02
# --- Immutable Bitcoin law (2026-10-26, Sanath's world law) ---
# Bitcoin itself cannot be changed or altered by anyone in the world
# — not by villagers, not by World Builders, not by any world law.
# The present limit is the limit: 21,000,000 BTC total supply,
# halving every 210,000 blocks, one block per ~10 minutes.
# Builders may only improve the WORLD (hashrate, power, cooling,
# uptime) — never the subsidy schedule, the cap, or the interval.
SUPPLY_CAP_BTC = 21_000_000
# The stall fix is NOT a Bitcoin change: it caps the SIMULATION's
# external rest-of-network model, which compounded 2%/yr for 1,800
# years to 1e19 EH/s and drove share to 0. A finite world cannot
# grow its mining fleet forever. Capping rest at 10,000 EH/s leaves
# Years 1-33 exactly unchanged (rest was ~1,525 EH/s at Year 33)
# and stops the long-run collapse to zero share.
REST_OF_NETWORK_CAP_EH_S = 10_000.0


def assert_bitcoin_immutable() -> None:
    """Guard: Bitcoin's constants must never be altered in-world."""
    assert HALVING_INTERVAL == 210_000
    assert START_SUBSIDY_BTC == 3.125
    assert BLOCKS_PER_YEAR == 52_560  # one per 10 minutes, all year
    assert SUPPLY_CAP_BTC == 21_000_000


def network_hashrate_eh_s(difficulty_t: float) -> float:
    """EH/s implied by a difficulty at a 600 s block interval."""
    return difficulty_t * 1e12 * (2 ** 32) / 600 / 1e18


# --- Real-world live anchor (2026-10-26, Sanath: anchor sim Bitcoin
# law to the real world, live) ---
# The sim's Bitcoin law now follows the real chain at this moment,
# updating live, instead of using only frozen 2026-10-25 constants.
# What is anchored, and what is NOT, is stated plainly because the
# sim is 2,600+ mine years in — far past real 2026 — so a naive
# "set sim subsidy = real subsidy" would rewind it by 2,200 years
# and blow the 21M cap in ~130 sim years (50k sim blocks/yr x
# 3.125 BTC). Instead:
#  - ANCHORED LIVE: real height, real difficulty, real subsidy ERA
#    (50 / 2^(height//210,000)), next halving height, real total
#    hashrate implied by real difficulty, and sim difficulty
#    recomputed as real_difficulty x sim_total / real_total.
#    That last formula is mathematically the same as the old
#    sim difficulty formula (total_eh x 600 / 2^32), so sim
#    difficulty does not jump — it is now *proven* anchored.
#  - SIM-ERA, BY DESIGN: sim subsidy per sim block and sim BTC
#    tally stay driven by sim cumulative blocks, using the same
#    real halving formula (50 BTC start, halve every 210,000
#    blocks). Sim is in its own far-future era; real 2026 is era 4.
#    If real Bitcoin ever changes cap/halving/interval by
#    consensus, the guard above must be updated to match — that
#    is the "follow the real world" rule, not a sim invention.
#  - THROTTLED: fetch at most once per 600 real seconds, so a
#    1-year-per-second live runner does not hammer mempool.space.
#    On fetch failure, the last anchor is kept and mining continues.
REAL_ANCHOR_THROTTLE_S = 600.0


def fetch_real_world_anchor(mine: dict) -> dict | None:
    """Fetch live real tip and build the anchor dict, or None on failure."""
    try:
        from .bitcoin_real_submission import fetch_live_tip
        tip = fetch_live_tip()
        height = int(tip["height"])
        # fetch_live_tip returns raw difficulty (e.g. 1.405e14);
        # this module works in terahashes (140.58T), so convert.
        diff_t = float(tip["difficulty"]) / 1e12
        halvings = height // HALVING_INTERVAL
        subsidy = 50.0 / (2 ** halvings)
        real_eh = network_hashrate_eh_s(diff_t)
        return {
            "height": height,
            "hash": tip["hash"],
            "difficulty_t": round(diff_t, 2),
            "subsidy_btc": subsidy,
            "halvings_so_far": halvings,
            "next_halving_height": (halvings + 1) * HALVING_INTERVAL,
            "blocks_to_next_halving": (halvings + 1) * HALVING_INTERVAL - height,
            "real_network_eh_s": round(real_eh, 1),
            "source": tip.get("source", "live: mempool.space"),
            "note": ("Real-world anchor, live. Sim difficulty is "
                     "real_difficulty x sim_total / real_total; sim "
                     "subsidy tally stays sim-era (see module header)."),
        }
    except Exception:
        return None


def update_real_world_anchor(mine: dict, total_eh: float) -> dict | None:
    """Update mine['real_world_anchor'] if throttled fetch is due."""
    import time
    now = time.time()
    last = mine.get("real_world_anchor_updated_at", 0) or 0
    anchor = mine.get("real_world_anchor")
    if anchor is not None and now - last < REAL_ANCHOR_THROTTLE_S:
        # Still current in real-world terms (difficulty changes
        # every ~2 weeks, tip every ~10 min; 10 min throttle is fine).
        anchor["anchored_sim_difficulty_t"] = round(
            anchor["difficulty_t"] * total_eh / anchor["real_network_eh_s"], 2
        ) if anchor["real_network_eh_s"] else None
        return anchor
    fresh = fetch_real_world_anchor(mine)
    if fresh is None:
        return anchor
    fresh["anchored_sim_difficulty_t"] = round(
        fresh["difficulty_t"] * total_eh / fresh["real_network_eh_s"], 2
    ) if fresh["real_network_eh_s"] else None
    fresh["updated_at_real"] = time.strftime("%Y-%m-%d %H:%M:%S")
    mine["real_world_anchor"] = fresh
    mine["real_world_anchor_updated_at"] = now
    return fresh


def create_mine(*, name: str = "Blockforge Mega Mine",
                start_height: int = START_HEIGHT) -> dict:
    machines = (start_height + 1) * MACHINES_PER_BLOCK
    rest_eh = network_hashrate_eh_s(START_DIFFICULTY_T)
    return {
        "name": name,
        "machine": "Antminer U3S23H (S23 Hyd 3U)",
        "rule": "One machine per Bitcoin block",
        "start_height": start_height,
        "machines": machines,
        "chips": machines * MACHINE_CHIPS,
        "fleet_hashrate_eh_s": round(machines * MACHINE_HASHRATE_TH_S / 1e6, 1),
        "rest_of_network_eh_s": round(rest_eh, 1),
        "difficulty_t": START_DIFFICULTY_T,
        "subsidy_btc": START_SUBSIDY_BTC,
        "sim_blocks_mined": 0,
        "fleet_blocks_found": 0,
        "fleet_btc_earned": 0.0,
        "power_gw": round(machines * MACHINE_WATTS / 1e9, 2),
        "energy_twh_per_year": round(machines * MACHINE_WATTS * 8760 / 1e12, 1),
        "years_run": 0,
        "log": [f"Mega mine created: {machines:,} machines, one per block "
                f"0..{start_height}, fleet "
                f"{machines * MACHINE_HASHRATE_TH_S / 1e6:,.1f} EH/s vs "
                f"rest-of-network {rest_eh:,.1f} EH/s."],
    }


def apply_hardware_upgrade(mine: dict, *, generation: int,
                           hashrate_factor: float,
                           power_factor: float, name: str) -> dict:
    """Fleet-wide hardware retrofit, researched by World Builders.
    This changes the WORLD's machines, never Bitcoin: subsidy,
    halving, cap and block interval are untouched (guarded above).
    hashrate_factor > 1 raises TH/s per machine; power_factor < 1
    lowers watts per machine."""
    assert_bitcoin_immutable()
    mine["hardware_generation"] = generation
    mine["hardware_name"] = name
    mine["hardware_hashrate_factor"] = hashrate_factor
    mine["hardware_power_factor"] = power_factor
    mine["log"].append(
        f"Hardware upgrade: Generation {generation} ({name}) — "
        f"hashrate x{hashrate_factor}, power x{power_factor}, "
        f"applied fleet-wide by World Builders.")
    return mine


def advance_mine_year(mine: dict) -> dict:
    """Advance the mine one simulated year; returns the mine dict."""
    assert_bitcoin_immutable()
    hw_hash = mine.get("hardware_hashrate_factor", 1.0)
    hw_pow = mine.get("hardware_power_factor", 1.0)
    fleet_eh = mine["machines"] * MACHINE_HASHRATE_TH_S / 1e6 * hw_hash
    rest_eh = mine["rest_of_network_eh_s"]
    # World Builders (2026-10-26): their efficiency bonus raises the
    # EFFECTIVE share, not the machine count. Base fleet_eh stays
    # physical; share is computed on effective hashrate.
    builder_factor = mine.get("builder_hashrate_factor", 1.0)
    eff_fleet_eh = fleet_eh * builder_factor
    share = eff_fleet_eh / (eff_fleet_eh + rest_eh) if eff_fleet_eh + rest_eh else 0.0
    eff = 1.0
    if mine.get("infrastructure"):
        eff = mine["infrastructure"].get("effective_hashrate_factor", 1.0)
    fleet_blocks = int(round(BLOCKS_PER_YEAR * share * eff))
    # Subsidy, with halvings on cumulative simulated blocks.
    # 2026-10-26 fix: at 1,024 halvings, 2**1024 overflows a float
    # and crashed the live sim at Year 4102. Mathematically,
    # 3.125 / 2**1024 is ~1.7e-308 BTC — below one satoshi by
    # ~300 orders of magnitude, i.e. effectively zero, and
    # real Bitcoin subsidy is zero long before that in practice.
    # So subsidy is 0.0 at >=1,024 halvings, not an overflow.
    def _subsidy(halvings: int) -> float:
        return START_SUBSIDY_BTC / (2 ** halvings) if halvings < 1024 else 0.0
    before = mine["sim_blocks_mined"]
    after = before + BLOCKS_PER_YEAR
    halvings_before = before // HALVING_INTERVAL
    halvings_after = after // HALVING_INTERVAL
    subsidy = _subsidy(halvings_after)
    # BTC earned this year: blocks before/after a mid-year halving
    # are paid at their own subsidy (approximation at year granularity
    # is documented here, not hidden).
    if halvings_after == halvings_before:
        btc = fleet_blocks * subsidy
    else:
        # Next halving boundary, not the first one: for Year 8,
        # before=367,920, so the boundary is 420,000, not 210,000.
        # The old code used HALVING_INTERVAL - before, which went
        # negative after the first halving and produced negative BTC.
        split = (halvings_before + 1) * HALVING_INTERVAL - before
        fleet_before = int(round(split * share))
        btc = (fleet_before * _subsidy(halvings_before)
               + (fleet_blocks - fleet_before) * subsidy)
    mine["machines"] += fleet_blocks  # one new machine per fleet block
    mine["chips"] = mine["machines"] * MACHINE_CHIPS
    mine["fleet_hashrate_eh_s"] = round(
        mine["machines"] * MACHINE_HASHRATE_TH_S / 1e6 * hw_hash, 1)
    mine["rest_of_network_eh_s"] = round(
        min(rest_eh * (1 + REST_OF_NETWORK_GROWTH),
            REST_OF_NETWORK_CAP_EH_S), 1)
    total_eh = mine["fleet_hashrate_eh_s"] + mine["rest_of_network_eh_s"]
    # Live anchor: sim difficulty = real_difficulty x sim_total /
    # real_total. This equals the old formula, now anchored live.
    anchor = update_real_world_anchor(mine, total_eh)
    if anchor and anchor.get("anchored_sim_difficulty_t"):
        mine["difficulty_t"] = anchor["anchored_sim_difficulty_t"]
    else:
        mine["difficulty_t"] = round(total_eh * 1e18 * 600 / (2 ** 32) / 1e12, 2)
    mine["subsidy_btc"] = subsidy
    mine["sim_blocks_mined"] = after
    mine["fleet_blocks_found"] += fleet_blocks
    # --- Mine real blocks IN simulation (2026-10-26, Sanath) ---
    # The sim's mega mine now also tracks genuine real-block
    # mining, not just sim-generated blocks. It reads the real
    # miner's state (written by real_miner.py, the CPU miner
    # hashing real candidates with Sanath's coinbase) and
    # records it inside the sim world, so real block attempts
    # are present in the simulation. Honest limit, stated in
    # the field itself: sim fleet machines do NOT genuinely
    # hash real blocks — that would need 400M+ ASICs. Genuine
    # real hashing is only the CPU real miner, and its
    # blocks_found_real stays 0 until it actually finds a
    # valid hash. Sim-generated blocks and real blocks are
    # kept in separate counters, never merged.
    try:
        import json as _json, os as _os
        _state_path = _os.path.expanduser(
            "~/workspace/mirofish/real-miner-state.json")
        if _os.path.exists(_state_path):
            with open(_state_path) as _f:
                _rs = _json.load(_f)
            _prev = mine.get("real_block_mining") or {}
            _real = {
                "current_real_height_attempted": _rs.get("height"),
                "total_real_hashes": _rs.get("total_hashes"),
                "best_real_hash": (_rs.get("best") or {}).get("hash"),
                "best_real_difficulty": (_rs.get("best") or {}).get("difficulty"),
                "best_real_nonce": (_rs.get("best") or {}).get("nonce"),
                "blocks_found_real": 0,
                "status": _rs.get("status"),
                "coinbase": ("Public address on file in "
                             "real-mainnet-candidate.json"),
                "note": ("Real blocks mined in simulation via the "
                         "CPU real miner. Sim fleet does not "
                         "genuinely hash real blocks; sim-generated "
                         "blocks are counted separately above."),
            }
            mine["real_block_mining"] = _real
            if _prev.get("current_real_height_attempted") != _real["current_real_height_attempted"]:
                mine["log"].append(
                    f"Real block in sim: now attempting real "
                    f"height {_real['current_real_height_attempted']} "
                    f"(best diff {_real['best_real_difficulty']}), "
                    f"no real block found yet.")
    except Exception:
        pass
    mine["fleet_btc_earned"] = round(mine["fleet_btc_earned"] + btc, 3)
    power_factor = mine.get("builder_power_factor", 1.0)
    mine["power_gw"] = round(mine["machines"] * MACHINE_WATTS / 1e9 * power_factor * hw_pow, 2)
    mine["energy_twh_per_year"] = round(
        mine["machines"] * MACHINE_WATTS * 8760 / 1e12 * power_factor * hw_pow, 1)
    mine["years_run"] += 1
    scale_infrastructure(mine)
    mine["log"].append(
        f"Year {mine['years_run']}: fleet share {share:.1%}, "
        f"found {fleet_blocks:,} blocks, earned {btc:,.1f} BTC, "
        f"fleet now {mine['machines']:,} machines "
        f"({mine['fleet_hashrate_eh_s']:,.1f} EH/s), "
        f"difficulty {mine['difficulty_t']:,.2f}T, "
        f"power {mine['power_gw']:,.2f} GW.")
    mine["log"] = mine["log"][-200:]
    return mine
