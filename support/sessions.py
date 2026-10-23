"""One orchestrator, store and trace per browser session, all for the signed-in customer."""

import asyncio
from collections import OrderedDict
from dataclasses import dataclass, field

from strands import Agent

from support.agents import build_orchestrator
from support.decider import DeciderClient
from support.store import CUSTOMERS, SIGNED_IN_CUSTOMER_ID, Store
from support.trace import Trace

MAX_SESSIONS = 50


@dataclass
class Session:
    store: Store
    trace: Trace
    agent: Agent
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)  # an Agent rejects concurrent invocations


class Sessions:
    def __init__(self, decider: DeciderClient, max_sessions: int = MAX_SESSIONS):
        self.decider = decider
        self.max_sessions = max_sessions
        self._sessions: OrderedDict[str, Session] = OrderedDict()

    def _create(self) -> Session:
        store, trace = Store(), Trace()
        agent = build_orchestrator(store, CUSTOMERS[SIGNED_IN_CUSTOMER_ID], self.decider, trace)
        return Session(store, trace, agent)

    def get(self, session_id: str) -> Session:
        """The session for this id, created on first use."""
        session = self._sessions.get(session_id)
        if session is None:
            session = self._create()
            self._sessions[session_id] = session
        self._sessions.move_to_end(session_id)
        while len(self._sessions) > self.max_sessions:
            self._sessions.popitem(last=False)
        return session

    def reset(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
