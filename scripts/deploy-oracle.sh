#!/usr/bin/env sh
set -eu

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.oracle.yml}"

if [ ! -f .env ]; then
  if [ -f .env.oracle.example ]; then
    cp .env.oracle.example .env
    chmod 600 .env
    echo "Created .env from .env.oracle.example. Edit it before starting the stack."
    exit 1
  fi
  echo ".env is required. Copy .env.oracle.example to .env and fill secrets." >&2
  exit 1
fi

docker compose -f "$COMPOSE_FILE" pull --ignore-buildable
docker compose -f "$COMPOSE_FILE" build
docker compose -f "$COMPOSE_FILE" up -d
docker compose -f "$COMPOSE_FILE" ps
