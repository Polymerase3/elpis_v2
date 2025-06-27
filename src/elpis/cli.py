import sys
import json
import click
from saxo_openapi import API
from elpis.download.instrument_to_uic import instrument_to_uic
from elpis.download.instrument_utils import insert_instruments, delete_instruments, fetch_instruments
from elpis.download.data_ingest import get_data_saxo, plot_saxo_data
from elpis.config import settings
from datetime import datetime
import psycopg2


@click.group()
def cli():
    """
    CLI for instrument management: insert, delete, fetch, search.
    """
    pass


@cli.command('insert-instrument')
@click.argument('json_files', type=click.File('r'), nargs=-1)
def insert_instrument(json_files):
    """
    Insert **or update** rows in *market.instrument* from JSON.

    • Accepts any number of JSON files **or** STDIN.  
    • Each JSON must be a list of objects with keys  
      `description, UIC, asset_type, symbol, currency, exchange`.
    • If a row with the same *(UIC, asset_type)* already exists you’ll be
      asked whether to update it.
    """

    # ---------- read JSON ----------------------------------------------------
    try:
        sources = json_files or [sys.stdin]
        records: list[dict] = []
        for f in sources:
            payload = json.load(f)
            if not isinstance(payload, list):
                click.echo('❌  Each JSON must be a *list* of objects', err=True)
                sys.exit(1)
            records.extend(payload)
    except json.JSONDecodeError as e:
        click.echo(f'❌  Invalid JSON: {e}', err=True)
        sys.exit(1)

    if not records:
        click.echo('Nothing to insert.'); return

    # ---------- DB connection ------------------------------------------------
    conn = psycopg2.connect(
        host=settings.db_host, port=settings.db_port,
        dbname=settings.db_name, user=settings.db_user,
        password=settings.db_password
    )
    inserted = updated = skipped = 0

    try:
        with conn.cursor() as cur:
            for rec in records:
                uic        = rec.get('UIC')
                asset_type = rec.get('asset_type')

                if uic is None or asset_type is None:
                    click.echo('⚠️  Missing UIC or asset_type – skipping one record')
                    skipped += 1
                    continue

                # does it already exist?
                cur.execute(
                    "SELECT id FROM market.instrument "
                    "WHERE uic = %s AND asset_type = %s;",
                    (uic, asset_type)
                )
                row = cur.fetchone()

                if row:
                    msg = (
                        f'Instrument (UIC={uic}, asset_type={asset_type}) already exists. '
                        'Update it?'
                    )
                    if click.confirm(msg, default=False):
                        cur.execute(
                            """
                            UPDATE market.instrument
                               SET description = %(description)s,
                                   symbol      = %(symbol)s,
                                   currency    = %(currency)s,
                                   exchange    = %(exchange)s
                             WHERE uic = %(UIC)s AND asset_type = %(asset_type)s;
                            """,
                            rec,
                        )
                        updated += 1
                    else:
                        skipped += 1
                        continue
                else:  # insert new
                    cur.execute(
                        """
                        INSERT INTO market.instrument
                              (description, uic, asset_type, symbol, currency, exchange)
                        VALUES (%(description)s, %(UIC)s, %(asset_type)s,
                                %(symbol)s, %(currency)s, %(exchange)s);
                        """,
                        rec,
                    )
                    inserted += 1

        conn.commit()

    except Exception as e:
        conn.rollback()
        click.echo(f'❌  Database error: {e}', err=True)
        sys.exit(1)
    finally:
        conn.close()

    # ---------- summary ------------------------------------------------------
    click.echo(f'✅  Inserted: {inserted}, Updated: {updated}, Skipped: {skipped}')



