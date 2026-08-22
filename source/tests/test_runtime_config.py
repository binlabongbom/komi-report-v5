from pathlib import Path

from runtime_config import load_runtime_settings, save_runtime_database_path


def test_runtime_settings_use_defaults_under_app_home(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    settings = load_runtime_settings({})

    assert settings.app_home == tmp_path / "KOMI Report V5"
    assert settings.db_path == settings.app_home / "KOMI_Report_V5.db"
    assert settings.log_dir == settings.app_home / "logs"
    assert settings.api_host == "127.0.0.1"
    assert settings.api_port == 8766


def test_runtime_settings_prefer_environment_over_local_toml(tmp_path):
    config_path = tmp_path / "runtime.toml"
    config_path.write_text(
        "[runtime]\napp_home = '/from-file'\napi_port = 9100\n",
        encoding="utf-8",
    )

    settings = load_runtime_settings(
        {"KOMI_APP_HOME": "/from-environment", "KOMI_API_PORT": "9200"},
        config_path=config_path,
    )

    assert settings.app_home == Path("/from-environment")
    assert settings.api_port == 9200


def test_runtime_settings_reject_invalid_port(tmp_path):
    settings = load_runtime_settings({"KOMI_API_PORT": "invalid"}, config_path=tmp_path / "missing.toml")

    assert settings.api_port == 8766


def test_save_runtime_database_path_preserves_existing_runtime_values(tmp_path):
    config_path = tmp_path / "runtime.toml"
    config_path.write_text(
        "[runtime]\napi_host = '0.0.0.0'\napi_port = 9100\n",
        encoding="utf-8",
    )
    database_path = tmp_path / "customer data" / "KOMI Report.db"

    saved = save_runtime_database_path(database_path, config_path=config_path)
    settings = load_runtime_settings({}, config_path=config_path)

    assert saved == config_path
    assert settings.db_path == database_path.resolve()
    assert settings.api_host == "0.0.0.0"
    assert settings.api_port == 9100
