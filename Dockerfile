FROM python:3.11-slim

WORKDIR /app

# Устанавливаем зависимости и инструменты
RUN apt-get update && apt-get install -y curl && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    apt-get clean

# Копируем файлы проекта
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py .
COPY tollbooth.config.json .

# Устанавливаем npx и запускаем оба процесса
CMD python bot.py & npx agent402-tollbooth --target http://localhost:5000 --config tollbooth.config.json
