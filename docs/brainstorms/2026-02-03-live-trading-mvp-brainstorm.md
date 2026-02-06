# Live Trading MVP Brainstorm

**Date:** 2026-02-03
**Status:** Ready for planning
**Next:** `/workflows:plan`

---

## What We're Building

A **Minimal Viable Live Executor** that replaces the paper trading executor with real Polymarket order placement. The system architecture remains unchanged—same opportunity scanner, risk guardian, and message bus. The only difference is trades execute for real.

### Scope

- **Venue:** Polymarket only
- **Capital:** $100-500 micro stakes
- **Risk posture:** Trust existing Risk Guardian rules
- **Auth:** API key (preferred) or wallet signing if required
- **Deployment:** Local machine initially, cloud later

### Out of Scope (for now)

- Multi-venue support (Kalshi)
- Advanced order lifecycle management
- Dedicated fill monitoring WebSocket
- Position reconciliation systems
- Shadow/testnet mode

---

## Why This Approach

**Minimal Viable Live** was chosen over alternatives:

| Approach | Rejected Because |
|----------|------------------|
| Order Lifecycle First | Over-engineers for micro stakes; delays thesis validation |
| Shadow Mode | Adds indirection; real API behavior may differ from testnet |

**Core reasoning:**
1. Paper trading has validated the architecture end-to-end
2. Risk Guardian already enforces position limits and drawdown stops
3. $100-500 means low absolute risk even if something goes wrong
4. The goal is to prove oracle lag arbitrage works with real money—fast feedback > perfect plumbing
5. Order lifecycle polish can be added once the thesis is validated

---

## Key Decisions

### 1. Executor Swap Strategy

**Decision:** Create `LiveExecutorAgent` that mirrors `PaperExecutorAgent` interface but calls Polymarket's order API.

**Rationale:** Keeps the rest of the system untouched. Pilot can switch between paper and live via config flag.

### 2. Authentication

**Decision:** Use Polymarket API key if available; fall back to wallet signing if required.

**Rationale:** API keys are simpler to manage. Need to verify Polymarket's current auth requirements.

**Open question:** Does Polymarket offer API key auth for CLOB, or is wallet signing mandatory?

### 3. Order Confirmation

**Decision:** Synchronous confirmation—wait for order acknowledgment before returning success.

**Rationale:** Simpler than fire-and-forget. At micro stakes, the latency cost is acceptable.

### 4. Error Handling

**Decision:** On order failure, log error and emit failure event. Do NOT retry automatically.

**Rationale:** At this stage, prefer visibility over automation. Manual review of failures is fine for micro stakes.

### 5. Position Tracking

**Decision:** Use existing `Position` model and postgres persistence. Update position on confirmed fills.

**Rationale:** Paper executor already does this. Live executor reuses the same pattern.

### 6. Kill Switch

**Decision:** Respect existing Risk Guardian rules (max position, drawdown stop). Add manual kill switch via CLI command (`pm-arb stop`).

**Rationale:** Risk Guardian already provides automated circuit breakers. Manual stop is backup.

### 7. Fee-Aware Edge Calculation

**Decision:** Modify opportunity scanner to calculate **net edge** = gross edge - expected taker fee.

**Implementation:**
- Add fee schedule by market type (15-min crypto: probability-dependent; others: 0%)
- Calculate expected fee based on current price/probability
- Only emit opportunity if net edge ≥ `min_edge_pct` (2%)

**Fee formula for 15-min crypto:**
```
fee_rate = 0.0312 * (0.5 - abs(price - 0.5))  # Max 1.56% at 50¢
expected_fee = trade_size * fee_rate
net_edge = gross_edge - fee_rate
```

**Rationale:** Ensures profitability after fees; single codebase handles all markets.

### 8. Position Sizing

**Decision:** Use existing capital allocator with conservative fixed sizing for MVP.

