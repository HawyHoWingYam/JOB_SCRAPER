# OfferToday `jobId`-Only Identity Compatibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Accept OfferToday HK listing/detail payloads that expose only `jobId`, while preserving strict identity validation, raw upstream evidence, route-ID provenance, and every existing Plan 2 live/no-write gate.

**Architecture:** One resolver in `detail_identity.py` owns canonical `jobId`, resolved detail-route ID, and the exact source (`encryptJobId` or `jobId_fallback`). Listing, staging, historical target selection, detail parsing, repair, baseline aggregation, smoke artifacts, and offline replay consume that same typed result; explicit evidence promotes fallback authority, while conflicting explicit mappings and reverse collisions remain hard failures. No schema migration or historical payload rewrite is allowed.

**Tech Stack:** Python 3.11, dataclasses and `Literal`, FastAPI application modules, SQLAlchemy 2.0 repositories, pytest/pytest-asyncio, canonical JSON/SHA-256 research artifacts, Ruff.

---

## Execution Boundary

- This plan authorizes deterministic code, test, documentation, compilation, lint, and offline artifact verification only.
- Do not make an OfferToday HTTP request while executing Tasks 1-7.
- Keep `backend/runtime/offertoday-research/fab9d8e1-4c12-4170-a539-c0a6cdbbca93` byte-for-byte unchanged. It remains the immutable failed Task 8 artifact with manifest SHA-256 `1928423eed6cfd95e4cd2a3af3eb1d62c2ea6d460b122acb0ca0fefcfb4b548b`.
- Keep `backend/runtime/offertoday-research/63b9d32a-5d47-44c9-8904-25a68ee2dee8` byte-for-byte unchanged. It remains the immutable identity-corrected but target-count-incomplete Task 8 artifact with manifest SHA-256 `a009be467c30b538e31be501cc3bbb38a528b56c2fe7268507df572dda7336d3`; it does not satisfy Task 8 and triggered the separate two-page amendment.
- Do not capture replacement-smoke baselines, run a replacement smoke, or start Plan 2 Tasks 9-15 until the deterministic implementation has passed review and the user separately authorizes exactly one replacement Task 8 smoke.
- Do not modify `backend/alembic/`, `backend/app/models/`, Compose files, or environment files.
- Keep auth expiry, WAF/IP block, transport, pacing, retry, batch-stop, and terminal code `2520` behavior unchanged; identity fallback must not reclassify those outcomes.
- The worktree is already dirty. In particular, preserve unrelated hunks in `backend/app/scraper/offertoday_browser_runtime.py`, `backend/scripts/offertoday_standalone_crawl.py`, and `backend/tests/test_offertoday_browser_runtime.py`.
- Historical pre-amendment evidence: the first failed smoke returned 10 rows even though the locked request asked for page size 50, while the then-current Task 8 acceptance gate required at least 20 distinct targets from one listing request. This identity correction did not silently weaken that separately approved gate. The later identity-corrected run `63b9d32a-5d47-44c9-8904-25a68ee2dee8` again returned 10 usable targets, stopped with `insufficient_valid_detail_targets`, and made zero detail requests; that target-count-incomplete evidence triggered the separately approved two-page amendment. This bullet records the superseded contract and does not reinstate it.

## File Map

### Shared identity and canonical parsing

- Create `backend/tests/fixtures/offertoday/jobid_only_search_page.json`: sanitized real-schema search response based on failed Task 8 evidence.
- Create `backend/tests/fixtures/offertoday/jobid_only_browse_page.json`: sanitized real-schema browse response based on crawl `5d1a13f3-fbc6-48f6-b7f4-6740962cfb80`.
- Modify `backend/app/sources/offertoday/detail_identity.py`: define provenance types, structured identity errors, row resolution, authority selection, and response validation.
- Modify `backend/app/scraper/offertoday_browser_runtime.py`: make the existing bounded smoke helper consume the shared resolver without touching headed-display behavior.
- Modify `backend/app/sources/offertoday/parsers.py`: normalize valid listing/detail rows through the shared resolver without mutating `raw_data`.
- Modify `backend/app/sources/contracts.py`: build canonical OfferToday URLs and persisted normalized evidence from the resolved identity.
- Modify `backend/tests/test_offertoday_canonical_and_identity.py`: cover fallback, explicit evidence, malformed aliases, response ownership, canonical URLs, and offline repair.
- Modify `backend/tests/test_offertoday_browser_runtime.py`: replace the stale two-raw-ID smoke-helper expectations while preserving unrelated headed-display hunks.

### Listing execution and evidence

- Modify `backend/app/sources/offertoday/listing_runner.py`: accept `jobId`-only rows, keep raw-missing counts, add fallback counts/source fields, and make mapping authority provenance-aware.
- Modify `backend/tests/test_offertoday_listing_runner.py`: run both saved schemas and retain explicit forward/reverse conflict coverage.
- Modify `backend/tests/test_offertoday_standalone_crawl.py`: verify the production staging adapter writes resolved route/source while preserving raw evidence.

### Research smoke and strict offline replay

- Modify `backend/app/sources/offertoday/research/live_contracts.py`: carry provenance in frozen targets and hashed target payloads.
- Modify `backend/app/sources/offertoday/research/smoke.py`: freeze first-seen accepted triples instead of unproven two-ID pairs.
- Modify `backend/app/services/offertoday_research_live_service.py`: pass and record provenance through the no-write detail loop.
- Modify `backend/app/services/offertoday_research_observation_service.py`: persist the aggregate fallback counter in durable smoke metrics.
- Modify `backend/app/sources/offertoday/research/stage_gate.py`: verify fallback counts, baseline identity counters, target provenance, frozen order, and strict replay without constructing live dependencies.
- Modify `backend/scripts/offertoday_research_census.py`: include new fallback counters in summaries while using the current replacement-smoke `listing=2/detail=20` budget; retain legacy `listing=1/detail=20` only for strict offline replay of failed artifacts.
- Modify `backend/tests/test_offertoday_research_smoke.py`, `backend/tests/test_offertoday_research_live_service.py`, `backend/tests/test_offertoday_research_stage_gate.py`, and `backend/tests/test_offertoday_research_census_cli.py`: cover provenance serialization and offline replay.

### Production staging, targeting, and detail/repair propagation

- Modify `backend/scripts/offertoday_standalone_crawl.py`: permit a resolved fallback route in staging payloads and record the source; do not touch the unrelated progress hunks near `main()`.
- Modify `backend/app/repositories/crawl_job_repository.py`: read durable OfferToday listing-identity observations from existing crawl-job events without changing event storage.
- Modify `backend/app/services/crawl_job_runtime.py`: resolve historical rows, promote exactly one explicit mapping over fallback rows, and retain hard forward/reverse conflict behavior.
- Modify `backend/app/services/offertoday_detail_pipeline.py`: preserve source through targets, attempts, canonical payloads, and persistence without fabricating raw `encryptJobId`.
- Modify `backend/app/scraper/offertoday_browser_detail_scraper.py`: construct typed request identities with provenance and preserve it in typed results.
- Modify `backend/app/services/offertoday_job_repair_service.py`: preserve provenance through live and offline repair ownership checks.
- Modify `backend/scripts/repair_offertoday_jobs.py`: pass the resolved identity source to the browser detail scraper.
- Modify `backend/tests/test_crawl_job_runtime.py`, `backend/tests/test_offertoday_detail_pipeline.py`, and the repair sections of `backend/tests/test_offertoday_canonical_and_identity.py` and `backend/tests/test_offertoday_browser_runtime.py`.

### Baseline, conservation, and Plan 2 documentation

- Modify `backend/app/sources/offertoday/research/contracts.py`: add observed, fallback, and unusable identity snapshot fields.
- Modify `backend/app/repositories/offertoday_research_repository.py`: project observed evidence separately from resolved identity/source.
- Modify `backend/app/sources/offertoday/research/baseline.py`: aggregate observation and usability independently and hash the new schema deterministically.
- Modify `backend/app/sources/offertoday/research/conservation.py`: validate persisted response identity provenance without changing conservation equations.
- Modify `backend/tests/test_offertoday_research_baseline.py` and `backend/tests/test_offertoday_research_conservation.py`.
- Modify `backend/tests/fixtures/offertoday_research/duplicate_cross_run/snapshot.json`: add attempt/persisted route provenance and the corresponding three-field response hash.
- Modify `docs/superpowers/specs/2026-07-10-offertoday-broad-it-coverage-reliability-research-design.md`, `docs/superpowers/specs/2026-07-11-offertoday-plan2-live-census-calibration-design.md`, `docs/superpowers/plans/2026-07-11-offertoday-plan2-live-census-calibration.md`, and `docs/superpowers/specs/2026-07-11-offertoday-jobid-only-identity-compatibility-design.md` to supersede the two-required-raw-ID assumption and insert the replacement-smoke gate.

## Dirty-Worktree Guard

Before Task 1, record the existing overlapping diffs:

```powershell
git diff -- backend/app/scraper/offertoday_browser_runtime.py
git diff -- backend/scripts/offertoday_standalone_crawl.py
git diff -- backend/tests/test_offertoday_browser_runtime.py
git status --short --branch
```

Expected: the runtime/test diffs contain the unrelated headed-display behavior, while the standalone diff contains unrelated progress fields near `main()`. Preserve those exact hunks throughout. For commits that touch the two dirty files, use `git add -p` and inspect `git diff --cached`; never stage their unrelated hunks.

---

### Task 1: Define the Shared Provenance-Aware Identity Contract

**Files:**
- Create: `backend/tests/fixtures/offertoday/jobid_only_search_page.json`
- Create: `backend/tests/fixtures/offertoday/jobid_only_browse_page.json`
- Modify: `backend/app/sources/offertoday/detail_identity.py`
- Modify: `backend/app/scraper/offertoday_browser_runtime.py`
- Test: `backend/tests/test_offertoday_canonical_and_identity.py`
- Test: `backend/tests/test_offertoday_browser_runtime.py`

- [ ] **Step 1: Add the two sanitized real-schema fixtures**

Create the fixture directory before adding either file:

```powershell
New-Item -ItemType Directory -Force backend/tests/fixtures/offertoday | Out-Null
```

Create `backend/tests/fixtures/offertoday/jobid_only_search_page.json` with this exact JSON:

```json
{
  "code": 0,
  "msg": "Success",
  "data": {
    "pageSize": 10,
    "total": 265,
    "hasMore": true,
    "resultList": [
      {
        "jobId": "RbeDGc1VoBZwKIInWPjDCA==",
        "jobName": "Product Analyst",
        "companyName": "Example Technology Limited",
        "jobFunctions": [
          {
            "code": "118000",
            "name": "Information Technology",
            "children": [
              {"code": "118002", "name": "Business/System Analyst", "children": []}
            ]
          }
        ]
      }
    ]
  }
}
```

Create `backend/tests/fixtures/offertoday/jobid_only_browse_page.json` with this exact JSON:

```json
{
  "code": 0,
  "msg": "Success",
  "data": {
    "pageSize": 10,
    "total": 431,
    "hasMore": true,
    "resultList": [
      {
        "jobId": "lxwa-xaLLtVD4diDhVRUjw==",
        "jobName": "Junior Programmer",
        "companyName": "Example Digital Limited",
        "jobFunctions": [
          {
            "code": "118000",
            "name": "Information Technology",
            "children": [
              {"code": "118006", "name": "Software Development", "children": []}
            ]
          }
        ]
      }
    ]
  }
}
```

These fixtures deliberately contain no `encryptJobId`. They contain no cookie, CSRF token, recruiter identity, company identifier, URL, or request header.

- [ ] **Step 2: Write failing resolver tests**

Add these imports and tests to `backend/tests/test_offertoday_canonical_and_identity.py`:

```python
from copy import deepcopy
import json
from pathlib import Path


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "offertoday"


def _fixture_row(name: str) -> dict:
    payload = json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))
    return payload["data"]["resultList"][0]


@pytest.mark.parametrize(
    ("fixture_name", "expected_job_id"),
    [
        ("jobid_only_search_page.json", "RbeDGc1VoBZwKIInWPjDCA=="),
        ("jobid_only_browse_page.json", "lxwa-xaLLtVD4diDhVRUjw=="),
    ],
)
def test_real_jobid_only_listing_identity_resolves_fallback_without_raw_mutation(
    fixture_name: str,
    expected_job_id: str,
) -> None:
    identity_module = _identity_module()
    raw = _fixture_row(fixture_name)
    before = deepcopy(raw)

    identity = identity_module.resolve_offertoday_listing_identity(raw)

    assert identity.job_id == expected_job_id
    assert identity.encrypted_job_id == expected_job_id
    assert identity.encrypted_job_id_source == "jobId_fallback"
    assert raw == before
    assert "encryptJobId" not in raw


def test_resolve_detail_identity_uses_jobid_fallback_from_listing_evidence() -> None:
    identity_module = _identity_module()
    listing_payload = _parsed_listing(_sample_listing_raw_missing_encrypted())

    identity = identity_module.resolve_offertoday_detail_identity(
        source_job_id="jid-1",
        listing_payload=listing_payload,
    )

    assert identity.job_id == "jid-1"
    assert identity.encrypted_job_id == "jid-1"
    assert identity.encrypted_job_id_source == "jobId_fallback"


def test_explicit_encrypted_identity_remains_distinct_and_preferred() -> None:
    identity_module = _identity_module()

    identity = identity_module.resolve_offertoday_listing_identity(
        {"jobId": "jid-1", "encryptJobId": "enc-jid-1"}
    )

    assert identity.job_id == "jid-1"
    assert identity.encrypted_job_id == "enc-jid-1"
    assert identity.encrypted_job_id_source == "encryptJobId"


def test_explicit_encrypted_identity_equal_to_jobid_stays_explicit() -> None:
    identity_module = _identity_module()

    identity = identity_module.resolve_offertoday_listing_identity(
        {"jobId": "same-token", "encryptJobId": "same-token"}
    )

    assert identity.encrypted_job_id == "same-token"
    assert identity.encrypted_job_id_source == "encryptJobId"


@pytest.mark.parametrize("missing_value", [None, "", "   "])
def test_null_or_blank_encrypted_evidence_uses_jobid_fallback(missing_value) -> None:
    identity_module = _identity_module()

    identity = identity_module.resolve_offertoday_listing_identity(
        {"jobId": "jid-1", "encryptJobId": missing_value}
    )

    assert identity.encrypted_job_id == "jid-1"
    assert identity.encrypted_job_id_source == "jobId_fallback"


def test_non_string_explicit_encrypted_evidence_is_a_structured_failure() -> None:
    identity_module = _identity_module()

    with pytest.raises(identity_module.OfferTodayIdentityError) as exc_info:
        identity_module.resolve_offertoday_listing_identity(
            {"jobId": "jid-1", "encryptJobId": ["invalid"]}
        )

    assert exc_info.value.classification == "invalid_encrypted_job_id_evidence"


@pytest.mark.parametrize(
    ("payload", "classification"),
    [
        (
            {
                "job_id": "j-normalized",
                "raw_data": {"jobId": "j-upstream"},
            },
            "job_id_alias_conflict",
        ),
        (
            {
                "jobId": "j-1",
                "encrypted_job_id": "enc-normalized",
                "raw_data": {
                    "jobId": "j-1",
                    "encryptJobId": "enc-upstream",
                },
            },
            "encrypted_job_id_alias_conflict",
        ),
    ],
)
def test_conflicting_identity_aliases_are_structured_failures(
    payload: dict,
    classification: str,
) -> None:
    identity_module = _identity_module()

    with pytest.raises(identity_module.OfferTodayIdentityError) as exc_info:
        identity_module.resolve_offertoday_listing_identity(payload)

    assert exc_info.value.classification == classification


@pytest.mark.parametrize(
    "kwargs",
    [
        {
            "job_id": "jid-1",
            "encrypted_job_id": "other",
            "encrypted_job_id_source": "jobId_fallback",
        },
        {
            "job_id": "jid-1",
            "encrypted_job_id": "jid-1",
            "encrypted_job_id_source": "unknown",
        },
    ],
)
def test_typed_identity_rejects_invalid_source_or_fallback_route(kwargs) -> None:
    identity_module = _identity_module()

    with pytest.raises(identity_module.OfferTodayIdentityError):
        identity_module.OfferTodayDetailIdentity(**kwargs)


def test_legacy_normalized_jobid_alias_does_not_claim_upstream_encrypted_evidence() -> None:
    identity_module = _identity_module()

    identity = identity_module.resolve_offertoday_listing_identity(
        {
            "job_id": "jid-1",
            "encrypted_job_id": "jid-1",
            "raw_data": {"jobId": "jid-1"},
        }
    )

    assert identity.encrypted_job_id_source == "jobId_fallback"


def test_authority_index_promotes_explicit_and_detects_reverse_collision() -> None:
    identity_module = _identity_module()
    fallback = identity_module.OfferTodayDetailIdentity(
        "j-1", "j-1", "jobId_fallback"
    )
    explicit = identity_module.OfferTodayDetailIdentity(
        "j-1", "enc-shared", "encryptJobId"
    )
    reverse = identity_module.OfferTodayDetailIdentity(
        "j-2", "enc-shared", "encryptJobId"
    )

    index = identity_module.build_offertoday_identity_authority_index(
        (fallback, explicit, reverse)
    )

    assert index.authoritative_identity_by_job["j-1"] == explicit
    assert index.fallback_job_ids == ("j-1",)
    assert index.explicit_ids_by_job["j-1"] == ("enc-shared",)
    assert index.route_to_job_ids["enc-shared"] == ("j-1", "j-2")
    assert dict(index.conflict_reason_by_job) == {
        "j-1": "reverse_collision",
        "j-2": "reverse_collision",
    }


def test_authority_index_keeps_multiple_explicit_routes_conflicting() -> None:
    identity_module = _identity_module()
    identities = (
        identity_module.OfferTodayDetailIdentity(
            "j-1", "enc-a", "encryptJobId"
        ),
        identity_module.OfferTodayDetailIdentity(
            "j-1", "enc-b", "encryptJobId"
        ),
    )

    index = identity_module.build_offertoday_identity_authority_index(identities)

    assert "j-1" not in index.authoritative_identity_by_job
    assert dict(index.conflict_reason_by_job) == {
        "j-1": "multiple_explicit_encrypted_ids"
    }


def test_validate_detail_identity_accepts_matching_jobid_without_encrypted_evidence() -> None:
    identity_module = _identity_module()
    identity = identity_module.OfferTodayDetailIdentity(
        "j-1",
        "enc-1",
        "encryptJobId",
    )

    identity_module.validate_offertoday_detail_identity(
        identity,
        {"jobId": "j-1"},
    )


def test_repair_service_resolves_missing_encrypted_listing_identity_as_jobid_fallback() -> None:
    service_module = importlib.import_module(
        "app.services.offertoday_job_repair_service"
    )
    service = service_module.OfferTodayJobRepairService(db=None)

    job_id, route_id = service.resolve_detail_identifiers(
        _job_stub(),
        _listing_stub(
            listing_payload=_parsed_listing(
                _sample_listing_raw_missing_encrypted()
            )
        ),
    )

    assert (job_id, route_id) == ("jid-1", "jid-1")
```

