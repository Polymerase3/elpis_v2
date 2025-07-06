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
-- 1. Create ASSET_CLASS if it doesn't already exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 
          FROM pg_type t 
          JOIN pg_namespace n ON n.oid = t.typnamespace 
         WHERE t.typname = 'asset_class'
           AND n.nspname = 'public'
    ) THEN
        CREATE TYPE asset_class AS ENUM (
            'FX',
            'EQUITY',
            'COMMODITY',
            'DEBT',
            'INDEX',
            'CRYPTOCURRENCY',
            'ALTERNATIVE'
        );
    END IF;
END
$$;

-- 2. Create INSTRUMENT_CLASS if it doesn't already exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
          FROM pg_type t 
          JOIN pg_namespace n ON n.oid = t.typnamespace 
         WHERE t.typname = 'instrument_class'
           AND n.nspname = 'public'
    ) THEN
        CREATE TYPE instrument_class AS ENUM (
            'Spot',
            'Swap',
            'Future',
            'FutureSpread',
            'Forward',
            'Cfg',           -- CFD
            'Bond',
            'Option',
            'OptionSpread',
            'Warrant',
            'SportsBetting'
        );
    END IF;
END
$$;

-- 3. Instruments table
CREATE TABLE IF NOT EXISTS instrument (
    id                       SERIAL            PRIMARY KEY NOT NULL,
    name_desc                TEXT,
    id_nautilus              TEXT              NOT NULL,  
    asset_class              ASSET_CLASS       NOT NULL,
    instrument_class         INSTRUMENT_CLASS  NOT NULL,
    raw_symbol               TEXT              NOT NULL,      -- venue‐specific ticker
    underlying_currency_id   TEXT              REFERENCES instrument(id),
    base_currency_id         TEXT              REFERENCES currency(id),
    quote_currency_id        TEXT              REFERENCES currency(id),
    settlement_currency_id   TEXT              REFERENCES currency(id),
    isin                     TEXT,
    exchange                 TEXT,
    option_kind              VARCHAR(4)        CHECK (option_kind IN ('CALL','PUT')),
    strike_price             NUMERIC,
    activation_ns            BIGINT,                          -- nanosecond timestamp
    expiration_ns            BIGINT,
    price_precision          INTEGER           NOT NULL,
    size_precision           INTEGER,
    price_increment          NUMERIC           NOT NULL,
    size_increment           NUMERIC,
    is_inverse               BOOLEAN           DEFAULT FALSE,
    multiplier               NUMERIC,
    lot_size                 NUMERIC,
    max_quantity             NUMERIC,
    min_quantity             NUMERIC,
    max_notional             NUMERIC,
    min_notional             NUMERIC,
    max_price                NUMERIC,
    min_price                NUMERIC,
    margin_init              NUMERIC           NOT NULL,
    margin_maint             NUMERIC           NOT NULL,
    maker_fee                NUMERIC,
    taker_fee                NUMERIC,
    tick_scheme_name         TEXT,
    info                     JSONB,
    -- binary options
    currency_id              TEXT REFERENCES currency(id),
    outcome                  TEXT,
    description              TEXT,

    -- the spread strategy (e.g. calendar, crack, etc.)
    strategy_type            TEXT,

    -- the derivation formula for the synthetic instrument
    formula                  TEXT,

    ts_event                 TIMESTAMPTZ       NOT NULL,
    ts_init                  TIMESTAMPTZ       NOT NULL,
    created_at               TIMESTAMPTZ       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at               TIMESTAMPTZ       NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 4. Indexes for performance
CREATE INDEX ON instrument(asset_class);
CREATE INDEX ON instrument(instrument_class);
CREATE INDEX ON instrument(raw_symbol);
CREATE INDEX ON instrument(expiration_ns);


-- 1. CurrencyType enum (unchanged)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
          FROM pg_type t
          JOIN pg_namespace n ON n.oid = t.typnamespace
         WHERE t.typname = 'currency_type'
           AND n.nspname = 'public'
    ) THEN
        CREATE TYPE currency_type AS ENUM (
            'FIAT',
            'CRYPTO'
        );
    END IF;
END
$$;

-- 2. Currency table (unchanged)
CREATE TABLE IF NOT EXISTS currency (
    code           TEXT            PRIMARY KEY,       -- e.g. 'USD', 'BTC'
    precision      SMALLINT        NOT NULL,          -- decimal precision (0–16)
    iso4217        INTEGER         NOT NULL,          -- ISO 4217 numeric code (or 0 for crypto)
    name           TEXT            NOT NULL,          -- full name, e.g. 'United States Dollar'
    currency_type  currency_type   NOT NULL           -- FIAT vs CRYPTO
);

-- 3. Pre-populate with your currencies (all precision = 6)