@cli.command('delete-instrument')
@click.option('--id', 'ids', type=int, multiple=True, help='Instrument id(s) to delete')
@click.option('--uic', 'uics', type=int, multiple=True, help='UIC(s) of instruments to delete')
@click.option('--symbol', 'symbols', type=str, multiple=True, help='Symbol(s) of instruments to delete')
def delete(ids, uics, symbols):
    """
    Delete instruments by id, uic, or symbol. Prompts for confirmation.
    """
    # Collect all matching instruments
    try:
        # Fetch all if specific filters provided, else error
        results = fetch_instruments(uic=None, asset_type=None)
        to_delete = []
        for item in results:
            if ids and item.get('id') in ids:
                to_delete.append(item)
            elif uics and item.get('uic') in uics:
                to_delete.append(item)
            elif symbols and item.get('symbol') in symbols:
                to_delete.append(item)
        if not to_delete:
            click.echo('No matching instruments found for deletion.')
            sys.exit(0)
        # Show table of instruments to delete
        click.echo('The following instruments will be deleted:')
        _print_table(to_delete)
        # Confirm
        confirm = click.prompt('Type y or yes to confirm deletion', default='n')
        if confirm.lower() not in ('y', 'yes'):
            click.echo('Deletion cancelled.')
            sys.exit(0)
        # Build keys list for deletion
        keys = [{'UIC': item.get('uic'), 'asset_type': item.get('asset_type')} for item in to_delete]
        delete_instruments(keys)
        click.echo(f"Deleted {len(to_delete)} instruments.")
        sys.exit(0)
    except Exception as e:
        click.echo(f"Error deleting instruments: {e}", err=True)
        sys.exit(1)


def _print_table(results: list):
    headers = ['id', 'uic', 'asset_type', 'symbol', 'exchange', 'description', 'currency']
    rows = [[
        item.get('id'),
        item.get('uic'),
        item.get('asset_type'),
        item.get('symbol'),
        item.get('exchange'),
        item.get('description'),
        item.get('currency')
    ] for item in results]
    if not rows:
        click.echo('No records found.')
        return
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(str(cell)))
    header_line = ' | '.join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
    sep_line = '-+-'.join('-' * col_widths[i] for i in range(len(headers)))
    click.echo(header_line)
    click.echo(sep_line)
    for row in rows:
        click.echo(' | '.join(str(cell).ljust(col_widths[i]) for i, cell in enumerate(row)))


@cli.command('get-instrument')
@click.option('--uic', type=int, help='Filter by UIC')
@click.option('--asset-type', 'asset_type', type=str, help='Filter by asset_type')
def fetch(uic, asset_type):
    """
    Fetch instruments from DB, optionally filtering by UIC and/or asset_type.
    Outputs a table of results.
    """
    try:
        results = fetch_instruments(uic=uic, asset_type=asset_type)
        _print_table(results)
        sys.exit(0)
    except Exception as e:
        click.echo(f"Error fetching instruments: {e}", err=True)
        sys.exit(1)


@cli.command('search-instrument')
@click.option('--instrument', '-i', required=True, help='Instrument keyword to search')
@click.option('--assettype', '-a', default=None, help='AssetType filter (None = all)')
@click.option('--filter-uic', type=int, multiple=True, help='Only include these UICs')
@click.option('--filter-symbol', type=str, multiple=True, help='Only include these Symbols')
@click.option('--debug', '-d', is_flag=True, default=False, help='Enable debug logging')
@click.option('--printout', '-p', is_flag=True, default=False, help='Print fetched counts')
@click.option('--to-json', 'to_json', is_flag=True, default=False, help='Output raw JSON suitable for piping into insert')
def search(instrument, assettype, filter_uic, filter_symbol, debug, printout, to_json):
    """
    Search for instruments via API, filter, and display results or output JSON for piping.

    By default prints a table when run interactively; if piped or --to-json flag is used, emits JSON.
    """
    from saxo_openapi import API
    try:
        client = API(access_token=settings.access_token)
        spec = {'Instrument': instrument}
        raw = instrument_to_uic(client=client,
                                spec=spec,
                                assettype=assettype,
                                debug=debug,
                                printout=printout)
        # Apply CLI filters
        if filter_uic:
            raw = [item for item in raw if item.get('Uic') in filter_uic]
        if filter_symbol:
            raw = [item for item in raw if item.get('Symbol') in filter_symbol]
        # Normalize for insert JSON
        normalized = [{
                'description': itm.get('Description'),
                'UIC': itm.get('Uic'),
                'asset_type': itm.get('AssetType'),
                'symbol': itm.get('Symbol'),
                'currency': itm.get('CurrencyCode'),
                'exchange': itm.get('ExchangeId')
            } for itm in raw]
        # Detect piping
        is_piped = not sys.stdout.isatty()
        if to_json or is_piped:
            click.echo(json.dumps(normalized, indent=2))
            sys.exit(0)
        # Otherwise print table
        headers = ["Uic", "AssetType", "Symbol", "ExchangeId", "IssuerCountry", "Description", "CurrencyCode"]
        rows = [[
            itm.get('Uic'),
            itm.get('AssetType'),
            itm.get('Symbol'),
            itm.get('ExchangeId'),
            itm.get('IssuerCountry') or '',
            itm.get('Description'),
            itm.get('CurrencyCode')
        ] for itm in raw]
        if rows:
            col_widths = [len(h) for h in headers]
            for row in rows:
                for i, cell in enumerate(row):
                    col_widths[i] = max(col_widths[i], len(str(cell)))
            header_line = ' | '.join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
            sep_line = '-+-'.join('-' * col_widths[i] for i in range(len(headers)))
            click.echo(header_line)
            click.echo(sep_line)
            for row in rows:
                click.echo(' | '.join(str(cell).ljust(col_widths[i]) for i, cell in enumerate(row)))
        else:
            click.echo('No results found.')
        sys.exit(0)
    except Exception as e:
        click.echo(f"Error searching instruments: {e}", err=True)
        sys.exit(1)
        