Replace the contradictory existing `test_resolve_detail_identity_requires_encrypted_id_from_listing_evidence()` and `test_offertoday_job_repair_service_rejects_missing_encrypted_listing_identity()` with the two fallback tests above; do not keep both expectations.

In `test_offertoday_browser_runtime.py`, replace `test_run_smoke_test_only_uses_rows_with_two_raw_string_ids()` with `test_run_smoke_test_resolves_explicit_and_jobid_fallback_rows()`. Keep its six-row input and assert the valid detail calls are exactly:

```python
assert detail_calls == [
    ("job-1", "encrypted-1"),
    ("job-2", "job-2"),
    ("job-3", "job-3"),
    ("job-6", "encrypted-6"),
]
assert result["detail_results"] == [
    {"job_id": "job-1", "code": 0},
    {"job_id": "job-2", "code": 0},
    {"job_id": "job-3", "code": 0},
    {"job_id": "job-6", "code": 0},
]
```

Update `test_run_smoke_test_applies_detail_limit_after_identity_validation()` so `detail_limit=1` selects the first valid fallback row and expects `[("missing-encrypted-id", "missing-encrypted-id")]`. The non-string `jobId` and non-string `encryptJobId` rows remain skipped.

- [ ] **Step 3: Run the resolver tests and verify RED**

Run:

```powershell
python -m pytest -q backend/tests/test_offertoday_canonical_and_identity.py -k "real_jobid_only or resolve_detail_identity or validate_detail_identity or repair_service_resolves_missing or explicit_encrypted_identity or encrypted_evidence or alias_conflict or typed_identity or legacy_normalized or authority_index"
python -m pytest -q backend/tests/test_offertoday_browser_runtime.py -k "run_smoke_test_only_uses or run_smoke_test_resolves or applies_detail_limit_after_identity_validation"
```

Expected: FAIL because `resolve_offertoday_listing_identity` and `encrypted_job_id_source` do not exist, typed identities do not validate provenance, the current detail resolver requires `encryptJobId`, and the bounded runtime helper skips fallback rows.

- [ ] **Step 4: Implement the shared row resolver and authority selector**

In `backend/app/sources/offertoday/detail_identity.py`, retain `OfferTodayDetailFetchResult` and replace the identity/error/evidence/resolver section with this contract:

```python
OfferTodayEncryptedJobIdSource = Literal["encryptJobId", "jobId_fallback"]


class OfferTodayIdentityError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        classification: str = "invalid_identity",
    ) -> None:
        super().__init__(message)
        self.classification = classification


@dataclass(frozen=True, slots=True)
class OfferTodayDetailIdentity:
    job_id: str
    encrypted_job_id: str
    encrypted_job_id_source: OfferTodayEncryptedJobIdSource = "encryptJobId"

    def __post_init__(self) -> None:
        if (
            not isinstance(self.job_id, str)
            or not self.job_id.strip()
            or self.job_id != self.job_id.strip()
        ):
            raise OfferTodayIdentityError(
                "OfferToday job_id must be a nonblank string",
                classification="missing_job_id",
            )
        if (
            not isinstance(self.encrypted_job_id, str)
            or not self.encrypted_job_id.strip()
            or self.encrypted_job_id != self.encrypted_job_id.strip()
        ):
            raise OfferTodayIdentityError(
                "OfferToday encrypted_job_id must be a nonblank string",
                classification="missing_encrypted_job_id",
            )
        if self.encrypted_job_id_source not in (
            "encryptJobId",
            "jobId_fallback",
        ):
            raise OfferTodayIdentityError(
                "Invalid encrypted_job_id_source",
                classification="invalid_encrypted_job_id_source",
            )
        if (
            self.encrypted_job_id_source == "jobId_fallback"
            and self.encrypted_job_id != self.job_id
        ):
            raise OfferTodayIdentityError(
                "jobId_fallback route must equal canonical jobId",
                classification="encrypted_job_id_source_conflict",
            )


def _alias_entries(
    payload: Mapping[str, Any],
    *,
    field_names: tuple[str, ...],
    raw_field_name: str,
    include_raw: bool = True,
) -> list[tuple[str, Any]]:
    entries = [(name, payload.get(name)) for name in field_names]
    raw_data = payload.get("raw_data")
    if include_raw and isinstance(raw_data, Mapping):
        entries.append((f"raw_data.{raw_field_name}", raw_data.get(raw_field_name)))
    return entries


def _read_entries(
    entries: list[tuple[str, Any]],
    *,
    evidence_name: str,
    required: bool,
    missing_classification: str,
    invalid_classification: str,
    conflict_classification: str,
) -> str | None:
    valid: list[tuple[str, str]] = []
    for name, value in entries:
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        if not isinstance(value, str):
            raise OfferTodayIdentityError(
                f"OfferToday identity alias {name} must be a nonblank string; got {value!r}",
                classification=invalid_classification,
            )
        valid.append((name, value.strip()))
    if not valid:
        if not required:
            return None
        rendered = ", ".join(f"{name}={value!r}" for name, value in entries)
        raise OfferTodayIdentityError(
            f"Missing nonblank string {evidence_name}; evidence: {rendered}",
            classification=missing_classification,
        )
    values = {value for _name, value in valid}
    if len(values) != 1:
        rendered = ", ".join(f"{name}={value!r}" for name, value in valid)
        raise OfferTodayIdentityError(
            f"Conflicting {evidence_name} identity evidence: {rendered}",
            classification=conflict_classification,
        )
    return valid[0][1]


def read_offertoday_identity_evidence(
    payload: Mapping[str, Any],
    *,
    field_names: tuple[str, ...],
    raw_field_name: str,
    evidence_name: str,
    required: bool = True,
) -> str | None:
    is_job_id = evidence_name == "jobId"
    prefix = "job_id" if is_job_id else "encrypted_job_id"
    return _read_entries(
        _alias_entries(
            payload,
            field_names=field_names,
            raw_field_name=raw_field_name,
        ),
        evidence_name=evidence_name,
        required=required,
        missing_classification=f"missing_{prefix}",
        invalid_classification=f"invalid_{prefix}_evidence",
        conflict_classification=f"{prefix}_alias_conflict",
    )


def _require_nonblank_string(value: Any, *, evidence_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        classification = (
            "invalid_source_job_id"
            if evidence_name == "source_job_id"
            else "missing_job_id"
        )
        raise OfferTodayIdentityError(
            f"Missing nonblank string {evidence_name}; got {value!r}",
            classification=classification,
        )
    return value.strip()


def _read_resolution_source(
    payload: Mapping[str, Any],
) -> OfferTodayEncryptedJobIdSource | None:
    if "encrypted_job_id_source" not in payload:
        return None
    value = payload.get("encrypted_job_id_source")
    if value not in ("encryptJobId", "jobId_fallback"):
        raise OfferTodayIdentityError(
            "encrypted_job_id_source must be 'encryptJobId' or 'jobId_fallback'",
            classification="invalid_encrypted_job_id_source",
        )
    return value


def resolve_offertoday_listing_identity(
    payload: Mapping[str, Any],
    *,
    source_job_id: Any | None = None,
) -> OfferTodayDetailIdentity:
    if not isinstance(payload, Mapping):
        raise OfferTodayIdentityError(
            f"Missing OfferToday identity payload; got {type(payload).__name__}",
            classification="missing_listing_payload",
        )
    job_id = read_offertoday_identity_evidence(
        payload,
        field_names=("job_id", "jobId"),
        raw_field_name="jobId",
        evidence_name="jobId",
    )
    route_id = read_offertoday_identity_evidence(
        payload,
        field_names=("encrypted_job_id", "encryptJobId"),
        raw_field_name="encryptJobId",
        evidence_name="encryptJobId",
        required=False,
    )
    explicit_route_id = _read_entries(
        _alias_entries(
            payload,
            field_names=("encryptJobId",),
            raw_field_name="encryptJobId",
        ),
        evidence_name="encryptJobId",
        required=False,
        missing_classification="missing_encrypted_job_id",
        invalid_classification="invalid_encrypted_job_id_evidence",
        conflict_classification="encrypted_job_id_alias_conflict",
    )
    declared_source = _read_resolution_source(payload)
    if explicit_route_id is not None:
        if declared_source == "jobId_fallback":
            raise OfferTodayIdentityError(
                "Explicit encryptJobId conflicts with jobId_fallback provenance",
                classification="encrypted_job_id_source_conflict",
            )
        source: OfferTodayEncryptedJobIdSource = "encryptJobId"
        resolved_route_id = explicit_route_id
    elif route_id is None:
        if declared_source == "encryptJobId":
            raise OfferTodayIdentityError(
                "encryptJobId provenance has no encrypted identity evidence",
                classification="missing_encrypted_job_id",
            )
        source = "jobId_fallback"
        resolved_route_id = job_id
    elif declared_source == "jobId_fallback" or (
        declared_source is None and route_id == job_id
    ):
        if route_id != job_id:
            raise OfferTodayIdentityError(
                "jobId_fallback route must equal canonical jobId",
                classification="encrypted_job_id_source_conflict",
            )
        source = "jobId_fallback"
        resolved_route_id = job_id
    else:
        source = "encryptJobId"
        resolved_route_id = route_id
    if source_job_id is not None:
        canonical_source_job_id = _require_nonblank_string(
            source_job_id,
            evidence_name="source_job_id",
        )
        if canonical_source_job_id != job_id:
            raise OfferTodayIdentityError(
                "OfferToday detail identity mismatch: "
                f"source_job_id={canonical_source_job_id!r}, listing jobId={job_id!r}",
                classification="source_job_id_mismatch",
            )
    return OfferTodayDetailIdentity(
        job_id=job_id,
        encrypted_job_id=resolved_route_id,
        encrypted_job_id_source=source,
    )


def resolve_offertoday_detail_identity(
    *,
    source_job_id: Any,
    listing_payload: Mapping[str, Any],
) -> OfferTodayDetailIdentity:
    canonical_source_job_id = _require_nonblank_string(
        source_job_id,
        evidence_name="source_job_id",
    )
    return resolve_offertoday_listing_identity(
        listing_payload,
        source_job_id=canonical_source_job_id,
    )


def choose_offertoday_authoritative_identity(
    *,
    job_id: str,
    identities: Sequence[OfferTodayDetailIdentity],
) -> OfferTodayDetailIdentity:
    canonical_job_id = _require_nonblank_string(job_id, evidence_name="jobId")
    normalized = tuple(identities)
    if not normalized or any(item.job_id != canonical_job_id for item in normalized):
        raise OfferTodayIdentityError(
            "Identity authority requires one canonical jobId",
            classification="source_job_id_mismatch",
        )
    explicit_ids = {
        item.encrypted_job_id
        for item in normalized
        if item.encrypted_job_id_source == "encryptJobId"
    }
    if len(explicit_ids) > 1:
        raise OfferTodayIdentityError(
            f"Multiple explicit encryptJobId values for jobId={canonical_job_id!r}",
            classification="one_job_id_to_multiple_encrypted_ids",
        )
    if explicit_ids:
        return OfferTodayDetailIdentity(
            job_id=canonical_job_id,
            encrypted_job_id=next(iter(explicit_ids)),
            encrypted_job_id_source="encryptJobId",
        )
    return OfferTodayDetailIdentity(
        job_id=canonical_job_id,
        encrypted_job_id=canonical_job_id,
        encrypted_job_id_source="jobId_fallback",
    )


@dataclass(frozen=True, slots=True)
class OfferTodayIdentityAuthorityIndex:
    authoritative_identity_by_job: Mapping[str, OfferTodayDetailIdentity]
    explicit_ids_by_job: Mapping[str, tuple[str, ...]]
    route_to_job_ids: Mapping[str, tuple[str, ...]]
    fallback_job_ids: tuple[str, ...]
    conflict_reason_by_job: Mapping[str, str]


def build_offertoday_identity_authority_index(
    identities: Sequence[OfferTodayDetailIdentity],
) -> OfferTodayIdentityAuthorityIndex:
    grouped: dict[str, list[OfferTodayDetailIdentity]] = {}
    fallback_job_ids: list[str] = []
    fallback_seen: set[str] = set()
    explicit_ids_by_job: dict[str, tuple[str, ...]] = {}
    for identity in identities:
        grouped.setdefault(identity.job_id, []).append(identity)
        if (
            identity.encrypted_job_id_source == "jobId_fallback"
            and identity.job_id not in fallback_seen
        ):
            fallback_seen.add(identity.job_id)
            fallback_job_ids.append(identity.job_id)

    authoritative: dict[str, OfferTodayDetailIdentity] = {}
    conflict_reason_by_job: dict[str, str] = {}
    for job_id, values in grouped.items():
        explicit_ids_by_job[job_id] = tuple(
            sorted(
                {
                    value.encrypted_job_id
                    for value in values
                    if value.encrypted_job_id_source == "encryptJobId"
                }
            )
        )
        try:
            authoritative[job_id] = choose_offertoday_authoritative_identity(
                job_id=job_id,
                identities=values,
            )
        except OfferTodayIdentityError as exc:
            if exc.classification != "one_job_id_to_multiple_encrypted_ids":
                raise
            conflict_reason_by_job[job_id] = (
                "multiple_explicit_encrypted_ids"
            )

    route_to_jobs: dict[str, set[str]] = {}
    for job_id, identity in authoritative.items():
        route_to_jobs.setdefault(identity.encrypted_job_id, set()).add(job_id)
    for job_ids in route_to_jobs.values():
        if len(job_ids) > 1:
            for job_id in job_ids:
                conflict_reason_by_job[job_id] = "reverse_collision"

    return OfferTodayIdentityAuthorityIndex(
        authoritative_identity_by_job=MappingProxyType(dict(authoritative)),
        explicit_ids_by_job=MappingProxyType(dict(explicit_ids_by_job)),
        route_to_job_ids=MappingProxyType(
            {
                route_id: tuple(sorted(job_ids))
                for route_id, job_ids in route_to_jobs.items()
            }
        ),
        fallback_job_ids=tuple(fallback_job_ids),
        conflict_reason_by_job=MappingProxyType(
            dict(sorted(conflict_reason_by_job.items()))
        ),
    )
```

At the top of `detail_identity.py`, use `from collections.abc import Mapping, Sequence`, `from types import MappingProxyType`, and retain `Any`, `Literal`, and `overload` from `typing`. The index groups typed identities by canonical job in input order, calls `choose_offertoday_authoritative_identity()` per group, records sorted distinct explicit routes and fallback-observed jobs, then builds the reverse map only from successfully selected authorities. It maps selector classification `one_job_id_to_multiple_encrypted_ids` to public conflict reason `multiple_explicit_encrypted_ids` and marks every job in an authoritative reverse collision with `reverse_collision`. This shared index is consumed by listing replay, historical target loading, repair, and baseline aggregation so promotion/conflict semantics cannot drift.

Keep the existing overloads for `read_offertoday_identity_evidence`, updating their implementation to delegate to the code above, and import `Sequence` from `collections.abc`.

Update direct `OfferTodayDetailIdentity(...)` constructors in touched tests and fakes to pass the source explicitly. Existing distinct-ID fixtures use `encryptJobId`; equal-ID fallback fixtures use `jobId_fallback`. Retain the production default only as compatibility for untouched explicit callers, not as a way for new tests to hide provenance. Keep direct imports from `detail_identity.py`; `backend/app/sources/offertoday/__init__.py` is only a module docstring and should not gain a new re-export façade.

Update `test_resolve_detail_identity_returns_frozen_distinct_identifiers()` so its slots assertion is exactly `("job_id", "encrypted_job_id", "encrypted_job_id_source")`, and retain the frozen-instance mutation assertion.

In `backend/app/scraper/offertoday_browser_runtime.py`, retain the existing `resolve_offertoday_detail_identity` import and additionally import `OfferTodayIdentityError` and `resolve_offertoday_listing_identity`. Replace the direct two-raw-string filter inside `run_smoke_test()` with the shared resolver:

```python
try:
    identity = resolve_offertoday_listing_identity(row)
except OfferTodayIdentityError:
    continue

detail_payload = await self.fetch_detail_json(
    job_id=identity.job_id,
    encrypted_job_id=identity.encrypted_job_id,
)
```

Use `identity.job_id` in the appended detail result. Keep non-dictionary rows and every structured identity error skipped, apply `detail_limit` after identity validation exactly as today, and do not alter headed-display launch behavior.

Replace `validate_offertoday_detail_identity()` so it resolves the response once and compares canonical ownership plus explicit response evidence:

```python
def validate_offertoday_detail_identity(
    identity: OfferTodayDetailIdentity,
    detail_payload: Mapping[str, Any],
) -> None:
    response_identity = resolve_offertoday_listing_identity(detail_payload)
    if response_identity.job_id != identity.job_id:
        raise OfferTodayIdentityError(
            "OfferToday detail response identity mismatch: "
            f"requested jobId={identity.job_id!r}, "
            f"response jobId={response_identity.job_id!r}",
            classification="detail_job_id_mismatch",
        )
    if (
        response_identity.encrypted_job_id_source == "encryptJobId"
        and response_identity.encrypted_job_id != identity.encrypted_job_id
    ):
        raise OfferTodayIdentityError(
            "OfferToday detail response identity mismatch: "
            f"requested encryptJobId={identity.encrypted_job_id!r}, "
            f"response encryptJobId={response_identity.encrypted_job_id!r}",
            classification="detail_encrypted_job_id_mismatch",
        )
```

- [ ] **Step 5: Run the focused resolver tests and verify GREEN**

Run:

```powershell
python -m pytest -q backend/tests/test_offertoday_canonical_and_identity.py -k "real_jobid_only or explicit_encrypted_identity or encrypted_evidence or alias_conflict or typed_identity or legacy_normalized or authority_index or resolve_detail_identity or validate_detail_identity or repair_service_resolves_missing"
python -m pytest -q backend/tests/test_offertoday_browser_runtime.py -k "run_smoke_test_resolves or applies_detail_limit_after_identity_validation"
```

