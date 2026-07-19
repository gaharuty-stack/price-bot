from flask import Flask, request, jsonify
import aiohttp
import asyncio
import json
from bs4 import BeautifulSoup

app = Flask(__name__)

async def fetch_data(query: str):
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
                    return [{"error": f"HTTP {resp.status}"}]
        except Exception as e:
            return [{"error": str(e)}]

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
    result = loop.run_until_complete(fetch_data(query))
    return jsonify({"status": "ok", "query": query, "count": len(result), "result": result})

# ============================================================
# ДОБАВЛЯЕМ ЗАГОЛОВКИ ДЛЯ X402 (ЧТОБЫ БОТЫ МОГЛИ ПЛАТИТЬ)
# ============================================================
@app.after_request
def add_x402_headers(response):
    response.headers['X-Payment-Required'] = 'true'
    response.headers['X-Payment-Amount'] = '0.002'
    response.headers['X-Payment-Asset'] = 'USDC'
    response.headers['X-Payment-Network'] = 'base'
    # ЗАМЕНИ АДРЕС НА СВОЙ (скопируй из tollbooth.config.json)
    response.headers['X-Payment-PayTo'] = '0x3f1...9915'
    return response

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
