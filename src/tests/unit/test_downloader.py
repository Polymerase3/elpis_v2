import zipfile
from datetime import datetime

import pytest
import requests

# Dynamically load the downloader_main module from src directory
import pathlib
import importlib.util

ROOT = pathlib.Path(__file__).resolve().parents[2]
module_path = ROOT / "elpis_nautilus" / "data_downloaders" / "downloader_main.py"
spec = importlib.util.spec_from_file_location("downloader_main", str(module_path))
dm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dm)

# ==== Tests for ensure_tmp_dir ==== 
import builtins
from types import SimpleNamespace

def test_ensure_tmp_dir_exists_dir(tmp_path, monkeypatch):
    # tmp_dir exists and is dir; override entire settings
    dummy_settings = SimpleNamespace(tmp_dir=tmp_path, log_level='INFO')
    monkeypatch.setattr(dm, 'settings', dummy_settings)
    result = dm._ensure_tmp_dir()
    assert result == tmp_path


def test_ensure_tmp_dir_exists_file(tmp_path, monkeypatch):
    # tmp_dir exists but is file
    file_path = tmp_path / 'file'
    file_path.write_text('x')
    dummy_settings = SimpleNamespace(tmp_dir=file_path, log_level='INFO')
    monkeypatch.setattr(dm, 'settings', dummy_settings)
    with pytest.raises(SystemExit) as exc:
        dm._ensure_tmp_dir()
    assert "exists but is not a directory" in str(exc.value)


def test_ensure_tmp_dir_user_declines(tmp_path, monkeypatch, capsys):
    # tmp_dir does not exist and user says no
    new_dir = tmp_path / 'new'
    dummy_settings = SimpleNamespace(tmp_dir=new_dir, log_level='INFO')
    monkeypatch.setattr(dm, 'settings', dummy_settings)
    monkeypatch.setattr(builtins, 'input', lambda prompt: 'n')
    with pytest.raises(SystemExit) as exc:
        dm._ensure_tmp_dir()
    assert "Aborted" in str(exc.value)


def test_ensure_tmp_dir_user_accepts(tmp_path, monkeypatch):
    # tmp_dir does not exist and user says yes
    new_dir = tmp_path / 'new'
    dummy_settings = SimpleNamespace(tmp_dir=new_dir, log_level='INFO')
    monkeypatch.setattr(dm, 'settings', dummy_settings)
    monkeypatch.setattr(builtins, 'input', lambda prompt: 'y')
    monkeypatch.setattr(dm.logger, 'info', lambda *args, **kwargs: None)
    result = dm._ensure_tmp_dir()
    assert new_dir.exists() and new_dir.is_dir()
    assert result == new_dir

# ==== Tests for fetch_zip error branches ====

from bs4 import BeautifulSoup

def make_response(text='', status=200, headers=None, raise_exception=None):
    class Resp:
        def __init__(self):
            self.text = text
            self.status_code = status
            self.headers = headers or {}
        def raise_for_status(self):
            if raise_exception:
                raise raise_exception
        def iter_content(self, chunk_size):
            yield b'data'
    return Resp()

class DummySession:
    def __init__(self):
        self.headers = {}
        self.requests = []
    def get(self, url, timeout):
        return make_response(text='<html></html>', status=404,
                              raise_exception=requests.RequestException('fail'))
    def post(self, url, **kwargs):
        return make_response(text='', status=200, headers={
            'Content-Type':'application/zip',
            'Content-Disposition':'attachment; filename="f.zip"'
        })

def test_fetch_zip_page_fail(monkeypatch, tmp_path):
    monkeypatch.setattr(dm, '_session', lambda: DummySession())
    path = dm._fetch_zip('SYM', 2020, 1, tmp_path)
    assert path is None


def test_fetch_zip_no_form_no_link(monkeypatch, tmp_path):
    # valid page but no form and no link
    class Sess(DummySession):
        def get(self, url, timeout):
            return make_response(text='<html><body></body></html>', status=200)
    monkeypatch.setattr(dm, '_session', lambda: Sess())
    path = dm._fetch_zip('SYM', 2020, 1, tmp_path)
    assert path is None


