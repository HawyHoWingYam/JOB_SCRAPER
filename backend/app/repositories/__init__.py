"""
Repository layer for database operations.

Provides data access abstraction for Job and Company entities.
"""

from .company_repository import CompanyRepository
from .crawl_job_repository import CrawlJobRepository
from .event_outbox_repository import EventOutboxRepository
from .job_embedding_repository import JobEmbeddingRepository
from .job_repository import JobRepository
from .skill_repository import SkillRepository
from .job_skill_repository import JobSkillRepository

__all__ = [
    "CompanyRepository",
    "CrawlJobRepository",
    "EventOutboxRepository",
    "JobEmbeddingRepository",
    "JobRepository",
    "SkillRepository",
    "JobSkillRepository",
]
