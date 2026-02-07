# PM Arbitrage Bot

**An automated system that finds and exploits pricing inefficiencies in prediction markets.**

## The Opportunity

Prediction markets (Polymarket, Kalshi) let you bet on real-world events - "Will BTC hit $100k?", "Will it rain in Miami tomorrow?". These markets often lag behind reality:

- **Crypto prices move on Binance seconds before** prediction market odds adjust
- **Weather forecasts update** before betting odds reflect new data
- **The same event priced differently** across platforms (45¢ vs 52¢)

This lag creates arbitrage opportunities.

## How It Works

Eight autonomous agents working together:

| Agent | Job |
|-------|-----|
| **Venue Watchers** | Stream prices from Polymarket, Kalshi |
| **Oracles** | Stream real-world data (Binance crypto, FRED economic data, NWS weather) |
| **Opportunity Scanner** | Detect when markets lag reality |
| **Strategy Agents** | Compete for capital using different approaches |
| **Risk Guardian** | Veto power - enforces position limits, drawdown stops |
| **Executor** | Places trades, handles fills |

## Risk Philosophy

- Initial capital = **risk money** (start with $500)
- Profits are **protected** via ratcheting stop-loss
- Grow to $800? New floor is $640 (80% of peak)
- **Full automation** with human-controlled kill switch

## Example Trade

1. BTC jumps 2% on Binance
2. Polymarket "BTC up in next 15 min" still priced at 45¢
3. Bot buys YES at 45¢
4. Market adjusts to 65¢
5. Bot sells or holds to resolution

## Tech Stack

- **Language:** Python 3.12
- **Message Bus:** Redis Streams
- **Database:** PostgreSQL
- **Dashboard:** Streamlit
- **Deployment:** Railway

## Project Status

| Sprint | Status | Deliverable |
|--------|--------|-------------|
| 1 | Complete | Foundation - agents communicate via message bus |
| 2 | In Progress | Live data from Polymarket, Kalshi + oracles (Binance, FRED, NWS) |
| 3 | Planned | Opportunity detection |
| 4 | Planned | Risk Guardian + paper trading |
| 5 | Planned | Strategy tournament system |
| 6 | Planned | Dashboard |
| 7 | Planned | Go live |

## Quick Start

```bash
# Start infrastructure
docker-compose up -d

# Install dependencies
pip install -e ".[dev]"

# Copy and configure environment
cp .env.example .env
# Edit .env with your API keys (Polymarket, Kalshi, FRED, etc.)

# Run tests
pytest tests/ -v

# Run linter
ruff check src/ tests/
```

> **Note on US legal compliance:** Kalshi is a CFTC-regulated exchange available to US residents. Polymarket has restrictions for US-based users. Ensure you comply with local regulations before enabling live trading on any venue.

## Documentation

- [Design Document](docs/plans/2026-01-30-arbitrage-bot-design.md) - Full architecture and rationale
- [Implementation Plan](docs/plans/2026-01-30-implementation-plan.md) - Sprint-by-sprint tasks

## License

Private project.
