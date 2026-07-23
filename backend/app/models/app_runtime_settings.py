from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text

from app.database import Base


class AppRuntimeSettings(Base):
    """Singleton-style persisted runtime settings for AI configuration."""

    __tablename__ = "app_runtime_settings"

    id = Column(Integer, primary_key=True, default=1)
    llm_provider = Column(String(32), nullable=True)
    company_llm_provider = Column(String(32), nullable=True)
    ai_enrichment_run_concurrency = Column(Integer, nullable=True)
    company_ai_enrichment_run_concurrency = Column(Integer, nullable=True)

    anthropic_api_key = Column(Text, nullable=True)
    anthropic_model = Column(String(255), nullable=True)
    anthropic_base_url = Column(String(512), nullable=True)

    gemini_api_key = Column(Text, nullable=True)
    gemini_model = Column(String(255), nullable=True)

    custom_api_key = Column(Text, nullable=True)
    custom_model = Column(String(255), nullable=True)
    custom_base_url = Column(String(512), nullable=True)
    custom_api_format = Column(String(64), nullable=True)

    zhipu_api_key = Column(Text, nullable=True)

    company_anthropic_api_key = Column(Text, nullable=True)
    company_anthropic_model = Column(String(255), nullable=True)
    company_anthropic_base_url = Column(String(512), nullable=True)

    company_gemini_api_key = Column(Text, nullable=True)
    company_gemini_model = Column(String(255), nullable=True)

    company_custom_api_key = Column(Text, nullable=True)
    company_custom_model = Column(String(255), nullable=True)
    company_custom_base_url = Column(String(512), nullable=True)
    company_custom_api_format = Column(String(64), nullable=True)

    company_zhipu_api_key = Column(Text, nullable=True)

    jobs_last_test_status = Column(String(32), nullable=True)
    jobs_last_tested_at = Column(DateTime, nullable=True)
    jobs_last_test_error = Column(Text, nullable=True)
    jobs_last_test_provider = Column(String(32), nullable=True)
    jobs_last_test_model = Column(String(255), nullable=True)
    jobs_last_test_latency_ms = Column(Integer, nullable=True)
    jobs_last_test_fingerprint = Column(String(128), nullable=True)
    jobs_last_successful_test_fingerprint = Column(String(128), nullable=True)

    companies_last_test_status = Column(String(32), nullable=True)
    companies_last_tested_at = Column(DateTime, nullable=True)
    companies_last_test_error = Column(Text, nullable=True)
    companies_last_test_provider = Column(String(32), nullable=True)
    companies_last_test_model = Column(String(255), nullable=True)
    companies_last_test_latency_ms = Column(Integer, nullable=True)
    companies_last_test_fingerprint = Column(String(128), nullable=True)
    companies_last_successful_test_fingerprint = Column(String(128), nullable=True)

    companies_web_search_last_test_status = Column(String(32), nullable=True)
    companies_web_search_last_tested_at = Column(DateTime, nullable=True)
    companies_web_search_last_test_error = Column(Text, nullable=True)
    companies_web_search_last_test_latency_ms = Column(Integer, nullable=True)
    companies_web_search_last_test_fingerprint = Column(String(128), nullable=True)

    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )
