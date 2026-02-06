# Institutional Learnings for Live Trading Executor

**Search Date:** 2026-02-03
**Scope:** Lessons from paper trading pilot, API integration patterns, and execution infrastructure
**Files Scanned:** BUG_FIXES_AND_PREVENTION.md, integration-issues/, execution-infrastructure plan, live-trading-mvp brainstorm, adapter conventions

---

## Critical Findings for Live Execution

### 1. Fee Structure Will Destroy Your Edge (CRITICAL)

**Finding:** 15-minute crypto markets on Polymarket now charge **up to 1.56% taker fees at 50% odds**.

**Impact on Strategy:**
- Typical oracle lag arbitrage edge: 2-5%
- Fee on 15-min markets: varies by price, max 1.56% at $0.50
- **Net edge after fees: Only 0.44-3.44%, and often below minimum threshold**

**Fee Calculation Formula (15-min crypto markets):**
```
fee_rate = 0.0312 * (0.5 - abs(price - 0.5))  # Max 1.56% at 50¢
expected_fee = trade_size * fee_rate
net_edge = gross_edge - fee_rate
```

**Decision Made (Reference):**
- Modify opportunity scanner to calculate **net edge** (gross edge - expected fee)
- Only emit opportunities if `net_edge ≥ min_edge_pct` (2%)
- Single codebase works for all markets (fee and fee-free)

**Gotcha to Avoid:**
- DO NOT assume your 2-5% edge still works on 15-min crypto
- Fees were introduced specifically to kill latency arbitrage strategies
- Your gross edge of 3% becomes net edge of 1.44% after fees → no longer profitable

**Market Type Fee Guide:**
| Market Type | Maker Fee | Taker Fee | Your Action |
|-------------|-----------|-----------|-------------|
| Most markets | 0% | 0% | Safe, proceed normally |
| **15-min crypto** | 0% | **Up to 1.56%** | **Adjust threshold UP or avoid** |

