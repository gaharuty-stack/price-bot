FROM python:3.11-slim

WORKDIR /app

# Устанавливаем Node.js 22.x (LTS) и необходимые пакеты
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

# Устанавливаем глобально npx (хотя это не обязательно)
RUN npm install -g npx

# Запускаем бота и прослойку в одном контейнере
CMD python bot.py & npx agent402-tollbooth --target http://localhost:5000 --config tollbooth.config.json
