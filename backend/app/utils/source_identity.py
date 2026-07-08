from __future__ import annotations

from typing import Any


def normalize_source_site(source_site: Any) -> str:
    normalized = str(source_site or "jobsdb").strip().lower()
    return normalized or "jobsdb"


def strip_source_prefix(value: Any, source_site: Any) -> str:
    raw_value = str(value or "").strip()
    normalized_source = normalize_source_site(source_site)
    prefix = f"{normalized_source}:"
    if raw_value.startswith(prefix):
        return raw_value[len(prefix):]
    return raw_value


def build_compat_job_id(source_site: Any, source_job_id: Any) -> str:
    normalized_source = normalize_source_site(source_site)
    raw_source_job_id = strip_source_prefix(source_job_id, normalized_source)
    if normalized_source == "ctgoodjobs":
        return f"{normalized_source}:{raw_source_job_id}"
    return raw_source_job_id


def derive_source_job_id(source_site: Any, job_id: Any) -> str:
    return strip_source_prefix(job_id, source_site)


def build_compat_company_id(source_site: Any, source_company_id: Any) -> str:
    normalized_source = normalize_source_site(source_site)
    raw_source_company_id = strip_source_prefix(source_company_id, normalized_source)
    if normalized_source == "ctgoodjobs":
        return f"{normalized_source}:{raw_source_company_id}"
    return raw_source_company_id


def derive_source_company_id_from_compat(source_site: Any, company_id: Any) -> str:
    return strip_source_prefix(company_id, source_site)


def derive_source_company_id_from_raw_data(source_site: Any, raw_data: Any) -> str | None:
    if not isinstance(raw_data, dict):
        return None

    normalized_source = normalize_source_site(source_site)

    for candidate in _iter_source_identity_payloads(raw_data):
        value = _derive_source_company_id_from_payload(normalized_source, candidate)
        if value is None:
            continue
        normalized_value = str(value).strip()
        if normalized_value:
            return normalized_value

    return None


def _iter_source_identity_payloads(raw_data: dict[str, Any]):
    yield raw_data

    nested_raw = raw_data.get("raw_data")
    if isinstance(nested_raw, dict):
        yield nested_raw


def _derive_source_company_id_from_payload(source_site: str, raw_data: dict[str, Any]) -> Any:
    if source_site == "ctgoodjobs":
        return raw_data.get("company_id")

    if source_site == "offertoday":
        return (
            raw_data.get("brandId")
            or raw_data.get("encryptBrandId")
            or raw_data.get("brand_id")
            or raw_data.get("companyId")
            or raw_data.get("company_id")
        )

    return raw_data.get("advertiser_id") or raw_data.get("company_id")
