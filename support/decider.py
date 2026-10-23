"""HTTP client for a strands-decider server (`strands-decider serve`)."""

import asyncio
import logging

import httpx

from support.config import DECIDER_CONCURRENCY, DECIDER_URL

log = logging.getLogger("support")


class DeciderError(Exception):
    """The decider could not be reached or rejected the request."""


class DeciderClient:
    def __init__(self, base_url: str = DECIDER_URL, concurrency: int = DECIDER_CONCURRENCY):
        self.base_url = base_url
        self.http = httpx.AsyncClient(base_url=base_url, timeout=60.0)
        self._slots = asyncio.Semaphore(concurrency)

    async def ask(self, state: str, questions: dict) -> dict:
        """Ask every question about `state` in one request (one forward pass over the text).

        Returns the raw `answers` keyed like `questions`, plus latency and input tokens.
        """
        try:
            async with self._slots:
                r = await self.http.post("/v1/systemone", json={"state": state, "questions": questions})
        except httpx.HTTPError as e:
            log.warning("decider unreachable: %r", e)
            raise DeciderError(
                f"Could not reach the decider model at {self.base_url}. Is `strands-decider serve` running?"
            ) from e

        try:
            if r.status_code >= 400:
                detail = r.json().get("detail", r.text) if "json" in r.headers.get("content-type", "") else r.text
                raise DeciderError(f"Decider model returned {r.status_code}: {detail}")
            body = r.json()
            answers = {key: body["answers"][key] for key in questions}
        except (ValueError, KeyError, TypeError, AttributeError) as e:
            raise DeciderError(f"Decider model returned an unexpected response: {e!r}") from e

        return {
            "answers": answers,
            "decider_ms": body.get("latency_ms", 0.0),
            "tokens": body.get("usage", {}).get("input_tokens"),
        }

    async def health(self) -> dict:
        r = await self.http.get("/health", timeout=3.0)
        r.raise_for_status()
        return r.json()

    async def aclose(self):
        await self.http.aclose()
