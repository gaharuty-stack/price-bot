import express from "express";
import { createProxyMiddleware } from "http-proxy-middleware";
import { paymentMiddleware, x402ResourceServer } from "@x402/express";
import { HTTPFacilitatorClient } from "@x402/core/server";
import { ExactEvmScheme } from "@x402/evm/exact/server";

const PAY_TO = process.env.PAY_TO || "0x3f10530c86e6a1d26edbf27b6b6e660c77d79915";
const PRICE = process.env.PRICE_USDC || "0.001";
const PRICE_LABEL = PRICE.startsWith("$") ? PRICE : `$${PRICE}`;
const FLASK_TARGET = process.env.FLASK_TARGET || "http://127.0.0.1:5000";
const PORT = Number(process.env.PORT || 8080);
const NETWORK = "eip155:8453";
const FACILITATOR_URL = process.env.X402_FACILITATOR_URL || "https://facilitator.payai.network";

const facilitator = new HTTPFacilitatorClient({ url: FACILITATOR_URL });
const resourceServer = new x402ResourceServer(facilitator).register(NETWORK, new ExactEvmScheme());

const app = express();
const proxy = createProxyMiddleware({ target: FLASK_TARGET, changeOrigin: true });

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
];

for (const route of freeRoutes) {
  app.get(route, proxy);
}

const paidRoute = (path, description) => ({
  [`GET ${path}`]: {
    accepts: [{ scheme: "exact", price: PRICE_LABEL, network: NETWORK, payTo: PAY_TO }],
    description,
    mimeType: "application/json",
  },
});

app.use(paymentMiddleware({
  ...paidRoute("/api/data", "LLM-ready crypto brief for one coin (?format=agent)"),
  ...paidRoute("/api/compare", "Compare 2-5 coins in one request"),
  ...paidRoute("/api/trending", "Top gainers and losers (24h)"),
}, resourceServer));

app.get("/api/data", proxy);
app.get("/api/compare", proxy);
app.get("/api/trending", proxy);

app.listen(PORT, "0.0.0.0", () => {
  console.log(`x402 gateway v13 on :${PORT} price=${PRICE_LABEL}`);
});
