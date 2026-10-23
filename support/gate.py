"""Scope gate: the decider decides whether a message reaches the orchestrator at all.

ScopeGate runs on the orchestrator's BeforeInvocationEvent and classifies each message as
in scope or out of scope:

  in_scope      noul    the message alone: is it something Acme Electronics support handles?
  follow_up     noul    mid-conversation only, with the previous assistant reply as context:
                        does it continue that conversation ("yes", "the first one")?

  max(in_scope, follow_up) >= threshold   -> in_scope      the orchestrator and specialists run
  otherwise                               -> out_of_scope  the out-of-scope agent replies instead

The context only feeds follow_up: scoring scope with it pulled new unrelated requests below
the threshold mid-conversation and lifted greetings above it.

An out-of-scope turn sets event.cancel to the out-of-scope agent's reply, so the
orchestrator's model is never called, and AfterInvocationEvent drops that reply from the
orchestrator's history. If the decider can't be reached the hook raises DeciderError before
anything else runs (fail closed).

Per-request settings come in, and the verdict goes out, through invocation_state["gate"].
"""

import logging
import time
from collections.abc import Awaitable, Callable

from strands.hooks import AfterInvocationEvent, BeforeInvocationEvent, HookProvider, HookRegistry

from support.decider import DeciderClient, DeciderError

log = logging.getLogger("support")

DEFAULT_SCOPE_THRESHOLD = 0.5

# how much of the previous assistant reply the follow-up question sees
CONTEXT_CHARS = 400

# Worded with scripts/calibrate.py. Naming concrete request types matters: a "does support
# handle this?" phrasing scored a coding request at 0.47, this one 0.23.
QUESTIONS = {
    "in_scope": {
        "type": "noul",
        "instructions": (
            "Is the customer message a customer service request to an electronics store about an "
            "order, a delivery, a cancellation, a return, a refund, or a product it sells?"
        ),
    },
}

# Asked with the previous reply as context. Real follow-ups score about 0.65 to 0.85;
# greetings, thanks and unrelated requests stay below 0.4 even mid-conversation.
FOLLOW_UP_QUESTIONS = {
    "follow_up": {
        "type": "noul",
        "instructions": (
            "Is the customer message a reply that continues the support conversation in the "
            "assistant's previous reply, for example confirming an action, choosing one of the "
            "options offered, or giving details the assistant asked for?"
        ),
    },
}

# answers an out-of-scope message; returns the reply text
Responder = Callable[[str], Awaitable[str]]

# used if the out-of-scope agent returns nothing: an empty event.cancel would let the
# message through to the orchestrator
FALLBACK_REPLY = (
    "I can only help with Acme Electronics orders, deliveries, returns, refunds and products. "
    "Please keep your questions to those."
)


def build_state(message: str, previous_reply: str | None = None) -> str:
    if not previous_reply:
        return f"Customer message: {message}"
    if len(previous_reply) > CONTEXT_CHARS:
        previous_reply = previous_reply[:CONTEXT_CHARS] + "..."
    return f"Assistant's previous reply: {previous_reply}\n\nCustomer message: {message}"


async def assess(client: DeciderClient, message: str, previous_reply: str | None) -> dict:
    """Ask the scope question, plus the follow-up question when there is a previous reply."""
    # one after the other: the client caps concurrent decider requests anyway (DECIDER_CONCURRENCY)
    results = [await client.ask(build_state(message), QUESTIONS)]
    if previous_reply:
        results.append(await client.ask(build_state(message, previous_reply), FOLLOW_UP_QUESTIONS))
    return {
        "answers": {key: a for r in results for key, a in r["answers"].items()},
        "decider_ms": sum(r["decider_ms"] for r in results),
        "tokens": sum(r["tokens"] or 0 for r in results) or None,
        "requests": len(results),
    }


def decide(answers: dict, threshold: float) -> dict:
    """Turn the decider's answers into a verdict. Raises DeciderError on a malformed answer."""
    try:
        in_scope = float(answers["in_scope"]["noul"])
        follow_up = float(answers["follow_up"]["noul"]) if "follow_up" in answers else None
    except (KeyError, TypeError, ValueError) as e:
        raise DeciderError(f"Decider model returned an unexpected answer: {e!r}") from e

    # a follow-up counts as in scope: it continues a conversation the gate already let through
    scope = max(in_scope, follow_up or 0.0)
    if scope >= threshold:
        decision = "in_scope"
        reason = "follow_up" if in_scope < threshold else None
    else:
        decision, reason = "out_of_scope", None

    return {
        "decision": decision,
        "reason": reason,
        "scope": scope,
        "in_scope": in_scope,
        "follow_up": follow_up,
        "threshold": threshold,
    }


def _text(message: dict) -> str:
    return " ".join(c["text"] for c in message.get("content", []) if "text" in c).strip()


class ScopeGate(HookProvider):
    def __init__(self, client: DeciderClient, out_of_scope: Responder, threshold: float = DEFAULT_SCOPE_THRESHOLD):
        self.client = client
        self.out_of_scope = out_of_scope
        self.threshold = threshold

    def register_hooks(self, registry: HookRegistry, **kwargs) -> None:
        registry.add_callback(BeforeInvocationEvent, self.check)
        registry.add_callback(AfterInvocationEvent, self.forget_out_of_scope)

    async def check(self, event: BeforeInvocationEvent) -> None:
        # only the new input for this turn, never the whole history
        text = " ".join(_text(m) for m in event.messages or []).strip()
        if not text:
            return

        state = event.invocation_state.setdefault("gate", {})
        previous = next((t for m in reversed(event.agent.messages)
                         if m["role"] == "assistant" and (t := _text(m))), None)

        t0 = time.perf_counter()
        # fail closed: a DeciderError propagates out of the invocation, before the message
        # is added to history or any model is called
        result = await assess(self.client, text, previous)
        verdict = decide(result["answers"], state.get("scope_threshold", self.threshold))
        state.update(verdict, decider_ms=result["decider_ms"], tokens=result["tokens"], requests=result["requests"],
                     gate_ms=(time.perf_counter() - t0) * 1000)
        log.info("gate decision=%s in_scope=%.3f follow_up=%s",
                 verdict["decision"], verdict["in_scope"], verdict["follow_up"])

        if verdict["decision"] == "out_of_scope":
            # the orchestrator never sees the message; the out-of-scope agent answers it
            event.cancel = (await self.out_of_scope(text)).strip() or FALLBACK_REPLY

    def forget_out_of_scope(self, event: AfterInvocationEvent) -> None:
        # On cancel Strands appends the reply to history as an assistant message (the user
        # message is never added). Drop it: a history that starts with, or repeats, an
        # assistant turn is rejected by Bedrock.
        if event.invocation_state.get("gate", {}).get("decision") == "out_of_scope" and event.agent.messages:
            if event.agent.messages[-1]["role"] == "assistant":
                event.agent.messages.pop()
