# Dashboard Creates Fresh DB Pool Per Request

---
status: pending
priority: p1
issue_id: 003
tags: [code-review, performance, resource-leak, stability]
dependencies: []
---

## Problem Statement

The dashboard's `_get_pilot_summary()` function creates a new database connection pool for every request, despite a cached pool function existing but being unused. This causes resource exhaustion under load and adds 50-200ms latency per request.

**Why it matters:** Connection exhaustion will crash the entire trading system, including trade persistence. The unused cached pool indicates architectural confusion.

## Findings

**Source:** performance-oracle, architecture-strategist, data-integrity-guardian

**Location:** `src/pm_arb/dashboard/app.py:30-39, 361-388`

**Evidence:**
```python
# Lines 30-39: Cached pool DEFINED but never used
@st.cache_resource
def get_cached_db_pool():
    """Get cached database pool for dashboard."""
    from pm_arb.db import get_pool, init_db
    async def _get_pool():
        await init_db()
        return await get_pool()
    return asyncio.run(_get_pool())

# Lines 369-373: Fresh pool created EVERY request
async def _get_pilot_summary() -> dict:
    pool = await asyncpg.create_pool(
        settings.database_url,
        min_size=1,
        max_size=2,
    )
    # ...
```

**Resource Exhaustion Scenario:**
- User enables auto-refresh (5s interval)
- Each refresh creates pool with 1-2 connections
- Postgres default max_connections = 100
- After ~50 rapid refreshes, connections exhausted
- Trading system's DB writes fail, trades lost

## Proposed Solutions

### Option A: Use Cached Pool (Recommended)
- **Description:** Call `get_cached_db_pool()` instead of creating new pools
- **Pros:** Fixes issue with 1-line change, pool already exists
- **Cons:** Need to ensure pool works across Streamlit reruns
- **Effort:** Small
- **Risk:** Low

```python
async def _get_pilot_summary() -> dict:
    pool = get_cached_db_pool()  # Use cached version
    repo = PaperTradeRepository(pool)
    # ... no pool.close() needed
```

### Option B: Use Streamlit Connection
- **Description:** Use `st.connection("postgresql")` for native Streamlit handling
- **Pros:** Streamlit manages lifecycle automatically
- **Cons:** Requires changing to sync or Streamlit's async patterns
- **Effort:** Medium
- **Risk:** Low

### Option C: Synchronous Database Access
- **Description:** Use sync psycopg2 for dashboard (simple queries don't need async)
- **Pros:** Eliminates async complexity in sync context
- **Cons:** Adds new dependency, duplicates data access code
- **Effort:** Medium
- **Risk:** Low

## Recommended Action

[To be filled during triage]

## Technical Details

**Affected Files:**
- `src/pm_arb/dashboard/app.py`

**Components:**
- Streamlit dashboard
- Database connection management

**Dead Code:**
- `get_cached_db_pool()` function (lines 30-39) - defined but never called

## Acceptance Criteria

- [ ] Dashboard uses singleton connection pool
- [ ] Pool survives across Streamlit reruns
- [ ] No connection leaks under rapid refresh
- [ ] Dead code removed or used

## Work Log

| Date | Action | Notes |
|------|--------|-------|
| 2026-02-03 | Created | Identified during code review of pilot bug fixes |

## Resources

- PR: Paper trading pilot bug fixes
- Streamlit docs: Connection management
