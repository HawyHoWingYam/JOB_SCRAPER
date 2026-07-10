from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class OfferTodayListingCondition:
    search_family: str
    category_id: int | None
    keyword: str
    endpoint: Literal["search", "browse"]
    rcd_type: int | None = 7

    @property
    def condition_id(self) -> str:
        canonical_json = json.dumps(
            {
                "category_id": self.category_id,
                "endpoint": self.endpoint,
                "keyword": self.keyword,
                "rcd_type": self.rcd_type,
                "search_family": self.search_family,
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(canonical_json.encode()).hexdigest()
