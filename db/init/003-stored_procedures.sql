-- 003_insert_analyses.sql — Bulk JSON import procedures rewritten for PostgreSQL
-- Place in db/init/ after schema and helper procs

\connect elpis

BEGIN;

SET search_path = helper, analytics, market, core, public;

-- 1. Bulk insert analyses, parameters, and results from a JSONB array
CREATE OR REPLACE FUNCTION helper.insert_analyses_bulk(p_json JSONB)
RETURNS VOID LANGUAGE plpgsql AS $$
DECLARE
    rec JSONB;
    analysis_id INT;
BEGIN
    FOR rec IN SELECT * FROM jsonb_array_elements(p_json) LOOP
        -- Insert analysis and return new ID
        INSERT INTO analytics.analysis (
            instrument_id, strategy_id, interval_id,
            created_at, updated_at,
            date_from, date_to,
            position_size, leverage,
            commission_p, stop_loss_p,
            total_return_p, annualized_return_p, cagr,
            max_drawdown_p, volatility_p, downside_deviation,
            sharpe_ratio, sortino_ratio, calmar_ratio,
            win_rate_p, number_trades, average_profit, profit_factor,
            alpha, beta
        ) VALUES (
            (rec->>'instrument_ID')::INT,
            (rec->>'strategy_ID')::INT,
            (rec->>'interval_code')::SMALLINT,
            (rec->>'created_at')::TIMESTAMPTZ,
            (rec->>'updated_at')::TIMESTAMPTZ,
            (rec->>'date_from')::TIMESTAMPTZ,
            (rec->>'date_to')::TIMESTAMPTZ,
            (rec->>'position_size')::NUMERIC,
            (rec->>'leverage')::NUMERIC,
            (rec->>'commision_p')::NUMERIC,
            (rec->>'stop_loss_p')::NUMERIC,
            (rec->>'total_return_p')::NUMERIC,
            (rec->>'annualized_return_p')::NUMERIC,
            (rec->>'CAGR')::NUMERIC,
            (rec->>'max_drawdown_p')::NUMERIC,
            (rec->>'volatility_p')::NUMERIC,
            (rec->>'downside_deviation')::NUMERIC,
            (rec->>'sharpe_ratio')::NUMERIC,
            (rec->>'sortino_ratio')::NUMERIC,
            (rec->>'calmar_ratio')::NUMERIC,
            (rec->>'win_rate_p')::NUMERIC,
            (rec->>'number_trades')::INT,
            (rec->>'average_profit')::NUMERIC,
            (rec->>'profit_factor')::NUMERIC,
            (rec->>'alpha')::NUMERIC,
            (rec->>'beta')::NUMERIC
        ) RETURNING id INTO analysis_id;

        -- Insert parameters array
        INSERT INTO analytics.parameter (analysis_id, strategy_id, name, value)
        SELECT
            analysis_id,
            (rec->>'strategy_ID')::INT,
            elem->>'parameter_name',
            (elem->>'parameter_value')::NUMERIC
        FROM jsonb_array_elements(rec->'parameter_names') AS a(elem);

        -- Insert results array
        INSERT INTO analytics.result (analysis_id, timepoint, portfolio_value)
        SELECT
            analysis_id,
            (elem->>'timepoint')::TIMESTAMPTZ,
            (elem->>'portfolio_value')::NUMERIC
        FROM jsonb_array_elements(rec->'results') AS r(elem);
    END LOOP;
    RAISE NOTICE 'Bulk insert completed for % records', jsonb_array_length(p_json);
END;
$$;

-- 2. Bulk insert instruments
CREATE OR REPLACE FUNCTION helper.insert_instruments_bulk(p_json JSONB)
RETURNS VOID LANGUAGE plpgsql AS $$
DECLARE rec JSONB;
BEGIN
    FOR rec IN SELECT * FROM jsonb_array_elements(p_json) LOOP
        INSERT INTO market.instrument (uic, asset_type, symbol, description, currency, exchange)
        VALUES (
            (rec->>'UIC')::INT,
            rec->>'asset_type',
            rec->>'symbol',
            rec->>'description',
            rec->>'currency',
            rec->>'exchange'
        ) ON CONFLICT (uic, asset_type) DO NOTHING;
    END LOOP;
    RAISE NOTICE 'Bulk instrument insert completed for % records', jsonb_array_length(p_json);
END;
$$;

-- 3. Bulk insert strategies
CREATE OR REPLACE FUNCTION helper.insert_strategies_bulk(p_json JSONB)
RETURNS VOID LANGUAGE plpgsql AS $$
DECLARE rec JSONB;
BEGIN
    FOR rec IN SELECT * FROM jsonb_array_elements(p_json) LOOP
        INSERT INTO analytics.strategy (name, description, type)
        VALUES (
            rec->>'strategy_name',
            rec->>'strategy_desc',
            (rec->>'strategy_type')::strategy_type_enum
        ) ON CONFLICT (name) DO NOTHING;
    END LOOP;
    RAISE NOTICE 'Bulk strategy insert completed for % records', jsonb_array_length(p_json);
END;
$$;

-- 4. Bulk insert prices
CREATE OR REPLACE FUNCTION helper.insert_prices_bulk(p_json JSONB)
RETURNS VOID LANGUAGE plpgsql AS $$
DECLARE rec JSONB;
BEGIN
    FOR rec IN SELECT * FROM jsonb_array_elements(p_json) LOOP
        INSERT INTO market.price (
            instrument_id, interval_id, time_price,
            price_open, price_high, price_low, price_close,
            price_interest, price_close_ask, price_close_bid,
            price_high_ask, price_high_bid, price_low_ask, price_low_bid,
            price_open_ask, price_open_bid, volume
        ) VALUES (
            (rec->>'instrument_ID')::INT,
            (rec->>'interval_code')::SMALLINT,
            (rec->>'time_price')::TIMESTAMPTZ,
            (rec->>'price_open')::NUMERIC,
            (rec->>'price_high')::NUMERIC,
            (rec->>'price_low')::NUMERIC,
            (rec->>'price_close')::NUMERIC,
            (rec->>'price_interest')::NUMERIC,
            (rec->>'price_close_ask')::NUMERIC,
            (rec->>'price_close_bid')::NUMERIC,
            (rec->>'price_high_ask')::NUMERIC,
            (rec->>'price_high_bid')::NUMERIC,
            (rec->>'price_low_ask')::NUMERIC,
            (rec->>'price_low_bid')::NUMERIC,
            (rec->>'price_open_ask')::NUMERIC,
            (rec->>'price_open_bid')::NUMERIC,
            (rec->>'volume')::INT
        ) ON CONFLICT (instrument_id, interval_id, time_price) DO UPDATE
          SET price_open = EXCLUDED.price_open,
              price_high = EXCLUDED.price_high,
              price_low  = EXCLUDED.price_low,
              price_close= EXCLUDED.price_close,
              volume     = EXCLUDED.volume;
    END LOOP;
    RAISE NOTICE 'Bulk price insert completed for % records', jsonb_array_length(p_json);
END;
$$;

COMMIT;
