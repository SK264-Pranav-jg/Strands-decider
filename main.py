import asyncio
import logging
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
)
from agent.router import (
    DEFAULT_ROUTE_FLOOR,
    TEAMS,
    TIERS,
)

log = logging.getLogger("pii-gate")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

class ChatRequest(BaseModel):
    message: str
    threshold: float = Field(DEFAULT_THRESHOLD, ge=0.0, le=1.0)
    instructions: str | None = None
    # team picks with confidence below this go to the general agent
    route_floor: float = Field(DEFAULT_ROUTE_FLOOR, ge=0.0, le=1.0)


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
        agent = create_agent(hooks=[DeciderGate(decider)])
    return agent


@app.get("/api/defaults", tags=["chat"])
async def defaults():
    return {
        "instructions": DEFAULT_INSTRUCTIONS,
        "threshold": DEFAULT_THRESHOLD,
        "route_floor": DEFAULT_ROUTE_FLOOR,
        "teams": {key: t["label"] for key, t in TEAMS.items()},
        "tiers": {key: t["label"] for key, t in TIERS.items()},
    }


@app.get("/api/health", tags=["chat"])
async def health():
    try:
        return {"decider": "ok", **await decider.health()}
    except (httpx.HTTPError, ValueError):
        return {"decider": "down", "url": decider.base_url}


@app.post("/api/chat", tags=["chat"])
async def chat(req: ChatRequest):
    text = req.message.strip()
    if not text:
        raise HTTPException(400, detail="Message Empty")

    gate = {
        "threshold": req.threshold,
        "instructions": (req.instructions or "").strip(),
        # value that is used to route the models 
        "route_floor": req.route_floor,
    }

    try:
        async with agent_lock:
            assistant = get_agent()
            response = await assistant.invoke_async(text, invocation_state={"decider": gate})
    except DeciderError as e:
        raise HTTPException(502, str(e))
    except Exception as e:
        log.exception("agent invocation failed")
        raise HTTPException(502, f"Could not reach the Bedrock model: {type(e).__name__}: {e}")

    # DeciderGate fills these in on every turn it doesn't raise for
    return {
        "score": gate["score"],
        "categories": gate["categories"],
        "decider_ms": gate["decider_ms"],
        "tokens": gate["tokens"],
        "threshold": gate["threshold"],
        "gate_ms": gate["gate_ms"],
        "blocked": gate["blocked"],
        "reply": str(response).strip(),
        "llm_ms": gate.get("llm_ms"),
        "route": gate.get("route"),
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
