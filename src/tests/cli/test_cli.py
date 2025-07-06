# tests/test_cli.py
"""
Unit-tests for elpis_nautilus.cli
Goal: ≥90 % coverage without touching the network or filesystem.
"""

from __future__ import annotations

import sys
import types
from datetime import date, datetime

import pytest
from click.testing import CliRunner
from pathlib import Path

###############################################################################
# 1.  Build fake dependency tree *before* importing the CLI under test.
###############################################################################
# ── 1. Make the src/ directory importable ────────────────────────
ROOT = Path(__file__).resolve().parents[2]   # project root
sys.path.insert(0, str(ROOT / "src"))        # add src/ to sys.path

# ── 2. Fake only the downloader_main dependency ──────────────────
dl_pkg = types.ModuleType("elpis_nautilus.data_downloaders")
dl_pkg.__path__ = []                             # mark as package
sys.modules["elpis_nautilus.data_downloaders"] = dl_pkg

dl_mod = types.ModuleType("elpis_nautilus.data_downloaders.downloader_main")
dl_mod.HISTDATA_BASE = "https://example.com"

def _ensure_tmp_dir() -> str:
    return "/tmp/elpis"
dl_mod._ensure_tmp_dir = _ensure_tmp_dir

def _download_histdata(symbol, date_from, date_to, tmp):
    _download_histdata.calls.append((symbol, date_from, date_to, tmp))
_download_histdata.calls = []
dl_mod.download_histdata = _download_histdata

class _DummyResp:
    status_code = 200
    def __init__(self, text): self.text = text
    def raise_for_status(self): pass

class _DummySession:
    HTML = """
    <table>
      <tr><td><a href="/ascii/tick-data-quotes/EURUSD">
        <strong>EUR/USD</strong></a> (2020/August)</td></tr>
      <tr><td><a href="/ascii/tick-data-quotes/GBPUSD">
        <strong>GBP/USD</strong></a> (2019/January)</td></tr>
    </table>
    """
    def get(self, *_a, **_kw): return _DummyResp(self.HTML)

dl_mod._session = lambda: _DummySession()
sys.modules["elpis_nautilus.data_downloaders.downloader_main"] = dl_mod

# ── 3. Now import the real CLI implementation ────────────────────
import elpis_nautilus.cli as cli


###############################################################################
# 2.  Shared Pytest fixtures
###############################################################################
@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()

@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    """
    Make cli.date.today() always return 2025-07-06.

    We can’t patch the .today attribute directly (immutable C descriptor),
    so we replace the *entire* date class inside elpis_nautilus.cli with a
    subclass that overrides today().
    """
    from datetime import date as _date

    class _FixedDate(_date):
        @classmethod
        def today(cls):
            return cls(2025, 7, 6)

    # Replace the 'date' symbol that elpis_nautilus.cli imported.
    monkeypatch.setattr(cli, "date", _FixedDate)

###############################################################################
# 3.  Unit-tests for internal helper: _histdata_info
###############################################################################
def test_histdata_info_parsing():
    infos = cli._histdata_info()
    # Two <td>s → two InstrumentInfo objects
    assert {i.symbol for i in infos} == {"EURUSD", "GBPUSD"}
    eur = next(i for i in infos if i.symbol == "EURUSD")
    # Start date matches HTML (2020-08-01)
    assert eur.date_from == datetime(2020, 8, 1)
    # End date = the first day of the month *two months before* frozen today
    assert eur.date_to == datetime(2025, 6, 1)
    # Interval fixed to "tick"
    assert eur.interval == "tick"

###############################################################################
# 4.  CLI command: download histdata
###############################################################################
def test_histdata_cmd_happy_path(monkeypatch, runner):
    """Positive flow – user confirms download."""
    # auto-confirm
    monkeypatch.setattr(cli.click, "confirm", lambda *_a, **_kw: True)

    res = runner.invoke(
        cli.cli,
        ["download", "histdata",
         "--symbol", "eurusd",
         "--from", "2024-01",
         "--to", "2024-03"],
    )
    assert res.exit_code == 0
    # download_histdata called exactly once with up-cased symbol
    assert _download_histdata.calls == [
        ("EURUSD", datetime(2024, 1, 1), datetime(2024, 3, 1), "/tmp/elpis")
    ]
    assert "Done – files in /tmp/elpis" in res.output

def test_histdata_cmd_user_aborts(monkeypatch, runner):
    _download_histdata.calls.clear()        # ← RESET
    monkeypatch.setattr(cli.click, "confirm", lambda *_a, **_kw: False)
    res = runner.invoke(
        cli.cli,
        ["download", "histdata",
         "--symbol", "eurusd",
         "--from", "2024-01",
         "--to", "2024-02"],
    )
    assert res.exit_code == 0
    # No call when user aborts
    assert not _download_histdata.calls
    assert "Aborted." in res.output

def test_histdata_cmd_invalid_range(runner):
    """--to earlier than --from yields BadParameter."""
    res = runner.invoke(
        cli.cli,
        ["download", "histdata",
         "--symbol", "eurusd",
         "--from", "2024-03",
         "--to", "2024-01"],
    )
    assert res.exit_code != 0
    assert "'--to' must be >=" in res.output

###############################################################################
# 5.  CLI command: show-available histdata
###############################################################################
def test_show_histdata_success(monkeypatch, runner):
    res = runner.invoke(cli.cli, ["show-available", "histdata"])
    assert res.exit_code == 0
    # Table should contain header and one known symbol
    assert "instrument" in res.output.lower()
    assert "EURUSD" in res.output

def test_show_histdata_empty(monkeypatch, runner):
    monkeypatch.setattr(cli, "_histdata_info", lambda: [])
    res = runner.invoke(cli.cli, ["show-available", "histdata"])
    assert res.exit_code == 1           # SystemExit(1)
    assert "No instruments found." in res.output
