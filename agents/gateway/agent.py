from __future__ import annotations

from pathlib import Path

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import Agent
from strands.models import BedrockModel
from tools import run_diagnosis, run_resolution, run_triage

MODEL_ID = "us.anthropic.claude-sonnet-4-6"
_SYSTEM_PROMPT = (Path(__file__).parent / "system_prompt.md").read_text()

app = BedrockAgentCoreApp()


def _create_agent() -> Agent:
    return Agent(
        model=BedrockModel(model_id=MODEL_ID, region_name="us-east-1"),
        system_prompt=_SYSTEM_PROMPT,
        tools=[run_triage, run_diagnosis, run_resolution],
    )


@app.entrypoint
def invoke(payload, context):
    agent = _create_agent()
    prompt = payload.get("prompt", payload.get("message", ""))
    result = agent(prompt)
    return {"response": str(result)}


if __name__ == "__main__":
    app.run()
