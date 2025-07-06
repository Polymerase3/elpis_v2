import os
from pathlib import Path
from dotenv import load_dotenv

# Project root (three levels above this file)
BASE_DIR = Path(__file__).resolve().parents[4]

# Load .env only once, right here
dotenv_path = BASE_DIR / ".env"
if dotenv_path.exists():
    load_dotenv(dotenv_path, override=True)


class Config:
    """
    Simple config class that reads settings from environment variables.
    """

    # --- Core data-dir paths -------------------------------------------------
    data_dir_name: str = os.getenv("DATA_DIR", "data")

    @property
    def data_dir(self) -> Path:
        return BASE_DIR / self.data_dir_name

    @property
    def tmp_dir(self) -> Path:
        return self.data_dir / "tmp"

    # --- Database -----------------------------------------------------------
    db_host: str = os.getenv("POSTGRES_HOST", "localhost")
    db_port: int = int(os.getenv("POSTGRES_PORT", 5432))
    db_name: str = os.getenv("POSTGRES_DB", "elpis")
    db_user: str = os.getenv("POSTGRES_USER", "polymerase")
    db_password: str | None = os.getenv("POSTGRES_PASSWORD")

    # --- API credentials ----------------------------------------------------
    account_key: str | None = os.getenv("ACCOUNT_KEY")
    access_token: str | None = os.getenv("ACCESS_TOKEN")

    # --- Logging & monitoring ----------------------------------------------
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    prometheus_port: int = int(os.getenv("PROMETHEUS_PORT", 8000))


# Shared singleton
settings = Config()
