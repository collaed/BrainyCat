#!/bin/sh
# Initialize the brainycat database on the existing postgres container.
# Run once before first docker compose up.
set -e

PGHOST="${1:-postgres}"
docker exec "$PGHOST" psql -U postgres -c "
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'brainycat') THEN
        CREATE ROLE brainycat WITH LOGIN PASSWORD 'brainycat';
    END IF;
END \$\$;
SELECT 'role ok';
"

docker exec "$PGHOST" psql -U postgres -c "
SELECT 'db exists' FROM pg_database WHERE datname = 'brainycat'
UNION ALL
SELECT 'creating' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'brainycat');
"

docker exec "$PGHOST" psql -U postgres -tc "SELECT 1 FROM pg_database WHERE datname = 'brainycat'" | grep -q 1 || \
    docker exec "$PGHOST" psql -U postgres -c "CREATE DATABASE brainycat OWNER brainycat"

# Grant permissions
docker exec "$PGHOST" psql -U postgres -d brainycat -c "GRANT ALL ON SCHEMA public TO brainycat;"

echo "Database ready."
