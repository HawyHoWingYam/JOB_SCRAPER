import os

try:
    import uvicorn
except ModuleNotFoundError:
    class _MissingUvicorn:
        def run(self, *args, **kwargs):
            raise ModuleNotFoundError("uvicorn is required to start API runtimes")

    uvicorn = _MissingUvicorn()


def resolve_reload_enabled(settings_obj) -> bool:
    if settings_obj.uvicorn_reload is not None:
        return settings_obj.uvicorn_reload
    return settings_obj.debug


def configure_watchfiles_environment(*, reload_enabled: bool, force_polling: bool) -> None:
    if reload_enabled and force_polling:
        os.environ["WATCHFILES_FORCE_POLLING"] = "true"


def run_api_app(
    app_path: str,
    *,
    settings_obj,
    host: str = "0.0.0.0",
    port: int = 8000,
) -> None:
    reload_enabled = resolve_reload_enabled(settings_obj)
    configure_watchfiles_environment(
        reload_enabled=reload_enabled,
        force_polling=settings_obj.uvicorn_reload_force_polling,
    )
    uvicorn.run(
        app_path,
        host=host,
        port=port,
        reload=reload_enabled,
    )
