import sys
import json
import click
import psycopg2
import time
import shlex
import subprocess
from typing import List, Dict, Any
from datetime import datetime
from saxo_openapi import API
from elpis.crud.instrument_to_uic import instrument_to_uic
from elpis.crud.instrument import insert_instrument, delete_instrument, get_instrument
from elpis.crud.data import insert_prices, get_prices, delete_prices
from elpis.crud.plot import plot_saxo_data
from elpis.utils.config import settings

@click.group()
def cli():
    """
    CLI for instrument management: insert, delete, fetch, search.
    """
    pass

@cli.command('insert-instrument')
@click.argument('json_files', type=click.File('r'), nargs=-1)
def _insert_instrument_cmd(json_files):
    """
    Insert **or update** rows in *market.instrument* from JSON.

    • Accepts any number of JSON files **or** STDIN.  
    • Each JSON must be a list of objects with keys  
      `description, UIC, asset_type, symbol, currency, exchange`.  
    """
    # --- load JSON payloads ---
    try:
        sources = json_files or [sys.stdin]
        records: List[Dict[str, Any]] = []
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
        click.echo('Nothing to insert.')
        return

    # --- delegate to the core function ---
    summary = insert_instrument(records)

    # --- report back ---
    click.echo(f"✅  Inserted: {summary['inserted']}, "
               f"Updated: {summary['updated']}, "
               f"Skipped: {summary['skipped']}")


@cli.command('delete-instrument')
@click.option('--id',     'ids',    type=int,   multiple=True, help='Instrument id(s) to delete')
@click.option('--uic',    'uics',   type=int,   multiple=True, help='UIC(s) of instruments to delete')
@click.option('--symbol', 'symbols', type=str, multiple=True, help='Symbol(s) of instruments to delete')
def _delete_instrument_cmd(ids, uics, symbols):
    """
    Delete instruments by id, UIC, or symbol. Prompts for confirmation.
    """
    # --- fetch all candidates (you likely have this helper already) ---
    try:
        results = get_instrument(uic=None, asset_type=None)
    except Exception as e:
        click.echo(f"Error fetching instruments: {e}", err=True)
        sys.exit(1)

    # --- filter ---
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

    # --- preview & confirm ---
    click.echo('The following instruments will be deleted:')
    _print_table(to_delete)
    confirm = click.prompt('Type y or yes to confirm deletion', default='n')
    if confirm.lower() not in ('y', 'yes'):
        click.echo('Deletion cancelled.')
        sys.exit(0)

    # --- build keys and call core delete ---
    keys = [{'UIC': item['uic'], 'asset_type': item['asset_type']} for item in to_delete]
    deleted_count = delete_instrument(keys)

    click.echo(f"✅  Deleted: {deleted_count} instrument(s).")
    sys.exit(0)

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
def _get_instrument(uic, asset_type):
    """
    Fetch instruments from DB, optionally filtering by UIC and/or asset_type.
    Outputs a table of results.
    """
    try:
        results = get_instrument(uic=uic, asset_type=asset_type)
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
@click.option('--id',         'instrument_id', type=int,    help='market.instrument.id')
@click.option('--uic',                     type=int,    help='Instrument UIC for Saxo API')
@click.option('--assettype', 'asset_type',  type=str,    help='Instrument AssetType for Saxo API')
@click.option('--interval',  'interval_label', required=True,
              help="Interval label (e.g. '1m','5m','15m','1h','4h','1d','1w','1mo')")
@click.option('--start-time','start_time', required=True,
              help='Start time ISO8601, e.g. 2025-01-01T00:00:00')
@click.option('--verbose', '-v', is_flag=True, default=False,
              help='Show download progress per chunk')
