"""Settings from the environment. `.env` at the project root is loaded once, here."""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DECIDER_URL = os.getenv("DECIDER_URL", "http://localhost:9000")
# requests this app sends the decider at once; on Apple GPUs (mps) overlapping requests
# crash `strands-decider serve`, so the default sends one at a time
DECIDER_CONCURRENCY = int(os.getenv("DECIDER_CONCURRENCY", "1"))
AWS_REGION = os.getenv("AWS_REGION", "ap-south-1")

# the orchestrator plans and writes the reply; the specialists only call tools
ORCHESTRATOR_MODEL_ID = os.getenv("ORCHESTRATOR_MODEL_ID", "global.anthropic.claude-sonnet-5-5")
SPECIALIST_MODEL_ID = os.getenv("SPECIALIST_MODEL_ID", "global.anthropic.claude-haiku-4-5-20251001-v1:0")
# answers what the gate keeps away from the orchestrator; a short reply needs no big model
OUT_OF_SCOPE_MODEL_ID = os.getenv("OUT_OF_SCOPE_MODEL_ID", "global.anthropic.claude-haiku-4-5-20251001-v1:0")
