"""Cloudflare Clef decision-model client for MiroFish (SystemOne API).

What Clef is — verified 2026-10-25 from its Hugging Face model card and
Cloudflare's announcement:

* Clef is a 27B multimodal DECISION model (post-trained Qwen3.8-27B;
  Clef-Flash is the 9B variant). It turns a state + a schema of typed
  questions into a probability for every allowed option, in one forward
  pass. There is NO free-form text generation and NO output parsing.
* Question types: ``noul`` (true/false -> probability of true),
  ``choice`` (named options -> chosen option + per-option probabilities
  + confidence), ``score`` (ordered levels -> probability-weighted score).
  Up to 64 questions per request.
* It therefore CANNOT replace MiroFish's chat LLM (NVIDIA) for ontology,
  profiles, config, post text or reports — those need generated text.
  Its fit in MiroFish is the decision layer: OASIS agents choose one
  action per round from a fixed set (Twitter: CREATE_POST, LIKE_POST,
  REPOST, FOLLOW, DO_NOTHING, QUOTE_POST; Reddit: LIKE_POST,
  DISLIKE_POST, CREATE_POST, CREATE_COMMENT, ...). That is exactly a
  Clef ``choice`` question: state = agent + feed + memory, options =
  the platform's action list. Clef decides WHAT to do; the chat LLM
  still writes the post/comment text when the chosen action needs it.

How it is reached from here:

* Hosted (the only route that works on this GPU-less VM): Cloudflare
  Workers AI, ``POST /client/v4/accounts/<id>/ai/run/@cf/cloudflare/clef``
  (or ``clef-flash``), Bearer token. Hosted pricing reported 2026-10-25:
  $0.24 / 1M input tokens (Clef), $0.09 / 1M (Clef-Flash), output not
  billed. Requires CLOUDFLARE_ACCOUNT_ID + CLOUDFLARE_API_TOKEN — if
  they are absent, every call fails closed with ClefNotConfigured and
  nothing is sent anywhere.
* Local (GPU box only): set CLEF_BASE_URL to an SGLang server's
  ``/v1/systemone`` endpoint (Cloudflare's documented local route for
  Clef on an H200/B200/B300). The 27B model needs ~54 GB memory in
  bf16; this VM has no GPU and 7.7 GB RAM, so local Clef is NOT
  runnable here — do not attempt a local download on this VM.

Credentials are read from the environment only, never logged, never
returned in errors or API responses.
"""

from __future__ import annotations

import json
import urllib.request
import urllib.error
from typing import Any

from ..config import Config
from ..utils.logger import get_logger

logger = get_logger("mirofish.clef_client")

# OASIS action lists, mirrored from Config so a Clef question can never
# offer an action the platform does not accept.
TWITTER_ACTIONS = list(Config.OASIS_TWITTER_ACTIONS)
REDDIT_ACTIONS = list(Config.OASIS_REDDIT_ACTIONS)


class ClefNotConfigured(RuntimeError):
    """Raised when no Clef endpoint/credentials are configured."""


class ClefError(RuntimeError):
    """Raised when a configured Clef endpoint returns an error."""


def is_configured() -> bool:
    """True only if a Clef route is actually configured."""
    if Config.CLEF_BASE_URL:
        return True
    return bool(Config.CLOUDFLARE_ACCOUNT_ID and Config.CLOUDFLARE_API_TOKEN)


def _endpoint() -> tuple[str, dict[str, str]]:
    """Return (url, headers) for the configured Clef route."""
    if Config.CLEF_BASE_URL:
        base = Config.CLEF_BASE_URL.rstrip("/")
        url = base if base.endswith("/systemone") else base + "/v1/systemone"
        return url, {"Content-Type": "application/json"}
    account = Config.CLOUDFLARE_ACCOUNT_ID
    token = Config.CLOUDFLARE_API_TOKEN
    if not account or not token:
        raise ClefNotConfigured(
            "Clef is not configured: set CLOUDFLARE_ACCOUNT_ID and "
            "CLOUDFLARE_API_TOKEN (Workers AI), or CLEF_BASE_URL "
            "(local SGLang /v1/systemone on a GPU box)."
        )
    model = (Config.CLEF_MODEL or "clef-flash").strip()
    # Workers AI model ids are @cf/cloudflare/clef and @cf/cloudflare/clef-flash.
    if not model.startswith("@cf/"):
        model = "@cf/cloudflare/" + model
    url = (
        f"https://api.cloudflare.com/client/v4/accounts/{account}"
        f"/ai/run/{model}"
    )
    return url, {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }


def decide(state: Any, questions: dict[str, Any]) -> dict[str, Any]:
    """Ask Clef typed questions about a state; return its answers dict.

    ``state`` is any string or JSON value; ``questions`` maps an id to
    {"type": "noul"|"choice"|"score", "instructions": str,
     "criteria": {option: description} | [ordered descriptions]}.
    Raises ClefNotConfigured (no route) or ClefError (endpoint error).
    The response's ``answers`` are returned verbatim — probabilities,
    never invented text.
    """
    if not questions:
        raise ValueError("Clef requires at least one question")
    url, headers = _endpoint()
    payload = {"model": (Config.CLEF_MODEL or "clef-flash"), "state": state,
               "questions": questions}
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # Never include the token or the full body; status is enough.
        raise ClefError(f"Clef endpoint returned HTTP {exc.code}") from exc
    except OSError as exc:
        raise ClefError(f"Clef endpoint unreachable: {exc}") from exc
    # Workers AI wraps the SystemOne body in {"result": {...}}.
    inner = body.get("result", body) if isinstance(body, dict) else {}
    answers = inner.get("answers") if isinstance(inner, dict) else None
    if not isinstance(answers, dict):
        raise ClefError("Clef response contained no answers")
    return answers


def decide_agent_action(platform: str, state: Any) -> dict[str, Any]:
    """Decide one OASIS action for an agent on ``platform``.

    Returns {"action": <chosen action>, "probabilities": {...},
    "confidence": float|None, "answers": <full Clef answers>}.
    """
    actions = (TWITTER_ACTIONS if platform.lower() == "twitter"
               else REDDIT_ACTIONS if platform.lower() == "reddit"
               else None)
    if actions is None:
        raise ValueError(f"Unknown platform for Clef action decision: {platform}")
    answers = decide(state, {
        "action": {
            "type": "choice",
            "instructions": (
                f"Which action should this {platform} agent take next, "
                "given its profile, recent feed and memory in the state?"
            ),
            "criteria": {a: f"Take the {a} action." for a in actions},
        },
        "should_act": {
            "type": "noul",
            "instructions": "Should the agent act at all this round, rather than do nothing?",
        },
    })
    action_answer = answers.get("action") or {}
    choice = action_answer.get("choice")
    if choice not in actions:
        # Clef must never invent an action: fall back to DO_NOTHING
        # rather than passing an invalid action to OASIS.
        logger.warning("Clef returned invalid action %r; using DO_NOTHING", choice)
        choice = "DO_NOTHING"
    return {
        "action": choice,
        "probabilities": action_answer.get("probabilities", {}),
        "confidence": action_answer.get("confidence"),
        "should_act_probability": (answers.get("should_act") or {}).get("noul"),
        "answers": answers,
    }
