# Crypto Agent Brief API

x402 crypto **setup scanner** for AI agents. USDC settles to your `PAY_TO` wallet on Base — you do **not** need AgentCash funded to receive money.

**Live:** https://price-bot-production-4d6a.up.railway.app  
**Hero paid:** `/api/scan`  
**Free FOMO:** `/api/pulse`  
**Check earnings:** https://basescan.org/address/0x3f10530c86e6a1d26edbf27b6b6e660c77d79915  

## Pricing (v15.1)

| Endpoint | Price | Why |
|----------|-------|-----|
| `GET /api/pulse` | Free | Setup-count FOMO |
| `GET /api/preview?q=btc` | Free | Spot tease, signal locked |
| `GET /signal/BTC` | **$0.001** | Micro entry (trickle) |
| `GET /api/trending` | **$0.001** | Micro entry |
| `GET /api/scan` | **$0.05** | Real money — market setups |
| `GET /api/compare` | **$0.05** | Multi-coin + vs-BTC |

## Money flow

```text
Other AI agents → pay x402 USDC on Base → your PAY_TO wallet
```

AgentCash is only a *buyer* tool. Receiving uses `PAY_TO` + PayAI facilitator.

## Quick start

```bash
curl "https://price-bot-production-4d6a.up.railway.app/api/pulse"
curl "https://price-bot-production-4d6a.up.railway.app/health"
# Paid → HTTP 402 until x402 settle:
# GET /api/scan
# GET /signal/BTC
```

## Disclaimer

TA signals are heuristic summaries, not financial advice.

## License

MIT
