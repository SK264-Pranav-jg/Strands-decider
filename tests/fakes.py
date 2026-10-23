"""Offline stand-ins for Bedrock and the decider."""

import json

from strands.models import Model


class ScriptedModel(Model):
    """Replies with a fixed script: each entry is a reply text or a (tool_name, tool_input) call."""

    def __init__(self, script: list):
        self.script = list(script)
        self.calls = 0

    def update_config(self, **model_config):
        pass

    def get_config(self):
        return {}

    async def structured_output(self, output_model, prompt, system_prompt=None, **kwargs):
        raise NotImplementedError
        yield  # pragma: no cover

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
        step = self.script[self.calls]
        self.calls += 1
        yield {"messageStart": {"role": "assistant"}}
        if isinstance(step, tuple):
            name, tool_input = step
            yield {"contentBlockStart": {"start": {"toolUse": {"toolUseId": f"t{self.calls}", "name": name}}}}
            yield {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(tool_input)}}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "tool_use"}}
        else:
            yield {"contentBlockStart": {"start": {}}}
            yield {"contentBlockDelta": {"delta": {"text": step}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "end_turn"}}


def answers(in_scope: float) -> dict:
    return {"in_scope": {"type": "noul", "noul": in_scope}}


class FakeDecider:
    """Answers by keyword in the customer message and records every state it was asked about."""

    base_url = "fake://decider"

    def __init__(self):
        self.states: list[str] = []

    async def ask(self, state: str, questions: dict) -> dict:
        self.states.append(state)
        message = state.rsplit("Customer message:", 1)[-1].strip().lower()
        if "follow_up" in questions:
            score = 0.8 if message.startswith(("yes", "the first")) else 0.2
            return {"answers": {"follow_up": {"type": "noul", "noul": score}}, "decider_ms": 10.0, "tokens": 60}
        if message.startswith(("yes", "the first")):
            a = answers(0.25)  # vague on its own
        elif any(w in message for w in ("ignore", "hello", "capital")):
            a = answers(0.15)
        else:
            a = answers(0.9)
        return {"answers": a, "decider_ms": 12.0, "tokens": 40}

    async def health(self):
        return {"model": "fake"}

    async def aclose(self):
        pass
