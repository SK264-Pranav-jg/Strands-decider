import os
from functools import lru_cache

import boto3
from dotenv import load_dotenv
from pathlib import Path

from strands import Agent
from strands.hooks import HookProvider
from strands.models import BedrockModel

from prompt.main_prompt import return_prompt

# .env lives at the project root, one level above this package
env_path = Path(__file__).resolve().parent.parent / ".env"

load_dotenv(dotenv_path=env_path)

DEFAULT_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "global.anthropic.claude-haiku-4-5-20251001-v1:0")


@lru_cache
def get_model(model_id: str = DEFAULT_MODEL_ID) -> BedrockModel:
    """One BedrockModel per model id, shared so the router can swap them per request."""
    # falls back to the default AWS credential chain when the keys are not in .env
    session = boto3.Session(
        aws_access_key_id=os.getenv("aws_access_key_id"),
        aws_secret_access_key=os.getenv("aws_secret_access_key"),
        aws_session_token=os.getenv("aws_session_token"),
        # strands rejects region_name alongside boto_session, so the region goes here
        region_name=os.getenv("AWS_REGION", "ap-south-1"),
    )
    return BedrockModel(boto_session=session, model_id=model_id)


def create_agent(hooks: list[HookProvider] | None = None) -> Agent:
    agent = Agent(
        model=get_model(),
        name="Decider demo agent",
        system_prompt=return_prompt(),
        hooks=hooks,
        callback_handler=None,  # don't stream tokens to the server's stdout
    )

    return agent
