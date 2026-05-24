FROM --platform=linux/arm64 ghcr.io/astral-sh/uv:latest AS uv
FROM --platform=linux/arm64 python:3.12-slim AS builder
COPY --from=uv /uv /bin/uv
WORKDIR /app
COPY diagnosis/pyproject.toml diagnosis/requirements.txt ./
RUN uv pip install --system --no-cache -r requirements.txt

FROM --platform=linux/arm64 python:3.12-slim
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY common/registry.py ./
COPY diagnosis/agent.py diagnosis/system_prompt.md diagnosis/tools.py ./
EXPOSE 8080
CMD ["opentelemetry-instrument", "python", "agent.py"]
