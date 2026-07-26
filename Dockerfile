FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /app

RUN apt-get update && apt-get install -y curl ca-certificates && \
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y nodejs && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY package.json gateway.mjs ./
RUN npm install --omit=dev

COPY *.py ./
COPY ai.txt robots.txt ./

EXPOSE 8080

CMD sh -c "gunicorn --bind 127.0.0.1:5000 --workers 1 --threads 4 --timeout 120 bot:app & sleep 4 && exec node gateway.mjs"
