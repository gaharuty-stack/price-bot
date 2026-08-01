# Crypto Agent Brief API

LLM-ready crypto price + TA briefs for AI agents.
Pay per call via **x402 / USDC on Base** (PayAI facilitator).

**Live:** https://price-bot-production-4d6a.up.railway.app

## Status (v13.1)

Hardening release:
- non-blocking CoinGecko boot (no healthcheck stalls)
- shorter upstream timeouts (fail fast instead of 15s+ hangs)
- OHLC warm cache for hot coins
- gateway proxy timeout 20s
- `/health` now counts free traffic too (was stuck at 0)

## Why agents use this (not raw CoinGecko)

| Raw API | This API |
|---------|----------|
| 15 fields of JSON | 1 concise brief with `reason` + `action_hint` |
| 1 coin per call | Compare 5 coins in 1 call |
| No signal context | BUY/SELL/HOLD + confidence |
| Free but verbose | $0.01 — saves agent tokens & round-trips |

## Pricing

| Endpoint | Price |
|----------|-------|
| `GET /api/data?q=btc&format=agent` | **$0.01 USDC** |
| `GET /api/compare?coins=btc,eth,sol&format=agent` | **$0.01 USDC** |
| `GET /api/trending` | **$0.01 USDC** |
| `/api/coins`, `/api/preview`, `/health`, `/llms.txt`, `/.well-known/x402` | Free |

## Example: free preview

```
GET /api/preview?q=btc
```

## For AI agents

Read `/llms.txt` first. Use `?format=agent` for token-efficient responses.
Pay via x402 USDC on Base — no API keys needed.

## Disclaimer

TA signals are heuristic summaries, not financial advice.

## License

MIT
