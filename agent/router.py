"""Request routing with strands-decider `choice` questions.

Two questions pick how a message is handled:
  team        -> which specialist system prompt answers it
  complexity  -> which model tier answers it (cheap and fast, or stronger)

They are sent in the same decider request as the PII gate questions, so routing
costs no extra round trip. Low-confidence team picks fall back to the general agent.
"""

import os

from prompt.main_prompt import return_prompt

DEFAULT_ROUTE_FLOOR = 0.3

TEAMS = {
    "billing": {
        "label": "Billing agent",
        "criteria": "payments, charges, refunds, invoices, subscriptions being billed",
        "prompt": "You are the billing specialist. Help with charges, refunds, invoices and subscriptions.",
    },
    "support": {
        "label": "Support agent",
        "criteria": "something is broken or not working: errors, bugs, login or account access problems",
        "prompt": "You are the technical support specialist. Help troubleshoot errors, bugs, login and access problems step by step.",
    },
    "sales": {
        "label": "Sales agent",
        "criteria": "buying, pricing, plans, upgrades, discounts, demos for new customers",
        "prompt": "You are the sales specialist. Help with plans, pricing, upgrades and choosing the right option.",
    },
    "general": {
        "label": "General agent",
        "criteria": "greetings, small talk, or questions that are not about billing, support or sales",
        "prompt": "You are the general assistant. Handle greetings and anything that is not billing, support or sales.",
    },
}

TIERS = {
    "simple": {
        "label": "Haiku 4.5",
        "criteria": "a short direct answer: a fact, a greeting, a yes or no, a one-step instruction",
        "model_id": os.getenv("SIMPLE_MODEL_ID", "global.anthropic.claude-haiku-4-5-20251001-v1:0"),
    },
    "complex": {
        "label": "Sonnet 5.5",
        "criteria": "multi-step reasoning, comparison, analysis, planning, writing or debugging",
        "model_id": os.getenv("COMPLEX_MODEL_ID", "global.anthropic.claude-sonnet-5-5"),
    },
}

# the specialists work for a fictional company and must not invent account data
COMPANY_CONTEXT = (
    "You work for Acme Cloud, a fictional software company used in a demo. You have no access to "
    "real accounts, orders or prices: when an answer would need them, say so briefly and explain "
    "what you would check."
)

ROUTE_QUESTIONS = {
    "team": {
        "type": "choice",
        "instructions": "Which team should handle this customer message?",
        "criteria": {key: t["criteria"] for key, t in TEAMS.items()},
    },
    "complexity": {
        "type": "choice",
        "instructions": "How much reasoning does a good answer to this message need?",
        "criteria": {key: t["criteria"] for key, t in TIERS.items()},
    },
}


def choose_route(answers: dict, floor: float = DEFAULT_ROUTE_FLOOR) -> dict:
    """Turn the decider's `team` and `complexity` answers into a route."""
    team, tier = answers["team"], answers["complexity"]

    # confidence is normalised: 0 = all options equally likely, 1 = certain
    fallback = team["confidence"] < floor
    chosen = "general" if fallback else team["choice"]

    return {
        "team": chosen,
        "label": TEAMS[chosen]["label"],
        "predicted": team["choice"],
        "confidence": team["confidence"],
        "floor": floor,
        "fallback": fallback,
        "options": [
            {"key": key, "label": TEAMS[key]["label"], "p": team["probabilities"][key]} for key in TEAMS
        ],
        "tier": tier["choice"],
        "tier_confidence": tier["confidence"],
        "tier_options": [
            {"key": key, "label": TIERS[key]["label"], "p": tier["probabilities"][key]} for key in TIERS
        ],
        "model_label": TIERS[tier["choice"]]["label"],
        "model_id": TIERS[tier["choice"]]["model_id"],
    }


def system_prompt_for(team: str) -> str:
    return f"{return_prompt()}\n\n{COMPANY_CONTEXT}\n\n{TEAMS[team]['prompt']}"
