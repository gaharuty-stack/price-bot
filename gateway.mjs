import express from "express";
import { createProxyMiddleware } from "http-proxy-middleware";
import { paymentMiddleware, x402ResourceServer } from "@x402/express";
import { HTTPFacilitatorClient } from "@x402/core/server";
import { ExactEvmScheme } from "@x402/evm/exact/server";
import { declareDiscoveryExtension } from "@x402/extensions/bazaar";

const PAY_TO = process.env.PAY_TO || "0x3f10530c86e6a1d26edbf27b6b6e660c77d79915";
// Tiered pricing: entry signal vs hero scan/compare bundles.
const PRICE_SIGNAL = process.env.PRICE_SIGNAL_USDC || process.env.PRICE_USDC_OVERRIDE || "0.01";
const PRICE_BUNDLE = process.env.PRICE_BUNDLE_USDC || "0.05";
const PRICE_SCAN = process.env.PRICE_SCAN_USDC || PRICE_BUNDLE;
const label = (p) => (String(p).startsWith("$") ? String(p) : `$${p}`);
const FLASK_TARGET = process.env.FLASK_TARGET || "http://127.0.0.1:5000";
const PORT = Number(process.env.PORT || 8080);
const NETWORK = "eip155:8453";
const FACILITATOR_URL = process.env.X402_FACILITATOR_URL || "https://facilitator.payai.network";

const facilitator = new HTTPFacilitatorClient({ url: FACILITATOR_URL });
const resourceServer = new x402ResourceServer(facilitator).register(NETWORK, new ExactEvmScheme());

const app = express();
// Railway terminates TLS; without this, x402 resource URLs become http:// and break settle/indexing.
app.set("trust proxy", 1);

function decodePaymentRequiredHeader(value) {
  if (!value || typeof value !== "string") return null;
  try {
    const pad = "=".repeat((4 - (value.length % 4)) % 4);
    return JSON.parse(Buffer.from(value + pad, "base64url").toString("utf8"));
  } catch {
    try {
      return JSON.parse(Buffer.from(value, "base64").toString("utf8"));
    } catch {
      return null;
    }
  }
}

// @x402/express puts the challenge in Payment-Required and often sends body {}.
// Syra/AgentCash/x402scan clients expect the same JSON in the 402 response body.
app.use((req, res, next) => {
  const originalJson = res.json.bind(res);
  res.json = (body) => {
    if (res.statusCode === 402) {
      const empty =
        body == null ||
        (typeof body === "object" && !Array.isArray(body) && Object.keys(body).length === 0);
      if (empty) {
        const header =
          res.getHeader("payment-required") ||
          res.getHeader("Payment-Required") ||
          res.getHeader("PAYMENT-REQUIRED");
        const decoded = decodePaymentRequiredHeader(
          Array.isArray(header) ? header[0] : header,
        );
        if (decoded) return originalJson(decoded);
      }
    }
    return originalJson(body);
  };
  next();
});

const proxy = createProxyMiddleware({
  target: FLASK_TARGET,
  changeOrigin: true,
  proxyTimeout: 20000,
  timeout: 20000,
});

