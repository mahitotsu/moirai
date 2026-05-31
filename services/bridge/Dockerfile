FROM python:3.12-slim AS builder
WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt --target /build/packages

FROM public.ecr.aws/lambda/python:3.12
RUN dnf install -y unzip wget && dnf clean all && \
    wget -q https://github.com/aws-observability/aws-otel-python-instrumentation/releases/latest/download/layer.zip -O /tmp/layer.zip && \
    unzip -q /tmp/layer.zip -d /opt/ && chmod -R 755 /opt/ && rm /tmp/layer.zip
COPY --from=builder /build/packages/ /var/task/
COPY lambda_function.py /var/task/
CMD ["lambda_function.handler"]