Expected: all selected tests pass; explicit mismatches remain failures, `jobId`-only rows resolve with `jobId_fallback`, and the bounded smoke helper routes absent/blank encrypted IDs through canonical `jobId`.

- [ ] **Step 6: Commit Task 1**

```powershell
git add backend/app/sources/offertoday/detail_identity.py backend/tests/test_offertoday_canonical_and_identity.py
git add -f backend/tests/fixtures/offertoday/jobid_only_search_page.json backend/tests/fixtures/offertoday/jobid_only_browse_page.json
git add -p backend/app/scraper/offertoday_browser_runtime.py
git add -p backend/tests/test_offertoday_browser_runtime.py
git diff --cached -- backend/app/scraper/offertoday_browser_runtime.py backend/tests/test_offertoday_browser_runtime.py
git diff --cached --check
git commit -m "fix(offertoday): resolve jobId-only identities"
```

Expected staged runtime/test diff: shared-resolver imports, `run_smoke_test()` identity selection, and its two focused test updates only; no `Path`, `fail_launch_by_channel`, browser fallback, or headed-display test hunks.

---

### Task 2: Normalize Parser and Canonical Output Without Fabricating Raw Evidence

**Files:**
- Modify: `backend/app/sources/offertoday/parsers.py`
- Modify: `backend/app/sources/contracts.py`
- Test: `backend/tests/test_offertoday_canonical_and_identity.py`

- [ ] **Step 1: Replace strict two-ID parser expectations with failing provenance tests**

Replace the existing missing-encrypted parser tests and add canonical coverage:

```python
def test_listing_parser_resolves_missing_encrypted_id_without_mutating_raw_data():
    raw = _sample_listing_raw_missing_encrypted()
    before = deepcopy(raw)

    listing = _parsed_listing(raw)

    assert listing["job_id"] == "jid-1"
    assert listing["encrypted_job_id"] == "jid-1"
    assert listing["encrypted_job_id_source"] == "jobId_fallback"
    assert listing["raw_data"] == before
    assert "encryptJobId" not in listing["raw_data"]


def test_detail_parser_resolves_missing_encrypted_id_without_mutating_raw_data():
    raw = _sample_detail_raw_missing_encrypted()
    before = deepcopy(raw)

    parsed = parse_offertoday_detail_response({"code": 0, "data": raw})

    assert parsed["job_id"] == "jid-1"
    assert parsed["encrypted_job_id"] == "jid-1"
    assert parsed["encrypted_job_id_source"] == "jobId_fallback"
    assert parsed["raw_data"] == before
    assert "encryptJobId" not in parsed["raw_data"]


def test_canonical_builder_accepts_jobid_only_payload_and_uses_fallback_url():
    raw = _sample_detail_raw_missing_encrypted()
    before = deepcopy(raw)
    parsed = parse_offertoday_detail_response({"code": 0, "data": raw})

    canonical = build_offertoday_canonical_job(parsed)

    assert canonical.source_job_id == "jid-1"
    assert canonical.source_url.endswith("/jid-1")
    assert canonical.raw_data["encrypted_job_id"] == "jid-1"
    assert canonical.raw_data["encrypted_job_id_source"] == "jobId_fallback"
    assert canonical.raw_data["raw_data"] == before
    assert "encryptJobId" not in canonical.raw_data["raw_data"]
```

Remove the `encryptJobId`-missing case from `test_build_offertoday_canonical_job_rejects_missing_identity_field`; keep the missing/invalid `jobId` and conflicting/non-string encrypted cases.

- [ ] **Step 2: Run parser/canonical tests and verify RED**

Run:

```powershell
python -m pytest -q backend/tests/test_offertoday_canonical_and_identity.py -k "parser_resolves_missing or canonical_builder_accepts_jobid_only or canonical_job_rejects"
```

Expected: FAIL because parser values are empty and the canonical builder still requires `encryptJobId`.

- [ ] **Step 3: Route valid parser rows through the resolver**

In `backend/app/sources/offertoday/parsers.py`, import `OfferTodayIdentityError` and `resolve_offertoday_listing_identity`, then add:

```python
def _normalized_identity_fields(raw: Mapping[str, Any]) -> dict[str, Any]:
    try:
        identity = resolve_offertoday_listing_identity(raw)
    except OfferTodayIdentityError:
        raw_job_id = raw.get("jobId")
        raw_encrypted_job_id = raw.get("encryptJobId")
        return {
            "job_id": raw_job_id.strip() if isinstance(raw_job_id, str) else "",
            "encrypted_job_id": (
                raw_encrypted_job_id.strip()
                if isinstance(raw_encrypted_job_id, str)
                else ""
            ),
            "encrypted_job_id_source": None,
        }
    return {
        "job_id": identity.job_id,
        "encrypted_job_id": identity.encrypted_job_id,
        "encrypted_job_id_source": identity.encrypted_job_id_source,
    }
```

At the start of `_parse_listing_job()`, compute `identity_fields = _normalized_identity_fields(raw)` and spread `**identity_fields` into the returned normalized dictionary. Keep `"raw_data": dict(raw)` unchanged and remove the current `str(...).strip()` identity coercions.

In `parse_offertoday_detail_response()`, resolve the `data` object strictly and return its fields:

```python
identity = resolve_offertoday_listing_identity(data)
```

Use:

```python
"job_id": identity.job_id,
"encrypted_job_id": identity.encrypted_job_id,
"encrypted_job_id_source": identity.encrypted_job_id_source,
```

Keep `"raw_data": dict(data)` unchanged.

- [ ] **Step 4: Make the canonical builder consume the same identity**

In `backend/app/sources/contracts.py`, replace the two independent identity reads with:

```python
from app.sources.offertoday.detail_identity import (
    resolve_offertoday_listing_identity,
)

identity = resolve_offertoday_listing_identity(parsed_job)
normalized_job = {
    **dict(parsed_job),
    "job_id": identity.job_id,
    "encrypted_job_id": identity.encrypted_job_id,
    "encrypted_job_id_source": identity.encrypted_job_id_source,
}
```

Build `source_job_id` from `identity.job_id`, `source_url` from `identity.encrypted_job_id`, read all canonical fields from `normalized_job`, and set `raw_data=normalized_job`. Do not insert `encryptJobId` into the nested upstream `raw_data` mapping.

- [ ] **Step 5: Run parser/canonical regressions and verify GREEN**

Run:

```powershell
python -m pytest -q backend/tests/test_offertoday_canonical_and_identity.py
```

Expected: all tests pass; raw listing/detail dictionaries remain equal to their input, explicit two-ID fixtures keep distinct URLs, and job-only fixtures use the canonical token for the route.

- [ ] **Step 6: Commit Task 2**

```powershell
git add backend/app/sources/offertoday/parsers.py backend/app/sources/contracts.py backend/tests/test_offertoday_canonical_and_identity.py
git diff --cached --check
git commit -m "fix(offertoday): normalize fallback identity provenance"
```

---

### Task 3: Make Listing Authority Provenance-Aware

**Files:**
- Modify: `backend/app/sources/offertoday/listing_runner.py`
- Modify: `backend/tests/test_offertoday_listing_runner.py`
- Modify: `backend/tests/test_offertoday_standalone_crawl.py`

- [ ] **Step 1: Write failing search/browse runner regressions**

Add fixture loading to `backend/tests/test_offertoday_listing_runner.py` and the following test:

```python
from pathlib import Path


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "offertoday"


@pytest.mark.parametrize(
    ("fixture_name", "endpoint", "expected_job_id"),
    [
        ("jobid_only_search_page.json", "search", "RbeDGc1VoBZwKIInWPjDCA=="),
        ("jobid_only_browse_page.json", "browse", "lxwa-xaLLtVD4diDhVRUjw=="),
    ],
)
@pytest.mark.asyncio
async def test_real_jobid_only_page_is_accepted_with_observation_and_fallback_counts(
    fixture_name: str,
    endpoint: str,
    expected_job_id: str,
) -> None:
    response = json.loads((FIXTURE_ROOT / fixture_name).read_text(encoding="utf-8"))
    raw_before = deepcopy(response["data"]["resultList"][0])
    condition = OfferTodayListingCondition(
        search_family="runtime_smoke",
        category_id=118000,
        keyword="",
        endpoint=endpoint,
        rcd_type=7,
    )

    result, observations, staging, _sleep = await _run(
        ScriptedTransport(response),
        conditions=[condition],
        max_pages=1,
        require_empty_confirmation=False,
    )

    assert result.stop_reason == "page_cap"
    assert result.identity_issues == ()
    assert result.identity_conflicts == ()
    assert result.accepted_job_ids == (expected_job_id,)
    assert result.id_pairs[0].job_id == expected_job_id
    assert result.id_pairs[0].encrypted_job_id == expected_job_id
    assert result.id_pairs[0].encrypted_job_id_source == "jobId_fallback"
    page = observations.observations[0]
    assert page.missing_encrypted_job_id_count == 1
    assert page.job_id_fallback_count == 1
    assert page.identity_issues == ()
    assert staging.staged_pages[0]["rows"][0]["raw_data"] == raw_before
    assert "encryptJobId" not in staging.staged_pages[0]["rows"][0]["raw_data"]
```

- [ ] **Step 2: Write failing promotion and strict-conflict regressions**

Add:

```python
@pytest.mark.asyncio
async def test_single_explicit_mapping_promotes_prior_fallback_authority() -> None:
    fallback = _listing_row("j-promote", None)
    fallback.pop("encryptJobId")
    transport = ScriptedTransport(
        _listing_response([fallback], has_more=True),
        _listing_response([_listing_row("j-promote", "enc-promoted")], has_more=False),
    )

    result, observations, staging, _sleep = await _run(
        transport,
        max_pages=2,
        require_empty_confirmation=False,
    )

    assert result.identity_conflicts == ()
    assert result.accepted_job_ids == ("j-promote",)
    assert result.id_pairs[0].encrypted_job_id == "enc-promoted"
    assert result.id_pairs[0].encrypted_job_id_source == "encryptJobId"
    assert observations.observations[0].job_id_fallback_count == 1
    assert observations.observations[1].job_id_fallback_count == 0
    assert observations.observations[0].id_pairs == (
        OfferTodayIdentityPair("j-promote", "j-promote", "jobId_fallback"),
    )
    assert observations.observations[1].id_pairs == (
        OfferTodayIdentityPair("j-promote", "enc-promoted", "encryptJobId"),
    )
    assert len(staging.staged_pages) == 2
    assert [
        page["rows"][0]["encrypted_job_id_source"]
        for page in staging.staged_pages
    ] == ["jobId_fallback", "encryptJobId"]


@pytest.mark.asyncio
async def test_two_explicit_mappings_remain_a_forward_conflict() -> None:
    transport = ScriptedTransport(
        _listing_response(
            [
                _listing_row("j-conflict", "enc-first"),
                _listing_row("j-conflict", "enc-second"),
            ],
            has_more=True,
        )
    )

    result, observations, staging, _sleep = await _run(transport, max_pages=1)

    assert result.stop_reason == "identity_conflict"
    assert result.id_pairs == ()
    assert result.identity_conflicts[0].reason == (
        "multiple_explicit_encrypted_ids"
    )
    assert observations.observations[0].job_id_fallback_count == 0
    assert staging.staged_pages == []


@pytest.mark.asyncio
async def test_later_fallback_does_not_downgrade_explicit_authority() -> None:
    later_fallback = _listing_row("j-stable", None)
    later_fallback.pop("encryptJobId")
    transport = ScriptedTransport(
        _listing_response(
            [_listing_row("j-stable", "enc-stable")],
            has_more=True,
        ),
        _listing_response([later_fallback], has_more=False),
    )

    result, observations, _staging, _sleep = await _run(
        transport,
        max_pages=2,
        require_empty_confirmation=False,
    )

    assert observations.observations[0].id_pairs == (
        OfferTodayIdentityPair("j-stable", "enc-stable", "encryptJobId"),
    )
    assert observations.observations[1].rows[0].encrypted_job_id_source == (
        "jobId_fallback"
    )
    assert observations.observations[1].id_pairs == (
        OfferTodayIdentityPair("j-stable", "enc-stable", "encryptJobId"),
    )
    assert result.id_pairs == observations.observations[1].id_pairs


@pytest.mark.parametrize("encrypted_value", [None, "   "])
@pytest.mark.asyncio
async def test_valid_jobid_with_null_or_blank_encrypted_value_uses_fallback(
    encrypted_value,
) -> None:
    transport = ScriptedTransport(
        _listing_response(
            [_listing_row("j-fallback", encrypted_value)],
            has_more=True,
        )
    )

    result, observations, staging, _sleep = await _run(
        transport,
        max_pages=1,
        require_empty_confirmation=False,
    )

    assert result.identity_issues == ()
    assert result.id_pairs == (
        OfferTodayIdentityPair(
            "j-fallback",
            "j-fallback",
            "jobId_fallback",
        ),
    )
    assert observations.observations[0].missing_encrypted_job_id_count == 1
    assert observations.observations[0].job_id_fallback_count == 1
    assert len(staging.staged_pages) == 1
```

Keep the existing reverse-collision test unchanged except for the new source fields.

Update the existing strict runner regressions at the same time:

- remove the valid-`jobId`/missing-or-blank-`encryptJobId` cases from `test_missing_identity_fields_are_observed_and_never_staged()`; the new fallback test owns those cases, while missing/blank canonical `jobId` remains an identity issue;
- replace `test_known_canonical_missing_encrypted_id_is_deferred()` with the no-downgrade regression above;
- change raw non-string issue expectations to `invalid_job_id_evidence` and `invalid_encrypted_job_id_evidence`, including the combined-fields parameterization; and
- change every explicit forward-conflict expectation from `one_job_id_to_multiple_encrypted_ids` to `multiple_explicit_encrypted_ids`. Keep the outward reverse-conflict reason `one_encrypted_id_to_multiple_job_ids` unchanged.

- [ ] **Step 3: Run listing tests and verify RED**

Run:

```powershell
python -m pytest -q backend/tests/test_offertoday_listing_runner.py -k "real_jobid_only or null_or_blank_encrypted or promotes_prior_fallback or later_fallback or explicit_mappings or reverse_identity_conflict"
```

Expected: FAIL because missing encrypted evidence still creates `identity_issue`, the fallback counter/source fields do not exist, and fallback-to-explicit is treated as a forward conflict.

- [ ] **Step 4: Extend listing evidence types**

In `backend/app/sources/offertoday/listing_runner.py`, import `OfferTodayEncryptedJobIdSource`, the shared resolver, authority selector, identity type, and error. Change the identity/evidence dataclasses to:

```python
@dataclass(frozen=True, slots=True)
class OfferTodayIdentityPair:
    job_id: str
    encrypted_job_id: str
    encrypted_job_id_source: OfferTodayEncryptedJobIdSource = "encryptJobId"


@dataclass(frozen=True, slots=True)
class ListingRowEvidence:
    job_id: str | None
    encrypted_job_id: str | None
    encrypted_job_id_source: OfferTodayEncryptedJobIdSource | None
    observed_encrypted_job_id: str | None
    title: str
    job_function_codes: tuple[str, ...]
    title_language: Literal["zh", "en", "mixed", "other"]
    api_language: str
```

Add `job_id_fallback_count: int` immediately after `missing_encrypted_job_id_count` in `ListingPageObservation`. Add `identity: OfferTodayDetailIdentity | None` to `_ListingRowIdentityAnalysis`.

Rewrite `_analyze_listing_row()` so raw absence remains observable but is no longer an issue:

```python
def _analyze_listing_row(parsed_row: dict[str, Any]) -> _ListingRowIdentityAnalysis:
    raw_data = parsed_row.get("raw_data")
    raw_data = raw_data if isinstance(raw_data, Mapping) else {}
    raw_job_id, job_issue_reason = _analyze_raw_identity_value(
        raw_data.get("jobId"),
        missing_reason="missing_job_id",
        invalid_reason="invalid_job_id",
    )
    observed_encrypted_job_id, encrypted_issue_reason = _analyze_raw_identity_value(
        raw_data.get("encryptJobId"),
        missing_reason="missing_encrypted_job_id",
        invalid_reason="invalid_encrypted_job_id",
    )
    identity: OfferTodayDetailIdentity | None = None
    resolver_issue: ListingIdentityIssue | None = None
    try:
        identity = resolve_offertoday_listing_identity(raw_data)
    except OfferTodayIdentityError as exc:
        resolver_issue = ListingIdentityIssue(
            job_id=raw_job_id,
            encrypted_job_id=observed_encrypted_job_id,
            reason=exc.classification,
        )
    title = str(parsed_row.get("title") or "").strip()
    evidence = ListingRowEvidence(
        job_id=identity.job_id if identity is not None else raw_job_id,
        encrypted_job_id=(
            identity.encrypted_job_id if identity is not None else observed_encrypted_job_id
        ),
        encrypted_job_id_source=(
            identity.encrypted_job_id_source if identity is not None else None
        ),
        observed_encrypted_job_id=observed_encrypted_job_id,
        title=title,
        job_function_codes=_job_function_codes(parsed_row.get("job_functions")),
        title_language=_classify_title_language(title),
        api_language="zh_HK",
    )
    return _ListingRowIdentityAnalysis(
        identity=identity,
        evidence=evidence,
        issue=resolver_issue,
        job_id_issue_reason=job_issue_reason,
        encrypted_job_id_issue_reason=encrypted_issue_reason,
    )
```

Thus `missing_encrypted_job_id_count` still counts raw null/blank/absent values, while only invalid/conflicting encrypted evidence produces an issue.

- [ ] **Step 5: Replace mapping authority with explicit-over-fallback merging**

Inside `OfferTodayListingRunner.run()`, replace `job_to_encrypted_id` and `encrypted_id_to_job` with `job_to_identity: dict[str, OfferTodayDetailIdentity]`. Replace `staged_pair_values` with `staged_identity_values: set[tuple[str, str, OfferTodayEncryptedJobIdSource]]`. For each page, clone the authoritative map, retain first-seen page job order, and merge each valid `analysis.identity` using the shared index:

```python
current = candidate_job_to_identity.get(identity.job_id)
authority_inputs = (identity,) if current is None else (current, identity)
authority_index = build_offertoday_identity_authority_index(authority_inputs)
reason = authority_index.conflict_reason_by_job.get(identity.job_id)
if reason is not None:
    add_conflict(
        ListingIdentityConflict(
            job_ids=(identity.job_id,),
            encrypted_job_ids=tuple(
                sorted(
                    {
                        item.encrypted_job_id
                        for item in authority_inputs
                        if item.encrypted_job_id_source == "encryptJobId"
                    }
                )
            ),
            reason=reason,
        )
    )
    continue
candidate_job_to_identity[identity.job_id] = (
    authority_index.authoritative_identity_by_job[identity.job_id]
)
```

