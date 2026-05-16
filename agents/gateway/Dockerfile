FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv
WORKDIR /app
COPY gateway/pyproject.toml gateway/requirements.txt ./
COPY common/ ./agents/common/
RUN uv pip install --system --no-cache -r requirements.txt

FROM python:3.12-slim
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY gateway/agent.py gateway/system_prompt.md gateway/tools.py ./
COPY common/ ./agents/common/
EXPOSE 8080
CMD ["python", "agent.py"]
