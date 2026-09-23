import { expect, test } from "@playwright/test";

test("configures and executes one bounded Jev run against the local provider", async ({
  page,
  request,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Settings" }).click();
  await expect(page.getByRole("heading", { name: "Jev System One" })).toBeVisible();

  await page.getByLabel("Enable Jev", { exact: true }).check();
  await page
    .getByLabel("Jev endpoint")
    .fill("http://127.0.0.1:18001/fake/systemone");
  await page.getByLabel("Jev API key", { exact: true }).fill("e2e-local-secret");
  await page.getByText("Advanced Jev controls").click();
  await page
    .getByLabel("Jev maximum request reservation microdollars")
    .fill("50000");
  await page.getByRole("button", { name: "Save settings" }).click();
  await expect(page.getByRole("alert")).toContainText("AI runtime settings saved");

  await page.reload();
  await expect(page.getByLabel("Enable Jev", { exact: true })).toBeChecked();
  await expect(page.getByText(/e2e-\.\.\.cret/)).toBeVisible();
  await expect(page.getByText("Remaining: USD 10.00")).toBeVisible();

  await page.getByRole("button", { name: "Run one Jev smoke test" }).click();
  const history = page.getByLabel("Jev run history");
  await expect(history).toContainText("configuration_smoke_test");
  await expect(history).toContainText("completed · 1/1 · 11 tokens");
  await expect(history).toContainText("Frozen model: jev-latest");
  await expect(history).toContainText(
    "Allowance USD 10.00 · spent 0.05 · reserved 0.00 · remaining 9.95",
  );
  await expect(page.getByText("Remaining: USD 9.95")).toBeVisible();

  const providerAudit = await request.get(
    "http://127.0.0.1:18001/fake/requests",
  );
  expect(providerAudit.ok()).toBeTruthy();
  expect(await providerAudit.json()).toEqual({
    count: 1,
    requests: [
      {
        path: "/fake/systemone",
        has_bearer: true,
        model: "jev-latest",
        question_names: ["requires_python"],
      },
    ],
  });

  await page.getByLabel("Jev model").fill("jev-next");
  await page.getByRole("button", { name: "Save settings" }).click();
  await expect(history).toContainText("Frozen model: jev-latest");
});

test("runs Jev Skill maintenance in the web UI and aggregate-approves a new Skill", async ({
  page,
  request,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Classification" }).click();
  await expect(page.getByRole("heading", { name: "Skills to review" })).toBeVisible();
  await expect(page.getByText("NovelDB", { exact: true }).first()).toBeVisible();
  await expect(page.getByText(/1 exceptions · starts at 1/)).toBeVisible();

  await page.getByRole("button", { name: "Run maintenance now" }).click();
  await expect(page.getByText(/Latest: ready_for_approval/)).toBeVisible();
  await expect(page.getByText(/receipt e2e-request-2/)).toBeVisible();
  await expect(page.getByText(/cost USD 0.00005/)).toBeVisible();
  const diff = page.getByLabel("Proposed Skill changes");
  await expect(diff).toContainText("NovelDB");
  await expect(diff).toContainText("Create under backend.databases");
  await expect(diff).toContainText("confidence 99%");
  await expect(
    page.getByRole("button", { name: "Approve proposed Skills" }),
  ).toBeVisible();

  await page.getByRole("button", { name: "Approve proposed Skills" }).click();
  await expect(page.getByText(/Latest: applied/)).toBeVisible();
  await expect(page.getByText("There are no Skills to review.")).toBeVisible();

  const treeResponse = await request.get(
    "http://127.0.0.1:18001/api/job-intelligence/skills/tree",
  );
  expect(treeResponse.ok()).toBeTruthy();
  const tree = await treeResponse.json();
  expect(tree.nodes.some((node) => node.code === "backend.databases.noveldb")).toBeTruthy();

  const providerAudit = await request.get(
    "http://127.0.0.1:18001/fake/requests",
  );
  expect((await providerAudit.json()).count).toBe(2);
});

test("previews and executes a bounded historical Jev Skill backfill from the UI", async ({
  page,
  request,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Classification" }).click();
  const limit = page.getByLabel("Jev Skill backfill limit");
  await limit.fill("1");
  await page.getByRole("button", { name: "Preview backfill" }).click();
  await expect(page.getByText(/1 eligible .* 1 selected/)).toBeVisible();
  await expect(page.getByRole("status")).toContainText("free database read");
  await page.getByRole("button", { name: "Start bounded backfill" }).click();
  const status = page.getByRole("status");
  await expect(status).toContainText("Queued 1 Jobs in run");
  const runId = (await status.textContent()).match(/run ([^.]+)/)?.[1];
  expect(runId).toBeTruthy();

  const execution = await request.post(
    `http://127.0.0.1:18001/fake/execute-backfill/${runId}`,
  );
  expect(execution.ok()).toBeTruthy();
  expect(await execution.json()).toEqual(expect.objectContaining({
    status: "completed",
    completed_items: 1,
    failed_items: 0,
  }));
  const state = await request.get(
    "http://127.0.0.1:18001/fake/backfill-state/20000000-0000-0000-0000-000000000001",
  );
  expect(await state.json()).toEqual(expect.objectContaining({
    classification_status: "answered",
    skills: ["backend.databases.noveldb"],
  }));
});

test("disabled Skill maintenance cannot dispatch from the UI", async ({ page, request }) => {
  const before = await request.get("http://127.0.0.1:18001/fake/requests");
  const beforeCount = (await before.json()).count;
  await page.goto("/");
  await page.getByRole("button", { name: "Settings" }).click();
  await page.getByLabel("Enable Skill maintenance").uncheck();
  await page.getByRole("button", { name: "Save settings" }).click();
  await expect(page.getByRole("alert")).toContainText("AI runtime settings saved");

  await page.getByRole("button", { name: "Classification" }).click();
  await expect(page.getByText(/disabled in Settings/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Run maintenance now" })).toBeDisabled();
  const after = await request.get("http://127.0.0.1:18001/fake/requests");
  expect((await after.json()).count).toBe(beforeCount);
});

test("provider unavailable keeps the Candidate visible with an auditable failure", async ({
  page,
  request,
}) => {
  await request.post("http://127.0.0.1:18001/fake/seed/2");
  await request.post("http://127.0.0.1:18001/fake/mode/unavailable");
  await page.goto("/");
  await page.getByRole("button", { name: "Settings" }).click();
  await page.getByLabel("Enable Skill maintenance").check();
  await page.getByRole("button", { name: "Save settings" }).click();
  await expect(page.getByRole("alert")).toContainText("AI runtime settings saved");

  await page.getByRole("button", { name: "Classification" }).click();
  await expect(page.getByText("NovelDB2", { exact: true }).first()).toBeVisible();
  await page.getByRole("button", { name: "Run maintenance now" }).click();
  await expect(page.getByText(/Latest: unavailable/)).toBeVisible();
  await expect(page.getByText("NovelDB2", { exact: true }).first()).toBeVisible();
  const audit = await request.get("http://127.0.0.1:18001/fake/requests");
  expect((await audit.json()).requests.at(-1)).toEqual(expect.objectContaining({
    path: "/fake/systemone",
  }));
});

test("over-budget maintenance makes zero provider calls and keeps Candidates", async ({
  page,
  request,
}) => {
  await request.post("http://127.0.0.1:18001/fake/seed/3");
  await request.post("http://127.0.0.1:18001/fake/mode/normal");
  const settings = await request.put(
    "http://127.0.0.1:18001/api/settings/ai",
    {
      data: { jev: { max_request_reservation_microdollars: 2_000_000 } },
    },
  );
  expect(settings.ok()).toBeTruthy();
  const before = await request.get("http://127.0.0.1:18001/fake/requests");
  const beforeCount = (await before.json()).count;

  await page.goto("/#classification");
  await expect(page.getByText("NovelDB3", { exact: true }).first()).toBeVisible();
  await page.getByRole("button", { name: "Run maintenance now" }).click();
  await expect(page.getByText(/Latest: unavailable/)).toBeVisible();
  await expect(page.getByText("NovelDB3", { exact: true }).first()).toBeVisible();
  const after = await request.get("http://127.0.0.1:18001/fake/requests");
  expect((await after.json()).count).toBe(beforeCount);
});

test("proposes and confirms a source-preserving duplicate association in Job Detail", async ({
  page,
  request,
}) => {
  await request.post("http://127.0.0.1:18001/fake/mode/normal");
  const seeded = await request.post(
    "http://127.0.0.1:18001/fake/seed-duplicate-pair/1",
  );
  expect(seeded.ok()).toBeTruthy();

  await page.goto("/#jobs");
  await page.getByRole("button", {
    name: "View Senior Backend Engineer E2E 1 at Duplicate E2E Company 1",
  }).click();
  await expect(page.getByRole("heading", { name: "Possible same vacancy" })).toBeVisible();
  await page.getByLabel("Possible same vacancy").getByRole("button", {
    name: "Evaluate with Jev",
  }).click();

  await expect(page.getByText("ctgoodjobs:e2e-duplicate-right-1")).toBeVisible();
  await expect(page.getByText("Jev proposal — pending review")).toBeVisible();
  await expect(page.getByText(/No Job is merged, hidden, or deleted/)).toBeVisible();
  await page.getByRole("button", { name: "Confirm association" }).click();
  await expect(page.getByText("Confirmed same vacancy")).toBeVisible();
  await expect(page.getByText(/both source Jobs remain available/)).toBeVisible();

  await page.getByRole("button", { name: "Close job details" }).click();
  await expect(page.getByRole("article", {
    name: "Senior Backend Engineer E2E 1 at Duplicate E2E Company 1",
    exact: true,
  })).toBeVisible();
  await expect(page.getByRole("article", {
    name: "Backend Engineer E2E 1 at Duplicate E2E Company 1",
    exact: true,
  })).toBeVisible();
});

test("Jev duplicate provider failure leaves both source Jobs unchanged", async ({
  page,
  request,
}) => {
  await request.post("http://127.0.0.1:18001/fake/seed-duplicate-pair/2");
  await request.post("http://127.0.0.1:18001/fake/mode/unavailable");

  await page.goto("/#jobs");
  await page.getByRole("button", {
    name: "View Senior Backend Engineer E2E 2 at Duplicate E2E Company 2",
  }).click();
  await page.getByLabel("Possible same vacancy").getByRole("button", {
    name: "Evaluate with Jev",
  }).click();
  await expect(page.getByText("No possible same-vacancy associations yet")).toBeVisible();
  await expect(page.getByRole("button", { name: "Confirm association" })).toHaveCount(0);

  await page.getByRole("button", { name: "Close job details" }).click();
  await expect(page.getByRole("article", {
    name: "Senior Backend Engineer E2E 2 at Duplicate E2E Company 2",
    exact: true,
  })).toBeVisible();
  await expect(page.getByRole("article", {
    name: "Backend Engineer E2E 2 at Duplicate E2E Company 2",
    exact: true,
  })).toBeVisible();
});

test("previews for free and evaluates crawl quality end to end", async ({
  page,
  request,
}) => {
  const seededResponse = await request.post(
    "http://127.0.0.1:18001/fake/seed-crawl-quality/1",
  );
  expect(seededResponse.ok()).toBeTruthy();
  const seeded = await seededResponse.json();
  const settings = await request.put(
    "http://127.0.0.1:18001/api/settings/ai",
    {
      data: {
        jev: {
          enabled: true,
          crawl_quality_enabled: true,
          crawl_quality_batch_limit: 20,
          max_request_reservation_microdollars: 50_000,
        },
      },
    },
  );
  expect(settings.ok()).toBeTruthy();
  await request.post(
    "http://127.0.0.1:18001/fake/mode/crawl_quality_problem",
  );

  const before = await request.get("http://127.0.0.1:18001/fake/requests");
  const beforeCount = (await before.json()).count;
  await page.goto(`/#crawl-tasks?task=${seeded.crawl_job_id}`);
  await expect(page.getByRole("heading", { name: "Task Details" })).toBeVisible();
  const advisory = page
    .getByRole("heading", { name: "Crawl content quality advisory" })
    .locator("..");
  await expect(advisory).toContainText(
    "does not retry, repair, resume, cancel, or change this Crawl Job",
  );
  await advisory.getByRole("button", { name: "Preview candidates" }).click();
  await expect(advisory.getByRole("status")).toContainText(
    "Free database preview: 1 selected / 1 eligible",
  );
  await expect(advisory.getByRole("status")).toContainText(
    "No Jev request was sent.",
  );
  const afterPreview = await request.get(
    "http://127.0.0.1:18001/fake/requests",
  );
  expect((await afterPreview.json()).count).toBe(beforeCount);

  await advisory.getByRole("button", { name: "Evaluate with Jev" }).click();
  await expect(advisory).toContainText("Latest: completed · 1 observations");
  await expect(advisory).toContainText("offertoday:e2e-crawl-quality-1");
  await expect(advisory).toContainText("quality_problem");
  await expect(advisory).toContainText("listing_or_template");
  await expect(advisory).toContainText(/receipt e2e-request-\d+/);
  await expect(advisory).toContainText("cost USD 0.00005");
  await expect(
    advisory.getByRole("button", { name: /retry|repair|resume|cancel/i }),
  ).toHaveCount(0);

  const audit = await request.get("http://127.0.0.1:18001/fake/requests");
  const auditPayload = await audit.json();
  expect(auditPayload.count).toBe(beforeCount + 1);
  expect(auditPayload.requests.at(-1)).toEqual(expect.objectContaining({
    path: "/fake/systemone",
    has_bearer: true,
    question_names: ["problem_kind", "quality"],
  }));
  const state = await request.get(
    `http://127.0.0.1:18001/fake/crawl-quality-state/${seeded.crawl_job_id}/${seeded.listing_id}`,
  );
  expect(await state.json()).toEqual({
    crawl_job_status: "completed",
    listing_detail_status: "completed",
  });
});

test("crawl quality provider failure stays advisory and preserves crawl state", async ({
  page,
  request,
}) => {
  const seededResponse = await request.post(
    "http://127.0.0.1:18001/fake/seed-crawl-quality/2",
  );
  const seeded = await seededResponse.json();
  await request.post("http://127.0.0.1:18001/fake/mode/unavailable");

  await page.goto(`/#crawl-tasks?task=${seeded.crawl_job_id}`);
  const advisory = page
    .getByRole("heading", { name: "Crawl content quality advisory" })
    .locator("..");
  await advisory.getByRole("button", { name: "Preview candidates" }).click();
  await advisory.getByRole("button", { name: "Evaluate with Jev" }).click();
  await expect(advisory).toContainText(
    "Latest: completed_with_failures · 1 observations",
  );
  await expect(advisory).toContainText(
    "offertoday:e2e-crawl-quality-2 · unavailable",
  );
  const state = await request.get(
    `http://127.0.0.1:18001/fake/crawl-quality-state/${seeded.crawl_job_id}/${seeded.listing_id}`,
  );
  expect(await state.json()).toEqual({
    crawl_job_status: "completed",
    listing_detail_status: "completed",
  });
});

test("previews and evaluates secret-safe repeated incident clusters without actions", async ({
  page,
  request,
}) => {
  const seededResponse = await request.post(
    "http://127.0.0.1:18001/fake/seed-incidents/1",
  );
  const seeded = await seededResponse.json();
  const configured = await request.put(
    "http://127.0.0.1:18001/api/settings/ai",
    {
      data: {
        jev: {
          enabled: true,
          incident_triage_enabled: true,
          incident_triage_event_limit: 100,
          endpoint: "http://127.0.0.1:18001/fake/systemone",
          api_key: "e2e-local-secret",
          max_request_reservation_microdollars: 50_000,
        },
      },
    },
  );
  expect(configured.ok()).toBeTruthy();
  await request.post("http://127.0.0.1:18001/fake/mode/incident_triage");
  const before = await request.get("http://127.0.0.1:18001/fake/requests");
  const beforeCount = (await before.json()).count;

  await page.goto("/#crawl-tasks");
  const advisory = page.getByRole("region", {
    name: "Jev repeated incident triage",
  });
  await expect(advisory).toContainText(
    "cannot change severity, retry, resume, cancel, dismiss, or write Crawl Job events",
  );
  await advisory.getByRole("button", { name: "Preview incident clusters" }).click();
  await expect(advisory.getByRole("status")).toContainText(
    "No Jev request was sent",
  );
  expect((await (await request.get("http://127.0.0.1:18001/fake/requests")).json()).count)
    .toBe(beforeCount);

  await advisory.getByRole("button", { name: "Evaluate clusters with Jev" }).click();
  await expect(advisory.getByTestId("jev-incident-triage-receipt")).toContainText(
    "Latest: completed",
  );
  await expect(advisory).toContainText("investigate_now");
  await expect(advisory).toContainText("[url]");
  await expect(advisory).toContainText("[credential]");
  await expect(advisory).not.toContainText("private.invalid");
  await expect(advisory).not.toContainText("secret-1");
  await expect(
    advisory.getByRole("button", { name: /retry|resume|cancel|dismiss/i }),
  ).toHaveCount(0);

  const audit = await request.get("http://127.0.0.1:18001/fake/requests");
  const auditPayload = await audit.json();
  expect(auditPayload.count).toBe(beforeCount + 1);
  expect(auditPayload.requests.at(-1).question_names).toEqual(["cluster_0"]);
  const state = await request.get(
    `http://127.0.0.1:18001/fake/incident-state/${seeded.crawl_job_id}`,
  );
  expect(await state.json()).toEqual({ crawl_job_status: "failed", event_count: 3 });
});

test("incident provider failure keeps deterministic clusters and crawl state", async ({
  page,
  request,
}) => {
  const seededResponse = await request.post(
    "http://127.0.0.1:18001/fake/seed-incidents/2",
  );
  const seeded = await seededResponse.json();
  await request.post("http://127.0.0.1:18001/fake/mode/unavailable");

  await page.goto("/#crawl-tasks");
  const advisory = page.getByRole("region", {
    name: "Jev repeated incident triage",
  });
  await advisory.getByLabel("Jev incident event limit").fill("1");
  await advisory.getByRole("button", { name: "Preview incident clusters" }).click();
  await advisory.getByRole("button", { name: "Evaluate clusters with Jev" }).click();
  await expect(advisory.getByTestId("jev-incident-triage-receipt")).toContainText(
    "Latest: completed_with_failures",
  );
  await expect(advisory.getByTestId("jev-incident-triage-fallback")).toContainText(
    "deterministic clusters remain visible",
  );
  const state = await request.get(
    `http://127.0.0.1:18001/fake/incident-state/${seeded.crawl_job_id}`,
  );
  expect(await state.json()).toEqual({ crawl_job_status: "failed", event_count: 3 });
});

test("over-budget incident triage sends zero provider calls and keeps clusters", async ({
  page,
  request,
}) => {
  await request.post("http://127.0.0.1:18001/fake/seed-incidents/3");
  const configured = await request.put(
    "http://127.0.0.1:18001/api/settings/ai",
    {
      data: {
        jev: {
          enabled: true,
          incident_triage_enabled: true,
          incident_triage_event_limit: 100,
          endpoint: "http://127.0.0.1:18001/fake/systemone",
          api_key: "e2e-local-secret",
          max_request_reservation_microdollars: 20_000_000,
        },
      },
    },
  );
  expect(configured.ok()).toBeTruthy();
  const before = await request.get("http://127.0.0.1:18001/fake/requests");
  const beforeCount = (await before.json()).count;

  await page.goto("/#crawl-tasks");
  const advisory = page.getByRole("region", {
    name: "Jev repeated incident triage",
  });
  await advisory.getByLabel("Jev incident event limit").fill("1");
  await advisory.getByRole("button", { name: "Preview incident clusters" }).click();
  await advisory.getByRole("button", { name: "Evaluate clusters with Jev" }).click();
  await expect(advisory.getByTestId("jev-incident-triage-receipt")).toContainText(
    "jev_allowance_exhausted",
  );
  await expect(advisory.getByTestId("jev-incident-triage-fallback")).toContainText(
    "deterministic clusters remain visible",
  );
  const after = await request.get("http://127.0.0.1:18001/fake/requests");
  expect((await after.json()).count).toBe(beforeCount);

  const restored = await request.put(
    "http://127.0.0.1:18001/api/settings/ai",
    { data: { jev: { max_request_reservation_microdollars: 50_000 } } },
  );
  expect(restored.ok()).toBeTruthy();
});

test("reranks one frozen lexical search prefix without changing membership", async ({
  page,
  request,
}) => {
  const seededResponse = await request.post(
    "http://127.0.0.1:18001/fake/seed-search-rerank/1",
  );
  expect(seededResponse.ok()).toBeTruthy();
  const seeded = await seededResponse.json();
  await request.post("http://127.0.0.1:18001/fake/mode/search_rerank");
  const before = await request.get("http://127.0.0.1:18001/fake/requests");
  const beforeCount = (await before.json()).count;

  await page.goto("/#jobs");
  const query = page.getByPlaceholder(
    "Query titles, companies, or deep scan descriptions...",
  );
  await query.fill("Rerank Python");
  await page.getByRole("button", { name: "Search all jobs" }).click();
  await expect(page.getByRole("button", { name: "Export 5 results" })).toBeVisible();
  const baselineTitles = await page.locator(".job-card .job-title").allTextContents();
  expect(baselineTitles).toEqual(seeded.titles);
  const afterSearch = await request.get(
    "http://127.0.0.1:18001/fake/requests",
  );
  expect((await afterSearch.json()).count).toBe(beforeCount);

  const advisory = page.getByRole("region", {
    name: "Jev search relevance advisory",
  });
  const previewResponsePromise = page.waitForResponse(
    (response) => response.url().endsWith("/api/jobs/search/rerank/preview"),
  );
  const previewRequestPromise = page.waitForRequest(
    (request_) => request_.url().endsWith("/api/jobs/search/rerank/preview"),
  );
  await advisory.getByRole("button", {
    name: "Preview rerank candidates",
  }).click();
  const preview = await (await previewResponsePromise).json();
  const previewRequest = (await previewRequestPromise).postDataJSON();
  await expect(advisory.getByRole("status")).toContainText(
    "Free database preview: 5 selected / 5 eligible",
  );
  await expect(advisory.getByRole("status")).toContainText(
    "No Jev request was sent.",
  );
  const afterPreview = await request.get(
    "http://127.0.0.1:18001/fake/requests",
  );
  expect((await afterPreview.json()).count).toBe(beforeCount);

  await advisory.getByRole("button", { name: "Evaluate with Jev" }).click();
  await expect(advisory.getByTestId("jev-search-rerank-receipt")).toContainText(
    "Latest: completed",
  );
  await expect(advisory.getByTestId("jev-search-rerank-receipt")).toContainText(
    /receipt e2e-request-\d+ · local-e2e · cost USD 0\.00005/,
  );
  const rerankedTitles = await page.locator(".job-card .job-title").allTextContents();
  expect(rerankedTitles).not.toEqual(baselineTitles);
  expect([...rerankedTitles].sort()).toEqual([...baselineTitles].sort());
  await expect(page.getByRole("button", { name: "Export 5 results" })).toBeVisible();

  const audit = await request.get("http://127.0.0.1:18001/fake/requests");
  const auditPayload = await audit.json();
  expect(auditPayload.count).toBe(beforeCount + 1);
  expect(auditPayload.requests.at(-1)).toEqual(expect.objectContaining({
    path: "/fake/systemone",
    has_bearer: true,
    question_names: [
      "candidate_0",
      "candidate_1",
      "candidate_2",
      "candidate_3",
      "candidate_4",
    ],
  }));

  const exportResponse = await request.post(
    "http://127.0.0.1:18001/api/jobs/search/export",
    {
      data: {
        scope: previewRequest.scope,
        retrieval_mode: "lexical",
        page: 1,
        page_size: 20,
        include_facets: false,
        jev_rerank_evaluation_id: preview.id,
      },
    },
  );
  expect(exportResponse.ok()).toBeTruthy();
  const csv = await exportResponse.text();
  const csvTitles = csv.trim().split("\n").slice(1).map((row) => row.split(",")[2]);
  expect(csvTitles).toEqual(rerankedTitles);
});

test("keeps the frozen lexical baseline when search reranking is unavailable", async ({
  page,
  request,
}) => {
  const seededResponse = await request.post(
    "http://127.0.0.1:18001/fake/seed-search-rerank/2",
  );
  expect(seededResponse.ok()).toBeTruthy();
  const seeded = await seededResponse.json();
  const configured = await request.put(
    "http://127.0.0.1:18001/api/settings/ai",
    {
      data: {
        jev: {
          enabled: true,
          endpoint: "http://127.0.0.1:18001/fake/systemone",
          api_key: "e2e-local-secret",
          search_rerank_enabled: true,
          max_request_reservation_microdollars: 50_000,
        },
      },
    },
  );
  expect(configured.ok()).toBeTruthy();
  await request.post("http://127.0.0.1:18001/fake/mode/unavailable");
  const before = await request.get("http://127.0.0.1:18001/fake/requests");
  const beforeCount = (await before.json()).count;

  await page.goto("/#jobs");
  const query = page.getByPlaceholder(
    "Query titles, companies, or deep scan descriptions...",
  );
  await query.fill("rerank-batch-2");
  await page.getByRole("button", { name: "Search all jobs" }).click();
  const baselineTitles = await page.locator(".job-card .job-title").allTextContents();
  expect(baselineTitles).toEqual(seeded.titles);

  const advisory = page.getByRole("region", {
    name: "Jev search relevance advisory",
  });
  await advisory.getByRole("button", {
    name: "Preview rerank candidates",
  }).click();
  await advisory.getByRole("button", { name: "Evaluate with Jev" }).click();
  await expect(advisory.getByTestId("jev-search-rerank-receipt")).toContainText(
    "Latest: completed_with_failures",
  );
  await expect(advisory.getByTestId("jev-search-rerank-fallback")).toContainText(
    "baseline order retained",
  );
  expect(await page.locator(".job-card .job-title").allTextContents()).toEqual(
    baselineTitles,
  );

  const after = await request.get("http://127.0.0.1:18001/fake/requests");
  expect((await after.json()).count).toBe(beforeCount + 1);
});
