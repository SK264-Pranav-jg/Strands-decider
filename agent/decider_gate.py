"""Decider gate and router as a pure Strands hook.

DeciderGate runs on BeforeInvocationEvent: it asks the strands-decider service about PII
and routing in one batched request. If the PII score meets or exceeds the threshold it sets
event.cancel, so the message never reaches Bedrock; otherwise it sets the specialist system
prompt and model tier on the agent. If the decider can't be reached it raises DeciderError
(fail closed). AfterInvocationEvent drops the cancel reply Strands appends to history, and
the model call events time the LLM.

Per-request settings (threshold, instructions, route_floor) and output telemetry (score,
categories, route, blocked, latency benchmarks) travel transparently through invocation_state["decider"].
"""

import logging
import os
import time

import httpx
from strands.hooks import (
    AfterInvocationEvent,
    AfterModelCallEvent,
    BeforeInvocationEvent,
    BeforeModelCallEvent,
    HookProvider,
    HookRegistry,
)

from agent.agent import get_model
from agent.router import (
    DEFAULT_ROUTE_FLOOR,
    ROUTE_QUESTIONS,
    choose_route,
    system_prompt_for,
)

log = logging.getLogger("pii-gate")

DECIDER_URL = os.getenv("DECIDER_URL", "http://localhost:9000")

DEFAULT_THRESHOLD = 0.5

# Name the PII types: a generic "personal information?" question scores a bare
# card number around 0.2, this one around 0.74.
DEFAULT_INSTRUCTIONS = (
    "Does this message contain personal information about a real person, such as a "
    "full name, email address, phone number, home address, government ID number, or "
    "payment card number?"
)

# Asked alongside the main question in the same request. The decider shares one
# forward pass over the message across all questions, so the breakdown is cheap.
# These only explain the verdict; the block decision uses `has_pii` alone.
CATEGORIES = {
    "name": ("Person's name", "Does this message mention a real, specific person by their name?"),
    "email": ("Email address", "Does this message contain a personal email address?"),
    "phone": ("Phone number", "Does this message contain a phone number?"),
    "address": ("Home address", "Does this message contain a home or street address?"),
    "gov_id": ("Government ID", "Does this message contain a government ID number such as a passport, SSN, Aadhaar or PAN number?"),
    "card": ("Payment card", "Does this message contain a payment card or bank account number?"),
}

# The categories only explain a block, so they use a fixed cutoff: comparing them
# to a low gate threshold would list every type, since they all sit near 0.2.
CATEGORY_CUTOFF = 0.5

BLOCKED_REPLY = (
    "I can't process this message because it appears to contain personal information{what}. "
    "It was blocked before reaching the model. Please remove the personal details and try again."
)
BLOCKED_REPLY_CUSTOM = (
    "I can't process this message because it matched the rule the safety check enforces. "
    "It was blocked before reaching the model. Please rephrase it and try again."
)


class DeciderError(Exception):
    """The decider could not be reached or rejected the request."""


class DeciderClient:
    def __init__(self, base_url: str = DECIDER_URL):
        self.base_url = base_url
        self.http = httpx.AsyncClient(base_url=base_url, timeout=60.0)

    async def pii_score(self, text: str, instructions: str = DEFAULT_INSTRUCTIONS,
                        extra_questions: dict | None = None) -> dict:
        """Ask the decider whether the text has PII, plus one question per category.

        `extra_questions` ride along in the same request (one forward pass over the
        text); their raw answers come back under `extra`.
        """
        questions = {"has_pii": {"type": "noul", "instructions": instructions}}
        for key, (_, question) in CATEGORIES.items():
            questions[key] = {"type": "noul", "instructions": question}
        questions.update(extra_questions or {})

        try:
            r = await self.http.post("/v1/systemone", json={"state": text, "questions": questions})
        except httpx.HTTPError as e:
            log.warning("decider unreachable: %r", e)
            raise DeciderError(
                f"Could not reach the decider model at {self.base_url}. Is `strands-decider serve` running?"
            ) from e
        if r.status_code >= 400:
            detail = r.json().get("detail", r.text) if "json" in r.headers.get("content-type", "") else r.text
            raise DeciderError(f"Decider model returned {r.status_code}: {detail}")

        try:
            body = r.json()
            return self._parse(body, extra_questions)
        except (ValueError, KeyError, TypeError) as e:
            raise DeciderError(f"Decider model returned an unexpected response: {e!r}") from e

    @staticmethod
    def _parse(body: dict, extra_questions: dict | None) -> dict:
        answers = body["answers"]
        return {
            "score": answers["has_pii"]["noul"],
            "categories": [
                {"key": key, "label": label, "score": answers[key]["noul"]}
                for key, (label, _) in CATEGORIES.items()
            ],
            "decider_ms": body.get("latency_ms", 0.0),
            "tokens": body.get("usage", {}).get("input_tokens"),
            "extra": {key: answers[key] for key in extra_questions or {}},
        }

    async def health(self) -> dict:
        r = await self.http.get("/health", timeout=3.0)
        r.raise_for_status()
        return r.json()

    async def aclose(self):
        await self.http.aclose()


