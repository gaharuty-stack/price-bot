 from flask import Flask, request, jsonify
import aiohttp
import asyncio
import json
from datetime import datetime

app = Flask(__name__)

# ====================================================
# РЕАЛЬНЫЕ ДАННЫЕ: КУРСЫ КРИПТОВАЛЮТ (CoinGecko API)
# ====================================================

async def fetch_data(query: str):
    """
    Возвращает реальные курсы криптовалют по запросу.
    CoinGecko — бесплатный, стабильный, не блокирует.
    """
    # Маппинг популярных запросов на ID монет
    coin_map = {
        "bitcoin": "bitcoin",
        "btc": "bitcoin",
        "ethereum": "ethereum",
        "eth": "ethereum",
        "solana": "solana",
        "sol": "solana",
        "ton": "the-open-network",
        "toncoin": "the-open-network",
        "dogecoin": "dogecoin",
        "doge": "dogecoin",
        "ripple": "ripple",
        "xrp": "ripple",
        "cardano": "cardano",
        "ada": "cardano"
    }
    
    # Определяем ID монеты
    coin_id = coin_map.get(query.lower(), "bitcoin")
    
    # API CoinGecko (бесплатный, 10-50 запросов в минуту)
    url = f"https://api.coingecko.com/api/v3/coins/{coin_id}"
    
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json"
    }
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, headers=headers, timeout=15) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    
                    # Извлекаем нужные данные
                    name = data.get("name", "Неизвестно")
                    symbol = data.get("symbol", "").upper()
                    price_usd = data.get("market_data", {}).get("current_price", {}).get("usd", 0.0)
                    price_btc = data.get("market_data", {}).get("current_price", {}).get("btc", 0.0)
                    market_cap = data.get("market_data", {}).get("market_cap", {}).get("usd", 0)
                    volume_24h = data.get("market_data", {}).get("total_volume", {}).get("usd", 0)
                    price_change_24h = data.get("market_data", {}).get("price_change_percentage_24h", 0.0)
                    
                    # Формируем результат
                    results = [{
                        "title": f"{name} ({symbol})",
                        "price_usd": round(price_usd, 2),
                        "price_btc": round(price_btc, 8),
                        "market_cap_usd": market_cap,
                        "volume_24h_usd": volume_24h,
                        "price_change_24h_percent": round(price_change_24h, 2),
                        "in_stock": True,
                        "source": "coingecko.com",
                        "timestamp": datetime.now().isoformat()
                    }]
                    return results
                else:
                    return get_fallback_data(query, f"API error: {resp.status}")
                    
        except Exception as e:
            return get_fallback_data(query, str(e))

# ====================================================
# FALLBACK (ЕСЛИ API НЕ ДОСТУПНО)
# ====================================================

def get_fallback_data(query: str, error: str = ""):
    """Возвращает тестовые данные, если реальный API не работает"""
    return [
        {
            "title": f"{query} (пример)",
            "price_usd": 999.99,
            "price_btc": 0.015,
            "market_cap_usd": 1000000000,
            "volume_24h_usd": 50000000,
            "price_change_24h_percent": 2.5,
            "in_stock": True,
            "source": "demo",
            "timestamp": datetime.now().isoformat()
        }
    ]

# ====================================================
# API — ТОЧКА ВХОДА
# ====================================================

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

# ====================================================
# X402 ЗАГОЛОВКИ ДЛЯ ПЛАТЕЖЕЙ
# ====================================================

@app.after_request
def add_x402_headers(response):
    response.headers['X-Payment-Required'] = 'true'
    response.headers['X-Payment-Amount'] = '0.002'
    response.headers['X-Payment-Asset'] = 'USDC'
    response.headers['X-Payment-Network'] = 'base'
    response.headers['X-Payment-PayTo'] = '0x3f10530c86e6a1d26edbf27b6b6e660c77d79915'
    response.headers['X-Payment-Description'] = 'Live cryptocurrency prices from CoinGecko'
    return response

# ====================================================
# ЗАПУСК
# ====================================================

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
