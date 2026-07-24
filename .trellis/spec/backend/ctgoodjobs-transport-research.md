# CTGoodJobs Transport Research Contracts

## Scenario: Bounded browserless/headless viability comparison

### 1. Scope / Trigger

Use this contract when running, extending, or consuming the research-only
CTGoodJobs transport comparison in
`backend/scripts/ctgoodjobs_headless_probe.py`.

The probe compares plain HTTP, fresh Playwright headless, stateful Playwright
headless, and a headed baseline. Production changed to headless-first only after
separate bounded listing, detail, and catalog canaries returned parser-valid
content. Research results never authorize an automatic transport fallback, and
a successful live window does not prove that an IP/session will never encounter
WAF.

Runtime evidence lives under
`backend/runtime/ctgoodjobs-headless-research/<run-id>/`, remains ignored, and
must never be committed.

### 2. Signatures

```text
python backend/scripts/ctgoodjobs_headless_probe.py --plan
python backend/scripts/ctgoodjobs_headless_probe.py \
  --category-count 3 --listing-repetitions 3 \
  --detail-count 10 --detail-repetitions 2 \
  --browser-sessions 2 --max-attempts 1 \
  --confirm-live-research
python backend/scripts/ctgoodjobs_headless_probe.py verify \
  --artifact <artifact-dir>
```

```python
calculate_request_budget(
    plan: ProbePlan,
    *,
    selected_arms: Sequence[str] = DEFAULT_ARMS,
    max_attempts: int = 1,
) -> dict[str, int]

classify_page_observation(...) -> dict[str, Any]
export_probe_artifact(...) -> Path
verify_probe_artifact(artifact_dir: Path) -> ArtifactVerificationResult
assess_operational_viability(observations, *, arm: str) -> dict[str, Any]
resolve_probe_exit_code(...) -> int
```

### 3. Contracts

#### Explicit live gate and budget

- `--plan` constructs no HTTP or browser dependency.
- Live work requires `--confirm-live-research`; omission is argparse exit `2`.
- The plan prints both the observation total and
  `request_attempt_ceiling = observations * max_attempts`. Operator approval is
  based on the request-attempt ceiling, not only the observation count.
- Default full evidence is 4 arms x (3 categories x 3 listing repetitions + 10
  details x 2 repetitions) = 116 observations and, with one attempt, 116
  maximum requests.
- A positive verification observation stops the whole run. The arms share one
  network, so continuing a different arm after a confirmed block is forbidden.

#### Transport ownership

- `plain-http` uses a fresh bounded HTTP client and no browser state.
- `fresh-headless` creates a new headless browser/context per observation.
- `stateful-headless` reuses two or more temporary persistent contexts.
- `headed-baseline` uses the same persistent-context shape with visibility
  enabled.
- Transport labels are research facts. The production CTGoodJobs CLI now keeps
  `--crawl-mode headless` and defaults to it, but production smoke is not a
  substitute for the probe's frozen multi-arm evidence threshold.

#### Classification order

1. Positive AWS WAF header or shared access evidence ->
   `verification_block`, `hard_stop=true`.
2. Detail-only explicit HTTP 404/410 or top-level unavailable evidence ->
   `terminal_unavailable`.
3. Other non-success status -> `transport_failure`.
4. Production category/detail parser validation -> `valid_content` or
   `structural_invalid`.

HTTP 200 or successful navigation alone is never `valid_content`. A valid
listing has parser-produced Job IDs. A valid detail has job ID, title, company
identity, and description. Terminal-unavailable is classified transport success
but is excluded from valid-detail yield.

#### Durable evidence

`manifest.json` owns schema version, run ID, captured time, completion/failure,
selected arms, frozen plan, observation and request-attempt budgets, browser
engine/channel, cooldown/timeout/attempt policy, aggregate decisions, and the
SHA-256 of `observations.jsonl`.

Every JSONL observation owns:

```text
schema_version, run_id, ordinal, captured_at
arm, phase, session_label, repetition, sample_label
source_url, final_url, status_code, attempts, elapsed_ms
body_sha256, classification, failure_reason, hard_stop, parser_result
```

URLs retain only approved CTGoodJobs HTTPS origin/path. Unknown schema versions,
non-contiguous ordinals, run-ID mismatch, symlinks, unexpected files/fields,
unsafe URLs, malformed hashes, or a file-hash mismatch fail verification.

Never persist HTML, response JSON, cookies, headers, storage state, browser
profile paths, CDP endpoints, proxy credentials, tokens, or raw exception text.
Transport exceptions collapse to a bounded failure reason.

#### Viability replay and interpretation

An arm is `operationally_viable` only when all of these hold:

