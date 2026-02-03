# nest_asyncio Workaround Masks Async Architecture Issues

---
status: pending
priority: p3
issue_id: 012
tags: [code-review, architecture, async, technical-debt]
dependencies: [003]
---

## Problem Statement

The dashboard uses `nest_asyncio.apply()` to allow `asyncio.run()` inside Streamlit's event loop. While functional, this is a workaround that can mask concurrency bugs and indicates architectural friction between sync dashboard and async backend.

**Why it matters:** Technical debt that can make debugging difficult if concurrency issues arise.

## Findings

**Source:** pattern-recognition-specialist, code-simplicity-reviewer

**Location:** `src/pm_arb/dashboard/app.py:6-9`

**Evidence:**
```python
import nest_asyncio

# Allow nested event loops (needed for asyncio.run() inside Streamlit)
nest_asyncio.apply()
```

**Usage Points:**
```python
# Line 39 - Pool creation
return asyncio.run(_get_pool())

# Line 296 - Data fetching
summary = asyncio.run(_get_pilot_summary())
```

**Issues:**
- Global state modification (patches event loop policy)
- Can mask race conditions by allowing nested loops
- Makes debugging async issues harder
- Indicates design mismatch

## Proposed Solutions

### Option A: Use Streamlit Native Async (Streamlit 1.18+)
- **Description:** Streamlit now supports async natively, remove nest_asyncio
- **Pros:** Clean, no workarounds, Streamlit-native
- **Cons:** Requires Streamlit version check
- **Effort:** Medium
- **Risk:** Low

### Option B: Use Synchronous Database Access
- **Description:** Use sync psycopg2 for dashboard queries
- **Pros:** No async complexity in sync context
- **Cons:** Adds dependency, duplicates patterns
- **Effort:** Medium
- **Risk:** Low

### Option C: Keep with Better Documentation
- **Description:** Document why it's needed and the limitations
- **Pros:** No code changes
- **Cons:** Technical debt remains
- **Effort:** Small
- **Risk:** None

## Recommended Action

**DEFERRED - Option C (Document and Keep)**

Rationale:
- nest_asyncio is functional and widely used for this exact use case
- The workaround is explicitly documented in the code (lines 6-9)
- No bugs have been observed from this pattern
- Streamlit's async support (Option A) requires investigation and testing

Technical debt acknowledged, but acceptable for paper trading pilot.
Revisit if async debugging issues arise or when upgrading Streamlit.

## Technical Details

**Affected Files:**
- `src/pm_arb/dashboard/app.py`

**Components:**
- Dashboard async handling

**Dependencies:**
- Related to #003 (pool management)

## Acceptance Criteria

- [ ] Dashboard works without nest_asyncio (or documents why it's needed)
- [ ] No masked concurrency issues

## Work Log

| Date | Action | Notes |
|------|--------|-------|
| 2026-02-03 | Created | Identified during code review of pilot bug fixes |
| 2026-02-03 | Deferred | Technical debt acknowledged; functional and documented |

## Resources

- PR: Paper trading pilot bug fixes
- Streamlit async docs
- nest_asyncio limitations
