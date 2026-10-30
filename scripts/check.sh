#!/bin/sh
set -e
cd "$(dirname "$0")/../backend"
python -m ruff check app tests
python -m ruff format --check app tests
python -m black --check app tests
python -m pytest -q
cd ../frontend
npm run build
