FROM python:3.11-slim

WORKDIR /app

# Устанавливаем Node.js и необходимые пакеты
RUN apt-get update && apt-get install -y curl && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    apt-get clean

# Копируем зависимости и устанавливаем их
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем код и конфиг
COPY bot.py .
COPY tollbooth.config.json .

# Запускаем бота и прослойку в одном контейнере
CMD python bot.py & npx agent402-tollbooth --target http://localhost:5000 --config tollbooth.config.json
