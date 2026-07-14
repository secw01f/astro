#!/bin/bash
set -e

echo "Running database migrations"
alembic upgrade head

uvicorn api:api --host 0.0.0.0 --port 8000
