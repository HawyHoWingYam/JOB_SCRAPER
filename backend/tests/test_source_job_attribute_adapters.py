from __future__ import annotations

from datetime import datetime, timezone

from app.job_intelligence.foundation import Provenance
from app.job_intelligence.source_attributes import (
    CTGoodJobsSourceEvidenceAdapter,
    JobsDBSourceEvidenceAdapter,
    OfferTodaySourceEvidenceAdapter,
    SourceClassificationContext,
)
from app.sources.contracts import (
    build_ctgoodjobs_canonical_job,
    build_jobsdb_canonical_job,
    build_jobsdb_listing_canonical_job,
    build_offertoday_canonical_job,
    build_offertoday_job_data,
)
from app.sources.ctgoodjobs.parsers import (
    parse_detail_page as parse_ctgoodjobs_detail_page,
)
from app.sources.jobsdb.parsers import parse_detail_redux_data, parse_search_response
from app.sources.offertoday.parsers import parse_offertoday_listing_rows
from app.sources.offertoday.parsers import parse_offertoday_detail_response


def test_jobsdb_adapter_preserves_every_source_path_and_employment_label():
    provenance = Provenance(
        method="jobsdb-listing-payload",
        source_site="jobsdb",
        evidence_refs=({"kind": "listing-payload", "source_job_id": "job-1"},),
        captured_at=datetime(2026, 7, 18, 8, 0, tzinfo=timezone.utc),
    )

    evidence = JobsDBSourceEvidenceAdapter().extract(
        {
            "classifications": [
                {
                    "classification": {
                        "id": "6281",
                        "description": "Information Technology",
                    },
                    "subclassification": {
                        "id": "6287",
                        "description": "Developers and Programmers",
                    },
                },
                {
                    "classification": {
                        "id": "6092",
                        "description": "Engineering",
                    }
                },
            ],
            "workTypes": ["Full-time", "Permanent"],
            "workArrangements": {
                "data": [{"label": {"text": "Remote"}}],
            },
        },
        provenance=provenance,
    )

    assert evidence.to_payload() == {
        "source_site": "jobsdb",
        "classification_paths": [
            {
                "source_order": 0,
                "nodes": [
                    {
                        "source_position": 0,
                        "native_depth": 0,
                        "source_classification_id": "jobsdb:6281",
                        "native_id": "6281",
                        "label": "Information Technology",
                    },
                    {
                        "source_position": 1,
                        "native_depth": 1,
                        "source_classification_id": "jobsdb:6287",
                        "native_id": "6287",
                        "label": "Developers and Programmers",
                    },
                ],
                "source_declared_primary": False,
                "primary_basis": None,
                "source_catalog_revision": None,
                "provenance": provenance.to_payload(),
            },
            {
                "source_order": 1,
                "nodes": [
                    {
                        "source_position": 0,
                        "native_depth": 0,
                        "source_classification_id": "jobsdb:6092",
                        "native_id": "6092",
                        "label": "Engineering",
                    }
                ],
                "source_declared_primary": False,
                "primary_basis": None,
                "source_catalog_revision": None,
                "provenance": provenance.to_payload(),
            },
        ],
        "employment_labels": [
            {
                "source_order": 0,
                "raw_code": None,
                "raw_label": "Full-time",
                "normalized_lookup_key": "full-time",
                "mapped_type_code": "full_time",
                "mapping_id": "jobsdb-label-v1:full-time",
                "provenance": provenance.to_payload(),
            },
            {
                "source_order": 1,
                "raw_code": None,
                "raw_label": "Permanent",
                "normalized_lookup_key": "permanent",
                "mapped_type_code": "permanent",
                "mapping_id": "jobsdb-label-v1:permanent",
                "provenance": provenance.to_payload(),
            },
        ],
        "work_arrangements": ["Remote"],
        "working_day_labels": [],
    }


