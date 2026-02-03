# Dashboard is GUI-Only - No Agent Accessibility

---
status: pending
priority: p2
issue_id: 008
tags: [code-review, agent-native, architecture]
dependencies: []
---

## Problem Statement

The Streamlit dashboard renders all data directly to GUI widgets with no API endpoints exposing the same data. External AI agents cannot observe portfolio state, risk metrics, or strategy performance without scraping the web interface.

**Why it matters:** In an agent-native architecture, any action a human can take, an agent should also be able to take. This principle is violated for 9 of 12 dashboard capabilities.

## Findings

**Source:** agent-native-reviewer

**Location:** `src/pm_arb/dashboard/app.py:76-511`

**Evidence:**
```python
# Example: Portfolio data consumed by Streamlit only
def render_overview() -> None:
    portfolio = get_mock_portfolio()  # Data is consumed by Streamlit only
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric(label="Total Capital", ...)  # Human-only output
```

**Capability Gap Analysis:**

| UI Action | Agent/CLI Equivalent | Status |
|-----------|---------------------|--------|
| View portfolio | None | ORPHAN |
| View strategies | None | ORPHAN |
| View trades | `cli.py report --json` | PARTIAL |
| View risk | None | ORPHAN |
| HALT button | None | ORPHAN |
| Query prices | None | ORPHAN |
| Get health | `pilot.get_health()` (internal) | PARTIAL |
| Start pilot | `cli.py pilot` | OK |
| Generate report | `cli.py report` | OK |

## Proposed Solutions

### Option A: Add REST API Module (Recommended)
- **Description:** Create FastAPI endpoints exposing dashboard data
- **Pros:** Full API parity with dashboard
- **Cons:** Adds maintenance surface
- **Effort:** Medium
- **Risk:** Low

```python
# New: src/pm_arb/api/routes.py
@app.get("/api/portfolio")
async def get_portfolio() -> dict:
    return get_mock_portfolio()

@app.get("/api/risk")
async def get_risk_state() -> dict:
    return get_mock_risk_state()

@app.post("/api/system/halt")
async def halt_all() -> dict:
    await bus.publish("system.commands", {"command": "HALT_ALL"})
    return {"status": "halted"}
```

### Option B: Extend CLI with More Commands
- **Description:** Add `pm-arb status`, `pm-arb price`, `pm-arb halt` commands
- **Pros:** No new service to run
- **Cons:** CLI is less flexible than API for automation
- **Effort:** Small
- **Risk:** None

### Option C: Add JSON Output to Dashboard
- **Description:** Add `?format=json` query param to Streamlit pages
- **Pros:** Works with existing dashboard
- **Cons:** Streamlit doesn't support this naturally
- **Effort:** Medium
- **Risk:** Medium (hacky)

## Recommended Action

**DEFERRED - Separate PR**

Rationale: This is a feature enhancement that requires architectural decisions:
- REST API vs GraphQL vs gRPC
- Separate service or integrated with dashboard
- Authentication for API endpoints

For paper trading pilot, the Streamlit dashboard is sufficient for human monitoring.
When implementing agent-native features (Sprint 5+), implement Option A (REST API).

This deserves its own design discussion and sprint, not a quick fix.

## Technical Details

**Affected Files:**
- `src/pm_arb/dashboard/app.py`
- `src/pm_arb/cli.py`

**Components:**
- Dashboard
- CLI
- Agent accessibility layer

**Priority Endpoints:**
1. `GET /api/health` - Pilot health status
2. `GET /api/portfolio` - Current portfolio state
3. `GET /api/risk` - Risk metrics
4. `POST /api/system/halt` - Emergency halt

## Acceptance Criteria

- [ ] All dashboard data accessible via API or CLI
- [ ] HALT command executable via CLI/API
- [ ] Health status queryable programmatically
- [ ] Tests verify API endpoints

## Work Log

| Date | Action | Notes |
|------|--------|-------|
| 2026-02-03 | Created | Identified during code review of pilot bug fixes |
| 2026-02-03 | Deferred | Larger scope, deserves own sprint; acceptable for paper trading |

## Resources

- PR: Paper trading pilot bug fixes
- Agent-native architecture principles