Do not append `page_pairs` directly from raw row order before this merge. After all valid rows have been merged, run `build_offertoday_identity_authority_index(tuple(candidate_job_to_identity.values()))` and emit `one_encrypted_id_to_multiple_job_ids` for its `reverse_collision` jobs using the shared route map. A fallback observation must never be added to the explicit-forward set for conflict detection. The listing event retains the legacy outward reverse-conflict reason while the shared index uses `reverse_collision` internally.

Build the page's accepted pairs from the authoritative map in first-seen page job order, excluding any job rejected by a page issue or conflict:

```python
page_pairs = [
    OfferTodayIdentityPair(
        job_id=identity.job_id,
        encrypted_job_id=identity.encrypted_job_id,
        encrypted_job_id_source=identity.encrypted_job_id_source,
    )
    for job_id in page_ordered_job_ids
    if job_id not in page_rejected_job_ids
    and (identity := candidate_job_to_identity.get(job_id)) is not None
]
```

This means a page containing fallback plus one explicit observation for the same job serializes only the explicit authority, and a later fallback observation cannot downgrade an already explicit page pair. Per-row `rows` evidence still records each row's observed resolution source.

Construct page and final pairs with all three fields:

```python
OfferTodayIdentityPair(
    job_id=identity.job_id,
    encrypted_job_id=identity.encrypted_job_id,
    encrypted_job_id_source=identity.encrypted_job_id_source,
)
```

Set the page counter with:

```python
job_id_fallback_count=sum(
    analysis.identity is not None
    and analysis.identity.encrypted_job_id_source == "jobId_fallback"
    for analysis in row_analyses
),
```

Set `job_id_fallback_count=0` in `_empty_observation()`. Replace the local two-field staging collections with the exact triple types before iterating the rows:

```python
stage_identity_values: list[
    tuple[str, str, OfferTodayEncryptedJobIdSource]
] = []
page_stage_identity_values: set[
    tuple[str, str, OfferTodayEncryptedJobIdSource]
] = set()
```

Stage every valid normalized row once per observed triple, independently of the authoritative page pair:

```python
identity_key = (
    analysis.identity.job_id,
    analysis.identity.encrypted_job_id,
    analysis.identity.encrypted_job_id_source,
)
if (
    identity_key not in staged_identity_values
    and identity_key not in page_stage_identity_values
):
    page_stage_identity_values.add(identity_key)
    stage_identity_values.append(identity_key)
    stage_rows.append(parsed_row)
```

A later explicit observation is therefore offered to the staging sink as a provenance upgrade even if the canonical `jobId` was already seen as fallback. Extend `stage_identity_values` into `staged_identity_values` only after `stage_page()` succeeds. Commit `candidate_job_to_identity` only when the page has no issue or conflict, and build final `ListingRunResult.id_pairs` from that authoritative map with all three fields.

- [ ] **Step 6: Update serialization and staging-adapter fixture constructors**

Update expected serialized pairs in `test_offertoday_listing_runner.py` and `test_offertoday_standalone_crawl.py` to include:

```python
{
    "job_id": "job-1",
    "encrypted_job_id": "enc-1",
    "encrypted_job_id_source": "encryptJobId",
}
```

Every direct `ListingPageObservation` constructor in `test_offertoday_listing_runner.py`, `test_offertoday_standalone_crawl.py`, `test_offertoday_research_smoke.py`, `test_offertoday_research_live_service.py`, `test_offertoday_research_census_cli.py`, and `test_offertoday_research_observation_service.py` must set `job_id_fallback_count=0` unless the row is a fallback fixture.

- [ ] **Step 7: Run listing and adapter tests and verify GREEN**

Run:

```powershell
python -m pytest -q backend/tests/test_offertoday_listing_runner.py backend/tests/test_offertoday_standalone_crawl.py
```

Expected: all tests pass; both endpoint fixtures are stageable, raw missing count and fallback count are independently visible, promotion succeeds, and genuine explicit conflicts still stop the run.

- [ ] **Step 8: Commit Task 3**

```powershell
git add backend/app/sources/offertoday/listing_runner.py backend/tests/test_offertoday_listing_runner.py backend/tests/test_offertoday_standalone_crawl.py
git diff --cached --check
git commit -m "fix(offertoday): accept provenance-aware listing identities"
```

---

### Task 4: Carry Provenance Through Smoke Artifacts and Strict Offline Replay

**Files:**
- Modify: `backend/app/sources/offertoday/research/live_contracts.py`
- Modify: `backend/app/sources/offertoday/research/smoke.py`
- Modify: `backend/app/scraper/offertoday_browser_detail_scraper.py`
- Modify: `backend/app/services/offertoday_research_live_service.py`
- Modify: `backend/app/services/offertoday_research_observation_service.py`
- Modify: `backend/app/sources/offertoday/research/stage_gate.py`
- Modify: `backend/scripts/offertoday_research_census.py`
- Test: `backend/tests/test_offertoday_research_smoke.py`
- Test: `backend/tests/test_offertoday_research_live_service.py`
- Test: `backend/tests/test_offertoday_research_stage_gate.py`
- Test: `backend/tests/test_offertoday_research_census_cli.py`
- Test: `backend/tests/test_offertoday_research_observation_service.py`
- Test: `backend/tests/test_offertoday_canonical_and_identity.py`

- [ ] **Step 1: Write failing target serialization and cohort tests**

Update the smoke test pair helper to accept a source, then add:

```python
def pair(
    job_id: str,
    encrypted_job_id: str,
    source: OfferTodayEncryptedJobIdSource = "encryptJobId",
) -> OfferTodayIdentityPair:
    return OfferTodayIdentityPair(
        job_id=job_id,
        encrypted_job_id=encrypted_job_id,
        encrypted_job_id_source=source,
    )


def test_freeze_detail_cohort_preserves_jobid_fallback_provenance() -> None:
    result = listing_result(
        id_pairs=(pair("j1", "j1", "jobId_fallback"),),
        accepted_job_ids=("j1",),
    )

    frozen = freeze_detail_smoke_cohort(result, limit=1)

    assert frozen == (
        DetailSmokeTarget(
            position=1,
            job_id="j1",
            encrypted_job_id="j1",
            encrypted_job_id_source="jobId_fallback",
        ),
    )
    payload = frozen[0].to_payload()
    assert payload["encrypted_job_id_source"] == "jobId_fallback"
    assert len(payload["identity_resolution_hash"]) == 64


@pytest.mark.asyncio
async def test_browser_detail_scraper_omitted_route_uses_jobid_fallback() -> None:
    scraper_module = importlib.import_module(
        "app.scraper.offertoday_browser_detail_scraper"
    )
    calls: list[tuple[str, str]] = []

    async def fake_fetcher(*, job_id: str, encrypted_job_id: str):
        calls.append((job_id, encrypted_job_id))
        return {
            "code": 0,
            "data": _sample_detail_raw_missing_encrypted(),
        }

    scraper = scraper_module.OfferTodayBrowserDetailScraper(
        detail_json_fetcher=fake_fetcher
    )

    result = await scraper.fetch_job_detail("jid-1")

    assert calls == [("jid-1", "jid-1")]
    assert result.identity.encrypted_job_id_source == "jobId_fallback"
```

Replace the contradictory existing `test_offertoday_browser_detail_scraper_missing_encrypted_id_makes_zero_fetch_calls()` with the omitted-route fallback test above.

Add a live-service test asserting a fallback target calls the scraper with the same token and source:

```python
assert detail_scraper.calls[0] == (
    "j1",
    "j1",
    "jobId_fallback",
)
```

- [ ] **Step 2: Write failing strict replay tests**

In `backend/tests/test_offertoday_research_stage_gate.py`, import `json` and add:

```python
def _identity_resolution_hash(
    job_id: str,
    encrypted_job_id: str,
    source: OfferTodayEncryptedJobIdSource,
) -> str:
    canonical = json.dumps(
        {
            "job_id": job_id,
            "encrypted_job_id": encrypted_job_id,
            "encrypted_job_id_source": source,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()
```

Extend `_live_events()` with `identity_source: OfferTodayEncryptedJobIdSource = "encryptJobId"`. Its target builder must derive `route_id = f"j{position}" if identity_source == "jobId_fallback" else f"e{position}"` and add both:

```python
"encrypted_job_id_source": identity_source,
"identity_resolution_hash": _identity_resolution_hash(
    f"j{position}",
    route_id,
    identity_source,
),
```

Its successful `research.page_attempt` payload must contain the authoritative triples that freeze the cohort:

```python
"row_count": 20,
"missing_job_id_count": 0,
"missing_encrypted_job_id_count": (
    20 if identity_source == "jobId_fallback" else 0
),
"job_id_fallback_count": (
    20 if identity_source == "jobId_fallback" else 0
),
"id_pairs": [
    {
        "job_id": f"j{position}",
        "encrypted_job_id": target["encrypted_job_id"],
        "encrypted_job_id_source": identity_source,
    }
    for position, target in enumerate(targets, start=1)
],
"rows": [
    {
        "job_id": f"j{position}",
        "encrypted_job_id": target["encrypted_job_id"],
        "encrypted_job_id_source": identity_source,
        "observed_encrypted_job_id": (
            None
            if identity_source == "jobId_fallback"
            else target["encrypted_job_id"]
        ),
    }
    for position, target in enumerate(targets, start=1)
],
```

Add census tests requiring `_build_summary()` to place both `missing_encrypted_job_id_count` and `job_id_fallback_count` in the terminal `research.run_summary`. Cover an ordinary execution by reading its exact `listing_result.observations`, an unexpected post-listing exception by reading already-persisted `research.page_attempt` payloads, and a true pre-listing exception with zero for both. These cases require partial evidence preservation without constructing a browser or database dependency during best-effort finalization.

In `test_offertoday_research_observation_service.py`, assert `finish_run()` copies `job_id_fallback_count` into durable crawl-job metrics. Add that key to the explicit metrics allowlist in `OfferTodayResearchObservationService.finish_run()`; do not add row IDs or raw payloads to metrics.

Add `test_verify_live_run_accepts_consistent_completed_fallback_smoke()` by calling `_live_events(identity_source="jobId_fallback")`; assert `verify_live_research_run(artifact).valid is True`. Add tamper cases that change only target `encrypted_job_id_source`, target `identity_resolution_hash`, a page-row source/observation, page-pair source, page fallback/raw-missing count, or summary fallback count; assert the verifier returns `detail_cohort_identity_mismatch`, `invalid_detail_identity_resolution_hash`, `page_identity_authority_mismatch`, `missing_encrypted_job_id_count_mismatch`, or `job_id_fallback_count_mismatch` as appropriate.

Update every accepted artifact/contract fixture builder in `test_offertoday_research_smoke.py`, `test_offertoday_research_live_service.py`, `test_offertoday_research_census_cli.py`, and `test_offertoday_research_observation_service.py` so direct `ListingPageObservation` construction includes `job_id_fallback_count`, every pair/target includes a source, and serialized targets include the resolution hash. Explicit fixtures use source `encryptJobId` and count `0`; fallback fixtures use `jobId_fallback` and count the fallback triples. Do not retrofit these fields into the immutable failed artifact or require them for a failed legacy `identity_issue` page.

- [ ] **Step 3: Run smoke/replay tests and verify RED**

Run:

```powershell
python -m pytest -q backend/tests/test_offertoday_research_smoke.py backend/tests/test_offertoday_research_live_service.py backend/tests/test_offertoday_research_stage_gate.py backend/tests/test_offertoday_research_census_cli.py backend/tests/test_offertoday_research_observation_service.py backend/tests/test_offertoday_canonical_and_identity.py
```

Expected: failures because target provenance/hash fields, fallback page counters, source-aware scraper calls, and strict replay validation are absent.

- [ ] **Step 4: Extend the frozen target contract**

In `live_contracts.py`, import `OfferTodayEncryptedJobIdSource` and add `encrypted_job_id_source: OfferTodayEncryptedJobIdSource = "encryptJobId"` to `DetailSmokeTarget`, validate the exact two literals, and serialize:

```python
identity_payload = {
    "job_id": self.job_id,
    "encrypted_job_id": self.encrypted_job_id,
    "encrypted_job_id_source": self.encrypted_job_id_source,
}
identity_canonical = json.dumps(
    identity_payload,
    ensure_ascii=True,
    separators=(",", ":"),
    sort_keys=True,
)
return {
    "position": self.position,
    **identity_payload,
    "job_id_hash": hashlib.sha256(self.job_id.encode()).hexdigest(),
    "encrypted_job_id_hash": hashlib.sha256(
        self.encrypted_job_id.encode()
    ).hexdigest(),
    "identity_resolution_hash": hashlib.sha256(
        identity_canonical.encode()
    ).hexdigest(),
}
```

Delegate route/source invariants in `DetailSmokeTarget.__post_init__()` to a temporary `OfferTodayDetailIdentity(...)` after validating position; this rejects unknown sources and fallback routes that differ from `jobId`. Import `json`. In `freeze_detail_smoke_cohort()`, pass `identity.encrypted_job_id_source` into every target. If typed target construction raises `OfferTodayIdentityError`, do not silently skip it; let the deterministic contract fail because `ListingRunResult.id_pairs` is expected to be prevalidated.

- [ ] **Step 5: Pass source through the live no-write service**

First extend `OfferTodayBrowserDetailScraper.fetch_job_detail()` and `_build_request_identity()` with `encrypted_job_id_source: OfferTodayEncryptedJobIdSource | None = None`. Import the shared source type plus `resolve_offertoday_listing_identity` and replace the direct two-field identity constructor with:

```python
payload: dict[str, Any] = {
    "jobId": job_id,
    "encrypted_job_id": encrypted_job_id,
}
if encrypted_job_id_source is not None:
    payload["encrypted_job_id_source"] = encrypted_job_id_source
return resolve_offertoday_listing_identity(payload)
```

When `_build_fetch_result()` creates `canonical_detail`, write all three request-owned normalized fields while leaving `raw_response` and `parsed_detail["raw_data"]` untouched:

```python
canonical_detail = {
    **parsed_detail,
    "job_id": identity.job_id,
    "encrypted_job_id": identity.encrypted_job_id,
    "encrypted_job_id_source": identity.encrypted_job_id_source,
}
```

Update the detail scraper call in `OfferTodayResearchLiveService.run_smoke()`:

```python
detail_result = await detail_scraper.fetch_job_detail(
    target.job_id,
    encrypted_job_id=target.encrypted_job_id,
    encrypted_job_id_source=target.encrypted_job_id_source,
)
```

Update fake scraper signatures and calls in `test_offertoday_research_live_service.py` to store `(job_id, encrypted_job_id, encrypted_job_id_source)`.

In `detail_result_to_observation()`, set `identity_valid` only when the successful typed result identity equals the frozen target triple, not merely when `canonical_detail` exists:

```python
expected_identity = OfferTodayDetailIdentity(
    job_id=target.job_id,
    encrypted_job_id=target.encrypted_job_id,
    encrypted_job_id_source=target.encrypted_job_id_source,
)
identity_valid = (
    classification.kind is OfferTodayResponseKind.SUCCESS
    and result.canonical_detail is not None
    and result.identity == expected_identity
)
```

Add a regression where the fake scraper returns the same two IDs with a different source and assert the smoke observation is not identity-valid.

- [ ] **Step 6: Bind strict replay to page resolution evidence**

In `stage_gate.py`, make `_canonical_smoke_target()` return `(position, job_id, encrypted_job_id, source)`, require the exact source literals, and verify `identity_resolution_hash` from the canonical three-field JSON.

Add a page-pair canonicalizer:

```python
def _canonical_page_identity_pairs(
    payload: dict[str, Any],
    issues: list[str],
) -> list[tuple[str, str, str]]:
    values = payload.get("id_pairs")
    if not isinstance(values, list):
        issues.append("invalid_page_identity_pairs")
        return []
    pairs: list[tuple[str, str, str]] = []
    for value in values:
        if not isinstance(value, dict):
            issues.append("invalid_page_identity_pair")
            continue
        job_id = value.get("job_id")
        route_id = value.get("encrypted_job_id")
        source = value.get("encrypted_job_id_source")
        if (
            not isinstance(job_id, str)
            or not job_id.strip()
            or not isinstance(route_id, str)
            or not route_id.strip()
            or source not in ("encryptJobId", "jobId_fallback")
            or (source == "jobId_fallback" and route_id != job_id)
        ):
            issues.append("invalid_page_identity_pair")
            continue
        pairs.append((job_id, route_id, source))
    return pairs
```

Add `_canonical_page_row_identities()` for serialized `rows`. Require a nonblank `job_id`, nonblank route, exact source literal, and an `observed_encrypted_job_id` key. A fallback row must have route equal `jobId` and observed value `None`; an explicit row must have a nonblank observed value equal to its route. Return ordered typed identities plus the observed values.

Import `resolve_offertoday_listing_identity`, `build_offertoday_identity_authority_index`, and `OfferTodayIdentityError` into `stage_gate.py`; the canonicalizers must delegate identity/source rules to those shared functions after verifying artifact field types. Do not duplicate a third fallback policy in the verifier.

For a successful runtime-smoke page:

- require non-negative exact-integer `missing_encrypted_job_id_count` and `job_id_fallback_count`;
- require raw-missing count to equal the number of row observations whose observed encrypted ID is `None`;
- require fallback count to equal the number of row identities sourced from `jobId_fallback`;
- reduce row identities to one ordered authoritative triple per canonical job with `build_offertoday_identity_authority_index()` and require that sequence to equal `id_pairs`;
- require the terminal summary's fallback count to equal the page fallback count; and
- require the frozen cohort to equal the first 20 distinct authoritative page triples in order.

For source `jobId_fallback`, require the route ID to equal `jobId`; for source `encryptJobId`, do not require inequality because an explicitly observed value may coincidentally equal `jobId`. Emit `missing_encrypted_job_id_count_mismatch`, `job_id_fallback_count_mismatch`, or `page_identity_authority_mismatch` for the three independent checks.

