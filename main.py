import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import uvicorn
from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from pydantic import BaseModel, Field

STATIC = Path(__file__).resolve().parent
load_dotenv(STATIC / ".env")

from agent.agent import create_agent
from agent.decider_gate import (
    DEFAULT_INSTRUCTIONS,
    DEFAULT_THRESHOLD,
    DeciderClient,
    DeciderError,
    DeciderGate,
    MockLLM,
)

log = logging.getLogger("pii-gate")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

# MOCK_LLM=1 runs the whole demo without calling Bedrock
MOCK_LLM = os.getenv("MOCK_LLM", "").lower() in ("1", "true", "yes")


class ChatRequest(BaseModel):
    message: str
    threshold: float = Field(DEFAULT_THRESHOLD, ge=0.0, le=1.0)
    instructions: str | None = None


class ScoreRequest(BaseModel):
    message: str
    instructions: str | None = None


decider: DeciderClient
agent = None
agent_lock = asyncio.Lock()  # a Strands Agent rejects concurrent invocations


@asynccontextmanager
async def lifespan(app: FastAPI):
    global decider
    decider = DeciderClient()
    yield
    await decider.aclose()


app = FastAPI(title="PII gate demo", lifespan=lifespan)
# lets the page work when opened from an editor's Live Server instead of from "/"
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?|null",
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")


def get_agent():
    global agent
    if agent is None:
        # the gate is a hook, so every way of invoking the agent goes through it
        hooks = [DeciderGate(decider)]
        if MOCK_LLM:
            hooks.append(MockLLM())  # after the gate: only answers what it let through
        agent = create_agent(hooks=hooks)
    return agent


@app.get("/api/defaults", tags=["chat"])
async def defaults():
    return {"instructions": DEFAULT_INSTRUCTIONS, "threshold": DEFAULT_THRESHOLD, "mock_llm": MOCK_LLM}


@app.get("/api/health", tags=["chat"])
async def health():
    try:
        return {"decider": "ok", **await decider.health(), "mock_llm": MOCK_LLM}
    except httpx.HTTPError:
        return {"decider": "down", "url": decider.base_url, "mock_llm": MOCK_LLM}


@app.post("/api/score", tags=["chat"])
async def score(req: ScoreRequest):
    """Score only, never touches the agent. Used for the live meter while typing."""
    text = req.message.strip()
    if not text:
        raise HTTPException(400, detail="Message Empty")
    try:
        return await decider.pii_score(text, (req.instructions or "").strip() or DEFAULT_INSTRUCTIONS)
    except DeciderError as e:
        raise HTTPException(502, str(e))


@app.post("/api/chat", tags=["chat"])
async def chat(req: ChatRequest):
    text = req.message.strip()
    if not text:
        raise HTTPException(400, detail="Message Empty")

    # per-request gate settings in, gate results out (DeciderGate reads and fills this)
    gate = {"threshold": req.threshold, "instructions": (req.instructions or "").strip()}

    t0 = time.perf_counter()
    try:
        async with agent_lock:
            response = await get_agent().invoke_async(text, invocation_state={"decider": gate})
    except Exception as e:
        log.exception("agent invocation failed")
        raise HTTPException(502, f"Could not reach the Bedrock model: {type(e).__name__}: {e}")
    total_ms = (time.perf_counter() - t0) * 1000

    if "error" in gate:
        # the hook failed closed; show the cause rather than a generic block
        raise HTTPException(502, gate["error"])

    blocked = gate["blocked"]
    return {
        "score": gate["score"],
        "categories": gate["categories"],
        "decider_ms": gate["decider_ms"],
        "tokens": gate["tokens"],
        "threshold": gate["threshold"],
        "gate_ms": gate["gate_ms"],
        "blocked": blocked,
        "reply": str(response).strip(),
        "llm_ms": None if blocked or MOCK_LLM else total_ms - gate["gate_ms"],
    }


@app.post("/api/reset", tags=["chat"])
async def reset():
    """Forget the agent's conversation history."""
    global agent
    async with agent_lock:
        agent = None
    return {"ok": True}


if __name__ == "__main__":
    uvicorn.run(
        app="main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
    )
