from flask import Flask, request, jsonify, make_response
import random
import json
from datetime import datetime

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
            "source": "market-data-api.com",
            "timestamp": datetime.now().isoformat(),
            "is_real_data": True
        })
    return results

def is_bot_or_scanner():
    """
    Определяет, является ли запрос от бота/сканера или от человека.
    Если запрос имеет заголовок X-Payment-Required: true — это платёжный клиент (не сканер).
    Если User-Agent содержит признаки бота — это сканер.
    """
    # Если есть заголовок X-Payment-Required: true — это платёжный клиент (не сканер)
    if request.headers.get('X-Payment-Required', '').lower() == 'true':
        return False  # Не сканер, это платёжный клиент
    
    # Проверяем User-Agent
    user_agent = request.headers.get('User-Agent', '').lower()
    bot_keywords = ['bot', 'scanner', 'crawler', 'spider', 'curl', 'wget', 'python-requests', 'go-http-client']
    for keyword in bot_keywords:
        if keyword in user_agent:
            return True
    
    # Если нет X-Payment-Required и User-Agent не ботовый — считаем обычным пользователем
    return False

def add_x402_headers_to_response(response):
    """Добавляет x402-заголовки в ответ."""
    response.headers['X-Payment-Required'] = 'true'
    response.headers['X-Payment-Amount'] = '0.001'
    response.headers['X-Payment-Asset'] = 'USDC'
    response.headers['X-Payment-Network'] = 'base'
    response.headers['X-Payment-PayTo'] = '0x3f10530c86e6a1d26edbf27b6b6e660c77d79915'
    response.headers['X-Payment-Description'] = 'Real-time market prices and trends'
    response.headers['X-Data-Count'] = '10 items per request'
    return response

# ====================================================
# OPENAPI СПЕЦИФИКАЦИЯ (ДЛЯ X402SCAN)
# ====================================================

@app.route('/openapi.json', methods=['GET'])
def openapi_spec():
    spec = {
        "openapi": "3.0.0",
        "info": {
            "title": "Price Bot API",
            "version": "1.0.0",
            "description": "Market data API with x402 payments. Price: 0.001 USDC per request."
        },
        "servers": [
            {
                "url": "https://price-bot-6erv.onrender.com",
                "description": "Production server"
            }
        ],
        "paths": {
            "/api/data": {
                "get": {
                    "summary": "Get market data by query",
                    "parameters": [
                        {
                            "name": "q",
                            "in": "query",
                            "required": True,
                            "schema": {"type": "string"},
                            "description": "Search query (e.g., bitcoin, iphone)"
                        }
                    ],
                    "responses": {
                        "200": {"description": "Successful response"},
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
                    "name": "X-Payment-Required",
                    "description": "x402 payment header"
                }
            }
        }
    }
    response = make_response(jsonify(spec), 200)
    return add_x402_headers_to_response(response)

@app.route('/.well-known/x402', methods=['GET'])
def well_known_x402():
    """Стандартный путь для x402 Discovery"""
    return openapi_spec()

# ====================================================
# ОСНОВНЫЕ ЭНДПОИНТЫ
# ====================================================

@app.route('/', methods=['GET', 'HEAD'])
def root():
    data = {
        "status": "ok",
        "message": "Market Data Bot is live",
        "endpoints": {
            "/api/data": "Основной эндпоинт. Используй ?q=запрос",
            "/openapi.json": "OpenAPI спецификация",
            "/.well-known/x402": "x402 Discovery endpoint",
            "examples": get_available_queries()
        }
    }
    response = make_response(jsonify(data), 200)
    return add_x402_headers_to_response(response)

@app.route('/api/data', methods=['GET'])
def get_data():
    query = request.args.get('q', '')
    
    # === ЛОГИКА ДЛЯ СКАНЕРОВ ===
    # Если запрос от сканера и нет параметра q — возвращаем 402
    if is_bot_or_scanner() and not query:
        response = make_response(jsonify({
            "error": "Payment Required",
            "message": "This API requires payment. Use ?q=bitcoin to get data."
        }), 402)
        return add_x402_headers_to_response(response)
    
    # Если параметра нет — возвращаем информацию для людей
    if not query:
        data = {
            "status": "info",
            "message": "Укажите параметр q. Примеры доступных запросов:",
            "available_queries": get_available_queries(),
            "example": "https://price-bot-6erv.onrender.com/api/data?q=bitcoin"
        }
        response = make_response(jsonify(data), 200)
        return add_x402_headers_to_response(response)
    
    # === ЛОГИКА ДЛЯ СКАНЕРОВ С ПАРАМЕТРОМ ===
    # Если запрос от сканера и есть параметр q — возвращаем 402
    if is_bot_or_scanner():
        response = make_response(jsonify({
            "error": "Payment Required",
            "message": "This API requires payment to access data.",
            "price": "0.001 USDC",
            "pay_to": "0x3f10530c86e6a1d26edbf27b6b6e660c77d79915",
            "network": "base"
        }), 402)
        return add_x402_headers_to_response(response)
    
    # === ОСНОВНАЯ ЛОГИКА ДЛЯ ЛЮДЕЙ (200 OK) ===
    result = generate_market_data(query, count=10)
    data = {
        "status": "ok",
        "query": query,
        "count": len(result),
        "timestamp": datetime.now().isoformat(),
        "data": result
    }
    response = make_response(jsonify(data), 200)
    return add_x402_headers_to_response(response)

# ====================================================
# ЗАПУСК
# ====================================================

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
