import express from "express";
import { createProxyMiddleware } from "http-proxy-middleware";
import { paymentMiddleware, x402ResourceServer } from "@x402/express";
import { HTTPFacilitatorClient } from "@x402/core/server";
import { ExactEvmScheme } from "@x402/evm/exact/server";
import { declareDiscoveryExtension } from "@x402/extensions/bazaar";

const PAY_TO = process.env.PAY_TO || "0x3f10530c86e6a1d26edbf27b6b6e660c77d79915";
const PRICE = process.env.PRICE_USDC || "0.01";
const PRICE_LABEL = PRICE.startsWith("$") ? PRICE : `$${PRICE}`;
const FLASK_TARGET = process.env.FLASK_TARGET || "http://127.0.0.1:5000";
const PORT = Number(process.env.PORT || 8080);
const NETWORK = "eip155:8453";
const FACILITATOR_URL = process.env.X402_FACILITATOR_URL || "https://facilitator.payai.network";

const facilitator = new HTTPFacilitatorClient({ url: FACILITATOR_URL });
const resourceServer = new x402ResourceServer(facilitator).register(NETWORK, new ExactEvmScheme());

const app = express();
// Railway terminates TLS; without this, x402 resource URLs become http:// and break settle/indexing.
app.set("trust proxy", 1);

const proxy = createProxyMiddleware({
  target: FLASK_TARGET,
  changeOrigin: true,
  // Fail fast instead of hanging agents for 30–120s (was causing Railway red latency).
  proxyTimeout: 20000,
  timeout: 20000,
});

const freeRoutes = [
  "/",
  "/health",
  "/api/coins",
  "/api/preview",
  "/openapi.json",
  "/.well-known/x402",
  "/.well-known/mcp.json",
  "/llms.txt",
  "/ai.txt",
  "/robots.txt",
  "/favicon.ico",
  "/favicon.svg",
];

for (const route of freeRoutes) {
  app.get(route, proxy);
}

const paidRoute = (path, description, discovery) => ({
  [`GET ${path}`]: {
    accepts: [{ scheme: "exact", price: PRICE_LABEL, network: NETWORK, payTo: PAY_TO }],
    description,
    mimeType: "application/json",
    extensions: declareDiscoveryExtension(discovery),
  },
});

app.use(paymentMiddleware({
  ...paidRoute(
    "/api/data",
    "Live crypto BUY/SELL/HOLD trading signal with support/resistance, regime, risk, edge_score and invalidation for Bitcoin/ETH/SOL — LLM-ready agent pack via x402",
    {
      input: { q: "btc", format: "agent" },
      inputSchema: {
        properties: {
          q: {
            type: "string",
            description: "Coin ticker for trading signal: btc, eth, sol, bitcoin, ethereum, …",
          },
          format: { type: "string", enum: ["agent", "full"] },
        },
        required: ["q"],
      },
      output: {
        example: {
          coin: "BTC",
          price_usd: 95000,
          signal: "HOLD",
          confidence: 62,
          edge_score: 64,
          regime: "calm",
          risk: "low",
          levels: { support: 92000, resistance: 98000 },
          reason: "neutral RSI; MACD flat",
          action_hint: "No strong edge.",
          invalidation: "break of support–resistance range",
        },
      },
    },
  ),
  ...paidRoute(
    "/api/compare",
    "Compare Bitcoin vs Ethereum vs Solana (2–5 coins) — BUY/SELL/HOLD briefs + vs-BTC relative strength in one x402 payment",
    {
      input: { coins: "btc,eth,sol", format: "agent" },
      inputSchema: {
        properties: {
          coins: {
            type: "string",
            description: "Comma-separated tickers to rank, e.g. btc,eth,sol",
          },
          format: { type: "string", enum: ["agent", "full"] },
        },
        required: ["coins"],
      },
      output: {
        example: {
          status: "ok",
          summary: { best_performer: "SOL", best_vs_btc: "SOL", best_edge: "ETH" },
          results: [],
        },
      },
    },
  ),
  ...paidRoute(
    "/api/trending",
    "Top crypto gainers and losers last 24h — momentum scan for AI trading agents via x402",
    {
      input: { limit: "5" },
      inputSchema: {
        properties: {
          limit: { type: "integer", description: "How many gainers/losers", default: 5 },
        },
      },
      output: { example: { gainers: [], losers: [] } },
    },
  ),
}, resourceServer));

app.get("/api/data", proxy);
app.get("/api/compare", proxy);
app.get("/api/trending", proxy);

app.listen(PORT, "0.0.0.0", () => {
  console.log(`x402 gateway v13.4 on :${PORT} price=${PRICE_LABEL}`);
});
