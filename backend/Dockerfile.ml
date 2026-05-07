FROM mcr.microsoft.com/playwright/python:v1.58.0-noble

WORKDIR /app

ARG TORCH_VERSION=2.10.0

COPY requirements.txt .
COPY requirements-runtime.txt .
COPY requirements-ml.txt .

RUN pip install --no-cache-dir -r requirements-runtime.txt \
    && pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch==${TORCH_VERSION} \
    && pip install --no-cache-dir -r requirements-ml.txt

COPY . .