Preserve compatibility for the immutable failed smoke by branching only when all of the following hold: the run is failed, the page classification is `identity_issue`, `id_pairs` is empty, and every page issue reason is `missing_encrypted_job_id`. That legacy page may omit `job_id_fallback_count` and target resolution hashes, but it cannot be accepted as a completed smoke. Add a regression that points `verify_live_research_run()` at `backend/runtime/offertoday-research/fab9d8e1-4c12-4170-a539-c0a6cdbbca93` and asserts `valid is True` without modifying the artifact.

In `offertoday_research_census.py`, implement that logic in the existing `_build_summary()` (there is no `_build_smoke_summary()`), and include both summary counters in the final CLI JSON printed after artifact verification:

```python
def _listing_identity_counts(
    *,
    execution,
    events_before_summary: list[dict[str, Any]],
) -> tuple[int, int]:
    if execution is not None:
        page_payloads = [
            listing_observation_to_payload(observation)
            for observation in execution.listing_result.observations
        ]
    else:
        page_payloads = [
            event["payload"]
            for event in events_before_summary
            if event.get("event_type") == "research.page_attempt"
            and isinstance(event.get("payload"), dict)
        ]

    def total(field_name: str) -> int:
        values = [payload.get(field_name, 0) for payload in page_payloads]
        if any(type(value) is not int or value < 0 for value in values):
            raise ValueError(
                f"research page {field_name} must be a non-negative exact integer"
            )
        return sum(values)

    return (
        total("missing_encrypted_job_id_count"),
        total("job_id_fallback_count"),
    )
```

Call this helper once in `_build_summary()` and write both returned integers into the summary payload. Then extend the terminal print payload:

```python
{
    "artifact": str(artifact_dir),
    "run_id": run_id,
    "exit_code": exit_code,
    "smoke_passed": bool(summary.get("smoke_passed")),
    "missing_encrypted_job_id_count": int(
        summary.get("missing_encrypted_job_id_count", 0)
    ),
    "job_id_fallback_count": int(summary.get("job_id_fallback_count", 0)),
}
```

Add a focused `_build_summary()` regression for an unexpected error after a persisted page attempt: even though `execution is None`, the best-effort terminal summary retains that page's exact raw-missing and fallback counts. A true pre-listing exception records zero for both. Separately, make the normal fallback-smoke CLI regression assert that stdout exposes both counters. Do not alter request budgets, retry policy, pacing, exception propagation, or exit-code mapping.

- [ ] **Step 7: Run the smoke-focused suite and verify GREEN**

Run:

```powershell
python -m pytest -q `
  backend/tests/test_offertoday_research_smoke.py `
  backend/tests/test_offertoday_research_live_service.py `
  backend/tests/test_offertoday_research_stage_gate.py `
  backend/tests/test_offertoday_research_census_cli.py `
  backend/tests/test_offertoday_research_observation_service.py `
  backend/tests/test_offertoday_research_staging_service.py `
  backend/tests/test_offertoday_canonical_and_identity.py
```

Expected: all tests pass; completed fallback artifacts replay strictly offline, tampered source/count evidence fails, the current two-listing/20-detail budget is enforced, and legacy one-listing/20-detail compatibility is limited to fail-only offline replay.

- [ ] **Step 8: Verify the immutable failed artifact offline**

Run:

```powershell
$artifact = 'backend/runtime/offertoday-research/fab9d8e1-4c12-4170-a539-c0a6cdbbca93'
$before = (Get-FileHash "$artifact/manifest.json" -Algorithm SHA256).Hash.ToLowerInvariant()
python backend/scripts/offertoday_research_census.py verify-run --artifact $artifact
if ($LASTEXITCODE -ne 0) { throw "immutable failed smoke no longer verifies" }
$after = (Get-FileHash "$artifact/manifest.json" -Algorithm SHA256).Hash.ToLowerInvariant()
if ($before -ne $after) { throw "immutable failed smoke was modified" }
```

Expected: exit `0`; both hashes equal `1928423eed6cfd95e4cd2a3af3eb1d62c2ea6d460b122acb0ca0fefcfb4b548b`. This command is offline and constructs no runtime/browser/database dependency.

- [ ] **Step 9: Commit Task 4**

```powershell
git add backend/app/sources/offertoday/research/live_contracts.py backend/app/sources/offertoday/research/smoke.py backend/app/scraper/offertoday_browser_detail_scraper.py backend/app/services/offertoday_research_live_service.py backend/app/services/offertoday_research_observation_service.py backend/app/sources/offertoday/research/stage_gate.py backend/scripts/offertoday_research_census.py backend/tests/test_offertoday_canonical_and_identity.py
git add -f backend/tests/test_offertoday_research_smoke.py backend/tests/test_offertoday_research_live_service.py backend/tests/test_offertoday_research_stage_gate.py backend/tests/test_offertoday_research_census_cli.py backend/tests/test_offertoday_research_observation_service.py
git diff --cached --check
git commit -m "fix(offertoday): preserve smoke identity provenance"
```

---

### Task 5: Resolve Historical Fallback Rows and Promote One Explicit Authority

**Files:**
- Modify: `backend/scripts/offertoday_standalone_crawl.py`
- Modify: `backend/app/repositories/crawl_job_repository.py`
- Modify: `backend/app/services/crawl_job_runtime.py`
- Modify: `backend/app/services/offertoday_detail_pipeline.py`
- Test: `backend/tests/test_offertoday_standalone_crawl.py`
- Test: `backend/tests/test_crawl_job_runtime.py`
- Test: `backend/tests/test_offertoday_detail_pipeline.py`

- [ ] **Step 1: Write failing staging and historical-authority tests**

In `test_offertoday_standalone_crawl.py`, add:

```python
def test_listing_staging_payload_accepts_jobid_fallback_without_raw_fabrication():
    crawl_module = importlib.import_module("backend.scripts.offertoday_standalone_crawl")
    parsed = {
        "job_id": "j-fallback",
        "encrypted_job_id": "j-fallback",
        "encrypted_job_id_source": "jobId_fallback",
        "title": "Fallback fixture",
        "raw_data": {"jobId": "j-fallback"},
    }

    payload = crawl_module._build_listing_staging_payload(
        parsed,
        condition=SimpleNamespace(
            category_id=118000,
            search_family="it_category",
            keyword="",
        ),
        page=1,
        rank=1,
    )

    assert payload["source_job_id"] == "j-fallback"
    assert payload["source_url"].endswith("/j-fallback")
    assert payload["listing_payload"]["encrypted_job_id_source"] == (
        "jobId_fallback"
    )
    assert payload["listing_payload"]["raw_data"] == {"jobId": "j-fallback"}
```

Delete the contradictory `pytest.raises(..., match="encrypted_job_id")` block from `test_build_listing_staging_payload_uses_canonical_id_and_encrypted_public_url()`. A blank normalized route with a valid canonical `job_id` now resolves to that canonical token; retain strict missing/invalid canonical-ID coverage in the shared resolver tests. Also assert that the explicit half of this existing staging test serializes `encrypted_job_id_source == "encryptJobId"`.

In `test_crawl_job_runtime.py`, add:

```python
def test_jobid_only_history_resolves_without_mutation_or_identity_conflict():
    payload = {
        "job_id": "j-1",
        "encrypted_job_id": "j-1",
        "encrypted_job_id_source": "jobId_fallback",
        "raw_data": {"jobId": "j-1"},
    }
    row = _detail_listing("row-1", "j-1", listing_payload=payload, rank=1)
    before = deepcopy(row.listing_payload)
    runtime, repository, _crawl_jobs, _session = _detail_runtime([row])

    result = runtime.load_detail_targets(
        source_site="offertoday",
        request_payload={"detail_limit": 10},
        detail_crawl_job_id="detail-run-1",
    )

    assert result.identity_conflict_ids == ()
    assert result.targets[0]["identity"].job_id == "j-1"
    assert result.targets[0]["identity"].encrypted_job_id == "j-1"
    assert result.targets[0]["identity"].encrypted_job_id_source == (
        "jobId_fallback"
    )
    assert row.listing_payload == before
    assert repository.identity_conflict_listing_ids == []


def test_one_explicit_history_mapping_promotes_fallback_authority():
    fallback = _detail_listing(
        "fallback",
        "j-1",
        listing_payload={
            "job_id": "j-1",
            "encrypted_job_id": "j-1",
            "encrypted_job_id_source": "jobId_fallback",
            "raw_data": {"jobId": "j-1"},
        },
        rank=1,
    )
    explicit = _detail_listing(
        "explicit",
        "j-1",
        listing_payload={
            "job_id": "j-1",
            "encrypted_job_id": "enc-1",
            "encrypted_job_id_source": "encryptJobId",
            "raw_data": {"jobId": "j-1", "encryptJobId": "enc-1"},
        },
        rank=2,
    )
    runtime, _repository, _crawl_jobs, _session = _detail_runtime(
        [fallback, explicit]
    )

    result = runtime.load_detail_targets(
        source_site="offertoday",
        request_payload={"detail_limit": 10},
        detail_crawl_job_id="detail-run-1",
    )

    assert result.identity_conflict_ids == ()
    assert result.targets[0]["identity"].encrypted_job_id == "enc-1"
    assert result.targets[0]["identity"].encrypted_job_id_source == "encryptJobId"


def test_unselected_invalid_history_does_not_block_unrelated_target():
    valid = _detail_listing(
        "valid",
        "j-1",
        listing_payload={
            "job_id": "j-1",
            "encrypted_job_id": "j-1",
            "encrypted_job_id_source": "jobId_fallback",
            "raw_data": {"jobId": "j-1"},
        },
        rank=1,
    )
    unrelated_invalid = _detail_listing(
        "invalid",
        "j-other",
        listing_payload={"raw_data": {"jobId": "j-other", "encryptJobId": []}},
        rank=2,
    )
    runtime, repository, _crawl_jobs, _session = _detail_runtime(
        [valid],
        identity_history=[valid, unrelated_invalid],
    )

    result = runtime.load_detail_targets(
        source_site="offertoday",
        request_payload={"detail_limit": 10},
        detail_crawl_job_id="detail-run-1",
    )

    assert result.identity_conflict_ids == ()
    assert result.targets[0]["source_job_id"] == "j-1"
    assert repository.identity_conflict_listing_ids == []


def test_skipped_explicit_observation_promotes_fallback_without_rewriting_row():
    fallback_payload = {
        "job_id": "j-1",
        "encrypted_job_id": "j-1",
        "encrypted_job_id_source": "jobId_fallback",
        "raw_data": {"jobId": "j-1"},
    }
    fallback = _detail_listing(
        "fallback",
        "j-1",
        listing_payload=fallback_payload,
        rank=1,
    )
    before = deepcopy(fallback.listing_payload)
    runtime, _repository, crawl_jobs, _session = _detail_runtime([fallback])
    crawl_jobs.identity_observations = [
        {
            "source_job_id": "j-1",
            "job_id": "j-1",
            "encrypted_job_id": "enc-1",
            "encrypted_job_id_source": "encryptJobId",
        }
    ]

    result = runtime.load_detail_targets(
        source_site="offertoday",
        request_payload={"detail_limit": 10},
        detail_crawl_job_id="detail-run-1",
    )

    assert result.identity_conflict_ids == ()
    assert result.targets[0]["identity"].encrypted_job_id == "enc-1"
    assert result.targets[0]["identity"].encrypted_job_id_source == "encryptJobId"
    assert fallback.listing_payload == before
    assert any(
        event["event_type"] == "crawl.detail_identity_provenance_upgraded"
        for event in crawl_jobs.events
    )
```

If `_detail_runtime()` does not currently accept a separate history list, extend its fake listing repository with `identity_history`; default it to selected rows so existing tests remain unchanged.

Initialize `self.identity_observations: list[dict] = []` inside `_FakeCrawlJobRepository.__init__()` and add `list_offertoday_listing_identity_observations()` returning deep copies of that instance list. Retain the existing two-explicit and reverse-collision tests; update expected conflict reason from `missing_or_changed_encrypted_id` to `multiple_explicit_encrypted_ids` where appropriate.

Keep `test_missing_identity_is_durable_conflict_and_event_failure_rolls_back()` strict by changing its fixture payload to omit canonical job evidence entirely, for example `{"encrypted_job_id": ""}`. A payload with valid `job_id="j-bad"` and only a blank encrypted alias is now a valid fallback and must no longer serve as the malformed fixture.

Update the existing `test_offertoday_stage_batch_locks_then_partitions_global_canonical_ids_and_records_event` expectation so every `crawl.listing_observed.payload.observations` entry also contains its resolved `job_id`, `encrypted_job_id`, and `encrypted_job_id_source`. Build the same-canonical upgrade inputs explicitly; setting only `encrypted_job_id == jobId` in the old helper is insufficient because its raw fixture still claims an upstream `encryptJobId`:

```python
fallback_payload = _offertoday_stage_payload(
    "upgrade-1",
    encrypted_job_id="upgrade-1",
)
fallback_payload["listing_payload"] = {
    "job_id": "upgrade-1",
    "encrypted_job_id": "upgrade-1",
    "encrypted_job_id_source": "jobId_fallback",
    "raw_data": {"jobId": "upgrade-1"},
}
explicit_payload = _offertoday_stage_payload(
    "upgrade-1",
    encrypted_job_id="enc-upgrade-1",
)
explicit_payload["listing_payload"]["encrypted_job_id_source"] = "encryptJobId"
```

Add both to one batch, fallback first. Assert only one staging row is created, but the event keeps two observation records in input order and the second record is the explicit triple. This proves same-batch and globally skipped explicit evidence remains durable.

Import `CrawlJob`, `CrawlJobEvent`, and `CrawlJobRepository` and add a repository regression:

```python
def test_crawl_job_repository_lists_offertoday_identity_observations_in_order():
    engine = create_engine("sqlite://")
    CrawlJob.__table__.create(engine)
    CrawlJobEvent.__table__.create(engine)
    offertoday_id = uuid4()
    jobsdb_id = uuid4()
    with Session(engine) as db:
        db.add_all(
            [
                CrawlJob(
                    id=offertoday_id,
                    source_site="offertoday",
                    trigger_type="manual",
                    status="completed",
                    request_payload={},
                ),
                CrawlJob(
                    id=jobsdb_id,
                    source_site="jobsdb",
                    trigger_type="manual",
                    status="completed",
                    request_payload={},
                ),
            ]
        )
        db.flush()
        db.add_all(
            [
                CrawlJobEvent(
                    crawl_job_id=offertoday_id,
                    sequence_no=1,
                    event_type="crawl.listing_observed",
                    payload={
                        "observations": [
                            {
                                "source_job_id": "j-1",
                                "job_id": "j-1",
                                "encrypted_job_id": "j-1",
                                "encrypted_job_id_source": "jobId_fallback",
                            }
                        ]
                    },
                ),
                CrawlJobEvent(
                    crawl_job_id=jobsdb_id,
                    sequence_no=1,
                    event_type="crawl.listing_observed",
                    payload={"observations": [{"source_job_id": "ignore"}]},
                ),
            ]
        )
        db.commit()

        observations = (
            CrawlJobRepository().list_offertoday_listing_identity_observations(db)
        )

    assert observations == [
        {
            "source_job_id": "j-1",
            "job_id": "j-1",
            "encrypted_job_id": "j-1",
            "encrypted_job_id_source": "jobId_fallback",
        }
    ]
```

- [ ] **Step 2: Write a failing promoted-target test**

In `test_offertoday_detail_pipeline.py`, add:

```python
def test_target_accepts_explicit_authority_over_fallback_listing_without_rewrite():
    runtime_target = _runtime_target("100")
    runtime_target["listing_payload"] = {
        "job_id": "100",
        "encrypted_job_id": "100",
        "encrypted_job_id_source": "jobId_fallback",
        "raw_data": {"jobId": "100"},
    }
    runtime_target["identity"] = OfferTodayDetailIdentity(
        job_id="100",
        encrypted_job_id="enc-100",
        encrypted_job_id_source="encryptJobId",
    )
    before = deepcopy(runtime_target["listing_payload"])

    target = OfferTodayDetailTarget.from_runtime_target(runtime_target)

    assert target.identity.encrypted_job_id == "enc-100"
    assert target.identity.encrypted_job_id_source == "encryptJobId"
    assert runtime_target["listing_payload"] == before
```

- [ ] **Step 3: Run staging/target tests and verify RED**

Run:

```powershell
python -m pytest -q backend/tests/test_offertoday_standalone_crawl.py backend/tests/test_crawl_job_runtime.py backend/tests/test_offertoday_detail_pipeline.py -k "jobid_only or fallback or promotes or promoted or unselected or identity_observations or changed_encrypted or reverse"
```

Expected: failures because staging rejects the equal fallback route, history treats fallback plus explicit as a conflict, and a promoted supplied identity must equal the row-local identity exactly.

- [ ] **Step 4: Resolve the staging payload through the shared contract**

In `_build_listing_staging_payload()` in `backend/scripts/offertoday_standalone_crawl.py`, replace the manual nonblank checks with:

```python
identity = resolve_offertoday_detail_identity(
    source_job_id=normalized_listing.get("job_id"),
    listing_payload=normalized_listing,
)
normalized_listing["job_id"] = identity.job_id
normalized_listing["encrypted_job_id"] = identity.encrypted_job_id
normalized_listing["encrypted_job_id_source"] = (
    identity.encrypted_job_id_source
)
```

Build `source_job_id` and URL from `identity`. Keep the copied `raw_data` exactly as supplied. Import `resolve_offertoday_detail_identity` at the top of the script.

- [ ] **Step 5: Persist skipped identity observations and audit rows plus events**

In `CrawlJobRuntime._listing_observation_payload()`, resolve the outer staging payload and add the three identity fields to the existing observation record:

```python
listing_payload = payload.get("listing_payload")
identity = resolve_offertoday_detail_identity(
    source_job_id=source_job_id,
    listing_payload=(
        dict(listing_payload) if isinstance(listing_payload, dict) else {}
    ),
)
return {
    "source_job_id": source_job_id,
    "job_id": identity.job_id,
    "encrypted_job_id": identity.encrypted_job_id,
    "encrypted_job_id_source": identity.encrypted_job_id_source,
    "classification": classification,
    "search_family": CrawlJobRuntime._optional_str(payload.get("search_family")),
    "category_id": CrawlJobRuntime._optional_str(
        payload.get("category_id") or payload.get("source_classification_id")
    ),
    "category_name": CrawlJobRuntime._optional_str(
        payload.get("category_name")
        or payload.get("source_classification_name")
    ),
    "keyword": CrawlJobRuntime._optional_str(payload.get("keyword")),
    "page": CrawlJobRuntime._optional_int(
        payload.get("page")
        if payload.get("page") is not None
        else payload.get("listing_page")
    ),
}
```

Keep the existing `first_payload_by_source_job_id` map only for relational staging, where one row per canonical ID is correct. Build event observations from every input payload instead of that map:

```python
"observations": [
    self._listing_observation_payload(
        source_job_id=source_job_id,
        classification=classification_by_source_job_id[source_job_id],
        payload=input_payload,
    )
    for input_payload in batch_payloads
    if (
        source_job_id := str(
            input_payload.get("source_job_id") or ""
        ).strip()
    )
],
```

`source_job_ids`, `job_ids_seen`, staging rows, and classifications remain canonical-`jobId` distinct. Only the observation list is triple-preserving. Therefore a later or same-batch explicit observation remains durable even when global staging deduplication correctly avoids another row.

In `backend/app/repositories/crawl_job_repository.py`, import `Mapping` from `collections.abc` and add this read-only method:

```python
def list_offertoday_listing_identity_observations(
    self,
    db: Session,
) -> list[dict[str, Any]]:
    events = (
        db.query(CrawlJobEvent)
        .join(CrawlJob, CrawlJob.id == CrawlJobEvent.crawl_job_id)
        .filter(
            CrawlJob.source_site == "offertoday",
            CrawlJobEvent.event_type == "crawl.listing_observed",
        )
        .order_by(CrawlJobEvent.created_at.asc(), CrawlJobEvent.id.asc())
        .all()
    )
    observations: list[dict[str, Any]] = []
    for event in events:
        payload = event.payload if isinstance(event.payload, Mapping) else {}
        values = payload.get("observations")
        if not isinstance(values, list):
            continue
        for value in values:
            if not isinstance(value, Mapping):
                continue
            if not {
                "job_id",
                "encrypted_job_id",
                "encrypted_job_id_source",
            }.issubset(value):
                continue
            observations.append(dict(value))
    return observations
