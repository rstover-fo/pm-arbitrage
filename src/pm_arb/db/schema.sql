-- Paper trades table for pilot persistence

CREATE TABLE IF NOT EXISTS paper_trades (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Opportunity context
    opportunity_id TEXT NOT NULL,
    opportunity_type TEXT NOT NULL,
    market_id TEXT NOT NULL,
    venue TEXT NOT NULL,

    -- Trade details
    side TEXT NOT NULL,
    outcome TEXT NOT NULL,
    quantity DECIMAL NOT NULL,
    price DECIMAL NOT NULL,
    fees DECIMAL NOT NULL DEFAULT 0,
    expected_edge DECIMAL NOT NULL,

    -- Risk context
    strategy_id TEXT,
    risk_approved BOOLEAN NOT NULL DEFAULT true,
    risk_rejection_reason TEXT,

    -- Simulated result
    status TEXT NOT NULL DEFAULT 'open',
    exit_price DECIMAL,
    realized_pnl DECIMAL,
    resolved_at TIMESTAMPTZ
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_paper_trades_created ON paper_trades(created_at);
CREATE INDEX IF NOT EXISTS idx_paper_trades_market ON paper_trades(market_id);
CREATE INDEX IF NOT EXISTS idx_paper_trades_status ON paper_trades(status);
CREATE INDEX IF NOT EXISTS idx_paper_trades_opportunity_type ON paper_trades(opportunity_type);

-- Prevent duplicate trades from same opportunity (race condition protection)
CREATE UNIQUE INDEX IF NOT EXISTS idx_paper_trades_opportunity_unique
ON paper_trades(opportunity_id, market_id, side);
