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

app.get("/", proxy);
app.get("/health", proxy);
app.get("/api/coins", proxy);
app.get("/openapi.json", proxy);
app.get("/.well-known/x402", proxy);
app.get("/.well-known/mcp.json", proxy);
app.get("/llms.txt", proxy);
app.get("/ai.txt", proxy);
app.get("/robots.txt", proxy);

app.use(paymentMiddleware({
  "GET /api/data": {
    accepts: [{ scheme: "exact", price: PRICE_LABEL, network: NETWORK, payTo: PAY_TO }],
    description: "Crypto brief for one coin",
    mimeType: "application/json",
  },
  "GET /api/compare": {
    accepts: [{ scheme: "exact", price: PRICE_LABEL, network: NETWORK, payTo: PAY_TO }],
    description: "Compare 2-5 coins",
    mimeType: "application/json",
  },
  "GET /api/trending": {
    accepts: [{ scheme: "exact", price: PRICE_LABEL, network: NETWORK, payTo: PAY_TO }],
    description: "Top gainers and losers",
    mimeType: "application/json",
  },
}, resourceServer));

app.get("/api/data", proxy);
app.get("/api/compare", proxy);
app.get("/api/trending", proxy);

app.listen(PORT, "0.0.0.0", () => {
  console.log("x402 gateway v12 on :" + PORT + " price=" + PRICE_LABEL);
});
