#!/bin/bash
set -e

python bot.py &

sleep 3

PORT=${PORT:-10000}
agent402-tollbooth \
  --target http://localhost:5000 \
  --config tollbooth.config.json \
  --port $PORT \
  --host 0.0.0.0

wait
