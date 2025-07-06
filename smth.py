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

print(EURUSD)