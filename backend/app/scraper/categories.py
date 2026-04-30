"""
JobsDB Hong Kong Category Registry

Contains all known main job categories discovered from JobsDB API.
Each category has an ID and description used for category-based scraping.
"""

from typing import Dict, List, NamedTuple


class Category(NamedTuple):
    """Represents a JobsDB job category."""
    id: int
    name: str
    slug: str  # URL-friendly name


# All known main categories discovered from JobsDB Hong Kong
JOBSDB_CATEGORIES: Dict[int, Category] = {
    1200: Category(1200, "Accounting", "accounting"),
    1203: Category(1203, "Banking & Financial Services", "banking-financial-services"),
    1204: Category(1204, "Call Centre & Customer Service", "call-centre-customer-service"),
    1206: Category(1206, "Construction", "construction"),
    1209: Category(1209, "Engineering", "engineering"),
    1211: Category(1211, "Healthcare & Medical", "healthcare-medical"),
    1212: Category(1212, "Hospitality & Tourism", "hospitality-tourism"),
    1214: Category(1214, "Insurance & Superannuation", "insurance-superannuation"),
    1216: Category(1216, "Legal", "legal"),
    1220: Category(1220, "Real Estate & Property", "real-estate-property"),
    1223: Category(1223, "Science & Technology", "science-technology"),
    1225: Category(1225, "Trades & Services", "trades-services"),
    6008: Category(6008, "Marketing & Communications", "marketing-communications"),
    6043: Category(6043, "Retail & Consumer Products", "retail-consumer-products"),
    6076: Category(6076, "Consulting & Strategy", "consulting-strategy"),
    6092: Category(6092, "Manufacturing, Transport & Logistics", "manufacturing-transport-logistics"),
    6123: Category(6123, "Education & Training", "education-training"),
    6163: Category(6163, "Community Services & Development", "community-services-development"),
    6317: Category(6317, "Human Resources & Recruitment", "human-resources-recruitment"),
    6251: Category(6251, "Administration & Office Support", "administration-office-support"),
    6263: Category(6263, "Design & Architecture", "design-architecture"),
    6281: Category(6281, "Information & Communication Technology", "information-communication-technology"),
    6304: Category(6304, "Advertising, Arts & Media", "advertising-arts-media"),
    6362: Category(6362, "Sales", "sales"),
    7019: Category(7019, "CEO & General Management", "ceo-general-management"),
}


def get_all_category_ids() -> List[int]:
    """Return all category IDs."""
    return list(JOBSDB_CATEGORIES.keys())


def get_category_by_id(category_id: int) -> Category | None:
    """Get category by ID."""
    return JOBSDB_CATEGORIES.get(category_id)


def get_category_name(category_id: int) -> str | None:
    """Get category name by ID."""
    cat = JOBSDB_CATEGORIES.get(category_id)
    return cat.name if cat else None


def get_all_categories() -> List[Category]:
    """Return all categories as a list."""
    return list(JOBSDB_CATEGORIES.values())