def _insert_prices(
    instrument_id, uic, asset_type, interval_label, start_time, verbose
):
    """
    Load and upsert price data from Saxo into market.price.
    Provide either --id *or* both --uic and --assettype.
    """
    # 1) resolve instrument_id and uic/asset_type
    if instrument_id:
        try:
            conn = psycopg2.connect(
                host=settings.db_host, port=settings.db_port,
                dbname=settings.db_name, user=settings.db_user,
                password=settings.db_password
            )
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT uic, asset_type FROM market.instrument WHERE id = %s;",
                    (instrument_id,)
                )
                row = cur.fetchone()
            conn.close()
        except Exception as e:
            click.echo(f"Error looking up id={instrument_id}: {e}", err=True)
            sys.exit(1)
        if not row:
            click.echo(f"Instrument id={instrument_id} not found.", err=True)
            sys.exit(1)
        uic, asset_type = row
    else:
        if not (uic and asset_type):
            click.echo("You must supply either --id or both --uic and --assettype", err=True)
            sys.exit(1)
        try:
            conn = psycopg2.connect(
                host=settings.db_host, port=settings.db_port,
                dbname=settings.db_name, user=settings.db_user,
                password=settings.db_password
            )
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM market.instrument WHERE uic = %s AND asset_type = %s;",
                    (uic, asset_type)
                )
                row = cur.fetchone()
            conn.close()
        except Exception as e:
            click.echo(f"Error looking up {uic}/{asset_type}: {e}", err=True)
            sys.exit(1)
        if not row:
            click.echo(f"Instrument UIC={uic}, asset_type={asset_type} not found.", err=True)
            sys.exit(1)
        instrument_id = row[0]

    # 2) parse start time
    try:
        dt = datetime.fromisoformat(start_time)
    except ValueError:
        click.echo(f"Invalid start-time format: {start_time}", err=True)
        sys.exit(1)

    # 3) optional warning if data exists
    try:
        conn = psycopg2.connect(
            host=settings.db_host, port=settings.db_port,
            dbname=settings.db_name, user=settings.db_user,
            password=settings.db_password
        )
        with conn.cursor() as cur:
            # map label→id
            label_map = {'1m':1,'5m':2,'15m':3,'1h':4,'4h':5,'1d':6,'1w':7,'1mo':8}
            iid = label_map.get(interval_label)
            cur.execute(
                "SELECT COUNT(*), MIN(time_price) FROM market.price "
                "WHERE instrument_id = %s AND interval_id = %s;",
                (instrument_id, iid)
            )
            count, first_ts = cur.fetchone()
        conn.close()
        if count:
            click.echo(f"⚠️  Found {count} existing rows from {first_ts}.")
            confirm = click.prompt(
                "Type y or yes to overwrite and fetch fresh data", default="n"
            )
            if confirm.lower() not in ("y","yes"):
                click.echo("Operation cancelled.")
                sys.exit(0)
    except Exception:
        # on error, just proceed
        pass

    # 4) do it
    rows = insert_prices(
        instrument_id=instrument_id,
        uic=uic,
        asset_type=asset_type,
        interval_label=interval_label,
        start_time=dt,
        verbose=verbose
    )

    click.echo(f"✅  Upserted {rows} price rows for instrument id={instrument_id}.")
    sys.exit(0)
        
@cli.command('get-prices')
@click.option('--id',         'instrument_id', type=int,    help='Internal market.instrument.id')
@click.option('--uic',                      type=int,    help='Instrument UIC for Saxo API')
@click.option('--assettype',  'asset_type',  type=str,    help='Instrument AssetType for Saxo API')
@click.option('--interval',   'interval_label', required=True,
              help="Interval label (e.g. '1m','5m','15m','1h','4h','1d','1w','1mo')")
@click.option('--head',       type=int,    default=None, help='Show only the first N rows')
@click.option('--from-date',  'from_date', default=None, help='Filter rows with time_price >= this ISO timestamp')
@click.option('--to-date',    'to_date',   default=None, help='Filter rows with time_price <= this ISO timestamp')
def _get_prices(
    instrument_id, uic, asset_type, interval_label, head, from_date, to_date
):
    """
    Display stored prices for a given instrument and interval.

    Identification: --id OR (--uic and --assettype).
    Optional filters: --from-date, --to-date (ISO 8601), --head N.
    Only columns with at least one non-null value are shown.
    """
    try:
        rows, columns = get_prices(
            instrument_id, uic, asset_type,
            interval_label, head, from_date, to_date
        )
    except ValueError as e:
        click.echo(f"❌  {e}", err=True)
        sys.exit(1)

    if not rows:
        click.echo("No price data found.")
        return

    # ===== format table: only keep cols with any non-null =====
    keep_idx = [i for i, c in enumerate(columns)
                if any(row[i] is not None for row in rows)]
    keep_cols = [columns[i] for i in keep_idx]

    # compute column widths
    widths = [len(col) for col in keep_cols]
    for r in rows:
        for j, idx in enumerate(keep_idx):
            widths[j] = max(widths[j], len(str(r[idx])))

    def pad(val: str, col_i: int) -> str:
        return val if col_i == len(widths)-1 else val.ljust(widths[col_i])

    # header
    header = " | ".join(pad(col, i) for i, col in enumerate(keep_cols))
    sep    = "-+-".join("-" * widths[i] for i in range(len(widths)))
    click.echo(header)
    click.echo(sep)

    # rows
    for r in rows:
        line = " | ".join(pad(str(r[idx]), j)
                          for j, idx in enumerate(keep_idx))
        click.echo(line)
        
# ──────────────────────────────────────────────────────────────────────────────
# Delete rows from market.price
# ──────────────────────────────────────────────────────────────────────────────
@cli.command('delete-prices')
@click.option('--id',        'instrument_id', type=int,    help='market.instrument.id')
@click.option('--uic',                     type=int,    help='Instrument UIC')
@click.option('--assettype', 'asset_type',   type=str,    help='Instrument AssetType')
@click.option('--interval',  'interval_label', required=True,
              help="Interval label: 1m / 5m / 15m / 1h / 4h / 1d / 1w / 1mo")
