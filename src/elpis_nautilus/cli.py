#!/usr/bin/env python3
"""elpis_nautilus.cli

Click-based unified command-line interface for Elpis Nautilus utilities.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Final, NamedTuple
from datetime import datetime, date
from calendar import month_name
from pathlib import Path

import click
from tabulate import tabulate
from bs4 import BeautifulSoup

from elpis_nautilus.data_downloaders.downloader_main import (
    HISTDATA_BASE,
    _ensure_tmp_dir,
    _session,
    download_histdata,
    logger as _dl_logger,
)

# Initialize logging for CLI
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
_dl_logger  # noqa: F401
LOGGER: Final = logging.getLogger("elpis.cli")

class InstrumentInfo(NamedTuple):
    symbol: str
    date_from: datetime
    date_to: datetime
    interval: str

##################################################################
# HistData discovery
##################################################################

_MONTH_MAP: Final[dict[str, int]] = {m: i for i, m in enumerate(month_name) if m}

def _histdata_info() -> list[InstrumentInfo]:
    """Scrape HistData homepage for symbols and their start dates."""
    # Fetch instrument list page
    list_url = f"{HISTDATA_BASE}/?/ascii/tick-data-quotes/"
    resp = _session().get(list_url, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    
    print(list_url)
    infos: list[InstrumentInfo] = []
    # Each instrument is in a <td> with an <a href> containing '/ascii/tick-data-quotes/'
    for td in soup.find_all("td"):
        link = None
        for a in td.find_all("a", href=True):
            if "/ascii/tick-data-quotes/" in a["href"]:
                link = a
                break
        if not link:
            continue
        # Symbol inside <strong>, e.g. <strong>EUR/USD</strong>
        strong = link.find("strong")
        if not strong:
            continue
        sym = strong.text.strip().replace("/", "").upper()
        # After the <br>, text like '(2000/May)'
        raw = td.get_text(separator=" ")
        m = re.search(r"\((\d{4})/(\w+)\)", raw)
        if not m:
            LOGGER.warning("No start date for %s", sym)
            continue
        year, mon = int(m.group(1)), m.group(2)
        mon_num = _MONTH_MAP.get(mon.capitalize())
        if not mon_num:
            LOGGER.error("Unknown month '%s' for %s", mon, sym)
            continue
        date_from = datetime(year, mon_num, 1)
        # End date = last complete month
        today = date.today()
        if today.month == 1:
            end_year, end_month = today.year - 1, 12
        else:
            end_year, end_month = today.year, today.month - 1
        date_to = datetime(end_year, end_month, 1)
        infos.append(InstrumentInfo(sym, date_from, date_to, "tick"))
    return infos

##################################################################
# CLI setup
##################################################################

@click.group(help="Elpis CLI.")
@click.version_option(package_name="elpis_nautilus", prog_name="elpis")
def cli() -> None:
    pass

@cli.group(help="Download market data from providers.")
def download() -> None:
    pass

@download.command("histdata", help="Tick data from HistData.com")
@click.option("--symbol", required=True, help="Market symbol, e.g. EURUSD")
@click.option(
    "--from", "date_from",
    required=True,
    callback=lambda _ctx,_param,val: datetime.strptime(val, "%Y-%m"),
    help="Start YYYY-MM",
)
@click.option(
    "--to", "date_to",
    required=True,
    callback=lambda _ctx,_param,val: datetime.strptime(val, "%Y-%m"),
    help="End YYYY-MM",
)
def histdata_cmd(symbol: str, date_from: datetime, date_to: datetime) -> None:
    if date_to < date_from:
        raise click.BadParameter("'--to' must be >= '--from'")
    tmp = _ensure_tmp_dir()
    if not click.confirm(f"Proceed with {symbol.upper()}?", default=True):
        click.echo("Aborted.")
        return
    download_histdata(symbol.upper(), date_from, date_to, tmp)
    click.echo(f"Done – files in {tmp}")

@cli.group(name="show-available", help="List instruments & date ranges.")
def show_available() -> None:
    pass

@show_available.command("histdata", help="Show available ticks from HistData.com")
def show_histdata() -> None:
    click.echo("Fetching metadata from HistData.com…", err=True)
    infos = _histdata_info()
    if not infos:
        click.echo("No instruments found.", err=True)
        raise SystemExit(1)
    rows = [
        [inf.symbol, inf.date_from.strftime("%Y-%m"), inf.date_to.strftime("%Y-%m"), inf.interval]
        for inf in infos
    ]
    click.echo(tabulate(rows, headers=["instrument","from","to","interval"], tablefmt="psql"))

if __name__ == "__main__":
    cli()
