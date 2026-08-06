# Crypto Agent Brief API

x402 crypto **setup scanner** for AI agents — not raw CoinGecko dumps.

**Hero product:** one paid call returns ranked BUY/SELL setups with confluence, `tradeable_now`, S/R, ATR targets.

**Live:** https://price-bot-production-4d6a.up.railway.app  
**Best paid call:** https://price-bot-production-4d6a.up.railway.app/api/scan  
**Free pulse:** https://price-bot-production-4d6a.up.railway.app/api/pulse  
**Free preview:** https://price-bot-production-4d6a.up.railway.app/api/preview?q=btc  
**Guidance:** https://price-bot-production-4d6a.up.railway.app/guidance  

## Pricing (v15.0.0)

| Endpoint | Price |
|----------|-------|
| `GET /api/pulse` | **Free** (setup count FOMO; directions locked) |
| `GET /api/preview?q=btc` | **Free** (spot + 24h + setup_hint) |
| `GET /api/scan` | **$0.05 USDC** — hero: market-wide setups |
| `GET /api/compare?coins=btc,eth,sol` | **$0.05 USDC** |
| `GET /signal/BTC` (also ETH/SOL) | **$0.01 USDC** |
| `GET /api/trending` | **$0.01 USDC** |
| `/guidance`, `/api/coins`, `/health`, `/llms.txt` | Free |

Network: **Base**. Facilitator: **PayAI**.

## Why this sells

| Weak API | This API |
|----------|----------|
| One-coin coin-flip | `/api/scan` ranks what to trade next |
| Price dump | confluence + `tradeable_now` |
| Fixed ±2% targets | ATR-based target/stop |
| Race-to-$0.001 | Honest tiers agents can budget |

## Quick start

```bash
curl "https://price-bot-production-4d6a.up.railway.app/api/pulse"
curl "https://price-bot-production-4d6a.up.railway.app/api/preview?q=btc"
curl "https://price-bot-production-4d6a.up.railway.app/guidance"
# Paid routes return HTTP 402 until settled via x402 USDC on Base:
# GET /api/scan
# GET /signal/BTC
```

## Disclaimer

TA signals are heuristic summaries, not financial advice.

## License

MIT
