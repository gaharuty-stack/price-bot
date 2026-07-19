FROM python:3.11-slim

WORKDIR /app

# Устанавливаем Node.js 22.x (LTS)
RUN apt-get update && apt-get install -y curl && \
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y nodejs && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Копируем зависимости и устанавливаем их
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем код и конфиг
COPY bot.py .
COPY tollbooth.config.json .

# Устанавливаем agent402-tollbooth глобально
RUN npm install -g agent402-tollbooth@0.4.3

# Запускаем бота и прослойку в одном контейнере
CMD python bot.py & agent402-tollbooth --target http://localhost:5000 --config tollbooth.config.json
