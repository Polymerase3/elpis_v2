import pytest
from datetime import datetime
from click.testing import CliRunner
from elpis_nautilus.cli import cli

# --- Fixtures & Helpers --- #


@pytest.fixture
def runner():
    return CliRunner()

# --- Mock data for show-available --- #


MOCK_INFOS = [
    # symbol, date_from, date_to, interval
    ("EURUSD", datetime(2020, 1, 1), datetime(2025, 6, 1), "tick"),
    ("GBPUSD", datetime(2019, 5, 1), datetime(2025, 5, 1), "tick"),
]


class DummyInfo:
    def __init__(self, symbol, date_from, date_to, interval):
        self.symbol = symbol
        self.date_from = date_from
        self.date_to = date_to
        self.interval = interval

# --- Tests for show-available histdata --- #


def test_show_available_histdata_success(monkeypatch, runner):
    # Monkeypatch _histdata_info to return our mock infos
    monkeypatch.setattr(
        "elpis_nautilus.cli._histdata_info",
        lambda: [DummyInfo(*t) for t in MOCK_INFOS],
    )

    result = runner.invoke(cli, ["show-available", "histdata"])
    assert result.exit_code == 0
    # It should print a psql-style table with headers
    assert "instrument" in result.output
    assert "from" in result.output
    assert "EURUSD" in result.output
    assert "2020-01" in result.output
    assert "tick" in result.output


def test_show_available_histdata_empty(monkeypatch, runner):
    # Return empty list → should echo "No instruments found." and exit 1
    monkeypatch.setattr("elpis_nautilus.cli._histdata_info", lambda: [])
    result = runner.invoke(cli, ["show-available", "histdata"])
    assert result.exit_code == 1
    assert "No instruments found." in result.output

# --- Tests for download histdata command --- #


def test_histdata_date_validation(runner):
    # date_to < date_from should raise BadParameter
    result = runner.invoke(
        cli,
        ["download", "histdata", "--symbol", "EURUSD",
         "--from", "2025-06", "--to", "2024-06"],
    )
    assert result.exit_code != 0
    assert "--to' must be >= '--from" in result.output


def test_histdata_abort(monkeypatch, runner, tmp_path):
    # Test user choosing "no" at confirmation
    monkeypatch.setattr("elpis_nautilus.cli._ensure_tmp_dir", lambda: tmp_path)
    monkeypatch.setattr("click.confirm", lambda *args, **kwargs: False)

    result = runner.invoke(
        cli,
        ["download", "histdata", "--symbol", "GBPUSD",
         "--from", "2024-01", "--to", "2024-02"],
    )
    assert result.exit_code == 0
    assert "Aborted." in result.output


def test_histdata_success(monkeypatch, runner, tmp_path):
    # Test full path: tmp dir, confirm yes, download_histdata called
    calls = {}

    def fake_ensure():
        return tmp_path

    def fake_download(symbol, df, dt, tmp):
        # record inputs
        calls['symbol'] = symbol
        calls['date_from'] = df
        calls['date_to'] = dt
        calls['tmp'] = tmp
    monkeypatch.setattr("elpis_nautilus.cli._ensure_tmp_dir", fake_ensure)
    monkeypatch.setattr("elpis_nautilus.cli.download_histdata", fake_download)
    monkeypatch.setattr("click.confirm", lambda *args, **kwargs: True)

    result = runner.invoke(
        cli,
        ["download", "histdata", "--symbol", "usdjpy",
         "--from", "2024-03", "--to", "2024-04"],
    )
    assert result.exit_code == 0
    # Check download_histdata was called with uppercase symbol
    assert calls['symbol'] == "USDJPY"
    assert calls['date_from'] == datetime(2024, 3, 1)
    assert calls['date_to'] == datetime(2024, 4, 1)
    assert calls['tmp'] == tmp_path
    assert f"Done – files in {tmp_path}" in result.output
