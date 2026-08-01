# Crypto Agent Brief API

Cheap x402 crypto intelligence for AI agents — not raw CoinGecko dumps.  
One call: **price + BUY/SELL/HOLD + support/resistance + regime + risk + invalidation**.

**Live:** https://price-bot-production-4d6a.up.railway.app  
**Free preview:** https://price-bot-production-4d6a.up.railway.app/api/preview?q=btc  
**Agent docs:** https://price-bot-production-4d6a.up.railway.app/llms.txt  
**OpenAPI:** https://price-bot-production-4d6a.up.railway.app/openapi.json

## Pricing (v13.3)

| Endpoint | Price |
|----------|-------|
| `GET /api/preview?q=btc` | **Free** |
| `GET /api/data?q=btc` | **$0.01 USDC** |
| `GET /api/compare?coins=btc,eth,sol` | **$0.01 USDC** (up to 5 coins) |
| `GET /api/trending` | **$0.01 USDC** |
| `/api/coins`, `/health`, `/llms.txt`, `/.well-known/x402` | Free |

Network: **Base**. Facilitator: **PayAI**. Default response format: **agent**.

## Why unique

| Typical API | This API |
|-------------|---------|
| Price only / huge JSON | Compact agent pack |
| No invalidation | `levels` + `invalidation` line |
| 1 coin / expensive essay | Compare 5 coins for $0.01 + vs-BTC strength |
| API keys | x402 pay-per-call |

## Quick start

```bash
curl "https://price-bot-production-4d6a.up.railway.app/api/preview?q=btc"
curl "https://price-bot-production-4d6a.up.railway.app/llms.txt"
```

Paid routes return **HTTP 402** until settled via x402 USDC on Base.

## Disclaimer

TA signals are heuristic summaries, not financial advice.

## License

MIT
