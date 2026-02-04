# Sprint 9: Stabilization & Validation

**Date:** 2026-02-04
**Status:** Ready for Planning
**Author:** Rob

---

## What We're Building

A stable, fully-green test suite with environment isolation, plus a validated 30+ minute dry-run proving the entire pipeline works end-to-end with live data.

### Sprint Goals

1. **Fix all 4 failing tests** using environment isolation (mocks for external services)
2. **Run extended dry-run** (30+ min) with live Polymarket + oracle data
3. **Validate full pipeline**: Opportunity → Strategy → Risk → Paper trade

### Success Criteria

- [ ] All 180 tests pass (currently 176/180)
- [ ] Dry-run completes 30+ minutes without crashes
- [ ] Scanner detects at least 1 real arbitrage opportunity
- [ ] At least 1 paper trade executes end-to-end

---

## Why This Approach

**Environment Isolation** chosen over fixing real integrations or skipping tests because:

1. Tests should run reliably anywhere (CI, local, different networks)
2. Mocks provide fast feedback during development
3. Integration tests can still run separately with `pytest -m integration`
4. The dry-run catches integration issues mocks might miss

---

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Test strategy | Environment isolation | Reliable, fast, maintainable |
| SSL cert handling | Mock Binance in unit tests | Avoids network-dependent failures |
| Dry-run duration | 30+ minutes | Long enough to see real opportunities |
| Sprint scope | Tests + dry-run only | Stay focused, no feature creep |

---

## Failing Tests Analysis

| Test | Issue | Fix Strategy |
|------|-------|--------------|
| `test_live_data_streaming` | 0 oracle messages (SSL cert) | Mock Binance WebSocket response |
| `test_scanner_detects_live_opportunities` | 0 oracle prices | Mock oracle adapter in integration test |
| `test_end_to_end_paper_trading` | Risk rejected (expected profit $0.00) | Inject opportunity with sufficient edge |
| `test_orchestrator_starts_agents` | 0 agents created | Fix agent initialization timing |

---

## Dry-Run Validation Plan

1. Start all agents with live Polymarket data
2. Connect to real oracle sources (Binance, CoinGecko)
3. Monitor for 30+ minutes
4. Verify:
   - [ ] Price updates flowing (venue + oracle)
   - [ ] Opportunities detected and logged
   - [ ] Strategy generates trade requests
   - [ ] RiskGuardian approves/rejects appropriately
   - [ ] PaperExecutor records simulated trades

---

## Open Questions

1. Should integration tests be in a separate test directory or use pytest markers?
2. What's the minimum edge threshold for the dry-run to detect opportunities?
3. Do we need to adjust poll intervals to catch more opportunities?

---

## Out of Scope

- Live trading with real capital
- New venue integrations (Kalshi)
- Kill switch implementation
- Production deployment

---

## Next Steps

Run `/workflows:plan` to generate implementation tasks.
