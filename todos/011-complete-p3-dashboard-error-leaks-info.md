# Dashboard Displays Raw Database Errors to Users

---
status: complete
priority: p3
issue_id: 011
tags: [code-review, security, user-experience]
dependencies: []
---

## Problem Statement

Database errors are displayed directly to users in the dashboard, potentially exposing connection strings, query structures, or internal paths.

**Why it matters:** Information leakage can help attackers understand system architecture. Generic error messages are also better UX.

## Findings

**Source:** security-sentinel

**Location:** `src/pm_arb/dashboard/app.py:296-299`

**Evidence:**
```python
try:
    summary = asyncio.run(_get_pilot_summary())
except Exception as e:
    st.error(f"Database error: {e}")  # Raw exception exposed
    summary = _get_mock_pilot_summary()
```

**Potential Leak Examples:**
- Connection error: `"could not connect to postgresql://pm_arb:pm_arb@localhost:5432/pm_arb"`
- Query error: `"relation \"paper_trades\" does not exist"`
- Path error: `"[Errno 2] No such file or directory: '/Users/rob/..."`

## Proposed Solutions

### Option A: Log Internally, Display Generic Message (Recommended)
- **Description:** Log full error for debugging, show generic message to users
- **Pros:** Secure, good UX, debugging still possible
- **Cons:** Harder to debug in production without logs
- **Effort:** Small
- **Risk:** None

```python
except Exception as e:
    logger.error("pilot_summary_error", error=str(e), exc_info=True)
    st.error("Unable to load data. Please try again later.")
    summary = _get_mock_pilot_summary()
```

### Option B: Sanitize Error Messages
- **Description:** Filter sensitive info from error messages before display
- **Pros:** Preserves some useful context
- **Cons:** Complex, may miss edge cases
- **Effort:** Medium
- **Risk:** Medium

## Recommended Action

[To be filled during triage]

## Technical Details

**Affected Files:**
- `src/pm_arb/dashboard/app.py`

**Components:**
- Dashboard error handling

## Acceptance Criteria

- [ ] No raw exception messages displayed to users
- [ ] Errors logged with full context for debugging
- [ ] User sees friendly error message

## Work Log

| Date | Action | Notes |
|------|--------|-------|
| 2026-02-03 | Created | Identified during code review of pilot bug fixes |

## Resources

- PR: Paper trading pilot bug fixes
- OWASP: Information Exposure Through Error Messages