@cli.command('insert-prices')
@click.option('--id', 'instrument_id', type=int, help='Internal market.instrument.id')
@click.option('--uic', type=int, help='Instrument UIC for Saxo API')
@click.option('--assettype', 'asset_type', help='Instrument AssetType for Saxo API')
@click.option(
    '--interval', 'interval_label', required=True,
    help="Interval label (e.g. '1m','5m','15m','1h','4h','1d','1w','1mo')"
)
@click.option(
    '--start-time', 'start_time', required=True,
    help='Start time ISO8601, e.g. 2025-01-01T00:00:00'
)
@click.option('--verbose', '-v', is_flag=True, default=False, help='Show download progress per chunk')
def load_prices(instrument_id, uic, asset_type, interval_label, start_time, verbose):
    """
    Load price data from Saxo and upsert into market.price.

    Provide either --id (DB id) *or* both --uic and --assettype.
    """
    # Resolve instrument identification and API keys
    conn = psycopg2.connect(
        host=settings.db_host, port=settings.db_port,
        dbname=settings.db_name, user=settings.db_user,
        password=settings.db_password
    )
    try:
        with conn.cursor() as cur:
            if instrument_id:
                cur.execute(
                    "SELECT uic, asset_type FROM market.instrument WHERE id = %s;",
                    (instrument_id,)
                )
                row = cur.fetchone()
                if not row:
                    click.echo(f"Instrument id={instrument_id} not found.", err=True)
                    sys.exit(1)
                uic, asset_type = row
                resolved_db_id = instrument_id
            else:
                if not (uic and asset_type):
                    click.echo(
                        'You must supply either --id or both --uic and --assettype',
                        err=True
                    )
                    sys.exit(1)
                cur.execute(
                    "SELECT id FROM market.instrument WHERE uic = %s AND asset_type = %s;",
                    (uic, asset_type)
                )
                row = cur.fetchone()
                if not row:
                    click.echo(
                        f"Instrument UIC={uic}, asset_type={asset_type} not found.",
                        err=True
                    )
                    sys.exit(1)
                resolved_db_id = row[0]
    finally:
        conn.close()

    # Map interval label to numeric id and minutes
    interval_map = {
        '1m':  (1,    1),
        '5m':  (2,    5),
        '15m': (3,   15),
        '1h':  (4,   60),
        '4h':  (5,  240),
        '1d':  (6, 1440),
        '1w':  (7,10080),
        '1mo': (8,43200),
    }
    if interval_label not in interval_map:
        click.echo(f"Invalid interval: {interval_label}", err=True)
        sys.exit(1)
    interval_id, horizon_minutes = interval_map[interval_label]

    # Parse start time
    try:
        dt = datetime.fromisoformat(start_time)
    except ValueError:
        click.echo(f"Invalid start-time format: {start_time}", err=True)
        sys.exit(1)
        
    # Check for existing price data (only warn if count>0)
    conn = psycopg2.connect(
        host=settings.db_host, port=settings.db_port,
        dbname=settings.db_name, user=settings.db_user,
        password=settings.db_password
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*), MIN(time_price) FROM market.price "
                "WHERE instrument_id = %s AND interval_id = %s;",
                (resolved_db_id, interval_id)
            )
            count, first_ts = cur.fetchone()
            print(count)
        if count and count > 0:
            click.echo(f"Warning: Found {count} existing price points starting from {first_ts}.")
            confirm = click.prompt(
                'Type y or yes to overwrite and fetch fresh data', default='n'
            )
            if confirm.lower() not in ('y', 'yes'):
                click.echo('Operation cancelled.')
                sys.exit(0)
    finally:
        conn.close()

    # Fetch data
    try:
        rows = get_data_saxo(
            access_token=settings.access_token,
            account_key=settings.account_key,
            Uic=uic,
            asset_type=asset_type,
            interval_code=interval_id,
            start_time=dt,
            horizon=horizon_minutes,
            verbose=verbose
        )
        click.echo(
            f"Fetched {len(rows)} rows for instrument id={resolved_db_id}, "
            f"interval {interval_label} (ID {interval_id})."
        )
        sys.exit(0)
    except Exception as e:
        click.echo(f"Error loading prices: {e}", err=True)
        sys.exit(1)
        
