from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    agent_runtime_arn: str = ""
    aws_region: str = "us-east-1"
