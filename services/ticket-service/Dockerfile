FROM public.ecr.aws/lambda/python:3.12 AS builder
WORKDIR /var/task
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt -t /var/task

FROM public.ecr.aws/lambda/python:3.12
# ADOT layer — AWS_LAMBDA_EXEC_WRAPPER=/opt/otel-instrument で otel-instrument が有効になる
# Lambda Python ベースイメージでは AWS_LAMBDA_EXEC_WRAPPER が機能する
RUN dnf install -y --nodocs unzip wget && \
    wget -q https://github.com/aws-observability/aws-otel-python-instrumentation/releases/latest/download/layer.zip -O /tmp/layer.zip && \
    unzip -q /tmp/layer.zip -d /opt/ && chmod -R 755 /opt/ && rm /tmp/layer.zip && \
    dnf clean all
COPY --from=builder /var/task /var/task
COPY app/ /var/task/app/
CMD ["app.main.handler"]
