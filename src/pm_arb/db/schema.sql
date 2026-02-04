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


-- Live trades table (extends paper_trades with order details)
CREATE TABLE IF NOT EXISTS live_trades (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Trade identifiers
    trade_id TEXT UNIQUE NOT NULL,
    request_id TEXT NOT NULL,

    -- Opportunity context
    opportunity_id TEXT NOT NULL,
    opportunity_type TEXT,
    market_id TEXT NOT NULL,
    venue TEXT NOT NULL,

    -- Order details
    token_id TEXT NOT NULL,
    side TEXT NOT NULL,
    outcome TEXT NOT NULL,

    -- Requested
    requested_amount DECIMAL(18,8) NOT NULL,
    max_price DECIMAL(18,8) NOT NULL,
    expected_edge DECIMAL(18,8),
    expected_fee DECIMAL(18,8),

    -- Actual
    filled_amount DECIMAL(18,8),
    fill_price DECIMAL(18,8),
    order_id TEXT,

    -- Status: pending, filled, partial, failed, cancelled, rejected
    status TEXT NOT NULL,
    error_message TEXT,

    -- Risk context
    strategy TEXT,
    risk_approved BOOLEAN NOT NULL DEFAULT true,
    risk_rejection_reason TEXT,

    -- Timestamps
    filled_at TIMESTAMPTZ
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_live_trades_market ON live_trades(market_id);
CREATE INDEX IF NOT EXISTS idx_live_trades_status ON live_trades(status);
CREATE INDEX IF NOT EXISTS idx_live_trades_created ON live_trades(created_at);

-- Prevent duplicate trades from same request
CREATE UNIQUE INDEX IF NOT EXISTS idx_live_trades_request_unique
ON live_trades(request_id);