**MVP approach:**
- Total capital: $200-500 (configurable)
- Max per-trade: $10-20 (hard cap during validation)
- Let existing allocator handle multi-strategy distribution

**Future (Phase 2):**
- Add Kelly criterion as optional sizing mode
- Configurable: `sizing_strategy = "fixed" | "allocator" | "kelly" | "half_kelly"`
- Requires real data on edge sizes and win rates to calibrate properly

**Rationale:** Validates core thesis with minimal risk before optimizing position sizing.

### 9. Monitoring & Alerting

**Decision:** Full alerting via Pushover (already configured in settings).

**Alert types to implement:**

| Alert | Priority | Trigger |
|-------|----------|---------|
| Agent crash | Critical | Any agent stops responding (>2 min stale) |
| Drawdown breach | Critical | Risk Guardian stops trading |
| Large loss | High | Single trade loses >$20 |
| Trade failure | High | Order rejected or API error |
| Trade confirmation | Normal | Each executed trade (with P&L) |
| Daily summary | Normal | End of day digest (trades, P&L, positions) |
| Opportunity activity | Low | Hourly count of detected opportunities |

**Implementation:**
- Create `AlertService` that wraps Pushover API
- Integrate with existing agent heartbeat system
- Add alert hooks to Risk Guardian, executor, and pilot

**Rationale:** Full visibility into live trading; catch issues before they compound.

### 10. Rollback Strategy

**Decision:** Manual rollback only for MVP (stay in control).

**Rollback playbook:**

| Scenario | Detection | Action |
|----------|-----------|--------|
| Bug in executor | Unexpected trades/positions | 1) `pm-arb stop` 2) Set `paper_trading=True` 3) Cancel orders in Polymarket UI 4) Investigate logs |
| Risk Guardian failure | Position exceeds limits | 1) Kill pilot 2) Verify positions in UI 3) Manually close excess 4) Root cause |
| API failure | Repeated order rejections | 1) Check logs for error details 2) Verify auth/rate limits 3) Re-auth if needed |
| Strategy unprofitable | Sustained losses | 1) Lower `initial_bankroll` 2) Switch to paper mode 3) Analyze performance 4) Adapt |

**Kill switch implementation:**
- `pm-arb stop` CLI command (graceful shutdown)
- Ctrl+C on pilot process (existing signal handling)
- Set `paper_trading = True` in .env (instant switch to paper mode)

**Rationale:** Manual control is safest for MVP. Auto-recovery adds complexity and failure modes.

---

## Research Findings (2026-02-03)

### Authentication (Answered)

**Wallet signing is mandatory.** Polymarket uses two-level auth:
- **L1:** Sign EIP-712 message with private key → generates API credentials
- **L2:** Use API creds (apiKey, secret, passphrase) for HMAC-SHA256 request signing
- **Order signing:** Even with L2 creds, orders still require wallet signature

**Your adapter already handles this** via `py-clob-client`:
- `PolymarketAdapter` takes `credentials` with `api_key`, `secret`, `passphrase`, `private_key`
- `place_order()` uses `_clob_client.create_and_post_order()` which handles signing
- Chain ID 137 (Polygon mainnet) hardcoded correctly

**Action:** Generate/store credentials securely (env vars or secrets manager).

