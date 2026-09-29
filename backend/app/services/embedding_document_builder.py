from __future__ import annotations

from dataclasses import dataclass
import hashlib
import html
import re

from app.search.embedding_contract import EMBEDDING_DOCUMENT_CONTRACT


@dataclass(frozen=True)
class EmbeddingDocument:
    document_text: str
    document_hash: str
    document_contract: str = EMBEDDING_DOCUMENT_CONTRACT


class EmbeddingDocumentBuilder:
    """Build the deterministic Description-only Job Browser search document."""

    def __init__(self, *, description_excerpt_chars: int = 2000):
        self.description_excerpt_chars = max(1, int(description_excerpt_chars))

    def build_for_job(self, job) -> EmbeddingDocument:
        description_excerpt = self._build_description_excerpt(
            getattr(job, "description", None)
        )
        document_text = description_excerpt
        hash_input = f"{EMBEDDING_DOCUMENT_CONTRACT}\n{document_text}"
        document_hash = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()
        return EmbeddingDocument(
            document_text=document_text,
            document_hash=document_hash,
        )

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
