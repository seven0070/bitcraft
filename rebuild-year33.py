"""Rebuild Emberhill as a Year 32 checkpoint, then the engine advances it to Year 33.
NOT an exact restore: no Year 32 save file exists. Mine numbers are the
verified Year 32 record; village/stats are reconstructed and labelled so.
Source backup: mc_bad4f906b5ff-before-time-travel.json (Year 2032, kept intact).
"""
import json, copy

SRC = "/home/hatch/workspace/mirofish/backend/app/uploads/minecraft_worlds/mc_bad4f906b5ff-before-time-travel.json"
DST = "/home/hatch/workspace/mirofish/backend/app/uploads/minecraft_worlds/mc_bad4f906b5ff.json"
d = json.load(open(SRC))

# --- World year / village: reconstructed Year 32 ---
d["year"] = 32
d["day"] = 3
d["hour"] = 6
# First 28 agents ever = the Year 32 population (28/28 alive then).
# Ages/inventories are reconstructed, not the originals: dead agents'
# stored ages are ages at death, so cap at 75 and mark alive.
agents = d["agents"][:28]
for i, a in enumerate(agents):
    a["alive"] = True
    # Giants' age: human age / 10, so a 75-year-old human becomes a
    # 7.5-year-old giant (800 sim years to live, not a dying elder).
    a["age"] = round(min(a.get("age", 40), 75) / 10.0, 1)
    a["generation"] = 1 if i < 12 else 2
    a["hunger"] = 100
    a["health"] = 100
d["agents"] = agents
d["aging"] = "giant"
d["structures"] = {"houses": 74, "farms": 1, "mineshafts": 1, "workshops": 1}
d["stats"] = {"mined": 1773, "wood_chopped": 2600, "wheat_grown": 6400,
              "built": 74, "crafted": 160, "trades": 300, "explored": 2000}

# --- World law: Bitcoin immutable (Sanath, 2026-10-26) ---
d["world_laws"] = {"bitcoin": {
    "bitcoin_immutable": True,
    "aim": "Make the world mine more, faster, easier, more effectively and more efficiently, without changing Bitcoin itself.",
    "supply_cap_btc": 21000000,
    "halving_interval_blocks": 210000,
    "target_block_interval_minutes": 10,
    "builders_may_change": ["hashrate", "power", "cooling", "uptime", "repair", "world efficiency"],
    "builders_may_not_change": ["bitcoin supply cap", "subsidy", "halving schedule", "block interval", "Bitcoin protocol"],
    "note": "The present Bitcoin limit is the limit. No being in this world can change Bitcoin or alter it.",
}}

# --- Mine: verified Year 32 record (mine Year 21) ---
m = d["mega_mine"]
m.update({
    "machines": 1575014,
    "chips": 1575014 * 466,
    "fleet_hashrate_eh_s": 1827.0,
    "rest_of_network_eh_s": 1525.1,
    "difficulty_t": 468.28,
    "subsidy_btc": 0.09765625,
    "sim_blocks_mined": 21 * 52560,
    "fleet_blocks_found": 602213,
    "fleet_btc_earned": 685296.288,
    "power_gw": 16.14,  # 1575014*11020/1e9 * 0.93 (renowned builders)
    "energy_twh_per_year": 141.4,
    "years_run": 21,
    "builder_hashrate_factor": 1.17,
    "builder_power_factor": 0.93,
    "builder_bonuses": {"builders": 6, "focus_counts": {"hashrate": 3, "uptime": 1, "power": 1, "cooling": 1},
                        "hashrate_bonus_pct": 17.0, "hashrate_factor": 1.17,
                        "power_saving_pct": 7.0, "power_factor": 0.93},
    "log": ["Checkpoint rebuilt 2026-10-26: Year 32, from the verified record. "
            "Mine numbers exact; village/stats reconstructed (no Year 32 save existed). "
            "World law: Bitcoin immutable. Rest-of-network capped at 10,000 EH/s (simulation model, not Bitcoin).",
            "Year 21: fleet share 56.4%, found 29,627 blocks, earned 2,893.3 BTC, "
            "fleet now 1,575,014 machines (1,827.0 EH/s), difficulty 468.28T, power 16.66 GW."],
})
# Builders: keep the renowned six already in the file (verified above).
assert len(d["world_builders"]) == 6, d["world_builders"]
d["time_dilation"] = {"years_per_second": 1.0, "set_by": "Atlas (test restore)",
                      "note": "1.0 in-game year(s) per real second in live mode"}

