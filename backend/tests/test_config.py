import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import app.config as config_module
from app.config import Settings


def test_default_env_file_points_to_repo_root_dotenv():
    expected = BACKEND_ROOT.parent / ".env"

    assert config_module.DEFAULT_ENV_FILE == expected
    assert Path(Settings.model_config["env_file"]) == expected


def test_database_url_env_var_overrides_env_file(monkeypatch):
    override = "postgresql://override/test"

    monkeypatch.setenv("DATABASE_URL", override)

    assert Settings().database_url == override


def test_retrieval_api_url_env_var_overrides_env_file(monkeypatch):
    override = "http://retrieval-api:8000"

    monkeypatch.setenv("RETRIEVAL_API_URL", override)

    assert Settings().retrieval_api_url == override


def test_recommendation_api_url_env_var_overrides_env_file(monkeypatch):
    override = "http://recommendation-api:8000"

    monkeypatch.setenv("RECOMMENDATION_API_URL", override)

    assert Settings().recommendation_api_url == override


def test_uvicorn_reload_env_var_overrides_env_file(monkeypatch):
    monkeypatch.setenv("UVICORN_RELOAD", "false")

    assert Settings().uvicorn_reload is False


def test_uvicorn_reload_force_polling_env_var_overrides_env_file(monkeypatch):
    monkeypatch.setenv("UVICORN_RELOAD_FORCE_POLLING", "true")

    assert Settings().uvicorn_reload_force_polling is True


def test_jobsdb_headed_browser_channel_env_var_overrides_env_file(monkeypatch):
    monkeypatch.setenv("JOBSDB_HEADED_BROWSER_CHANNEL", "chrome")

    assert Settings().jobsdb_headed_browser_channel == "chrome"


def test_jobsdb_headed_browser_user_data_dir_env_var_overrides_env_file(monkeypatch):
    override = r"C:\browser-profiles\jobsdb"
    monkeypatch.setenv("JOBSDB_HEADED_BROWSER_USER_DATA_DIR", override)

    assert Settings().jobsdb_headed_browser_user_data_dir == override
