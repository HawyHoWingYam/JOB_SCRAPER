import { expect, test } from '@playwright/test';


async function providerRequestCount(request) {
  const response = await request.get('http://127.0.0.1:18001/fake/requests');
  return (await response.json()).count;
}

async function configureJev(page) {
  await page.goto('/#settings');
  await expect(page.getByRole('heading', { name: 'Jev System One' })).toBeVisible();
  await page.getByLabel('Enable Jev', { exact: true }).check();
  await page.getByLabel('Jev endpoint').fill('http://127.0.0.1:18001/fake/systemone');
  await page.getByLabel('Jev API key', { exact: true }).fill('e2e-local-secret');
  await page.getByRole('button', { name: 'Save settings' }).click();
  await expect(page.getByRole('alert')).toContainText('AI runtime settings saved');
}

test('keeps money in the provider console and starts smoke only from Jev Operations', async ({
  page,
  request,
}) => {
  await configureJev(page);
  await expect(page.getByText(/monetary limits are managed in the jev api console/i))
    .toBeVisible();
  await expect(page.getByLabel(/allowance|reservation|microdollars/i)).toHaveCount(0);

  const beforeCount = await providerRequestCount(request);
  await page.goto('/#jev');
  await expect(page.getByRole('heading', { name: 'Jev Operations' })).toBeVisible();
  await expect(page.getByText(/nothing on this page starts until/i)).toBeVisible();
  expect(await providerRequestCount(request)).toBe(beforeCount);

  await page.getByRole('button', { name: 'Run one Jev smoke request' }).click();
  await expect(page.getByText(/"status": "completed"/)).toBeVisible();
  await expect(page.getByLabel(/Jev run /).first()).toContainText(
    'configuration_smoke_test',
  );
  expect(await providerRequestCount(request)).toBe(beforeCount + 1);
});

test('starts Skill maintenance manually in the unified console and approves in review', async ({
  page,
  request,
}) => {
  await request.post('http://127.0.0.1:18001/fake/mode/normal');
  const beforeCount = await providerRequestCount(request);
  await page.goto('/#jev');
  const tool = page.getByRole('heading', { name: 'Skill taxonomy maintenance' }).locator('..');
  await tool.getByRole('button', { name: 'Run maintenance now' }).click();
  await expect(tool).toContainText('ready_for_approval');
  expect(await providerRequestCount(request)).toBe(beforeCount + 1);

  await page.goto('/#classification');
  await expect(page.getByText('NovelDB', { exact: true }).first()).toBeVisible();
  await expect(page.getByRole('button', { name: 'Run maintenance now' })).toHaveCount(0);
  await page.getByRole('button', { name: 'Approve proposed Skills' }).click();
  await expect(page.getByText(/Latest: applied/)).toBeVisible();
  await expect(page.getByText('There are no Skills to review.')).toBeVisible();
});

test('previews crawl quality without dispatch and evaluates only after the manual action', async ({
  page,
  request,
}) => {
  const seededResponse = await request.post(
    'http://127.0.0.1:18001/fake/seed-crawl-quality/1',
  );
  const seeded = await seededResponse.json();
  await request.post('http://127.0.0.1:18001/fake/mode/crawl_quality_problem');
  const beforeCount = await providerRequestCount(request);

  await page.goto('/#jev');
  const tool = page.getByRole('heading', { name: 'Crawl content quality' }).locator('..');
  await tool.getByLabel('Crawl Job UUID').fill(seeded.crawl_job_id);
  await tool.getByRole('button', { name: 'Preview listings' }).click();
  await expect(tool.getByRole('button', { name: 'Evaluate listings with Jev' }))
    .toBeEnabled();
  expect(await providerRequestCount(request)).toBe(beforeCount);

  await tool.getByRole('button', { name: 'Evaluate listings with Jev' }).click();
  await expect(tool).toContainText('quality_problem');
  await expect(tool).toContainText('"cost_usd": 0.00005');
  expect(await providerRequestCount(request)).toBe(beforeCount + 1);
  const state = await request.get(
    `http://127.0.0.1:18001/fake/crawl-quality-state/${seeded.crawl_job_id}/${seeded.listing_id}`,
  );
  expect(await state.json()).toEqual({
    crawl_job_status: 'completed',
    listing_detail_status: 'completed',
  });
});

test('previews and evaluates redacted incident clusters only from Jev Operations', async ({
  page,
  request,
}) => {
  const seededResponse = await request.post(
    'http://127.0.0.1:18001/fake/seed-incidents/1',
  );
  const seeded = await seededResponse.json();
  await request.post('http://127.0.0.1:18001/fake/mode/incident_triage');
  const beforeCount = await providerRequestCount(request);

  await page.goto('/#jev');
  const tool = page.getByRole('heading', { name: 'Repeated incident triage' }).locator('..');
  await tool.getByLabel('Event limit').fill('100');
  await tool.getByRole('button', { name: 'Preview incidents' }).click();
  await expect(tool.getByRole('button', { name: 'Evaluate clusters with Jev' }))
    .toBeEnabled();
  expect(await providerRequestCount(request)).toBe(beforeCount);

  await tool.getByRole('button', { name: 'Evaluate clusters with Jev' }).click();
  await expect(tool).toContainText('investigate_now');
  await expect(tool).toContainText('[url]');
  await expect(tool).not.toContainText('private.invalid');
  await expect(tool).not.toContainText('secret-1');
  expect(await providerRequestCount(request)).toBe(beforeCount + 1);
  const state = await request.get(
    `http://127.0.0.1:18001/fake/incident-state/${seeded.crawl_job_id}`,
  );
  expect(await state.json()).toEqual({ crawl_job_status: 'failed', event_count: 3 });
});

test('uses a saved Job Browser scope for a manually started relevance advisory', async ({
  page,
  request,
}) => {
  await request.post('http://127.0.0.1:18001/fake/seed-search-rerank/1');
  await request.post('http://127.0.0.1:18001/fake/mode/search_rerank');
  const beforeCount = await providerRequestCount(request);

  await page.goto('/#jobs');
  await page.getByPlaceholder(
    'Query titles, companies, or deep scan descriptions...',
  ).fill('Rerank Python');
  await page.getByRole('button', { name: 'Search all jobs' }).click();
  await expect(page.getByRole('button', { name: 'Export 5 results' })).toBeVisible();
  expect(await providerRequestCount(request)).toBe(beforeCount);

  await page.goto('/#jev');
  const tool = page.getByRole('heading', { name: 'Search relevance advisory' }).locator('..');
  await tool.getByRole('button', { name: 'Preview saved search' }).click();
  await expect(tool.getByRole('button', { name: 'Evaluate preview with Jev' }))
    .toBeEnabled();
  expect(await providerRequestCount(request)).toBe(beforeCount);

  await tool.getByRole('button', { name: 'Evaluate preview with Jev' }).click();
  await expect(tool).toContainText('"reranked_position": 0');
  await expect(tool).toContainText('"cost_usd": 0.00005');
  expect(await providerRequestCount(request)).toBe(beforeCount + 1);
});