**Resources:**
- [Polymarket Maker Rebates Program](https://docs.polymarket.com/polymarket-learn/trading/maker-rebates-program)
- [The Block Analysis](https://www.theblock.co/post/384461/polymarket-adds-taker-fees-to-15-minute-crypto-markets-to-fund-liquidity-rebates)

---

### 2. Authentication is Mandatory Wallet Signing (NOT API Keys)

**Finding:** Polymarket requires **two-level authentication**. API keys alone are insufficient.

**Auth Flow (Two Levels):**
```
Level 1: Sign EIP-712 message with private key → generates API credentials
         (api_key, secret, passphrase)
Level 2: Use L2 creds for HMAC-SHA256 request signing
Level 3: Orders still require wallet signature even with L2 creds
```

**Implementation Pattern (Already in `py-clob-client`):**
```python
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds

creds = ApiCreds(
    api_key="your-api-key",
    api_secret="your-secret",
    api_passphrase="your-passphrase"
)

client = ClobClient(
    host="https://clob.polymarket.com",
    chain_id=137,  # Polygon mainnet - HARDCODE THIS
    key="0x<your-private-key>",  # Raw private key needed
    creds=creds
)
```

**Credential Storage Pattern (from execution-infrastructure plan):**
```python
# File: pm_arb/core/auth.py
class PolymarketCredentials(BaseModel):
    api_key: str
    secret: str
    passphrase: str
    private_key: str  # Must be 0x + 64 hex chars

    @field_validator("private_key")
    def validate_private_key(cls, v: str) -> str:
        """Validate private key format."""
        if not re.match(r"^0x[a-fA-F0-9]{64}$", v):
            raise ValueError("Invalid private key format")
        return v

    def __str__(self) -> str:
        """Mask secrets in logs."""
        return f"PolymarketCredentials(api_key={self.api_key[:8]}...)"

def load_credentials(venue: str) -> PolymarketCredentials:
    """Load from environment variables: POLYMARKET_API_KEY, etc."""
    # ... (see execution-infrastructure plan)
```

**Gotcha to Avoid:**
- Do NOT pass private key in logs or error messages
- Implement `__str__()` to mask secrets
- MUST validate private key format on load (0x + 64 hex chars)
- Chain ID 137 is hardcoded for mainnet—verify before mainnet deploy

**Environment Variables Required:**
```bash
POLYMARKET_API_KEY=...
POLYMARKET_SECRET=...
POLYMARKET_PASSPHRASE=...
POLYMARKET_PRIVATE_KEY=0x...
```

---

### 3. API Integration Reliability Patterns (HARD-LEARNED)

**Pattern from Paper Trading Pilot Bugs:**

#### 3a. Multi-Provider Fallback (Binance Geo-blocking)
**Problem:** Binance blocks requests from US due to regulatory restrictions.
**Solution:** Design multi-provider architecture from day one.

```python
from pm_arb.adapters.oracles.multi_provider import MultiProviderOracle

providers = [
    OracleProvider("binance", BinanceOracle(), priority=100),
    OracleProvider("coingecko", CoinGeckoOracle(), priority=50),
]
oracle = MultiProviderOracle(providers)

# Auto-falls back on failure, tries highest priority first
price = await oracle.get_current("BTC")
```

**Lesson:** If live trading fails on primary provider:
- Have CoinGecko as fallback (no geo-restrictions)
- Mark unhealthy providers after N failures
- Test fallover explicitly before going live

#### 3b. Batch API Calls (CoinGecko Rate Limits)
**Problem:** Per-symbol API calls = HTTP 429 immediately.
**Solution:** Batch all symbols in single call.

```python
# WRONG: 10 API calls for 10 symbols
for symbol in symbols:
    await coingecko.get_current(symbol)  # ← Hits rate limit

# RIGHT: 1 API call for all symbols
oracle.set_symbols(symbols)
prices = await oracle.fetch_batch()  # Single call: 4 coins/min = 10-30 req/min budget
```

**Rate Limit Guidance:**
- CoinGecko free tier: ~10-30 requests/minute
- 1 call every 15 seconds = 4 calls/min (safe)
- Implement exponential backoff on 429 responses
- Consider paid tier ($129/mo) for production

#### 3c. Defensive Parsing (Polymarket Decimal Crashes)
**Problem:** `Decimal("")` throws `InvalidOperation`, crashes whole system.
**Solution:** Defensive parsing for all external data.

```python
from decimal import Decimal, InvalidOperation

def safe_decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    """Safe conversion from external APIs."""
    if value is None or value == "":
        return default
    try:
        str_val = str(value).strip()
        if str_val.lower() in ("nan", "inf", "-inf"):
            return default
        return Decimal(str_val)
    except (InvalidOperation, ValueError, TypeError):
        return default

# Use everywhere external data enters system
price = safe_decimal(api_response["price"])
```

**Edge Cases to Handle:**
- `None` values (incomplete data)
- Empty strings `""`
- Special values: `"NaN"`, `"Infinity"`, `"-Infinity"`
- Malformed JSON
- Type mismatches (int vs string)

---

### 4. Error Handling Pattern for Live Trading

**Pattern (from ADAPTER_CONVENTIONS.md):**

For order placement, **always return an object with status**, never raise exceptions.

```python
async def place_order(self, market: Market, side: str, size: Decimal) -> Order:
    """Place order on Polymarket."""
    try:
        response = await self._clob_client.create_and_post_order(
            token_id=market.token_id,
            price=market.mid_price,
            size=size,
            side=side
        )
        return Order(
            id=response["id"],
            market_id=market.id,
            status=OrderStatus.OPEN,
            filled=Decimal("0")
        )
    except Exception as e:
        logger.error("order_failed",
                    market_id=market.id,
                    error=str(e),
                    size=size)
        return Order(
            id=None,
            market_id=market.id,
            status=OrderStatus.REJECTED,
            error_message=str(e)
        )

# Caller checks status
order = await executor.place_order(market, "yes", Decimal("10"))
if order.status == OrderStatus.REJECTED:
    logger.warning("trade_rejected", reason=order.error_message)
    # Handle gracefully - may retry, skip, or alert
```

**Why This Pattern Works:**
1. Explicit failure handling (no silent crashes)
2. All errors logged with context for debugging
3. One adapter failure doesn't crash entire system
4. Consistent pattern everywhere (predictable behavior)

---

### 5. Symbol Format Validation (Format Doubling Bug)

**Problem (from paper trading):** `"BTCUSDT"` passed to adapter → adapter adds `"USDT"` → `"BTCUSDTUSDT"`

**Solution:** Canonical format discipline.

```python
from pm_arb.core.validators import SymbolValidator

# ALWAYS use bare format
symbols = ["BTC", "ETH"]  # NOT ["BTCUSDT", "ETHUSDT"]

# Validate at entry points
symbols = SymbolValidator.validate_bare_symbols(symbols)

# Adapter transforms internally
def _symbol_to_pair(symbol: str) -> str:
    """Private transform - never called twice."""
    return f"{symbol}USDT"  # "BTC" → "BTCUSDT"
```

**Format Convention:**
- **External format:** Bare symbols `"BTC"`, `"ETH"` (human readable)
- **API format:** Platform specific `"BTCUSDT"` (Binance), `"bitcoin"` (CoinGecko)
- **Validation:** Reject pre-suffixed input at entry points

**Prevention Checklist:**
- [ ] Document canonical format in adapter docstrings
- [ ] Validate at boundaries (reject pre-suffixed)
- [ ] Test complete transformation chain (not just unit tests)

---

### 6. Live Execution Architecture Decision

**Decision (from execution-infrastructure plan):**

Create `LiveExecutorAgent` that mirrors `PaperExecutorAgent` interface:

```python
class LiveExecutorAgent(BaseAgent):
    """Execute trades on Polymarket with real capital."""

    def __init__(
        self,
        redis_url: str,
        credentials: PolymarketCredentials,
        polymarket: PolymarketAdapter,
        initial_bankroll: Decimal = Decimal("200"),
        max_trade_size: Decimal = Decimal("20"),
    ):
        super().__init__(redis_url)
        self._credentials = credentials
        self._polymarket = polymarket
        self._bankroll = initial_bankroll
        self._max_trade_size = max_trade_size

    async def execute_opportunity(self, opp: Opportunity) -> ExecutionResult:
        """Execute an arbitrage opportunity."""
        # Risk Guardian has already validated position limits
        # Just execute the trade
        order = await self._polymarket.place_order(
            market=opp.market,
            side=opp.side,
            size=min(opp.size, self._max_trade_size)
        )

        if order.status == OrderStatus.REJECTED:
            # Log and emit failure event
            logger.error("execution_failed", opportunity_id=opp.id)
            return ExecutionResult(success=False, reason=order.error_message)

        # Persist position
        await self._repository.create_position(order)
        return ExecutionResult(success=True, order_id=order.id)
```

**Key Design Decisions:**
1. **Executor swap via config:** Pilot switches between `PaperExecutorAgent` and `LiveExecutorAgent`
2. **Risk Guardian first:** Position size already validated by Risk Guardian
3. **Synchronous confirmation:** Wait for order ACK before returning (simpler than async)
4. **No auto-retry:** Log and alert on failure, manual review for MVP
5. **Existing position model:** Reuse postgres persistence from paper executor

---

### 7. Fee-Aware Edge Calculation (CRITICAL FOR PROFITABILITY)

**Decision (from live-trading-mvp-brainstorm):**

Modify opportunity scanner to calculate **net edge** before emitting opportunity.

**Current Implementation:**
```python
# opportunity_scanner.py
min_edge_pct: Decimal = Decimal("0.02")  # 2% minimum

# Simplified edge calculation (no fees considered):
edge = (oracle_price - market_price) / market_price
if edge >= min_edge_pct:
    emit_opportunity()
```

**Required Change (for live executor):**
```python
# Add market type detection and fee calculation
async def _should_emit_opportunity(self,
                                   opportunity: Opportunity) -> bool:
    """Check if net edge (after fees) exceeds minimum threshold."""

    market = opportunity.market
    gross_edge = opportunity.edge  # Already calculated

    # Fee schedule by market type
    fee_rate = self._get_taker_fee(market)  # → 0% or 1.56% for 15-min crypto
    expected_fee = fee_rate  # As % of trade

    net_edge = gross_edge - expected_fee

    if net_edge < self._min_edge_pct:
        logger.info("opportunity_filtered_by_fees",
                   market_id=market.id,
                   gross_edge=gross_edge,
                   fee_rate=fee_rate,
                   net_edge=net_edge)
        return False

    return True

def _get_taker_fee(self, market: Market) -> Decimal:
    """Return taker fee as decimal percentage."""
    if market.is_15min_crypto:
        # Formula: fee_rate = 0.0312 * (0.5 - abs(price - 0.5))
        price = market.mid_price / Decimal("100")  # Convert 50¢ to 0.50
        fee_rate = Decimal("0.0312") * (Decimal("0.5") - abs(price - Decimal("0.5")))
        return fee_rate
    return Decimal("0")  # Most markets are fee-free
```

**How to Identify 15-Min Crypto Markets:**
- Market question contains "BTC", "ETH", "SOL", "XRP"
- AND "15-minute" or "15 minute"
- Example: "Will BTC be above $50,000 at 3:15 PM UTC?"

**Impact on min_edge_pct Setting:**
- Keep `min_edge_pct = 2%` as your threshold
- But now it's **net edge**, not gross edge
- On 15-min crypto markets, you need gross edge ≥ 3.56% to clear the threshold

---

### 8. Monitoring, Alerting & Kill Switches

**Decision (from live-trading-mvp-brainstorm):**

Full alerting + manual kill switches for MVP phase.

**Alert Types to Implement:**

| Alert | Priority | Trigger | Action |
|-------|----------|---------|--------|
| Agent crash | Critical | Stale >2 min | Check logs, restart manually |
| Drawdown breach | Critical | Risk Guardian stops trading | Review P&L, assess market conditions |
| Large loss | High | Single trade loses >$20 | Review position sizing |
| Trade failure | High | Order rejected/API error | Check logs, verify auth/rate limits |
| Trade confirmation | Normal | Each executed trade | Log with P&L for tracking |
| Daily summary | Normal | End of day | Review daily P&L and position count |

**Implementation Pattern:**
```python
# Create AlertService wrapping Pushover (already configured)
class AlertService:
    async def send_critical(self, title: str, message: str):
        """Send critical alert (agent crash, drawdown)."""
        await self._pushover.notify(
            title=title,
            message=message,
            priority=2  # HIGH
        )

    async def send_trade_confirmation(self, trade: Trade):
        """Send normal alert with trade details."""
        await self._pushover.notify(
            title=f"Trade: {trade.market.short_name}",
            message=f"Executed {trade.side} @ {trade.price} | P&L: ${trade.pnl}",
            priority=0  # NORMAL
        )

# Integrate with agents
class LiveExecutorAgent:
    async def execute_opportunity(self, opp: Opportunity):
        order = await self._polymarket.place_order(...)
        if order.status == OrderStatus.REJECTED:
            await self._alerter.send_critical(
                "Trade Execution Failed",
                f"Market: {opp.market.id}\nError: {order.error_message}"
            )
            return

        await self._alerter.send_trade_confirmation(order)
```

**Kill Switch Implementation:**
1. **CLI command:** `pm-arb stop` (graceful shutdown)
2. **Env var:** Set `PAPER_TRADING=true` (instant switch to paper mode)
3. **Signal handling:** Ctrl+C on pilot process (existing)

**Rollback Playbook:**

| Scenario | Detection | Action |
|----------|-----------|--------|
| Bug in executor | Unexpected trades/positions | 1) `pm-arb stop` 2) Set `PAPER_TRADING=true` 3) Cancel orders in Polymarket UI 4) Investigate logs |
| Risk Guardian failure | Position exceeds limits | 1) Kill pilot 2) Verify positions in UI 3) Manually close excess 4) Root cause |
| API failure | Repeated order rejections | 1) Check logs for 429/auth errors 2) Verify credentials 3) Re-auth if needed 4) Retry |
| Unprofitable | Sustained losses | 1) Lower `initial_bankroll` 2) Switch to paper mode 3) Analyze performance 4) Adapt |

