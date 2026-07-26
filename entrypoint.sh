#!/bin/bash
set -e
python bot.py &
sleep 5
exec node gateway.mjs
