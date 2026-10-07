#!/bin/sh
set -eu

: "${M2_DB_HOST:?set M2_DB_HOST}"
: "${M2_DB_USER:?set M2_DB_USER}"
: "${M2_DB_PASSWORD:?set M2_DB_PASSWORD}"

workdir=$(mktemp -d)
trap 'rm -rf "$workdir"' EXIT

echo "Extracting backup..."
unzip -q /opt/restore/db-backup.zip -d "$workdir"

for database in account common world player log hotbackup; do
  dump="$workdir/$database.sql"
  test -f "$dump"
  echo "Restoring $database..."
  mariadb --protocol=TCP \
    --host="$M2_DB_HOST" \
    --port="${M2_DB_PORT:-3306}" \
    --user="$M2_DB_USER" \
    --password="$M2_DB_PASSWORD" \
    "$database" < "$dump"
done

echo "Restore completed successfully."
