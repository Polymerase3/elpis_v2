#!/usr/bin/env python3
from decimal import Decimal
from pathlib import Path
import gc
import pandas as pd

from nautilus_trader.backtest.node import (
    BacktestDataConfig, BacktestEngineConfig,
    BacktestNode, BacktestRunConfig, BacktestVenueConfig,
)
from nautilus_trader.config import ImportableStrategyConfig
from nautilus_trader.core.datetime import dt_to_unix_nanos
from nautilus_trader.model import QuoteTick
from nautilus_trader.persistence.catalog import ParquetDataCatalog

CATALOG_PATH = Path("nautilus_data/catalog").expanduser().resolve()


def yearly_chunks(start_ts: pd.Timestamp,
                  end_ts: pd.Timestamp) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Zwraca [(start1, end1), (start2, end2), …] – jeden rok każdy."""
    chunks = []
    cur = start_ts
    while cur < end_ts:
        nxt = min(cur.replace(year=cur.year + 1), end_ts)
        chunks.append((cur, nxt))
        cur = nxt
    return chunks


def main() -> None:
    catalog = ParquetDataCatalog(CATALOG_PATH)

    instrument = catalog.instruments()[0]

    start_dt = pd.Timestamp("2015-06-30", tz="UTC")
    end_dt   = pd.Timestamp("2025-06-30", tz="UTC")   # 30, nie 31

    # ---------- DATA CONFIGS PER YEAR ---------------------------------------
    data_configs = []
    for s, e in yearly_chunks(start_dt, end_dt):
        data_configs.append(
            BacktestDataConfig(
                catalog_path=str(CATALOG_PATH),
                data_cls=QuoteTick,
                instrument_id=instrument.id,
                start_time=dt_to_unix_nanos(s),
                end_time=dt_to_unix_nanos(e),
                # Jeżeli Twoja wersja Nautilusa na to pozwala:
                # columns=["ts", "bid", "ask"],
            )
        )

    # ---------- VENUE & STRATEGY -------------------------------------------
    venue_configs = [
        BacktestVenueConfig(
            name="SIM",
            oms_type="HEDGING",
            account_type="MARGIN",
            base_currency="USD",
            starting_balances=["1_000_000 USD"],
        )
    ]

    strategies = [
        ImportableStrategyConfig(
            strategy_path="nautilus_trader.examples.strategies.ema_cross:EMACross",
            config_path="nautilus_trader.examples.strategies.ema_cross:EMACrossConfig",
            config={
                "instrument_id": instrument.id,
                "bar_type": "EURUSD.SIM-1-DAY-BID-INTERNAL",
                "fast_ema_period": 50,
                "slow_ema_period": 100,
                "trade_size": Decimal(1_000_000),
            },
        )
    ]

    run_cfg = BacktestRunConfig(
        engine=BacktestEngineConfig(strategies=strategies),
        data=data_configs,
        venues=venue_configs,
    )

    node = BacktestNode(configs=[run_cfg])
    results = node.run()
    print(results)

    # sprzątanie
    del node, run_cfg, strategies, venue_configs, data_configs
    gc.collect()


if __name__ == "__main__":
    main()
