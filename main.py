import logging
from contextlib import asynccontextmanager

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from support.config import ORCHESTRATOR_MODEL_ID, OUT_OF_SCOPE_MODEL_ID, ROOT, SPECIALIST_MODEL_ID
from support.decider import DeciderClient, DeciderError
from support.examples import EXAMPLES
from support.gate import DEFAULT_SCOPE_THRESHOLD, FOLLOW_UP_QUESTIONS, QUESTIONS
from support.prompts import SPECIALISTS
from support.sessions import Sessions
from support.store import CUSTOMERS, SIGNED_IN_CUSTOMER_ID, Store
from support.tools import build_tools
from support.trace import ORCHESTRATOR, OUT_OF_SCOPE

log = logging.getLogger("support")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=64)
    message: str
    scope_threshold: float = Field(DEFAULT_SCOPE_THRESHOLD, ge=0.0, le=1.0)


class ResetRequest(BaseModel):
    session_id: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    # tests may install a fake decider before startup
    if not hasattr(app.state, "decider"):
        app.state.decider = DeciderClient()
    app.state.sessions = Sessions(app.state.decider)
    yield
    await app.state.decider.aclose()


app = FastAPI(title="Acme Electronics support, behind a decider gate", lifespan=lifespan)
# lets the page work when opened from an editor's Live Server instead of from "/"
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?|null",
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def index():
    return FileResponse(ROOT / "index.html")


@app.get("/api/defaults", tags=["chat"])
async def defaults():
    tools = build_tools(Store(), "")  # only for the tool names
    return {
        "scope_threshold": DEFAULT_SCOPE_THRESHOLD,
        "questions": {key: q["instructions"] for key, q in (QUESTIONS | FOLLOW_UP_QUESTIONS).items()},
        "customer": CUSTOMERS[SIGNED_IN_CUSTOMER_ID],
        "examples": EXAMPLES,
        "models": {"orchestrator": ORCHESTRATOR_MODEL_ID, "specialist": SPECIALIST_MODEL_ID,
                   "out_of_scope": OUT_OF_SCOPE_MODEL_ID},
        "specialists": [
            {"name": name, "description": spec["description"], "tools": [t.tool_name for t in tools[name]]}
            for name, spec in SPECIALISTS.items()
        ],
    }


@app.get("/api/health", tags=["chat"])
async def health():
    decider = app.state.decider
    try:
        return {"decider": "ok", **await decider.health()}
    except (httpx.HTTPError, ValueError):
        return {"decider": "down", "url": decider.base_url}


@app.post("/api/chat", tags=["chat"])
async def chat(req: ChatRequest):
    text = req.message.strip()
    if not text:
        raise HTTPException(400, detail="Message Empty")

    session = app.state.sessions.get(req.session_id)
    gate = {"scope_threshold": req.scope_threshold}

    async with session.lock:
        session.trace.reset()
        try:
            response = await session.agent.invoke_async(text, invocation_state={"gate": gate})
        except DeciderError as e:
            raise HTTPException(502, str(e))
        except Exception as e:
            who = "out-of-scope agent" if gate.get("decision") == "out_of_scope" else "orchestrator"
            log.exception("%s invocation failed", who)
            raise HTTPException(502, f"The {who} failed: {type(e).__name__}: {e}")
        trace = session.trace.as_dict()

    # ScopeGate fills these in on every turn it doesn't raise for
    return {
        "decision": gate["decision"],
        "reason": gate["reason"],
        "handled_by": ORCHESTRATOR if gate["decision"] == "in_scope" else OUT_OF_SCOPE,
        "gate": {key: gate[key] for key in
                 ("scope", "in_scope", "follow_up", "threshold", "decider_ms", "gate_ms", "tokens", "requests")},
        "reply": str(response).strip(),
        "trace": trace["steps"],
        "llm_calls": trace["llm_calls"],
        "llm_ms": trace["llm_ms"],
    }


@app.post("/api/reset", tags=["chat"])
async def reset(req: ResetRequest):
    """Forget the session's conversation and restore its mock data."""
    app.state.sessions.reset(req.session_id)
    return {"ok": True}


if __name__ == "__main__":
    uvicorn.run(
        app="main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
    )
