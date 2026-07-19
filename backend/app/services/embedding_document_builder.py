from __future__ import annotations

from dataclasses import dataclass
import hashlib
import html
import re
from typing import Iterable


@dataclass(frozen=True)
class EmbeddingDocument:
    document_text: str
    document_hash: str


class EmbeddingDocumentBuilder:
    """Build a deterministic embedding document from a job's current database state."""

    def __init__(self, *, description_excerpt_chars: int = 2000):
        self.description_excerpt_chars = max(1, int(description_excerpt_chars))

    def build_for_job(
        self,
        job,
        *,
        governed_skill_names: Iterable[str] | None = None,
    ) -> EmbeddingDocument:
        sections: list[str] = []

        title = self._clean_text(getattr(job, "title", None))
        if title:
            sections.append(f"Title: {title}")

        company_name = self._clean_text(
            getattr(getattr(job, "company", None), "name", None)
        )
        if company_name:
            sections.append(f"Company: {company_name}")

        source_taxonomy = self._build_source_taxonomy(job)
        if source_taxonomy:
            sections.append(f"Source Taxonomy: {source_taxonomy}")

        ai_summary = self._clean_text(getattr(job, "ai_summary", None))
        if ai_summary:
            sections.append(f"AI Summary: {ai_summary}")

        skills = self._build_skills(job, governed_skill_names=governed_skill_names)
        if skills:
            sections.append(f"Skills: {' | '.join(skills)}")

        description_excerpt = self._build_description_excerpt(
            getattr(job, "description", None)
        )
        if description_excerpt:
            sections.append(f"Description: {description_excerpt}")

        document_text = "\n".join(sections)
        document_hash = hashlib.sha256(document_text.encode("utf-8")).hexdigest()
        return EmbeddingDocument(
            document_text=document_text,
            document_hash=document_hash,
        )

    def _build_source_taxonomy(self, job) -> str:
        parts = [
            self._clean_text(getattr(job, "source_classification_name", None)),
            self._clean_text(getattr(job, "source_subclassification_name", None)),
        ]
        return " | ".join(part for part in parts if part)

    def _build_skills(
        self,
        job,
        *,
        governed_skill_names: Iterable[str] | None,
    ) -> list[str]:
        names: set[str] = set()
        raw_names = (
            governed_skill_names
            if governed_skill_names is not None
            else (getattr(job, "skills", []) or [])
        )
        for raw_name in raw_names:
            name = self._clean_text(raw_name)
            if not name:
                continue
            names.add(name)
        return sorted(names)

    def _build_description_excerpt(self, value: str | None) -> str:
        cleaned = self._clean_text(value)
        if not cleaned:
            return ""
        return cleaned[: self.description_excerpt_chars]

    def _clean_text(self, value: str | None) -> str:
        if not value:
            return ""
        without_tags = re.sub(r"<[^>]+>", " ", value)
        collapsed = " ".join(html.unescape(without_tags).split())
        return collapsed.strip()