def test_ctgoodjobs_adapter_preserves_root_context_and_first_employment_evidence():
    captured_at = datetime(2026, 7, 18, 8, 30, tzinfo=timezone.utc)
    payload_provenance = Provenance(
        method="ctgoodjobs-detail-payload",
        source_site="ctgoodjobs",
        evidence_refs=({"kind": "detail-payload", "source_job_id": "job-2"},),
        captured_at=captured_at,
    )
    context_provenance = Provenance(
        method="crawl-context",
        source_site="ctgoodjobs",
        evidence_refs=({"kind": "crawl-job-listing", "id": "listing-2"},),
        captured_at=captured_at,
    )

    evidence = CTGoodJobsSourceEvidenceAdapter().extract(
        {
            "jobContent": {
                "workTypes": [
                    {"code": "FT", "name": "Full-time"},
                    {"code": "OTHER", "name": "Other"},
                ]
            },
            "basicInfo": {"empTypes": [{"name": "Part-time"}]},
            "jobPosting": {"employmentType": ["TEMPORARY"]},
        },
        provenance=payload_provenance,
        classification_context=SourceClassificationContext(
            source_classification_id="ctgoodjobs:021",
            label="Information Technology",
            source_catalog_revision=None,
            provenance=context_provenance,
        ),
    )

    assert evidence.to_payload() == {
        "source_site": "ctgoodjobs",
        "classification_paths": [
            {
                "source_order": 0,
                "nodes": [
                    {
                        "source_position": 0,
                        "native_depth": 0,
                        "source_classification_id": "ctgoodjobs:021",
                        "native_id": "021",
                        "label": "Information Technology",
                    }
                ],
                "source_declared_primary": False,
                "primary_basis": None,
                "source_catalog_revision": None,
                "provenance": context_provenance.to_payload(),
            }
        ],
        "employment_labels": [
            {
                "source_order": 0,
                "raw_code": "FT",
                "raw_label": "Full-time",
                "normalized_lookup_key": "full-time",
                "mapped_type_code": "full_time",
                "mapping_id": "ctgoodjobs-label-v1:full-time",
                "provenance": payload_provenance.to_payload(),
            },
            {
                "source_order": 1,
                "raw_code": "OTHER",
                "raw_label": "Other",
                "normalized_lookup_key": "other",
                "mapped_type_code": None,
                "mapping_id": None,
                "provenance": payload_provenance.to_payload(),
            },
        ],
        "work_arrangements": [],
        "working_day_labels": [],
    }


def test_offertoday_adapter_preserves_semantic_paths_codes_and_separate_work_evidence():
    provenance = Provenance(
        method="offertoday-detail-payload",
        source_site="offertoday",
        evidence_refs=({"kind": "detail-payload", "source_job_id": "job-3"},),
        captured_at=datetime(2026, 7, 18, 9, 0, tzinfo=timezone.utc),
    )

    evidence = OfferTodaySourceEvidenceAdapter().extract(
        {
            "jobFunctions": [
                {
                    "code": "118000",
                    "name": "Information Technology",
                    "children": [
                        {"code": "118000", "name": "IT alias"},
                        {"code": "118100", "name": "Software Development"},
                    ],
                },
                {"code": "119000", "name": "Design", "children": []},
                {
                    "code": "118000",
                    "name": "Information Technology",
                    "children": [{"code": "118100", "name": "Software Development"}],
                },
            ],
            "jobType": 1,
            "jobTypeDesc": "全職",
            "employType": {"name": "全職"},
            "workingModels": "Hybrid",
            "workingDays": "Five days",
        },
        provenance=provenance,
    )

    payload = evidence.to_payload()
    assert {
        "paths": [
            [node["source_classification_id"] for node in path["nodes"]]
            for path in payload["classification_paths"]
        ],
        "path_orders": [
            path["source_order"] for path in payload["classification_paths"]
        ],
        "employment": [
            (
                label["raw_code"],
                label["raw_label"],
                label["mapped_type_code"],
                label["mapping_id"],
            )
            for label in payload["employment_labels"]
        ],
        "work_arrangements": payload["work_arrangements"],
        "working_day_labels": payload["working_day_labels"],
        "has_primary": any(
            path["source_declared_primary"] for path in payload["classification_paths"]
        ),
    } == {
        "paths": [
            ["offertoday:118000"],
            ["offertoday:118000", "offertoday:118100"],
            ["offertoday:119000"],
        ],
        "path_orders": [0, 1, 2],
        "employment": [
            ("1", "全職", "full_time", "offertoday-code-v1:1"),
            (None, "全職", "full_time", "offertoday-label-v1:全職"),
        ],
        "work_arrangements": ["Hybrid"],
        "working_day_labels": ["Five days"],
        "has_primary": False,
    }


def test_jobsdb_listing_canonical_payload_transports_complete_source_evidence():
    parsed = parse_search_response(
        {
            "data": [
                {
                    "id": "job-4",
                    "title": "Platform Engineer",
                    "companyName": "Example Limited",
                    "classifications": [
                        {
                            "classification": {
                                "id": "6281",
                                "description": "Information Technology",
                            },
                            "subclassification": {
                                "id": "6287",
                                "description": "Developers and Programmers",
                            },
                        },
                        {
                            "classification": {
                                "id": "6092",
                                "description": "Engineering",
                            }
                        },
                    ],
                    "workTypes": ["Full-time", "Permanent"],
                }
            ]
        }
    )["jobs"][0]

    canonical = build_jobsdb_listing_canonical_job(
        parsed,
        source_url="https://hk.jobsdb.com/job/job-4",
    ).to_dict()

    assert {
        "legacy_classification": canonical["source_classification_id"],
        "paths": [
            [node["source_classification_id"] for node in path["nodes"]]
            for path in canonical["source_attribute_evidence"]["classification_paths"]
        ],
        "employment_codes": [
            label["mapped_type_code"]
            for label in canonical["source_attribute_evidence"]["employment_labels"]
        ],
    } == {
        "legacy_classification": "6281",
        "paths": [
            ["jobsdb:6281", "jobsdb:6287"],
            ["jobsdb:6092"],
        ],
        "employment_codes": ["full_time", "permanent"],
    }


