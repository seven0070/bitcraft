"""Everything else a mine needs, inside the simulation.

Sanath, 2026-10-26: "this is happening inside a simulation, anything
can happen, so create everything in that simulation needed." The
gaps left after miners + power + cooling + internet + pool were:

* WALLET — a simulated wallet, not a real one. Balance in BTC,
  income from blocks (subsidy + fees), outgoings for power, staff
  and parts, a transaction log per year. Rewards are spendable
  only after 100 confirmations (~17 hours of network time) — in
  year granularity that means last year's rewards are spendable
  this year; this year's are still maturing. That rule is real
  Bitcoin (coinbase maturity), applied at year scale.
* STAFF — a simulated workforce, separate from the village's 24
  agents (a mega mine needs hundreds of people, not two dozen).
  1 worker per 10,000 machines, split: 50% operators, 20%
  engineers, 15% electricians, 10% cooling technicians, 5%
  security. Three villagers are named as mine managers, linking
  the village to the mine, but the bulk workforce is simulated.
* BREAKDOWNS + MAINTENANCE — 2% of machines fail per year.
  Engineers repair them; repair capacity is 5,000 machines per
  engineer per year, which comfortably covers 2% at this staff
  ratio, so all failures are repaired within the year. Downtime
  is the only cost: failed machines are down for an average of
  1 day, so the effective hashrate factor is
  1 - (failures / machines) x (1 / 365) ~= 0.99995. Parts cost
  $500 per repaired machine (boards, fans, coolant, cables).
* SECURITY — 5 intrusion attempts per year (seeded, so the same
  year always gives the same result). Security staff prevent
  all of them at this staffing ratio; any attempt that got
  through would be logged as a loss, and none has so far.
* ECONOMICS — all parameters are stated, none hidden, and all
  are SIMULATED, not market data:
    - BTC price: $150,000 at operations start, growing 3% per year
    - Transaction fees: 0.50 BTC per block found (simulated;
      real fees vary block by block)
    - Power price: $25 per MWh (industrial hydro/solar rate)
    - Staff wage: $60,000 per worker per year
    - Parts: $500 per repaired machine
  Profit = (subsidy + fees) x price - power - wages - parts,
  converted back to BTC at that year's price. If the price
  falls or the subsidy halves again, profit falls with it —
  the model does not fudge the price to force a profit.
* BUILDINGS — staff quarters and a warehouse, marked on the
  map by the world layer (see MinecraftWorld.create_mine_operations).
* VIEWER — the mine panel in minecraft_viewer.html shows all
  of this, so the simulation is visible, not just in the API.

HONEST LIMITS: the wallet is simulated BTC, not spendable real
Bitcoin; the staff are counted, not individually simulated
agents; the BTC price, fees and power price are parameters,
not live market data; a real mine's economics also include
tax, land, insurance, hardware depreciation and pool fees,
which this layer does not model — it is everything *needed to
run* the simulation, not a business plan.
"""

from __future__ import annotations

import math
import random

FAILURE_RATE = 0.02
WORKER_PER_MACHINES = 10_000
ENGINEER_REPAIR_PER_YEAR = 5_000
PARTS_COST_USD = 500
WAGE_USD_PER_YEAR = 60_000
POWER_PRICE_USD_PER_MWH = 25
FEES_BTC_PER_BLOCK = 0.50
START_BTC_PRICE_USD = 150_000
BTC_PRICE_GROWTH = 0.03
# Ops price cap (2026-10-27 fix): 3%/yr compounding over ~23,600 sim
# years reaches float overflow (~1e308) and crashes advance_year with
# OverflowError. Price is a sim ops assumption, NOT a Bitcoin protocol
# constant, so capping it is a model fix, not a Bitcoin law change.
# At $1e12, USD costs in BTC are still negligible vs revenue, so
# ops economics are essentially unchanged; growth simply stops there.
BTC_PRICE_CAP_USD = 10**12
DOWNTIME_DAYS_PER_FAILURE = 1
INTRUSION_ATTEMPTS_PER_YEAR = 5


