"""
Data Mapper - Utilities for transforming scraped data to database schema.

Handles data transformation, validation, and field mapping.
"""

import logging
import re
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)


def _namespace_ctgoodjobs_id(raw_value: Any) -> Any:
    if not isinstance(raw_value, str):
        return raw_value
    normalized = raw_value.strip()
    if not normalized:
        return normalized
    if normalized.startswith("ctgoodjobs:"):
        return normalized
    return f"ctgoodjobs:{normalized}"


def parse_listing_date(date_string: Optional[str]) -> Optional[datetime]:
    """
    Parse listing date string to datetime object.

    Handles ISO format dates from JobsDB API and Chinese relative dates from OfferToday.

    OfferToday formats:
    - "\u767c\u5e03\u65bc3\u500b\u6708\u524d" (published 3 months ago)
    - "\u66f4\u65b0\u65bc3\u500b\u6708\u524d" (updated 3 months ago)
    - "\u767c\u5e03\u65bc06-15" (published on Jun 15)
    - "\u66f4\u65b0\u65bc06-24" (updated on Jun 24)

    Args:
        date_string: Date string to parse

    Returns:
        datetime object or None if parsing fails
    """
    if not date_string:
        return None

    # Try OfferToday Chinese relative date formats first
    if "\u6708" in date_string:  # contains "月"
        # e.g., "發布於3個月前", "更新於近3個月"
        m = re.search(r"(\d+)\u500b\u6708", date_string)  # "X個月"
        if m:
            months = int(m.group(1))
            now = datetime.now(timezone.utc)
            is_nearly = "\u8fd1" in date_string  # "近" — nearly
            days = int(months * 30 * 0.85) if is_nearly else months * 30
            return datetime(now.year, now.month, now.day) - timedelta(days=days)
        return None

    # Try OfferToday short date formats: "發布於06-15", "更新於06-24"
    short_m = re.search(r"(\d{2})-(\d{2})$", date_string)
    if short_m:
        month = int(short_m.group(1))
        day = int(short_m.group(2))
        now = datetime.now(timezone.utc)
        year = now.year
        # If the parsed date is in the future relative to current month, use previous year
        if month > now.month:
            year = now.year - 1
        try:
            return datetime(year, month, day)
        except ValueError:
            return None

    try:
        # Handle ISO format with Z suffix
        if date_string.endswith("Z"):
            date_string = date_string[:-1] + "+00:00"

        # Try parsing ISO format
        return datetime.fromisoformat(date_string)
    except (ValueError, TypeError) as e:
        logger.warning(f"Failed to parse date '{date_string}': {e}")
        return None


def join_work_types(work_types: Optional[List[str]]) -> Optional[str]:
    """
    Convert work types array to comma-separated string.

    Args:
        work_types: List of work type strings (e.g., ["Full-time", "Permanent"])

    Returns:
        Comma-separated string or None if empty
    """
    if not work_types:
        return None

    try:
        return ", ".join(str(wt) for wt in work_types if wt)
    except Exception as e:
        logger.warning(f"Failed to join work types: {e}")
        return None


def parse_salary_range(salary_label: Optional[str]) -> Tuple[Optional[int], Optional[int], str]:
    """
    Parse salary label string into min, max, and currency.

    Handles formats:
    - "HK$30,000 - HK$40,000"
    - "HK$30K - HK$40K"
    - "HK$30,000 - HK$40,000 per month"
    - "Negotiable"
    - None or empty

    Args:
        salary_label: Raw salary string from JobsDB

    Returns:
        Tuple of (salary_min, salary_max, currency)
    """
    if not salary_label:
        return None, None, 'HKD'

    # Default currency
    currency = 'HKD'

    # Clean the string
    salary_str = salary_label.strip()

    # Check for non-numeric salary labels
    if salary_str.lower() in ['negotiable', 'competitive', 'not specified', '']:
        return None, None, currency

    try:
        # Pattern for HK$ amounts with optional K suffix
        # Matches: HK$30,000 or HK$30K or $30,000
        pattern = r'(?:HK)?\$\s*([\d,]+)\s*([Kk])?'
        matches = re.findall(pattern, salary_str)

        if len(matches) >= 2:
            # Range format: min - max
            min_val = _parse_salary_value(matches[0][0], matches[0][1])
            max_val = _parse_salary_value(matches[1][0], matches[1][1])
            return min_val, max_val, currency
        elif len(matches) == 1:
            # Single value
            val = _parse_salary_value(matches[0][0], matches[0][1])
            return val, val, currency

    except Exception as e:
        logger.warning(f"Failed to parse salary '{salary_label}': {e}")

    return None, None, currency


