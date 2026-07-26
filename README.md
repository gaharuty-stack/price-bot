# Crypto Price & TA API

Real-time cryptocurrency prices and technical analysis for AI agents.  
Monetized via [x402](https://www.x402.org/) / USDC on Base through [agent402-tollbooth](https://agent402.tools/tollbooth).

## What you get

- **Real prices** from CoinGecko (not random numbers)
- **Real 24h change & volume**
- **TA indicators** computed from 30-day OHLC: RSI, MACD, Bollinger Bands, ATR, Stochastic
- **Rule-based signal** (BUY / SELL / HOLD) with confidence score
- **Honest metadata** — no fake backtests or social proof

## Pricing

| Endpoint | Price |
|----------|-------|
| `GET /api/data?q=bitcoin` | **$0.001 USDC** per request (Base mainnet, x402) |
| `GET /api/coins` | Free (discovery) |
| `GET /`, `/health`, `/.well-known/x402` | Free (discovery) |

Payment is enforced by **@x402/express** gateway (`gateway/gateway.mjs`) with real on-chain USDC settlement via the x402 facilitator. This replaces the old tollbooth-only setup where PoW let agents bypass payment entirely.

## Why the old version earned $0

1. **`pow: true`** — agents paid with free CPU, not USDC
2. **No `verifyX402`** — tollbooth advertised USDC but could not verify/settle it
3. **3 free trials in bot.py** — extra free access inside the app
4. **Fake data** — agents tried once and never returned
5. **No README** — zero discovery in x402 directories
6. **$0.10** — too expensive for unverified random signals

## Quick start (local)

```bash
pip install -r requirements.txt
python bot.py
# → http://localhost:5000/api/data?q=btc
```

## Deploy (Railway / Docker)

1. Set environment variables:

```env
INTEGRITY_SECRET=your-long-random-secret
TOLLBOOTH_SECRET=another-long-random-secret
ADMIN_TOKEN=admin-stats-token
PAY_TO=0xYourWalletAddress
PRICE_USDC=0.001
SERVICE_URL=https://your-app.up.railway.app
COINGECKO_API_KEY=optional-demo-api-key
```

2. Deploy with Docker — x402 gateway starts on `PORT` (default 10000), Flask on internal `:5000`.

3. Verify payment works:

```bash
# Free discovery
curl https://your-app.up.railway.app/.well-known/x402

# Paid endpoint (should return 402 without payment)
curl "https://your-app.up.railway.app/api/data?q=bitcoin"
```

4. Register your API in x402 directories (see below).

## API examples

```bash
# List supported coins (free)
curl https://your-app.up.railway.app/api/coins

# Get bitcoin data (requires x402 payment via tollbooth for bots)
curl -A "ClaudeBot/1.0" "https://your-app.up.railway.app/api/data?q=bitcoin"
# → 402 Payment Required

# x402 discovery
curl https://your-app.up.railway.app/.well-known/x402
```

## Supported coins

25 coins including BTC, ETH, SOL, DOGE, ADA, XRP, DOT, LINK, MATIC, LTC, AVAX, SHIB, UNI, ATOM, FIL, NEAR, ALGO, VET, XTZ and more.  
Use `/api/coins` for the full list with aliases.

## Why v11 vs old version

| Problem (v10) | Fix (v11) |
|---------------|-----------|
| PoW enabled → agents paid with CPU, not USDC | Real x402 gateway with on-chain USDC settlement |
| No verifyX402 in tollbooth | `@x402/express` + facilitator |
| $0.10/request too expensive | $0.001 — volume-friendly |
| Fake backtest, reputation, social proof | Removed — real CoinGecko data only |
| Double payment gate (tollbooth + bot 402) | Bot serves data; gateway handles payment only |
| No README / discovery | OpenAPI, MCP, ai.txt, this README |

## Register for discovery

List your API on x402 directories and agent marketplaces:

- [x402.org ecosystem](https://www.x402.org/)
- [agent402.tools](https://agent402.tools/)
- GitHub topics: `x402`, `agent-api`, `crypto-api`

## Admin

```bash
curl -H "X-Admin-Token: YOUR_TOKEN" https://your-app/admin/stats
```

## Disclaimer

Signals are heuristic TA summaries, not financial advice. Always verify data independently.