```

Legacy `crawl.listing_observed` events without the three new keys are ignored; they are not treated as identity failures.

Replace `_audit_offertoday_detail_identities()` with an event-aware authority audit. Its signature and return contract are:

```python
def _audit_offertoday_detail_identities(
    *,
    identity_history: list[Any],
    identity_observations: list[dict[str, Any]],
    selected_rows: list[Any],
    groups: dict[str, list[Any]],
) -> tuple[
    dict[Any, OfferTodayDetailIdentity],
    dict[str, OfferTodayDetailIdentity],
    dict[str, set[str]],
    dict[str, set[str]],
    dict[str, str],
    tuple[dict[str, str], ...],
]:
    selected_row_ids = {row.id for row in selected_rows}
```

Use this implementation body after `selected_row_ids`; its collection phase feeds the shared authority index rather than reimplementing promotion/reverse-collision rules:

```python
resolved_identity_by_row_id: dict[Any, OfferTodayDetailIdentity] = {}
all_identities: list[OfferTodayDetailIdentity] = []
unusable_job_ids: set[str] = set()

def add_identity(identity: OfferTodayDetailIdentity) -> None:
    all_identities.append(identity)

for history_row in identity_history:
    source_job_id = str(
        getattr(history_row, "source_job_id", "") or ""
    ).strip()
    history_payload = getattr(history_row, "listing_payload", None)
    try:
        identity = resolve_offertoday_detail_identity(
            source_job_id=source_job_id,
            listing_payload=(
                dict(history_payload)
                if isinstance(history_payload, Mapping)
                else {}
            ),
        )
    except OfferTodayIdentityError:
        if source_job_id:
            unusable_job_ids.add(source_job_id)
        continue
    add_identity(identity)
    if history_row.id in selected_row_ids:
        resolved_identity_by_row_id[history_row.id] = identity

for observation in identity_observations:
    source_job_id = str(observation.get("source_job_id") or "").strip()
    try:
        identity = resolve_offertoday_detail_identity(
            source_job_id=source_job_id,
            listing_payload=observation,
        )
    except OfferTodayIdentityError:
        if source_job_id:
            unusable_job_ids.add(source_job_id)
        continue
    add_identity(identity)

authority_index = build_offertoday_identity_authority_index(
    tuple(all_identities)
)
authoritative_identity_by_job = dict(
    authority_index.authoritative_identity_by_job
)
explicit_ids_by_job = {
    job_id: set(route_ids)
    for job_id, route_ids in authority_index.explicit_ids_by_job.items()
}
route_to_job_ids = {
    route_id: set(job_ids)
    for route_id, job_ids in authority_index.route_to_job_ids.items()
}

conflict_reason_by_job: dict[str, str] = {}
for source_job_id, rows in groups.items():
    selected_identities = [
        resolved_identity_by_row_id.get(row.id) for row in rows
    ]
    if source_job_id in authority_index.conflict_reason_by_job:
        conflict_reason_by_job[source_job_id] = (
            authority_index.conflict_reason_by_job[source_job_id]
        )
        continue
    if (
        source_job_id in unusable_job_ids
        or any(identity is None for identity in selected_identities)
        or source_job_id not in authoritative_identity_by_job
    ):
        conflict_reason_by_job[source_job_id] = "unusable_identity_evidence"
        continue
    authority = authoritative_identity_by_job[source_job_id]
    if len(route_to_job_ids.get(authority.encrypted_job_id, set())) > 1:
        conflict_reason_by_job[source_job_id] = "reverse_collision"

provenance_upgrades = tuple(
    {
        "source_job_id": source_job_id,
        "encrypted_job_id": authoritative_identity_by_job[
            source_job_id
        ].encrypted_job_id,
        "from_source": "jobId_fallback",
        "to_source": "encryptJobId",
    }
    for source_job_id in groups
    if source_job_id not in conflict_reason_by_job
    and source_job_id in authority_index.fallback_job_ids
    and authoritative_identity_by_job[source_job_id].encrypted_job_id_source
    == "encryptJobId"
)

return (
    resolved_identity_by_row_id,
    authoritative_identity_by_job,
    explicit_ids_by_job,
    route_to_job_ids,
    conflict_reason_by_job,
    provenance_upgrades,
)
```

Import `Mapping` from `collections.abc` in `crawl_job_runtime.py`. `unusable_job_ids` may contain unrelated historical jobs, but only IDs present in `groups` enter `conflict_reason_by_job`. Valid selected jobs therefore remain targetable while malformed evidence, including a non-object listing payload, still blocks its own canonical job.

Return the six values in the declared order. Update the caller to pass:

```python
identity_observations=(
    self.crawl_job_repository.list_offertoday_listing_identity_observations(db)
),
```

Use `authoritative_identity_by_job[source_job_id]` for every OfferToday target. When `provenance_upgrades` is nonempty, append exactly one transaction-bound event before commit:

```python
self.crawl_job_repository.append_event(
    db,
    crawl_job_id=detail_crawl_job_id,
    event_type="crawl.detail_identity_provenance_upgraded",
    payload={"upgrades": [dict(item) for item in provenance_upgrades]},
    emitted_by="crawl-runtime",
    auto_commit=False,
)
```

Rewrite `_build_identity_conflict_evidence()` as:

```python
def _build_identity_conflict_evidence(
    *,
    conflict_reason_by_job: dict[str, str],
    explicit_ids_by_job: dict[str, set[str]],
    authoritative_identity_by_job: dict[str, OfferTodayDetailIdentity],
    route_to_job_ids: dict[str, set[str]],
) -> list[dict[str, Any]]:
    evidence_records: list[dict[str, Any]] = []
    for source_job_id in sorted(conflict_reason_by_job):
        authority = authoritative_identity_by_job.get(source_job_id)
        reverse_peer_job_ids = (
            sorted(
                route_to_job_ids.get(authority.encrypted_job_id, set())
                - {source_job_id}
            )
            if authority is not None
            else []
        )
        evidence_records.append(
            {
                "source_job_id": source_job_id,
                "encrypted_job_ids": sorted(
                    explicit_ids_by_job.get(source_job_id, set())
                ),
                "reverse_peer_job_ids": reverse_peer_job_ids,
                "reason": conflict_reason_by_job[source_job_id],
            }
        )
    return evidence_records
```

Use `identity_conflict_ids = set(conflict_reason_by_job)` in the existing conflict transition branch. Fallback-only evidence never creates `multiple_explicit_encrypted_ids`.

- [ ] **Step 6: Permit an authoritative supplied identity in the typed target**

In `OfferTodayDetailTarget.from_runtime_target()`, replace exact equality with:

```python
listing_identity = resolve_offertoday_detail_identity(
    source_job_id=target.get("source_job_id"),
    listing_payload=listing_payload,
)
supplied_identity = target.get("identity")
if supplied_identity is None:
    identity = listing_identity
elif not isinstance(supplied_identity, OfferTodayDetailIdentity):
    raise ValueError("OfferToday runtime target identity must be typed")
else:
    authority_index = build_offertoday_identity_authority_index(
        (listing_identity, supplied_identity)
    )
    if authority_index.conflict_reason_by_job:
        raise ValueError("OfferToday runtime target identity is conflicting")
    identity = authority_index.authoritative_identity_by_job[
        listing_identity.job_id
    ]
    if identity != supplied_identity:
        raise ValueError(
            "OfferToday runtime target identity does not match authoritative identity"
        )
```

This accepts fallback-to-explicit promotion without mutating the listing payload, while still rejecting a supplied fallback that attempts to downgrade known explicit authority.

- [ ] **Step 7: Run staging/runtime/target regressions and verify GREEN**

Run:

```powershell
python -m pytest -q backend/tests/test_offertoday_standalone_crawl.py backend/tests/test_crawl_job_runtime.py backend/tests/test_offertoday_detail_pipeline.py
```

Expected: all tests pass; historical job-only rows are targetable without mutation, one explicit mapping promotes, multiple explicit mappings and reverse collisions defer, and no relational schema change exists.

- [ ] **Step 8: Commit Task 5 without staging unrelated standalone hunks**

```powershell
git add backend/app/repositories/crawl_job_repository.py backend/app/services/crawl_job_runtime.py backend/app/services/offertoday_detail_pipeline.py backend/tests/test_crawl_job_runtime.py backend/tests/test_offertoday_detail_pipeline.py backend/tests/test_offertoday_standalone_crawl.py
git add -p backend/scripts/offertoday_standalone_crawl.py
git diff --cached -- backend/scripts/offertoday_standalone_crawl.py
git diff --cached --check
git commit -m "fix(offertoday): promote fallback detail authority"
```

Expected staged standalone diff: only imports and `_build_listing_staging_payload()`; no `planned_total_pages`, `current_page`, `total_pages`, or `search_family` hunk.

---

### Task 6: Preserve Provenance Through Detail Fetch, Persistence, and Repair

**Files:**
- Modify: `backend/app/scraper/offertoday_browser_detail_scraper.py`
- Modify: `backend/app/services/offertoday_detail_pipeline.py`
- Modify: `backend/app/services/crawl_job_runtime.py`
- Modify: `backend/app/services/offertoday_job_repair_service.py`
- Modify: `backend/scripts/repair_offertoday_jobs.py`
- Test: `backend/tests/test_offertoday_canonical_and_identity.py`
- Test: `backend/tests/test_offertoday_detail_pipeline.py`
- Test: `backend/tests/test_offertoday_browser_runtime.py`
- Test: `backend/tests/test_offertoday_standalone_crawl.py`

- [ ] **Step 1: Write failing detail request/response provenance tests**

Add to `test_offertoday_canonical_and_identity.py`:

```python
@pytest.mark.asyncio
async def test_browser_detail_scraper_jobid_fallback_uses_same_tokens_and_preserves_source():
    scraper_module = importlib.import_module(
        "app.scraper.offertoday_browser_detail_scraper"
    )
    calls = []
    raw_response = {
        "code": 0,
        "data": _sample_detail_raw_missing_encrypted(),
    }
    raw_before = deepcopy(raw_response)

    async def fake_fetcher(*, job_id: str, encrypted_job_id: str):
        calls.append((job_id, encrypted_job_id))
        return raw_response

    scraper = scraper_module.OfferTodayBrowserDetailScraper(
        detail_json_fetcher=fake_fetcher
    )
    result = await scraper.fetch_job_detail(
        "jid-1",
        encrypted_job_id="jid-1",
        encrypted_job_id_source="jobId_fallback",
    )

    assert calls == [("jid-1", "jid-1")]
    assert result.identity.encrypted_job_id_source == "jobId_fallback"
    assert result.canonical_detail["encrypted_job_id_source"] == "jobId_fallback"
    assert result.raw_response == raw_before
    assert "encryptJobId" not in result.raw_response["data"]
```

Add a second request-owned normalization regression for an explicit target whose successful response omits `encryptJobId`:

```python
@pytest.mark.asyncio
async def test_browser_detail_scraper_keeps_explicit_target_when_response_omits_encrypted_id():
    scraper_module = importlib.import_module(
        "app.scraper.offertoday_browser_detail_scraper"
    )
    raw_response = {"code": 0, "data": _sample_detail_raw_missing_encrypted()}

    async def fake_fetcher(*, job_id: str, encrypted_job_id: str):
        assert (job_id, encrypted_job_id) == ("jid-1", "enc-jid-1")
        return raw_response

    scraper = scraper_module.OfferTodayBrowserDetailScraper(
        detail_json_fetcher=fake_fetcher
    )
    result = await scraper.fetch_job_detail(
        "jid-1",
        encrypted_job_id="enc-jid-1",
        encrypted_job_id_source="encryptJobId",
    )

    assert result.identity.encrypted_job_id == "enc-jid-1"
    assert result.canonical_detail["encrypted_job_id"] == "enc-jid-1"
    assert result.canonical_detail["encrypted_job_id_source"] == "encryptJobId"
    assert result.canonical_detail["raw_data"] == raw_response["data"]
    assert "encryptJobId" not in result.canonical_detail["raw_data"]
```

Keep and rerun existing response `jobId` mismatch and explicit response `encryptJobId` mismatch tests.

- [ ] **Step 2: Write failing pipeline raw-preservation and hash tests**

In `test_offertoday_detail_pipeline.py`, add a fallback `_runtime_target` variant and assert:

```python
assert env.fetcher.calls == [("100", "100")]
assert stored_detail["job_id"] == "100"
assert stored_detail["encrypted_job_id"] == "100"
assert stored_detail["encrypted_job_id_source"] == "jobId_fallback"
assert stored_detail["raw_data"] == raw_response["data"]
assert "encryptJobId" not in stored_detail["raw_data"]
assert "listing_only_marker" not in stored_detail
assert attempt_event["payload"]["detail_crawl_job_id"] == "detail-run"
assert attempt_event["payload"]["encrypted_job_id_source"] == "jobId_fallback"
assert persisted_event["payload"]["encrypted_job_id_source"] == "jobId_fallback"
```

Add a promoted explicit target whose listing row is fallback and whose response has matching `jobId` but no `encryptJobId`; assert the persisted `detail_payload` contains target-owned `encrypted_job_id="enc-100"` and source `encryptJobId`, while its nested `raw_data` remains byte-for-byte equal to the response `data`. This prevents the parser's response-local fallback from downgrading event-only authority.

Change the expected response identity hash to canonical JSON over all three fields:

```python
{
    "encrypted_job_id": "100",
    "encrypted_job_id_source": "jobId_fallback",
    "job_id": "100",
}
```

- [ ] **Step 3: Write failing offline repair round-trip test**

Extend `test_offline_parsed_repair_persists_canonical_identity_for_cached_round_trip` with a job-only listing and assert:

```python
assert listing.detail_payload["job_id"] == "jid-1"
assert listing.detail_payload["encrypted_job_id"] == "jid-1"
assert listing.detail_payload["encrypted_job_id_source"] == "jobId_fallback"
assert "encryptJobId" not in listing.detail_payload["raw_data"]
```

Add a separate explicit fixture assertion proving `enc-jid-1` and source `encryptJobId` survive unchanged.

Add repair authority regressions with fake staging-history and crawl-event repositories. One consistent explicit event over a fallback-only row must make `resolve_detail_identity()` return the explicit route/source without mutating the listing; `repair_job()` and offline parsed repair must both persist/build a canonical URL using the promoted explicit route while nested raw evidence remains unchanged. Two explicit routes or a reverse collision involving another canonical job must raise `OfferTodayIdentityError` before the scraper or write repositories are called. Call the resolver for two jobs and assert each read repository was invoked exactly once, proving the global authority index is cached. Assert the legacy two-string `resolve_detail_identifiers()` wrapper returns the promoted explicit route.

Update the existing `db=object()` repair tests that are not exercising authority audit to inject empty fake staging-history and event repositories, or use `db=None` for pure read-only helpers. Do not let production repository defaults query an object sentinel. Tests exercising persistence keep their fake DB/write repositories and add the two read fakes explicitly.

- [ ] **Step 4: Run detail/repair tests and verify RED**

Run:

```powershell
python -m pytest -q backend/tests/test_offertoday_canonical_and_identity.py backend/tests/test_offertoday_detail_pipeline.py backend/tests/test_offertoday_browser_runtime.py -k "fallback or authority or promotes or reverse_collision or mismatch or offline_parsed_repair or passes_both_ids or repair_jobs"
```

Expected: failures because the scraper signature/result, pipeline events/hash, canonical payload, and repair payload omit provenance; the pipeline currently fabricates `raw_data.encryptJobId`.

- [ ] **Step 5: Verify browser detail provenance remains request-owned**

Task 4 added `encrypted_job_id_source` to the browser detail scraper so the research smoke could compile independently. Keep that implementation unchanged here and use the new Task 6 test to prove that fallback requests send the same token twice, `canonical_detail` keeps `jobId_fallback`, and the raw response never gains `encryptJobId`. If this test fails, fix only `_build_request_identity()` or `_build_fetch_result()` and rerun the single test before changing pipeline or repair code.

- [ ] **Step 6: Stop fabricating raw encrypted evidence in the detail pipeline**

Add a focused `_build_persisted_detail_payload()` and make `_build_canonical_payload()` compose listing fallbacks around it:

```python
@staticmethod
def _build_persisted_detail_payload(
    *,
    target: OfferTodayDetailTarget,
    parsed_detail: dict[str, Any],
) -> dict[str, Any]:
    detail_raw = deepcopy(dict(parsed_detail.get("raw_data") or {}))
    return {
        **deepcopy(parsed_detail),
        "job_id": target.identity.job_id,
        "encrypted_job_id": target.identity.encrypted_job_id,
        "encrypted_job_id_source": target.identity.encrypted_job_id_source,
        "canonical_job_url": build_offertoday_job_url(
            target.identity.encrypted_job_id
        ),
        "raw_data": detail_raw,
    }


