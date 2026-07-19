from flask import Flask, request, jsonify, make_response
import random
import json
from datetime import datetime
import logging
import aiohttp
import asyncio
from cachetools import TTLCache
import sqlite3
import os

# ====================================================
# НАСТРОЙКА ЛОГИРОВАНИЯ
# ====================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# ====================================================
# НАСТРОЙКА КЕША (5 минут)
# ====================================================

cache = TTLCache(maxsize=100, ttl=300)

# ====================================================
# НАСТРОЙКА БАЗЫ ДАННЫХ
# ====================================================

def init_db():
    try:
        conn = sqlite3.connect('bot_stats.db')
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS requests
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      query TEXT,
                      timestamp TEXT,
                      ip TEXT,
                      status INTEGER)''')
        conn.commit()
        conn.close()
        logger.info("База данных инициализирована")
    except Exception as e:
        logger.error(f"Ошибка инициализации БД: {e}")

init_db()

def log_request(query: str, ip: str, status: int):
    try:
        conn = sqlite3.connect('bot_stats.db')
        c = conn.cursor()
        c.execute("INSERT INTO requests (query, timestamp, ip, status) VALUES (?, ?, ?, ?)",
                  (query, datetime.now().isoformat(), ip, status))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Ошибка записи в БД: {e}")

# ====================================================
# APP
# ====================================================

app = Flask(__name__)

# ====================================================
# ФУНКЦИИ
# ====================================================

def get_available_queries():
    return {
        "crypto": ["bitcoin", "ethereum", "solana", "dogecoin"],
        "goods": ["iphone", "macbook", "ps5", "телефон"],
        "parts": ["автозапчасть"]
    }

def generate_market_data(query: str, count: int = 10):
    """Генерирует реалистичные данные (фолбэк, если API не работает)"""
    base_prices = {
        "bitcoin": 65000, "btc": 65000,
        "ethereum": 3500, "eth": 3500,
        "solana": 150, "sol": 150,
        "dogecoin": 0.15, "doge": 0.15,
        "iphone": 800, "macbook": 1500,
        "ps5": 500, "автозапчасть": 2000,
        "телефон": 300
    }
    base_price = base_prices.get(query.lower(), random.uniform(10, 1000))
    results = []
    for i in range(count):
        price_noise = random.uniform(-0.15, 0.15)
        current_price = round(base_price * (1 + price_noise), 2)
        change_24h = round(random.uniform(-7.0, 7.0), 2)
        high = round(current_price * (1 + random.uniform(0.01, 0.07)), 2)
        low = round(current_price * (1 - random.uniform(0.01, 0.07)), 2)
        volume = round(random.uniform(500000, 5000000000), 2)
        market_status = random.choice(["Bullish", "Bearish", "Neutral", "Volatile"])
        trend = "Up" if change_24h > 0 else "Down" if change_24h < 0 else "Stable"
        results.append({
            "id": i + 1,
            "name": f"{query.title()} #{i+1}",
            "price_usd": current_price,
            "price_btc": round(current_price / 65000, 8) if "bitcoin" in query.lower() else None,
            "change_24h_percent": change_24h,
            "high_24h": high,
            "low_24h": low,
            "volume_24h": volume,
            "market_status": market_status,
            "trend": trend,
            "in_stock": random.random() > 0.2,
            "source": "generated",
            "timestamp": datetime.now().isoformat(),
            "is_real_data": False
        })
    return results

async def fetch_real_prices(query: str):
    """
    Получает реальные цены с CoinGecko API.
    Если API недоступен — возвращает сгенерированные данные.
    """
    coin_map = {
        "bitcoin": "bitcoin", "btc": "bitcoin",
        "ethereum": "ethereum", "eth": "ethereum",
        "solana": "solana", "sol": "solana",
        "dogecoin": "dogecoin", "doge": "dogecoin",
        "cardano": "cardano", "ada": "cardano",
        "ripple": "ripple", "xrp": "ripple"
    }
    coin_id = coin_map.get(query.lower(), "bitcoin")
    url = f"https://api.coingecko.com/api/v3/coins/{coin_id}"
    
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json"
    }
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, headers=headers, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    price = data.get('market_data', {}).get('current_price', {}).get('usd', 0)
                    change = data.get('market_data', {}).get('price_change_percentage_24h', 0)
                    high = data.get('market_data', {}).get('high_24h', {}).get('usd', price * 1.05)
                    low = data.get('market_data', {}).get('low_24h', {}).get('usd', price * 0.95)
                    volume = data.get('market_data', {}).get('total_volume', {}).get('usd', 0)
                    market_cap = data.get('market_data', {}).get('market_cap', {}).get('usd', 0)
                    name = data.get('name', query.title())
                    symbol = data.get('symbol', '').upper()
                    
                    return [{
                        "id": 1,
                        "name": f"{name} ({symbol})",
                        "price_usd": round(price, 2),
                        "price_btc": round(price / 65000, 8),
                        "change_24h_percent": round(change, 2),
                        "high_24h": round(high, 2),
                        "low_24h": round(low, 2),
                        "volume_24h": round(volume, 2),
                        "market_cap_usd": round(market_cap, 2),
                        "market_status": "Bullish" if change > 0 else "Bearish" if change < 0 else "Neutral",
                        "trend": "Up" if change > 0 else "Down" if change < 0 else "Stable",
                        "in_stock": True,
                        "source": "coingecko.com",
                        "timestamp": datetime.now().isoformat(),
                        "is_real_data": True
                    }]
                else:
                    logger.warning(f"CoinGecko вернул {resp.status}, используем генерацию")
                    return generate_market_data(query, count=5)
        except Exception as e:
            logger.error(f"Ошибка CoinGecko: {e}, используем генерацию")
            return generate_market_data(query, count=5)

def is_bot_or_scanner():
    if request.headers.get('X-Payment-Required', '').lower() == 'true':
        return False
    user_agent = request.headers.get('User-Agent', '').lower()
    bot_keywords = ['bot', 'scanner', 'crawler', 'spider', 'curl', 'wget', 'python-requests', 'go-http-client']
    for keyword in bot_keywords:
        if keyword in user_agent:
            return True
    return False

def add_x402_headers_to_response(response):
    response.headers['X-Payment-Required'] = 'true'
    response.headers['X-Payment-Amount'] = '0.001'
    response.headers['X-Payment-Asset'] = 'USDC'
    response.headers['X-Payment-Network'] = 'base'
    response.headers['X-Payment-PayTo'] = '0x3f10530c86e6a1d26edbf27b6b6e660c77d79915'
    response.headers['X-Payment-Description'] = 'Real-time market prices from CoinGecko'
    response.headers['X-Data-Count'] = '1 item per request'
    return response

# ====================================================
# OPENAPI СПЕЦИФИКАЦИЯ
# ====================================================

@app.route('/openapi.json', methods=['GET'])
def openapi_spec():
    spec = {
        "openapi": "3.0.0",
        "info": {
            "title": "Price Bot API",
            "version": "1.0.0",
            "description": "Real-time cryptocurrency prices via CoinGecko. Price: 0.001 USDC per request."
        },
        "servers": [{"url": "https://price-bot-6erv.onrender.com"}],
        "paths": {
            "/api/data": {
                "get": {
                    "summary": "Get real-time price data",
                    "parameters": [
                        {
                            "name": "q",
                            "in": "query",
                            "required": True,
                            "schema": {"type": "string"},
                            "description": "e.g., bitcoin, ethereum, solana"
                        }
                    ],
                    "responses": {
                        "200": {"description": "Price data"},
                        "402": {"description": "Payment Required"}
                    },
                    "security": [{"x402": []}]
                }
            }
        },
        "components": {
            "securitySchemes": {
                "x402": {
                    "type": "apiKey",
                    "in": "header",
                    "name": "X-Payment-Required"
                }
            }
        }
    }
    response = make_response(jsonify(spec), 200)
    return add_x402_headers_to_response(response)

@app.route('/.well-known/x402', methods=['GET'])
def well_known_x402():
    return openapi_spec()

# ====================================================
# ОСНОВНЫЕ ЭНДПОИНТЫ
# ====================================================

@app.route('/', methods=['GET', 'HEAD'])
def root():
    data = {
        "status": "ok",
        "message": "Price Bot with real CoinGecko data",
        "endpoints": {
            "/api/data": "Use ?q=bitcoin to get real prices",
            "/openapi.json": "OpenAPI spec",
            "/.well-known/x402": "x402 discovery"
        }
    }
    response = make_response(jsonify(data), 200)
    return add_x402_headers_to_response(response)

@app.route('/api/data', methods=['GET'])
def get_data():
    query = request.args.get('q', '')
    client_ip = request.remote_addr
    
    # Проверка на сканеров
    if is_bot_or_scanner():
        log_request(query, client_ip, 402)
        response = make_response(jsonify({
            "error": "Payment Required",
            "message": "Pay 0.001 USDC to access real CoinGecko prices",
            "price": "0.001 USDC",
            "pay_to": "0x3f10530c86e6a1d26edbf27b6b6e660c77d79915",
            "network": "base"
        }), 402)
        return add_x402_headers_to_response(response)
    
    if not query:
        data = {
            "status": "info",
            "message": "Укажите параметр q. Примеры: bitcoin, ethereum, solana, dogecoin"
        }
        response = make_response(jsonify(data), 200)
        log_request(query, client_ip, 200)
        return add_x402_headers_to_response(response)
    
    # Проверка кеша
    cache_key = query.lower()
    if cache_key in cache:
        logger.info(f"Кеш-хит для {query}")
        response = make_response(jsonify(cache[cache_key]), 200)
        log_request(query, client_ip, 200)
        return add_x402_headers_to_response(response)
    
    # Получение реальных данных
    logger.info(f"Запрос к CoinGecko для {query} от {client_ip}")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    result = loop.run_until_complete(fetch_real_prices(query))
    loop.close()
    
    data = {
        "status": "ok",
        "query": query,
        "count": len(result),
        "timestamp": datetime.now().isoformat(),
        "data": result
    }
    
    # Сохраняем в кеш
    cache[cache_key] = data
    log_request(query, client_ip, 200)
    
    response = make_response(jsonify(data), 200)
    return add_x402_headers_to_response(response)

# ====================================================
# ЗАПУСК
# ====================================================

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
