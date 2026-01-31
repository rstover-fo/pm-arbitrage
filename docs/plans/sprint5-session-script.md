# Sprint 5 Session Script

Copy/paste this to start a new session:

---

```
/superpowers:executing-plans

Execute Sprint 5 from docs/plans/2026-01-31-sprint5-strategy-capital-allocator.md for pm-arbitrage

## Context
- Sprint 4 is complete (commit 772ce12) - Risk Guardian + Paper Executor working
- All 59 tests passing, linting/mypy clean

## Sprint 5 Goal
Build Strategy Agent framework with Oracle Sniper implementation, and Capital Allocator with tournament-style scoring.

## Tasks (7 total)
- Task 5.1: Strategy Agent base class
- Task 5.2: Oracle Sniper strategy implementation
- Task 5.3: Capital Allocator agent with tournament scoring
- Task 5.4: StrategyAllocation model
- Task 5.5: Paper Executor P&L tracking
- Task 5.6: Sprint 5 Integration Test
- Task 5.7: Sprint 5 Final Commit

## Instructions
1. Follow the plan exactly - it has complete code, tests, and commit messages
2. TDD: write failing test first, then implementation
3. Commit after each task
4. Run full test suite before final commit
5. Request code review after completing all tasks

## Commands
- Activate venv: source .venv/bin/activate
- Run tests: pytest tests/ -v
- Lint: ruff check src/ tests/ && ruff format src/ tests/
- Type check: mypy src/

## Working Directory
/Users/robstover/Development/personal/pm-arbitrage

Start with Task 5.1.
```
