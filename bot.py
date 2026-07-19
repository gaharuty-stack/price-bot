from flask import Flask, request, jsonify
import aiohttp
import asyncio
import json
import re

app = Flask(__name__)

# ====================================================
# ПАРСИНГ ЧЕРЕЗ ОТКРЫТОЕ API (ALPHA VANTAGE — ДЕМО)
# ====================================================

async def fetch_data(query: str):
    """
    Парсит данные через открытое API.
    Здесь используется бесплатный API для демонстрации.
    ЗАМЕНИ на свой источник данных.
    """
    
    # ВАРИАНТ 1: Используем открытое API для поиска (пример)
    # Это бесплатный API, который возвращает данные по запросу
    url = f"https://api.duckduckgo.com/?q={query}&format=json"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, headers=headers, timeout=15) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    
                    # Извлекаем результаты поиска
                    results = []
                    # Берем связанные темы (RelatedTopics) — там есть ссылки и описания
                    topics = data.get("RelatedTopics", [])
                    for idx, topic in enumerate(topics[:15]):
                        text = topic.get("Text", "")
                        # Извлекаем название (первая часть до символа)
                        title = text.split(" - ")[0] if " - " in text else text[:50]
                        # Извлекаем ссылку
                        link = topic.get("FirstURL", "")
                        # Имитируем цену (для демонстрации)
                        price = round((idx + 1) * 50 + 99.99, 2)
                        
                        results.append({
                            "title": title.strip() if title else f"Результат {idx+1}",
                            "price": price,
                            "in_stock": idx % 2 == 0,
                            "source": "duckduckgo.com",
                            "url": link
                        })
                    
                    # Если результатов нет — возвращаем тестовые данные
                    if not results:
                        return get_fallback_data(query)
                    
                    return results
                else:
                    # Если API не ответил — возвращаем тестовые данные
                    return get_fallback_data(query)
                    
        except Exception as e:
            # Если ошибка — возвращаем тестовые данные
            return get_fallback_data(query)

# ====================================================
# ТЕСТОВЫЕ ДАННЫЕ (ЕСЛИ API НЕ РАБОТАЕТ)
# ====================================================

def get_fallback_data(query: str):
    """Возвращает тестовые данные, если реальный парсинг не работает"""
    return [
        {
            "title": f"{query} — товар {i+1}",
            "price": round(99.99 + i * 15.50, 2),
            "in_stock": i % 2 == 0,
            "source": "fallback",
            "url": f"https://example.com/{query}/{i}"
        }
        for i in range(10)
    ]

# ====================================================
# API — ТОЧКА ВХОДА
# ====================================================

@app.route('/', methods=['GET', 'HEAD'])
def root():
    return jsonify({"status": "ok", "message": "Bot is alive"})

@app.route('/api/data', methods=['GET'])
def get_data():
    query = request.args.get('q', '')
    if not query:
        return jsonify({"error": "Укажи q"}), 400
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # Получаем данные
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
    response.headers['X-Payment-Description'] = 'Product search and price data'
    return response

# ====================================================
# ЗАПУСК
# ====================================================

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
