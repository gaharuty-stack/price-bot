FROM python:3.11-slim

WORKDIR /app

# Устанавливаем Node.js
RUN apt-get update && apt-get install -y curl && \
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y nodejs && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Устанавливаем Python-зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем код, конфиг и скрипт
COPY bot.py .
COPY tollbooth.config.json .
COPY entrypoint.sh .

# Делаем скрипт исполняемым
RUN chmod +x entrypoint.sh

# Устанавливаем agent402-tollbooth глобально
RUN npm install -g agent402-tollbooth@0.4.3

# Запускаем через обёртку
CMD ./entrypoint.sh
