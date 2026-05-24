FROM --platform=linux/arm64 ghcr.io/astral-sh/uv:latest AS uv
FROM --platform=linux/arm64 python:3.12-slim AS builder
COPY --from=uv /uv /bin/uv
WORKDIR /app
COPY resolution/pyproject.toml resolution/requirements.txt ./
RUN uv pip install --system --no-cache -r requirements.txt

FROM --platform=linux/arm64 python:3.12-slim
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY common/registry.py ./
COPY resolution/agent.py resolution/system_prompt.md ./
EXPOSE 8080
CMD ["opentelemetry-instrument", "python", "agent.py"]