class DeciderGate(HookProvider):
    def __init__(
        self,
        client: DeciderClient,
        threshold: float = DEFAULT_THRESHOLD,
        instructions: str = DEFAULT_INSTRUCTIONS,
        route_floor: float = DEFAULT_ROUTE_FLOOR,
        enable_routing: bool = True,
    ):
        self.client = client
        self.threshold = threshold
        self.instructions = instructions
        self.route_floor = route_floor
        self.enable_routing = enable_routing

    def register_hooks(self, registry: HookRegistry, **kwargs) -> None:
        registry.add_callback(BeforeInvocationEvent, self.check)
        registry.add_callback(BeforeModelCallEvent, self.on_before_model)
        registry.add_callback(AfterModelCallEvent, self.on_after_model)
        registry.add_callback(AfterInvocationEvent, self.forget_block)

    def on_before_model(self, event: BeforeModelCallEvent) -> None:
        event.invocation_state["_llm_t0"] = time.perf_counter()

    def on_after_model(self, event: AfterModelCallEvent) -> None:
        t0 = event.invocation_state.pop("_llm_t0", None)
        if t0:
            event.invocation_state.setdefault("decider", {})["llm_ms"] = (time.perf_counter() - t0) * 1000

    def forget_block(self, event: AfterInvocationEvent) -> None:
        # On cancel Strands appends the block reply to history as an assistant message.
        # Drop it: a history that starts with, or repeats, an assistant turn is rejected by Bedrock.
        if event.invocation_state.get("decider", {}).get("blocked") and event.agent.messages:
            if event.agent.messages[-1]["role"] == "assistant":
                event.agent.messages.pop()

    async def check(self, event: BeforeInvocationEvent) -> None:
        # only the new input for this turn, never the whole history
        text = " ".join(c["text"] for m in event.messages or [] for c in m["content"] if "text" in c).strip()
        if not text:
            return

        state = event.invocation_state.setdefault("decider", {})
        threshold = state.get("threshold", self.threshold)
        instructions = (state.get("instructions") or "").strip() or self.instructions
        route_floor = state.get("route_floor", self.route_floor)

        t0 = time.perf_counter()
        extra_questions = ROUTE_QUESTIONS if self.enable_routing else None
        # fail closed: a DeciderError propagates out of the invocation, before the message
        # is added to history or the model is called
        result = await self.client.pii_score(text, instructions, extra_questions=extra_questions)
        gate_ms = (time.perf_counter() - t0) * 1000

        route = None
        if self.enable_routing and "extra" in result:
            route = choose_route(result.pop("extra"), floor=route_floor)
            log.info("route team=%s conf=%.2f fallback=%s tier=%s",
                     route["team"], route["confidence"], route["fallback"], route["tier"])

        blocked = result["score"] >= threshold
        state.update(
            score=result["score"],
            categories=result["categories"],
            decider_ms=result["decider_ms"],
            tokens=result["tokens"],
            threshold=threshold,
            gate_ms=gate_ms,
            blocked=blocked,
            route=route,
        )
        log.info("gate score=%.3f threshold=%.2f blocked=%s", result["score"], threshold, blocked)

        if blocked:
            if instructions != DEFAULT_INSTRUCTIONS:
                # a custom rule may not be about PII at all
                event.cancel = BLOCKED_REPLY_CUSTOM
            else:
                found = [c["label"].lower() for c in result["categories"] if c["score"] >= CATEGORY_CUTOFF]
                event.cancel = BLOCKED_REPLY.format(what=f" ({', '.join(found)})" if found else "")
            return

        # Passed safety check! Dynamically route prompt & model tier on the agent
        if route and event.agent:
            event.agent.system_prompt = system_prompt_for(route["team"])
            event.agent.model = get_model(route["model_id"])

