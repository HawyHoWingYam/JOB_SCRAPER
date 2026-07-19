from __future__ import annotations

import re
import unicodedata


_DASHES = ("\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\u2212")


def normalize_skill_text(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    for dash in _DASHES:
        text = text.replace(dash, "-")
    return re.sub(r"\s+", " ", text)


def normalize_exact_skill_key(value: object) -> str:
    text = normalize_skill_text(value).casefold()
    text = re.sub(r"[^a-z0-9+#./\-\s]+", " ", text)
    text = re.sub(r"\s*([+#./-])\s*", r"\1", text)
    normalized = re.sub(r"\s+", " ", text).strip()
    return normalized or normalize_skill_text(value).casefold()


def normalize_skill_lookup_key(value: object) -> str:
    text = normalize_skill_text(value).casefold()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()
