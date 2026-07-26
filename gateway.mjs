import express from "express";
import { createProxyMiddleware } from "http-proxy-middleware";
import { paymentMiddleware, x402ResourceServer } from "@x402/express";
import { HTTPFacilitatorClient } from "@x402/core/server";
import { ExactEvmScheme } from "@x402/evm/exact/server";

const PAY_TO = process.env.PAY_TO || "0x3f10530c86e6a1d26edbf27b6b6e660c77d79915";
const PRICE = process.env.PRICE_USDC || "0.001";
const PRICE_LABEL = PRICE.startsWith("$") ? PRICE : `$${PRICE}`;
const FLASK_TARGET = process.env.FLASK_TARGET || "http://127.0.0.1:5000";
const PORT = Number(process.env.PORT || 10000);
const FACILITATOR_URL = process.env.X402_FACILITATOR_URL || "https://x402.org/facilitator";
const BASE_MAINNET = "eip155:8453";

const facilitator = new HTTPFacilitatorClient({ url: FACILITATOR_URL });
const resourceServer = new x402ResourceServer(facilitator).register(BASE_MAINNET, new ExactEvmScheme());

const app = express();
const proxy = createProxyMiddleware({ target: FLASK_TARGET, changeOrigin: true });

for (const path of ["/", "/health", "/api/coins", "/openapi.json", "/.well-known/x402", "/.well-known/mcp.json", "/ai.txt", "/robots.txt"]) {
  app.use(path, proxy);
}

app.use(paymentMiddleware({
  "GET /api/data": {
    accepts: [{ scheme: "exact", price: PRICE_LABEL, network: BASE_MAINNET, payTo: PAY_TO }],
    description: "Crypto price with TA indicators",
    mimeType: "application/json",
  },
}, resourceServer));

app.use("/api/data", proxy);
app.listen(PORT, "0.0.0.0", () => console.log(`Gateway on :${PORT}`));
