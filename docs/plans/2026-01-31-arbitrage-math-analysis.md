# Arbitrage Detection: Mathematical Infrastructure Analysis

**Date:** 2026-01-31
**Status:** Research Complete
**Context:** Brainstorm session analyzing sophisticated arbitrage extraction methods from Polymarket research

---

## Executive Summary

A research paper documented $40M in arbitrage profits extracted from Polymarket over one year. This document analyzes whether the mathematical infrastructure described (marginal polytopes, Bregman projections, Frank-Wolfe algorithms) should be incorporated into our pm-arbitrage system.

**Conclusion:** The sophisticated math produced only 0.24% of extracted profits. Focus on infrastructure and simple checks first.

---

## Profit Breakdown by Strategy

| Category | Amount | % of Total | Complexity |
|----------|--------|------------|------------|
| Single condition (YES + NO ≠ $1) | $10.5M | 26.6% | Trivial |
| Market rebalancing (all outcomes ≠ $1) | $29.0M | 73.1% | Simple |
| Combinatorial (cross-market constraints) | $95K | 0.24% | High |
| **Total** | **$39.7M** | **100%** | |

**Key insight:** 99.76% of profits came from checking if prices sum to $1.00.

---

## The Mathematical Stack (For Reference)

### Part I: Marginal Polytope

The set of arbitrage-free prices forms a convex polytope M defined by:
- Valid outcome vectors Z = {φ(ω) : ω ∈ Ω}
- M = conv(Z) (convex hull of valid outcomes)
- Prices outside M → arbitrage exists

For n conditions, brute force requires checking 2^n outcomes. Integer programming compresses this to linear constraints: Z = {z ∈ {0,1}^I : A^T z ≥ b}

### Part II: Bregman Projection

Optimal arbitrage trade = Bregman projection of current prices θ onto M:
- μ* = argmin_{μ ∈ M} D(μ||θ)
- D is KL divergence for LMSR markets
- D(μ*||θ) = maximum extractable profit

### Part III: Frank-Wolfe Algorithm

Makes projection tractable for exponential outcome spaces:
1. Build active vertex set iteratively
2. Each iteration solves IP oracle: min_{z ∈ Z} ∇F(μ_t)·z
3. Converges in 50-150 iterations typically
4. Barrier variant handles gradient explosion near boundaries

### Part IV: Execution Reality

Mathematical correctness ≠ profitability:
- Non-atomic CLOB execution creates slippage risk
- First leg fills, price moves, second leg fills at worse price
- Minimum $0.05 profit threshold to cover execution risk
- Order book depth limits extractable profit
- Parallel submission targeting same block required for multi-leg

---

## Research Methodology Notes

**Scale analyzed:**
- 17,218 conditions examined
- 86 million transactions processed
- 305 US election markets → 46,360 possible pairs

**Dependency detection:**
- LLM (DeepSeek-R1-Distill-Qwen-32B) filtered pairs
- 81.45% accuracy on complex markets
- 1,576 dependent pairs found
- 13 manually verified as exploitable

**Execution success:**
- Single condition: 87% success rate
- Combinatorial: 45% success rate
- Failure causes: liquidity (48%), price movement (31%), competition (21%)

---

## Implications for pm-arbitrage

### What the data actually supports:

| Priority | Enhancement | Expected Impact | Effort |
|----------|-------------|-----------------|--------|
| **P0** | Single-condition check (YES + NO < 1) | High ($10.5M opportunity class) | Trivial |
| **P0** | Multi-outcome check (all prices < 1) | Highest ($29M opportunity class) | Low |
| **P0** | Order book depth streaming | Required for execution | Medium |
| **P0** | VWAP-based slippage estimation | Prevents losing trades | Medium |
| **P1** | Parallel leg execution | Same-block submission | Medium |
| **P1** | Minimum profit threshold ($0.05) | Filters unprofitable edges | Trivial |
| **P2** | LLM dependency detection | Extends Market Matcher | Medium |
| **P3** | Full Frank-Wolfe stack | 0.24% of opportunity | High |