const freeRoutes = [
  "/",
  "/health",
  "/guidance",
  "/api/coins",
  "/api/preview",
  "/api/pulse",
  "/openapi.json",
  "/.well-known/x402",
  "/.well-known/x402.json",
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

const paidRoute = (path, price, description, discovery) => ({
  [`GET ${path}`]: {
    accepts: [{ scheme: "exact", price: label(price), network: NETWORK, payTo: PAY_TO }],
    description,
    mimeType: "application/json",
    extensions: declareDiscoveryExtension(discovery),
  },
});

const signalDiscovery = (exampleCoin) => ({
  input: exampleCoin ? undefined : { q: "btc" },
  inputSchema: exampleCoin
    ? {
        properties: {},
      }
    : {
        properties: {
          q: {
            type: "string",
            description: "Coin ticker for trading signal: btc, eth, sol, bitcoin, ethereum, …",
          },
        },
        required: ["q"],
      },
  output: {
    example: {
      coin: exampleCoin || "BTC",
      price_usd: 95000,
      signal: "HOLD",
      confidence: 62,
      edge_score: 64,
      confluence: 2,
      tradeable_now: false,
      regime: "calm",
      risk: "low",
      levels: { support: 92000, resistance: 98000 },
      reason: "neutral RSI; MACD flat",
      action_hint: "No strong edge.",
      invalidation: "break of support–resistance range",
      target_price: 98000,
      stop_loss: 92000,
    },
  },
});

const signalDesc = (coin) =>
  coin
    ? `Returns a trading signal for ${coin} (BUY/SELL/HOLD) with confluence, tradeable_now, S/R, ATR target/stop — ${label(PRICE_SIGNAL)} USDC x402 on Base`
    : `Live crypto BUY/SELL/HOLD trading signal with confluence, tradeable_now, S/R, regime, risk, edge_score — ${label(PRICE_SIGNAL)} USDC x402`;

const indexCoins = ["BTC", "ETH", "SOL", "XRP", "DOGE"];
const paidRoutes = {
  ...paidRoute(
    "/api/scan",
    PRICE_SCAN,
    `Market-wide BUY/SELL setup scanner for AI agents — ranked tradeable setups with confluence + ATR targets — ${label(PRICE_SCAN)} USDC x402`,
    {
      input: { limit: "5" },
      inputSchema: {
        properties: {
          limit: {
            type: "integer",
            description: "How many top buys and top sells to return",
            default: 5,
          },
        },
      },
      output: {
        example: {
          status: "ok",
          scanned: 15,
          tradeable_count: 3,
          top_buys: [signalDiscovery("SOL").output.example],
          top_sells: [],
          best_setup: signalDiscovery("SOL").output.example,
          summary: "3 tradeable setups / 15 scanned. Best: SOL BUY.",
        },
      },
    },
  ),
  ...paidRoute(
    "/api/data",
    PRICE_SIGNAL,
    `Legacy wrapped agent pack (prefer /api/scan or /signal/BTC) — ${label(PRICE_SIGNAL)} USDC x402`,
    {
      input: { q: "btc", format: "agent" },
      inputSchema: {
        properties: {
          q: { type: "string", description: "Coin ticker: btc, eth, sol, …" },
          format: { type: "string", enum: ["agent", "full"] },
        },
        required: ["q"],
      },
      output: { example: { status: "ok", data: signalDiscovery("BTC").output.example } },
    },
  ),
  ...paidRoute("/api/signal", PRICE_SIGNAL, signalDesc(), signalDiscovery()),
  ...paidRoute("/trade-signal", PRICE_SIGNAL, signalDesc(), signalDiscovery()),
  ...paidRoute(
    "/signal/:coin",
    PRICE_SIGNAL,
    signalDesc(),
    {
      inputSchema: {
        properties: {
          coin: { type: "string", description: "Ticker: BTC, ETH, SOL, …" },
        },
        required: ["coin"],
      },
      output: signalDiscovery("BTC").output,
    },
  ),
  ...paidRoute(
    "/api/v1/signal/:coin",
    PRICE_SIGNAL,
    signalDesc(),
    {
      inputSchema: {
        properties: {
          coin: { type: "string", description: "Ticker: BTC, ETH, SOL, …" },
        },
        required: ["coin"],
      },
      output: signalDiscovery("BTC").output,
    },
  ),
  ...paidRoute(
    "/api/compare",
    PRICE_BUNDLE,
    `Compare Bitcoin vs Ethereum vs Solana (2–5 coins) — BUY/SELL/HOLD + vs-BTC strength in one ${label(PRICE_BUNDLE)} x402 payment`,
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
    PRICE_SIGNAL,
    `Top crypto gainers and losers last 24h — momentum list for AI trading agents via x402 (${label(PRICE_SIGNAL)})`,
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
};

for (const coin of indexCoins) {
  Object.assign(
    paidRoutes,
    paidRoute(`/signal/${coin}`, PRICE_SIGNAL, signalDesc(coin), signalDiscovery(coin)),
    paidRoute(`/api/v1/signal/${coin}`, PRICE_SIGNAL, signalDesc(coin), signalDiscovery(coin)),
  );
}

app.use(paymentMiddleware(paidRoutes, resourceServer));

app.get("/api/scan", proxy);
app.get("/api/data", proxy);
app.get("/api/signal", proxy);
app.get("/trade-signal", proxy);
app.get("/api/compare", proxy);
app.get("/api/trending", proxy);
app.get("/signal/:coin", proxy);
app.get("/api/v1/signal/:coin", proxy);

app.listen(PORT, "0.0.0.0", () => {
  console.log(
    `x402 gateway v15.0 on :${PORT} signal=${label(PRICE_SIGNAL)} scan=${label(PRICE_SCAN)}`,
  );
});
