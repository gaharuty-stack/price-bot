FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY *.py ./
COPY ai.txt robots.txt ./

CMD sh -c "gunicorn --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 120 bot:app"
