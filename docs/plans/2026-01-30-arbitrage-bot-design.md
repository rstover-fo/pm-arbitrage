# Prediction Market Arbitrage Bot - Design Document

**Date:** 2026-01-30
**Status:** Approved
**Author:** Rob + Claude

## Overview

An agent-based system that monitors prediction markets (Polymarket, Kalshi, others) and real-world data sources to identify and execute arbitrage opportunities automatically, with human-controlled risk parameters.

## Goals

- **Primary:** Generate consistent side income through automated arbitrage
- **Risk philosophy:** Initial capital is risk money; profits protected via ratcheting stop-loss
- **Automation level:** Full automation with human-managed bankroll and kill switch

## Architecture

### Agent-Based System

Eight autonomous agents communicating via Redis Streams message bus:

| Agent | Responsibility |
|-------|----------------|
| **Venue Watcher** | One per platform. Streams prices, order books, market metadata. |
| **Market Matcher** | Uses LLM to identify equivalent events across platforms. Maintains canonical opportunity universe. |
| **Real-World Oracle** | Streams authoritative external data (crypto prices, weather, sports, news). |
| **Opportunity Scanner** | Monitors for arbitrage signals. Classifies by type (cross-platform, oracle-based). |
| **Strategy Agents** | Multiple competing agents with different execution approaches. Bid on opportunities. |
| **Capital Allocator** | Runs the tournament. Allocates capital based on strategy track records. |
| **Executor** | Places orders, manages fills, handles retries. |
| **Risk Guardian** | Veto power over all trades. Enforces limits. Can halt entire system. |

### Message Bus Channels

| Channel | Publisher | Subscribers |
|---------|-----------|-------------|
| `venue.{platform}.prices` | Venue Watcher | Opportunity Scanner |
| `venue.{platform}.markets` | Venue Watcher | Market Matcher |
| `oracle.{type}.{symbol}` | Real-World Oracle | Opportunity Scanner |
| `matched.markets` | Market Matcher | Opportunity Scanner |
| `opportunities` | Opportunity Scanner | Strategy Agents |
| `trade.requests` | Strategy Agents | Risk Guardian → Executor |
| `trade.results` | Executor | Strategy Agents, Capital Allocator |
| `system.alerts` | Any agent | Alert Router |
| `system.commands` | User (kill switch) | All agents |

## Arbitrage Types

### Cross-Platform Arbitrage
Same event priced differently across prediction markets.

**Example:** "Will Bitcoin hit $100k by March?" at 45¢ on Polymarket, 52¢ on Kalshi.

### Oracle-Based Arbitrage (Primary Strategy)
Prediction markets lag real-world data sources.

| Data Source | Prediction Markets | Edge |
|-------------|-------------------|------|
| Crypto exchanges (Binance, Coinbase) | BTC/ETH/SOL up/down (15-min, hourly) | CEX price moves before PM odds adjust |
| Weather APIs (NOAA, OpenWeather) | Temperature, precipitation markets | Official forecasts update before markets |
| Sports APIs | Live game outcomes | Score changes before odds adjust |
| News feeds | Political/event markets | Breaking news before market reaction |
| Flight trackers | "Will X flight land on time?" | Real-time position data |
| Economic releases | Fed decisions, jobs numbers | Official release timing |

### Market Matching

LLM-assisted semantic matching to identify equivalent events across platforms:
- Input: Market titles, descriptions, resolution criteria from two platforms
- Output: Match confidence score (0-1), equivalence determination
- Human review: Uncertain matches (0.6-0.85 confidence) flagged for confirmation

## Execution Strategies

Multiple strategies run in parallel, competing for capital:

| Strategy | Approach | Risk Profile |
|----------|----------|--------------|
| `oracle-sniper` | Instant market buy when oracle divergence exceeds threshold | Aggressive, high volume |
| `oracle-patient` | Limit orders at favorable prices, waits for fill | Conservative, better prices |
| `atomic-arb` | Only executes if both legs fill simultaneously | Low risk, fewer opportunities |
| `leg-and-hedge` | Takes one side, hedges within time window | Medium risk, more opportunities |
| `mean-reversion` | Bets on odds returning to "fair" value after spikes | Contrarian |

### Tournament System

1. **Startup:** Equal allocation across all strategies
2. **Scoring window:** Rolling 7-day performance
3. **Reallocation:** Daily at midnight UTC
4. **Winners:** Top performers get increased allocation (linear to Sharpe ratio)
5. **Losers:** Bottom performers get allocation halved; below threshold = paused
6. **New strategies:** Enter with minimum viable bankroll, must earn their way up

## Risk Management

### Risk Guardian Rules

| Rule | Description | Action |
|------|-------------|--------|
| Position limit | Max exposure per market | Reject trade |
| Platform limit | Max total exposure per venue | Reject trade |
| Portfolio limit | Max total deployed capital | Reject trade |
| High-water mark | Track peak portfolio value | Monitor |
| Ratcheting stop | Portfolio drops X% from high-water mark | `HALT_ALL` |
| Daily loss limit | Max loss in 24h period | Pause until next day |
| Stale price | Prices older than N seconds | Reject trade |
| Slippage guard | Expected fill deviates too much | Reject trade |