@staticmethod
def _build_canonical_payload(
    *,
    target: OfferTodayDetailTarget,
    persisted_detail: dict[str, Any],
) -> dict[str, Any]:
    listing_raw = deepcopy(dict(target.listing_payload.get("raw_data") or {}))
    detail_raw = deepcopy(dict(persisted_detail.get("raw_data") or {}))
    return {
        **deepcopy(target.listing_payload),
        **deepcopy(persisted_detail),
        "raw_data": {**listing_raw, **detail_raw},
    }
```

The persisted nested `raw_data` is the exact upstream detail response object. Do not merge listing raw fields into it, do not add normalized aliases or `canonical_job_url`, and do not replace an omitted response `encryptJobId` with the target route. The normalized outer persisted payload is request-owned and always overrides parser-local identity, so an explicit target remains explicit even when the response proves ownership only with matching `jobId`.

The canonical-only mapping payload may merge deep copies of listing and detail raw evidence so existing company/brand identity fallback remains available to `build_offertoday_company_data()`. That composite is never written to `CrawlJobListing.detail_payload`, adds no key that was absent from both upstream mappings, and must still omit `encryptJobId` when both upstream mappings omit it. Add a regression where listing raw supplies `brandId` and detail raw omits it; company identity must still use the listing brand while the stored detail raw remains exactly the response data. The persisted `detail_payload` must not gain listing-only keys such as `listing_only_marker`.

In the success branch, build `persisted_detail_payload` first, pass it to `_build_canonical_payload()`, then build the canonical job. Pass `persisted_detail_payload` as `detail_payload` to `_persist_success()` instead of the response-local parsed mapping. Require `persisted_detail_payload`, `prepared_payload`, and `canonical_job` before persistence. This keeps `CrawlJobListing.detail_payload` free of listing-only fields while canonical mapping, persistence, and repair round trips share the same target-owned route/source.

Add `detail_crawl_job_id` and `encrypted_job_id_source` to `crawl.detail_attempt`, add route/source to `crawl.detail_persisted`, and add source to `_response_identity_hash()`. Extend `CrawlJobRuntime.record_detail_persisted()` with required `encrypted_job_id` and `encrypted_job_id_source` arguments and serialize both as top-level event payload fields:

```python
"source_job_id": str(source_job_id),
"encrypted_job_id": str(encrypted_job_id),
"encrypted_job_id_source": str(encrypted_job_id_source),
```

Pass all three target identity fields from `_persist_success()`. The persisted event is the durable authority used by conservation replay when the staging row itself still contains fallback provenance.

- [ ] **Step 7: Preserve source through repair ownership**

In `OfferTodayJobRepairService`:

- add `crawl_job_listing_repository: CrawlJobListingRepository | None = None` and `crawl_job_repository: CrawlJobRepository | None = None` keyword dependencies, defaulting to their production repositories, so repair can read the same staging history and durable identity observations as crawl runtime;
- add `resolve_detail_identity(job, listing) -> OfferTodayDetailIdentity` and keep `resolve_detail_identifiers()` as a two-string compatibility wrapper;
- set `encrypted_job_id_source` whenever constructing `canonical_detail`;
- include source in non-success JSON error evidence;
- compare the complete typed identity in network result ownership checks; and
- never add `encryptJobId` to a raw payload that did not contain it.

Add a lazy `_identity_authority_index()` cache on the service. On first use with a real DB session, read every OfferToday staging identity row plus every normalized durable observation, resolve each through the shared resolver, and build one global authority index. Cache resolver failures by canonical `source_job_id`; malformed evidence blocks that job, not unrelated repairs, while all valid jobs still participate in reverse-collision detection. Do not query per repair candidate; cache the immutable index and immutable error map for the lifetime of this service instance. Tests that use `db=None` retain row-local compatibility and do not construct repository dependencies.

Import `Mapping` from `collections.abc`, `MappingProxyType` from `types`, both crawl repositories, and the shared authority index symbols. Initialize `_cached_identity_authority_index = None` and `_cached_identity_error_by_job = MappingProxyType({})` in `__init__`.

The cache body is:

```python
def _identity_authority_index(self) -> OfferTodayIdentityAuthorityIndex:
    if self._cached_identity_authority_index is not None:
        return self._cached_identity_authority_index
    if self.db is None:
        raise ValueError("identity authority audit requires an active database session")
    identities: list[OfferTodayDetailIdentity] = []
    identity_error_by_job: dict[str, OfferTodayIdentityError] = {}

    def add_evidence(source_job_id: Any, payload: Mapping[str, Any]) -> None:
        canonical_source_job_id = str(source_job_id or "").strip()
        try:
            identities.append(
                resolve_offertoday_detail_identity(
                    source_job_id=canonical_source_job_id,
                    listing_payload=payload,
                )
            )
        except OfferTodayIdentityError as exc:
            if canonical_source_job_id:
                identity_error_by_job.setdefault(canonical_source_job_id, exc)

    for row in self.crawl_job_listing_repository.list_offertoday_identity_history(
        self.db
    ):
        listing_payload = getattr(row, "listing_payload", None)
        add_evidence(
            getattr(row, "source_job_id", None),
            (
                dict(listing_payload)
                if isinstance(listing_payload, Mapping)
                else {}
            ),
        )
    for observation in (
        self.crawl_job_repository.list_offertoday_listing_identity_observations(
            self.db
        )
    ):
        add_evidence(
            observation.get("source_job_id"),
            observation,
        )
    self._cached_identity_error_by_job = MappingProxyType(
        dict(identity_error_by_job)
    )
    self._cached_identity_authority_index = (
        build_offertoday_identity_authority_index(tuple(identities))
    )
    return self._cached_identity_authority_index
```

Use this resolver implementation:

```python
def resolve_detail_identity(
    self,
    job: Job | Any,
    listing: CrawlJobListing | Any | None = None,
) -> OfferTodayDetailIdentity:
    listing_payload = getattr(listing, "listing_payload", None)
    listing_identity = resolve_offertoday_detail_identity(
        source_job_id=getattr(job, "source_job_id", None),
        listing_payload=(
            dict(listing_payload) if isinstance(listing_payload, Mapping) else {}
        ),
    )
    if self.db is None:
        return listing_identity
    index = self._identity_authority_index()
    identity_error = self._cached_identity_error_by_job.get(
        listing_identity.job_id
    )
    if identity_error is not None:
        raise identity_error
    conflict_reason = index.conflict_reason_by_job.get(listing_identity.job_id)
    if conflict_reason is not None:
        raise OfferTodayIdentityError(
            f"OfferToday repair identity conflict: {conflict_reason}",
            classification=conflict_reason,
        )
    return index.authoritative_identity_by_job.get(
        listing_identity.job_id,
        listing_identity,
    )
```

`_identity_authority_index()` must include all valid jobs before reverse-collision evaluation; filtering observations to the current job would miss one route mapped to two canonical jobs. Legacy observations without the three normalized identity keys are already filtered by the repository method. A structured resolver error in valid-key evidence is retained against its nonblank canonical job and raised before that job's fetch or persistence. Unassignable global evidence with a blank outer `source_job_id` is ignored by this targeting cache, just as the runtime audit ignores it; a selected/current row with a blank canonical ID still fails in the row-local resolver before any fetch.

Use this exact compatibility wrapper:

```python
def resolve_detail_identifiers(
    self,
    job: Job | Any,
    listing: CrawlJobListing | Any | None = None,
) -> tuple[str, str]:
    identity = self.resolve_detail_identity(job, listing)
    return identity.job_id, identity.encrypted_job_id
```

For offline parsed repair, normalize only the outer identity and retain the parser's raw evidence:

```python
def _with_canonical_identity(
    payload: Mapping[str, Any],
    identity: OfferTodayDetailIdentity,
) -> dict[str, Any]:
    return {
        **deepcopy(dict(payload)),
        "job_id": identity.job_id,
        "encrypted_job_id": identity.encrypted_job_id,
        "encrypted_job_id_source": identity.encrypted_job_id_source,
    }
```

Use `_with_canonical_identity()` in all three repair entry points:

- `repair_job()` resolves global authority, normalizes a copied completed `detail_payload` when present (otherwise a copied `listing_payload`), and passes it as `detail_payload_override` to `build_canonical_job_snapshot()`;
- `repair_job_with_parsed_detail()` validates response ownership, normalizes the parsed payload, and persists that normalized copy; and
- `repair_job_with_detail_result()` requires `result.identity == expected_identity`, validates response ownership, normalizes the successful canonical detail again, and persists that copy.

The helper changes only outer normalized fields; a nested `raw_data` mapping remains deep-equal to its input. Add `encrypted_job_id_source` next to the two IDs in non-success JSON evidence.

In `repair_offertoday_jobs.py`, call `resolve_detail_identity()` and pass:

```python
detail_result = await scraper.fetch_job_detail(
    identity.job_id,
    encrypted_job_id=identity.encrypted_job_id,
    encrypted_job_id_source=identity.encrypted_job_id_source,
)
```

- [ ] **Step 8: Update dirty repair CLI tests with hunk isolation**

In the repair fakes in `test_offertoday_browser_runtime.py`, implement `resolve_detail_identity()` and accept `encrypted_job_id_source` in fake scraper signatures. Assert the fallback call contains `jobId_fallback` and the explicit call contains `encryptJobId`. Do not alter or stage the unrelated headed-display tests near the top of that file.

- [ ] **Step 9: Run detail/repair regressions and verify GREEN**

Run:

```powershell
python -m pytest -q `
  backend/tests/test_offertoday_canonical_and_identity.py `
  backend/tests/test_offertoday_detail_pipeline.py `
  backend/tests/test_offertoday_browser_runtime.py `
  backend/tests/test_offertoday_standalone_crawl.py `
  backend/tests/test_crawl_job_runtime.py
```

Expected: all tests pass; job-only requests send the same token in both query parameters, response ownership remains keyed to `jobId`, explicit response mismatch still stops before persistence, and no raw `encryptJobId` is fabricated.

- [ ] **Step 10: Commit Task 6 without unrelated dirty test hunks**

```powershell
git add backend/app/scraper/offertoday_browser_detail_scraper.py backend/app/services/offertoday_detail_pipeline.py backend/app/services/crawl_job_runtime.py backend/app/services/offertoday_job_repair_service.py backend/scripts/repair_offertoday_jobs.py backend/tests/test_offertoday_canonical_and_identity.py backend/tests/test_offertoday_detail_pipeline.py backend/tests/test_offertoday_standalone_crawl.py backend/tests/test_crawl_job_runtime.py
git add -p backend/tests/test_offertoday_browser_runtime.py
git diff --cached -- backend/tests/test_offertoday_browser_runtime.py
git diff --cached --check
git commit -m "fix(offertoday): preserve detail identity provenance"
```

Expected staged browser-runtime test diff: repair fake/service assertions only; no `Path`, `fail_launch_by_channel`, browser fallback, or headed-display test hunks.

---

### Task 7: Separate Baseline Observation From Usable Resolution and Close the Deterministic Gate

**Files:**
- Modify: `backend/app/sources/offertoday/research/contracts.py`
- Modify: `backend/app/repositories/offertoday_research_repository.py`
- Modify: `backend/app/sources/offertoday/research/baseline.py`
- Modify: `backend/app/sources/offertoday/research/conservation.py`
- Modify: `backend/app/sources/offertoday/research/stage_gate.py`
- Test: `backend/tests/test_offertoday_research_baseline.py`
- Test: `backend/tests/test_offertoday_research_conservation.py`
- Test: `backend/tests/test_offertoday_research_stage_gate.py`
- Modify: `backend/tests/fixtures/offertoday_research/duplicate_cross_run/snapshot.json`
- Modify: `docs/superpowers/specs/2026-07-10-offertoday-broad-it-coverage-reliability-research-design.md`
- Modify: `docs/superpowers/specs/2026-07-11-offertoday-plan2-live-census-calibration-design.md`
- Modify: `docs/superpowers/plans/2026-07-11-offertoday-plan2-live-census-calibration.md`
- Modify: `docs/superpowers/specs/2026-07-11-offertoday-jobid-only-identity-compatibility-design.md`

- [ ] **Step 1: Write failing snapshot and baseline tests**

Add to `test_offertoday_research_baseline.py`:

```python
def test_baseline_separates_observed_missing_from_usable_jobid_fallback():
    fallback = StagedListingSnapshot(
        row_id="row-1",
        source_job_id="j-1",
        detail_status="pending",
        published_job_id=None,
        crawl_job_id="crawl-1",
        encrypted_job_id="j-1",
        encrypted_job_id_source="jobId_fallback",
        observed_encrypted_job_id=None,
        identity_error=None,
        identity_error_classification=None,
    )

    snapshot = build_baseline_snapshot(listings=[fallback], jobs=[])

    assert snapshot.missing_encrypted_job_id_rows == 1
    assert snapshot.observed_encrypted_job_id_rows == 0
    assert snapshot.job_id_fallback_rows == 1
    assert snapshot.unusable_identity_rows == 0
    assert snapshot.identity_error_classifications == {}
    assert snapshot.identity_mapping_conflict_ids == ()


def test_baseline_explicit_mapping_promotes_fallback_without_false_conflict():
    rows = [
        StagedListingSnapshot(
            row_id="fallback",
            source_job_id="j-1",
            detail_status="pending",
            published_job_id=None,
            crawl_job_id="crawl-1",
            encrypted_job_id="j-1",
            encrypted_job_id_source="jobId_fallback",
            observed_encrypted_job_id=None,
        ),
        StagedListingSnapshot(
            row_id="explicit",
            source_job_id="j-1",
            detail_status="pending",
            published_job_id=None,
            crawl_job_id="crawl-2",
            encrypted_job_id="enc-1",
            encrypted_job_id_source="encryptJobId",
            observed_encrypted_job_id="enc-1",
        ),
    ]

    snapshot = build_baseline_snapshot(listings=rows, jobs=[])

    assert snapshot.observed_encrypted_job_id_rows == 1
    assert snapshot.job_id_fallback_rows == 1
    assert snapshot.identity_mapping_conflict_ids == ()
```

Add two strict aggregation tests: two different source `encryptJobId` values for one `jobId` must put that job in `identity_mapping_conflict_ids`, and one authoritative route shared by two canonical jobs must put both jobs in the conflict set. Update both existing missing-encrypted expectations: `extract_snapshot_identity_error(...)` and `classify_snapshot_identity_error(...)` return `None` for a valid job-only payload. Remove the old string-membership assertion against that now-`None` error. In `test_structured_identity_errors_distinguish_alias_conflict_from_missing`, retain only `{"encrypted_job_id_alias_conflict": 1}` in `identity_error_classifications`; the fallback row contributes to raw-missing/fallback counts, not identity errors.

- [ ] **Step 2: Write failing repository projection tests**

For a row whose normalized alias equals `jobId` and whose `raw_data` lacks `encryptJobId`, assert the repository snapshot contains:

```python
assert snapshot.encrypted_job_id == "j-1"
assert snapshot.encrypted_job_id_source == "jobId_fallback"
assert snapshot.observed_encrypted_job_id is None
assert snapshot.identity_error is None
assert snapshot.identity_error_classification is None
```

For an explicit row, assert observed and resolved values equal the explicit ID and source `encryptJobId`.

Add a `load_baseline_artifact()` gate regression in `test_offertoday_research_stage_gate.py`. Extend `BASELINE_COUNTS` and `_COUNT_KEYS` with:

```python
"missing_encrypted_job_id_rows": 12,
"observed_encrypted_job_id_rows": 88,
"job_id_fallback_rows": 12,
"unusable_identity_rows": 3,
```

Assert two baselines differing only in one of those counters fail with `count evidence`. This makes the pre-smoke gate concrete without requiring old baseline artifacts to deserialize into the new dataclass.

Update `_snapshot_counts()` in `backend/scripts/offertoday_research_census.py` with the same four keys and the exact `_COUNT_KEYS` order. Add a CLI regression where the current snapshot differs only in `job_id_fallback_rows` and assert the smoke stops before constructing browser/live dependencies.

- [ ] **Step 3: Run baseline tests and verify RED**

Run:

```powershell
python -m pytest -q `
  backend/tests/test_offertoday_research_baseline.py `
  backend/tests/test_offertoday_research_stage_gate.py `
  backend/tests/test_offertoday_research_census_cli.py `
  -k "baseline or snapshot or job_id_fallback_rows"
```

Expected: failures because snapshot/source/observed fields and aggregate counters do not exist, missing encrypted evidence is still classified as unusable, and the baseline/CLI gate does not compare fallback rows.

- [ ] **Step 4: Extend snapshot contracts and read-only projection**

Add to `StagedListingSnapshot`:

```python
encrypted_job_id_source: OfferTodayEncryptedJobIdSource | None = None
observed_encrypted_job_id: str | None = None
```

Add to `BaselineSnapshot`:

```python
observed_encrypted_job_id_rows: int
job_id_fallback_rows: int
unusable_identity_rows: int
```

In `offertoday_research_repository.py`, replace the separate extraction passes with one immutable projection helper:

```python
@dataclass(frozen=True, slots=True)
class _SnapshotIdentityProjection:
    encrypted_job_id: str | None
    encrypted_job_id_source: OfferTodayEncryptedJobIdSource | None
    observed_encrypted_job_id: str | None
    identity_error: str | None
    identity_error_classification: str | None
```

`_project_snapshot_identity(source_job_id, listing_payload)` must first read exact upstream observation from only `listing_payload["encryptJobId"]` and `listing_payload["raw_data"]["encryptJobId"]`, using the shared evidence reader with `required=False`; a normalized `encrypted_job_id` alias is never observation. It then calls `resolve_offertoday_detail_identity()` exactly once. On success, return resolved route/source, observed evidence, and no error. On `OfferTodayIdentityError`, return no resolved route/source, retain any unambiguous observed value, and copy `str(exc)` plus `exc.classification`.

In `list_staged_snapshots()`, compute one projection per row and populate all five snapshot fields from it. Keep `extract_snapshot_identity_error()` and `classify_snapshot_identity_error()` as wrappers over that projection. Rename the old ambiguous `extract_snapshot_encrypted_job_id()` helper to `extract_snapshot_observed_encrypted_job_id()` and make it inspect only the two exact upstream camel-case locations; repository projection, not this observation helper, owns the resolved route. Update its tests accordingly. In the existing normalized-`enc-a`/raw-`enc-b` mismatch fixture, the observation helper now returns the unambiguous upstream value `enc-b` while the full projection still reports `encrypted_job_id_alias_conflict`. A valid fallback must return route `jobId`, source `jobId_fallback`, observation `None`, and no classification; non-string/conflicting aliases retain structured failures.

