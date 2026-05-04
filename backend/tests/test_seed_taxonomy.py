import json
import sys
import uuid
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.database import Base
from app.models import Skill, SkillCategory, SkillTechnology
from scripts import seed_taxonomy

if not hasattr(SQLiteTypeCompiler, "visit_UUID"):
    SQLiteTypeCompiler.visit_UUID = lambda self, type_, **kw: "CHAR(32)"

if not hasattr(SQLiteTypeCompiler, "visit_ARRAY"):
    SQLiteTypeCompiler.visit_ARRAY = lambda self, type_, **kw: "TEXT"


def _build_sqlite_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            SkillCategory.__table__,
            SkillTechnology.__table__,
            Skill.__table__,
        ],
    )
    Session = sessionmaker(bind=engine)
    return Session()


def _coerce_aliases(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return json.loads(value)
    return []


def test_sync_skills_promotes_existing_nodes_and_merges_aliases():
    db = _build_sqlite_session()
    try:
        category = SkillCategory(
            id=uuid.uuid4(),
            name="DevOps",
            created_by="ai",
            is_auto_created=True,
        )
        technology = SkillTechnology(
            id=uuid.uuid4(),
            category_id=category.id,
            name="Cloud Platforms",
            created_by="ai",
            is_auto_created=True,
        )
        skill = Skill(
            id=uuid.uuid4(),
            technology_id=technology.id,
            name="AWS",
            aliases=None,
            created_by="ai",
            is_auto_created=True,
        )
        db.add_all([category, technology, skill])
        db.commit()

        report = seed_taxonomy.sync_skills(
            db,
            {
                "categories": [
                    {
                        "name": "DevOps",
                        "technologies": [
                            {
                                "name": "Cloud Platforms",
                                "skills": [
                                        {
                                            "name": "AWS",
                                        }
                                    ],
                                }
                            ],
                    }
                ]
            },
            execute=True,
        )

        db.refresh(category)
        db.refresh(technology)
        db.refresh(skill)

        assert report == {
            "categories_created": 0,
            "categories_promoted": 1,
            "technologies_created": 0,
            "technologies_promoted": 1,
            "skills_created": 0,
            "skills_promoted": 1,
            "skill_aliases_updated": 0,
        }
        assert category.created_by == "seed"
        assert category.is_auto_created is False
        assert technology.created_by == "seed"
        assert technology.is_auto_created is False
        assert skill.created_by == "seed"
        assert skill.is_auto_created is False
        assert _coerce_aliases(skill.aliases) == []
    finally:
        db.close()


def test_sync_skills_dry_run_rolls_back_missing_node_creation():
    db = _build_sqlite_session()
    try:
        report = seed_taxonomy.sync_skills(
            db,
            {
                "categories": [
                    {
                        "name": "Frontend",
                        "technologies": [
                            {
                                "name": "JavaScript",
                                "skills": [
                                    {"name": "React"},
                                ],
                            }
                        ],
                    }
                ]
            },
            execute=False,
        )

        assert report == {
            "categories_created": 1,
            "categories_promoted": 0,
            "technologies_created": 1,
            "technologies_promoted": 0,
            "skills_created": 1,
            "skills_promoted": 0,
            "skill_aliases_updated": 0,
        }
        assert db.query(SkillCategory).count() == 0
        assert db.query(SkillTechnology).count() == 0
        assert db.query(Skill).count() == 0
    finally:
        db.close()


def test_merge_aliases_combines_existing_and_incoming_values():
    assert seed_taxonomy._merge_aliases(
        ["reactjs"],
        ["reactjs", "react.js"],
    ) == ["reactjs", "react.js"]
