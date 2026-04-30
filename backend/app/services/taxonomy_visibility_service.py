"""Promotion logic for governed taxonomy visibility."""

from typing import Optional

from app.config import settings
from app.utils.time import utc_now


class TaxonomyVisibilityService:
    """Tracks taxonomy usage and promotes mature nodes into filters."""

    def __init__(self, config=settings):
        self.settings = config

    def record_skill_usage(self, skill, is_distinct_job: bool) -> None:
        """Update leaf and parent skill taxonomy nodes after a skill match."""
        self._touch_node(skill, is_distinct_job, self.settings.filter_skill_l3_min_jobs)

        technology = getattr(skill, "technology", None)
        if technology is not None:
            self._touch_node(
                technology,
                is_distinct_job,
                self.settings.filter_skill_l2_min_jobs,
            )

            category = getattr(technology, "category", None)
            if category is not None:
                self._touch_node(
                    category,
                    is_distinct_job,
                    self.settings.filter_skill_l1_min_jobs,
                )

    def record_job_taxonomy_usage(self, subcategory, is_distinct_job: bool) -> None:
        """Update leaf and parent job taxonomy nodes after a category match."""
        self._touch_node(
            subcategory,
            is_distinct_job,
            self.settings.filter_job_l3_min_jobs,
        )

        category = getattr(subcategory, "category", None)
        if category is not None:
            self._touch_node(
                category,
                is_distinct_job,
                self.settings.filter_job_l2_min_jobs,
            )

            domain = getattr(category, "domain", None)
            if domain is not None:
                self._touch_node(
                    domain,
                    is_distinct_job,
                    self.settings.filter_job_l1_min_jobs,
                )

    def _touch_node(self, node, is_distinct_job: bool, threshold: int) -> None:
        """Update usage counters and visibility state for a single node."""
        node.usage_count = (node.usage_count or 0) + 1
        if is_distinct_job:
            node.distinct_job_count = (node.distinct_job_count or 0) + 1

        node.last_used_at = utc_now()

        if (node.distinct_job_count or 0) >= threshold:
            node.is_filter_visible = True


_service: Optional[TaxonomyVisibilityService] = None


def get_taxonomy_visibility_service() -> TaxonomyVisibilityService:
    """Get singleton taxonomy visibility service."""
    global _service
    if _service is None:
        _service = TaxonomyVisibilityService()
    return _service
