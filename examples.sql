-- 1) Bulk‐insert analyses + parameters + results
SELECT helper.insert_analyses_bulk(
$$
[
  {
    "instrument_ID": 1,
    "strategy_ID": 1,
    "interval_code": 1,
    "created_at": "2025-04-13T10:00:00Z",
    "updated_at": "2025-04-13T10:00:00Z",
    "date_from":   "2025-01-01T00:00:00Z",
    "date_to":     "2025-03-01T00:00:00Z",
    "position_size":     10000.00,
    "leverage":           2.0,
    "commision_p":        0.10,
    "stop_loss_p":        1.50,
    "total_return_p":     8.5000,
    "annualized_return_p":12.3000,
    "CAGR":              11.9000,
    "max_drawdown_p":     2.0000,
    "volatility_p":       1.5000,
    "downside_deviation": 1.0000,
    "sharpe_ratio":       2.5000,
    "sortino_ratio":      3.1000,
    "calmar_ratio":       4.2000,
    "win_rate_p":         0.6500,
    "number_trades":      30,
    "average_profit":   200.00,
    "profit_factor":      1.8000,
    "alpha":              0.1200,
    "beta":               0.8500,
    "parameter_names": [
      { "parameter_name": "threshold", "parameter_value": 0.75 }
    ],
    "results": [
      { "timepoint": "2025-01-01T00:00:00Z", "portfolio_value": 10000.00 },
      { "timepoint": "2025-03-01T00:00:00Z", "portfolio_value": 10850.00 }
    ]
  },
  {
    "instrument_ID": 2,
    "strategy_ID": 2,
    "interval_code": 5,
    "created_at": "2025-04-13T12:00:00Z",
    "updated_at": "2025-04-13T12:00:00Z",
    "date_from":   "2025-02-01T00:00:00Z",
    "date_to":     "2025-04-01T00:00:00Z",
    "position_size":     5000.00,
    "leverage":           1.5,
    "commision_p":        0.15,
    "stop_loss_p":        1.00,
    "total_return_p":     5.2000,
    "annualized_return_p": 9.1000,
    "CAGR":               8.8000,
    "max_drawdown_p":     1.8000,
    "volatility_p":       1.2000,
    "downside_deviation": 0.9000,
    "sharpe_ratio":       1.9000,
    "sortino_ratio":      2.4000,
    "calmar_ratio":       3.0000,
    "win_rate_p":         0.5800,
    "number_trades":      20,
    "average_profit":   150.00,
    "profit_factor":      1.6000,
    "alpha":              0.1000,
    "beta":               0.7500,
    "parameter_names": [
      { "parameter_name": "risk", "parameter_value": 0.5 }
    ],
    "results": [
      { "timepoint": "2025-02-01T00:00:00Z", "portfolio_value": 5000.00 },
      { "timepoint": "2025-04-01T00:00:00Z", "portfolio_value": 5260.00 }
    ]
  }
]
$$::jsonb
);


-- 2) Bulk‐insert instruments
SELECT helper.insert_instruments_bulk(
$$
[
  {
    "description": "Apple Inc.",
    "UIC": 123456,
    "asset_type": "Stock",
    "symbol": "AAPL",
    "currency": "USD",
    "exchange": "NASDAQ"
  },
  {
    "description": "Alphabet Inc.",
    "UIC": 234567,
    "asset_type": "Stock",
    "symbol": "GOOGL",
    "currency": "USD",
    "exchange": "NASDAQ"
  }
]
$$::jsonb
);


-- 3) Bulk‐insert strategies
SELECT helper.insert_strategies_bulk(
$$
[
  {
    "strategy_name": "Trend Follower",
    "strategy_desc": "Follows prevailing market trends",
    "strategy_type": "bullish"
  },
  {
    "strategy_name": "Mean Reversion",
    "strategy_desc": "Leverages price deviations",
    "strategy_type": "both"
  }
]
$$::jsonb
);


-- 4) Bulk‐insert prices
SELECT helper.insert_prices_bulk(
$$
[
  {
    "instrument_ID": 1,
    "interval_code": 1,
    "time_price": "2025-04-13T12:00:00Z",
    "price_open": 123.45,
    "price_high": 125.00,
    "price_low": 122.00,
    "price_close":124.00,
    "volume": 25000
  },
  {
    "instrument_ID": 1,
    "interval_code": 1,
    "time_price": "2025-04-13T12:05:00Z",
    "price_open": 124.00,
    "price_high": 126.00,
    "price_low": 123.50,
    "price_close":125.50,
    "volume": 28000
  }
]
$$::jsonb
);