---

### 9. Open Questions Remaining

From the brainstorm—these need investigation before full implementation:

1. **Token ID Mapping:** How to get correct `token_id` for order placement from market data?
   - Polymarket API returns this in market details—verify endpoint

2. **Credential Generation:** Best practice for generating L1/L2 credentials?
   - Currently: Store in .env, load at runtime
   - Future: Consider secret manager (AWS Secrets, Vault)

3. **15-Min Market Detection:** Reliable way to identify fee-bearing markets?
   - Current approach: Parse question string for "15-minute" + crypto symbols
   - Better: Ask Polymarket API if market has taker fees

---

### 10. Risk Posture for MVP

**Decision (from brainstorm):**

- **Total capital:** $200-500 (configurable)
- **Max per trade:** $10-20 (hard cap during validation)
- **Position limits:** Existing Risk Guardian rules (max position, drawdown stop)
- **Confidence threshold:** Only trade when net edge ≥ 2%
- **Manual intervention:** Manual kill switch, no auto-recovery

**Rationale:**
- $10-20 per trade = LOW absolute risk even if something goes wrong
- Fast feedback on thesis validation
- Order lifecycle polish can be added once thesis is proven
- Risk Guardian provides automated circuit breakers
- Manual stop is backup safety mechanism

---

## Summary of Gotchas

