import json
from pathlib import Path
from types import SimpleNamespace

from scripts.batch_enrich_jobs import (
    _build_audit_row,
    _build_description_preview,
    _collect_signal_profile,
    _job_matches_filters,
    _write_csv_report,
    _write_json_report,
)


def _build_job(*, title: str, description: str, source_subclassification_name: str, category_name: str, subcategory_name: str):
    return SimpleNamespace(
        title=title,
        description=description,
        source_site="jobsdb",
        source_subclassification_name=source_subclassification_name,
        job_taxonomy={
            "category_name": category_name,
            "subcategory_name": subcategory_name,
        },
        skills=[],
        provisional_skills=[],
        job_skill_mentions=[],
    )


def test_job_matches_filters_accepts_devops_like_backend_candidate():
    job = _build_job(
        title="Senior DevOps Engineer (AWS, Alicloud)",
        description="Own CI/CD, Terraform, Kubernetes, Docker, and cloud infrastructure.",
        source_subclassification_name="Engineering - Software",
        category_name="Software Development",
        subcategory_name="Backend Development",
    )

    assert _job_matches_filters(
        job,
        source_site="jobsdb",
        source_subclassification="Engineering - Software",
        current_category="Software Development",
        current_subcategory="Backend Development",
        title_contains=["devops", "sre"],
        description_contains=["terraform", "kubernetes", "docker"],
    ) is True


def test_job_matches_filters_rejects_regular_backend_role_without_devops_signals():
    job = _build_job(
        title="Senior Backend Engineer",
        description="Build APIs with Python and PostgreSQL for customer features.",
        source_subclassification_name="Engineering - Software",
        category_name="Software Development",
        subcategory_name="Backend Development",
    )

    assert _job_matches_filters(
        job,
        source_site="jobsdb",
        source_subclassification="Engineering - Software",
        current_category="Software Development",
        current_subcategory="Backend Development",
        title_contains=["devops", "sre"],
        description_contains=["terraform", "kubernetes", "docker"],
    ) is False


def test_job_matches_filters_respects_negative_title_and_description_fragments():
    job = _build_job(
        title="Senior Backend Engineer – Node.js (Azure & Kubernetes)",
        description="Build backend APIs and microservices with Docker and Kubernetes.",
        source_subclassification_name="Engineering - Software",
        category_name="Software Development",
        subcategory_name="Backend Development",
    )

    assert _job_matches_filters(
        job,
        source_site="jobsdb",
        source_subclassification="Engineering - Software",
        current_category="Software Development",
        current_subcategory="Backend Development",
        description_contains=["docker", "kubernetes"],
        title_not_contains=["backend engineer"],
        description_not_contains=["microservices", "backend apis"],
    ) is False


def test_job_matches_filters_can_require_multiple_description_signal_hits():
    job = _build_job(
        title="Software Developer/Engineer",
        description="Maintain test environments, CI/CD pipelines, and environment provisioning with Terraform and Kubernetes.",
        source_subclassification_name="Engineering - Software",
        category_name="Software Development",
        subcategory_name="Backend Development",
    )

    assert _job_matches_filters(
        job,
        source_site="jobsdb",
        source_subclassification="Engineering - Software",
        current_category="Software Development",
        current_subcategory="Backend Development",
        description_contains=["test environments", "ci/cd pipelines", "environment provisioning"],
        min_description_fragment_hits=3,
    ) is True

    assert _job_matches_filters(
        job,
        source_site="jobsdb",
        source_subclassification="Engineering - Software",
        current_category="Software Development",
        current_subcategory="Backend Development",
        description_contains=["test environments", "ci/cd pipelines", "environment provisioning", "ansible"],
        min_description_fragment_hits=4,
    ) is False


def test_job_matches_filters_can_target_explicit_job_ids():
    job = _build_job(
        title="Senior DevOps Engineer",
        description="Own CI/CD, Terraform, Docker, and Kubernetes.",
        source_subclassification_name="Engineering - Software",
        category_name="Software Development",
        subcategory_name="Backend Development",
    )
    job.id = "job-123"

    assert _job_matches_filters(job, job_ids={"job-123"}) is True
    assert _job_matches_filters(job, job_ids={"job-999"}) is False


def test_collect_signal_profile_marks_obvious_devops_roles_as_infra_devops():
    job = _build_job(
        title="Senior DevOps Engineer",
        description="Own CI/CD, Terraform, Docker, Kubernetes, and Linux operations.",
        source_subclassification_name="Engineering - Software",
        category_name="Software Development",
        subcategory_name="Backend Development",
    )
    job.skills = ["Terraform", "Docker", "Kubernetes", "Linux"]
    job.provisional_skills = ["Bash"]

    profile = _collect_signal_profile(job)

    assert profile["bucket"] == "infra-devops"
    assert "devops" in profile["infra_title_hits"]


