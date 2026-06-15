FROM python:3.12-slim AS api
COPY api/ /api
WORKDIR /api
RUN pip install --no-cache-dir --retries 10 --default-timeout=300 -r requirements.txt
RUN useradd --create-home --uid 10001 astro \
    && mkdir -p /api/specs /var/log/astro /var/lib/astro/files \
    && chown -R astro:astro /api /var/log/astro /var/lib/astro
USER astro

FROM python:3.12-slim AS tools
COPY tools/ /tools
WORKDIR /tools
RUN pip install --no-cache-dir --retries 10 --default-timeout=300 -r requirements.txt
RUN apt-get update \
    && apt-get install -y --no-install-recommends nmap \
    && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --uid 10001 astro \
    && chown -R astro:astro /tools
USER astro