@click.option('--from-time', 'from_time',    default=None,
              help="Delete from (inclusive) – ISO-8601, e.g. 2025-01-01T00:00:00")
@click.option('--to-time',   'to_time',      default=None,
              help="Delete to   (exclusive) – ISO-8601, e.g. 2025-12-31T23:59:59")
def _delete_prices_cmd(
    instrument_id, uic, asset_type,
    interval_label, from_time, to_time
):
    """
    Delete price rows from *market.price*.

    Supply --id **or** both --uic and --assettype, plus --interval.
    Optionally limit with --from-time / --to-time.
    """
    # ── resolve instrument_id ↔ (uic, asset_type) ─────────
    try:
        conn = psycopg2.connect(
            host=settings.db_host, port=settings.db_port,
            dbname=settings.db_name, user=settings.db_user,
            password=settings.db_password
        )
        with conn.cursor() as cur:
            if instrument_id:
                cur.execute(
                    "SELECT id FROM market.instrument WHERE id = %s;",
                    (instrument_id,)
                )
            else:
                if not (uic and asset_type):
                    click.echo('Provide --id *or* both --uic and --assettype', err=True)
                    sys.exit(1)
                cur.execute(
                    "SELECT id FROM market.instrument WHERE uic = %s AND asset_type = %s;",
                    (uic, asset_type)
                )
            row = cur.fetchone()
    finally:
        conn.close()

    if not row:
        click.echo("❌  Instrument not found.", err=True)
        sys.exit(1)
    resolved_id = row[0]

    # ── parse timestamps ───────────────────────────────────
    def _parse(ts, name):
        if ts is None:
            return None
        try:
            return datetime.fromisoformat(ts)
        except ValueError:
            click.echo(f"❌  Invalid {name} format: {ts}", err=True)
            sys.exit(1)

    t_from = _parse(from_time, "--from-time")
    t_to   = _parse(to_time,   "--to-time")

    # ── delegate everything else ───────────────────────────
    delete_prices(resolved_id, interval_label, t_from, t_to)
    
    
@cli.command('summary-prices')
@click.option('--separate', is_flag=True,
              help='Run the summary in a new terminal window')
def price_summary(separate):
    """
    Summarize each (symbol, asset_type, instrument_id, interval) in market.price
    with first/last time_price and row count.
    """
    if separate:
        argv = [shlex.quote(a) for a in sys.argv if a != '--separate']
        cmdline = " ".join(argv)
        terminal_cmd = [
            "gnome-terminal", "--",
            "bash", "-c",
            f"{cmdline}; echo; echo \"(press enter to close)\"; read"
        ]
        try:
            subprocess.Popen(terminal_cmd)
        except FileNotFoundError:
            click.echo("❌  gnome-terminal not found; adjust `terminal_cmd`.", err=True)
        return

    # --- POPRAWIONY SELECT ---
    sql = """
        SELECT
            i.symbol,                -- 1
            i.asset_type,            -- 2
            p.instrument_id,         -- 3
            ic.label         AS interval_label,
            MIN(p.time_price) AS first_time,
            MAX(p.time_price) AS last_time,
            COUNT(*)         AS row_count
        FROM market.price AS p
        JOIN market.instrument AS i
          ON p.instrument_id = i.id
        JOIN core.interval_code AS ic
          ON p.interval_id = ic.id
        GROUP BY
            i.symbol,
            i.asset_type,
            p.instrument_id,
            ic.label,
            ic.id
        ORDER BY
            p.instrument_id,
            ic.id;
    """

    start = time.monotonic()
    try:
        conn = psycopg2.connect(
            host=settings.db_host,
            port=settings.db_port,
            dbname=settings.db_name,
            user=settings.db_user,
            password=settings.db_password
        )
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
    except Exception as e:
        click.echo(f"❌  Database error: {e}", err=True)
        sys.exit(1)
    finally:
        if 'conn' in locals():
            conn.close()
    elapsed = time.monotonic() - start

    if not rows:
        click.echo("No price data found.")
        return

    headers    = ["symbol", "asset_type", "instrument_id", "interval", "from", "to", "row_count"]
    col_widths = [len(h) for h in headers]

    # długości kolumn – teraz sym i atype to już stringi
    for sym, atype, iid, interval, first, last, cnt in rows:
        col_widths[0] = max(col_widths[0], len(sym))
        col_widths[1] = max(col_widths[1], len(atype))
        col_widths[2] = max(col_widths[2], len(str(iid)))
        col_widths[3] = max(col_widths[3], len(interval))
        col_widths[4] = max(col_widths[4], len(first.isoformat()))
        col_widths[5] = max(col_widths[5], len(last.isoformat()))
        col_widths[6] = max(col_widths[6], len(str(cnt)))

    header_line = " | ".join(headers[i].ljust(col_widths[i]) for i in range(len(headers)))
    sep_line    = "-+-".join("-" * col_widths[i] for i in range(len(headers)))
    click.echo(header_line)
    click.echo(sep_line)

    for sym, atype, iid, interval, first, last, cnt in rows:
        parts = [
            sym.ljust(col_widths[0]),
            atype.ljust(col_widths[1]),
            str(iid).ljust(col_widths[2]),
            interval.ljust(col_widths[3]),
            first.isoformat().ljust(col_widths[4]),
            last.isoformat().ljust(col_widths[5]),
            str(cnt).rjust(col_widths[6]),
        ]
        click.echo(" | ".join(parts))

    click.echo("\n--------")
    click.echo(f"Query executed in {elapsed:.3f} seconds")

