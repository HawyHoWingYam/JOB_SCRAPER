"""Recommendation helpers for governed skill review candidates."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import re
from typing import Any, Iterable, Optional

from app.models import Skill, SkillCategory, SkillReviewCandidate, SkillTechnology
from app.services.skill_normalizer import SkillNormalizer
from app.utils.skill_taxonomy_policy import polluted_other_general_clause

try:
    from rapidfuzz import fuzz
except Exception:  # pragma: no cover - optional dependency
    fuzz = None

try:
    from sentence_transformers import SentenceTransformer
except Exception:  # pragma: no cover - optional dependency
    SentenceTransformer = None


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _cosine_similarity(lhs: list[float], rhs: list[float]) -> float:
    numerator = sum(left * right for left, right in zip(lhs, rhs))
    lhs_magnitude = sum(value * value for value in lhs) ** 0.5
    rhs_magnitude = sum(value * value for value in rhs) ** 0.5
    if lhs_magnitude == 0 or rhs_magnitude == 0:
        return 0.0
    return numerator / (lhs_magnitude * rhs_magnitude)


def _tokenize(value: str) -> set[str]:
    return {
        token
        for token in re.split(r"[^a-z0-9]+", value.lower())
        if token
    }


class TokenOverlapSemanticScorer:
    """Fallback semantic scorer that works without extra model dependencies."""

    def score(self, source: str, candidates: Iterable[str]) -> dict[str, float]:
        source_tokens = _tokenize(source)
        scores: dict[str, float] = {}
        for candidate in candidates:
            candidate_tokens = _tokenize(candidate)
            if not source_tokens or not candidate_tokens:
                scores[candidate] = 0.0
                continue
            overlap = source_tokens & candidate_tokens
            union = source_tokens | candidate_tokens
            scores[candidate] = len(overlap) / len(union)
        return scores


class SentenceTransformerSemanticScorer:
    """Optional scorer backed by sentence-transformers."""

    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2"):
        if SentenceTransformer is None:  # pragma: no cover - import gate
            raise RuntimeError("sentence-transformers is not installed")
        self._model = SentenceTransformer(model_name)

    def score(self, source: str, candidates: Iterable[str]) -> dict[str, float]:
        candidate_list = list(candidates)
        if not candidate_list:
            return {}

        source_embedding = self._model.encode(source, normalize_embeddings=True)
        candidate_embeddings = self._model.encode(
            candidate_list,
            normalize_embeddings=True,
        )
        return {
            candidate: _cosine_similarity(list(source_embedding), list(candidate_embedding))
            for candidate, candidate_embedding in zip(candidate_list, candidate_embeddings)
        }


@dataclass
class RecommendedSkill:
    skill_id: str
    skill: str
    category: str
    technology: str
    lexical_score: float
    semantic_score: float
    combined_score: float


class SkillRecommendationService:
    """Recommend canonical skills for unresolved review candidates."""

    def __init__(self, db, *, semantic_scorer: Optional[Any] = None):
        self.db = db
        self.normalizer = SkillNormalizer(db)
        if semantic_scorer is not None:
            self.semantic_scorer = semantic_scorer
        elif SentenceTransformer is not None:
            self.semantic_scorer = SentenceTransformerSemanticScorer()
        else:
            self.semantic_scorer = TokenOverlapSemanticScorer()

    def recommend_for_candidate(
        self,
        candidate: SkillReviewCandidate,
        *,
        top_k: int = 3,
    ) -> list[dict[str, Any]]:
        raw_name = str(candidate.raw_name or candidate.normalized_name or "").strip()
        if not raw_name:
            return []

        normalized_input = self.normalizer._canonicalize_name(raw_name)
        canonical_skills = self._load_canonical_skills()
        if not canonical_skills:
            return []

        semantic_scores = self.semantic_scorer.score(
            normalized_input,
            [entry["skill_name"] for entry in canonical_skills],
        )

        recommendations: list[RecommendedSkill] = []
        for entry in canonical_skills:
            lexical_score = self._lexical_similarity(
                normalized_input,
                entry["skill_name"],
                aliases=entry["aliases"],
            )
            semantic_score = float(semantic_scores.get(entry["skill_name"], 0.0))
            combined_score = (lexical_score * 0.7) + (semantic_score * 0.3)
            if candidate.suggested_category and candidate.suggested_category == entry["category_name"]:
                combined_score += 0.05
            if candidate.suggested_technology and candidate.suggested_technology == entry["technology_name"]:
                combined_score += 0.05
            recommendations.append(
                RecommendedSkill(
                    skill_id=entry["skill_id"],
                    skill=entry["skill_name"],
                    category=entry["category_name"],
                    technology=entry["technology_name"],
                    lexical_score=round(lexical_score, 4),
                    semantic_score=round(semantic_score, 4),
                    combined_score=round(min(combined_score, 1.0), 4),
                )
            )

        recommendations.sort(
            key=lambda recommendation: (
                recommendation.combined_score,
                recommendation.lexical_score,
                recommendation.semantic_score,
                recommendation.skill,
            ),
            reverse=True,
        )
        return [
            {
                "skill_id": recommendation.skill_id,
                "skill": recommendation.skill,
                "category": recommendation.category,
                "technology": recommendation.technology,
                "lexical_score": recommendation.lexical_score,
                "semantic_score": recommendation.semantic_score,
                "combined_score": recommendation.combined_score,
            }
            for recommendation in recommendations[:top_k]
        ]

    def cluster_candidates(
        self,
        candidates: Iterable[SkillReviewCandidate],
    ) -> dict[str, str]:
        cluster_map: dict[str, str] = {}
        for candidate in candidates:
            normalized_name = str(candidate.normalized_name or candidate.raw_name or "").strip()
            if not normalized_name:
                continue
            recommendations = self.recommend_for_candidate(candidate, top_k=1)
            if recommendations and recommendations[0]["combined_score"] >= 0.55:
                cluster_map[normalized_name] = _slugify(recommendations[0]["skill"])
            else:
                cluster_map[normalized_name] = _slugify(normalized_name)
        return cluster_map

    def _load_canonical_skills(self) -> list[dict[str, Any]]:
        query = (
            self.db.query(Skill, SkillTechnology, SkillCategory)
            .join(SkillTechnology, Skill.technology_id == SkillTechnology.id)
            .join(SkillCategory, SkillTechnology.category_id == SkillCategory.id)
            .filter(
                Skill.is_auto_created.is_(False),
                SkillTechnology.is_auto_created.is_(False),
                SkillCategory.is_auto_created.is_(False),
            )
            .filter(~polluted_other_general_clause(SkillCategory, SkillTechnology))
            .order_by(Skill.name.asc())
        )
        entries = []
        for skill, technology, category in query.all():
            entries.append(
                {
                    "skill_id": str(skill.id),
                    "skill_name": skill.name,
                    "technology_name": technology.name,
                    "category_name": category.name,
                    "aliases": self.normalizer._coerce_aliases(skill.aliases),
                }
            )
        return entries

    def _lexical_similarity(self, source: str, target: str, *, aliases: list[str]) -> float:
        candidates = [target, *aliases]
        if fuzz is not None:
            best = max(
                fuzz.token_set_ratio(source, candidate) / 100.0
                for candidate in candidates
            )
            return float(best)
        return max(
            SequenceMatcher(None, source.lower(), candidate.lower()).ratio()
            for candidate in candidates
        )
