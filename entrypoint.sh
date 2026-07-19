#!/bin/bash
set -e

# Бот слушает на порту 5000
python bot.py &

sleep 3

# Tollbooth проксирует с порта 10000 (внешний) на 5000 (внутренний)
agent402-tollbooth \
  --target http://localhost:5000 \
  --config tollbooth.config.json \
  --port 10000 \
  --host 0.0.0.0

wait
