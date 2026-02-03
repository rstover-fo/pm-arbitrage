# Silent Price Fallback Creates Phantom Arbitrage Signals

---
status: pending
priority: p1
issue_id: 001
tags: [code-review, data-integrity, trading-safety]
dependencies: []
---

## Problem Statement

The `_safe_decimal()` function in `polymarket.py` silently returns a default value (0.5) when price parsing fails, with no logging or indication of the error. In a trading system, this can create phantom arbitrage signals based on fabricated prices.

**Why it matters:** A trading system operating on corrupted data can execute trades based on non-existent opportunities, leading to financial losses.

## Findings

**Source:** data-integrity-guardian, security-sentinel

**Location:** `src/pm_arb/adapters/venues/polymarket.py:7-14, 136-153`

**Evidence:**
```python
def _safe_decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    if value is None or value == "":
        return default
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return default  # Silent fallback - no logging

# Usage with default of 0.5:
default_price = Decimal("0.5")
yes_price = _safe_decimal(prices[0], default_price) if prices else default_price
```

**Corruption Scenario:**
- Reality: BTC market YES = $0.92, NO = null (API error)
- System sees: YES = $0.92, NO = $0.50 (default applied)
- Result: Prices sum to 1.42, appears to be arbitrage opportunity
- Actual: NO at $0.50 doesn't exist, trade fails or fills at wrong price

## Proposed Solutions

### Option A: Log and Return None (Recommended)
- **Description:** Modify `_safe_decimal` to log errors and return `None` instead of a default. Update callers to skip markets with invalid prices.
- **Pros:** Full visibility, prevents trading on bad data
- **Cons:** Requires changes to downstream code to handle `None`
- **Effort:** Medium
- **Risk:** Low

### Option B: Log but Keep Default
- **Description:** Add logging to `_safe_decimal` but keep the default return value
- **Pros:** Minimal code changes, maintains backward compatibility
- **Cons:** Still trades on potentially wrong data
- **Effort:** Small
- **Risk:** Medium - may still cause bad trades

### Option C: Fail Fast
- **Description:** Let exceptions propagate and fail the market fetch
- **Pros:** Immediately obvious when API format changes
- **Cons:** One bad market breaks all market fetching
- **Effort:** Small
- **Risk:** High - reduced availability

## Recommended Action

[To be filled during triage]

## Technical Details

**Affected Files:**
- `src/pm_arb/adapters/venues/polymarket.py`
- `src/pm_arb/agents/opportunity_scanner.py` (downstream consumer)

**Components:**
- Polymarket adapter
- Opportunity detection pipeline

## Acceptance Criteria

- [ ] Price conversion failures are logged with context
- [ ] Markets with invalid prices are excluded from trading signals
- [ ] No silent data corruption in price pipeline
- [ ] Tests cover malformed API response scenarios

## Work Log

| Date | Action | Notes |
|------|--------|-------|
| 2026-02-03 | Created | Identified during code review of pilot bug fixes |

## Resources

- PR: Paper trading pilot bug fixes
- Similar: CoinGecko adapter has same issue at line 108
