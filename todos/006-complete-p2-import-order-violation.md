# Import Order Violation in Polymarket Adapter

---
status: complete
priority: p2
issue_id: 006
tags: [code-review, code-quality, python-conventions]
dependencies: []
---

## Problem Statement

The `_safe_decimal()` helper function is defined before imports in `polymarket.py`, violating Python conventions (PEP 8) and making the code harder to navigate.

**Why it matters:** Unconventional code structure makes the codebase harder to maintain and signals potential sloppiness that could indicate other issues.

## Findings

**Source:** pattern-recognition-specialist, architecture-strategist

**Location:** `src/pm_arb/adapters/venues/polymarket.py:1-28`

**Evidence:**
```python
"""Polymarket venue adapter."""

from decimal import Decimal, InvalidOperation
from typing import Any


def _safe_decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    """Safely convert value to Decimal, returning default if conversion fails."""
    if value is None or value == "":
        return default
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return default

import httpx  # <-- Import AFTER function definition!
import structlog
# ... more imports
```

**Python Convention (PEP 8):**
1. Module docstring
2. `__future__` imports
3. Standard library imports
4. Related third-party imports
5. Local application imports
6. Module-level code (functions, classes)

## Proposed Solutions

### Option A: Move Function After Imports (Recommended)
- **Description:** Reorder to follow PEP 8 conventions
- **Pros:** Follows conventions, easy to scan
- **Cons:** None
- **Effort:** Small
- **Risk:** None

### Option B: Extract to Utils Module
- **Description:** Move `_safe_decimal()` to `src/pm_arb/core/utils.py`
- **Pros:** Reusable, fixes import order, better organization
- **Cons:** One more file to maintain
- **Effort:** Small
- **Risk:** None

## Recommended Action

[To be filled during triage]

## Technical Details

**Affected Files:**
- `src/pm_arb/adapters/venues/polymarket.py`

**Components:**
- Polymarket adapter
- Code organization

## Acceptance Criteria

- [ ] Imports appear before function definitions
- [ ] Code passes `ruff check` without import order warnings
- [ ] Function still accessible where needed

## Work Log

| Date | Action | Notes |
|------|--------|-------|
| 2026-02-03 | Created | Identified during code review of pilot bug fixes |

## Resources

- PR: Paper trading pilot bug fixes
- PEP 8: https://peps.python.org/pep-0008/#imports
