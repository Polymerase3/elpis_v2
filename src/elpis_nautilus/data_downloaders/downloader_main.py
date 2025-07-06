#!/usr/bin/env python3
"""data_download.py

CLI + programmatic downloader for HistData.com tick data.

Changelog
---------
* **2025‑07‑05** – Added _ensure_logger() so log messages appear even when the
  module is imported and download_histdata() is called programmatically (no
  CLI). The helper attaches a StreamHandler to logger if none exist and sets
  the level from settings.log_level.
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Iterable

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

# ---------------------------------------------------------------------------
# Centralised settings
# ---------------------------------------------------------------------------
from elpis_nautilus.utils.config import settings

###############################################################################
# Globals & logging
###############################################################################
logger = logging.getLogger("data_download")

# Attach a handler only if the root logger (or any external code) has not
# already configured logging. This ensures logs are visible when the module is
# used programmatically.


def _ensure_logger() -> None:
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        )
        logger.addHandler(handler)
    logger.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))
    # Prevent messages from propagating up to the root logger
    # (avoids double‐logging)
    logger.propagate = False


_ensure_logger()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
    "Accept":
        "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

###############################################################################
# Constants for HistData.com
###############################################################################
HISTDATA_BASE = "https://www.histdata.com/download-free-forex-historical-data"

###############################################################################
# Helper functions
###############################################################################


def _ensure_tmp_dir() -> Path:
    tmp = settings.tmp_dir
    if tmp.exists():
        if tmp.is_dir():
            return tmp
        sys.exit(f"Configuration error: '{tmp}' exists but is not a directory")
    ans = input(f"Create temporary directory '{tmp}'? [y/N] ").strip().lower()
    if ans not in {"y", "yes"}:
        sys.exit("Aborted – tmp dir required.")
    tmp.mkdir(parents=True, exist_ok=True)
    logger.info("Created %s", tmp)
    return tmp


def _year_month_range(start: datetime,
                      end: datetime) -> Iterable[tuple[int, int]]:
    cur = datetime(start.year, start.month, 1)
    end_marker = datetime(end.year, end.month, 1)
    while cur <= end_marker:
        yield cur.year, cur.month
        cur = datetime(cur.year + (cur.month // 12), (cur.month % 12) + 1, 1)

###############################################################################
# HistData workflow
###############################################################################


_SESSION: requests.Session | None = None  # lazily initialised


def _session() -> requests.Session:
    global _SESSION 
    if _SESSION is None:
        _SESSION = requests.Session()
        _SESSION.headers.update(HEADERS)
    return _SESSION


def _histdata_page(symbol: str, year: int, month: int) -> str:
    return (
        f"{HISTDATA_BASE}"
        f"?/ascii/tick-data-quotes/"
        f"{symbol.lower()}/"
        f"{year}/"
        f"{month}"
    )


def _extract_filename(content_disposition: str) -> str | None:
    match = re.search(r"filename=([^;]+)", content_disposition)
    if match:
        return match.group(1).strip().strip("\"")
    return None


def _fetch_zip(symbol: str, year: int, month: int, dest: Path) -> Path | None:
    """Download one monthly ZIP; return path or *None* on failure."""
    sess = _session()
    page_url = _histdata_page(symbol, year, month)
    try:
        page = sess.get(page_url, timeout=20)
        page.raise_for_status()
    except requests.RequestException as exc:
        logger.error("Listing page failed %s – %s", page_url, exc)
        return None

    soup = BeautifulSoup(page.text, "html.parser")

    # 1) Try the standard form-based download
    form = soup.find("form", id="file_down")
    if form:
        payload = {
            inp["name"]: inp.get("value", "")
            for inp in form.find_all("input", attrs={"name": True})
        }
        form_action = urljoin(page_url, form.get("action", "get.php"))
        downloader = sess.post
        dl_args = {
            "data": payload,
            "headers": {"Referer": page_url},
            "stream": True,
        }
    # 2) Fallback: grab the hidden <a id="a_file"> link and POST its filename
    else:
        link = soup.find("a", id="a_file")
        if not link or not link.text.strip().lower().endswith(".zip"):
            logger.error("No download form or ZIP link found on %s", page_url)
            return None
        zip_name = link.text.strip()
        form_action = urljoin(page_url, "get.php")
        downloader = sess.post
        dl_args = {
            "data": {"file": zip_name},
            "headers": {"Referer": page_url},
            "stream": True,
        }

    # perform the actual download
    try:
        resp = downloader(form_action, **dl_args, timeout=60)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.error("Download failed for %s %04d/%02d – %s",
                     symbol, year, month, exc)
        return None

    ctype = resp.headers.get("Content-Type", "").lower()
    disp = resp.headers.get("Content-Disposition", "")

    # bail out on HTML or missing ZIP-disposition
    if "html" in ctype or "zip" not in disp.lower():
        logger.error(
            "Unexpected response (%r, %r) for %s %04d/%02d – skipping",
            ctype, disp, symbol, year, month
        )
        return None

    # write out the file
    fname = _extract_filename(disp) or zip_name
    zip_path = dest / fname
    with zip_path.open("wb") as fh:
        for chunk in resp.iter_content(chunk_size=1 << 16):
            if chunk:
                fh.write(chunk)

    size_bytes = zip_path.stat().st_size
    size_mb = size_bytes / (1024 * 1024)
    logger.info("Saved %s (%.2f MB)", zip_path.name, size_mb)
    return zip_path



def _extract_zip(zip_path: Path, dest: Path) -> None:
    try:
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(dest)
    except zipfile.BadZipFile as exc:
        logger.error("Bad ZIP %s – %s", zip_path.name, exc)
        zip_path.unlink(missing_ok=True)
        return
    finally:
        # Always remove the ZIP itself
        zip_path.unlink(missing_ok=True)

    # Remove any .txt files in dest
    for txt in dest.glob("*.txt"):
        try:
            txt.unlink()
        except OSError as exc:
            logger.warning("Could not delete %s – %s", txt.name, exc)


def download_histdata(symbol: str,
                      start: datetime,
                      end: datetime,
                      dest: Path) -> None:
    """Programmatic API: download HistData tick
    ZIPs and leave CSVs in *dest*."""
    logger.info(
        "Downloading %s %s → %s into %s",
        symbol,
        start.strftime("%Y-%m"),
        end.strftime("%Y-%m"),
        dest,
    )
    for y, m in _year_month_range(start, end):
        zip_path = _fetch_zip(symbol, y, m, dest)
        if zip_path:
            _extract_zip(zip_path, dest)
    logger.info("Completed %s", symbol)