def _parse_salary_value(amount_str: str, suffix: Optional[str]) -> Optional[int]:
    """Parse a single salary value."""
    try:
        # Remove commas
        amount = amount_str.replace(',', '')
        value = int(amount)

        # Handle K suffix (multiply by 1000)
        if suffix and suffix.lower() == 'k':
            value *= 1000

        return value
    except (ValueError, TypeError):
        return None


def map_scraped_company_to_db(scraped_job: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract company data from scraped job and map to Company schema.

    Handles both list API format and detail scraper format.

    Args:
        scraped_job: Transformed job data from REST API or detail scraper

    Returns:
        Company data dict with keys: company_id, name, industry, location, extra_data
    """
    try:
        # Handle both list API and detail scraper formats
        company_data = {
            "source_site": "jobsdb",
            "source_company_id": scraped_job.get("advertiser_id") or scraped_job.get("company_id"),
            "company_id": scraped_job.get("advertiser_id") or scraped_job.get("company_id"),
            "name": (
                scraped_job.get("company_name") or
                scraped_job.get("advertiser_name") or
                scraped_job.get("advertiser", {}).get("name") or
                "Unknown Company"
            ),
            "industry": scraped_job.get("classification_name") or scraped_job.get("classification"),
            "location": scraped_job.get("location"),
            "extra_data": {
                "logo_url": scraped_job.get("logo_url"),
                "advertiser_name": scraped_job.get("advertiser_name"),
                "bullet_points": scraped_job.get("bullet_points") or scraped_job.get("bullets"),
                "work_arrangements": scraped_job.get("work_arrangements"),
            },
        }
        return company_data
    except Exception as e:
        logger.error(f"Error mapping company data: {e}")
        raise


def map_scraped_job_to_db(
    scraped_job: Dict[str, Any], company_id: str
) -> Dict[str, Any]:
    """
    Transform scraped job data to Job database schema.

    Handles both list API format and detail scraper format.

    Args:
        scraped_job: Transformed job data from REST API or detail scraper
        company_id: UUID of the company (from database)

    Returns:
        Job data dict ready for database insertion
    """
    try:
        # Handle work_type (detail scraper) vs work_types (list API)
        work_type = scraped_job.get("work_type")
        if not work_type:
            work_type = join_work_types(scraped_job.get("work_types"))

        # Handle description: detail scraper has description_html, list API has teaser
        description = (
            scraped_job.get("description_html") or
            scraped_job.get("abstract") or
            scraped_job.get("teaser")
        )

        # Parse salary range
        salary_label = scraped_job.get("salary_label") or scraped_job.get("salary")
        salary_min, salary_max, salary_currency = parse_salary_range(salary_label)

        job_data = {
            # job_id: detail scraper uses jobsdb_id, list API uses external_id
            "job_id": scraped_job.get("external_id") or scraped_job.get("jobsdb_id"),
            "source_site": "jobsdb",
            "source_job_id": scraped_job.get("external_id") or scraped_job.get("jobsdb_id"),
            "company_id": company_id,
            "title": scraped_job.get("title"),
            "description": description,
            "salary_range": scraped_job.get("salary_label") or scraped_job.get("salary"),
            "salary_min": salary_min,
            "salary_max": salary_max,
            "salary_currency": salary_currency,
            "location": scraped_job.get("location"),
            "employment_type": work_type,
            "source_classification_id": scraped_job.get("classification_id"),
            "source_classification_name": (
                scraped_job.get("classification_name") or scraped_job.get("classification")
            ),
            "source_subclassification_id": scraped_job.get("subclassification_id"),
            "source_subclassification_name": scraped_job.get("subclassification"),
            "posted_date": parse_listing_date(scraped_job.get("listing_date")),
            "raw_data": scraped_job,
        }
        return job_data
    except Exception as e:
        logger.error(f"Error mapping job data: {e}")
        raise


def map_source_scraped_company_to_db(scraped_job: Dict[str, Any]) -> Dict[str, Any]:
    """Source-aware wrapper for company mapping.

    JobsDB behavior must remain unchanged; CTgoodjobs may populate alternate keys.
    """
    company_data = map_scraped_company_to_db(scraped_job)
    source_site = scraped_job.get("source_site")
    if source_site == "ctgoodjobs":
        company_data["source_site"] = "ctgoodjobs"
        company_data["source_company_id"] = str(scraped_job.get("company_id") or "").strip() or None
        company_data["company_id"] = _namespace_ctgoodjobs_id(company_data.get("company_id"))
        if not company_data.get("industry"):
            industry = scraped_job.get("source_classification_name")
            if isinstance(industry, str) and industry.strip():
                company_data["industry"] = industry.strip()
    return company_data


def _parse_optional_iso_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        parsed = parse_listing_date(value)
        if parsed is not None:
            return parsed
        # CTgoodjobs dates are often ISO-like but without trailing Z.
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def map_ctgoodjobs_scraped_job_to_db(scraped_job: Dict[str, Any], company_id: str) -> Dict[str, Any]:
    """Map a CTgoodjobs merged payload into the Job DB schema."""
    salary_label = scraped_job.get("salary_range") or scraped_job.get("salary")
    parsed_salary_min, parsed_salary_max, parsed_salary_currency = parse_salary_range(
        salary_label if isinstance(salary_label, str) else None
    )

    salary_min = scraped_job.get("salary_min")
    if not isinstance(salary_min, int):
        salary_min = parsed_salary_min

    salary_max = scraped_job.get("salary_max")
    if not isinstance(salary_max, int):
        salary_max = parsed_salary_max

    salary_currency = scraped_job.get("salary_currency")
    if not isinstance(salary_currency, str) or not salary_currency.strip():
        salary_currency = parsed_salary_currency

    description = (
        scraped_job.get("description_html")
        or scraped_job.get("description_text")
        or scraped_job.get("description")
    )

    return {
        "job_id": scraped_job.get("job_id"),
        "source_site": scraped_job.get("source_site") or "ctgoodjobs",
        "source_job_id": str(scraped_job.get("job_id") or "").removeprefix("ctgoodjobs:"),
        "company_id": company_id,
        "title": scraped_job.get("title"),
        "description": description,
        "salary_range": salary_label,
        "salary_min": salary_min,
        "salary_max": salary_max,
        "salary_currency": salary_currency,
        "experience_min_years": scraped_job.get("experience_min_years"),
        "experience_max_years": scraped_job.get("experience_max_years"),
        "location": scraped_job.get("location"),
        "employment_type": scraped_job.get("employment_type"),
        "source_classification_id": scraped_job.get("source_classification_id"),
        "source_classification_name": scraped_job.get("source_classification_name"),
        "source_subclassification_id": scraped_job.get("source_subclassification_id"),
        "source_subclassification_name": scraped_job.get("source_subclassification_name"),
        "posted_date": _parse_optional_iso_datetime(scraped_job.get("posted_date")),
        "raw_data": scraped_job,
    }


def map_source_scraped_job_to_db(scraped_job: Dict[str, Any], company_id: str) -> Dict[str, Any]:
    """Source-aware wrapper for job mapping.

    JobsDB mapping behavior must remain unchanged when `source_site` is absent.
    """
    if scraped_job.get("source_site") == "ctgoodjobs":
        return map_ctgoodjobs_scraped_job_to_db(scraped_job, company_id)
    return map_scraped_job_to_db(scraped_job, company_id)