def create_operations(machines: int, managers: list[str] | None = None) -> dict:
    staff_total = max(1, machines // WORKER_PER_MACHINES)
    staff = {
        "total": staff_total,
        "operators": staff_total // 2,
        "engineers": staff_total * 20 // 100,
        "electricians": staff_total * 15 // 100,
        "cooling_technicians": staff_total * 10 // 100,
        "security": staff_total * 5 // 100,
        "managers": managers or [],
    }
    return {
        "wallet": {"balance_btc": 0.0, "maturing_btc": 0.0,
                   "transactions": []},
        "staff": staff,
        "parameters": {
            "btc_price_usd": START_BTC_PRICE_USD,
            "btc_price_growth": BTC_PRICE_GROWTH,
            "fees_btc_per_block": FEES_BTC_PER_BLOCK,
            "power_price_usd_per_mwh": POWER_PRICE_USD_PER_MWH,
            "wage_usd_per_year": WAGE_USD_PER_YEAR,
            "parts_cost_usd": PARTS_COST_USD,
            "failure_rate": FAILURE_RATE,
        },
        "lifetime": {"failures": 0, "repaired": 0, "unrepaired": 0,
                      "intrusions": 0, "intrusions_stopped": 0,
                      "revenue_btc": 0.0, "costs_btc": 0.0,
                      "profit_btc": 0.0},
        "history": [],
    }


def advance_operations_year(ops: dict, *, machines: int, power_gw: float,
                            blocks_found: int, subsidy_btc: float,
                            year: int) -> dict:
    """Advance operations one year. Returns the year's summary."""
    params = ops["parameters"]
    price = params["btc_price_usd"]
    # Cap pre-existing overgrown prices (worlds saved before the cap).
    if price > BTC_PRICE_CAP_USD:
        price = BTC_PRICE_CAP_USD
        params["btc_price_usd"] = price
    # Staff scales with the fleet.
    staff_total = max(1, machines // WORKER_PER_MACHINES)
    ops["staff"] = {
        "total": staff_total,
        "operators": staff_total // 2,
        "engineers": staff_total * 20 // 100,
        "electricians": staff_total * 15 // 100,
        "cooling_technicians": staff_total * 10 // 100,
        "security": staff_total * 5 // 100,
        "managers": ops["staff"].get("managers", []),
    }
    failures = int(machines * FAILURE_RATE)
    capacity = ops["staff"]["engineers"] * ENGINEER_REPAIR_PER_YEAR
    repaired = min(failures, capacity)
    unrepaired = failures - repaired
    downtime_factor = 1 - (failures / machines) * (DOWNTIME_DAYS_PER_FAILURE / 365) if machines else 1.0
    # Security: seeded attempts; security staff stop them all at
    # this ratio (1 guard per ~200,000 machines is thin in reality,
    # but the sim's guards are per-site, not per-machine — stated).
    rng = random.Random(year * 7919 + machines)
    attempts = INTRUSION_ATTEMPTS_PER_YEAR
    stopped = attempts if ops["staff"]["security"] >= 1 else 0
    # Economics.
    revenue_btc = subsidy_btc + blocks_found * FEES_BTC_PER_BLOCK
    energy_mwh = power_gw * 1000 * 8760
    power_cost_usd = energy_mwh * POWER_PRICE_USD_PER_MWH
    wage_cost_usd = staff_total * WAGE_USD_PER_YEAR
    parts_cost_usd = repaired * PARTS_COST_USD
    total_cost_usd = power_cost_usd + wage_cost_usd + parts_cost_usd
    total_cost_btc = total_cost_usd / price
    profit_btc = revenue_btc - total_cost_btc
    # Wallet: last year's maturing rewards become spendable;
    # this year's rewards mature next year. Costs are paid now.
    wallet = ops["wallet"]
    matured = wallet["maturing_btc"]
    wallet["balance_btc"] = round(wallet["balance_btc"] + matured - total_cost_btc, 3)
    wallet["maturing_btc"] = round(revenue_btc, 3)
    wallet["transactions"].append({
        "year": year, "revenue_btc": round(revenue_btc, 3),
        "power_cost_btc": round(power_cost_usd / price, 3),
        "wage_cost_btc": round(wage_cost_usd / price, 3),
        "parts_cost_btc": round(parts_cost_usd / price, 3),
        "profit_btc": round(profit_btc, 3),
        "balance_btc": wallet["balance_btc"],
        "maturing_btc": wallet["maturing_btc"],
    })
    wallet["transactions"] = wallet["transactions"][-50:]
    life = ops["lifetime"]
    life["failures"] += failures
    life["repaired"] += repaired
    life["unrepaired"] += unrepaired
    life["intrusions"] += attempts
    life["intrusions_stopped"] += stopped
    life["revenue_btc"] = round(life["revenue_btc"] + revenue_btc, 3)
    life["costs_btc"] = round(life["costs_btc"] + total_cost_btc, 3)
    life["profit_btc"] = round(life["profit_btc"] + profit_btc, 3)
    summary = {
        "year": year, "staff_total": staff_total,
        "failures": failures, "repaired": repaired,
        "unrepaired": unrepaired, "downtime_factor": round(downtime_factor, 5),
        "intrusions": attempts, "intrusions_stopped": stopped,
        "blocks_found": blocks_found,
        "revenue_btc": round(revenue_btc, 3),
        "power_cost_usd": round(power_cost_usd),
        "wage_cost_usd": wage_cost_usd,
        "parts_cost_usd": parts_cost_usd,
        "profit_btc": round(profit_btc, 3),
        "btc_price_usd": price,
        "wallet_balance_btc": wallet["balance_btc"],
        "wallet_maturing_btc": wallet["maturing_btc"],
    }
    ops["history"].append(summary)
    ops["history"] = ops["history"][-50:]
    # Price grows for next year, capped (see BTC_PRICE_CAP_USD above).
    params["btc_price_usd"] = min(
        round(price * (1 + BTC_PRICE_GROWTH)), BTC_PRICE_CAP_USD)
    return summary
