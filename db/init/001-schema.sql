-- 001_schema.sql  — singular table names for consistency
-- Schemas: core, market, analytics, helper (unchanged)
-- Every table is **singular**, and PK columns simplified to just `id`.

\connect elpis

BEGIN;

CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;

CREATE SCHEMA IF NOT EXISTS core      AUTHORIZATION polymerase;
CREATE SCHEMA IF NOT EXISTS market    AUTHORIZATION polymerase;
CREATE SCHEMA IF NOT EXISTS analytics AUTHORIZATION polymerase;
CREATE SCHEMA IF NOT EXISTS helper    AUTHORIZATION polymerase;

ALTER ROLE polymerase SET search_path = analytics, market, core, public;

-- ---------------------------------------------------------------------------
-- Enum type: strategy_type_enum (unchanged)
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'strategy_type_enum') THEN
        CREATE TYPE strategy_type_enum AS ENUM ('bullish', 'bearish', 'both');
    END IF;
END$$;

-- ---------------------------------------------------------------------------
-- Core.lookup tables (singular)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS core.interval_code (
    id          SMALLINT PRIMARY KEY,
    label       VARCHAR(4)  NOT NULL UNIQUE,
    seconds     INTEGER     NOT NULL CHECK (seconds > 0),
    minutes     INTEGER     GENERATED ALWAYS AS (seconds / 60)    STORED,
    hours       INTEGER     GENERATED ALWAYS AS (seconds / 3600)  STORED,
    days        INTEGER     GENERATED ALWAYS AS (seconds / 86400) STORED,
    weeks       NUMERIC(5,2) GENERATED ALWAYS AS (ROUND(seconds / 604800.0, 2)) STORED,
    months      NUMERIC(5,2) GENERATED ALWAYS AS (ROUND(seconds / 2592000.0, 2)) STORED
);

INSERT INTO core.interval_code (id,label,seconds) VALUES
    (1,'1m',   60),
    (2,'5m',  300),
    (3,'15m', 900),
    (4,'1h', 3600),
    (5,'4h',14400),
    (6,'1d',86400),
    (7,'1w',604800),
    (8,'1mo',2592000)
ON CONFLICT DO NOTHING;

-- ---------------------------------------------------------------------------
-- Market schema (instrument, price)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS market.instrument (
    id SERIAL PRIMARY KEY,
    description VARCHAR(60),
    uic         INTEGER     NOT NULL,
    asset_type  VARCHAR(20) NOT NULL,
    symbol      VARCHAR(20) NOT NULL,
    currency    CHAR(3),
    exchange    VARCHAR(10),
    UNIQUE (uic, asset_type)
);

