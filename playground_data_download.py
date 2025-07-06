# another_script.py
from datetime import datetime

from elpis_nautilus.utils.config import settings           # gives you paths & .env variables
from elpis_nautilus.data_downloaders.downloader_main import _ensure_tmp_dir, download_histdata   # “private” but reusable

def main() -> None:
    # 1. Get (or create) the tmp directory managed by config.py
    tmp_dir = _ensure_tmp_dir()

    # 2. Define what you want to pull
    symbol = "EURUSD"
    start  = datetime(2012, 1, 1)     # inclusive month/year
    end    = datetime(2012, 3, 1)

    # 3. Kick off the download
    download_histdata(symbol, start, end, tmp_dir)

if __name__ == "__main__":
    main()