# --- Operations: recorded Years 25-32 (from the Year 32 verification) ---
def op(year, blocks, revenue, power, wages, parts, profit, wallet, maturing, staff, failures):
    return {"year": year, "blocks_found": blocks, "revenue_btc": revenue,
            "power_cost_usd": power, "wage_cost_usd": wages, "parts_cost_usd": parts,
            "profit_btc": profit, "wallet_balance_btc": wallet, "wallet_maturing_btc": maturing,
            "staff_total": staff, "failures": failures, "repaired": failures, "unrepaired": 0,
            "downtime_factor": 0.99995, "intrusions": 5, "intrusions_stopped": 5,
            "btc_price_usd": {25: 150000, 26: 154500, 27: 159135, 28: 163909,
                              29: 168826, 30: 173891, 31: 179108, 32: 184481}[year]}
hist = [
    op(25, 28578, 25452.281, 3302520000, 8160000, 13686500, 3289.838, -22162.443, 25452.281, 136, 27373),
    op(26, 28595, 25467.422, 3372600000, 8340000, 13972500, 3493.878, -18683.706, 25467.422, 139, 27945),
    op(27, 29604, 26266.062, 3306900000, 8520000, 14268500, 5342.390, -14139.956, 26266.062, 142, 28537),
    op(28, 29619, 20594.461, 3374790000, 8700000, 14564500, -136.887, -8605.242, 20594.461, 145, 29129),
    op(29, 29629, 20601.414, 3442680000, 8880000, 14861000, 68.907, -8543.288, 20601.414, 148, 29722),
    op(30, 29633, 20604.195, 3512760000, 9060000, 15157500, 263.996, -8282.073, 20604.195, 151, 30315),
    op(31, 29632, 20540.316, 3580650000, 9240000, 15453500, 410.877, -7807.317, 20540.316, 154, 30907),
    op(32, 29627, 17706.762, 3648540000, 9420000, 15750000, -2206.996, -7180.759, 17706.762, 157, 31500),
]
ops = m.get("operations", {})
ops.update({
    "history": hist,
    "wallet": {"balance_btc": -7180.759, "maturing_btc": 17706.762, "transactions": hist},
    "lifetime": {"revenue_btc": 177232.913, "costs_btc": 166706.91, "profit_btc": 10526.003,
                 "failures": 235428, "repaired": 235428, "unrepaired": 0,
                 "intrusions": 40, "intrusions_stopped": 40},
    "staff": {"total": 157, "operators": 78, "engineers": 31, "electricians": 23,
              "cooling_technicians": 15, "security": 7, "managers": ["AIBuilders", "Policymakers", "Steve"]},
    "parameters": {"btc_price_usd": 184481, "btc_price_growth": 0.03, "failure_rate": 0.02,
                   "fees_btc_per_block": 0.5, "parts_cost_usd": 500,
                   "power_price_usd_per_mwh": 25, "wage_usd_per_year": 60000},
})
m["operations"] = ops
d["log"] = ["Checkpoint rebuilt 2026-10-26: time travel to Year 32 (reconstruction, "
            "mine numbers from the verified record), Bitcoin immutable law set, "
            "rest-of-network cap 10,000 EH/s applied. Present Year 2032 state kept in "
            "mc_bad4f906b5ff-before-time-travel.json."]

json.dump(d, open(DST, "w"))
print("checkpoint written: year", d["year"], "machines", m["machines"], "blocks", m["fleet_blocks_found"], "btc", m["fleet_btc_earned"])
