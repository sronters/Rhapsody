#!/usr/bin/env sh
set -eu

: "${MINIO_ALIAS:=teammind-minio}"
: "${S3_BUCKET:=teammind}"
: "${BACKUP_DIR:?BACKUP_DIR is required}"

mc mirror "$BACKUP_DIR" "$MINIO_ALIAS/$S3_BUCKET"