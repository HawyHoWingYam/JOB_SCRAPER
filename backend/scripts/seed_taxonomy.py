#!/usr/bin/env python3
"""Seed initial taxonomy data into the database."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import SessionLocal
from app.models import SkillCategory, SkillTechnology, Skill, JobDomain, JobCategory, JobSubcategory


def data_path(filename: str) -> Path:
    """Resolve taxonomy data files relative to the backend app/data directory."""
    return Path(__file__).resolve().parents[1] / "app" / "data" / filename


def seed_skills():
    """Seed skill taxonomy from JSON file."""
    db = SessionLocal()
    try:
        with data_path("skill_taxonomy.json").open() as f:
            data = json.load(f)

        for cat_data in data["categories"]:
            category = SkillCategory(name=cat_data["name"])
            db.add(category)
            db.flush()

            for tech_data in cat_data["technologies"]:
                technology = SkillTechnology(
                    category_id=category.id,
                    name=tech_data["name"]
                )
                db.add(technology)
                db.flush()

                for skill_data in tech_data["skills"]:
                    skill = Skill(
                        technology_id=technology.id,
                        name=skill_data["name"],
                        aliases=skill_data.get("aliases", [])
                    )
                    db.add(skill)

        db.commit()
        print("✓ Skills taxonomy seeded")
    except Exception as e:
        db.rollback()
        print(f"✗ Error seeding skills: {e}")
        raise
    finally:
        db.close()


def seed_job_categories():
    """Seed job category taxonomy from JSON file."""
    db = SessionLocal()
    try:
        with data_path("job_category_taxonomy.json").open() as f:
            data = json.load(f)

        for domain_data in data["domains"]:
            domain = JobDomain(name=domain_data["name"])
            db.add(domain)
            db.flush()

            for cat_data in domain_data["categories"]:
                category = JobCategory(
                    domain_id=domain.id,
                    name=cat_data["name"]
                )
                db.add(category)
                db.flush()

                for subcat_name in cat_data["subcategories"]:
                    subcategory = JobSubcategory(
                        category_id=category.id,
                        name=subcat_name
                    )
                    db.add(subcategory)

        db.commit()
        print("✓ Job categories taxonomy seeded")
    except Exception as e:
        db.rollback()
        print(f"✗ Error seeding job categories: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    print("Seeding taxonomy data...")
    seed_skills()
    seed_job_categories()
    print("✓ All taxonomy data seeded successfully")
