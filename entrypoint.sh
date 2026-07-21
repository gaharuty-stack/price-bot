#!/bin/bash
set -e

python bot.py &
BOT_PID=$!

sleep 5

if ! kill -0 $BOT_PID 2>/dev/null; then
    echo "Ошибка: бот не запустился"
    exit 1
fi

PORT=${PORT:-10000}
agent402-tollbooth \
  --target http://localhost:5000 \
  --config tollbooth.config.json \
  --port $PORT \
  --host 0.0.0.0

wait
