from flask import Flask, request, jsonify
import aiohttp
import asyncio
import json
from bs4 import BeautifulSoup
import re

app = Flask(__name__)

# ====================================================
# РЕАЛЬНЫЙ ПАРСИНГ — ЗАМЕНИ URL И СЕЛЕКТОРЫ ПОД СВОЙ САЙТ
# ====================================================

async def fetch_data(query: str):
    """
    Парсит реальный сайт с автозапчастями (пример).
    ЗДЕСЬ ТЫ МЕНЯЕШЬ:
    1. url — адрес сайта, который парсишь
    2. headers — если сайт требует User-Agent
    3. Селекторы для названия, цены, наличия
    """
    
    # ПРИМЕР: сайт с автозапчастями (замени на свой)
    # Если сайт использует API — проще, если HTML — используй BeautifulSoup
    url = f"https://www.exist.ru/search/?q={query}"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9"
    }
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, headers=headers, timeout=20) as resp:
                if resp.status == 200:
                    html = await resp.text()
                    soup = BeautifulSoup(html, 'html.parser')
                    
                    # ИЩЕМ ТОВАРЫ (селекторы зависят от сайта)
                    # Это пример — замени под структуру своего сайта
                    items = soup.find_all('div', class_='product-item')
                    
                    if not items:
                        # Если нет товаров — пробуем другой селектор
                        items = soup.find_all('div', class_='catalog-item')
                    
                    results = []
                    for item in items[:20]:  # Ограничиваем 20 товаров
                        try:
                            # Извлекаем название
                            title_elem = item.find('a', class_='product-name') or item.find('h3')
                            title = title_elem.text.strip() if title_elem else "Неизвестно"
                            
                            # Извлекаем цену (ищем числа в тексте)
                            price_elem = item.find('span', class_='price') or item.find('div', class_='price')
                            if price_elem:
                                price_text = price_elem.text.strip()
                                # Извлекаем число из текста
                                price_match = re.search(r'([\d\s,]+)', price_text)
                                price = float(price_match.group(1).replace(' ', '').replace(',', '.')) if price_match else 0.0
                            else:
                                price = 0.0
                            
                            # Проверяем наличие
                            stock_text = item.text.lower()
                            in_stock = "нет" not in stock_text and "отсутствует" not in stock_text
                            
                            results.append({
                                "title": title,
                                "price": round(price, 2),
                                "in_stock": in_stock,
                                "source": "exist.ru"
                            })
                        except Exception as e:
                            # Если один товар не распарсился — пропускаем
                            continue
                    
                    return results
                else:
                    return [{"error": f"HTTP {resp.status} — возможно, сайт заблокировал запрос"}]
                    
        except Exception as e:
            return [{"error": f"Ошибка парсинга: {str(e)}"}]

# ====================================================
# ТЕСТОВЫЙ РЕЖИМ (ЕСЛИ РЕАЛЬНЫЙ ПАРСИНГ НЕ РАБОТАЕТ)
# ====================================================

async def fetch_fallback_data(query: str):
    """Возвращает тестовые данные, если реальный парсинг падает"""
    return [
        {"title": f"Товар по запросу '{query}' — {i}", "price": 100 + i * 10, "in_stock": i % 2 == 0, "source": "fallback"}
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
    
    try:
        # Пытаемся получить реальные данные
        result = loop.run_until_complete(fetch_data(query))
    except Exception:
        # Если упало — возвращаем тестовые данные
        result = loop.run_until_complete(fetch_fallback_data(query))
    
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
    response.headers['X-Payment-Description'] = 'Price and stock data for auto parts'
    return response

# ====================================================
# ЗАПУСК
# ====================================================

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
