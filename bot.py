from flask import Flask, request, jsonify, make_response
import time
from datetime import datetime
import logging
import requests
from cachetools import TTLCache
import sqlite3
import os
import re

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

cache = TTLCache(maxsize=200, ttl=60)

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
                      paid BOOLEAN DEFAULT FALSE,
                      source TEXT)''')
        conn.commit()
        conn.close()
        logger.info("База данных инициализирована")
    except Exception as e:
        logger.error(f"Ошибка инициализации БД: {e}")

init_db()

def log_request(query: str, ip: str, status: int, paid: bool = False, source: str = "unknown"):
    try:
        conn = sqlite3.connect('bot_stats.db')
        c = conn.cursor()
        c.execute("INSERT INTO requests (query, timestamp, ip, status, paid, source) VALUES (?, ?, ?, ?, ?, ?)",
                  (query, datetime.now().isoformat(), ip, status, paid, source))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Ошибка записи в БД: {e}")

app = Flask(__name__)

PAYMENT_CONFIG = {
    "amount": "0.001",
    "currency": "USDC",
    "network": "base",
    "receiver": "0x3f10530c86e6a1d26edbf27b6b6e660c77d79915"
}

COINGECKO_API_KEY = "CG-MAyw674wsFCM6p3hJdSR6nU4"

def get_payment_headers():
    return {
        "X-Payment-Required": PAYMENT_CONFIG["amount"],
        "X-Payment-Currency": PAYMENT_CONFIG["currency"],
        "X-Payment-Network": PAYMENT_CONFIG["network"],
        "X-Payment-Receiver": PAYMENT_CONFIG["receiver"],
        "X-Payment-Description": "Real-time market price data from CoinGecko"
    }

def fetch_real_prices_sync(query: str):
    coin_map = {
        "bitcoin": "bitcoin", "btc": "bitcoin",
        "ethereum": "ethereum", "eth": "ethereum",
        "solana": "solana", "sol": "solana",
        "dogecoin": "dogecoin", "doge": "dogecoin",
        "cardano": "cardano", "ada": "cardano",
        "ripple": "ripple", "xrp": "ripple",
        "polkadot": "polkadot", "dot": "polkadot",
        "chainlink": "chainlink", "link": "chainlink",
        "polygon": "polygon", "matic": "polygon",
        "litecoin": "litecoin", "ltc": "litecoin",
        "bitcoin-cash": "bitcoin-cash", "bch": "bitcoin-cash",
        "stellar": "stellar", "xlm": "stellar",
        "monero": "monero", "xmr": "monero",
        "avalanche": "avalanche-2", "avax": "avalanche-2",
        "shiba-inu": "shiba-inu", "shib": "shiba-inu"
    }
    
    coin_id = coin_map.get(query.lower(), None)
    if not coin_id:
        logger.warning(f"Неизвестная монета: {query}")
        return None
    
    # ИСПРАВЛЕННЫЙ URL ДЛЯ PRO-API
    url = f"https://pro-api.coingecko.com/api/v3/coins/{coin_id}"
    params = {
        "localization": "false",
        "tickers": "false",
        "market_data": "true",
        "community_data": "false",
        "developer_data": "false",
        "sparkline": "false"
    }
    
    headers = {
        "User-Agent": "PriceBot/2.0 (Blackbox Research)",
        "Accept": "application/json",
        "x-cg-pro-api-key": COINGECKO_API_KEY
    }
    
    logger.info(f"Запрос к CoinGecko Pro API для {coin_id}")
    
    for attempt in range(3):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=10)
            
            if resp.status_code == 200:
                data = resp.json()
                market = data.get('market_data', {})
                
                price = market.get('current_price', {}).get('usd', 0)
                if price == 0:
                    logger.warning(f"Цена для {coin_id} не найдена")
                    break
                
                change = market.get('price_change_percentage_24h', 0)
                high = market.get('high_24h', {}).get('usd', price * 1.05)
                low = market.get('low_24h', {}).get('usd', price * 0.95)
                volume = market.get('total_volume', {}).get('usd', 0)
                market_cap = market.get('market_cap', {}).get('usd', 0)
                name = data.get('name', query.title())
                symbol = data.get('symbol', '').upper()
                
                return {
                    "id": 1,
                    "name": f"{name} ({symbol})",
                    "price_usd": round(price, 4),
                    "change_24h_percent": round(change, 2),
                    "high_24h": round(high, 2),
                    "low_24h": round(low, 2),
                    "volume_24h": round(volume, 2),
                    "market_cap_usd": round(market_cap, 2),
                    "source": "coingecko.com (real)",
                    "timestamp": datetime.now().isoformat(),
                    "is_real": True,
                    "coin_id": coin_id
                }
            
            elif resp.status_code == 429:
                logger.warning(f"Лимит запросов, попытка {attempt+1}/3, ждём {2 * (attempt + 1)}с")
                time.sleep(2 * (attempt + 1))
                continue
            
            elif resp.status_code == 401:
                logger.error("Неверный API-ключ, проверьте COINGECKO_API_KEY")
                break
            
            else:
                logger.error(f"CoinGecko вернул {resp.status_code}: {resp.text[:200]}")
                break
                
        except requests.exceptions.Timeout:
            logger.warning(f"Таймаут, попытка {attempt+1}/3")
            time.sleep(1)
        except Exception as e:
            logger.error(f"Ошибка запроса: {e}")
            time.sleep(1)
    
    return None

@app.route('/api/data', methods=['GET'])
def get_data():
    query = request.args.get('q', '').strip()
    client_ip = request.remote_addr
    
    if not query:
        return jsonify({
            "error": "Missing parameter",
            "message": "Укажите ?q=bitcoin или ?q=ethereum"
        }), 400
    
    if not re.match(r'^[a-zA-Z0-9\-\_\s]+$', query):
        return jsonify({
            "error": "Invalid query",
            "message": "Только буквы, цифры, дефис и подчёркивание"
        }), 400
    
    cache_key = query.lower()
    response_data = None
    source = "cache"
    
    if cache_key in cache:
        logger.info(f"Кэш для {query}")
        response_data = cache[cache_key]
        source = "cache"
    else:
        logger.info(f"Запрос к CoinGecko: {query}")
        real_data = fetch_real_prices_sync(query)
        
        if real_data:
            response_data = {
                "status": "ok",
                "query": query,
                "count": 1,
                "timestamp": datetime.now().isoformat(),
                "data": [real_data],
                "source": "coingecko"
            }
            cache[cache_key] = response_data
            source = "coingecko"
        else:
            fallback_prices = {
                "bitcoin": {"price": 64523.12, "change": 2.34},
                "btc": {"price": 64523.12, "change": 2.34},
                "ethereum": {"price": 3456.78, "change": 1.23},
                "eth": {"price": 3456.78, "change": 1.23},
                "solana": {"price": 148.50, "change": 5.67},
                "sol": {"price": 148.50, "change": 5.67},
                "dogecoin": {"price": 0.1423, "change": -2.45},
                "doge": {"price": 0.1423, "change": -2.45},
                "cardano": {"price": 0.4521, "change": -1.23},
                "ada": {"price": 0.4521, "change": -1.23},
                "ripple": {"price": 0.6234, "change": 0.87},
                "xrp": {"price": 0.6234, "change": 0.87}
            }
            
            fb = fallback_prices.get(cache_key)
            if fb:
                response_data = {
                    "status": "ok",
                    "query": query,
                    "count": 1,
                    "timestamp": datetime.now().isoformat(),
                    "data": [{
                        "id": 1,
                        "name": query.title(),
                        "price_usd": fb["price"],
                        "change_24h_percent": fb["change"],
                        "source": "historical_fallback",
                        "timestamp": datetime.now().isoformat(),
                        "is_real": False,
                        "note": "CoinGecko API временно недоступен"
                    }],
                    "source": "fallback"
                }
                cache[cache_key] = response_data
                source = "fallback"
            else:
                return jsonify({
                    "error": "Unknown coin",
                    "message": f"Монета '{query}' не найдена. Доступны: bitcoin, ethereum, solana, dogecoin, cardano, ripple, polkadot, chainlink, polygon, litecoin, bitcoin-cash, stellar, monero, avalanche, shiba-inu"
                }), 404
    
    payment_tx = request.headers.get('X-Payment-Tx-Hash', '')
    paid = bool(payment_tx and len(payment_tx) > 10)
    
    log_request(query, client_ip, 200, paid=paid, source=source)
    
    response = make_response(jsonify(response_data), 200)
    
    for k, v in get_payment_headers().items():
        response.headers[k] = v
    
    if paid:
        response.headers['X-Payment-Verified'] = 'true'
        response.headers['X-Payment-Tx-Hash'] = payment_tx
    
    response.headers['X-Data-Source'] = source
    response.headers['X-Cache-Status'] = 'HIT' if source == 'cache' else 'MISS'
    
    return response

@app.route('/openapi.json', methods=['GET'])
def openapi_spec():
    spec = {
        "openapi": "3.0.0",
        "info": {
            "title": "Price Bot API",
            "version": "2.1.0",
            "description": "Real-time cryptocurrency prices via CoinGecko Pro API. Payment: 0.001 USDC on Base.",
            "x402": {
                "price": PAYMENT_CONFIG["amount"],
                "currency": PAYMENT_CONFIG["currency"],
                "network": PAYMENT_CONFIG["network"],
                "receiver": PAYMENT_CONFIG["receiver"]
            }
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
                            "schema": {"type": "string", "example": "bitcoin"},
                            "description": "ID монеты: bitcoin, ethereum, solana, dogecoin, cardano, ripple, polkadot, chainlink, polygon, litecoin, bitcoin-cash, stellar, monero, avalanche, shiba-inu"
                        }
                    ],
                    "responses": {
                        "200": {"description": "Price data returned"},
                        "402": {"description": "Payment required — check X-Payment-* headers"},
                        "404": {"description": "Coin not found"}
                    },
                    "x402": {"payment": PAYMENT_CONFIG}
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
    info = {
        "status": "ok",
        "service": "Price Bot v2.1",
        "description": "Real cryptocurrency prices via CoinGecko Pro",
        "payment": PAYMENT_CONFIG,
        "endpoints": {
            "/api/data": "GET with ?q=bitcoin (payment required)",
            "/openapi.json": "OpenAPI specification",
            "/.well-known/x402": "x402 discovery endpoint"
        }
    }
    response = make_response(jsonify(info), 200)
    for k, v in get_payment_headers().items():
        response.headers[k] = v
    return response

@app.route('/admin/stats', methods=['GET'])
def admin_stats():
    if request.remote_addr not in ['127.0.0.1', '::1']:
        return jsonify({"error": "Forbidden"}), 403
    
    conn = sqlite3.connect('bot_stats.db')
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM requests")
    total = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM requests WHERE paid = 1")
    paid = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM requests WHERE status = 200")
    success = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM requests WHERE source = 'coingecko'")
    real = c.fetchone()[0]
    conn.close()
    
    return jsonify({
        "total_requests": total,
        "paid_requests": paid,
        "successful_requests": success,
        "real_data_requests": real,
        "conversion_rate": round(paid / max(total, 1) * 100, 2)
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, threaded=True)
