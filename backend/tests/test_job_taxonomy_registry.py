from app.services.job_taxonomy_registry import get_job_taxonomy_registry


def test_engineering_software_slice_allows_infrastructure_support_for_devops_like_roles():
    registry = get_job_taxonomy_registry()

    source_slice = registry.get_allowed_slice(
        source_classification_id="6281",
        source_classification_name="Information & Communication Technology",
        source_subclassification_name="Engineering - Software",
    )

    assert "Software Development" in source_slice.allowed_categories
    assert "Infrastructure & Support" in source_slice.allowed_categories
    assert source_slice.default_path == (
        "Information & Communication Technology",
        "Software Development",
        "Backend Development",
    )
