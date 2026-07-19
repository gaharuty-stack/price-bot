#!/bin/bash
python bot.py &
npx agent402-tollbooth --target http://localhost:5000 --config tollbooth.config.json
