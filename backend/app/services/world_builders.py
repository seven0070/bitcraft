"""World Builders for Bitcraft / Emberhill — Sanath, 2026-10-26.

Concept, in his words: world builders of this reality build this
bitcraft; everyone's goal is to mine; the world builders' goal is to
make the world mine more, faster, easier, more effectively and more
efficiently; world builders from the real world are picked and asked
to build; and they can also set the time dilation period in the
simulation.

What this module actually does (simulation only):
* A World Builder is a picked person/role whose ONE job is mining
  efficiency. Builders are appointed, not spawned at random: either
  an existing villager is promoted (their name/role are already in
  the world), or an external builder is added by name — and in that
  case the name must be supplied by Sanath. This module invents NO
  real person's name. A builder with no supplied name is recorded
  as "Unnamed picked builder", never as a real person.
* Each builder contributes, per year, to the mega mine:
    base: +2% effective hashrate, -1% power demand
    focus bonus: +1% extra to their focus area
    focuses: hashrate, power, cooling, repair, uptime
  Caps (so builders cannot run away to infinity):
    total hashrate bonus capped at +25%, power saving at -20%.
  These are simulation parameters, not real hardware gains: a
  +2% in this model means better tuning, less downtime, better
  cooling layout and fewer failed machines in-sim, not a new ASIC.
* Time dilation: a builder-set clock for live mode.
    time_dilation.years_per_second = D means D in-game years pass
    per real second in live mode. The default is 1 (the scale set
    2026-10-25). D is clamped to [0.1, 100]. D > 1 ages villagers
    faster (they die at 80, as before) — a high dilation is a
    trade-off, not a free lunch, and the setter is recorded.
  This is a simulation clock, not relativistic time dilation:
  nothing in real physics changes when D changes.

Honest limits: builders are counted roles with stated bonuses.
They do not mine real Bitcoin, do not change real difficulty,
and do not make a real machine faster. Their effect is visible
only inside Emberhill/Blockforge's aggregate arithmetic.
"""

from __future__ import annotations

import uuid

FOCUSES = ("hashrate", "power", "cooling", "repair", "uptime")
BASE_HASHRATE_PCT = 2.0
BASE_POWER_PCT = -1.0  # negative = saving
FOCUS_EXTRA_PCT = 1.0
MAX_HASHRATE_PCT = 25.0
MAX_POWER_SAVING_PCT = 20.0
MIN_DILATION = 0.1
MAX_DILATION = 100.0


def create_builder(name: str | None = None, *, origin: str = "picked",
                   focus: str = "hashrate", picked_by: str = "Sanath",
                   simulated: bool = False) -> dict:
    focus = focus if focus in FOCUSES else "hashrate"
    builder = {
        "id": f"wb_{uuid.uuid4().hex[:8]}",
        "name": (name or "").strip() or "Unnamed picked builder",
        "origin": origin,  # "picked", "villager_promoted", "picked_simulated"
        "focus": focus,
        "picked_by": picked_by,
        "goal": "Make the world mine more, faster, easier, more effectively, more efficiently",
    }
    if simulated or origin == "picked_simulated":
        builder["simulated_representation"] = True
        builder["note"] = ("Simulated representation of this renowned "
                           "person's public expertise only; not the real "
                           "person, no affiliation, endorsement, or "
                           "participation.")
    return builder


def compute_bonuses(builders: list[dict]) -> dict:
    """Aggregate builder bonuses, with caps. Returns factors."""
    n = len(builders or [])
    hashrate_pct = BASE_HASHRATE_PCT * n
    power_pct = BASE_POWER_PCT * n
    focus_counts: dict[str, int] = {}
    for b in builders or []:
        f = b.get("focus", "hashrate")
        focus_counts[f] = focus_counts.get(f, 0) + 1
    # Focus extra: +1% hashrate for hashrate focus, -1% power for
    # power focus, +1% hashrate for cooling/uptime (better cooling /
    # uptime = more sustained hashrate), repair does not change
    # hashrate directly in this model (it is recorded, and the
    # operations layer's repair capacity is unchanged — see limits).
    hashrate_pct += FOCUS_EXTRA_PCT * (focus_counts.get("hashrate", 0)
                                       + focus_counts.get("cooling", 0)
                                       + focus_counts.get("uptime", 0))
    power_pct -= FOCUS_EXTRA_PCT * focus_counts.get("power", 0)
    hashrate_pct = min(hashrate_pct, MAX_HASHRATE_PCT)
    power_saving = min(-power_pct, MAX_POWER_SAVING_PCT)
    return {
        "builders": n,
        "focus_counts": focus_counts,
        "hashrate_bonus_pct": round(hashrate_pct, 2),
        "power_saving_pct": round(power_saving, 2),
        "hashrate_factor": round(1 + hashrate_pct / 100, 4),
        "power_factor": round(1 - power_saving / 100, 4),
    }


def default_dilation() -> dict:
    return {"years_per_second": 1.0, "set_by": "default",
            "note": "1 real second = 1 in-game year in live mode"}


def clamp_dilation(years_per_second: float) -> float:
    try:
        d = float(years_per_second)
    except (TypeError, ValueError):
        raise ValueError("years_per_second must be a number")
    if d < MIN_DILATION or d > MAX_DILATION:
        raise ValueError(
            f"time dilation must be between {MIN_DILATION} and "
            f"{MAX_DILATION} years per real second")
    return d