No repository method may call `add`, `flush`, `commit`, `delete`, `update`, or a runtime transition.

- [ ] **Step 5: Make baseline aggregation provenance-aware**

In `build_baseline_snapshot()`:

- compute `missing_encrypted_job_id_rows` from `observed_encrypted_job_id is None`, excluding rows classified as `invalid_encrypted_job_id_evidence` or `encrypted_job_id_alias_conflict` so malformed/conflicting evidence is not mislabeled as absent;
- compute `observed_encrypted_job_id_rows` from nonblank observed values;
- compute `job_id_fallback_rows` from source `jobId_fallback`;
- compute `unusable_identity_rows` from non-null identity error classification; and
- build one authoritative identity per canonical job with `build_offertoday_identity_authority_index()` before reverse-collision checks.

Add `encrypted_job_id_source_conflict` to `_IDENTITY_EVIDENCE_CONFLICT_CLASSIFICATIONS`; invalid source/evidence classifications count as unusable rows, while genuine alias/source conflicts also contribute their canonical job to `identity_evidence_conflict_ids`.

Construct each valid row identity only when `source_job_id`, resolved route, and exact source are present; pass all valid identities to `build_offertoday_identity_authority_index()`. Merge its conflict keys into `identity_mapping_conflict_ids`; only its successfully selected authoritative identities participate in reverse authority. Thus one fallback plus one explicit row for a job is not a conflict, two distinct explicit values remain a conflict, and one authoritative resolved route mapped to two jobs remains a conflict. Include all new counters in the canonical `data_hash` payload.

Update the existing `_listing()` and `_staged()` test helpers: when a fixture supplies a nonblank `encrypted_job_id` but omits source, infer `jobId_fallback` only when route equals canonical `source_job_id`, otherwise infer `encryptJobId`; for inferred explicit fixtures, also default `observed_encrypted_job_id` to the route. Explicitly override observation to `None` in legacy-normalized and fallback tests. This keeps old fixture intent clear while production snapshots always use repository-projected source.

- [ ] **Step 6: Bind conservation evidence to attempt-owned provenance**

First add a listing replay regression whose one successful page contains two row observations for `j-1`—fallback `("j-1", "j-1", "jobId_fallback")` and explicit `("j-1", "enc-1", "encryptJobId")`—but one authoritative `id_pairs` entry for the explicit triple. Assert `identity_pair_mismatch_page_keys == ()`, no mapping conflict is introduced, and listing conservation remains valid. Tamper only the authoritative source or route and assert the page key becomes a mismatch.

Add a second two-page regression matching Task 3's no-downgrade case: page 1 observes explicit `("j-1", "enc-1", "encryptJobId")`; page 2 observes only fallback `("j-1", "j-1", "jobId_fallback")`, while page 2 `id_pairs` retains the accumulated explicit authority. Replay must remain valid. Changing page 2's declared pair back to fallback must add that page key to `identity_pair_mismatch_page_keys`.

Add conservation regressions with a completed staging row whose local identity is `jobId_fallback` but whose current-run events are:

```python
{
    "sequence_no": 2,
    "event_type": "crawl.detail_attempt",
    "payload": {
        "detail_crawl_job_id": "detail-run",
        "source_job_id": "j-1",
        "encrypted_job_id": "enc-1",
        "encrypted_job_id_source": "encryptJobId",
        "attempt": 1,
        "classification": "success",
    },
},
{
    "sequence_no": 3,
    "event_type": "crawl.detail_persisted",
    "payload": {
        "detail_crawl_job_id": "detail-run",
        "source_job_id": "j-1",
        "encrypted_job_id": "enc-1",
        "encrypted_job_id_source": "encryptJobId",
        "listing_ids": ["row-1"],
        "published_job_id": "job-1",
        "response_identity_hash": "11a10feb7fc09eacee8973361c4f8fdf0ebc1f4e54c6d459b1e7f92957e9add0",
    },
},
```

Assert replay is valid. Then independently tamper attempt route/source and persisted route/source and assert `persisted_evidence_mismatch_ids == ("j-1",)`. Add a fallback case with route `j-1`, source `jobId_fallback`, and hash `7d289db2bd3fbadc01634d078903ac1a6dc0cbd5847be97085c0cc24b47bcd94`.

Run the new conservation regressions before changing the replay implementation:

```powershell
python -m pytest -q backend/tests/test_offertoday_research_conservation.py -k "identity_pair or no_downgrade or attempt_owned or persisted_evidence"
```

Expected: FAIL because replay compares raw two-field page pairs independently, derives persisted route authority from the staging row, and does not validate attempt/persisted source fields.

Replace `_ordered_valid_identity_pairs()` with `_ordered_authoritative_identity_triples()`. Resolve every row/pair record through `resolve_offertoday_listing_identity()`, preserve first-seen canonical job order, and pass identities to `build_offertoday_identity_authority_index()`. Compare ordered triples, not raw two-field sets.

`_find_identity_pair_mismatch_page_keys()` must replay pages in normalized event/insertion order with one accumulated row-authority input list. For each page, first collect canonical job IDs explicitly rejected by that page's `identity_issues` or `identity_conflicts`; do not add those rows to expected accepted-pair authority. This preserves replay of legacy pages that explicitly classified `missing_encrypted_job_id` before this correction, while new fallback pages contain no such issue. Build a candidate authority list from the previously committed inputs plus the remaining page rows, then derive expected triples only for non-rejected canonical jobs observed on that page. Resolve the declared `id_pairs` independently and compare them with those expected triples. Commit the candidate list as accumulated authority only when the page has no identity issue or conflict, matching the runner's page-atomic authority update; a dirty page may still expose its valid page pairs but cannot influence later pages. This makes a prior committed explicit observation remain authoritative on a later fallback-only page while still detecting a tampered downgrade. Do not compare each page's rows in isolation.

Reuse the same shared index inside `_identity_evidence()` so fallback plus one explicit route is not a forward conflict; only multiple explicit routes and authoritative reverse collisions remain deferred. Legacy explicit fixtures without a source continue to infer `encryptJobId` when route differs from `jobId`.

Update `_expected_response_identity_hash()` in `research/conservation.py` to accept `encrypted_job_id_source` and hash:

```python
{
    "encrypted_job_id": encrypted_job_id,
    "encrypted_job_id_source": encrypted_job_id_source,
    "job_id": source_job_id,
}
```

Add `detail_crawl_job_id` to every new `crawl.detail_attempt` payload. Then add `_successful_attempt_identity_by_source_id(events, detail_crawl_job_id, eligible_ids)`. Iterate normalized events in sequence order; accept only `crawl.detail_attempt` payloads with `classification == "success"`, a matching `detail_crawl_job_id`, exact eligible source IDs, a nonblank route, and one of the two exact source literals. Require `jobId_fallback` routes to equal the canonical source ID. Multiple distinct successful triples for the same source ID make that ID unusable.

Change `_expected_persisted_evidence_by_source_id()` to receive this attempt-owned mapping. Completed row state still proves exact listing IDs, published job, detail payload presence, and current run ownership; it no longer supplies route authority. For each completed source ID, use the unique successful-attempt triple to compute the expected hash. `_validate_persisted_events()` must additionally require the persisted event's `encrypted_job_id` and `encrypted_job_id_source` to equal that triple. A missing, invalid, ambiguous, or mismatched attempt/persisted triple adds the source ID to `persisted_evidence_mismatch_ids`.

Update the fixed `duplicate_cross_run` fixture and direct conservation helpers so their success attempt and persisted event include route/source. The fixture's explicit three-field hash becomes `11a10feb7fc09eacee8973361c4f8fdf0ebc1f4e54c6d459b1e7f92957e9add0`. Keep listing/detail conservation equations and no-write assertions unchanged.

- [ ] **Step 7: Run baseline and conservation tests and verify GREEN**

Run:

```powershell
python -m pytest -q backend/tests/test_offertoday_research_baseline.py backend/tests/test_offertoday_research_conservation.py backend/tests/test_offertoday_research_stage_gate.py
```

Expected: all tests pass with deterministic hashes; raw-missing fallback rows are usable, true conflicts remain visible, and conservation differences remain zero.

- [ ] **Step 8: Commit baseline and conservation code**

```powershell
git add backend/app/sources/offertoday/research/contracts.py backend/app/repositories/offertoday_research_repository.py backend/app/sources/offertoday/research/baseline.py backend/app/sources/offertoday/research/conservation.py backend/app/sources/offertoday/research/stage_gate.py
git add -f backend/tests/test_offertoday_research_baseline.py backend/tests/test_offertoday_research_conservation.py backend/tests/test_offertoday_research_stage_gate.py backend/tests/fixtures/offertoday_research/duplicate_cross_run/snapshot.json
git diff --cached --check
git commit -m "fix(offertoday): separate observed and resolved identities"
```

- [ ] **Step 9: Amend the approved Plan 2 documents**

Make these exact semantic amendments:

1. In the broad research design, replace the two-required-ID canonical rule with `jobId` canonical plus provenance-aware resolved route; replace ordered `(jobId, encryptJobId)` evidence with `(jobId, resolved_route_id, encrypted_job_id_source)` plus an independent observed-missing counter.
2. In the live census design, state that the failed run `fab9d8e1-4c12-4170-a539-c0a6cdbbca93` invalidated only the two-raw-ID assumption; retain its artifact/hash and all request/no-write gates.
3. In the live census implementation plan, mark the original Task 8 attempt as failed evidence, add a deterministic correction gate pointing to this plan, and require separate user approval for exactly one replacement smoke. Do not mark Task 8 accepted and do not unlock Task 9.
4. In the compatibility design, set status to `Approved for implementation` and record that the implementation plan is `docs/superpowers/plans/2026-07-11-offertoday-jobid-only-identity-compatibility.md`.

- [ ] **Step 10: Commit documentation amendments**

```powershell
git add -f docs/superpowers/specs/2026-07-10-offertoday-broad-it-coverage-reliability-research-design.md docs/superpowers/specs/2026-07-11-offertoday-plan2-live-census-calibration-design.md docs/superpowers/plans/2026-07-11-offertoday-plan2-live-census-calibration.md docs/superpowers/specs/2026-07-11-offertoday-jobid-only-identity-compatibility-design.md
git diff --cached --check
git commit -m "docs(offertoday): amend plan 2 identity contract"
```

- [ ] **Step 11: Run the complete smoke-focused selector**

```powershell
python -m pytest -q `
  backend/tests/test_offertoday_research_stage_gate.py `
  backend/tests/test_offertoday_research_smoke.py `
  backend/tests/test_offertoday_research_live_service.py `
  backend/tests/test_offertoday_research_census_cli.py `
  backend/tests/test_offertoday_research_observation_service.py `
  backend/tests/test_offertoday_research_staging_service.py `
  backend/tests/test_offertoday_research_artifacts.py `
  backend/tests/test_offertoday_research_cli.py `
  backend/tests/test_offertoday_listing_runner.py `
  backend/tests/test_offertoday_browser_runtime.py `
  backend/tests/test_offertoday_canonical_and_identity.py
```

Expected: all tests pass. The pre-correction reference was `393 passed`; record the new exact count.

- [ ] **Step 12: Run the complete Plan 1 regression selector**

```powershell
python -m pytest -q `
  backend/tests/test_offertoday_response_policy.py `
  backend/tests/test_offertoday_search_space.py `
  backend/tests/test_offertoday_listing_runner.py `
  backend/tests/test_offertoday_research_observation_service.py `
  backend/tests/test_offertoday_research_artifacts.py `
  backend/tests/test_offertoday_research_baseline.py `
  backend/tests/test_offertoday_research_conservation.py `
  backend/tests/test_offertoday_research_cli.py `
  backend/tests/test_offertoday_detail_pipeline.py `
  backend/tests/test_offertoday_standalone_crawl.py `
  backend/tests/test_offertoday_browser_runtime.py `
  backend/tests/test_offertoday_canonical_and_identity.py `
  backend/tests/test_crawl_job_runtime.py `
  backend/tests/test_startup_recovery_service.py `
  backend/tests/test_offertoday_coverage_audit.py
```

Expected: all tests pass. The pre-correction reference was `581 passed`; record the new exact count.

- [ ] **Step 13: Compile and lint every changed Python path**

```powershell
python -m compileall -q `
  backend/app/sources/contracts.py `
  backend/app/sources/offertoday `
  backend/app/repositories/crawl_job_repository.py `
  backend/app/repositories/offertoday_research_repository.py `
  backend/app/services/crawl_job_runtime.py `
  backend/app/services/offertoday_detail_pipeline.py `
  backend/app/services/offertoday_job_repair_service.py `
  backend/app/services/offertoday_research_live_service.py `
  backend/app/services/offertoday_research_observation_service.py `
  backend/app/scraper/offertoday_browser_runtime.py `
  backend/app/scraper/offertoday_browser_detail_scraper.py `
  backend/scripts/offertoday_standalone_crawl.py `
  backend/scripts/offertoday_research_census.py `
  backend/scripts/repair_offertoday_jobs.py

python -m ruff check `
  backend/app/sources/contracts.py `
  backend/app/sources/offertoday/detail_identity.py `
  backend/app/sources/offertoday/parsers.py `
  backend/app/sources/offertoday/listing_runner.py `
  backend/app/sources/offertoday/research/contracts.py `
  backend/app/sources/offertoday/research/baseline.py `
  backend/app/sources/offertoday/research/conservation.py `
  backend/app/sources/offertoday/research/live_contracts.py `
  backend/app/sources/offertoday/research/smoke.py `
  backend/app/sources/offertoday/research/stage_gate.py `
  backend/app/repositories/crawl_job_repository.py `
  backend/app/repositories/offertoday_research_repository.py `
  backend/app/services/crawl_job_runtime.py `
  backend/app/services/offertoday_detail_pipeline.py `
  backend/app/services/offertoday_job_repair_service.py `
  backend/app/services/offertoday_research_live_service.py `
  backend/app/services/offertoday_research_observation_service.py `
  backend/app/scraper/offertoday_browser_runtime.py `
  backend/app/scraper/offertoday_browser_detail_scraper.py `
  backend/scripts/offertoday_standalone_crawl.py `
  backend/scripts/offertoday_research_census.py `
  backend/scripts/repair_offertoday_jobs.py
```

Expected: both commands exit `0`. Do not broaden Ruff cleanup into unrelated files.

- [ ] **Step 14: Prove scope, offline behavior, and unchanged product data**

```powershell
python backend/scripts/offertoday_research_census.py verify-run --artifact backend/runtime/offertoday-research/fab9d8e1-4c12-4170-a539-c0a6cdbbca93
git diff --check refs/codex/offertoday-plan2-base..HEAD
git diff --name-only refs/codex/offertoday-plan2-base..HEAD -- backend/alembic backend/app/models docker-compose.yml docker-compose.dev.yml .env .env.example
git status --short
```

Expected: offline verifier exits `0`; forbidden-range command has no output; the immutable artifact is unchanged; no Task 9-15 source file exists; unrelated dirty files remain present.

- [ ] **Step 15: Run two-stage review and fix every material issue**

First review the implementation against every acceptance criterion in `2026-07-11-offertoday-jobid-only-identity-compatibility-design.md`. Then review code quality, with explicit checks for:

- raw payload non-mutation and no fabricated `raw_data.encryptJobId`;
- exact source literals and type consistency across every dataclass/event;
- explicit-over-fallback promotion without weakening multi-explicit/reverse conflict handling;
- canonical detail response ownership before parse/persistence;
- unchanged auth/WAF/transport/pacing/retry/batch-stop and terminal `2520` classification behavior;
- smoke request/no-write/partial-artifact gates unchanged;
- strict offline replay of fallback decisions;
- no migration, model, Compose, environment, or Task 9-15 change; and
- no unrelated dirty hunk staged or committed.

Fix every Critical/Important finding, rerun the affected focused tests, and repeat the relevant review until no such finding remains.

- [ ] **Step 16: Stop and request replacement-smoke authorization**

Report:

- exact implementation and document commit IDs;
- exact focused and Plan 1 pass counts;
- compile/Ruff/offline replay results;
- forbidden-range and dirty-worktree results;
- confirmation that no OfferToday request occurred; and
- the proposed one replacement Task 8 smoke budget: at most two ordered listing requests, at most 20 detail requests, no retries, same browser, zero product writes.

Do not capture replacement baselines or execute the replacement smoke in this task. Wait for explicit user authorization.

---

## Verification Matrix

| Requirement | Deterministic evidence |
|---|---|
| Search `jobId`-only row is usable | Saved search fixture through resolver, parser, runner, staging, and smoke cohort |
| Browse `jobId`-only row is usable | Saved browse fixture through the same shared path |
| Raw evidence is truthful | Deep-equality tests and absence of `raw_data.encryptJobId` |
| Missing observation differs from unusable identity | Page fallback/raw-missing counters and baseline snapshot counters |
| Explicit ID remains preferred | Resolver, listing promotion, runtime history, and canonical URL tests |
| Multiple explicit IDs remain conflicts | Listing and historical forward-conflict tests |
| Authoritative reverse collision remains conflict | Listing and runtime reverse-collision tests |
| Detail ownership remains canonical | Response `jobId` and explicit `encryptJobId` mismatch tests before persistence |
| Historical rows need no rewrite | Deep-equality runtime target tests; no migration/model diff |
| Repair preserves provenance | Offline and typed network result round-trip tests |
| Artifact provenance is replayable | Target source/hash, page fallback count, tamper tests, offline `verify-run` |
| Smoke remains bounded and no-write | Existing stage gate, lifecycle, no-op sink, DB hash, and request budget tests |
| Both failed Task 8 artifacts remain immutable and unaccepted | Exact artifact manifest hashes before/after offline verification; neither run satisfies Task 8 |
| Later Plan 2 stages remain locked | Documentation amendment, source-range review, and explicit stop before live work |

## Commit Sequence

1. `fix(offertoday): resolve jobId-only identities`
2. `fix(offertoday): normalize fallback identity provenance`
3. `fix(offertoday): accept provenance-aware listing identities`
4. `fix(offertoday): preserve smoke identity provenance`
5. `fix(offertoday): promote fallback detail authority`
6. `fix(offertoday): preserve detail identity provenance`
7. `fix(offertoday): separate observed and resolved identities`
8. `docs(offertoday): amend plan 2 identity contract`

Do not squash these checkpoints during implementation. Do not commit runtime artifacts.