import json
import click
from typing import Any, Dict, List
from elpis.crud.plot import plot_saxo_data

import json
import sys
import click
from elpis.crud.plot import plot_saxo_data  # wherever you defined it

@cli.command('plot-prices')
@click.option('--separate', is_flag=True,
              help='Run the plotting in a new terminal window')
@click.option('--id',         'instrument_id', type=int, help='market.instrument.id')
@click.option('--uic',                        type=int, help='Instrument UIC for Saxo')
@click.option('--assettype',  'asset_type',   type=str, help='AssetType for Saxo')
@click.option('--interval',   'interval_label', required=True,
              help="Interval label: 1m 5m 15m 1h 4h 1d 1w 1mo")
@click.option('--from-date',  'from_date',    help='ISO timestamp start filter (>=)')
@click.option('--to-date',    'to_date',      help='ISO timestamp end   filter (<=)')
@click.option('--side',       'price_side',
              type=click.Choice(['ask','bid','mid'], case_sensitive=False),
              default='mid', show_default=True,
              help="Which price side to plot when Ask/Bid available")
@click.option('-v', '--verbose', is_flag=True, help='Verbose output')
@click.option('-i', '--indicator',
              multiple=True,
              help=(
                  "Indicator spec as JSON, e.g. "
                  "'{\"name\":\"SMA\",\"params\":{\"period\":30}}'. "
                  "Repeatable to add multiple indicators."
              ))
@click.option('--style', type=click.Choice(['bar','candle','line'], case_sensitive=False),
              default='candle', show_default=True,
              help="Plot style for Backtrader: bar, candle, or line")
@click.option('--mpl-style', default='quantum',
              type=click.Choice(['default','dark','quantum','cyberpunk'], case_sensitive=False),
              help="Matplotlib theme to apply before plotting")
def _plot_prices(
    separate,
    instrument_id, uic, asset_type,
    interval_label, from_date, to_date,
    price_side, verbose, indicator, style, mpl_style
):
    """
    Plot stored prices with DynamicStrat indicators.

    Identify instrument by --id or by the (uic, assettype) pair.
    Use --side ask|bid|mid to choose which columns to draw.
    Pass one or more --indicator JSON blobs to specify indicators.

    Example:
      elpis plot-prices --id 123 --interval 1h \
        -i '{"name":"SMA","params":{"period":50}}' \
        -i '{"name":"MACD","params":{"period_me1":12,"period_me2":26}}'
    """
    # 0) If requested, re-spawn this same command in a new terminal
    if separate:
        argv = [shlex.quote(a) for a in sys.argv if a != '--separate']
        cmdline = " ".join(argv)
        terminal_cmd = [
            "gnome-terminal", "--",
            "bash", "-c",
            f"{cmdline}; echo; echo \"(press enter to close)\"; read"
        ]
        try:
            subprocess.Popen(terminal_cmd)
        except FileNotFoundError:
            click.echo("❌  gnome-terminal not found; adjust `terminal_cmd`.", err=True)
        return

    # 1) Parse JSON specs
    try:
        specs = [json.loads(spec) for spec in indicator]
    except json.JSONDecodeError as e:
        click.echo(f"❌  Invalid indicator JSON: {e}", err=True)
        sys.exit(1)

    # 2) Call the plotting helper
    try:
        plot_saxo_data(
            instrument_id  = instrument_id,
            uic            = uic,
            asset_type     = asset_type,
            interval_label = interval_label,
            from_date      = from_date,
            to_date        = to_date,
            price_side     = price_side.lower(),
            indicator      = specs,
            verbose        = verbose,
            style          = style.lower(),
            mpl_style_name = mpl_style,
        )
    except Exception as exc:
        click.echo(f"❌  Error: {exc}", err=True)
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
