FROM public.ecr.aws/lambda/python:3.12
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt -t /var/task/
COPY registry_catalog_handler.py /var/task/
CMD ["registry_catalog_handler.handler"]