### Simple checks to add to Opportunity Scanner:

```python
def check_single_condition_arb(self, market: Market) -> Opportunity | None:
    """Detect YES + NO < $1.00 (26.6% of extracted profits)."""
    total = market.yes_price + market.no_price
    if total < Decimal("0.98"):  # 2% threshold for fees/slippage
        return Opportunity(
            type=OpportunityType.MISPRICING,
            markets=[market.id],
            expected_edge=Decimal("1.0") - total,
            signal_strength=Decimal("0.95"),
        )
    return None

def check_multi_outcome_arb(self, market: MultiOutcomeMarket) -> Opportunity | None:
    """Detect all outcome prices < $1.00 (73.1% of extracted profits)."""
    total = sum(o.price for o in market.outcomes)
    if total < Decimal("0.98"):
        return Opportunity(
            type=OpportunityType.MISPRICING,
            markets=[market.id],
            expected_edge=Decimal("1.0") - total,
            signal_strength=Decimal("0.95"),
        )
    return None
```

### Enhanced Risk Guardian rules:

```python
class MinimumProfitRule:
    """Reject trades with insufficient expected profit."""
    threshold: Decimal = Decimal("0.05")

    def evaluate(self, request: TradeRequest, liquidity: Decimal) -> RiskDecision:
        expected_profit = request.expected_edge * min(request.amount, liquidity)
        if expected_profit < self.threshold:
            return RiskDecision(approved=False, reason="Below minimum profit threshold")
        return RiskDecision(approved=True, reason="Profit threshold met")

class SlippageGuard:
    """Reject trades where slippage exceeds edge."""

    def evaluate(self, request: TradeRequest, order_book: OrderBook) -> RiskDecision:
        vwap = order_book.calculate_vwap(request.amount)
        slippage = abs(vwap - request.max_price)
        if slippage > request.expected_edge * Decimal("0.5"):
            return RiskDecision(approved=False, reason="Slippage exceeds 50% of edge")
        return RiskDecision(approved=True, reason="Slippage acceptable")
```

---

## Future Roadmap (When Needed)

Trigger conditions for investing in sophisticated math:
1. Simple strategies saturate (competition erodes edge)
2. Targeting election cycles with 50+ correlated markets
3. Capital scales to $50K+ (justifies infrastructure investment)

### Phase 0: Constraint Primitives
- Condition, Implication, Exclusion data models
- Constraint graph representation

### Phase 1: Pairwise Detection
- LLM identifies logical dependencies
- Simple constraint violation check

### Phase 2: Constraint Network
- N-market constraint graphs
- Linear constraint matrix A^T z ≥ b

### Phase 3: Bregman Basics
- LMSR cost function implementation
- KL divergence calculation
- Direct projection for small markets

### Phase 4: Frank-Wolfe
- Iterative projection algorithm
- IP oracle integration (HiGHS or Gurobi)
- Barrier variant for numerical stability

### Phase 5: Production Pipeline
- Real-time constraint updates
- Integration with Opportunity Scanner
- Execution validation layer

---

## Resources

| Resource | Purpose | Link |
|----------|---------|------|
| Primary paper | Arbitrage extraction analysis | arXiv:2508.03474v1 |
| Theory foundation | IP for market making | arXiv:1606.02825v2 |
| Gurobi | Commercial IP solver | gurobi.com |
| HiGHS | Open-source IP solver | highs.dev |
| SCIP | Open-source IP solver | scipopt.org |
| Alchemy | Polygon node API | alchemy.com |

---

## Conclusion

The article's narrative ("sophisticated traders with math PhDs") obscures the actual data: **simple price-sum checks produced 99.76% of profits**.

For pm-arbitrage v1:
1. Add single-condition and multi-outcome checks (trivial)
2. Add order book depth analysis (medium)
3. Add execution safeguards (slippage, min profit)
4. Keep oracle-lag as primary strategy

The Frank-Wolfe stack is intellectually interesting but not ROI-positive at current scale. Revisit when capital exceeds $50K or when targeting complex event structures (elections, tournaments).

**The infrastructure won. Not the math.**
