#!/usr/bin/env sh
set -eu

: "${MINIO_ALIAS:=rhapsody-minio}"
: "${S3_BUCKET:=rhapsody}"
: "${BACKUP_DIR:?BACKUP_DIR is required}"

mc mirror "$BACKUP_DIR" "$MINIO_ALIAS/$S3_BUCKET"