import shutil
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
from nautilus_trader.persistence.wranglers import QuoteTickDataWrangler
from nautilus_trader.test_kit.providers import (
    CSVTickDataLoader, TestInstrumentProvider,
)

# === ŚCIEŻKI ================================================================
DATA_DIR = "/home/polymerase/elpis_v2/nautilus_data"
path = Path(DATA_DIR).expanduser()

raw_files = [p for p in sorted(path.iterdir())
             if p.is_file() and p.suffix.lower() == ".csv"]
assert raw_files, f"Brak plików CSV w {path}"

CATALOG_PATH = Path.cwd() / "nautilus_data/catalog"
if CATALOG_PATH.exists():
    shutil.rmtree(CATALOG_PATH)
CATALOG_PATH.mkdir(parents=True)

catalog = ParquetDataCatalog(CATALOG_PATH)

# === INSTRUMENT =============================================================
EURUSD = TestInstrumentProvider.default_fx_ccy("EURUSD")
wrangler = QuoteTickDataWrangler(EURUSD)
catalog.write_data([EURUSD])            # zapisujemy meta-dane instrumentu

instrument = catalog.instruments()[0]
print(instrument.id)
# === STREAMING CSV → Parquet ===============================================
for file_path in raw_files:
    print(f"Loading {file_path.name}…")

    df = CSVTickDataLoader.load(
        file_path=str(file_path),
        index_col=0,
        header=None,
        names=["timestamp", "bid_price", "ask_price", "volume"],
        usecols=["timestamp", "bid_price", "ask_price"],
        parse_dates=["timestamp"],
        date_format="%Y%m%d %H%M%S%f",
        dtype={"bid_price": "float32", "ask_price": "float32"},  # węższe typy
    )

    df = df[~df.index.duplicated(keep="first")]
    df.sort_index(inplace=True)

    ticks = wrangler.process(df)
    catalog.write_chunk(data=ticks,
                        data_cls=QuoteTick,
                        instrument_id=str(instrument.id),
                        mode="APPEND",                         # lub NEWFILE/OVERWRITE
                        basename_template=f"{file_path.stem}-{{i}}"
    )

    # natychmiast zwalniamy pamięć
    del df, ticks
    gc.collect()

print(f"Catalog populated at {CATALOG_PATH}")

# === BACKTEST ===============================================================


start = dt_to_unix_nanos(pd.Timestamp("2025-01-01", tz="UTC"))
end   = dt_to_unix_nanos(pd.Timestamp("2025-06-30", tz="UTC"))  # 30, nie 31

data_configs = [
    BacktestDataConfig(
        catalog_path=str(CATALOG_PATH),
        data_cls=QuoteTick,
        instrument_id=instrument.id,
        start_time=start,
        end_time=end,
    )
]

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
            "bar_type": "EURUSD.SIM-1-HOUR-BID-INTERNAL",
            "fast_ema_period": 50,
            "slow_ema_period": 200,
            "trade_size": Decimal(1_000_000),
        },
    )
]

config = BacktestRunConfig(
    engine=BacktestEngineConfig(strategies=strategies),
    data=data_configs,
    venues=venue_configs,
)

node = BacktestNode(configs=[config])
results = node.run()
print(results)
