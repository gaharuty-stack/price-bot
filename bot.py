from flask import Flask, request, jsonify
import aiohttp
import asyncio
import json
from bs4 import BeautifulSoup

app = Flask(__name__)

# ====================================================
# РЕАЛЬНАЯ ЛОГИКА СБОРА ДАННЫХ
# ====================================================

async def fetch_data(query: str):
    """
    Парсит данные по запросу.
    ЗДЕСЬ ТЫ МЕНЯЕШЬ ТОЛЬКО ТРИ ВЕЩИ:
    1. url — адрес сайта, который парсишь
    2. селекторы для названия, цены, наличия
    3. преобразование цены в число
    """
    # ЭТО ПРИМЕР — ЗАМЕНИ НА СВОЙ САЙТ
    url = f"https://jsonplaceholder.typicode.com/posts?q={query}"
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, timeout=15) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    results = []
                    for item in data[:20]:
                        results.append({
                            "title": item.get("title", "Неизвестно"),
                            "price": round((item.get("id", 1) * 10) + 5.99, 2),
                            "in_stock": item.get("id", 1) % 2 == 0,
                            "source": "example.com"
                        })
                    return results
                else:
                    return [{"error": f"Ошибка HTTP {resp.status}"}]
        except Exception as e:
            return [{"error": str(e)}]

# ====================================================
# API — ТОЧКА ВХОДА ДЛЯ ЗАПРОСОВ
# ====================================================

@app.route('/api/data', methods=['GET'])
def get_data():
    query = request.args.get('q', '')
    if not query:
        return jsonify({"error": "Укажи параметр q, например ?q=iphone"}), 400
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    result = loop.run_until_complete(fetch_data(query))
    
    return jsonify({
        "status": "ok",
        "query": query,
        "count": len(result),
        "result": result
    })

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "alive"})

# ====================================================
# ЗАПУСК
# ====================================================

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)