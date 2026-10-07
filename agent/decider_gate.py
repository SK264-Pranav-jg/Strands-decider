"""PII gate as a Strands hook.

DeciderGate runs on BeforeInvocationEvent, before the agent calls the model. It asks
the strands-decider service whether the new message contains PII and cancels the
invocation when the score reaches the threshold, so a blocked message never reaches
Bedrock and is never added to the agent's history.

Per-request settings and results travel through `invocation_state["decider"]`:
the caller may set `threshold` and `instructions` there, and the hook writes the
score, category breakdown and timings back into the same dict.
"""

import logging
import os
import time

import httpx
from strands.hooks import BeforeInvocationEvent, HookProvider, HookRegistry

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
UNAVAILABLE_REPLY = "The safety check is unavailable right now, so this message was not processed. Please try again."


class DeciderError(Exception):
    """The decider could not be reached or rejected the request."""


class DeciderClient:
    def __init__(self, base_url: str = DECIDER_URL):
        self.base_url = base_url
        # the first call after the decider starts can be slow while it warms up
        self.http = httpx.AsyncClient(base_url=base_url, timeout=60.0)

    async def pii_score(self, text: str, instructions: str = DEFAULT_INSTRUCTIONS) -> dict:
        """Ask the decider whether the text has PII, plus one question per category."""
        questions = {"has_pii": {"type": "noul", "instructions": instructions}}
        for key, (_, question) in CATEGORIES.items():
            questions[key] = {"type": "noul", "instructions": question}

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

        body = r.json()
        answers = body["answers"]
        return {
            "score": answers["has_pii"]["noul"],
            "categories": [
                {"key": key, "label": label, "score": answers[key]["noul"]}
                for key, (label, _) in CATEGORIES.items()
            ],
            "decider_ms": body.get("latency_ms", 0.0),
            "tokens": body.get("usage", {}).get("input_tokens"),
        }

    async def health(self) -> dict:
        r = await self.http.get("/health", timeout=3.0)
        r.raise_for_status()
        return r.json()

    async def aclose(self):
        await self.http.aclose()


class DeciderGate(HookProvider):
    def __init__(self, client: DeciderClient, threshold: float = DEFAULT_THRESHOLD,
                 instructions: str = DEFAULT_INSTRUCTIONS):
        self.client = client
        self.threshold = threshold
        self.instructions = instructions

    def register_hooks(self, registry: HookRegistry, **kwargs) -> None:
        registry.add_callback(BeforeInvocationEvent, self.check)

    async def check(self, event: BeforeInvocationEvent) -> None:
        # only the new input for this turn, never the whole history
        text = " ".join(c["text"] for m in event.messages or [] for c in m["content"] if "text" in c).strip()
        if not text:
            return

        state = event.invocation_state.setdefault("decider", {})
        threshold = state.get("threshold", self.threshold)
        instructions = state.get("instructions") or self.instructions

        t0 = time.perf_counter()
        try:
            result = await self.client.pii_score(text, instructions)
        except DeciderError as e:
            # fail closed: without a verdict the message must not reach the model
            state.update(error=str(e), blocked=True)
            event.cancel = UNAVAILABLE_REPLY
            return

        blocked = result["score"] >= threshold
        state.update(result, threshold=threshold, blocked=blocked,
                     gate_ms=(time.perf_counter() - t0) * 1000)
        # log the decision, never the message text
        log.info("gate score=%.3f threshold=%.2f blocked=%s", result["score"], threshold, blocked)

        if blocked:
            if instructions != DEFAULT_INSTRUCTIONS:
                # a custom rule may not be about PII at all
                event.cancel = BLOCKED_REPLY_CUSTOM
                return
            found = [c["label"].lower() for c in result["categories"] if c["score"] >= CATEGORY_CUTOFF]
            event.cancel = BLOCKED_REPLY.format(what=f" ({', '.join(found)})" if found else "")


class MockLLM(HookProvider):
    """MOCK_LLM mode: answer messages the gate let through without calling Bedrock.

    Registered after DeciderGate, so it only sees invocations the gate did not cancel.
    """

    def register_hooks(self, registry: HookRegistry, **kwargs) -> None:
        registry.add_callback(BeforeInvocationEvent, self.reply)

    def reply(self, event: BeforeInvocationEvent) -> None:
        if event.cancel:
            return
        text = " ".join(c["text"] for m in event.messages or [] for c in m["content"] if "text" in c).strip()
        event.cancel = f"(mock LLM) Your message passed the PII gate. You said: {text}"
