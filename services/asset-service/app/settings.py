from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    table_name: str = "agora-assets"
    aws_region: str = "us-east-1"
