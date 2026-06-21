#!/usr/bin/env sh
set -eu

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.oracle.yml}"
BACKUP_ROOT="${BACKUP_ROOT:-./backups}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"

mkdir -p "$BACKUP_ROOT/postgres" "$BACKUP_ROOT/minio"

docker compose -f "$COMPOSE_FILE" exec -T postgres \
  pg_dump -U rhapsody -d rhapsody \
  | gzip > "$BACKUP_ROOT/postgres/rhapsody-$STAMP.sql.gz"

docker compose -f "$COMPOSE_FILE" run --rm \
  --volume "$(pwd)/$BACKUP_ROOT/minio:/backup" \
  --entrypoint sh \
  minio-init -c "
    mc alias set local http://minio:9000 \"\$S3_ACCESS_KEY_ID\" \"\$S3_SECRET_ACCESS_KEY\" >/dev/null &&
    mc mirror local/\"\${S3_BUCKET:-rhapsody}\" /backup/\"\${S3_BUCKET:-rhapsody}-$STAMP\"
  "

echo "Backups written to $BACKUP_ROOT"
