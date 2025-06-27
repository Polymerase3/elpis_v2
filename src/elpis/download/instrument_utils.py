import psycopg2
from psycopg2.extras import execute_values, RealDictCursor
from typing import List, Dict, Any, Optional
from elpis.config import settings


def insert_instruments(data: List[Dict[str, Any]]) -> None:
    """
    Bulk insert or update instruments into the Postgres database.

    :param data: List of dicts with keys:
        - description (str)
        - UIC (int)
        - asset_type (str)
        - symbol (str)
        - currency (str)
        - exchange (str)
    """
    conn = psycopg2.connect(
        host=settings.db_host,
        port=settings.db_port,
        dbname=settings.db_name,
        user=settings.db_user,
        password=settings.db_password
    )
    try:
        with conn.cursor() as cur:
            sql = """
                INSERT INTO market.instrument
                    (description, uic, asset_type, symbol, currency, exchange)
                VALUES %s
                ON CONFLICT (uic, asset_type) DO UPDATE SET
                    description = EXCLUDED.description,
                    symbol      = EXCLUDED.symbol,
                    currency    = EXCLUDED.currency,
                    exchange    = EXCLUDED.exchange;
            """
            values = [(
                instr.get('description'),
                instr.get('UIC'),
                instr.get('asset_type'),
                instr.get('symbol'),
                instr.get('currency'),
                instr.get('exchange')
            ) for instr in data]
            if not values:
                return
            execute_values(cur, sql, values)
        conn.commit()
    finally:
        conn.close()


def delete_instruments(keys: List[Dict[str, Any]]) -> None:
    """
    Delete instruments matching given list of UIC and asset_type pairs.

    :param keys: List of dicts with keys 'UIC' and 'asset_type'.
    """
    conn = psycopg2.connect(
        host=settings.db_host,
        port=settings.db_port,
        dbname=settings.db_name,
        user=settings.db_user,
        password=settings.db_password
    )
    try:
        with conn.cursor() as cur:
            # Prepare tuples for IN-clause
            pairs = [(k['UIC'], k['asset_type']) for k in keys]
            if not pairs:
                return
            delete_sql = "DELETE FROM market.instrument WHERE (uic, asset_type) IN %s;"
            cur.execute(delete_sql, (tuple(pairs),))
        conn.commit()
    finally:
        conn.close()


def fetch_instruments(uic: Optional[int] = None,
                       asset_type: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Retrieve instruments from the database, optionally filtered by UIC and/or asset_type.

    :param uic: Optional integer UIC to filter by.
    :param asset_type: Optional asset_type string to filter by.
    :return: List of dicts for each instrument.
    """
    conn = psycopg2.connect(
        host=settings.db_host,
        port=settings.db_port,
        dbname=settings.db_name,
        user=settings.db_user,
        password=settings.db_password
    )
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            base_sql = "SELECT id, description, uic, asset_type, symbol, currency, exchange FROM market.instrument"
            filters = []
            params: List[Any] = []
            if uic is not None:
                filters.append("uic = %s")
                params.append(uic)
            if asset_type is not None:
                filters.append("asset_type = %s")
                params.append(asset_type)
            if filters:
                base_sql += " WHERE " + " AND ".join(filters)
            base_sql += ";"
            cur.execute(base_sql, tuple(params))
            return cur.fetchall()
    finally:
        conn.close()
