#!/bin/bash
set -euo pipefail

# Flask/gunicorn on loopback; Express x402 gateway is the public PORT.
gunicorn --bind 127.0.0.1:5000 --workers 1 --threads 8 --timeout 25 --keep-alive 5 bot:app &
APP_PID=$!

sleep 3

if ! kill -0 "$APP_PID" 2>/dev/null; then
  echo "Error: gunicorn failed to start"
  exit 1
fi

exec node gateway.mjs
