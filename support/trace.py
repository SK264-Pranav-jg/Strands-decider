"""Per-turn trace of what the orchestrator and specialists did, for the UI.

One TraceHook per agent, all writing into the session's Trace. The orchestrator's tool calls
are specialists; a specialist's tool calls are nested under the specialist call that is open,
which is unambiguous because the orchestrator runs its tools one at a time.
"""

import time
from dataclasses import dataclass, field

from strands.hooks import (
    AfterModelCallEvent,
    AfterToolCallEvent,
    BeforeModelCallEvent,
    BeforeToolCallEvent,
    HookProvider,
    HookRegistry,
)

ORCHESTRATOR = "orchestrator"
OUT_OF_SCOPE = "out_of_scope_agent"


@dataclass
class Trace:
    steps: list[dict] = field(default_factory=list)
    llm_calls: int = 0
    llm_ms: float = 0.0
    _open: dict | None = None

    def reset(self) -> None:
        self.steps, self.llm_calls, self.llm_ms, self._open = [], 0, 0.0, None

    def as_dict(self) -> dict:
        return {"steps": self.steps, "llm_calls": self.llm_calls, "llm_ms": self.llm_ms if self.llm_calls else None}


def _short(value, limit: int = 300) -> str:
    text = value if isinstance(value, str) else str(value)
    return text if len(text) <= limit else text[:limit] + "..."


def _result_text(result: dict) -> str:
    return " ".join(c.get("text", "") for c in result.get("content", []))


class TraceHook(HookProvider):
    def __init__(self, trace: Trace, agent_name: str):
        self.trace = trace
        self.agent_name = agent_name
        self._model_t0: float | None = None

    def register_hooks(self, registry: HookRegistry, **kwargs) -> None:
        registry.add_callback(BeforeToolCallEvent, self.before_tool)
        registry.add_callback(AfterToolCallEvent, self.after_tool)
        registry.add_callback(BeforeModelCallEvent, self.before_model)
        registry.add_callback(AfterModelCallEvent, self.after_model)

    def before_tool(self, event: BeforeToolCallEvent) -> None:
        if self.agent_name == ORCHESTRATOR:
            # the input the orchestrator wrote for the specialist
            request = event.tool_use["input"]
            request = request.get("input", request) if isinstance(request, dict) else request
            self.trace._open = {"agent": event.tool_use["name"], "request": _short(request), "tools": []}
            self.trace.steps.append(self.trace._open)

    def after_tool(self, event: AfterToolCallEvent) -> None:
        ok = event.exception is None and event.result.get("status") == "success"
        ms = (event.duration or 0.0) * 1000
        if self.agent_name == ORCHESTRATOR:
            if self.trace._open:
                self.trace._open.update(ms=ms, ok=ok)
                self.trace._open = None
            return
        call = {"tool": event.tool_use["name"], "input": event.tool_use["input"], "ms": ms, "ok": ok,
                "output": _short(_result_text(event.result))}
        if self.trace._open is not None:
            self.trace._open["tools"].append(call)
        else:  # a specialist invoked directly, outside the orchestrator
            self.trace.steps.append({"agent": self.agent_name, "request": "", "tools": [call]})

    def before_model(self, event: BeforeModelCallEvent) -> None:
        self._model_t0 = time.perf_counter()

    def after_model(self, event: AfterModelCallEvent) -> None:
        if self._model_t0 is not None:
            self.trace.llm_calls += 1
            self.trace.llm_ms += (time.perf_counter() - self._model_t0) * 1000
            self._model_t0 = None