@cli.command('get-prices')
@click.option('--id', 'instrument_id', type=int, help='Internal market.instrument.id')
@click.option('--uic', type=int, help='Instrument UIC for Saxo API')
@click.option('--assettype', 'asset_type', help='Instrument AssetType for Saxo API')
@click.option('--interval', 'interval_label', required=True,
              help="Interval label (e.g. '1m','5m','15m','1h','4h','1d','1w','1mo')")
@click.option('--head', type=int, default=None, help='Show only the first N rows')
@click.option('--from-date', 'from_date', help='Filter rows with time_price >= this ISO timestamp')
@click.option('--to-date', 'to_date', help='Filter rows with time_price <= this ISO timestamp')
def show_prices(instrument_id, uic, asset_type, interval_label, head, from_date, to_date):
    """Display stored prices for a given instrument and interval.

    You can identify the instrument by internal **id** *or* by (uic, assettype).
    Optional filters:
      • --from-date / --to-date (ISO 8601)
      • --head N                (limit rows returned)
    Only columns that contain at least one non‑null value are shown.
    """
    # ---------------- Resolve instrument -----------------
    conn = psycopg2.connect(host=settings.db_host, port=settings.db_port,
                            dbname=settings.db_name, user=settings.db_user,
                            password=settings.db_password)
    try:
        with conn.cursor() as cur:
            if instrument_id:
                cur.execute("SELECT uic, asset_type FROM market.instrument WHERE id=%s;", (instrument_id,))
                row = cur.fetchone()
                if not row:
                    click.echo(f"Instrument id={instrument_id} not found.", err=True)
                    sys.exit(1)
                uic, asset_type = row
                resolved_id = instrument_id
            else:
                if not (uic and asset_type):
                    click.echo('Provide --id OR (--uic and --assettype).', err=True)
                    sys.exit(1)
                cur.execute("SELECT id FROM market.instrument WHERE uic=%s AND asset_type=%s;", (uic, asset_type))
                row = cur.fetchone()
                if not row:
                    click.echo(f"Instrument uic={uic}, asset_type={asset_type} not found.", err=True)
                    sys.exit(1)
                resolved_id = row[0]
    finally:
        conn.close()

    # -------------- interval mapping ---------------------
    interval_map = {'1m':1,'5m':2,'15m':3,'1h':4,'4h':5,'1d':6,'1w':7,'1mo':8}
    if interval_label not in interval_map:
        click.echo(f"Invalid interval: {interval_label}", err=True)
        sys.exit(1)
    interval_id = interval_map[interval_label]

    # -------------- optional date filters ---------------
    filters = []
    params  = [resolved_id, interval_id]

    if from_date:
        try:
            _ = datetime.fromisoformat(from_date)
        except ValueError:
            click.echo('Invalid --from-date format. Use ISO8601.', err=True)
            sys.exit(1)
        filters.append("time_price >= %s")
        params.append(from_date)

    if to_date:
        try:
            _ = datetime.fromisoformat(to_date)
        except ValueError:
            click.echo('Invalid --to-date format. Use ISO8601.', err=True)
            sys.exit(1)
        filters.append("time_price <= %s")
        params.append(to_date)

    where_clause = " AND ".join(["instrument_id=%s", "interval_id=%s"] + filters)
    order_clause = "ORDER BY time_price DESC"
    limit_clause = ""
    if head:
        limit_clause = "LIMIT %s"
        params.append(head)

    sql = f"SELECT * FROM market.price WHERE {where_clause} {order_clause} {limit_clause};"

    # ---------------- query ------------------------------
    conn = psycopg2.connect(host=settings.db_host, port=settings.db_port,
                            dbname=settings.db_name, user=settings.db_user,
                            password=settings.db_password)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
            columns = [d[0] for d in cur.description]
    finally:
        conn.close()

    if not rows:
        click.echo('No price data found.')
        return

        # ---------------- format + print table ------------------
    # keep only columns that contain at least one non‑null value
    keep_idx = [i for i, col in enumerate(columns) if any(row[i] is not None for row in rows)]
    keep_cols = [columns[i] for i in keep_idx]

    # compute width = max(len(cell), len(header)) for each column
    widths = [len(keep_cols[i]) for i in range(len(keep_cols))]
    for row in rows:
        for j, idx in enumerate(keep_idx):
            widths[j] = max(widths[j], len(str(row[idx])))

    # helper to pad all but the last column (avoids right‑hand trailing blanks)
    def pad(value: str, col_idx: int) -> str:
        if col_idx == len(widths) - 1:
            return value  # last column – no padding
        return value.ljust(widths[col_idx])

    # header
    header = " | ".join(pad(col, i) for i, col in enumerate(keep_cols))
    sep    = "-+-".join("-" * len(col) if i == len(widths)-1 else "-" * widths[i]
                         for i, col in enumerate(keep_cols))
    click.echo(header)
    click.echo(sep)

    # rows
    for row in rows:
        line = " | ".join(pad(str(row[idx]), j) for j, idx in enumerate(keep_idx))
        click.echo(line)
        
