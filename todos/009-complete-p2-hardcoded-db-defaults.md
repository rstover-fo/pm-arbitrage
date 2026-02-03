# Hardcoded Default Database Credentials in Config

---
status: complete
priority: p2
issue_id: 009
tags: [code-review, security, configuration]
dependencies: []
---

## Problem Statement

Default database credentials are hardcoded in the Settings class. If `.env` file is missing or misconfigured, the application silently uses these defaults, potentially connecting to an unintended database or exposing credentials in version control.

**Why it matters:** Hardcoded credentials are a security anti-pattern. Silent fallback to defaults can cause data to be written to wrong databases.

## Findings

**Source:** security-sentinel

**Location:** `src/pm_arb/core/config.py:16-17`

**Evidence:**
```python
class Settings(BaseSettings):
    redis_url: str = "redis://localhost:6379"
    database_url: str = "postgresql://pm_arb:pm_arb@localhost:5432/pm_arb"
```

**Risk Scenario:**
- Developer deploys to staging but forgets `.env`
- App silently connects to localhost database (which may exist)
- Production data mixed with staging, or trades lost
- Credentials visible in git history

## Proposed Solutions

### Option A: Remove Defaults, Require Environment Variables (Recommended)
- **Description:** Remove default values and validate on startup
- **Pros:** Fails fast if not configured, no credential exposure
- **Cons:** Requires explicit config even for local dev
- **Effort:** Small
- **Risk:** Low

```python
class Settings(BaseSettings):
    redis_url: str  # Required - set via REDIS_URL
    database_url: str  # Required - set via DATABASE_URL

    @field_validator('database_url', 'redis_url')
    def not_empty(cls, v):
        if not v:
            raise ValueError("Required configuration not set")
        return v
```

### Option B: Use Placeholder That Will Fail
- **Description:** Use placeholder values that will fail connection
- **Pros:** Obvious failure if not configured
- **Cons:** Error message less clear than validation error
- **Effort:** Small
- **Risk:** Low

```python
database_url: str = "postgresql://CONFIGURE_ME:CONFIGURE_ME@localhost/CONFIGURE_ME"
```

### Option C: Keep Defaults for Local Dev Only
- **Description:** Document that defaults are for local development only
- **Pros:** Convenient for developers
- **Cons:** Still a security risk if deployed accidentally
- **Effort:** None
- **Risk:** Medium

## Recommended Action

[To be filled during triage]

## Technical Details

**Affected Files:**
- `src/pm_arb/core/config.py`

**Components:**
- Configuration management
- Environment setup

## Acceptance Criteria

- [ ] No default database credentials in code
- [ ] Application fails with clear error if DATABASE_URL not set
- [ ] Documentation updated with required environment variables
- [ ] `.env.example` shows required vars without real credentials

## Work Log

| Date | Action | Notes |
|------|--------|-------|
| 2026-02-03 | Created | Identified during code review of pilot bug fixes |

## Resources

- PR: Paper trading pilot bug fixes
- OWASP: A05:2021 Security Misconfiguration
