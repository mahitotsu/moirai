FROM python:3.12-slim AS builder
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM python:3.12-slim
# Lambda Web Adapter — translates Lambda events to HTTP and back
COPY --from=public.ecr.aws/awsguru/aws-lambda-adapter:0.9.1 /lambda-adapter /opt/extensions/lambda-adapter
# ADOT layer — auto-instruments via AWS_LAMBDA_EXEC_WRAPPER=/opt/otel-instrument
RUN apt-get update && apt-get install -y --no-install-recommends unzip wget && apt-get clean && rm -rf /var/lib/apt/lists/* && \
    wget -q https://github.com/aws-observability/aws-otel-python-instrumentation/releases/latest/download/layer.zip -O /tmp/layer.zip && \
    unzip -q /tmp/layer.zip -d /opt/ && chmod -R 755 /opt/ && rm /tmp/layer.zip
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin/uvicorn /usr/local/bin/uvicorn
COPY app/ app/
ENV PORT=8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