Sources: [Polymarket Auth Docs](https://docs.polymarket.com/developers/CLOB/authentication), [py-clob-client](https://github.com/Polymarket/py-clob-client)

### Fee Structure (Answered)

**Critical finding: 15-minute crypto markets now have taker fees that likely kill the arbitrage edge.**

| Market Type | Maker Fee | Taker Fee |
|-------------|-----------|-----------|
| Most markets | 0% | 0% |
| **15-min crypto markets** | 0% | **Up to 1.56% at 50% odds** |

The taker fee on 15-min crypto markets was introduced specifically to neutralize latency arbitrage:
- Fee highest (~3.15% on 50¢ contract) precisely where arbitrage strategies operate
- Fees collected fund maker rebates
- Only affects: BTC, ETH, SOL, XRP 15-min markets

**Impact on strategy:** Oracle lag arbitrage on 15-min crypto markets is likely unprofitable now. Consider:
1. Target **non-15-min markets** (event-based crypto markets, long-duration price targets)
2. Target **non-crypto markets** (still zero fees)
3. Accept reduced edge on 15-min markets (may still work if lag is substantial)

Sources: [Polymarket Maker Rebates](https://docs.polymarket.com/polymarket-learn/trading/maker-rebates-program), [The Block](https://www.theblock.co/post/384461/polymarket-adds-taker-fees-to-15-minute-crypto-markets-to-fund-liquidity-rebates), [Finance Magnates](https://www.financemagnates.com/cryptocurrency/polymarket-introduces-dynamic-fees-to-curb-latency-arbitrage-in-short-term-crypto-markets/)

### Rate Limits (Answered)

| Endpoint | Limit |
|----------|-------|
| `/order` | 3000 per 10 minutes |
| Non-trading queries | ~1000/hour |
| Throttling | Cloudflare-based, requests delayed (not dropped) |

**Impact:** 3000 orders/10 min = 5 orders/sec sustained. More than adequate for micro-stakes.

Sources: [Polymarket Rate Limits](https://docs.polymarket.com/quickstart/introduction/rate-limits)

### Testnet (Answered)

**No testnet.** Polymarket does not offer a sandbox environment.

**Testing alternatives:**
1. Test with minimal capital on mainnet (~$10 per trade)
2. Use Manifold Markets (play money) for logic validation
3. Local forks for contract testing

Sources: [QuantVPS Guide](https://www.quantvps.com/blog/setup-polymarket-trading-bot)

---

## Revised Strategy

Given the taker fee on 15-min crypto markets, the original oracle lag strategy needs adjustment:

### Option A: Pivot to Non-15-Min Markets
Target longer-duration crypto price markets (e.g., "BTC above $X by end of week") where:
- No taker fees
- Oracle lag still exists (less frequent but larger moves)
- Lower trade frequency, potentially higher edge per trade

### Option B: Pivot to Non-Crypto Markets
Political, sports, or other event markets:
- Zero fees
- Different oracle requirements (news feeds, APIs)
- Less predictable signal sources

### Option C: Accept Reduced Edge
Stay on 15-min crypto:
- Fee at 50% odds is 1.56%, typical arbitrage edge is 2-5%
- May still be profitable if you catch large/fast moves
- Higher variance, lower expected value

**Decision:** Account for fees in edge calculation. Build fee-awareness into the opportunity scanner so it calculates **net edge** (gross edge - expected fee) and only trades when net edge exceeds threshold.

Benefits:
- Threshold stays at 2% **net** (meaningful after fees)
- Automatically filters marginal opportunities on fee markets
- Works across all market types (fee and fee-free)
- Single codebase handles both scenarios

---

## Open Questions (Remaining)

1. **Token ID mapping:** How to get the correct `token_id` for order placement from market data?
2. **Credential generation:** Best practice for generating and storing L1/L2 credentials securely?
3. **15-min market detection:** How to identify which markets have taker fees vs fee-free?

---

## Success Criteria

1. Live executor places real orders on Polymarket
2. Orders execute and settle correctly
3. Position tracking matches actual holdings
4. P&L reporting reflects real gains/losses
5. Risk Guardian stops trading if limits hit
6. System recovers gracefully from API errors

---

## Implementation Signals

Ready for `/workflows:plan`:
- [x] Polymarket API auth requirements clarified (wallet signing mandatory, py-clob-client handles it)
- [x] Fee structure understood (15-min crypto has taker fees, others are free)
- [x] Rate limits documented (3000 orders/10 min, adequate for micro-stakes)

---

## Next Steps

Run `/workflows:plan` to create implementation tasks for the Live Executor MVP.
