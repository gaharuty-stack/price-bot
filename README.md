# Crypto Agent Brief API

LLM-ready crypto price + TA briefs for AI agents.  
Pay per call via **x402 / USDC on Base** (PayAI facilitator).

**Live:** https://price-bot-production-4d6a.up.railway.app

## Why agents use this (not raw CoinGecko)

| Raw API | This API |
|---------|----------|
| 15 fields of JSON | 1 concise brief with `reason` + `action_hint` |
| 1 coin per call | Compare 5 coins in 1 call |
| No signal context | BUY/SELL/HOLD + confidence |
| Free but verbose | $0.001 — saves agent tokens & round-trips |

## Pricing

| Endpoint | Price |
|----------|-------|
| `GET /api/data?q=btc&format=agent` | **$0.001 USDC** |
| `GET /api/compare?coins=btc,eth,sol&format=agent` | **$0.001 USDC** |
| `GET /api/trending` | **$0.001 USDC** |
| `/api/coins`, `/health`, `/llms.txt`, `/.well-known/x402` | Free |

## Example: agent brief (paid)

```
GET /api/data?q=btc&format=agent
```

```json
{
  "status": "ok",
  "data": {
    "coin": "BTC",
    "price_usd": 64373,
    "change_24h": "+0.63%",
    "signal": "HOLD",
    "confidence": 50.0,
    "reason": "neutral (RSI 52); MACD bearish; price mid-range in Bollinger bands; 24h change +0.63%",
    "action_hint": "No strong edge. Wait for clearer RSI/MACD alignment before acting.",
    "target_price": 64373,
    "stop_loss": 64373
  }
}
```

## Example: compare (paid)

```
GET /api/compare?coins=btc,eth,sol&format=agent
```

Returns 3 coins + best/worst performer summary in one response.

## Example: trending (paid)

```
GET /api/trending?limit=5
```

Returns top 5 gainers and losers from supported coins (24h).

## Free discovery

```
GET /api/coins
GET /health
GET /llms.txt
GET /.well-known/x402
```

## Supported coins (21)

BTC, ETH, SOL, DOGE, ADA, XRP, DOT, LINK, MATIC, LTC, AVAX, SHIB, UNI, ATOM, FIL, NEAR, ALGO, VET, XTZ, XLM, XMR

## For AI agents

Read `/llms.txt` first. Use `?format=agent` for token-efficient responses.  
Pay via x402 USDC on Base — no API keys needed.

## Disclaimer

TA signals are heuristic summaries, not financial advice.

## License

MIT
