import { expect, test } from "@playwright/test";

const apiKey = process.env.OPENROUTER_API_KEY;
const apiBase = "http://127.0.0.1:18001";
const model = "typesafe/jev-1.13";

async function configureRealJev(page) {
  await page.goto("/");
  await page.getByRole("button", { name: "Settings" }).click();
  await page.getByLabel("Enable Jev", { exact: true }).check();
  await page
    .getByLabel("Jev endpoint")
    .fill("https://openrouter.ai/api/alpha/decisions");
  await page.getByLabel("Jev model").fill(model);
  await page.getByLabel("Jev API key", { exact: true }).fill(apiKey);

  await page.getByLabel("Enable Jev duplicate evaluation").check();
  await page.getByLabel("Enable Jev search reranking").check();
  await page.getByLabel("Enable Jev incident triage").check();
  await page.getByLabel("Enable Jev crawl quality advisory").check();
  await page.getByLabel("Enable Skill maintenance").check();
  await page.getByLabel("Jev maintenance model").fill(model);
  await page.getByLabel("Jev maintenance minimum candidates").fill("1");

  await page.getByText("Advanced Jev controls").click();
  await page
    .getByLabel("Jev maximum request reservation microdollars")
    .fill("50000");
  await page.getByRole("button", { name: "Save settings" }).click();
  await expect(page.getByRole("alert")).toContainText(
    "AI runtime settings saved",
  );
}

async function expectCompletedRun(request, purpose) {
  const response = await request.get(`${apiBase}/api/jev/runs?limit=100`);
  expect(response.ok()).toBeTruthy();
  const payload = await response.json();
  const run = payload.runs.find((candidate) =>
    typeof purpose === "string"
      ? candidate.purpose === purpose
      : purpose.test(candidate.purpose),
  );
  expect(run, `missing Jev run matching ${purpose}`).toBeTruthy();
  expect(run).toEqual(
    expect.objectContaining({
      status: "completed",
      failed_items: 0,
      pending_items: 0,
    }),
  );
  return run;
}

async function expectRealProviderOnly(request) {
  const response = await request.get(`${apiBase}/fake/requests`);
  expect(response.ok()).toBeTruthy();
  expect(await response.json()).toEqual({ count: 0, requests: [] });
}

test.beforeEach(() => {
  test.skip(!apiKey, "OPENROUTER_API_KEY is not configured");
});

test("runs one bounded real OpenRouter Jev request through the Settings UI", async ({
  page,
  request,
}) => {
  await configureRealJev(page);

  await page.getByRole("button", { name: "Run one Jev smoke test" }).click();
  const history = page.getByLabel("Jev run history");
  await expect(history).toContainText("configuration_smoke_test", {
    timeout: 90_000,
  });
  await expect(history).toContainText(/completed · 1\/1/, { timeout: 90_000 });
  await expect(history).toContainText(`Frozen model: ${model}`);
  await expectCompletedRun(request, "configuration_smoke_test");
  await expectRealProviderOnly(request);
});

test("classifies a historical Skill through the real OpenRouter model and UI", async ({
  page,
  request,
}) => {
  await configureRealJev(page);
  await page.getByRole("button", { name: "Classification" }).click();

  await page.getByLabel("Jev Skill backfill limit").fill("1");
  await page.getByRole("button", { name: "Preview backfill" }).click();
  await expect(page.getByRole("status")).toContainText("free database read");
  await page.getByRole("button", { name: "Start bounded backfill" }).click();
  const status = page.getByRole("status");
  await expect(status).toContainText("Queued 1 Jobs in run");
  const runId = (await status.textContent()).match(/run ([^.]+)/)?.[1];
  expect(runId).toBeTruthy();

  const execution = await request.post(
    `${apiBase}/fake/execute-backfill/${runId}`,
    { timeout: 90_000 },
  );
  expect(execution.ok()).toBeTruthy();
  expect(await execution.json()).toEqual(
    expect.objectContaining({
      status: "completed",
      completed_items: 1,
      failed_items: 0,
    }),
  );
  const stateResponse = await request.get(
    `${apiBase}/fake/backfill-state/20000000-0000-0000-0000-000000000001`,
  );
  const state = await stateResponse.json();
  expect(state.classification_status).toBe("answered");
  expect(state.request_id).toBeTruthy();
  await expectCompletedRun(request, /^online_skill:/);

  await page.goto("/#jobs");
  await page.getByRole("button", {
    name: "View Novel Database Engineer at E2E Company 1",
  }).click();
  const classification = page.getByLabel("Latest Jev Skill classification");
  await expect(classification).toContainText("Status");
  await expect(classification).toContainText("answered");
  await expect(classification).toContainText(model);
  await expect(classification).toContainText(state.request_id);
  await expectRealProviderOnly(request);
});

