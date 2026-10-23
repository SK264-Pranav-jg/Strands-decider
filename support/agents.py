"""The support orchestrator and its specialists, built once per session."""

import os
from functools import lru_cache

import boto3

from strands import Agent
from strands.models import BedrockModel
from strands.tools.executors import SequentialToolExecutor

from support.config import AWS_REGION, ORCHESTRATOR_MODEL_ID, OUT_OF_SCOPE_MODEL_ID, SPECIALIST_MODEL_ID
from support.decider import DeciderClient
from support.gate import Responder, ScopeGate
from support.prompts import SPECIALIST_SUFFIX, SPECIALISTS, STYLE, orchestrator_prompt, out_of_scope_prompt
from support.store import Store
from support.tools import build_tools
from support.trace import ORCHESTRATOR, OUT_OF_SCOPE, Trace, TraceHook


@lru_cache
def get_model(model_id: str) -> BedrockModel:
    """One BedrockModel per model id, shared by every agent and session."""
    # falls back to the default AWS credential chain when the keys are not in .env
    session = boto3.Session(
        aws_access_key_id=os.getenv("aws_access_key_id"),
        aws_secret_access_key=os.getenv("aws_secret_access_key"),
        aws_session_token=os.getenv("aws_session_token"),
        # strands rejects region_name alongside boto_session, so the region goes here
        region_name=AWS_REGION,
    )
    return BedrockModel(boto_session=session, model_id=model_id)


def build_out_of_scope_responder(customer: dict, trace: Trace) -> Responder:
    """The agent that answers what the gate keeps away from the orchestrator. It sits outside
    the orchestrator and has no tools; each message gets a fresh agent with no history."""

    async def respond(message: str) -> str:
        agent = Agent(
            model=get_model(OUT_OF_SCOPE_MODEL_ID),
            name=OUT_OF_SCOPE,
            system_prompt=out_of_scope_prompt(customer),
            hooks=[TraceHook(trace, OUT_OF_SCOPE)],
            callback_handler=None,
        )
        return str(await agent.invoke_async(message))

    return respond


def build_orchestrator(store: Store, customer: dict, decider: DeciderClient, trace: Trace) -> Agent:
    tools = build_tools(store, customer["id"])
    specialists = []
    for name, spec in SPECIALISTS.items():
        specialist = Agent(
            model=get_model(SPECIALIST_MODEL_ID),
            name=name,
            description=spec["description"],
            system_prompt=f"{spec['prompt']}\n\n{SPECIALIST_SUFFIX}\n\n{STYLE}",
            tools=tools[name],
            hooks=[TraceHook(trace, name)],
            callback_handler=None,
        )
        # fresh context on every call: the orchestrator owns the conversation
        specialists.append(specialist.as_tool(name=name, description=spec["description"], preserve_context=False))

    return Agent(
        model=get_model(ORCHESTRATOR_MODEL_ID),
        name=ORCHESTRATOR,
        system_prompt=orchestrator_prompt(customer),
        tools=specialists,
        # the gate runs first, so an out-of-scope message never reaches the orchestrator's model
        hooks=[ScopeGate(decider, build_out_of_scope_responder(customer, trace)), TraceHook(trace, ORCHESTRATOR)],
        # a specialist handles one call at a time, and the trace nests tools under the open call
        tool_executor=SequentialToolExecutor(),
        callback_handler=None,  # don't stream tokens to the server's stdout
    )
