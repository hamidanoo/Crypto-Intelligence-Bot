# API Configuration

Phase 1 provides the configuration structure and the
`ApiIntegration` model. The dashboard integration management
screens arrive in Phase 8.

Supported providers in later phases include Binance Spot,
Binance Futures, Binance announcements, CoinGecko, a crypto news
provider, Alternative.me, Etherscan, BscScan, and Telegram.

Rules that already apply in Phase 1:

- Public, read-only endpoints are preferred wherever possible.
- API keys and secrets live only in environment variables or the
  encrypted credential store, never in Git, logs, or frontend
  responses.
- `.env.example` contains placeholders only.
- Each integration records its base URL, enabled status, last
  successful request, last error, and rate limit configuration.
- Connection tests and masked key display are implemented with
  the dashboard in Phase 8.

No seed phrase, private wallet key, exchange password, or
withdrawal authorisation is ever requested or stored.
