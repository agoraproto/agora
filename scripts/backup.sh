#!/usr/bin/env bash
# Daily pg_dump backup of the Agora Postgres database.
#
# Installed via systemd-timer (see deploy/agora-backup.timer).
# Output:  /var/backups/agora/agora-YYYY-MM-DD.sql.gz
# Retention: 14 days (older files are deleted).
set -euo pipefail

BACKUP_DIR=/var/backups/agora
DB_NAME=agora
DB_USER=agora
RETENTION_DAYS=14

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

stamp=$(date +%Y-%m-%d_%H%M)
outfile="$BACKUP_DIR/agora-${stamp}.sql.gz"

echo "[$(date -Is)] backup start -> $outfile"
sudo -u postgres pg_dump --no-owner --no-privileges "$DB_NAME" | gzip -9 > "$outfile"
size=$(du -h "$outfile" | cut -f1)
echo "[$(date -Is)] backup done ($size)"

echo "[$(date -Is)] cleanup: deleting files older than ${RETENTION_DAYS}d"
find "$BACKUP_DIR" -name 'agora-*.sql.gz' -mtime +${RETENTION_DAYS} -print -delete

echo "[$(date -Is)] OK"
