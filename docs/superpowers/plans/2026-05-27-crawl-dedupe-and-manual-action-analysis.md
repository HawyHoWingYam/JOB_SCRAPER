# Crawl Dedupe And Manual Action Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent duplicate CTgoodjobs and JobsDB listing IDs from being re-emitted within a crawl while adding a manual-action screenshot analysis flow for human-verification blocks.

**Architecture:** Keep database uniqueness as the final guard, but move crawl-wide dedupe into the spiders and resume flow so listing IDs are filtered before staging and detail work. Extend the existing headed manual-action helper with a screenshot endpoint and a small backend analysis API that can call the existing AI runtime with image-aware prompts, then surface the analysis from the progress UI.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy, Playwright, React 19, Vite, pytest, Vitest

---

### Task 1: Crawl-Wide Listing Dedupe

**Files:**
- Modify: `backend/crawler/job_crawler/spiders/jobsdb_headed_spider.py`
- Modify: `backend/crawler/job_crawler/spiders/ctgoodjobs_headed_spider.py`
- Modify: `backend/crawler/job_crawler/spiders/jobsdb_spider.py`
- Modify: `backend/crawler/job_crawler/spiders/ctgoodjobs_spider.py`
- Modify: `backend/app/repositories/crawl_job_listing_repository.py`
- Test: `backend/tests/test_jobsdb_headed_spider.py`
- Test: `backend/tests/test_ctgoodjobs_headed_spider.py`

- [ ] **Step 1: Write failing spider tests for cross-category dedupe**

```python
@pytest.mark.asyncio
async def test_jobsdb_headed_spider_dedupes_ids_across_categories(monkeypatch):
    ...
    assert [item["source_job_id"] for item in emitted_listings] == ["123456", "234567", "345678"]


@pytest.mark.asyncio
async def test_ctgoodjobs_headed_spider_dedupes_ids_across_categories(monkeypatch):
    ...
    assert [item["source_job_id"] for item in emitted_listings] == ["10108385", "10108386", "10108387"]
```

- [ ] **Step 2: Run the targeted spider tests and confirm they fail for duplicate emission**

Run: `python -m pytest backend/tests/test_jobsdb_headed_spider.py backend/tests/test_ctgoodjobs_headed_spider.py -q`

Expected: FAIL with duplicate `source_job_id` values still being emitted when the same listing appears in multiple categories.

- [ ] **Step 3: Implement crawl-wide seen-ID handling with resume-safe merging**

```python
seen_job_ids: set[str] = set(seeded_seen_job_ids)
for category_index, category_id in enumerate(category_ids):
    ...
    for job in jobs:
        job_id = str(job.get("external_id") or "").strip()
        if not job_id or job_id in seen_job_ids:
            continue
        seen_job_ids.add(job_id)
        emit_listing_emitted(...)
```

- [ ] **Step 4: Re-run the spider tests and confirm green**

Run: `python -m pytest backend/tests/test_jobsdb_headed_spider.py backend/tests/test_ctgoodjobs_headed_spider.py -q`

Expected: PASS with no duplicate emitted listing IDs across categories.

### Task 2: Screenshot Capture And Manual-Action Analysis API

**Files:**
- Modify: `backend/app/host_manual_action_helper.py`
- Modify: `backend/app/ai/llm_client.py`
- Modify: `backend/app/api/ai.py`
- Modify: `backend/app/services/runtime_capabilities_service.py`
- Test: `backend/tests/test_headed_manual_action_helper.py`
- Test: `backend/tests/test_ai_enrichment_dispatch_api.py`

- [ ] **Step 1: Write failing helper and API tests for screenshot capture and analysis**

```python
def test_capture_screenshot_endpoint_returns_saved_artifact_metadata():
    response = client.post("/manual-actions/capture-screenshot", json={"crawl_job_id": crawl_job_id})
    assert response.status_code == 200
    assert response.json()["content_type"] == "image/png"


def test_manual_action_analysis_route_returns_structured_guidance():
    response = client.post("/api/v1/ai/manual-action-analyze", json=payload)
    assert response.status_code == 200
    assert response.json()["challenge_type"] == "captcha"
```

- [ ] **Step 2: Run the targeted backend tests and confirm they fail for missing endpoints/support**

