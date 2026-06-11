#!/usr/bin/env sh
set -eu

: "${MINIO_ALIAS:=rhapsody-minio}"
: "${S3_BUCKET:=rhapsody}"
: "${BACKUP_DIR:=./backups/minio}"

mkdir -p "$BACKUP_DIR"
mc mirror "$MINIO_ALIAS/$S3_BUCKET" "$BACKUP_DIR/$S3_BUCKET-$(date -u +%Y%m%dT%H%M%SZ)"