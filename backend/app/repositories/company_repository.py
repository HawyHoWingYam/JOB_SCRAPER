"""
Company Repository - Data access layer for Company entities.

Handles company lookup, creation, and deduplication logic.
"""

import logging
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.models.company import Company
from app.utils.source_identity import normalize_source_site

logger = logging.getLogger(__name__)


class CompanyRepository:
    """Repository for Company database operations."""

    def upsert_company(
        self,
        db: Session,
        company_data: Dict[str, Any],
        auto_commit: bool = True,
    ) -> tuple[Company, str]:
        source_site = normalize_source_site(company_data.get("source_site"))
        source_company_id = str(company_data.get("source_company_id") or "").strip()
        if not source_company_id:
            raise ValueError("source_company_id is required for source-aware upsert")

        existing = self.get_company_by_source_key(
            db,
            source_site=source_site,
            source_company_id=source_company_id,
        )
        normalized_data = dict(company_data)
        normalized_data["source_site"] = source_site
        normalized_data["source_company_id"] = source_company_id

        if existing is None:
            return self.create_company(db, normalized_data, auto_commit=auto_commit), "created"

        changed = False
        for key, value in normalized_data.items():
            if not hasattr(existing, key) or key in {"id", "created_at"}:
                continue
            if getattr(existing, key) != value:
                setattr(existing, key, value)
                changed = True

        if not changed:
            return existing, "skipped"

        if auto_commit:
            db.commit()
            db.refresh(existing)
        else:
            db.flush()
        return existing, "updated"

    def get_company_by_source_key(
        self,
        db: Session,
        *,
        source_site: str,
        source_company_id: str,
    ) -> Optional[Company]:
        try:
            return (
                db.query(Company)
                .filter(
                    Company.source_site == normalize_source_site(source_site),
                    Company.source_company_id == str(source_company_id).strip(),
                    Company.is_deleted == False,
                )
                .first()
            )
        except Exception as e:
            logger.error(
                "Error querying company by source key %s/%s: %s",
                source_site,
                source_company_id,
                e,
            )
            return None

    def get_or_create_company(
        self, db: Session, company_data: Dict[str, Any], auto_commit: bool = True
    ) -> tuple[Company, bool]:
        """
        Get existing company or create new one.

        Lookup order:
        1. By company_id (if provided)
        2. By name (exact match)
        3. Create new if not found

        Args:
            db: SQLAlchemy session
            company_data: Company data dict with keys: company_id, name, industry, location, extra_data

        Returns:
            (Company, created: bool) - Company instance and whether it was created
        """
        if company_data.get("source_site") and company_data.get("source_company_id"):
            company = self.get_company_by_source_key(
                db,
                source_site=str(company_data["source_site"]),
                source_company_id=str(company_data["source_company_id"]),
            )
            if company:
                logger.debug(
                    "Found company by source key: %s/%s",
                    company_data["source_site"],
                    company_data["source_company_id"],
                )
                return company, False

        # Try lookup by company_id first
        if company_data.get("company_id"):
            company = self.get_company_by_company_id(db, company_data["company_id"])
            if company:
                logger.debug(f"Found company by company_id: {company_data['company_id']}")
                return company, False

        # Try lookup by name
        if company_data.get("name"):
            company = self.get_company_by_name(db, company_data["name"])
            if company:
                logger.debug(f"Found company by name: {company_data['name']}")
                return company, False

        # Create new company
        company = self.create_company(db, company_data, auto_commit=auto_commit)
        logger.info(f"Created new company: {company.name} (id: {company.id})")
        return company, True

    def get_company_by_company_id(
        self, db: Session, company_id: str
    ) -> Optional[Company]:
        """
        Get company by JobsDB company_id.

        Args:
            db: SQLAlchemy session
            company_id: JobsDB company identifier

        Returns:
            Company instance or None if not found
        """
        try:
            return (
                db.query(Company)
                .filter(Company.company_id == company_id, Company.is_deleted == False)
                .first()
            )
        except Exception as e:
            logger.error(f"Error querying company by company_id {company_id}: {e}")
            return None

    def get_company_by_name(self, db: Session, name: str) -> Optional[Company]:
        """
        Get company by name (exact match).

        Args:
            db: SQLAlchemy session
            name: Company name

        Returns:
            Company instance or None if not found
        """
        try:
            return (
                db.query(Company)
                .filter(Company.name == name, Company.is_deleted == False)
                .first()
            )
        except Exception as e:
            logger.error(f"Error querying company by name {name}: {e}")
            return None

    def create_company(
        self, db: Session, company_data: Dict[str, Any], auto_commit: bool = True
    ) -> Company:
        """
        Create a new company.

        Args:
            db: SQLAlchemy session
            company_data: Company data dict

        Returns:
            Created Company instance

        Raises:
            IntegrityError: If company with same name/company_id already exists
        """
        try:
            company = Company(
                company_id=company_data.get("company_id"),
                source_site=normalize_source_site(company_data.get("source_site")),
                source_company_id=company_data.get("source_company_id"),
                name=company_data.get("name"),
                industry=company_data.get("industry"),
                location=company_data.get("location"),
                ai_description=company_data.get("ai_description"),
                extra_data=company_data.get("extra_data"),
            )
            db.add(company)
            if auto_commit:
                db.commit()
            else:
                db.flush()
            db.refresh(company)
            return company
        except IntegrityError as e:
            if auto_commit:
                db.rollback()
            else:
                raise
            logger.warning(f"Integrity error creating company: {e}")
            # Try to find existing company
            if company_data.get("name"):
                existing = self.get_company_by_name(db, company_data["name"])
                if existing:
                    return existing
            raise
        except Exception as e:
            if auto_commit:
                db.rollback()
            logger.error(f"Error creating company: {e}")
            raise
