FROM --platform=linux/arm64 ghcr.io/astral-sh/uv:latest AS uv
FROM --platform=linux/arm64 public.ecr.aws/lambda/python:3.12-arm64

COPY --from=uv /uv /bin/uv
COPY requirements.txt ./
RUN uv pip install --system --no-cache -r requirements.txt

COPY handler.py run_server.py ./

CMD ["handler.handler"]