### Risk Profile (Default)

- Initial bankroll: User-defined (e.g., $500)
- High-water mark: Starts at initial bankroll
- Ratcheting stop: 20% drawdown from peak
- Daily loss limit: 10% of bankroll
- Per-market position limit: 10% of bankroll
- Per-platform limit: 50% of bankroll

**Example:** Start with $500, grow to $800. New floor is $640 (80% of peak). If portfolio drops to $640, system halts and alerts user.

## Data Storage

### Three-Layer Architecture

| Layer | Technology | Purpose |
|-------|------------|---------|
| Hot state | Redis | Current positions, live prices, agent heartbeats |
| Warm storage | PostgreSQL | Trade history, performance, audit log |
| Cold analytics | Parquet files | Backtesting, historical analysis |

### Core Tables (PostgreSQL)

```sql
venues              -- Platform configs, API credentials (encrypted)
markets             -- All markets across all venues
market_matches      -- LLM equivalencies with confidence scores
positions           -- Current and historical positions
trades              -- Every execution with full context
strategy_performance-- Daily snapshots (P&L, Sharpe, win rate)
risk_events         -- Rejections, halts, limit breaches
alerts              -- All alerts sent and acknowledged
```

### Audit Trail

Every trade request logged with:
- Triggering opportunity
- Requesting strategy
- Risk Guardian decision + reason
- Execution result (fill price, slippage, fees)
- P&L attribution

## Alerting

### Tiered System

| Tier | Channel | Triggers |
|------|---------|----------|
| Routine | Dashboard | Trade executed, position changes, reallocation |
| Important | Push notification | Daily P&L, strategy rankings, unusual volume |
| Critical | SMS + push | Risk halt, API failure, drawdown warning |
| Emergency | All + repeat | System down, ratcheting stop hit |

## Dashboard

### Views

1. **Portfolio Overview** - Total value, high-water mark, P&L chart
2. **Live Positions** - Current holdings, unrealized P&L
3. **Strategy Leaderboard** - Tournament standings, allocation %
4. **Opportunity Feed** - Real-time detected opportunities
5. **Oracle Status** - Data feed health, latency
6. **Risk Monitor** - Limit utilization, recent rejections
7. **Audit Log** - Searchable trade history

## Tech Stack

| Component | Technology |
|-----------|------------|
| Language | Python 3.12+ |
| Agent Framework | asyncio + Redis pub/sub |
| Message Bus | Redis Streams |
| Database | PostgreSQL |
| Cache | Redis |
| Dashboard | Streamlit |
| LLM | Claude API (market matching) |
| Deployment | Railway |

### External Integrations

| Service | Purpose |
|---------|---------|
| Polymarket API | Primary venue |
| Kalshi API | Secondary venue |
| Binance/Coinbase WebSocket | Crypto oracle |
| OpenWeatherMap / Tomorrow.io | Weather oracle |
| Twilio or Pushover | Alerts |

## Deployment

### Phases

1. **Local (Mac)** - Development, paper trading
2. **Railway** - Live with small bankroll
3. **Scale** - Upgrade only if profits justify

### Railway Setup

- PostgreSQL and Redis as managed add-ons
- Deploy via GitHub integration
- Environment variables in dashboard
- Built-in logs and metrics

### Paper Trading Mode

Flag that makes Executor log trades without placing them. All other agents behave normally. Run 1-2 weeks before going live.

### Kill Switch Access

- Dashboard button: `HALT_ALL`
- CLI: `python cli.py halt`
- Optional: Telegram/Discord bot command

## Project Structure

```
pm-arbitrage/
├── agents/
│   ├── venue_watcher/
│   ├── market_matcher/
│   ├── oracle/
│   ├── opportunity_scanner/
│   ├── strategy/
│   ├── capital_allocator/
│   ├── executor/
│   └── risk_guardian/
├── adapters/
│   ├── venues/
│   │   ├── polymarket.py
│   │   ├── kalshi.py
│   │   └── base.py
│   └── oracles/
│       ├── crypto.py
│       ├── weather.py
│       └── base.py
├── core/
│   ├── message_bus.py
│   ├── models.py
│   └── config.py
├── dashboard/
│   └── app.py
├── cli.py
├── docker-compose.yml
├── requirements.txt
└── docs/
    └── plans/
```

## Open Questions / Future Considerations

1. **Backtesting:** Build historical replay system to test strategies before live deployment
2. **ML enhancement:** Train models on opportunity success rates to improve signal quality
3. **Additional venues:** Betfair, PredictIt, crypto prediction markets (Azuro, etc.)
4. **Latency optimization:** If edge erodes, consider colocation or faster infrastructure
5. **Tax implications:** Consult accountant on prediction market gains treatment

## Success Metrics

- **Sharpe ratio > 1.5** across portfolio
- **Win rate > 55%** on oracle-based trades
- **Max drawdown < 20%** from any peak
- **System uptime > 99%** during market hours
- **Alert response time < 5 min** for critical issues