def test_build_description_preview_strips_html_and_truncates():
    preview = _build_description_preview(
        "<p>Maintain <strong>test environments</strong> and support CI/CD pipelines with Docker and Kubernetes.</p>",
        max_length=40,
    )

    assert preview.startswith("Maintain test environments and")
    assert preview.endswith("...")


def test_collect_signal_profile_marks_explicit_backend_roles_as_backend_platform():
    job = _build_job(
        title="Senior Backend Engineer - Node.js",
        description="Build backend APIs and microservices in a cloud-native environment.",
        source_subclassification_name="Engineering - Software",
        category_name="Software Development",
        subcategory_name="BackendDevelopment",
    )
    job.skills = ["Node.js", "RESTful APIs"]
    job.provisional_skills = []

    profile = _collect_signal_profile(job)

    assert profile["bucket"] == "backend-platform"
    assert "backend engineer" in profile["backend_title_hits"]


def test_job_matches_filters_can_filter_by_signal_bucket():
    job = _build_job(
        title="Senior DevOps Engineer",
        description="Own CI/CD, Terraform, Docker, and Kubernetes.",
        source_subclassification_name="Engineering - Software",
        category_name="Software Development",
        subcategory_name="Backend Development",
    )
    job.skills = ["Terraform", "Docker", "Kubernetes"]
    job.provisional_skills = []

    assert _job_matches_filters(job, signal_buckets={"infra-devops"}) is True
    assert _job_matches_filters(job, signal_buckets={"backend-platform"}) is False


def test_build_audit_row_and_write_json_report_capture_taxonomy_and_signal_profile(tmp_path):
    job = _build_job(
        title="Senior DevOps Engineer",
        description="Own CI/CD, Terraform, Docker, and Kubernetes.",
        source_subclassification_name="Engineering - Software",
        category_name="Software Development",
        subcategory_name="Backend Development",
    )
    job.id = "job-123"
    job.original_job_url = "https://example.com/job-123"
    job.job_taxonomy["path"] = "Information & Communication Technology / Software Development / Backend Development"
    job.skills = ["Terraform", "Docker"]
    job.provisional_skills = ["Bash"]
    job.job_skill_mentions = [object(), object()]

    row = _build_audit_row(job)

    assert row["job_id"] == "job-123"
    assert row["taxonomy_path"] == "Information & Communication Technology / Software Development / Backend Development"
    assert row["original_job_url"] == "https://example.com/job-123"
    assert row["governed_skill_count"] == 2
    assert row["signal_profile"]["bucket"] == "infra-devops"
    assert row["suggested_action"] == "move_infra"
    assert "description_preview" in row

    output_file = tmp_path / "report.json"
    _write_json_report(
        output_file=str(output_file),
        audit_rows=[row],
        bucket_summary={"infra-devops": 1},
    )

    payload = json.loads(output_file.read_text(encoding="utf-8"))
    assert payload["total"] == 1
    assert payload["bucket_summary"] == {"infra-devops": 1}
    assert payload["jobs"][0]["job_id"] == "job-123"

    csv_output = tmp_path / "report.csv"
    _write_csv_report(output_file=str(csv_output), audit_rows=[row])
    csv_text = csv_output.read_text(encoding="utf-8")
    assert "job_id,title,source_site" in csv_text
    assert "job-123" in csv_text
    assert "Terraform | Docker" in csv_text


def test_build_audit_row_prefers_keep_backend_for_devtestops_with_strong_backend_delivery_signals():
    job = _build_job(
        title="Software Developer/Engineer",
        description=(
            "Maintain test environments, CI/CD pipelines, environment provisioning, "
            "and support microservices plus RESTful APIs with Java, Docker, Kubernetes, and Terraform."
        ),
        source_subclassification_name="Engineering - Software",
        category_name="Software Development",
        subcategory_name="Backend Development",
    )
    job.id = "job-456"
    job.job_taxonomy["path"] = "Information & Communication Technology / Software Development / Backend Development"
    job.skills = ["Java", "Docker", "Kubernetes", "Terraform", "RESTful APIs"]
    job.provisional_skills = ["Ansible"]
    job.job_skill_mentions = [object(), object(), object()]

    row = _build_audit_row(job)

    assert row["signal_profile"]["bucket"] == "devtestops"
    assert row["suggested_action"] == "keep_backend"
