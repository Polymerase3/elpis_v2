import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env in project root
BASE_DIR = Path(__file__).resolve().parents[2]
dotenv_path = BASE_DIR / ".env"
if dotenv_path.exists():
    load_dotenv(dotenv_path, override=True)

class Config:
    """
    Simple config class that reads settings from environment variables.
    """
    # Database connection settings
    db_host: str = os.getenv("POSTGRES_HOST", "localhost")
    db_port: int = int(os.getenv("POSTGRES_PORT", 5432))
    db_name: str = os.getenv("POSTGRES_DB", "elpis")
    db_user: str = os.getenv("POSTGRES_USER", "polymerase")
    db_password: str = os.getenv("POSTGRES_PASSWORD")

    # API credentials
    account_key: str = os.getenv("ACCOUNT_KEY")
    access_token: str = os.getenv("ACCESS_TOKEN")

    # Logging & monitoring
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    prometheus_port: int = int(os.getenv("PROMETHEUS_PORT", 8000))

# Single shared config instance
settings = Config()