# ──────────────────────────────────────────────────────────────────────────────
# Delete rows from market.price
# ──────────────────────────────────────────────────────────────────────────────
@cli.command('delete-prices')
@click.option('--id',          'instrument_id', type=int, help='market.instrument.id')
@click.option('--uic',         type=int,         help='Instrument UIC')
@click.option('--assettype',   'asset_type',     help='Instrument AssetType')
@click.option('--interval',    'interval_label', required=True,
              help="Interval label: 1m / 5m / 15m / 1h / 4h / 1d / 1w / 1mo")
@click.option('--from-time',   'from_time', default=None,
              help="Delete from (inclusive)  – ISO-8601, e.g. 2023-01-01T00:00:00")
@click.option('--to-time',     'to_time',   default=None,
              help="Delete to   (exclusive) – ISO-8601, e.g. 2023-12-31T23:59:59")
def delete_prices(instrument_id, uic, asset_type,
                  interval_label, from_time, to_time):
    """
    Delete price rows from *market.price*.

    Supply either --id **or** both --uic and --assettype, plus an interval
    label.  Optionally limit the deletion with --from-time / --to-time.
    A summary table is shown and you must confirm the operation.
    """
    # ── resolve instrument ────────────────────────────────────────────────────
    conn = psycopg2.connect(
        host=settings.db_host, port=settings.db_port,
        dbname=settings.db_name, user=settings.db_user,
        password=settings.db_password
    )
    try:
        with conn.cursor() as cur:
            if instrument_id:
                cur.execute(
                    "SELECT id, uic, asset_type FROM market.instrument WHERE id=%s;",
                    (instrument_id,)
                )
            else:
                if not (uic and asset_type):
                    click.echo('Provide --id *or* both --uic and --assettype', err=True)
                    sys.exit(1)
                cur.execute(
                    "SELECT id, uic, asset_type FROM market.instrument "
                    "WHERE uic=%s AND asset_type=%s;",
                    (uic, asset_type)
                )
            row = cur.fetchone()
            if not row:
                click.echo('Instrument not found.', err=True); sys.exit(1)
            resolved_id, uic, asset_type = row
    finally:
        conn.close()

    # ── interval mapping ─────────────────────────────────────────────────────
    imap = {'1m':1,'5m':2,'15m':3,'1h':4,'4h':5,'1d':6,'1w':7,'1mo':8}
    if interval_label not in imap:
        click.echo('Invalid interval label', err=True); sys.exit(1)
    interval_id = imap[interval_label]

    # ── parse from/to times ──────────────────────────────────────────────────
    def _parse(ts):
        if ts is None: return None
        try:
            return datetime.fromisoformat(ts)
        except ValueError:
            click.echo(f'Invalid ISO-8601 timestamp: {ts}', err=True); sys.exit(1)

    t_from = _parse(from_time)
    t_to   = _parse(to_time)

    # ── build SQL WHERE clause ───────────────────────────────────────────────
    where = ["instrument_id = %s", "interval_id = %s"]
    params = [resolved_id, interval_id]
    if t_from:
        where.append("time_price >= %s");  params.append(t_from)
    if t_to:
        where.append("time_price <  %s");  params.append(t_to)
    where_clause = " AND ".join(where)

    # ── count rows to delete ────────────────────────────────────────────────
    conn = psycopg2.connect(
        host=settings.db_host, port=settings.db_port,
        dbname=settings.db_name, user=settings.db_user,
        password=settings.db_password
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT COUNT(*), MIN(time_price), MAX(time_price) "
                f"FROM market.price WHERE {where_clause};",
                tuple(params)
            )
            cnt, t_min, t_max = cur.fetchone()

            if cnt == 0:
                click.echo('No rows match the criteria – nothing to delete.')
                return

            # ── show summary table ──────────────────────────────────────────
            hdr = ['instrument_id','interval_id','from','to','rows']
            colw = [14,12,19,19,10]
            row_data = [
                str(resolved_id).rjust(colw[0]),
                str(interval_id).rjust(colw[1]),
                (t_from.isoformat() if t_from else str(t_min))[:19].ljust(colw[2]),
                (t_to.isoformat()   if t_to   else str(t_max))[:19].ljust(colw[3]),
                f'{cnt:,}'.rjust(colw[4])
            ]
            click.echo(" | ".join(h.ljust(colw[i]) for i,h in enumerate(hdr)))
            click.echo("-+-".join('-'*w for w in colw))
            click.echo(" | ".join(row_data))
            click.echo()

            if not click.confirm('Proceed with deletion?', default=False):
                click.echo('Aborted.'); return

            # ── delete rows ────────────────────────────────────────────────
            cur.execute(f"DELETE FROM market.price WHERE {where_clause};", tuple(params))
        conn.commit()
        click.echo(f'✅  Deleted {cnt:,} rows.')
    except Exception as e:
        conn.rollback()
        click.echo(f'❌  Error: {e}', err=True); sys.exit(1)
    finally:
        conn.close()

        
