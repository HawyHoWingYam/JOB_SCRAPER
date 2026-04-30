#!/usr/bin/env python3
"""Migrate existing job categories to hierarchical taxonomy."""
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
import uuid

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from app.database import SessionLocal
from app.models import JobDomain, JobCategory, JobSubcategory


class JobCategoryMigrator:
    def __init__(self, db: Any = None):
        self.db = db or SessionLocal()
        self._owns_session = db is None
        self.domain_cache: Dict[str, uuid.UUID] = {}
        self.category_cache: Dict[Tuple[str, str], uuid.UUID] = {}
        self.subcategory_cache: Dict[Tuple[str, str, str], uuid.UUID] = {}

    def get_or_create_domain(self, name: str) -> uuid.UUID:
        """Get or create job domain."""
        if name in self.domain_cache:
            return self.domain_cache[name]

        domain = self.db.query(JobDomain).filter_by(name=name).first()
        if not domain:
            domain = JobDomain(
                name=name,
                created_by="ai",
                is_auto_created=True,
                is_filter_visible=False,
                usage_count=0,
                distinct_job_count=0,
            )
            self.db.add(domain)
            self.db.flush()

        self.domain_cache[name] = domain.id
        return domain.id

    def get_or_create_category(self, domain_name: str, cat_name: str) -> uuid.UUID:
        """Get or create job category."""
        key = (domain_name, cat_name)
        if key in self.category_cache:
            return self.category_cache[key]

        domain_id = self.get_or_create_domain(domain_name)
        category = self.db.query(JobCategory).filter_by(
            domain_id=domain_id, name=cat_name
        ).first()

        if not category:
            category = JobCategory(
                domain_id=domain_id,
                name=cat_name,
                created_by="ai",
                is_auto_created=True,
                is_filter_visible=False,
                usage_count=0,
                distinct_job_count=0,
            )
            self.db.add(category)
            self.db.flush()

        self.category_cache[key] = category.id
        return category.id

    def get_or_create_subcategory(self, domain_name: str, cat_name: str, subcat_name: str) -> uuid.UUID:
        """Get or create job subcategory."""
        key = (domain_name, cat_name, subcat_name)
        if key in self.subcategory_cache:
            return self.subcategory_cache[key]

        category_id = self.get_or_create_category(domain_name, cat_name)
        subcategory = self.db.query(JobSubcategory).filter_by(
            category_id=category_id, name=subcat_name
        ).first()

        if not subcategory:
            subcategory = JobSubcategory(
                category_id=category_id,
                name=subcat_name,
                created_by="ai",
                is_auto_created=True,
                is_filter_visible=False,
                usage_count=0,
                distinct_job_count=0,
            )
            self.db.add(subcategory)
            self.db.flush()

        self.subcategory_cache[key] = subcategory.id
        return subcategory.id

    def infer_hierarchy(self, ai_category: str) -> Tuple[str, str, str]:
        """Infer domain, category, and subcategory from old ai_category."""
        cat_lower = ai_category.lower() if ai_category else ""

        # IT domain
        if any(x in cat_lower for x in ['software', 'web', 'mobile', 'developer', 'engineer', 'programming']):
            if any(x in cat_lower for x in ['web', 'frontend', 'backend', 'fullstack']):
                return ("IT", "Software Development", "Web Development")
            if 'mobile' in cat_lower:
                return ("IT", "Software Development", "Mobile Development")
            return ("IT", "Software Development", "Web Development")

        if any(x in cat_lower for x in ['data', 'analyst', 'scientist', 'ml', 'ai']):
            if any(x in cat_lower for x in ['machine learning', 'ml', 'ai']):
                return ("IT", "Data Science", "Machine Learning")
            if 'engineer' in cat_lower:
                return ("IT", "Data Science", "Data Engineering")
            return ("IT", "Data Science", "Data Analysis")

        if any(x in cat_lower for x in ['devops', 'cloud', 'infrastructure']):
            return ("IT", "DevOps", "Cloud Infrastructure")

        # Finance domain
        if any(x in cat_lower for x in ['finance', 'banking', 'accounting']):
            if 'account' in cat_lower:
                return ("Finance", "Accounting", "Financial Accounting")
            return ("Finance", "Banking", "Corporate Banking")

        # Default
        return ("IT", "Software Development", "Web Development")

    def migrate(self) -> dict[str, int]:
        """Migrate all jobs to hierarchical categories."""
        stats = {
            "processed": 0,
            "migrated": 0,
            "skipped": 0,
            "unmapped": 0,
            "errors": 0,
        }
        try:
            result = self.db.execute(text("""
                SELECT id, ai_category, subcategory_id
                FROM jobs
            """))
            jobs = result.fetchall()

            print(f"Found {len(jobs)} jobs to inspect")

            for job_id, ai_category, subcategory_id in jobs:
                stats["processed"] += 1

                if subcategory_id is not None:
                    stats["skipped"] += 1
                    continue

                if not ai_category:
                    stats["unmapped"] += 1
                    continue

                domain_name, cat_name, subcat_name = self.infer_hierarchy(ai_category)
                subcategory_id = self.get_or_create_subcategory(domain_name, cat_name, subcat_name)

                self.db.execute(text("""
                    UPDATE jobs
                    SET subcategory_id = :subcat_id
                    WHERE id = :job_id
                """), {"subcat_id": subcategory_id, "job_id": job_id})
                stats["migrated"] += 1

            self.db.commit()
            print(
                "✓ Job category migration complete "
                f"(migrated={stats['migrated']}, skipped={stats['skipped']}, "
                f"unmapped={stats['unmapped']}, errors={stats['errors']})"
            )
            return stats

        except Exception as e:
            stats["errors"] += 1
            self.db.rollback()
            print(f"✗ Error migrating job categories: {e}")
            raise
        finally:
            if self._owns_session:
                self.db.close()


def migrate_job_categories(db: Any = None) -> dict[str, int]:
    """Run the job category migration with an optional injected session."""
    migrator = JobCategoryMigrator(db=db)
    return migrator.migrate()


if __name__ == "__main__":
    print("Migrating job categories to hierarchical taxonomy...")
    migrate_job_categories()
    print("✓ Migration complete")
