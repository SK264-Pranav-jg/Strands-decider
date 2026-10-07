import os

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


def create_agent(hooks: list[HookProvider] | None = None) -> Agent:
    # falls back to the default AWS credential chain when the keys are not in .env
    session = boto3.Session(
        aws_access_key_id=os.getenv("aws_access_key_id"),
        aws_secret_access_key=os.getenv("aws_secret_access_key"),
        aws_session_token=os.getenv("aws_session_token"),
        # strands rejects region_name alongside boto_session, so the region goes here
        region_name=os.getenv("AWS_REGION", "ap-south-1"),
    )

    model = BedrockModel(
        boto_session=session,
        model_id=os.getenv("BEDROCK_MODEL_ID", "global.anthropic.claude-haiku-4-5-20251001-v1:0"),
    )

    agent = Agent(
        model=model,
        name="Decider demo agent",
        system_prompt=return_prompt(),
        hooks=hooks,
        callback_handler=None,  # don't stream tokens to the server's stdout
    )

    return agent
