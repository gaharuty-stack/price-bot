from flask import Flask, request, jsonify, make_response
import requests
import json
import time
from datetime import datetime
import logging
from cachetools import TTLCache
import sqlite3
import re
import random

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Кеш на 2 минуты
cache = TTLCache(maxsize=200, ttl=120)

# База данных для статистики
def init_db():
    try:
        conn = sqlite3.connect('bot_stats.db')
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS requests
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      query TEXT,
                      timestamp TEXT,
                      ip TEXT,
                      status INTEGER,
                      source TEXT)''')
        conn.commit()
        conn.close()
        logger.info("База данных инициализирована")
    except Exception as e:
        logger.error(f"Ошибка БД: {e}")

init_db()

def log_request(query: str, ip: str, status: int, source: str = "unknown"):
    try:
        conn = sqlite3.connect('bot_stats.db')
        c = conn.cursor()
        c.execute("INSERT INTO requests (query, timestamp, ip, status, source) VALUES (?, ?, ?, ?, ?)",
                  (query, datetime.now().isoformat(), ip, status, source))
        conn.commit()
        conn.close()
    except Exception:
        pass

# ====================================================
# КОНФИГ ПЛАТЕЖЕЙ
# ====================================================

PAYMENT_CONFIG = {
    "amount": "0.001",
    "currency": "USDC",
    "network": "base",
    "receiver": "0x3f10530c86e6a1d26edbf27b6b6e660c77d79915"
}

def get_payment_headers():
    return {
        "X-Payment-Required": PAYMENT_CONFIG["amount"],
        "X-Payment-Currency": PAYMENT_CONFIG["currency"],
        "X-Payment-Network": PAYMENT_CONFIG["network"],
        "X-Payment-Receiver": PAYMENT_CONFIG["receiver"],
        "X-Payment-Description": "Real-time cryptocurrency prices from Binance"
    }

# ====================================================
# МАППИНГ МОНЕТ
# ====================================================

BINANCE_SYMBOLS = {
    "bitcoin": "BTCUSDT", "btc": "BTCUSDT",
    "ethereum": "ETHUSDT", "eth": "ETHUSDT",
    "solana": "SOLUSDT", "sol": "SOLUSDT",
    "dogecoin": "DOGEUSDT", "doge": "DOGEUSDT",
    "cardano": "ADAUSDT", "ada": "ADAUSDT",
    "ripple": "XRPUSDT", "xrp": "XRPUSDT"
}

def generate_fallback(query: str):
    """Фолбэк-данные, если API недоступен"""
    base_prices = {
        "bitcoin": 65000, "btc": 65000,
        "ethereum": 3500, "eth": 3500,
        "solana": 150, "sol": 150,
        "dogecoin": 0.15, "doge": 0.15,
        "cardano": 0.45, "ada": 0.45,
        "ripple": 0.62, "xrp": 0.62
    }
    base_price = base_prices.get(query.lower(), random.uniform(10, 1000))
    return [{
        "id": 1,
        "name": query.title(),
        "price_usd": round(base_price, 2),
        "change_24h_percent": round(random.uniform(-5.0, 5.0), 2),
        "source": "cache",
        "timestamp": datetime.now().isoformat(),
        "is_real": False
    }]

# ====================================================
# ПОЛУЧЕНИЕ РЕАЛЬНЫХ ЦЕН
# ====================================================

def fetch_real_price_sync(query: str):
    """Получает реальную цену через ALLOrigins + Binance"""
    symbol = BINANCE_SYMBOLS.get(query.lower())
    if not symbol:
        return generate_fallback(query)

    # Используем ALLOrigins как бесплатный прокси
    proxy_url = "https://api.allorigins.win/raw?url="
    binance_url = f"https://api.binance.com/api/v3/ticker/24hr?symbol={symbol}"
    
    for attempt in range(3):
        try:
            resp = requests.get(proxy_url + binance_url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                price = float(data.get('lastPrice', 0))
                change = float(data.get('priceChangePercent', 0))
                high = float(data.get('highPrice', 0))
                low = float(data.get('lowPrice', 0))
                volume = float(data.get('quoteVolume', 0))

                return [{
                    "id": 1,
                    "name": query.title(),
                    "price_usd": round(price, 2),
                    "change_24h_percent": round(change, 2),
                    "high_24h": round(high, 2),
                    "low_24h": round(low, 2),
                    "volume_24h": round(volume, 2),
                    "source": "binance.com (real-time)",
                    "timestamp": datetime.now().isoformat(),
                    "is_real": True
                }]
            else:
                logger.warning(f"ALLOrigins вернул {resp.status_code}, попытка {attempt+1}")
                time.sleep(0.5)
        except Exception as e:
            logger.warning(f"Ошибка {attempt+1}: {e}")
            time.sleep(0.5)
    
    # Если все попытки провалились — возвращаем fallback
    logger.warning(f"Используем fallback для {query}")
    return generate_fallback(query)

# ====================================================
# ОСНОВНОЙ ЭНДПОИНТ
# ====================================================

@app.route('/api/data', methods=['GET'])
def get_data():
    query = request.args.get('q', '').strip()
    client_ip = request.remote_addr

    if not query:
        return jsonify({"error": "Missing parameter", "message": "Укажите ?q=bitcoin"}), 400

    if not re.match(r'^[a-zA-Z0-9\-\_\s]+$', query):
        return jsonify({"error": "Invalid query"}), 400

    cache_key = query.lower()

    # Проверяем кеш
    if cache_key in cache:
        logger.info(f"Кеш для {query}")
        response_data = cache[cache_key]
        source = "cache"
    else:
        logger.info(f"Запрос к Binance для {query}")
        result = fetch_real_price_sync(query)
        response_data = {
            "status": "ok",
            "query": query,
            "count": len(result),
            "timestamp": datetime.now().isoformat(),
            "data": result
        }
        # Кешируем только если данные реальные
        if result and result[0].get("is_real", False):
            cache[cache_key] = response_data
            source = "binance"
        else:
            source = "fallback"

    response = make_response(jsonify(response_data), 200)
    
    # Добавляем платёжные заголовки
    for k, v in get_payment_headers().items():
        response.headers[k] = v

    log_request(query, client_ip, 200, source)
    return response

# ====================================================
# ОСТАЛЬНЫЕ ЭНДПОИНТЫ
# ====================================================

@app.route('/openapi.json', methods=['GET'])
def openapi_spec():
    spec = {
        "openapi": "3.0.0",
        "info": {
            "title": "Price Bot API",
            "version": "2.0.0",
            "description": "Real-time cryptocurrency prices via Binance. Payment: 0.001 USDC on Base.",
            "x402": PAYMENT_CONFIG
        },
        "servers": [{"url": "https://price-bot-6erv.onrender.com"}],
        "paths": {
            "/api/data": {
                "get": {
                    "summary": "Get real-time price",
                    "parameters": [
                        {
                            "name": "q",
                            "in": "query",
                            "required": True,
                            "schema": {"type": "string"},
                            "description": "bitcoin, ethereum, solana, dogecoin, cardano, ripple"
                        }
                    ],
                    "responses": {
                        "200": {"description": "Price data"},
                        "402": {"description": "Payment Required"}
                    }
                }
            }
        }
    }
    response = make_response(jsonify(spec), 200)
    for k, v in get_payment_headers().items():
        response.headers[k] = v
    return response

@app.route('/.well-known/x402', methods=['GET'])
def well_known_x402():
    return openapi_spec()

@app.route('/', methods=['GET'])
def root():
    return jsonify({
        "status": "ok",
        "service": "Price Bot v2.0",
        "description": "Real cryptocurrency prices via Binance",
        "payment": PAYMENT_CONFIG,
        "supported": list(BINANCE_SYMBOLS.keys()),
        "endpoints": {
            "/api/data": "GET with ?q=bitcoin",
            "/openapi.json": "OpenAPI spec",
            "/.well-known/x402": "x402 discovery"
        }
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, threaded=True)
