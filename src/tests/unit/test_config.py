import os
import importlib
from pathlib import Path
import pytest
from importlib import import_module
import dotenv


def reload_config_module(monkeypatch, env_vars=None, path_exists=True):
    """
    Helper to reload the utils.config module with specified environment vars and Path.exists behavior.
    """
    # Clear relevant env vars
    keys = [
        'DATA_DIR', 'POSTGRES_HOST', 'POSTGRES_PORT', 'POSTGRES_DB',
        'POSTGRES_USER', 'POSTGRES_PASSWORD', 'ACCOUNT_KEY', 'ACCESS_TOKEN',
        'LOG_LEVEL', 'PROMETHEUS_PORT', 'TEST_ENV_VAR'
    ]
    for k in keys:
        monkeypatch.delenv(k, raising=False)

    # Set provided env vars
    if env_vars:
        for k, v in env_vars.items():
            monkeypatch.setenv(k, v)

    # Monkeypatch Path.exists to control .env loading
    real_exists = Path.exists
    def fake_exists(self):
        if self.name == '.env':
            return path_exists
        return real_exists(self)
    monkeypatch.setattr(Path, 'exists', fake_exists)

    # Reload module
    module_name = 'elpis_nautilus.utils.config'
    if module_name in importlib.sys.modules:
        del importlib.sys.modules[module_name]
    config = import_module(module_name)
    importlib.reload(config)
    return config


def test_defaults(monkeypatch, tmp_path):
    config = reload_config_module(monkeypatch, env_vars=None, path_exists=False)
    cfg = config.Config()

    # Check BASE_DIR resolution
    assert isinstance(config.BASE_DIR, Path)
    assert (config.BASE_DIR / cfg.data_dir_name).name == 'data'

    # Defaults
    assert cfg.data_dir_name == 'data'
    assert cfg.data_dir == config.BASE_DIR / 'data'
    assert cfg.tmp_dir == config.BASE_DIR / 'data' / 'tmp'

    assert cfg.db_host == 'localhost'
    assert cfg.db_port == 5432
    assert cfg.db_name == 'elpis'
    assert cfg.db_user == 'polymerase'
    assert cfg.db_password is None

    assert cfg.account_key is None
    assert cfg.access_token is None

    assert cfg.log_level == 'INFO'
    assert cfg.prometheus_port == 8000


def test_env_overrides(monkeypatch):
    env_vars = {
        'DATA_DIR': 'customdata',
        'POSTGRES_HOST': 'db.example.com',
        'POSTGRES_PORT': '6543',
        'POSTGRES_DB': 'testdb',
        'POSTGRES_USER': 'testuser',
        'POSTGRES_PASSWORD': 'secret',
        'ACCOUNT_KEY': 'acct123',
        'ACCESS_TOKEN': 'token456',
        'LOG_LEVEL': 'DEBUG',
        'PROMETHEUS_PORT': '9000'
    }
    config = reload_config_module(monkeypatch, env_vars=env_vars, path_exists=False)
    cfg = config.Config()

    assert cfg.data_dir_name == 'customdata'
    assert cfg.data_dir == config.BASE_DIR / 'customdata'
    assert cfg.tmp_dir == config.BASE_DIR / 'customdata' / 'tmp'

    assert cfg.db_host == 'db.example.com'
    assert cfg.db_port == 6543
    assert cfg.db_name == 'testdb'
    assert cfg.db_user == 'testuser'
    assert cfg.db_password == 'secret'

    assert cfg.account_key == 'acct123'
    assert cfg.access_token == 'token456'

    assert cfg.log_level == 'DEBUG'
    assert cfg.prometheus_port == 9000


def test_invalid_port_raises(monkeypatch):
    env_vars = {'POSTGRES_PORT': 'not_an_int'}
    with pytest.raises(ValueError):
        reload_config_module(monkeypatch, env_vars=env_vars, path_exists=False)


def test_singleton_settings(monkeypatch):
    config_module = reload_config_module(monkeypatch, env_vars=None, path_exists=False)
    settings = config_module.settings
    assert isinstance(settings, config_module.Config)
    # Changing env after instantiation should not affect existing settings
    monkeypatch.setenv('LOG_LEVEL', 'WARNING')
    assert settings.log_level == 'INFO'


def test_dotenv_loading(monkeypatch):
    called = {'yes': False}
    def fake_load_dotenv(path, override=False):
        os.environ['TEST_ENV_VAR'] = 'loaded'
        called['yes'] = True

    # Patch dotenv.load_dotenv before reloading config module
    monkeypatch.setattr(dotenv, 'load_dotenv', fake_load_dotenv)

    # Reload module with .env present and custom env vars
    config = reload_config_module(
        monkeypatch,
        env_vars={'DATA_DIR': 'envdata', 'LOG_LEVEL': 'WARN'},
        path_exists=True
    )

    # Verify load_dotenv was called
    assert called['yes'], "load_dotenv should be called when .env exists"
    assert os.environ.get('TEST_ENV_VAR') == 'loaded'

    cfg = config.Config()
    assert cfg.data_dir_name == 'envdata'
    assert cfg.log_level == 'WARN'
