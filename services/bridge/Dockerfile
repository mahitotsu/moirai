FROM python:3.12-slim AS builder
WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt --target /build/packages

FROM public.ecr.aws/lambda/python:3.12
COPY --from=builder /build/packages/ /var/task/
COPY lambda_function.py /var/task/
CMD ["lambda_function.handler"]