- three listing samples each have repetitions 1, 2, and 3 as `valid_content`;
- ten detail samples each have repetitions 1 and 2 as `valid_content`;
- browser arms show at least two independent valid session labels; and
- verification, transport-failure, and structural-invalid counts are zero.

Smaller, partial, or failed comparisons remain conditional. A successful window
does not remove the existing operator-driven WAF recovery boundary. Do not
automatically cascade from HTTP to browser after positive access evidence.

The rollout canary recorded parser-valid fresh/stateful headless listing and
detail results plus a passing published-catalog adapter smoke. The smaller
artifact remains conditional (verification exit `3`) because it is below this
research spec's full viability threshold; that exit does not invalidate the
separate bounded production rollout gate.

### 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| `--plan`, including `--max-attempts 3` | No live dependency; print observations and 3x request-attempt ceiling |
| Live command lacks confirmation | Argparse exit `2`; zero requests |
| URL is not approved CTGoodJobs HTTPS origin/path | Reject before live/export |
| AWS `x-amzn-waf-action: captcha` | `verification_block`, preserve prefix, stop all later requests, exit `4` |
| Shared positive IP/WAF evidence | Same hard-stop behavior; never parse as a job page |
| HTTP 404/410 detail without WAF evidence | `terminal_unavailable`; exclude from valid-detail yield |
| HTTP 503 without WAF evidence | `transport_failure`; never IP/manual-action guess |
| HTTP 200 with missing listing IDs/detail identity | `structural_invalid`; never valid navigation |
| Complete threshold with zero failures | Every qualifying arm `operationally_viable`; exit `0` |
| Valid smaller/partial/conditional evidence | Preserve artifact; exit `3` |
| Internal probe failure or artifact verification failure | Preserve bounded evidence when possible; exit `5` |
| Unknown version, hash mismatch, extra file/field, secret field | Verification fails closed; exit `5` |

### 5. Good / Base / Bad Cases

- **Good:** All four arms return parser-valid listing and detail content under the
  116-observation threshold. The artifact verifies, and the report may say that
  a visible browser is not routinely required for that accessible window.
- **Base:** A 1-category/1-detail smoke succeeds except for one fresh-headless
  HTTP 503. Preserve the valid artifact and report technical/conditional
  viability; do not promote it to routine operation.
- **Good hard stop:** The first headed request receives AWS CAPTCHA. Record one
  sanitized observation, send no later request, return `4`, and ask the operator
  to recover the network/session.
- **Bad:** Continue plain HTTP or headless arms after a headed CAPTCHA to see
  whether another transport bypasses it. This widens traffic after positive
  access evidence and confounds network with visibility.
- **Bad:** Store HTML or cookies so a reviewer can inspect the challenge. Keep
  only bounded classification, parser counters, timing, sanitized URL, and hash.
- **Bad:** Call the run operationally viable because navigation returned 200, or
  because one page succeeded once.

### 6. Tests Required

`backend/tests/test_ctgoodjobs_headless_probe.py` must cover:

- exact observation and request-attempt budget ceilings;
- approved-host URL sanitization and secret/extra-field rejection;
- parser-valid listing/detail observations without raw bodies;
- WAF precedence, including AWS CAPTCHA headers;
- terminal-unavailable versus structural-invalid behavior;
- artifact round trip, hash tamper, unknown version, and valid hard-stop prefix;
- full threshold for every arm and conditional smaller/blocked evidence;
- distinct exits `0/2/3/4/5`; and
- offline `--plan` plus explicit live confirmation.

Run:

```text
pytest backend/tests/test_ctgoodjobs_headless_probe.py -q
pytest backend/tests -q
python -m ruff check \
  backend/scripts/ctgoodjobs_headless_probe.py \
  backend/tests/test_ctgoodjobs_headless_probe.py
python -m compileall -q backend/app backend/scripts backend/tests
```

For each live artifact, run `verify` and scan durable fields for forbidden
secrets before citing it in a report. Live success is never a deterministic unit
test requirement.

### 7. Wrong vs Correct

#### Wrong

```python
if response.status_code == 200:
    accepted = True
if headless_failed:
    retry_with_headed_browser()
```

This accepts structurally invalid pages and automatically adds traffic without
checking whether the network is already blocked.

#### Correct

```python
observation = classify_page_observation(
    status_code=response.status_code,
    waf_action=response.headers.get("x-amzn-waf-action"),
    html=html,
    phase=phase,
    # bounded identity/session fields omitted
)
events.append(observation)
if observation["hard_stop"]:
    export_verified_prefix_and_stop()

decision = assess_operational_viability(events, arm=arm)
```

The shared access boundary runs first, production parsers prove content, and the
fixed replay threshold owns the verdict.