# The heavy‑lifting function lives below (plot_saxo_data).  Here we only wrap it
# for the CLI.

@cli.command('plot-prices')
@click.option('--id', 'instrument_id', type=int, help='Internal market.instrument.id')
@click.option('--uic', type=int, help='Instrument UIC for Saxo')
@click.option('--assettype', 'asset_type', help='AssetType for Saxo')
@click.option('--interval', 'interval_label', required=True,
              help="Interval label: 1m 5m 15m 1h 4h 1d 1w 1mo")
@click.option('--from-date', help='ISO timestamp start filter (>=)')
@click.option('--to-date',   help='ISO timestamp end   filter (<=)')
@click.option('--side', 'price_side', type=click.Choice(['ask','bid','mid'], case_sensitive=False),
              default='mid', show_default=True,
              help="Which price side to plot when Ask/Bid available")
@click.option('-v', '--verbose', is_flag=True, help='Verbose output')
def plot_prices(instrument_id, uic, asset_type, interval_label, from_date, to_date, price_side, verbose):
    """Plot stored prices with Backtrader.

    Identify instrument by **--id** or by the (uic, assettype) pair, same as
    *show-prices*.  Use --side ask|bid|mid to choose which columns to draw for
    instruments that carry Ask/Bid fields (FxSpot, CFDs, futures, …).
    """
    try:
        plot_saxo_data(
            instrument_id=instrument_id,
            uic=uic,
            asset_type=asset_type,
            interval_label=interval_label,
            from_date=from_date,
            to_date=to_date,
            price_side=price_side.lower(),
            verbose=verbose,
        )
    except Exception as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

# ──────────────────────────────────────────────────────────────────────────────
# Show DB size  (collapsed view by default, expand with --internal)
# ──────────────────────────────────────────────────────────────────────────────

# ───────── helpers ─────────
_UNIT_MAP = {'b': 1, 'kb': 1024, 'mb': 1024**2,
             'gb': 1024**3, 'tb': 1024**4}


def _fmt(num_bytes: int, div: int, width: int) -> str:
    """Human-readable size number, padded to *width*."""
    return f'{num_bytes / div:,.2f}'.rjust(width)


