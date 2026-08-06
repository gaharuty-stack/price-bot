import os

SECRET_KEY = os.environ.get("INTEGRITY_SECRET", "change-me-in-production")
PAY_TO = os.environ.get("PAY_TO", "0x3f10530c86e6a1d26edbf27b6b6e660c77d79915")
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")

# Hybrid pricing for trickle revenue without buyer wallet funding:
# - micro signal ($0.001) matches AgentCash search cache + low friction
# - scan/compare ($0.05) is the real money product
PRICE_SIGNAL = os.environ.get("PRICE_SIGNAL_USDC") or os.environ.get("PRICE_USDC_OVERRIDE") or "0.001"
PRICE_BUNDLE = os.environ.get("PRICE_BUNDLE_USDC") or "0.05"
PRICE_SCAN = os.environ.get("PRICE_SCAN_USDC") or PRICE_BUNDLE

PAYMENT = {
    "amount": PRICE_SIGNAL,
    "currency": "USDC",
    "network": os.environ.get("PAYMENT_NETWORK", "base"),
    "receiver": PAY_TO,
    "facilitator": os.environ.get(
        "X402_FACILITATOR_URL",
        "https://facilitator.payai.network",
    ),
}

PAYMENT_TIERS = {
    "signal": PRICE_SIGNAL,
    "trending": PRICE_SIGNAL,
    "compare": PRICE_BUNDLE,
    "scan": PRICE_SCAN,
}

COINGECKO_BASE = "https://api.coingecko.com/api/v3"
COINGECKO_API_KEY = os.environ.get("COINGECKO_API_KEY", "")

CACHE_TTL_SECONDS = int(os.environ.get("CACHE_TTL_SECONDS", "60"))
RATE_LIMIT_PER_MINUTE = int(os.environ.get("RATE_LIMIT_PER_MINUTE", "120"))
PREVIEW_RATE_LIMIT_PER_MINUTE = int(os.environ.get("PREVIEW_RATE_LIMIT_PER_MINUTE", "30"))

COINS = {
    "bitcoin": "bitcoin", "btc": "bitcoin",
    "ethereum": "ethereum", "eth": "ethereum",
    "solana": "solana", "sol": "solana",
    "dogecoin": "dogecoin", "doge": "dogecoin",
    "cardano": "cardano", "ada": "cardano",
    "ripple": "ripple", "xrp": "ripple",
    "polkadot": "polkadot", "dot": "polkadot",
    "chainlink": "chainlink", "link": "chainlink",
    "polygon": "matic-network", "matic": "matic-network", "matic-network": "matic-network",
    "litecoin": "litecoin", "ltc": "litecoin",
    "stellar": "stellar", "xlm": "stellar",
    "monero": "monero", "xmr": "monero",
    "avalanche": "avalanche-2", "avax": "avalanche-2",
    "shiba-inu": "shiba-inu", "shib": "shiba-inu",
    "uniswap": "uniswap", "uni": "uniswap",
    "cosmos": "cosmos", "atom": "cosmos",
    "filecoin": "filecoin", "fil": "filecoin",
    "near": "near-protocol", "near-protocol": "near-protocol",
    "algorand": "algorand", "algo": "algorand",
    "vechain": "vechain", "vet": "vechain",
    "tezos": "tezos", "xtz": "tezos",
    "pepe": "pepe",
    "sui": "sui",
    "arbitrum": "arbitrum", "arb": "arbitrum",
    "optimism": "optimism", "op": "optimism",
    "aptos": "aptos", "apt": "aptos",
    "internet-computer": "internet-computer", "icp": "internet-computer",
    "binancecoin": "binancecoin", "bnb": "binancecoin",
    "tron": "tron", "trx": "tron",
    "the-open-network": "the-open-network", "ton": "the-open-network",
    "render": "render-token", "render-token": "render-token",
    "injective": "injective-protocol", "inj": "injective-protocol",
    "aave": "aave",
    "maker": "maker", "mkr": "maker",
    "cronos": "crypto-com-chain", "cro": "crypto-com-chain",
    "hedera": "hedera-hashgraph", "hbar": "hedera-hashgraph",
    "fetch": "fetch-ai", "fet": "fetch-ai",
    "bonk": "bonk",
    "sei": "sei-network",
    "celestia": "celestia", "tia": "celestia",
    "stacks": "blockstack", "stx": "blockstack",
    "immutable": "immutable-x", "imx": "immutable-x",
}

SERVICE_URL = os.environ.get(
    "SERVICE_URL",
    "https://price-bot-production-4d6a.up.railway.app",
)

VERSION = "15.1.0"
MAX_COMPARE_COINS = 5
# Coins with dedicated OpenAPI paths so AgentCash search matches "/signal/BTC" queries.
SIGNAL_INDEX_COINS = ("BTC", "ETH", "SOL", "XRP", "DOGE")
# Universe scanned by /api/scan (hot + liquid names).
SCAN_COINS = (
    "bitcoin",
    "ethereum",
    "solana",
    "binancecoin",
    "ripple",
    "dogecoin",
    "cardano",
    "avalanche-2",
    "chainlink",
    "sui",
    "the-open-network",
    "near-protocol",
    "arbitrum",
    "aave",
    "pepe",
)
