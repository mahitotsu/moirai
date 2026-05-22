FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv
WORKDIR /app
COPY resolution/pyproject.toml resolution/requirements.txt ./
COPY common/ ./common/
RUN uv pip install --system --no-cache -r requirements.txt

FROM python:3.12-slim
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY resolution/agent.py resolution/system_prompt.md ./
COPY common/ ./common/
EXPOSE 9000
CMD ["opentelemetry-instrument", "python", "agent.py"]
