#!/bin/bash
set -e

# Запускаем бота в фоне
python bot.py &

# Ждём 3 секунды, чтобы бот успел стартовать
sleep 3

# Запускаем прослойку в фоновом режиме
agent402-tollbooth --target http://localhost:5000 --config tollbooth.config.json

# Держим процесс активным
wait
