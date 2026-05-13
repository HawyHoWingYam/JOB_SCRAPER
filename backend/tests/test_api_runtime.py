import os
import sys
import types
from pathlib import Path
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


class _DummyAsyncIOScheduler:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    def start(self):
        return None


class _DummySQLAlchemyJobStore:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs


class _DummyCronTrigger:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs


apscheduler_module = types.ModuleType("apscheduler")
apscheduler_schedulers_module = types.ModuleType("apscheduler.schedulers")
apscheduler_asyncio_module = types.ModuleType("apscheduler.schedulers.asyncio")
apscheduler_jobstores_module = types.ModuleType("apscheduler.jobstores")
apscheduler_sqlalchemy_module = types.ModuleType("apscheduler.jobstores.sqlalchemy")
apscheduler_triggers_module = types.ModuleType("apscheduler.triggers")
apscheduler_cron_module = types.ModuleType("apscheduler.triggers.cron")

apscheduler_asyncio_module.AsyncIOScheduler = _DummyAsyncIOScheduler
apscheduler_sqlalchemy_module.SQLAlchemyJobStore = _DummySQLAlchemyJobStore
apscheduler_cron_module.CronTrigger = _DummyCronTrigger

sys.modules.setdefault("apscheduler", apscheduler_module)
sys.modules.setdefault("apscheduler.schedulers", apscheduler_schedulers_module)
sys.modules.setdefault("apscheduler.schedulers.asyncio", apscheduler_asyncio_module)
sys.modules.setdefault("apscheduler.jobstores", apscheduler_jobstores_module)
sys.modules.setdefault("apscheduler.jobstores.sqlalchemy", apscheduler_sqlalchemy_module)
sys.modules.setdefault("apscheduler.triggers", apscheduler_triggers_module)
sys.modules.setdefault("apscheduler.triggers.cron", apscheduler_cron_module)

import app.main as backend_main
import app.recommendation_main as recommendation_main
import app.retrieval_main as retrieval_main
import app.server_runtime as server_runtime


def test_resolve_reload_enabled_defaults_to_debug_when_reload_unset():
    settings = SimpleNamespace(debug=True, uvicorn_reload=None)

    assert server_runtime.resolve_reload_enabled(settings) is True


def test_resolve_reload_enabled_prefers_explicit_false_over_debug_true():
    settings = SimpleNamespace(debug=True, uvicorn_reload=False)

    assert server_runtime.resolve_reload_enabled(settings) is False


def test_run_api_app_sets_watchfiles_polling_when_requested(monkeypatch):
    captured = {}

    def fake_run(app_path, **kwargs):
        captured["app_path"] = app_path
        captured["kwargs"] = kwargs

    monkeypatch.delenv("WATCHFILES_FORCE_POLLING", raising=False)
    monkeypatch.setattr(server_runtime.uvicorn, "run", fake_run)

    settings = SimpleNamespace(
        debug=False,
        uvicorn_reload=True,
        uvicorn_reload_force_polling=True,
    )

    server_runtime.run_api_app("app.main:app", settings_obj=settings)

    assert os.environ["WATCHFILES_FORCE_POLLING"] == "true"
    assert captured["app_path"] == "app.main:app"
    assert captured["kwargs"]["reload"] is True


def test_backend_main_delegates_to_shared_runtime(monkeypatch):
    captured = {}

    def fake_run_api_app(app_path, *, settings_obj):
        captured["app_path"] = app_path
        captured["settings_obj"] = settings_obj

    monkeypatch.setattr(backend_main, "run_api_app", fake_run_api_app)

    backend_main.main()

    assert captured["app_path"] == "app.main:app"
    assert captured["settings_obj"] is backend_main.settings


def test_retrieval_main_delegates_to_shared_runtime(monkeypatch):
    captured = {}

    def fake_run_api_app(app_path, *, settings_obj):
        captured["app_path"] = app_path
        captured["settings_obj"] = settings_obj

    monkeypatch.setattr(retrieval_main, "run_api_app", fake_run_api_app)

    retrieval_main.main()

    assert captured["app_path"] == "app.retrieval_main:app"
    assert captured["settings_obj"] is retrieval_main.settings


def test_recommendation_main_delegates_to_shared_runtime(monkeypatch):
    captured = {}

    def fake_run_api_app(app_path, *, settings_obj):
        captured["app_path"] = app_path
        captured["settings_obj"] = settings_obj

    monkeypatch.setattr(recommendation_main, "run_api_app", fake_run_api_app)

    recommendation_main.main()

    assert captured["app_path"] == "app.recommendation_main:app"
    assert captured["settings_obj"] is recommendation_main.settings
