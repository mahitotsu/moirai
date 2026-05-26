from __future__ import annotations

import boto3
from pydantic import model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    table_name: str
    # Set directly via API_KEY, or resolved at startup from API_KEY_SECRET_NAME
    api_key: str = ""
    api_key_secret_name: str = ""
    gateway_prompt_arn: str = ""
    triage_prompt_arn: str = ""
    diagnosis_prompt_arn: str = ""
    resolution_prompt_arn: str = ""

    @model_validator(mode="after")
    def resolve_api_key_from_secret(self) -> Settings:
        if not self.api_key and self.api_key_secret_name:
            sm = boto3.client("secretsmanager")
            self.api_key = sm.get_secret_value(SecretId=self.api_key_secret_name)["SecretString"]
        return self
