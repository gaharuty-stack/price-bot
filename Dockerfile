FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates bash && \
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY package.json package-lock.json* ./
RUN npm install --omit=dev

COPY gateway.mjs entrypoint.sh ./
COPY *.py ./
COPY ai.txt robots.txt ./

# Windows checkouts may ship CRLF; Linux then fails with "No such file or directory" on the shebang.
RUN sed -i 's/\r$//' entrypoint.sh && chmod +x entrypoint.sh

EXPOSE 8080

CMD ["bash", "/app/entrypoint.sh"]