def test_offertoday_listing_canonical_payload_transports_complete_source_evidence():
    parsed = parse_offertoday_listing_rows(
        [
            {
                "jobId": "job-5",
                "encryptJobId": "encrypted-job-5",
                "jobName": "Backend Developer",
                "jobFunctions": [
                    {
                        "code": "118000",
                        "name": "Information Technology",
                        "children": [
                            {"code": "118100", "name": "Software Development"},
                            {"code": "118200", "name": "Technical Support"},
                        ],
                    }
                ],
                "jobType": 2,
                "jobTypeDesc": "兼職",
            }
        ]
    )[0]

    canonical = build_offertoday_canonical_job(parsed).to_dict()

    assert {
        "legacy_subclassification": canonical["source_subclassification_id"],
        "paths": [
            [node["source_classification_id"] for node in path["nodes"]]
            for path in canonical["source_attribute_evidence"]["classification_paths"]
        ],
        "employment_codes": [
            label["mapped_type_code"]
            for label in canonical["source_attribute_evidence"]["employment_labels"]
        ],
    } == {
        "legacy_subclassification": "offertoday:118100",
        "paths": [
            ["offertoday:118000", "offertoday:118100"],
            ["offertoday:118000", "offertoday:118200"],
        ],
        "employment_codes": ["part_time"],
    }


def test_ctgoodjobs_canonical_payload_transports_json_ld_employment_evidence():
    parsed = parse_ctgoodjobs_detail_page(
        """
        <html>
          <head>
            <title>Infrastructure Engineer</title>
            <script type="application/ld+json">
              {
                "@context": "https://schema.org",
                "@type": "JobPosting",
                "employmentType": ["FULL_TIME", "TEMPORARY"]
              }
            </script>
          </head>
        </html>
        """,
        source_classification_id="ctgoodjobs:021",
        source_classification_name="Information Technology",
        source_classification_slug="information-technology",
        url="https://jobs.ctgoodjobs.hk/job/ct-job-6",
    )

    canonical = build_ctgoodjobs_canonical_job(parsed).to_dict()

    assert {
        "legacy_employment": canonical["employment_type"],
        "legacy_subclassification": canonical["source_subclassification_id"],
        "paths": [
            [node["source_classification_id"] for node in path["nodes"]]
            for path in canonical["source_attribute_evidence"]["classification_paths"]
        ],
        "employment_codes": [
            label["mapped_type_code"]
            for label in canonical["source_attribute_evidence"]["employment_labels"]
        ],
    } == {
        "legacy_employment": "Full-time, Temporary",
        "legacy_subclassification": None,
        "paths": [["ctgoodjobs:021"]],
        "employment_codes": ["full_time", "temporary"],
    }


def test_jobsdb_detail_canonical_payload_transports_scalar_detail_evidence():
    parsed = parse_detail_redux_data(
        {
            "jobdetails": {
                "result": {
                    "job": {
                        "title": "Security Engineer",
                        "tracking": {
                            "classificationInfo": {
                                "classificationId": "6281",
                                "classification": "Information Technology",
                                "subClassificationId": "6289",
                                "subClassification": "Security",
                            }
                        },
                        "workTypes": {"label": "Contract"},
                    }
                }
            }
        },
        "job-7",
    )

    canonical = build_jobsdb_canonical_job(
        parsed,
        source_url="https://hk.jobsdb.com/job/job-7",
    ).to_dict()

    assert {
        "paths": [
            [node["source_classification_id"] for node in path["nodes"]]
            for path in canonical["source_attribute_evidence"]["classification_paths"]
        ],
        "employment": [
            label["mapped_type_code"]
            for label in canonical["source_attribute_evidence"]["employment_labels"]
        ],
    } == {
        "paths": [["jobsdb:6281", "jobsdb:6289"]],
        "employment": ["contract"],
    }


