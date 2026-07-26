FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y curl && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY *.py ./
COPY ai.txt robots.txt ./
COPY entrypoint.sh ./
COPY gateway/package.json gateway/gateway.mjs ./gateway/

RUN cd gateway && npm install --omit=dev

RUN chmod +x entrypoint.sh

CMD ["./entrypoint.sh"]