def test_fetch_zip_fallback_link_success(monkeypatch, tmp_path):
    # page with a_file link
    link_html = '<a id="a_file">file.zip</a>'
    class Sess(DummySession):
        def get(self, url, timeout):
            return make_response(text=f'<html>{link_html}</html>', status=200)
    monkeypatch.setattr(dm, '_session', lambda: Sess())
    # monkeypatch post to return zip content
    def fake_post(self, url, **kwargs):
        return make_response(text='', status=200, headers={
            'Content-Type':'application/octet-zip',
            'Content-Disposition':'attachment; filename="f.zip"'
        })
    monkeypatch.setattr(Sess, 'post', fake_post)
    path = dm._fetch_zip('SYM', 2020, 2, tmp_path)
    assert path.name == 'f.zip'
    assert path.exists()


# ==== Additional tests to increase coverage ==== 

def test_extract_filename_no_quote_and_extra_semicolon():
    disp = 'attachment; filename=data2.zip; charset=utf-8'
    assert dm._extract_filename(disp) == 'data2.zip'


def test_fetch_zip_html_response(monkeypatch, tmp_path):
    # Mock GET ok, fallback form, but POST returns HTML content
    class Sess(DummySession):
        def get(self, url, timeout):
            return make_response(text='<html><body><a id="a_file">file.zip</a></body></html>', status=200)
    monkeypatch.setattr(dm, '_session', lambda: Sess())
    # Fake POST with HTML content type
    def fake_post(self, url, **kwargs):
        return make_response(text='<html>', status=200, headers={
            'Content-Type':'text/html',
            'Content-Disposition':'attachment; filename="f.zip"'
        })
    monkeypatch.setattr(Sess, 'post', fake_post)
    path = dm._fetch_zip('SYM', 2020, 3, tmp_path)
    assert path is None


def test_fetch_zip_form_success(monkeypatch, tmp_path):
    # page with form-based download
    form_html = ('<form id="file_down" action="get.php">'
                 '<input name="file" value="f2.zip"/>'
                 '<input name="token" value="abc"/>'
                 '</form>')
    class Sess(DummySession):
        def get(self, url, timeout):
            return make_response(text=f'<html>{form_html}</html>', status=200)
    monkeypatch.setattr(dm, '_session', lambda: Sess())
    # Fake POST returns proper zip
    def fake_post(self, url, data, headers, stream, timeout):
        assert data['file'] == 'f2.zip'
        return make_response(text='', status=200, headers={
            'Content-Type':'application/zip',
            'Content-Disposition':'attachment; filename="f2.zip"'
        })
    monkeypatch.setattr(Sess, 'post', fake_post)
    path = dm._fetch_zip('SYM', 2020, 4, tmp_path)
    assert path.name == 'f2.zip'
    assert path.exists()


def test_download_histdata_full_cycle(monkeypatch, tmp_path):
    # Simulate two months, one succeeds, one fails
    fetched = []
    extracted = []
    def fake_fetch(symbol, y, m, dest):
        fetched.append((y, m))
        if m == 5:
            f = tmp_path / 'x.zip'
            f.write_bytes(b'zip')
            return f
        return None
    def fake_extract(zip_path, dest):
        extracted.append(zip_path.name)
    monkeypatch.setattr(dm, '_fetch_zip', fake_fetch)
    monkeypatch.setattr(dm, '_extract_zip', fake_extract)
    dm.download_histdata('SYM', datetime(2020, 4, 1), datetime(2020, 5, 31), tmp_path)
    assert fetched == [(2020, 4), (2020, 5)]
    assert extracted == ['x.zip']


# ==== Tests for basic helpers ==== 

def test_year_month_range_single_month():
    start = datetime(2021, 5, 10)
    end = datetime(2021, 5, 20)
    assert list(dm._year_month_range(start, end)) == [(2021, 5)]