def test_offertoday_detail_canonical_payload_keeps_code_labels_and_work_evidence():
    parsed = parse_offertoday_detail_response(
        {
            "data": {
                "jobId": "job-8",
                "encryptJobId": "encrypted-job-8",
                "jobName": "Software Intern",
                "employType": {"name": "實習"},
                "addressVO": {},
                "jobFunctions": [
                    {
                        "code": "118000",
                        "name": "Information Technology",
                        "children": [
                            {"code": "118100", "name": "Software Development"}
                        ],
                    }
                ],
                "jobType": 3,
                "jobTypeDesc": "實習",
                "workingModels": "On-site",
                "workingDays": "Five days",
            }
        }
    )

    canonical = build_offertoday_canonical_job(parsed).to_dict()
    evidence = canonical["source_attribute_evidence"]

    assert {
        "employment": [
            (
                label["raw_code"],
                label["raw_label"],
                label["mapped_type_code"],
            )
            for label in evidence["employment_labels"]
        ],
        "work_arrangements": evidence["work_arrangements"],
        "working_day_labels": evidence["working_day_labels"],
    } == {
        "employment": [
            ("3", "實習", "internship"),
            (None, "實習", "internship"),
        ],
        "work_arrangements": ["On-site"],
        "working_day_labels": ["Five days"],
    }


def test_jobsdb_exact_labels_map_only_the_seven_governed_employment_types():
    provenance = Provenance(
        method="jobsdb-listing-payload",
        source_site="jobsdb",
        evidence_refs=({"kind": "listing-payload", "source_job_id": "job-9"},),
        captured_at=datetime(2026, 7, 18, 13, 0, tzinfo=timezone.utc),
    )

    evidence = JobsDBSourceEvidenceAdapter().extract(
        {
            "workTypes": [
                "Full-time",
                "Part-time",
                "Permanent",
                "Contract",
                "Temporary",
                "Internship",
                "Freelance",
                "Other",
                "N, A",
                "Hybrid",
            ]
        },
        provenance=provenance,
    )

    assert [
        (label.raw_label, label.mapped_type_code)
        for label in evidence.employment_labels
    ] == [
        ("Full-time", "full_time"),
        ("Part-time", "part_time"),
        ("Permanent", "permanent"),
        ("Contract", "contract"),
        ("Temporary", "temporary"),
        ("Internship", "internship"),
        ("Freelance", "freelance"),
        ("Other", None),
        ("N, A", None),
        ("Hybrid", None),
    ]


def test_adapters_preserve_malformed_employment_items_as_bounded_raw_evidence():
    provenance = Provenance(
        method="malformed-fixture",
        source_site=None,
        evidence_refs=({"kind": "fixture", "id": "malformed-employment"},),
        captured_at=datetime(2026, 7, 18, 13, 30, tzinfo=timezone.utc),
    )

    jobsdb = JobsDBSourceEvidenceAdapter().extract(
        {"workTypes": [None, "", {"unexpected": "value"}]},
        provenance=provenance,
    )
    ctgoodjobs = CTGoodJobsSourceEvidenceAdapter().extract(
        {
            "jobContent": {
                "workTypes": [
                    None,
                    {},
                    {"code": [], "name": ""},
                ]
            }
        },
        provenance=provenance,
    )
    offertoday = OfferTodaySourceEvidenceAdapter().extract(
        {
            "jobType": {},
            "jobTypeDesc": [],
            "employType": [],
        },
        provenance=provenance,
    )

    assert {
        "jobsdb": [
            (label.raw_code, label.raw_label, label.normalized_lookup_key)
            for label in jobsdb.employment_labels
        ],
        "ctgoodjobs": [
            (label.raw_code, label.raw_label, label.normalized_lookup_key)
            for label in ctgoodjobs.employment_labels
        ],
        "offertoday": [
            (label.raw_code, label.raw_label, label.normalized_lookup_key)
            for label in offertoday.employment_labels
        ],
    } == {
        "jobsdb": [
            (None, "<malformed:null>", None),
            (None, "<malformed:empty-string>", None),
            (None, "<malformed:object>", None),
        ],
        "ctgoodjobs": [
            (None, "<malformed:null>", None),
            (None, "<malformed:empty-object>", None),
            (
                "<malformed:array>",
                "<malformed:empty-string>",
                None,
            ),
        ],
        "offertoday": [
            ("<malformed:object>", "<malformed:array>", None),
            (None, "<malformed:array>", None),
        ],
    }


def test_offertoday_job_write_payload_does_not_dual_write_legacy_attributes():
    parsed = parse_offertoday_listing_rows(
        [
            {
                "jobId": "job-10",
                "encryptJobId": "encrypted-job-10",
                "jobName": "No Dual Write Engineer",
                "companyName": "No Dual Write Limited",
                "jobFunctions": [
                    {
                        "code": "118000",
                        "name": "Information Technology",
                    }
                ],
                "jobType": 1,
                "jobTypeDesc": "全職",
            }
        ]
    )[0]
    canonical = build_offertoday_canonical_job(parsed)

    job_data = build_offertoday_job_data(canonical, "company-10")

    assert {
        "employment_type",
        "source_classification_id",
        "source_classification_name",
        "source_subclassification_id",
        "source_subclassification_name",
    }.isdisjoint(job_data)
