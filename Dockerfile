FROM python:3.12-slim AS api
COPY api/ /api
COPY .env /api
WORKDIR /api
RUN pip install --no-cache-dir --retries 10 --default-timeout=300 -r requirements.txt

FROM python:3.12-slim AS tools
COPY tools/ /tools
COPY .env /tools
WORKDIR /tools
RUN pip install --no-cache-dir --retries 10 --default-timeout=300 -r requirements.txt
RUN apt-get update \
    && apt-get install -y --no-install-recommends nmap \
    && rm -rf /var/lib/apt/lists/*
