from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from app.job_intelligence.current_taxonomies.company_mapping_manifest import (
    CompanyIndustryMappingManifestError,
    CompanyIndustryMappingSynchronizer,
    load_company_industry_mapping_manifest,
)
from app.models.current_taxonomy import (
    CurrentSourceTaxonomyMapping,
    CurrentTaxonomyNodeRecord,
)


def _write_manifest(tmp_path: Path, sources: list[dict[str, object]]) -> Path:
    path = tmp_path / "company-industry-source-mappings.json"
    path.write_text(
        json.dumps(
            {"taxonomy": "company_industry", "sources": sources},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def _mapped_entry(label: str, code: str = "611000") -> dict[str, object]:
    return {
        "source_label": label,
        "source_key": f"label:{label.casefold()}",
        "disposition": "mapped",
        "target_codes": [code],
    }


def _non_mapping_entry(label: str) -> dict[str, object]:
    return {
        "source_label": label,
        "source_key": f"label:{label.casefold()}",
        "disposition": "non_mapping",
        "reason": "Source label is broader than an assignable HSIC subclass.",
    }


@pytest.fixture
def mapping_db() -> Session:
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    CurrentTaxonomyNodeRecord.__table__.create(engine)
    CurrentSourceTaxonomyMapping.__table__.create(engine)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    try:
        session.add_all(
            [
                CurrentTaxonomyNodeRecord(
                    taxonomy="company_industry",
                    code="611000",
                    parent_code=None,
                    level="subclass",
                    labels={"en": "Telecommunications network operation"},
                    sort_order=1,
                    is_assignable=True,
                    is_active=True,
                ),
                CurrentTaxonomyNodeRecord(
                    taxonomy="company_industry",
                    code="61",
                    parent_code=None,
                    level="division",
                    labels={"en": "Telecommunications"},
                    sort_order=2,
                    is_assignable=False,
                    is_active=True,
                ),
                CurrentTaxonomyNodeRecord(
                    taxonomy="company_industry",
                    code="inactive",
                    parent_code=None,
                    level="subclass",
                    labels={"en": "Inactive"},
                    sort_order=3,
                    is_assignable=True,
                    is_active=False,
                ),
            ]
        )
        session.commit()
        yield session
    finally:
        session.close()
        engine.dispose()


def test_manifest_normalizes_unicode_and_requires_exact_source_key(tmp_path: Path):
    path = _write_manifest(
        tmp_path,
        [
            {
                "source_site": "OfferToday",
                "entries": [
                    {
                        "source_label": "  電訊  ",
                        "source_key": "label:電訊",
                        "disposition": "non_mapping",
                        "reason": "Broad source label.",
                    }
                ],
            }
        ],
    )

    manifest = load_company_industry_mapping_manifest(path)

    assert manifest.sources[0].source_site == "offertoday"
    assert manifest.sources[0].entries[0].source_label == "電訊"
    assert manifest.sources[0].entries[0].source_key == "label:電訊"


def test_committed_offertoday_manifest_dispositions_current_observed_labels():
    path = Path(__file__).parents[1] / "app" / "data" / "company_industry_source_mappings.json"

    manifest = load_company_industry_mapping_manifest(path)
    source = manifest.source("offertoday")

    assert source is not None
    assert len(source.entries) == 54
    assert all(entry.disposition == "non_mapping" for entry in source.entries)
    assert {entry.source_label for entry in source.entries} >= {
        "IT資訊科技/電子商務",
        "其他",
        "保險",
        "製造業",
        "電訊",
    }


@pytest.mark.parametrize(
    ("entry", "message"),
    [
        (_mapped_entry("電訊") | {"reason": "not allowed"}, "mapped.*reason"),
        (_mapped_entry("電訊") | {"target_codes": []}, "target"),
        (_non_mapping_entry("電訊") | {"target_codes": ["611000"]}, "non_mapping.*target"),
        (_non_mapping_entry("電訊") | {"reason": ""}, "reason"),
        (_non_mapping_entry("電訊") | {"source_key": "label:wrong"}, "source_key"),
    ],
)
def test_manifest_rejects_contradictory_or_malformed_entries(
    tmp_path: Path,
    entry: dict[str, object],
    message: str,
):
    path = _write_manifest(
        tmp_path,
        [{"source_site": "offertoday", "entries": [entry]}],
    )

    with pytest.raises(CompanyIndustryMappingManifestError, match=message):
        load_company_industry_mapping_manifest(path)


def test_manifest_rejects_duplicate_normalized_labels(tmp_path: Path):
    duplicate = _non_mapping_entry(" 電訊 ")
    duplicate["source_key"] = "label:電訊"
    path = _write_manifest(
        tmp_path,
        [
            {
                "source_site": "offertoday",
                "entries": [_non_mapping_entry("電訊"), duplicate],
            }
        ],
    )

    with pytest.raises(CompanyIndustryMappingManifestError, match="duplicate"):
        load_company_industry_mapping_manifest(path)


@pytest.mark.parametrize("target_code", ["missing", "inactive", "61"])
def test_synchronizer_rejects_unknown_inactive_or_non_assignable_targets(
    tmp_path: Path,
    mapping_db: Session,
    target_code: str,
):
    manifest = load_company_industry_mapping_manifest(
        _write_manifest(
            tmp_path,
            [
                {
                    "source_site": "offertoday",
                    "entries": [_mapped_entry("電訊", target_code)],
                }
            ],
        )
    )

    with pytest.raises(CompanyIndustryMappingManifestError, match=target_code):
        CompanyIndustryMappingSynchronizer(mapping_db).plan(
            manifest,
            observed_labels={"offertoday": ("電訊",)},
        )


def test_synchronizer_rejects_incomplete_observed_label_coverage(
    tmp_path: Path,
    mapping_db: Session,
):
    manifest = load_company_industry_mapping_manifest(
        _write_manifest(
            tmp_path,
            [
                {
                    "source_site": "offertoday",
                    "entries": [_non_mapping_entry("其他")],
                }
            ],
        )
    )

    with pytest.raises(CompanyIndustryMappingManifestError, match="電訊"):
        CompanyIndustryMappingSynchronizer(mapping_db).plan(
            manifest,
            observed_labels={"offertoday": ("其他", "電訊")},
        )


def test_synchronizer_is_idempotent_and_removes_stale_positive_rows(
    tmp_path: Path,
    mapping_db: Session,
):
    mapping_db.add(
        CurrentSourceTaxonomyMapping(
            taxonomy="company_industry",
            source_site="offertoday",
            source_key="label:stale",
            source_label="Stale",
            target_code="611000",
            role="deterministic",
            evidence={"managed_by": "old"},
        )
    )
    mapping_db.commit()
    manifest = load_company_industry_mapping_manifest(
        _write_manifest(
            tmp_path,
            [
                {
                    "source_site": "offertoday",
                    "entries": [
                        _mapped_entry("電訊"),
                        _non_mapping_entry("其他"),
                    ],
                }
            ],
        )
    )
    synchronizer = CompanyIndustryMappingSynchronizer(mapping_db)

    first = synchronizer.synchronize(
        manifest,
        observed_labels={"offertoday": ("電訊", "其他")},
    )
    mapping_db.commit()
    second = synchronizer.synchronize(
        manifest,
        observed_labels={"offertoday": ("其他", "電訊")},
    )

    assert first.sources[0].to_payload() == {
        "source_site": "offertoday",
        "created": 1,
        "updated": 0,
        "removed": 1,
        "unchanged": 0,
        "mapped_dispositions": 1,
        "non_mapping_dispositions": 1,
    }
    assert second.sources[0].to_payload() == {
        "source_site": "offertoday",
        "created": 0,
        "updated": 0,
        "removed": 0,
        "unchanged": 1,
        "mapped_dispositions": 1,
        "non_mapping_dispositions": 1,
    }
    assert [
        (row.source_key, row.target_code)
        for row in mapping_db.scalars(
            select(CurrentSourceTaxonomyMapping).order_by(
                CurrentSourceTaxonomyMapping.source_key,
                CurrentSourceTaxonomyMapping.target_code,
            )
        )
    ] == [("label:電訊", "611000")]


def test_full_validation_happens_before_any_source_mutation(
    tmp_path: Path,
    mapping_db: Session,
):
    mapping_db.add(
        CurrentSourceTaxonomyMapping(
            taxonomy="company_industry",
            source_site="offertoday",
            source_key="label:old",
            source_label="Old",
            target_code="611000",
            role="deterministic",
            evidence={},
        )
    )
    mapping_db.commit()
    manifest = load_company_industry_mapping_manifest(
        _write_manifest(
            tmp_path,
            [
                {
                    "source_site": "offertoday",
                    "entries": [_mapped_entry("電訊")],
                },
                {
                    "source_site": "ctgoodjobs",
                    "entries": [_mapped_entry("Unknown", "missing")],
                },
            ],
        )
    )

    with pytest.raises(CompanyIndustryMappingManifestError, match="missing"):
        CompanyIndustryMappingSynchronizer(mapping_db).synchronize(
            manifest,
            observed_labels={
                "offertoday": ("電訊",),
                "ctgoodjobs": ("Unknown",),
            },
        )

    assert mapping_db.get(
        CurrentSourceTaxonomyMapping,
        ("company_industry", "offertoday", "label:old", "611000"),
    ) is not None


def test_source_synchronization_failure_rolls_back_that_source(
    tmp_path: Path,
    mapping_db: Session,
    monkeypatch: pytest.MonkeyPatch,
):
    mapping_db.add(
        CurrentSourceTaxonomyMapping(
            taxonomy="company_industry",
            source_site="offertoday",
            source_key="label:old",
            source_label="Old",
            target_code="611000",
            role="deterministic",
            evidence={},
        )
    )
    mapping_db.commit()
    manifest = load_company_industry_mapping_manifest(
        _write_manifest(
            tmp_path,
            [
                {
                    "source_site": "offertoday",
                    "entries": [_non_mapping_entry("其他")],
                }
            ],
        )
    )
    synchronizer = CompanyIndustryMappingSynchronizer(mapping_db)

    def _fail_after_mutation(_source_plan):
        stale = mapping_db.get(
            CurrentSourceTaxonomyMapping,
            ("company_industry", "offertoday", "label:old", "611000"),
        )
        mapping_db.delete(stale)
        mapping_db.flush()
        raise RuntimeError("simulated database failure")

    monkeypatch.setattr(synchronizer, "_apply_source", _fail_after_mutation)

    with pytest.raises(RuntimeError, match="simulated database failure"):
        synchronizer.synchronize(
            manifest,
            observed_labels={"offertoday": ("其他",)},
        )

    assert mapping_db.get(
        CurrentSourceTaxonomyMapping,
        ("company_industry", "offertoday", "label:old", "611000"),
    ) is not None
