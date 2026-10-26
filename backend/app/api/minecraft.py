"""Minecraft-style world endpoints.

POST /api/minecraft/create
    {"name": str, "seed": str, "size": 64,
     "agents": [{"name": str, "role": str}] (optional),
     "graph_id": str (optional — build villagers from a MiroFish graph)}
POST /api/minecraft/<world_id>/tick   {"ticks": 1..24}
GET  /api/minecraft/<world_id>         summary (no full cell grid)
GET  /api/minecraft/<world_id>/map     full cell grid + agents (for the viewer)
GET  /api/minecraft/<world_id>/log     last log lines

This world type is independent of OASIS: it runs on its own tick
engine, so it works while the social simulation is blocked on FastMCP.
"""

from flask import request, jsonify

from . import minecraft_bp
from ..services.local_graph import LocalGraphStore
from ..services.minecraft_world import MinecraftWorld


@minecraft_bp.route('/create', methods=['POST'])
def create_world():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "Minecraft World").strip()
    seed = str(data.get("seed") or "mirofish")
    size = data.get("size", 64)
    if data.get("graph_id"):
        store = LocalGraphStore()
        nodes = store.list_nodes(data["graph_id"])
        if not nodes:
            return jsonify({"success": False,
                            "error": f"Graph not found or empty: {data['graph_id']}"}), 404
        world = MinecraftWorld.from_graph_nodes(
            name=name, seed=seed, nodes=nodes, size=size)
    else:
        world = MinecraftWorld.create(
            name=name, seed=seed, size=size,
            agents=data.get("agents"), source="manual")
    return jsonify({"success": True, **world.summary()})


@minecraft_bp.route('/<world_id>', methods=['GET'])
def get_world(world_id):
    world = MinecraftWorld.load(world_id)
    if world is None:
        return jsonify({"success": False, "error": "World not found"}), 404
    return jsonify({"success": True, **world.summary()})


@minecraft_bp.route('/<world_id>/map', methods=['GET'])
def get_map(world_id):
    world = MinecraftWorld.load(world_id)
    if world is None:
        return jsonify({"success": False, "error": "World not found"}), 404
    d = world.data
    return jsonify({"success": True, "world_id": d["world_id"],
                    "name": d["name"], "size": d["size"],
                    "spawn": d["spawn"], "cells": d["cells"],
                    "agents": d["agents"], "tick": d["tick"],
                    "day": d["day"], "hour": d["hour"],
                    "structures": d["structures"], "stats": d["stats"]})


@minecraft_bp.route('/<world_id>/tick', methods=['POST'])
def tick_world(world_id):
    world = MinecraftWorld.load(world_id)
    if world is None:
        return jsonify({"success": False, "error": "World not found"}), 404
    data = request.get_json(silent=True) or {}
    return jsonify({"success": True, **world.tick(data.get("ticks", 1))})


@minecraft_bp.route('/<world_id>/log', methods=['GET'])
def get_log(world_id):
    world = MinecraftWorld.load(world_id)
    if world is None:
        return jsonify({"success": False, "error": "World not found"}), 404
    return jsonify({"success": True, "log": world.data["log"][-200:]})


@minecraft_bp.route('/<world_id>/year', methods=['POST'])
def advance_year(world_id):
    """Advance N in-game years (default 1). In live mode, the runner
    calls this once per real second, so 1 second = 1 year. A world's
    mega mine, if built, advances with it."""
    world = MinecraftWorld.load(world_id)
    if world is None:
        return jsonify({"success": False, "error": "World not found"}), 404
    data = request.get_json(silent=True) or {}
    return jsonify({"success": True, **world.advance_year(data.get("years", 1))})


@minecraft_bp.route('/<world_id>/mega-miner', methods=['POST', 'GET'])
def mega_miner(world_id):
    """POST builds the mega mine (one machine per Bitcoin block);
    GET returns its current state. It is a simulation inside the
    Minecraft world — it mines no real Bitcoin."""
    world = MinecraftWorld.load(world_id)
    if world is None:
        return jsonify({"success": False, "error": "World not found"}), 404
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        mine = world.create_mega_mine(data.get("name", "Blockforge Mega Mine"))
        return jsonify({"success": True, "mega_mine": mine})
    mine = world.data.get("mega_mine")
    if mine is None:
        return jsonify({"success": False,
                        "error": "No mega mine built in this world yet"}), 404
    return jsonify({"success": True, "mega_mine": mine})


@minecraft_bp.route('/<world_id>/mega-miner/operations',
                    methods=['POST'])
def mega_miner_operations(world_id):
    """Create wallet, staff, maintenance, security and economics
    for this world's mega mine (retrofit for mines built before
    operations existed). Simulation only."""
    world = MinecraftWorld.load(world_id)
    if world is None:
        return jsonify({"success": False, "error": "World not found"}), 404
    try:
        ops = world.create_mine_operations()
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    return jsonify({"success": True, "operations": ops})


@minecraft_bp.route('/<world_id>/mega-miner/infrastructure',
                    methods=['POST'])
def mega_miner_infrastructure(world_id):
    """Build Tesla power + satellite internet + water cooling for
    this world's mega mine (retrofit for mines built before
    infrastructure existed). Simulation only."""
    world = MinecraftWorld.load(world_id)
    if world is None:
        return jsonify({"success": False, "error": "World not found"}), 404
    try:
        infra = world.build_mega_mine_infrastructure()
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    return jsonify({"success": True, "infrastructure": infra})
