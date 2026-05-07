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
