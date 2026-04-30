from dataclasses import dataclass
from typing import Optional


REGION_HONG_KONG_WIDE = "Hong Kong-wide"
REGION_HONG_KONG_ISLAND = "Hong Kong Island"
REGION_KOWLOON = "Kowloon"
REGION_NEW_TERRITORIES = "New Territories"
REGION_OTHER = "Other"

REGION_ORDER = [
    REGION_HONG_KONG_WIDE,
    REGION_HONG_KONG_ISLAND,
    REGION_KOWLOON,
    REGION_NEW_TERRITORIES,
    REGION_OTHER,
]

DISTRICT_TO_REGION = {
    "Central and Western District": REGION_HONG_KONG_ISLAND,
    "Eastern District": REGION_HONG_KONG_ISLAND,
    "Southern District": REGION_HONG_KONG_ISLAND,
    "Wan Chai District": REGION_HONG_KONG_ISLAND,
    "Kowloon City District": REGION_KOWLOON,
    "Kwun Tong District": REGION_KOWLOON,
    "Sham Shui Po District": REGION_KOWLOON,
    "Wong Tai Sin District": REGION_KOWLOON,
    "Yau Tsim Mong District": REGION_KOWLOON,
    "Islands District": REGION_NEW_TERRITORIES,
    "Kwai Tsing District": REGION_NEW_TERRITORIES,
    "North District": REGION_NEW_TERRITORIES,
    "Sai Kung District": REGION_NEW_TERRITORIES,
    "Sha Tin District": REGION_NEW_TERRITORIES,
    "Tai Po District": REGION_NEW_TERRITORIES,
    "Tsuen Wan District": REGION_NEW_TERRITORIES,
    "Tuen Mun District": REGION_NEW_TERRITORIES,
    "Yuen Long District": REGION_NEW_TERRITORIES,
}

SPECIAL_REGION_VALUES = {
    "Hong Kong SAR": REGION_HONG_KONG_WIDE,
    "Hong Kong": REGION_HONG_KONG_WIDE,
    REGION_HONG_KONG_ISLAND: REGION_HONG_KONG_ISLAND,
    REGION_KOWLOON: REGION_KOWLOON,
    REGION_NEW_TERRITORIES: REGION_NEW_TERRITORIES,
    "Others": REGION_OTHER,
    REGION_OTHER: REGION_OTHER,
}


@dataclass(frozen=True)
class NormalizedLocation:
    region: str
    district: Optional[str]
    raw: str


def normalize_location(raw: Optional[str]) -> NormalizedLocation:
    value = (raw or "").strip()
    if value in SPECIAL_REGION_VALUES:
        return NormalizedLocation(
            region=SPECIAL_REGION_VALUES[value],
            district=None,
            raw=value,
        )

    district = _extract_district(value)
    if district:
        return NormalizedLocation(
            region=DISTRICT_TO_REGION[district],
            district=district,
            raw=value,
        )

    return NormalizedLocation(region=REGION_OTHER, district=None, raw=value)


def _extract_district(value: str) -> Optional[str]:
    if not value:
        return None

    if value in DISTRICT_TO_REGION:
        return value

    candidate = value.split(",")[-1].strip()
    if candidate in DISTRICT_TO_REGION:
        return candidate

    return None
