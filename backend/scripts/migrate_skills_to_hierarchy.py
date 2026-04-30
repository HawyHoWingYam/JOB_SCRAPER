#!/usr/bin/env python3
"""Migrate existing flat skills to hierarchical taxonomy."""
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
import uuid

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from app.database import SessionLocal
from app.models import SkillCategory, SkillTechnology, Skill


class SkillMigrator:
    def __init__(self, db: Any = None):
        self.db = db or SessionLocal()
        self._owns_session = db is None
        self.category_cache: Dict[str, uuid.UUID] = {}
        self.technology_cache: Dict[Tuple[str, str], uuid.UUID] = {}

    def get_or_create_category(self, name: str) -> uuid.UUID:
        """Get or create skill category."""
        if name in self.category_cache:
            return self.category_cache[name]

        category = self.db.query(SkillCategory).filter_by(name=name).first()
        if not category:
            category = SkillCategory(
                name=name,
                created_by="ai",
                is_auto_created=True,
                is_filter_visible=False,
                usage_count=0,
                distinct_job_count=0,
            )
            self.db.add(category)
            self.db.flush()

        self.category_cache[name] = category.id
        return category.id

    def get_or_create_technology(self, category_name: str, tech_name: str) -> uuid.UUID:
        """Get or create skill technology."""
        key = (category_name, tech_name)
        if key in self.technology_cache:
            return self.technology_cache[key]

        category_id = self.get_or_create_category(category_name)
        technology = self.db.query(SkillTechnology).filter_by(
            category_id=category_id, name=tech_name
        ).first()

        if not technology:
            technology = SkillTechnology(
                category_id=category_id,
                name=tech_name,
                created_by="ai",
                is_auto_created=True,
                is_filter_visible=False,
                usage_count=0,
                distinct_job_count=0,
            )
            self.db.add(technology)
            self.db.flush()

        self.technology_cache[key] = technology.id
        return technology.id

    @staticmethod
    def build_aliases(name: str, existing_aliases: Optional[list[str]]) -> list[str]:
        """Merge the canonical lowercase alias with any existing aliases."""
        aliases = list(existing_aliases or [])
        normalized_alias = name.lower()
        if normalized_alias not in aliases:
            aliases.append(normalized_alias)
        return aliases

    def infer_hierarchy(self, skill_name: str, old_category: Optional[str]) -> Tuple[str, str]:
        """Infer category and technology from skill name and old category."""
        skill_lower = skill_name.lower()

        # Frontend frameworks
        if any(x in skill_lower for x in ['react', 'vue', 'angular', 'svelte', 'next']):
            return ("Frontend", "JavaScript")
        if any(x in skill_lower for x in ['css', 'sass', 'tailwind', 'bootstrap']):
            return ("Frontend", "CSS")
        if 'typescript' in skill_lower:
            return ("Frontend", "TypeScript")

        # Backend
        if any(x in skill_lower for x in ['django', 'flask', 'fastapi']):
            return ("Backend", "Python")
        if any(x in skill_lower for x in ['express', 'nest']):
            return ("Backend", "Node.js")
        if any(x in skill_lower for x in ['spring', 'hibernate']):
            return ("Backend", "Java")

        # Database
        if any(x in skill_lower for x in ['postgres', 'mysql', 'sql']):
            return ("Database", "SQL")
        if any(x in skill_lower for x in ['mongo', 'redis']):
            return ("Database", "NoSQL")

        # DevOps
        if any(x in skill_lower for x in ['docker', 'kubernetes', 'k8s']):
            return ("DevOps", "Containers")
        if any(x in skill_lower for x in ['jenkins', 'github actions', 'ci/cd']):
            return ("DevOps", "CI/CD")

        # Fallback to old category or Other
        if old_category:
            return (old_category, "General")
        return ("Other", "General")

    def migrate(self) -> dict[str, int]:
        """Migrate all existing skills to hierarchical structure."""
        stats = {"processed": 0, "migrated": 0, "skipped": 0, "errors": 0}
        try:
            result = self.db.execute(text("""
                SELECT id, name, category, popularity, technology_id, aliases
                FROM skills
            """))
            skills = result.fetchall()

            print(f"Found {len(skills)} skills to inspect")

            for skill_row in skills:
                skill_id, name, old_category, popularity, technology_id, aliases = skill_row
                stats["processed"] += 1

                if technology_id is not None:
                    stats["skipped"] += 1
                    continue

                category_name, tech_name = self.infer_hierarchy(name, old_category)
                technology_id = self.get_or_create_technology(category_name, tech_name)
                merged_aliases = self.build_aliases(name, aliases)

                self.db.execute(text("""
                    UPDATE skills
                    SET technology_id = :tech_id, aliases = :aliases
                    WHERE id = :skill_id
                """), {
                    "tech_id": technology_id,
                    "aliases": merged_aliases,
                    "skill_id": skill_id
                })
                stats["migrated"] += 1

            self.db.commit()
            print(
                "✓ Skill migration complete "
                f"(migrated={stats['migrated']}, skipped={stats['skipped']}, errors={stats['errors']})"
            )
            return stats

        except Exception as e:
            stats["errors"] += 1
            self.db.rollback()
            print(f"✗ Error migrating skills: {e}")
            raise
        finally:
            if self._owns_session:
                self.db.close()


def migrate_skills_to_hierarchy(db: Any = None) -> dict[str, int]:
    """Run the skill hierarchy migration with an optional injected session."""
    migrator = SkillMigrator(db=db)
    return migrator.migrate()


if __name__ == "__main__":
    print("Migrating skills to hierarchical taxonomy...")
    migrate_skills_to_hierarchy()
    print("✓ Migration complete")