test("runs real OpenRouter taxonomy maintenance from the Classification UI", async ({
  page,
  request,
}) => {
  const seed = await request.post(`${apiBase}/fake/seed/2`);
  expect(seed.ok()).toBeTruthy();
  await configureRealJev(page);
  await page.getByRole("button", { name: "Classification" }).click();
  await expect(page.getByText("NovelDB2", { exact: true }).first()).toBeVisible();

  const maintenance = page.getByLabel("Jev Skill maintenance");
  await maintenance.getByRole("button", { name: "Run maintenance now" }).click();
  await expect(maintenance).toContainText(/Latest: (?:applied|ready_for_approval)/, {
    timeout: 90_000,
  });
  await expect(maintenance).toContainText(model);
  await expect(maintenance).toContainText(/receipt /);
  await expectCompletedRun(request, /^taxonomy_maintenance:/);
  await expectRealProviderOnly(request);
});

test("evaluates a source-preserving duplicate pair with real OpenRouter Jev", async ({
  page,
  request,
}) => {
  const seed = await request.post(`${apiBase}/fake/seed-duplicate-pair/1`);
  expect(seed.ok()).toBeTruthy();
  await configureRealJev(page);

  await page.goto("/#jobs");
  await page.getByRole("button", {
    name: "View Senior Backend Engineer E2E 1 at Duplicate E2E Company 1",
  }).click();
  const advisory = page.getByLabel("Possible same vacancy");
  await expect(advisory).toContainText(
    "No Job is merged, hidden, or deleted",
  );
  await advisory.getByRole("button", { name: "Evaluate with Jev" }).click();
  await expect(advisory.getByRole("status")).toContainText(
    /Jev duplicate evaluation completed|No new candidate pairs needed evaluation/,
    { timeout: 90_000 },
  );
  await expectCompletedRun(request, "duplicate_association_product");

  await page.getByRole("button", { name: "Close job details" }).click();
  await expect(
    page.getByRole("article", {
      name: "Senior Backend Engineer E2E 1 at Duplicate E2E Company 1",
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    page.getByRole("article", {
      name: "Backend Engineer E2E 1 at Duplicate E2E Company 1",
      exact: true,
    }),
  ).toBeVisible();
  await expectRealProviderOnly(request);
});

test("evaluates crawl content quality with real OpenRouter Jev without lifecycle writes", async ({
  page,
  request,
}) => {
  const seedResponse = await request.post(
    `${apiBase}/fake/seed-crawl-quality/1`,
  );
  expect(seedResponse.ok()).toBeTruthy();
  const seed = await seedResponse.json();
  await configureRealJev(page);

  await page.goto(`/#crawl-tasks?task=${seed.crawl_job_id}`);
  const advisory = page
    .getByRole("heading", { name: "Crawl content quality advisory" })
    .locator("..");
  await expect(advisory).toContainText(
    "does not retry, repair, resume, cancel, or change this Crawl Job",
  );
  await advisory.getByRole("button", { name: "Preview candidates" }).click();
  await expect(advisory.getByRole("status")).toContainText(
    "No Jev request was sent.",
  );
  await advisory.getByRole("button", { name: "Evaluate with Jev" }).click();
  await expect(advisory).toContainText("Latest: completed · 1 observations", {
    timeout: 90_000,
  });
  await expect(advisory).toContainText(/receipt /);
  await expectCompletedRun(request, /^crawl_quality_product:/);

  const stateResponse = await request.get(
    `${apiBase}/fake/crawl-quality-state/${seed.crawl_job_id}/${seed.listing_id}`,
  );
  expect(await stateResponse.json()).toEqual({
    crawl_job_status: "completed",
    listing_detail_status: "completed",
  });
  await expectRealProviderOnly(request);
});

test("reranks a frozen lexical search with real OpenRouter Jev", async ({
  page,
  request,
}) => {
  const seedResponse = await request.post(
    `${apiBase}/fake/seed-search-rerank/1`,
  );
  expect(seedResponse.ok()).toBeTruthy();
  await configureRealJev(page);

  await page.goto("/#jobs");
  await page
    .getByPlaceholder("Query titles, companies, or deep scan descriptions...")
    .fill("rerank-batch-1");
  await page.getByRole("button", { name: "Search all jobs" }).click();
  await expect(page.getByRole("button", { name: "Export 5 results" })).toBeVisible();
  const baselineTitles = await page.locator(".job-card .job-title").allTextContents();

  const advisory = page.getByRole("region", {
    name: "Jev search relevance advisory",
  });
  await advisory
    .getByRole("button", { name: "Preview rerank candidates" })
    .click();
  await expect(advisory.getByRole("status")).toContainText(
    "Candidate membership is frozen. No Jev request was sent.",
  );
  await advisory.getByRole("button", { name: "Evaluate with Jev" }).click();
  await expect(advisory.getByTestId("jev-search-rerank-receipt")).toContainText(
    "Latest: completed",
    { timeout: 90_000 },
  );
  await expect(advisory.getByTestId("jev-search-rerank-receipt")).toContainText(
    /receipt /,
  );
  const rerankedTitles = await page.locator(".job-card .job-title").allTextContents();
  expect([...rerankedTitles].sort()).toEqual([...baselineTitles].sort());
  await expect(page.getByRole("button", { name: "Export 5 results" })).toBeVisible();
  await expectCompletedRun(request, /^search_rerank:/);
  await expectRealProviderOnly(request);
});

test("triages secret-safe incidents with real OpenRouter Jev without operational actions", async ({
  page,
  request,
}) => {
  const seedResponse = await request.post(`${apiBase}/fake/seed-incidents/1`);
  expect(seedResponse.ok()).toBeTruthy();
  const seed = await seedResponse.json();
  await configureRealJev(page);

  await page.goto("/#crawl-tasks");
  const advisory = page.getByRole("region", {
    name: "Jev repeated incident triage",
  });
  await expect(advisory).toContainText(
    "cannot change severity, retry, resume, cancel, dismiss, or write Crawl Job events",
  );
  await advisory.getByLabel("Jev incident event limit").fill("3");
  await advisory
    .getByRole("button", { name: "Preview incident clusters" })
    .click();
  await expect(advisory.getByRole("status")).toContainText(
    "No Jev request was sent.",
  );
  await advisory
    .getByRole("button", { name: "Evaluate clusters with Jev" })
    .click();
  await expect(advisory.getByTestId("jev-incident-triage-receipt")).toContainText(
    "Latest: completed",
    { timeout: 90_000 },
  );
  await expect(advisory.getByTestId("jev-incident-triage-receipt")).toContainText(
    /receipt /,
  );
  await expect(advisory).toContainText("[url]");
  await expect(advisory).toContainText("[credential]");
  await expect(advisory).not.toContainText("private.invalid");
  await expect(advisory).not.toContainText("secret-1");
  await expectCompletedRun(request, /^incident_triage:/);

  const stateResponse = await request.get(
    `${apiBase}/fake/incident-state/${seed.crawl_job_id}`,
  );
  expect(await stateResponse.json()).toEqual({
    crawl_job_status: "failed",
    event_count: 3,
  });
  await expectRealProviderOnly(request);
});
