#!/bin/sh
set -e
# Run database migrations before starting the API, so a fresh
# deployment never starts with missing tables. If the database is
# unavailable, this fails fast instead of starting an API that
# cannot persist anything.
alembic upgrade head
exec "$@"