Run: `python -m pytest backend/tests/test_headed_manual_action_helper.py backend/tests/test_ai_enrichment_dispatch_api.py -q`

Expected: FAIL because screenshot capture and manual-action analysis routes do not exist yet.

- [ ] **Step 3: Add screenshot capture to the helper and image-aware manual-action analysis endpoint**

```python
@app.post("/manual-actions/capture-screenshot")
async def capture_screenshot(request: ManualActionRequest):
    ...
    screenshot_bytes = capture_manual_action_screenshot(...)
    return {
        "filename": artifact_name,
        "content_type": "image/png",
        "image_base64": base64.b64encode(screenshot_bytes).decode("ascii"),
    }
```

```python
@router.post("/manual-action-analyze")
async def analyze_manual_action(request: ManualActionAnalysisRequest):
    result = await llm_client.generate_json(
        prompt=prompt,
        image_base64=request.image_base64,
        image_media_type=request.content_type,
    )
    return result
```

- [ ] **Step 4: Re-run the backend tests and confirm green**

Run: `python -m pytest backend/tests/test_headed_manual_action_helper.py backend/tests/test_ai_enrichment_dispatch_api.py -q`

Expected: PASS with screenshot metadata returned and structured analysis JSON produced.

### Task 3: Progress Panel Capture-And-Analyze UI

**Files:**
- Modify: `frontend/src/components/scraper/ScheduleManager.jsx`
- Modify: `frontend/src/components/scraper/ScrapeProgressPanel.jsx`
- Modify: `frontend/src/components/scraper/ScrapeProgressPanel.test.jsx`

- [ ] **Step 1: Write failing UI tests for the capture-and-analyze action**

```jsx
it('captures a manual-action screenshot and shows returned analysis guidance', async () => {
  ...
  fireEvent.click(screen.getByRole('button', { name: /capture and analyze/i }));
  expect(await screen.findByText(/challenge type: captcha/i)).toBeInTheDocument();
})
```

- [ ] **Step 2: Run the targeted frontend test and confirm it fails**

Run: `npm test -- --run frontend/src/components/scraper/ScrapeProgressPanel.test.jsx`

Expected: FAIL because the capture-and-analyze action and analysis output are not rendered yet.

- [ ] **Step 3: Implement the progress-panel action and response rendering**

```jsx
const handleCaptureAndAnalyze = async () => {
  const screenshot = await captureManualActionScreenshot(crawl_job_id);
  const analysis = await analyzeManualActionScreenshot({
    crawl_job_id,
    ...screenshot,
  });
  setManualActionAnalysis(analysis);
};
```

- [ ] **Step 4: Re-run the frontend test and confirm green**

Run: `npm test -- --run frontend/src/components/scraper/ScrapeProgressPanel.test.jsx`

Expected: PASS with the analysis action visible and structured guidance displayed.

### Task 4: Full Verification

**Files:**
- Modify: `backend/tests/test_jobsdb_headed_spider.py`
- Modify: `backend/tests/test_ctgoodjobs_headed_spider.py`
- Modify: `backend/tests/test_headed_manual_action_helper.py`
- Modify: `backend/tests/test_ai_enrichment_dispatch_api.py`
- Modify: `frontend/src/components/scraper/ScrapeProgressPanel.test.jsx`

- [ ] **Step 1: Run the full targeted backend verification suite**

Run: `python -m pytest backend/tests/test_jobsdb_headed_spider.py backend/tests/test_ctgoodjobs_headed_spider.py backend/tests/test_headed_manual_action_helper.py backend/tests/test_ai_enrichment_dispatch_api.py -q`

Expected: PASS with all targeted backend behaviors green.

- [ ] **Step 2: Run the targeted frontend verification suite**

Run: `npm test -- --run frontend/src/components/scraper/ScrapeProgressPanel.test.jsx frontend/src/components/scraper/ScheduleManager.test.jsx`

Expected: PASS with manual-action browser helpers and capture-analysis flow green.

- [ ] **Step 3: Review the final diff before closing the task**

Run: `git diff -- backend/crawler/job_crawler/spiders backend/app/host_manual_action_helper.py backend/app/api/ai.py backend/app/ai/llm_client.py frontend/src/components/scraper`

Expected: Only dedupe and manual-action analysis changes are present in the touched files.
