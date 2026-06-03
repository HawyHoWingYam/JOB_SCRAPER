from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.app_runtime_settings import AppRuntimeSettings
from app.services.ai_runtime_settings_service import AIRuntimeSettingsService


def _create_service():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[AppRuntimeSettings.__table__])
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = session_factory()
    return db, AIRuntimeSettingsService(db)


def test_get_effective_company_concurrency_uses_dedicated_value_and_falls_back_to_jobs_default():
    db, service = _create_service()
    try:
        row = service.get_or_create()
        row.ai_enrichment_run_concurrency = 8
        row.company_ai_enrichment_run_concurrency = None
        db.commit()

        assert service.get_effective_concurrency("companies") == 8

        row.company_ai_enrichment_run_concurrency = 3
        db.commit()

        assert service.get_effective_concurrency("companies") == 3
        assert service.get_effective_concurrency("jobs") == 8
    finally:
        db.close()


def test_serialize_configs_include_company_concurrency():
    db, service = _create_service()
    try:
        row = service.get_or_create()
        row.ai_enrichment_run_concurrency = 9
        row.company_ai_enrichment_run_concurrency = 2
        db.commit()

        persisted = service.serialize_persisted_config()
        effective = service.serialize_effective_config()

        assert persisted["ai_enrichment_run_concurrency"] == 9
        assert persisted["company_ai_enrichment_run_concurrency"] == 2
        assert effective["ai_enrichment_run_concurrency"] == 9
        assert effective["company_ai_enrichment_run_concurrency"] == 2
    finally:
        db.close()
