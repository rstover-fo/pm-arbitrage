# Inconsistent Error Handling Patterns Across Adapters

---
status: complete
priority: p3
issue_id: 010
tags: [code-review, code-quality, consistency]
dependencies: []
---

## Problem Statement

Error handling varies across adapters: some log and return None, some return rejected objects with error messages, some silently swallow errors. This inconsistency makes it hard to reason about failure modes and handle errors correctly in calling code.

**Why it matters:** Inconsistent error handling leads to bugs when developers make assumptions about what failures look like.

## Findings

**Source:** pattern-recognition-specialist

**Location:** Multiple adapter files

**Evidence:**

**Pattern A (CoinGecko):** Log error, silent return
```python
# coingecko.py:111-112
except httpx.HTTPError as e:
    logger.error("coingecko_batch_fetch_error", error=str(e))
    # No return statement - continues with stale cache
```

**Pattern B (Binance):** Log error, return None
```python
# crypto.py:77-79
except httpx.HTTPError as e:
    logger.error("binance_fetch_error", symbol=symbol, error=str(e))
    return None
```

**Pattern C (Polymarket orders):** Return rejected object with error
```python
# polymarket.py:307-320
except Exception as e:
    logger.error("order_placement_failed", error=str(e), token=token_id)
    return Order(..., status=OrderStatus.REJECTED, error_message=str(e))
```

**Pattern D (Order book):** Log error, return None
```python
# polymarket.py:198-200
except httpx.HTTPError as e:
    logger.error("order_book_fetch_error", market=market_id, error=str(e))
    return None
```

## Proposed Solutions

### Option A: Standardize on Result Type (Recommended)
- **Description:** Use explicit Result/Error types following `better-result` pattern from CLAUDE.md
- **Pros:** Explicit error handling, type-safe
- **Cons:** Requires refactoring existing code
- **Effort:** Large
- **Risk:** Medium

### Option B: Standardize on None + Logging
- **Description:** All errors log and return None, callers check for None
- **Pros:** Simple, consistent
- **Cons:** Loses error context at call site
- **Effort:** Small
- **Risk:** Low

### Option C: Standardize on Objects with Error State
- **Description:** Return objects with `.error` field populated on failure
- **Pros:** Error context preserved, consistent pattern
- **Cons:** Requires adding error field to all return types
- **Effort:** Medium
- **Risk:** Low

## Recommended Action

[To be filled during triage]

## Technical Details

**Affected Files:**
- `src/pm_arb/adapters/oracles/coingecko.py`
- `src/pm_arb/adapters/oracles/crypto.py`
- `src/pm_arb/adapters/venues/polymarket.py`

**Components:**
- All external adapters

## Acceptance Criteria

- [ ] Error handling pattern documented in CONTRIBUTING.md or similar
- [ ] All adapters follow consistent error handling
- [ ] Calling code can reliably detect and handle failures

## Work Log

| Date | Action | Notes |
|------|--------|-------|
| 2026-02-03 | Created | Identified during code review of pilot bug fixes |

## Resources

- PR: Paper trading pilot bug fixes
- CLAUDE.md: `better-result` pattern reference