-- Fiat currencies
INSERT INTO currency (code, precision, iso4217, name, currency_type) VALUES
  ('AUD', 6, 36,  'Australian Dollar',       'FIAT'),
  ('BRL', 6, 986, 'Brazilian Real',          'FIAT'),
  ('CAD', 6, 124, 'Canadian Dollar',         'FIAT'),
  ('CHF', 6, 756, 'Swiss Franc',             'FIAT'),
  ('CNY', 6, 156, 'Chinese Yuan',            'FIAT'),
  ('CNH', 6, 156, 'Chinese Yuan (Offshore)', 'FIAT'),
  ('CZK', 6, 203, 'Czech Koruna',            'FIAT'),
  ('DKK', 6, 208, 'Danish Krone',            'FIAT'),
  ('EUR', 6, 978, 'Euro',                    'FIAT'),
  ('GBP', 6, 826, 'British Pound',           'FIAT'),
  ('HKD', 6, 344, 'Hong Kong Dollar',        'FIAT'),
  ('HUF', 6, 348, 'Hungarian Forint',        'FIAT'),
  ('ILS', 6, 376, 'Israeli Shekel',          'FIAT'),
  ('INR', 6, 356, 'Indian Rupee',            'FIAT'),
  ('JPY', 6, 392, 'Japanese Yen',            'FIAT'),
  ('KRW', 6, 410, 'South Korean Won',        'FIAT'),
  ('MXN', 6, 484, 'Mexican Peso',            'FIAT'),
  ('NOK', 6, 578, 'Norwegian Krone',         'FIAT'),
  ('NZD', 6, 554, 'New Zealand Dollar',      'FIAT'),
  ('PLN', 6, 985, 'Polish Złoty',            'FIAT'),
  ('RUB', 6, 643, 'Russian Ruble',           'FIAT'),
  ('SAR', 6, 682, 'Saudi Riyal',             'FIAT'),
  ('SEK', 6, 752, 'Swedish Krona',           'FIAT'),
  ('SGD', 6, 702, 'Singapore Dollar',        'FIAT'),
  ('THB', 6, 764, 'Thai Baht',               'FIAT'),
  ('TRY', 6, 949, 'Turkish Lira',            'FIAT'),
  ('USD', 6, 840, 'US Dollar',               'FIAT'),
  ('XAG', 6, 961, 'Silver (troy ounce)',     'FIAT'),
  ('XAU', 6, 959, 'Gold (troy ounce)',       'FIAT'),
  ('ZAR', 6, 710, 'South African Rand',      'FIAT')
ON CONFLICT (code) DO NOTHING;

-- Crypto currencies (precision = 8)
INSERT INTO currency (code, precision, iso4217, name, currency_type) VALUES
  ('1INCH',  8, 0, '1INCH',         'CRYPTO'),
  ('AAVE',   8, 0, 'AAVE',          'CRYPTO'),
  ('ACA',    8, 0, 'ACA',           'CRYPTO'),
  ('ADA',    8, 0, 'ADA',           'CRYPTO'),
  ('AVAX',   8, 0, 'AVAX',          'CRYPTO'),
  ('BCH',    8, 0, 'BCH',           'CRYPTO'),
  ('BTTC',   8, 0, 'BTTC',          'CRYPTO'),
  ('BNB',    8, 0, 'BNB',           'CRYPTO'),
  ('BRZ',    8, 0, 'BRZ',           'CRYPTO'),
  ('BSV',    8, 0, 'BSV',           'CRYPTO'),
  ('BTC',    8, 0, 'BTC',           'CRYPTO'),
  ('BUSD',   8, 0, 'BUSD',          'CRYPTO'),
  ('XBT',    8, 0, 'XBT',           'CRYPTO'),
  ('DASH',   8, 0, 'DASH',          'CRYPTO'),
  ('DOGE',   8, 0, 'DOGE',          'CRYPTO'),
  ('DOT',    8, 0, 'DOT',           'CRYPTO'),
  ('EOS',    8, 0, 'EOS',           'CRYPTO'),
  ('ETH',    8, 0, 'ETH',           'CRYPTO'),
  ('ETHW',   8, 0, 'ETHW',          'CRYPTO'),
  ('FDUSD',  8, 0, 'FDUSD',         'CRYPTO'),
  ('EZ',     8, 0, 'EZ',            'CRYPTO'),
  ('FTT',    8, 0, 'FTT',           'CRYPTO'),
  ('JOE',    8, 0, 'JOE',           'CRYPTO'),
  ('LINK',   8, 0, 'LINK',          'CRYPTO'),
  ('LTC',    8, 0, 'LTC',           'CRYPTO'),
  ('LUNA',   8, 0, 'LUNA',          'CRYPTO'),
  ('NBT',    8, 0, 'NBT',           'CRYPTO'),
  ('SOL',    8, 0, 'SOL',           'CRYPTO'),
  ('TRX',    8, 0, 'TRX',           'CRYPTO'),
  ('TRYB',   8, 0, 'TRYB',          'CRYPTO'),
  ('TUSD',   8, 0, 'TUSD',          'CRYPTO'),
  ('VTC',    8, 0, 'VTC',           'CRYPTO'),
  ('XLM',    8, 0, 'XLM',           'CRYPTO'),
  ('XMR',    8, 0, 'XMR',           'CRYPTO'),
  ('XRP',    8, 0, 'XRP',           'CRYPTO'),
  ('XTZ',    8, 0, 'XTZ',           'CRYPTO'),
  ('USDC',   8, 0, 'USDC',          'CRYPTO'),
  ('USDC.e', 8, 0, 'USDC.e',        'CRYPTO'),
  ('USDP',   8, 0, 'USDP',          'CRYPTO'),
  ('USDT',   8, 0, 'USDT',          'CRYPTO'),
  ('WSB',    8, 0, 'WSB',           'CRYPTO'),
  ('XEC',    8, 0, 'XEC',           'CRYPTO'),
  ('ZEC',    8, 0, 'ZEC',           'CRYPTO')
ON CONFLICT (code) DO NOTHING;

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
