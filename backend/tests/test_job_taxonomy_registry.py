from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.job_intelligence.canonical_taxonomy import (
    CanonicalClassifierContext,
    CanonicalClassifierTarget,
    CanonicalEvaluationError,
    CanonicalTaxonomyPreflight,
)
from app.services.job_taxonomy_registry import (
    LegacyJobTaxonomyRegistryRetiredError,
    get_job_taxonomy_registry,
)


class _SourceAttributes:
    def __init__(self, *, view=object(), error: Exception | None = None):
        self.view = view
        self.error = error

    def get(self, _job_id):
        if self.error is not None:
            raise self.error
        return self.view


class _CanonicalTaxonomy:
    def __init__(self, *, context=None, error: Exception | None = None):
        self.context = context
        self.error = error

    def build_classifier_context(self, _evidence):
        if self.error is not None:
            raise self.error
        return self.context


def _context(*, blocking_reasons=(), include_target=True):
    targets = (
        (
            CanonicalClassifierTarget(
                code="software.software_development.backend_development",
                label="Backend Development",
                breadcrumb=(
                    "Information Technology / Software Development / "
                    "Backend Development"
                ),
            ),
        )
        if include_target
        else ()
    )
    return CanonicalClassifierContext(
        taxonomy_revision_id=uuid4(),
        mapping_revision_id=uuid4(),
        source_classification_paths=(),
        canonical_targets=targets,
        blocking_reasons=blocking_reasons,
    )


def _preflight(*, context=None, source_error=None, canonical_error=None):
    return CanonicalTaxonomyPreflight(
        db=object(),
        source_attributes=_SourceAttributes(error=source_error),
        canonical_taxonomy=_CanonicalTaxonomy(
            context=context,
            error=canonical_error,
        ),
    )


def test_active_canonical_context_is_the_only_supported_preflight():
    result = _preflight(context=_context()).inspect(SimpleNamespace(id=uuid4()))

    assert result.status == "supported"
    assert result.reasons == ()
    assert result.reason is None
    assert result.context is not None


def test_canonical_preflight_preserves_all_blocking_mapping_reasons():
    result = _preflight(
        context=_context(
            blocking_reasons=(
                "source_mapping_excluded",
                "source_mapping_unmapped",
            )
        )
    ).inspect(SimpleNamespace(id=uuid4()))

    assert result.status == "excluded"
    assert result.reasons == (
        "source_mapping_excluded",
        "source_mapping_unmapped",
    )
    assert result.reason == "source_mapping_excluded,source_mapping_unmapped"


@pytest.mark.parametrize(
    ("source_error", "canonical_error", "expected_reason"),
    [
        (ValueError("missing projection"), None, "source_classification_paths_missing"),
        (
            None,
            CanonicalEvaluationError(
                "CANONICAL_MAPPING_NOT_ACTIVE",
                "No compatible active mapping",
            ),
            "CANONICAL_MAPPING_NOT_ACTIVE",
        ),
    ],
)
def test_missing_evidence_or_active_mapping_fails_closed(
    source_error,
    canonical_error,
    expected_reason,
):
    result = _preflight(
        context=_context(),
        source_error=source_error,
        canonical_error=canonical_error,
    ).inspect(SimpleNamespace(id=uuid4()))

    assert result.status == "excluded"
    assert result.reason == expected_reason


def test_empty_canonical_slice_fails_closed_without_default_path_guess():
    result = _preflight(context=_context(include_target=False)).inspect(
        SimpleNamespace(id=uuid4())
    )

    assert result.status == "excluded"
    assert result.reasons == ("canonical_target_invalid",)


def test_legacy_label_registry_is_explicitly_retired():
    with pytest.raises(
        LegacyJobTaxonomyRegistryRetiredError,
        match="active canonical mapping",
    ):
        get_job_taxonomy_registry()
