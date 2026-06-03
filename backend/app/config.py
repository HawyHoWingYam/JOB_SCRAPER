from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator
from pathlib import Path
from typing import Optional

SUPPORTED_LLM_PROVIDERS = ("anthropic", "claude", "custom", "gemini", "zhipu", "mock")
AI_ENRICHMENT_RUN_CONCURRENCY_MIN = 1
AI_ENRICHMENT_RUN_CONCURRENCY_MAX = 50
DEFAULT_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
DEFAULT_RUNTIME_DIR = Path(__file__).resolve().parents[1] / "runtime"


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=str(DEFAULT_ENV_FILE),
        case_sensitive=False,
        extra="ignore",
    )

    # Database
    database_url: str = "postgresql://admin:dev_password@postgres-db:5432/jobsdb"

    # Redis
    redis_url: str = "redis://redis-mq:6379/0"

    # JobsDB API
    jobsdb_base_url: str = "https://hk.jobsdb.com"
    jobsdb_api_url: str = "https://hk.jobsdb.com/api/jobsearch/v5/search"

    # Scraper settings (stealth-first)
    scraper_min_delay: float = 2.0
    scraper_max_delay: float = 5.0
    scraper_max_retries: int = 3
    scraper_use_playwright_fallback: bool = True
    jobsdb_headed_browser_channel: str = "msedge"
    jobsdb_headed_browser_user_data_dir: Optional[str] = None
    jobsdb_headed_browser_executable_path: Optional[str] = None
    jobsdb_headed_navigation_timeout_ms: int = 60000
    jobsdb_headed_worker_lock_port: int = 47651
    jobsdb_headed_worker_stale_seconds: int = 60
    manual_action_helper_host: str = "127.0.0.1"
    jobsdb_headed_manual_action_helper_port: int = 47652
    manual_action_registry_state_path: str = str(
        DEFAULT_RUNTIME_DIR / "manual_actions" / "live_browser_sessions.json"
    )
    ctgoodjobs_proxy_enabled: bool = False
    ctgoodjobs_proxy_provider: str = "static"
    ctgoodjobs_proxy_static_url: Optional[str] = None
    ctgoodjobs_proxy_pool_api_base_url: Optional[str] = None
    ctgoodjobs_proxy_pool_get_path: str = "/get"
    ctgoodjobs_proxy_pool_delete_path: Optional[str] = "/delete"
    ctgoodjobs_proxy_request_timeout_s: float = 30.0
    ctgoodjobs_proxy_quarantine_minutes_challenge: int = 15
    ctgoodjobs_proxy_quarantine_minutes_network: int = 10
    ctgoodjobs_proxy_min_seconds_between_reuse: float = 0.0
    ctgoodjobs_proxy_require_https_capable: bool = False
    ctgoodjobs_proxy_provider_auth_header: Optional[str] = None

    # Scheduler worker runtime
    scheduler_heartbeat_interval_seconds: int = 15
    scheduler_reconcile_interval_seconds: int = 30
    scheduler_heartbeat_stale_seconds: int = 60

    # LLM Configuration
    llm_provider: str = "gemini"  # Options: anthropic, claude, custom, gemini, zhipu, mock
    anthropic_api_key: Optional[str] = None
    anthropic_model: str = "claude-sonnet-4-5"
    anthropic_base_url: Optional[str] = None  # For API proxies
    gemini_api_key: Optional[str] = None
    gemini_model: str = "gemini-2.5-flash"
    zhipu_api_key: Optional[str] = None

    # Custom LLM Provider (for proxy services)
    custom_api_key: Optional[str] = None
    custom_base_url: Optional[str] = None
    custom_api_format: str = "anthropic"
    custom_model: str = "claude-sonnet-4-5"
    retrieval_api_url: Optional[str] = None
    recommendation_api_url: Optional[str] = None

    @field_validator(
        'anthropic_base_url',
        'anthropic_api_key',
        'custom_api_key',
        'custom_base_url',
        'retrieval_api_url',
        'recommendation_api_url',
        'jobsdb_headed_browser_user_data_dir',
        'jobsdb_headed_browser_executable_path',
        'ctgoodjobs_proxy_static_url',
        'ctgoodjobs_proxy_pool_api_base_url',
        'ctgoodjobs_proxy_pool_delete_path',
        'ctgoodjobs_proxy_provider_auth_header',
        mode='before',
    )
    @classmethod
    def empty_str_to_none(cls, v):
        return None if v == "" else v

    # Google Custom Search
    google_api_key: Optional[str] = None
    google_cse_id: Optional[str] = None

    # Taxonomy visibility thresholds
    filter_skill_l3_min_jobs: int = 5
    filter_skill_l2_min_jobs: int = 10
    filter_skill_l1_min_jobs: int = 20
    filter_job_l3_min_jobs: int = 5
    filter_job_l2_min_jobs: int = 10
    filter_job_l1_min_jobs: int = 20
    job_classification_conservative_mode: bool = False
    job_classification_cross_domain_min_confidence: float = 0.9
    ai_enrichment_run_concurrency: int = 10
    company_ai_enrichment_run_concurrency: Optional[int] = None

    # Application
    debug: bool = False
    uvicorn_reload: Optional[bool] = None
    uvicorn_reload_force_polling: bool = False
    sqlalchemy_echo: bool = False
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:5174,http://127.0.0.1:5174"

settings = Settings()
