from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.ai.job_insight_extractor import JobInsightExtractor


def test_build_prompt_includes_late_requirement_sections_for_skill_context():
    extractor = object.__new__(JobInsightExtractor)
    filler = "Core responsibilities include stakeholder alignment and delivery planning. " * 35
    description = (
        "Role overview:\n"
        f"{filler}\n"
        "Requirements:\n"
        "- Power BI\n"
        "- Azure\n"
        "- SSIS\n"
        "Preferred tools:\n"
        "- DAX\n"
    )

    assert description.index("Power BI") > 2000

    prompt = extractor.build_prompt(
        title="Data Architect",
        description=description,
        taxonomy_candidates={},
        skill_taxonomy_candidates={},
    )

    assert "Power BI" in prompt
    assert "Azure" in prompt
    assert "SSIS" in prompt
    assert "DAX" in prompt
    assert "Aim for 3-20 technical skills" in prompt


def test_normalize_skills_caps_output_at_twenty_items():
    extractor = object.__new__(JobInsightExtractor)
    raw_skills = [{"name": f"Skill {index}"} for index in range(25)]

    normalized = extractor._normalize_skills(raw_skills)

    assert len(normalized) == 20
    assert normalized[0]["name"] == "Skill 0"
    assert normalized[-1]["name"] == "Skill 19"


def test_build_prompt_includes_product_ba_support_role_guidance():
    extractor = object.__new__(JobInsightExtractor)

    prompt = extractor.build_prompt(
        title="Product Manager",
        description="Own roadmap delivery, stakeholder alignment, and KPI tracking.",
        taxonomy_candidates={},
        skill_taxonomy_candidates={
            "role_mode": "product_ba_support",
            "role_mode_guidance": "For product / BA / support roles, include concrete tools, delivery practices, and structured analysis skills when explicitly named or strongly evidenced.",
        },
    )

    assert "product / BA / support roles" in prompt
    assert "delivery practices" in prompt