| Gotcha | Impact | Prevention |
|--------|--------|-----------|
| **15-min crypto fees will kill your edge** | Strategy unprofitable on major market type | Calculate net edge = gross - fees before trading |
| **Decimal parsing crashes on None/empty** | System crash on bad API data | Use defensive parsing for all external inputs |
| **Single provider blocks (geo, rate limit)** | Complete system failure | Multi-provider fallback from day one |
| **Symbol format doubled (BTCUSDTUSDT)** | 404 errors on all API calls | Enforce bare format, validate at boundaries |
| **Async event loop conflicts** | RuntimeError in Streamlit | Use sync DB drivers or separate concerns |
| **Private key exposure in logs** | Security breach | Implement __str__() masking, validate format |
| **No testnet on Polymarket** | Can't fully test before mainnet | Accept small-stake test trades on mainnet |
| **Execution needs wallet signing** | API keys alone won't work | py-clob-client handles this correctly |

---

## Implementation Checklist for Live Executor

Based on all learnings above, here's your launch checklist:

### Authentication & Credentials
- [ ] Load Polymarket credentials from environment
- [ ] Validate private key format (0x + 64 hex chars)
- [ ] Test credentials by connecting to CLOB client
- [ ] Mask secrets in logging (implement `__str__()`)

### API Integration
- [ ] Implement multi-provider oracle (Binance + CoinGecko fallback)
- [ ] Add defensive parsing for all Decimal fields
- [ ] Batch CoinGecko API calls (all symbols in one request)
- [ ] Implement exponential backoff on 429 responses