def test_year_month_range_multiple_months():
    start = datetime(2021, 12, 15)
    end = datetime(2022, 1, 5)
    assert list(dm._year_month_range(start, end)) == [(2021, 12), (2022, 1)]


def test_histdata_page_url():
    url = dm._histdata_page('TestSym', 1999, 11)
    assert url.startswith(dm.HISTDATA_BASE)
    assert 'testsym/1999/11' in url


def test_session_singleton_and_headers(monkeypatch):
    # Dummy session for headers
    class DummySess:
        def __init__(self):
            self.headers = {}
        def headers_update(self, d):
            self.headers.update(d)
    monkeypatch.setattr(requests, 'Session', DummySess)
    # reset SESSION
    dm._SESSION = None
    s1 = dm._session()
    s2 = dm._session()
    assert s1 is s2
    for k in dm.HEADERS:
        assert k in s1.headers


def test_extract_filename_quotes_and_plain():
    assert dm._extract_filename('attachment; filename="abc.zip"') == 'abc.zip'
    assert dm._extract_filename('attachment; filename=xyz.zip') == 'xyz.zip'

# ==== Tests for extract_zip (cleanup and error) ==== 

def test_extract_zip_success_and_txt_removal(tmp_path):
    # Create a zip containing csv and txt
    z = tmp_path / 'test.zip'
    out = tmp_path / 'out'
    out.mkdir()
    with zipfile.ZipFile(z, 'w') as zf:
        zf.writestr('f.csv', '1,2,3')
        zf.writestr('f.txt', 'hello')
    # Call extract
    dm._extract_zip(z, out)
    assert not z.exists()
    assert (out / 'f.csv').exists()
    assert not (out / 'f.txt').exists()


def test_extract_zip_bad_zip_removes_file(monkeypatch, tmp_path):
    # Create invalid zip file
    z = tmp_path / 'bad.zip'
    z.write_bytes(b'bad')
    out = tmp_path / 'out'
    out.mkdir()
    # Should not raise and should remove z
    dm._extract_zip(z, out)
    assert not z.exists()


def test_extract_zip_txt_unlink_warning(monkeypatch, tmp_path):
    # Create a zip with txt
    z = tmp_path / 't.zip'
    out = tmp_path / 'out'
    out.mkdir()
    with zipfile.ZipFile(z, 'w') as zf:
        zf.writestr('a.txt', 'data')
    # Monkeypatch unlink to raise for .txt
    import pathlib as _pl
    orig_unlink = _pl.Path.unlink
    def fake_unlink(self, *args, **kwargs):
        if self.suffix == '.txt':
            raise OSError('cannot delete')
        return orig_unlink(self, *args, **kwargs)
    monkeypatch.setattr(_pl.Path, 'unlink', fake_unlink)
    # Capture warning
    warnings = []
    monkeypatch.setattr(dm.logger, 'warning', lambda *args, **kwargs: warnings.append(args))
    dm._extract_zip(z, out)
    # zip removed, txt still present
    assert not z.exists()
    assert (out / 'a.txt').exists()
    assert warnings, 'Expected a warning for txt unlink'

# ==== Tests for constants and logger ====  
import logging

def test_headers_constant():
    assert 'User-Agent' in dm.HEADERS
    assert 'Accept' in dm.HEADERS


def test_histdata_base_constant():
    assert dm.HISTDATA_BASE.startswith('https://www.histdata.com')


def test_ensure_logger_adds_handler(monkeypatch):
    # Clear existing handlers
    l = logging.getLogger('data_download')
    orig_handlers = list(l.handlers)
    l.handlers.clear()
    # Mock settings log_level
    from types import SimpleNamespace
    dummy_settings = SimpleNamespace(log_level='WARNING')
    monkeypatch.setattr(dm, 'settings', dummy_settings)
    # Call ensure_logger
    dm._ensure_logger()
    # Expect at least one handler and correct level
    assert len(l.handlers) >= 1
    assert l.level == logging.WARNING
    assert l.propagate is False
    # restore handlers
    l.handlers[:] = orig_handlers

# End of tests