CREATE TABLE IF NOT EXISTS market.price (
    instrument_id INTEGER     NOT NULL,
    interval_id   SMALLINT    NOT NULL,
    time_price    TIMESTAMPTZ NOT NULL,

    price_open      NUMERIC(12,4),
    price_high      NUMERIC(12,4),
    price_low       NUMERIC(12,4),
    price_close     NUMERIC(12,4),
    price_interest  NUMERIC(12,4),

    price_close_ask NUMERIC(12,4),
    price_close_bid NUMERIC(12,4),
    price_high_ask  NUMERIC(12,4),
    price_high_bid  NUMERIC(12,4),
    price_low_ask   NUMERIC(12,4),
    price_low_bid   NUMERIC(12,4),
    price_open_ask  NUMERIC(12,4),
    price_open_bid  NUMERIC(12,4),

    volume          INTEGER,

    PRIMARY KEY (instrument_id, interval_id, time_price),
    FOREIGN KEY (instrument_id) REFERENCES market.instrument(id) ON DELETE CASCADE,
    FOREIGN KEY (interval_id)   REFERENCES core.interval_code(id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_price_instr_interval ON market.price (instrument_id, interval_id);
CREATE INDEX IF NOT EXISTS idx_price_time_desc      ON market.price (time_price DESC);

-- Create primary time dimension
SELECT public.create_hypertable('market.price', 'time_price', if_not_exists => TRUE);
-- Add a space dimension so each chunk is also partitioned by instrument_id
DO $$
BEGIN
    -- add_dimension is idempotent; skip if already present
    IF NOT EXISTS (
        SELECT 1 FROM timescaledb_information.dimensions
        WHERE hypertable_name = 'price'
          AND column_name = 'instrument_id'
    ) THEN
        PERFORM add_dimension('market.price', 'instrument_id', number_partitions => 32);
    END IF;
END$$;

-- ---------------------------------------------------------------------------
-- Analytics schema (strategy, analysis, parameter, result)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS analytics.strategy (
    id SERIAL PRIMARY KEY,
    name        VARCHAR(40) NOT NULL UNIQUE,
    description TEXT,
    type        strategy_type_enum NOT NULL
);

CREATE TABLE IF NOT EXISTS analytics.analysis (
    id SERIAL PRIMARY KEY,
    instrument_id INTEGER  NOT NULL REFERENCES market.instrument(id) ON DELETE RESTRICT,
    strategy_id   INTEGER  NOT NULL REFERENCES analytics.strategy(id) ON DELETE CASCADE,
    interval_id   SMALLINT NOT NULL REFERENCES core.interval_code(id) ON DELETE RESTRICT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    date_from     TIMESTAMPTZ NOT NULL,
    date_to       TIMESTAMPTZ NOT NULL,
    position_size NUMERIC(12,4) NOT NULL,
    leverage      NUMERIC(5,2)  NOT NULL,
    commission_p  NUMERIC(5,2)  NOT NULL,
    stop_loss_p   NUMERIC(5,2)  NOT NULL,
    total_return_p      NUMERIC(10,4) NOT NULL,
    annualized_return_p NUMERIC(10,4),
    cagr                NUMERIC(10,4),
    max_drawdown_p      NUMERIC(7,4)  NOT NULL,
    volatility_p        NUMERIC(7,4),
    downside_deviation  NUMERIC(7,4),
    sharpe_ratio        NUMERIC(10,4) NOT NULL,
    sortino_ratio       NUMERIC(10,4),
    calmar_ratio        NUMERIC(10,4),
    win_rate_p          NUMERIC(7,4)  NOT NULL,
    number_trades       INTEGER       NOT NULL,
    average_profit      NUMERIC(12,4) NOT NULL,
    profit_factor       NUMERIC(8,4)  NOT NULL,
    alpha               NUMERIC(8,4),
    beta                NUMERIC(8,4)
);

CREATE INDEX IF NOT EXISTS idx_analysis_instr_interval ON analytics.analysis (instrument_id, interval_id);
CREATE INDEX IF NOT EXISTS idx_analysis_instr_strategy  ON analytics.analysis (instrument_id, strategy_id);
CREATE INDEX IF NOT EXISTS idx_analysis_date_span  ON analytics.analysis (date_from, date_to) INCLUDE (instrument_id, strategy_id, total_return_p);

CREATE TABLE IF NOT EXISTS analytics.parameter (
    analysis_id    INTEGER     NOT NULL,
    strategy_id    INTEGER     NOT NULL,
    name           VARCHAR(40) NOT NULL,
    value          NUMERIC(15,6) NOT NULL,
    PRIMARY KEY (analysis_id, strategy_id, name),
    FOREIGN KEY (analysis_id) REFERENCES analytics.analysis(id)  ON DELETE CASCADE,
    FOREIGN KEY (strategy_id) REFERENCES analytics.strategy(id)  ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS analytics.result (
    analysis_id     INTEGER     NOT NULL REFERENCES analytics.analysis(id) ON DELETE CASCADE,
    timepoint       TIMESTAMPTZ NOT NULL,
    portfolio_value NUMERIC(15,6) NOT NULL,
    PRIMARY KEY (analysis_id, timepoint)
);

COMMIT;
