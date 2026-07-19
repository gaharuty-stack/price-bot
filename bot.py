from flask import Flask, request, jsonify
import aiohttp
import asyncio
import json
from datetime import datetime

app = Flask(__name__)

async def fetch_data(query: str):
    """
    Возвращает реальные курсы криптовалют с Binance.
    Binance — стабильный, не блокирует запросы с Render.
    """
    # Маппинг запросов на торговые пары Binance
    pair_map = {
        "bitcoin": "BTCUSDT",
        "btc": "BTCUSDT",
        "ethereum": "ETHUSDT",
        "eth": "ETHUSDT",
        "solana": "SOLUSDT",
        "sol": "SOLUSDT",
        "dogecoin": "DOGEUSDT",
        "doge": "DOGEUSDT"
    }
    
    symbol = pair_map.get(query.lower(), "BTCUSDT")
    
    # Binance API (публичный, без ключей)
    url = f"https://api.binance.com/api/v3/ticker/24hr?symbol={symbol}"
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, timeout=15) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    
                    # Извлекаем данные
                    price = float(data.get("lastPrice", 0))
                    change = float(data.get("priceChangePercent", 0))
                    volume = float(data.get("quoteVolume", 0))
                    high = float(data.get("highPrice", 0))
                    low = float(data.get("lowPrice", 0))
                    
                    # Формируем результат
                    results = [{
                        "title": f"{query.upper()} (USDT)",
                        "price_usd": round(price, 2),
                        "price_change_24h_percent": round(change, 2),
                        "high_24h": round(high, 2),
                        "low_24h": round(low, 2),
                        "volume_24h_usd": round(volume, 2),
                        "in_stock": True,
                        "source": "binance.com",
                        "timestamp": datetime.now().isoformat()
                    }]
                    return results
                else:
                    # Если Binance не ответил — возвращаем fallback
                    return get_fallback_data(query)
                    
        except Exception as e:
            return get_fallback_data(query)

def get_fallback_data(query: str):
    """Возвращает тестовые данные, если API не доступен"""
    return [
        {
            "title": f"{query} (пример)",
            "price_usd": 999.99,
            "price_change_24h_percent": 2.5,
            "high_24h": 1010.00,
            "low_24h": 990.00,
            "volume_24h_usd": 50000000,
            "in_stock": True,
            "source": "demo",
            "timestamp": datetime.now().isoformat()
        }
    ]

@app.route('/', methods=['GET', 'HEAD'])
def root():
    return jsonify({"status": "ok", "message": "Crypto Price Bot is alive"})

@app.route('/api/data', methods=['GET'])
def get_data():
    query = request.args.get('q', '')
    if not query:
        return jsonify({"error": "Укажите запрос, например: ?q=bitcoin"}), 400
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    result = loop.run_until_complete(fetch_data(query))
    
    return jsonify({
        "status": "ok",
        "query": query,
        "count": len(result),
        "result": result
    })

@app.after_request
def add_x402_headers(response):
    response.headers['X-Payment-Required'] = 'true'
    response.headers['X-Payment-Amount'] = '0.002'
    response.headers['X-Payment-Asset'] = 'USDC'
    response.headers['X-Payment-Network'] = 'base'
    response.headers['X-Payment-PayTo'] = '0x3f10530c86e6a1d26edbf27b6b6e660c77d79915'
    response.headers['X-Payment-Description'] = 'Live cryptocurrency prices from Binance'
    return response

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