### Fee-Aware Edge Calculation
- [ ] Add `_get_taker_fee()` to opportunity scanner
- [ ] Calculate net_edge = gross_edge - fee_rate
- [ ] Detect 15-min crypto markets (parse question)
- [ ] Only emit opportunities if net_edge ≥ 2%

### Order Execution
- [ ] Create `LiveExecutorAgent` (mirrors `PaperExecutorAgent`)
- [ ] Implement error handling pattern (return Order with status)
- [ ] Respect Risk Guardian position limits (no double-validation)
- [ ] Persist fills to postgres (reuse paper executor pattern)

### Monitoring & Safety
- [ ] Create AlertService (wrap Pushover)
- [ ] Alert on trade execution with P&L
- [ ] Alert on critical failures (agent crash, drawdown)
- [ ] Implement kill switch: CLI command `pm-arb stop`
- [ ] Implement emergency brake: `PAPER_TRADING=true` env var

### Testing
- [ ] Unit tests for SafeDecimal parsing
- [ ] Unit tests for fee calculation (all market types)
- [ ] Mock tests for order placement (success + failure)
- [ ] Integration tests with mocked Polymarket API
- [ ] Manual smoke test with $10 trades on mainnet

### Launch
- [ ] Set `initial_bankroll = $200` (conservative)
- [ ] Set `max_trade_size = $20` (hard cap)
- [ ] Set `min_edge_pct = 2%` (filters marginal opportunities)
- [ ] Start monitoring alerts closely
- [ ] Be ready to `pm-arb stop` if issues arise

---

## Key Files to Review

These are the source documents that informed these learnings:

1. **Bug Prevention & Patterns:**
   - `/Users/robstover/Development/personal/pm-arbitrage/docs/BUG_FIXES_AND_PREVENTION.md` (2811 lines)
   - `/Users/robstover/Development/personal/pm-arbitrage/docs/QUICK_FIX_REFERENCE.md`
   - `/Users/robstover/Development/personal/pm-arbitrage/docs/solutions/integration-issues/paper-trading-pilot-api-integration-fixes.md`

2. **Execution Infrastructure Plan:**
   - `/Users/robstover/Development/personal/pm-arbitrage/docs/plans/2026-02-02-execution-infrastructure.md` (44KB)

3. **Live Trading Strategy:**
   - `/Users/robstover/Development/personal/pm-arbitrage/docs/brainstorms/2026-02-03-live-trading-mvp-brainstorm.md`

4. **Adapter Conventions:**
   - `/Users/robstover/Development/personal/pm-arbitrage/docs/ADAPTER_CONVENTIONS.md`

5. **Opportunity Scanner Implementation:**
   - `/Users/robstover/Development/personal/pm-arbitrage/src/pm_arb/agents/opportunity_scanner.py`

---

## Next Steps

1. **Review fee implications** - Revisit your target markets given 15-min crypto fees
2. **Implement fee-aware edge calculation** in opportunity_scanner.py
3. **Run through execution infrastructure plan** task-by-task for LiveExecutor implementation
4. **Test on mainnet with small stakes** ($10-20 trades) before scaling
5. **Set up comprehensive alerting** before going live
6. **Have rollback playbook ready** (keep `.env` and kill switch accessible)

This live executor will require real capital. Everything in this document comes from hard lessons learned in the paper trading pilot. Take these seriously.

**Key principle:** External systems are unreliable. Assume they'll fail, return garbage, block you, or rate-limit you. Design defensively.