# ───────── db-size command ─────────
@cli.command('db-size')
@click.option(
    '--unit',
    type=click.Choice(['b', 'kb', 'mb', 'gb', 'tb'], case_sensitive=False),
    default='mb',
    help='Display sizes in the chosen unit (default: MB)',
)
@click.option(
    '--all',
    'show_all',
    is_flag=True,
    default=False,
    help='Show every relation including TimescaleDB internal chunks / catalogs',
)
def db_size(unit: str, show_all: bool) -> None:
    """
    Show the size of every table (or *all* relations with --all) plus totals.
    """
    _UNIT_MAP = {'b': 1, 'kb': 1024, 'mb': 1024**2,
                 'gb': 1024**3, 'tb': 1024**4}

    def fmt(num: int) -> str:
        """Format *num* (bytes) in the requested unit."""
        div = _UNIT_MAP[unit.lower()]
        return f'{num / div:,.2f}'

    conn = psycopg2.connect(
        host=settings.db_host,
        port=settings.db_port,
        dbname=settings.db_name,
        user=settings.db_user,
        password=settings.db_password,
    )
    try:
        with conn.cursor() as cur:
            # -----------------------------------------------------------------
            # 1‣ discover hypertables
            # -----------------------------------------------------------------
            cur.execute("""
                SELECT hypertable_schema, hypertable_name
                  FROM timescaledb_information.hypertables
            """)
            hts = {(s, t) for s, t in cur.fetchall()}

            rows: list[tuple[str, int]] = []

            # -----------------------------------------------------------------
            # 2‣ handle hypertables
            # -----------------------------------------------------------------
            if show_all:
                # we'll enumerate every relation later – nothing to do here
                pass
            else:
                for schema, table in sorted(hts):
                    cur.execute(
                        "SELECT SUM(total_bytes) "
                        "  FROM hypertable_detailed_size(%s)",
                        (f'{schema}.{table}',),
                    )
                    size = cur.fetchone()[0] or 0
                    rows.append((f'{schema}.{table}', size))

            # -----------------------------------------------------------------
            # 3‣ gather all remaining relations
            # -----------------------------------------------------------------
            if show_all:
                excl_ns = ()  # show literally everything
            else:
                excl_ns = (
                    'pg_catalog', 'information_schema', 'pg_toast',
                    '_timescaledb_internal', '_timescaledb_catalog',
                    '_timescaledb_cache', '_timescaledb_config',
                )

            cur.execute(f"""
                SELECT n.nspname   AS schema,
                       c.relname   AS table,
                       pg_total_relation_size(c.oid) AS bytes
                  FROM pg_class      c
                  JOIN pg_namespace n ON n.oid = c.relnamespace
                 WHERE c.relkind = 'r'                       -- ordinary tables
                   AND NOT n.nspname = ANY(%s)
            """, (list(excl_ns),))
            for schema, tbl, sz in cur.fetchall():
                # skip hypertable bases if we've already added the consolidated
                if not show_all and (schema, tbl) in hts:
                    continue
                rows.append((f'{schema}.{tbl}', sz))

            # -----------------------------------------------------------------
            # 4‣ totals
            # -----------------------------------------------------------------
            sum_rows = sum(sz for _, sz in rows)
            cur.execute("SELECT pg_database_size(%s)", (settings.db_name,))
            db_total = cur.fetchone()[0]

    finally:
        conn.close()

    # -------------------------------------------------------------------------
    # 5‣ pretty-print
    # -------------------------------------------------------------------------
    name_w = max(len(n) for n, _ in rows + [('TOTAL (rows)', 0)])
    size_w = max(len(fmt(sz)) for _, sz in rows + [('db', db_total)])

    header = f'{"Table".ljust(name_w)} | Size ({unit.upper()})'
    click.echo(header)
    click.echo('-' * len(header))

    for name, sz in sorted(rows, key=lambda r: (-r[1], r[0])):
        click.echo(f'{name.ljust(name_w)} | {fmt(sz).rjust(size_w)}')

    click.echo('-' * len(header))
    click.echo(f'{"TOTAL (rows)".ljust(name_w)} | {fmt(sum_rows).rjust(size_w)}')
    click.echo(f'{"TOTAL (pg_catalog)".ljust(name_w)} | {fmt(db_total).rjust(size_w)}')



if __name__ == '__main__':
    cli()
