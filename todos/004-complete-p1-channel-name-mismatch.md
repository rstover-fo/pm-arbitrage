# Oracle Channel Name Mismatch Breaks Data Flow

---
status: pending
priority: p1
issue_id: 004
tags: [code-review, architecture, data-flow, bug]
dependencies: []
---

## Problem Statement

The pilot orchestrator subscribes to `oracle.coingecko.prices` channel, but the OracleAgent publishes to `oracle.coingecko.{SYMBOL}` (e.g., `oracle.coingecko.BTC`). If using exact channel matching, the OpportunityScannerAgent may never receive oracle data.

**Why it matters:** Without oracle data, the arbitrage detection system cannot calculate price discrepancies, making the entire pilot non-functional.

## Findings

**Source:** architecture-strategist

**Location:** `src/pm_arb/pilot.py:98`, `src/pm_arb/agents/oracle_agent.py:81-82`

**Evidence:**
```python
# pilot.py:98 - Subscribes to aggregate channel
oracle_channels = ["oracle.coingecko.prices"]

# oracle_agent.py:81-82 - Publishes per-symbol
await self.publish(
    f"oracle.{data.source}.{data.symbol}",  # e.g., oracle.coingecko.BTC
    ...
)
```

**Data Flow Break:**
- OpportunityScannerAgent subscribes to `oracle.coingecko.prices`
- OracleAgent publishes to `oracle.coingecko.BTC`, `oracle.coingecko.ETH`
- If Redis subscription is exact match, scanner never receives data
- No arbitrage opportunities detected, pilot appears to do nothing

**Note:** This may work if using prefix matching (`oracle.*`), but the channel name is misleading and should match the actual publication pattern.

## Proposed Solutions

### Option A: Fix Channel Names to Match Publication (Recommended)
- **Description:** Change pilot.py to subscribe to actual published channels
- **Pros:** Explicit, matches what's published, easy to understand
- **Cons:** Hardcodes symbol list in two places
- **Effort:** Small
- **Risk:** Low

```python
# pilot.py
symbols = ["BTC", "ETH"]
oracle_channels = [f"oracle.coingecko.{sym}" for sym in symbols]
```

### Option B: Add Wildcard/Pattern Subscription
- **Description:** Implement pattern subscription in BaseAgent (`oracle.coingecko.*`)
- **Pros:** More flexible, handles dynamic symbols
- **Cons:** Redis Streams don't support patterns, needs implementation
- **Effort:** Medium
- **Risk:** Low

### Option C: Publish to Aggregate Channel
- **Description:** Have OracleAgent publish to both per-symbol AND aggregate channel
- **Pros:** Supports both use cases
- **Cons:** Dual publication adds complexity
- **Effort:** Small
- **Risk:** Low

## Recommended Action

[To be filled during triage]

## Technical Details

**Affected Files:**
- `src/pm_arb/pilot.py`
- `src/pm_arb/agents/oracle_agent.py`
- `src/pm_arb/agents/opportunity_scanner.py`

**Components:**
- Pilot orchestrator
- Oracle agent
- Opportunity scanner

**Design Doc Reference:**
- `docs/plans/2026-01-30-arbitrage-bot-design.md` specifies `oracle.{type}.{symbol}` convention

## Acceptance Criteria

- [ ] Channel names in pilot match what OracleAgent publishes
- [ ] OpportunityScannerAgent receives oracle data
- [ ] Integration test verifies data flow

## Work Log

| Date | Action | Notes |
|------|--------|-------|
| 2026-02-03 | Created | Identified during code review of pilot bug fixes |

## Resources

- PR: Paper trading pilot bug fixes
- Design doc: Arbitrage bot design (channel conventions)
