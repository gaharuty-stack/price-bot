# Crypto Agent Brief API

Cheapest x402 crypto intelligence for AI agents — not raw CoinGecko dumps.
One call: **price + BUY/SELL/HOLD + support/resistance + regime + risk + invalidation**.

**Live:** https://price-bot-production-4d6a.up.railway.app  
**Preferred paid call:** https://price-bot-production-4d6a.up.railway.app/signal/BTC  
**Free preview:** https://price-bot-production-4d6a.up.railway.app/api/preview?q=btc  
**Guidance:** https://price-bot-production-4d6a.up.railway.app/guidance  
**OpenAPI:** https://price-bot-production-4d6a.up.railway.app/openapi.json  

## Pricing (v14.0.0)

| Endpoint | Price |
|----------|-------|
| `GET /api/preview?q=btc` | **Free** (spot + 24h + edge teaser; signal locked) |
| `GET /signal/BTC` (also `/signal/ETH`, `/signal/SOL`) | **$0.001 USDC** |
| `GET /api/signal?q=btc` / `GET /trade-signal?q=btc` | **$0.001 USDC** |
| `GET /api/compare?coins=btc,eth,sol` | **$0.001 USDC** (up to 5 coins) |
| `GET /api/trending` | **$0.001 USDC** |
| `/guidance`, `/api/coins`, `/health`, `/llms.txt` | Free |

Network: **Base**. Facilitator: **PayAI**.

## Why unique

| Typical API | This API |
|-------------|---------|
| $0.01–$0.25 per signal | **$0.001** |
| Price only / huge JSON | Flat agent pack |
| No invalidation | `levels` + `invalidation` |
| 1 coin | Compare 5 coins + vs-BTC in one payment |
| API keys | x402 pay-per-call |

## Quick start

```bash
curl "https://price-bot-production-4d6a.up.railway.app/api/preview?q=btc"
curl "https://price-bot-production-4d6a.up.railway.app/guidance"
# Paid routes return HTTP 402 until settled via x402 USDC on Base:
# GET /signal/BTC
```

## Disclaimer

TA signals are heuristic summaries, not financial advice.

## License

MIT
