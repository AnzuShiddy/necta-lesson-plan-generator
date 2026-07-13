#!/usr/bin/env bash
# Start the lesson plan generator.
# Requires GEMINI_API_KEY (free key at https://aistudio.google.com/apikey).
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/pip install -q -r requirements.txt
fi
exec .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
