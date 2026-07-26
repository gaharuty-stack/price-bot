#!/bin/bash
set -e

python bot.py &
BOT_PID=$!

sleep 5

if ! kill -0 "$BOT_PID" 2>/dev/null; then
  echo "Error: Flask bot failed to start"
  exit 1
fi

cd gateway
exec node gateway.mjs
