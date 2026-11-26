#!/usr/bin/env bash
# Start Fresh Vibe (macOS / Linux). First run creates .venv and installs deps.
set -e
cd "$(dirname "$0")/.."
if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/pip install --upgrade pip
  .venv/bin/pip install -r requirements.txt
fi
[ -f .env ] || cp .env.example .env
cd backend && exec ../.venv/bin/python -m app
