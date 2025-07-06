#!/usr/bin/env python3
"""elpis_nautilus.cli

Click-based unified command-line interface for Elpis Nautilus utilities.
"""
from __future__ import annotations

import logging
import re
from typing import Final, NamedTuple
from datetime import datetime, date
from calendar import month_name

import click
from tabulate import tabulate
from bs4 import BeautifulSoup

from elpis_nautilus.data_downloaders.downloader_main import (
    HISTDATA_BASE,
    _ensure_tmp_dir,
    _session,
    download_histdata
)

# Initialize logging for CLI
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

LOGGER: Final = logging.getLogger("elpis.cli")


class InstrumentInfo(NamedTuple):
    """
    Represents a financial instrument’s available range and interval.

    Attributes:
        symbol (str): The instrument’s ticker or symbol (e.g., "EURUSD").
        date_from (datetime): The first date for which tick data is available.
        date_to (datetime): The last date for which tick data is available.
        interval (str): The data interval or granularity
        (e.g., "tick", "1min").
    """
    symbol: str
    date_from: datetime
    date_to: datetime
    interval: str

##################################################################
# HistData discovery
##################################################################


_MONTH_MAP: Final[dict[str, int]] = {
    m: i
    for i, m in enumerate(month_name)
    if m
}


def _histdata_info() -> list[InstrumentInfo]:
    """
    Scrape HistData.com for all available tick‐data instruments and
    their date ranges.

    Returns:
        List[InstrumentInfo]: one entry per symbol with (symbol, date_from,
        date_to, "tick").
    """
    resp = _session().get(f"{HISTDATA_BASE}/?/ascii/tick-data-quotes/",
                          timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    infos: list[InstrumentInfo] = []
    for td in soup.find_all("td"):
        link = next(
            (a for a in td.find_all("a", href=True)
             if "/ascii/tick-data-quotes/" in a["href"]),
            None
        )
        if not link or not (strong := link.find("strong")):
            continue

        symbol = strong.text.replace("/", "").strip().upper()
        m = re.search(r"\((\d{4})/(\w+)\)", td.get_text(" "))
        if not m:
            LOGGER.warning("No start date for %s", symbol)
            continue

        year = int(m.group(1))
        month = _MONTH_MAP.get(m.group(2).capitalize())
        if not month:
            LOGGER.error("Unknown month '%s' for %s", m.group(2), symbol)
            continue

        date_from = datetime(year, month, 1)
        today = date.today()
        date_to = datetime(
            today.year - (today.month == 1),
            (today.month - 2) % 12 + 1,
            1
        )

        infos.append(InstrumentInfo(symbol, date_from, date_to, "tick"))

    return infos


##################################################################
# CLI setup
##################################################################

@click.group(help="Elpis CLI.")
@click.version_option(package_name="elpis_nautilus", prog_name="elpis")
def cli() -> None:
    """Top-level command group for the Elpis Nautilus CLI."""


@cli.group(help="Download market data from providers.")
def download() -> None:
    """Group of commands for downloading market data from
    supported providers."""


@download.command("histdata", help="Tick data from HistData.com")
@click.option("--symbol", required=True, help="Market symbol, e.g. EURUSD")
@click.option(
    "--from", "date_from",
    required=True,
    callback=lambda _ctx, _param, val: datetime.strptime(val, "%Y-%m"),
    help="Start YYYY-MM",
)
@click.option(
    "--to", "date_to",
    required=True,
    callback=lambda _ctx, _param, val: datetime.strptime(val, "%Y-%m"),
    help="End YYYY-MM",
)
def histdata_cmd(symbol: str, date_from: datetime, date_to: datetime) -> None:
    """Download tick data for a given symbol and
    date range from HistData.com."""
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
    """Group of commands for listing available instruments
    and their data ranges."""


@show_available.command("histdata",
                        help="Show available ticks from HistData.com")
def show_histdata() -> None:
    """Fetch and display all instruments with available
    tick-data ranges from HistData.com."""
    click.echo("Fetching metadata from HistData.com…", err=True)
    infos = _histdata_info()
    if not infos:
        click.echo("No instruments found.", err=True)
        raise SystemExit(1)
    rows = [
        [inf.symbol,
         inf.date_from.strftime("%Y-%m"),
         inf.date_to.strftime("%Y-%m"),
         inf.interval]
        for inf in infos
    ]
    click.echo(tabulate(rows,
                        headers=["instrument", "from", "to", "interval"],
                        tablefmt="psql"))


if __name__ == "__main__":
    cli()
