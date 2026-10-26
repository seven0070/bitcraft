"""Minecraft-style world simulation for MiroFish.

This is a NEW world type, not a patch to the OASIS Twitter/Reddit
simulation — and deliberately not dependent on OASIS or on an LLM per
tick, so it runs even while the social simulation is blocked on the
FastMCP import error. The social simulation code is untouched; this
module lives alongside it.

World model (kept deliberately Minecraft-like, not a Minecraft clone):
* A square voxel-ish map, default 64x64 cells, generated from a seed
  with smooth value noise (multiple octaves) for height and moisture.
* Biomes from height/moisture: ocean, beach, plains, forest, desert,
  mountains, snow. Each cell has a surface block (grass, sand, stone,
  snow, water), an optional tree, and an optional underground ore
  (coal, iron, gold, diamond) that mining can reveal.
* A village at the map centre (spawn). Structures built over time:
  houses, farms, mineshafts, workshops — each is a placed block
  cluster on the map, counted in world stats.
* Agents are villagers/players with a role, position, hunger, health,
  and inventory. One tick = one in-game hour; 24 ticks = one day,
  with day (06:00-18:00) for work and night (22:00-05:00) for sleep.
  Night outside the village is dangerous: agents take damage unless
  they are home, which is why the village matters.
* Agent roles and their work:
  Miner (ore/stone), Lumberjack (wood), Farmer (wheat -> bread),
  Builder (wood+stone -> houses), Explorer (reveals map),
  Trader (swaps surplus for coins), Engineer (wood+iron -> tools),
  Guard (patrols the village at night), Villager (general help).
* Everything is rule-based and deterministic for a given seed, so a
  world can be replayed and its log audited. No text is generated,
  no LLM call is made per tick, and no action is invented: every
  inventory change and structure comes from a logged action.

Persistence: one JSON file per world under
``backend/uploads/minecraft_worlds/<world_id>.json`` — the same
file-per-world pattern as the local graph store.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import random
import uuid
from typing import Any

from ..config import Config
from ..utils.logger import get_logger
from .bitcoin_mega_miner import (advance_mine_year, build_infrastructure,
                                 create_mine)
from .bitcoin_mine_operations import (advance_operations_year,
                                      create_operations)

logger = get_logger("mirofish.minecraft_world")

BASE_DIR = os.path.join(os.path.dirname(__file__), "../uploads/minecraft_worlds")

BLOCK_COLORS = {
    "water": "#3b82f6", "sand": "#e7d27a", "grass": "#4ade80",
    "stone": "#9ca3af", "snow": "#f8fafc", "wood": "#92400e",
    "leaves": "#166534", "house": "#b45309", "farm": "#a16207",
    "mine": "#44403c", "workshop": "#7c3aed",
}

# MiroFish graph entity types -> Minecraft roles. Non-person entities
# (Twitter, Reddit, MiroFish, Backend, Zep Cloud, ...) are not agents.
ROLE_BY_ENTITY = {
    "CreatorEntity": "Builder", "Creators": "Builder", "BangaloreCreator": "Builder",
    "FreelancerEntity": "Explorer", "Freelancers": "Explorer",
    "BusinessOwnerEntity": "Trader", "BusinessOwners": "Trader",
    "InvestorEntity": "Trader", "Investors": "Trader",
    "StudentEntity": "Farmer", "Students": "Farmer",
    "JournalistEntity": "Explorer", "Journalists": "Explorer",
    "PolicymakerEntity": "Guard", "Policymakers": "Guard",
    "AibuilderEntity": "Engineer", "AIBuilders": "Engineer",
    "Person": "Villager", "Families": "Villager",
}
SKIP_NODES = {"twitter", "reddit", "mirofish", "backend", "zep cloud",
              "eator/builder"}


def _seed_int(seed: str) -> int:
    return int(hashlib.sha256(str(seed).encode()).hexdigest()[:8], 16)


def _noise(rng: random.Random, size: int, octaves: int = 3) -> list[list[float]]:
    """Smooth value noise in [0, 1], one value per cell."""
    grid = [[0.0] * size for _ in range(size)]
    for octave in range(octaves):
        step = max(1, size // (4 * (2 ** octave)))
        coarse = [[rng.random() for _ in range(size // step + 2)]
                  for _ in range(size // step + 2)]
        amp = 1.0 / (2 ** octave)
        for y in range(size):
            for x in range(size):
                gx, gy = x / step, y / step
                x0, y0 = int(gx), int(gy)
                fx, fy = gx - x0, gy - y0
                sx = fx * fx * (3 - 2 * fx)
                sy = fy * fy * (3 - 2 * fy)
                v = (coarse[y0][x0] * (1 - sx) * (1 - sy)
                     + coarse[y0][x0 + 1] * sx * (1 - sy)
                     + coarse[y0 + 1][x0] * (1 - sx) * sy
                     + coarse[y0 + 1][x0 + 1] * sx * sy)
                grid[y][x] += v * amp
    mx = max(max(row) for row in grid) or 1.0
    return [[v / mx for v in row] for row in grid]


def _biome(height: float, moisture: float) -> tuple[str, str]:
    if height < 0.32:
        return "ocean", "water"
    if height < 0.38:
        return "beach", "sand"
    if height > 0.82:
        return "snowy mountains", "snow"
    if height > 0.68:
        return "mountains", "stone"
    if moisture < 0.35:
        return "desert", "sand"
    if moisture > 0.62:
        return "forest", "grass"
    return "plains", "grass"


class MinecraftWorld:
    """A single persistent Minecraft-style world."""

    def __init__(self, data: dict):
        self.data = data

    # -- creation -----------------------------------------------------
    @classmethod
    def create(cls, *, name: str, seed: str, size: int = 64,
               agents: list[dict] | None = None,
               source: str = "manual") -> "MinecraftWorld":
        size = max(32, min(96, int(size or 64)))
        rng = random.Random(_seed_int(seed))
        height = _noise(rng, size)
        moisture = _noise(rng, size)
        cells = []
        for y in range(size):
            row = []
            for x in range(size):
                biome, block = _biome(height[y][x], moisture[y][x])
                tree = biome == "forest" and rng.random() < 0.35
                if biome == "plains" and rng.random() < 0.08:
                    tree = True
                ore = None
                if block in ("stone", "grass") and rng.random() < 0.12:
                    ore = rng.choices(
                        ["coal", "iron", "gold", "diamond"],
                        weights=[50, 30, 12, 8])[0]
                row.append({"x": x, "y": y, "biome": biome, "block": block,
                            "tree": tree, "ore": ore, "ore_mined": False,
                            "structure": None, "explored": False})
            cells.append(row)
        cx = cy = size // 2
        # Village: flatten a small centre so spawn is always walkable.
        for dy in range(-3, 4):
            for dx in range(-3, 4):
                cell = cells[cy + dy][cx + dx]
                if cell["block"] == "water":
                    cell["block"], cell["biome"] = "grass", "plains"
                cell["tree"] = False
                cell["explored"] = True
        cells[cy][cx]["structure"] = "village_square"
        world_agents = []
        for i, spec in enumerate(agents or []):
            world_agents.append({
                "id": f"agent_{i}", "name": spec.get("name", f"Villager {i}"),
                "role": spec.get("role", "Villager"),
                "age": spec.get("age", rng.randint(18, 45)),
                "x": cx + rng.randint(-2, 2), "y": cy + rng.randint(-2, 2),
                "hunger": 100, "health": 100,
                "inventory": {"wood": 0, "stone": 0, "coal": 0, "iron": 0,
                              "gold": 0, "diamond": 0, "wheat": 0,
                              "bread": 2, "tools": 0, "coins": 0},
                "alive": True, "last_action": "Spawned in the village.",
            })
        data = {
            "world_id": f"mc_{uuid.uuid4().hex[:12]}",
            "name": name, "seed": seed, "size": size, "source": source,
            "spawn": {"x": cx, "y": cy},
            "cells": cells, "agents": world_agents,
            "tick": 0, "day": 1, "hour": 6, "year": 1,
            "mega_mine": None,
            "time_scale": "1 real second = 1 in-game year in live mode",
            "structures": {"houses": 0, "farms": 0, "mineshafts": 0,
                           "workshops": 0},
            "stats": {"mined": 0, "wood_chopped": 0, "wheat_grown": 0,
                      "built": 0, "crafted": 0, "trades": 0, "explored": 49},
            "log": [f"World '{name}' generated from seed '{seed}' "
                    f"({size}x{size}, village at {cx},{cy})."],
        }
        world = cls(data)
        world.save()
        return world

    @classmethod
    def from_graph_nodes(cls, *, name: str, seed: str, nodes: list[dict],
                         size: int = 64) -> "MinecraftWorld":
        """Turn MiroFish graph entities into Minecraft villagers."""
        agents, seen = [], set()
        for node in nodes or []:
            label = (node.get("labels") or ["Entity"])[0]
            nm = (node.get("name") or "").strip()
            if nm.lower() in SKIP_NODES or not nm:
                continue
            role = ROLE_BY_ENTITY.get(label) or ROLE_BY_ENTITY.get(nm) or "Villager"
            if nm in seen:
                continue
            seen.add(nm)
            agents.append({"name": nm, "role": role})
        if not agents:
            agents = [{"name": "Steve", "role": "Miner"},
                      {"name": "Alex", "role": "Farmer"},
                      {"name": "Villager", "role": "Builder"}]
        # A Minecraft world needs mining and woodcutting even if the
        # graph has no miner/lumberjack entity: add them as villagers
        # rather than leaving those whole economies at zero.
        roles = {a["role"] for a in agents}
        if "Miner" not in roles:
            agents.append({"name": "Steve", "role": "Miner"})
        if "Lumberjack" not in roles:
            agents.append({"name": "Alex", "role": "Lumberjack"})
        return cls.create(name=name, seed=seed, size=size, agents=agents,
                          source="mirofish_graph")

    # -- persistence --------------------------------------------------
    @classmethod
    def _path(cls, world_id: str) -> str:
        os.makedirs(BASE_DIR, exist_ok=True)
        safe = "".join(c for c in str(world_id) if c.isalnum() or c in "_-")
        return os.path.join(BASE_DIR, safe + ".json")

    @classmethod
    def load(cls, world_id: str) -> "MinecraftWorld | None":
        path = cls._path(world_id)
        if not os.path.exists(path):
            return None
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        # Worlds created before the year scale existed gain it here.
        data.setdefault("year", 1)
        data.setdefault("mega_mine", None)
        data.setdefault("time_scale",
                        "1 real second = 1 in-game year in live mode")
        for i, agent in enumerate(data.get("agents", [])):
            agent.setdefault("age", 25)
            agent.setdefault("id", f"agent_{i}")
        return cls(data)

    def save(self) -> None:
        path = self._path(self.data["world_id"])
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False)
        os.replace(tmp, path)

    def summary(self) -> dict:
        d = self.data
        return {
            "world_id": d["world_id"], "name": d["name"], "seed": d["seed"],
            "size": d["size"], "source": d["source"], "spawn": d["spawn"],
            "tick": d["tick"], "day": d["day"], "hour": d["hour"],
            "year": d.get("year", 1),
            "mega_mine": d.get("mega_mine"),
            "time_scale": d.get("time_scale",
                                "1 real second = 1 in-game year in live mode"),
            "time_of_day": "night" if d["hour"] < 6 or d["hour"] >= 22
                           else "day" if d["hour"] < 18 else "evening",
            "agents": d["agents"], "structures": d["structures"],
            "stats": d["stats"],
            "log": d["log"][-50:],
        }

    # -- mega mine ----------------------------------------------------
    def create_mega_mine(self, name: str = "Blockforge Mega Mine") -> dict:
        """Build the world's largest Bitcoin miner in this world:
        one U3S23H per Bitcoin block, placed as a mine district east
        of the village. Returns the mine dict (or the existing one)."""
        if self.data.get("mega_mine"):
            return self.data["mega_mine"]
        mine = create_mine(name=name)
        self.data["mega_mine"] = mine
        # Mine district: 16x16 cells east of spawn, on walkable land.
        cx, cy = self.data["spawn"]["x"] + 12, self.data["spawn"]["y"]
        for dy in range(-8, 8):
            for dx in range(-8, 8):
                cell = self._cell(cx + dx, cy + dy)
                if cell and cell["block"] != "water":
                    cell["structure"] = "mega_mine"
                    cell["tree"] = False
        self._log(f"Mega mine '{name}' built east of the village: "
                  f"{mine['machines']:,} machines, one per Bitcoin block, "
                  f"{mine['fleet_hashrate_eh_s']:,.1f} EH/s.")
        self.save()
        # New mines get their infrastructure at birth; existing mines
        # (like Emberhill's, built before infrastructure existed) get
        # it via build_mega_mine_infrastructure().
        self.build_mega_mine_infrastructure()
        self.create_mine_operations()
        return mine

    def build_mega_mine_infrastructure(self) -> dict:
        """Retrofit (or build) Tesla power + satellite + water cooling
        for this world's mega mine, and mark its districts on the map.
        Returns the infrastructure dict."""
        mine = self.data.get("mega_mine")
        if not mine:
            raise ValueError("No mega mine built in this world yet")
        if mine.get("infrastructure"):
            return mine["infrastructure"]
        water_cells = sum(
            1 for row in self.data["cells"] for c in row
            if c["block"] == "water")
        sx, sy = self.data["spawn"]["x"], self.data["spawn"]["y"]
        intake = None
        best = None
        for y, row in enumerate(self.data["cells"]):
            for x, cell in enumerate(row):
                if cell["block"] == "water":
                    dist = abs(x - sx) + abs(y - sy)
                    if best is None or dist < best[0]:
                        best = (dist, x, y)
        if best:
            intake = {"x": best[1], "y": best[2]}
            cell = self._cell(best[1], best[2])
            if cell:
                cell["structure"] = "cooling_plant"
        # Tesla Power District: south of the village.
        for dy in range(4):
            for dx in range(12):
                cell = self._cell(sx - 6 + dx, sy + 10 + dy)
                if cell and cell["block"] != "water":
                    cell["structure"] = "tesla_power"
        # Satellite dishes: a row north of the village.
        for dx in range(8):
            cell = self._cell(sx - 4 + dx, sy - 10)
            if cell and cell["block"] != "water":
                cell["structure"] = "satellite_dish"
        infra = build_infrastructure(mine, water_cells=water_cells,
                                     intake=intake)
        self._log(f"Mega mine infrastructure built: Tesla power "
                  f"{infra['power']['supply_gw']} GW, "
                  f"{infra['internet']['satellites']} satellites, "
                  f"water cooling {infra['cooling']['flow_m3_s']} m^3/s "
                  f"from intake {intake}.")
        self.save()
        return infra

    def create_mine_operations(self) -> dict:
        """Create everything else the mine needs: wallet, staff,
        maintenance, security, economics — and mark staff quarters
        and a warehouse on the map. Returns the operations dict."""
        mine = self.data.get("mega_mine")
        if not mine:
            raise ValueError("No mega mine built in this world yet")
        if mine.get("operations"):
            return mine["operations"]
        alive = [a for a in self.data["agents"] if a["alive"]]
        # Managers: prefer Engineer, Guard, Miner, then first alive.
        def rank(agent):
            return {"Engineer": 0, "Guard": 1, "Miner": 2}.get(
                agent["role"], 3)
        managers = [a["name"] for a in sorted(alive, key=rank)[:3]]
        ops = create_operations(mine["machines"], managers=managers)
        mine["operations"] = ops
        sx, sy = self.data["spawn"]["x"], self.data["spawn"]["y"]
        for dy in range(3):
            for dx in range(6):
                cell = self._cell(sx - 12 + dx, sy + 6 + dy)
                if cell and cell["block"] != "water":
                    cell["structure"] = "staff_quarters"
        for dy in range(3):
            for dx in range(4):
                cell = self._cell(sx + 6 + dx, sy + 10 + dy)
                if cell and cell["block"] != "water":
                    cell["structure"] = "warehouse"
        self._log(f"Mine operations created: wallet, "
                  f"{ops['staff']['total']} staff, managers "
                  f"{', '.join(managers)}, staff quarters + warehouse.")
        self.save()
        return ops

    # -- helpers ------------------------------------------------------
    def _cell(self, x: int, y: int) -> dict | None:
        size = self.data["size"]
        if 0 <= x < size and 0 <= y < size:
            return self.data["cells"][y][x]
        return None

    def _walkable(self, cell: dict | None) -> bool:
        return cell is not None and cell["block"] != "water"

    def _step_toward(self, agent: dict, tx: int, ty: int) -> None:
        """One greedy step toward (tx, ty), never into water."""
        best, best_d = None, abs(agent["x"] - tx) + abs(agent["y"] - ty)
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = agent["x"] + dx, agent["y"] + dy
            cell = self._cell(nx, ny)
            if not self._walkable(cell):
                continue
            d = abs(nx - tx) + abs(ny - ty)
            if d < best_d:
                best, best_d = (nx, ny), d
        if best:
            agent["x"], agent["y"] = best
            self._cell(best[0], best[1])["explored"] = True

    def _nearest(self, agent: dict, pred) -> dict | None:
        size, best, best_d = self.data["size"], None, 10 ** 9
        for row in self.data["cells"]:
            for cell in row:
                if not pred(cell):
                    continue
                d = abs(cell["x"] - agent["x"]) + abs(cell["y"] - agent["y"])
                if d < best_d:
                    best, best_d, = cell, d
        return best

    def _log(self, msg: str) -> None:
        self.data["log"].append(f"Day {self.data['day']} "
                                f"{self.data['hour']:02d}:00 — {msg}")
        self.data["log"] = self.data["log"][-500:]

    # -- tick ---------------------------------------------------------
    def tick(self, n: int = 1) -> dict:
        for _ in range(max(1, min(24, int(n or 1)))):
            self._tick_one()
        self.save()
        return self.summary()

    # -- years --------------------------------------------------------
    # 1 real second = 1 in-game year, in live mode. A year is NOT
    # 8,760 hourly ticks replayed — that would be far too slow to run
    # once a second. It is one aggregated year: each villager ages a
    # year, works a year's worth of their role at village scale, and
    # the village grows or shrinks. Hourly ticks still exist for
    # detailed, day-by-day play; years are the fast-forward layer.
    def _consume_village(self, resource: str, amount: int) -> int:
        taken = 0
        for agent in self.data["agents"]:
            if taken >= amount:
                break
            have = agent["inventory"].get(resource, 0)
            take = min(have, amount - taken)
            agent["inventory"][resource] = have - take
            taken += take
        return taken

    def advance_year(self, n: int = 1) -> dict:
        d = self.data
        for _ in range(max(1, min(100, int(n or 1)))):
            d["year"] = d.get("year", 1) + 1
            year = d["year"]
            rng = random.Random(_seed_int(d["seed"]) + year * 1009)
            births, deaths = [], []
            for agent in list(d["agents"]):
                if not agent["alive"]:
                    continue
                agent["age"] = agent.get("age", 25) + 1
                agent["hunger"] = 100
                agent["health"] = min(100, agent["health"] + 20)
                if agent["age"] >= 80 or (agent["age"] >= 70
                                          and rng.random() < 0.25):
                    agent["alive"] = False
                    deaths.append(agent["name"])
                    self._log(f"Year {year}: {agent['name']} "
                              f"({agent['role']}) died at age {agent['age']}.")
                    continue
                role, inv = agent["role"], agent["inventory"]
                if role == "Miner":
                    inv["coal"] += 30; inv["iron"] += 20
                    inv["gold"] += 5; inv["diamond"] += 2
                    d["stats"]["mined"] += 57
                    d["structures"]["mineshafts"] = max(
                        1, d["structures"]["mineshafts"])
                    agent["last_action"] = f"Year {year}: mined the year through."
                elif role == "Lumberjack":
                    inv["wood"] += 80
                    d["stats"]["wood_chopped"] += 80
                    agent["last_action"] = f"Year {year}: felled timber all year."
                elif role == "Farmer":
                    inv["wheat"] += 200; inv["bread"] += 50
                    d["stats"]["wheat_grown"] += 200
                    d["structures"]["farms"] = max(1, d["structures"]["farms"])
                    agent["last_action"] = f"Year {year}: harvested and baked."
                elif role == "Builder":
                    wood = self._consume_village("wood", 20)
                    stone = self._consume_village("stone", 20)
                    built = 3 if wood >= 20 and stone >= 20 else 1
                    d["structures"]["houses"] += built
                    d["stats"]["built"] += built
                    agent["last_action"] = f"Year {year}: built {built} houses."
                elif role == "Explorer":
                    new_cells = 0
                    for row in d["cells"]:
                        for cell in row:
                            if not cell["explored"] and new_cells < 60:
                                cell["explored"] = True
                                new_cells += 1
                    d["stats"]["explored"] += new_cells
                    agent["last_action"] = f"Year {year}: mapped {new_cells} new cells."
                elif role == "Trader":
                    inv["coins"] += 100
                    d["stats"]["trades"] += 10
                    agent["last_action"] = f"Year {year}: traded all year."
                elif role == "Engineer":
                    if self._consume_village("iron", 5) >= 5:
                        inv["tools"] += 5
                        d["stats"]["crafted"] += 5
                        d["structures"]["workshops"] = max(
                            1, d["structures"]["workshops"])
                        agent["last_action"] = f"Year {year}: crafted 5 tools."
                    else:
                        inv["wood"] += 20
                        agent["last_action"] = f"Year {year}: gathered materials."
                elif role == "Guard":
                    agent["last_action"] = f"Year {year}: kept the village safe."
                else:
                    inv["wood"] += 20
                    agent["last_action"] = f"Year {year}: helped the village."
            alive = [a for a in d["agents"] if a["alive"]]
            if d["structures"]["houses"] > len(alive) and year % 2 == 0:
                name = rng.choice(["Maya", "Arjun", "Noor", "Leo",
                                   "Ira", "Kabir", "Zoe", "Ravi"])
                d["agents"].append({
                    "id": f"agent_{len(d['agents'])}", "name": name,
                    "role": "Villager", "age": 18,
                    "x": d["spawn"]["x"], "y": d["spawn"]["y"],
                    "hunger": 100, "health": 100,
                    "inventory": {"wood": 0, "stone": 0, "coal": 0,
                                  "iron": 0, "gold": 0, "diamond": 0,
                                  "wheat": 0, "bread": 2, "tools": 0,
                                  "coins": 0},
                    "alive": True,
                    "last_action": f"Born/arrived in Year {year}.",
                })
                births.append(name)
            self._log(f"Year {year} complete: {len(alive)} villagers alive"
                      + (f", {len(deaths)} died" if deaths else "")
                      + (f", {len(births)} arrived" if births else "")
                      + f", {d['structures']['houses']} houses.")
            if d.get("mega_mine"):
                mine = d["mega_mine"]
                before_blocks = mine["fleet_blocks_found"]
                before_btc = mine["fleet_btc_earned"]
                advance_mine_year(mine)
                self._log(f"Year {year}: mega mine now "
                          f"{mine['machines']:,} machines, "
                          f"found {mine['fleet_blocks_found']:,} "
                          f"blocks in total.")
                if mine.get("operations"):
                    ops = advance_operations_year(
                        mine["operations"],
                        machines=mine["machines"],
                        power_gw=mine["power_gw"],
                        blocks_found=mine["fleet_blocks_found"] - before_blocks,
                        subsidy_btc=mine["fleet_btc_earned"] - before_btc,
                        year=year)
                    self._log(f"Year {year}: mine operations — "
                              f"{ops['failures']:,} failures, "
                              f"{ops['repaired']:,} repaired, "
                              f"profit {ops['profit_btc']:,.1f} BTC, "
                              f"wallet {ops['wallet_balance_btc']:,.1f} BTC.")
        self.save()
        return self.summary()

    def _tick_one(self) -> None:
        d = self.data
        d["tick"] += 1
        d["hour"] = (d["hour"] + 1) % 24
        if d["hour"] == 6:
            d["day"] += 1
        hour, night = d["hour"], d["hour"] < 6 or d["hour"] >= 22
        spawn = d["spawn"]
        for agent in d["agents"]:
            if not agent["alive"]:
                continue
            agent["hunger"] = max(0, agent["hunger"] - 2)
            # Villagers share food: a hungry agent with no bread takes
            # one from a Farmer who has spare, instead of starving
            # while the village bakery sits full.
            if agent["hunger"] <= 20 and agent["inventory"]["bread"] == 0:
                for other in d["agents"]:
                    if other["role"] == "Farmer" and other["inventory"]["bread"] > 1:
                        other["inventory"]["bread"] -= 1
                        agent["inventory"]["bread"] += 1
                        break
            if agent["hunger"] <= 20 and agent["inventory"]["bread"] > 0:
                agent["inventory"]["bread"] -= 1
                agent["hunger"] = min(100, agent["hunger"] + 40)
                agent["last_action"] = "Ate bread."
            if agent["hunger"] == 0:
                agent["health"] = max(0, agent["health"] - 5)
                if agent["health"] == 0:
                    agent["alive"] = False
                    self._log(f"{agent['name']} starved.")
                    continue
            if night:
                # Night: go home. Outside the village, mobs hurt you.
                dist = abs(agent["x"] - spawn["x"]) + abs(agent["y"] - spawn["y"])
                if dist > 4:
                    self._step_toward(agent, spawn["x"], spawn["y"])
                    agent["last_action"] = "Fleeing home from the night."
                    if dist > 8:
                        agent["health"] = max(0, agent["health"] - 10)
                        self._log(f"{agent['name']} was hurt by a mob at night.")
                else:
                    agent["health"] = min(100, agent["health"] + 10)
                    agent["last_action"] = "Sleeping safely in the village."
                continue
            self._do_work(agent, hour)
        # Passive regrowth: a chopped forest slowly returns.
        if d["tick"] % 24 == 0:
            for row in d["cells"]:
                for cell in row:
                    if cell["biome"] == "forest" and not cell["tree"]:
                        if random.Random(d["tick"] + cell["x"] * 31
                                          + cell["y"]).random() < 0.02:
                            cell["tree"] = True

    def _do_work(self, agent: dict, hour: int) -> None:
        d, inv, role = self.data, agent["inventory"], agent["role"]
        cell = self._cell(agent["x"], agent["y"])
        if role == "Miner":
            target = self._nearest(agent, lambda c: c["ore"] and not c["ore_mined"])
            if target and (target["x"], target["y"]) == (agent["x"], agent["y"]):
                ore = target["ore"]
                target["ore_mined"], target["ore"] = True, None
                inv[ore] += 1
                d["stats"]["mined"] += 1
                if d["structures"]["mineshafts"] == 0:
                    d["structures"]["mineshafts"] = 1
                agent["last_action"] = f"Mined {ore}."
                self._log(f"{agent['name']} mined {ore}.")
            elif target:
                self._step_toward(agent, target["x"], target["y"])
                agent["last_action"] = "Heading to the mine."
            else:
                inv["stone"] += 1
                agent["last_action"] = "Dug stone."
        elif role == "Lumberjack":
            if cell and cell["tree"]:
                cell["tree"] = False
                inv["wood"] += 2
                d["stats"]["wood_chopped"] += 2
                agent["last_action"] = "Chopped a tree."
            else:
                target = self._nearest(agent, lambda c: c["tree"])
                if target:
                    self._step_toward(agent, target["x"], target["y"])
                    agent["last_action"] = "Heading to the forest."
        elif role == "Farmer":
            if inv["wheat"] >= 3:
                inv["wheat"] -= 3
                inv["bread"] += 1
                agent["last_action"] = "Baked bread."
            else:
                inv["wheat"] += 1
                d["stats"]["wheat_grown"] += 1
                if d["structures"]["farms"] == 0:
                    d["structures"]["farms"] = 1
                    self._log(f"{agent['name']} started the first farm.")
                agent["last_action"] = "Tending the farm."
        elif role == "Builder":
            if inv["wood"] >= 4 and inv["stone"] >= 4:
                inv["wood"] -= 4
                inv["stone"] -= 4
                d["structures"]["houses"] += 1
                d["stats"]["built"] += 1
                cell["structure"] = "house"
                agent["last_action"] = "Built a house."
                self._log(f"{agent['name']} built house #{d['structures']['houses']}.")
            else:
                inv["wood"] += 1
                inv["stone"] += 1
                agent["last_action"] = "Gathering building materials."
        elif role == "Explorer":
            target = self._nearest(agent, lambda c: not c["explored"])
            if target:
                self._step_toward(agent, target["x"], target["y"])
                d["stats"]["explored"] += 1
                agent["last_action"] = "Exploring new land."
            else:
                agent["last_action"] = "The whole map is explored."
        elif role == "Trader":
            surplus = max(inv.items(), key=lambda kv: kv[1])
            if surplus[1] >= 3 and surplus[0] not in ("coins", "tools", "bread"):
                inv[surplus[0]] -= 2
                inv["coins"] += 3
                d["stats"]["trades"] += 1
                agent["last_action"] = f"Traded {surplus[0]} for coins."
            else:
                inv["coins"] += 1
                agent["last_action"] = "Running the market stall."
        elif role == "Engineer":
            # Villagers share: an Engineer with no iron takes one from a
            # Miner who has spare, instead of waiting forever for iron
            # that only Miners ever find.
            if inv["iron"] == 0:
                for other in d["agents"]:
                    if other["role"] == "Miner" and other["inventory"]["iron"] >= 1:
                        other["inventory"]["iron"] -= 1
                        inv["iron"] += 1
                        agent["last_action"] = "Collected iron from the miner."
                        break
            if inv["wood"] >= 2 and inv["iron"] >= 1:
                inv["wood"] -= 2
                inv["iron"] -= 1
                inv["tools"] += 1
                d["stats"]["crafted"] += 1
                if d["structures"]["workshops"] == 0:
                    d["structures"]["workshops"] = 1
                agent["last_action"] = "Crafted a tool."
                self._log(f"{agent['name']} crafted a tool.")
            else:
                inv["wood"] += 1
                agent["last_action"] = "Gathering workshop materials."
        elif role == "Guard":
            self._step_toward(agent, d["spawn"]["x"], d["spawn"]["y"])
            agent["last_action"] = "Patrolling the village."
        else:  # Villager
            inv["wood"] += 1
            agent["last_action"] = "Helping around the village."
