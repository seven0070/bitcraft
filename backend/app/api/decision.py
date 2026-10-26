"""Clef decision endpoints.

POST /api/decision/decide        {"state": ..., "questions": {...}}
POST /api/decision/agent-action  {"platform": "twitter"|"reddit", "state": ...}

Both require Clef to be configured (see clef_client.py); when it is
not, they return 503 naming only what is missing — never any
credential. These endpoints decide; they do not generate text, run a
simulation, or change any graph/simulation state.
"""

from flask import request, jsonify

from . import decision_bp
from ..config import Config
from ..utils import clef_client


@decision_bp.route('/decide', methods=['POST'])
def decide():
    if not Config.CLEF_ENABLED:
        return jsonify({"success": False,
                        "error": "Clef is disabled (CLEF_ENABLED is not true)"}), 503
    data = request.get_json(silent=True) or {}
    state, questions = data.get("state"), data.get("questions")
    if state is None or not isinstance(questions, dict) or not questions:
        return jsonify({"success": False,
                        "error": "state and a non-empty questions object are required"}), 400
    try:
        answers = clef_client.decide(state, questions)
    except clef_client.ClefNotConfigured as exc:
        return jsonify({"success": False, "error": str(exc)}), 503
    except clef_client.ClefError as exc:
        return jsonify({"success": False, "error": str(exc)}), 502
    return jsonify({"success": True, "answers": answers})


@decision_bp.route('/agent-action', methods=['POST'])
def agent_action():
    if not Config.CLEF_ENABLED:
        return jsonify({"success": False,
                        "error": "Clef is disabled (CLEF_ENABLED is not true)"}), 503
    data = request.get_json(silent=True) or {}
    platform, state = data.get("platform"), data.get("state")
    if not platform or state is None:
        return jsonify({"success": False,
                        "error": "platform and state are required"}), 400
    try:
        result = clef_client.decide_agent_action(platform, state)
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except clef_client.ClefNotConfigured as exc:
        return jsonify({"success": False, "error": str(exc)}), 503
    except clef_client.ClefError as exc:
        return jsonify({"success": False, "error": str(exc)}), 502
    return jsonify({"success": True, **result})
