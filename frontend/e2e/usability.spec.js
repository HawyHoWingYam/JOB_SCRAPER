import { test, expect } from '@playwright/test';

for (const viewport of [{ width: 1366, height: 768 }, { width: 1440, height: 900 }]) {
  test(`laptop search keeps results visible and applies edits explicitly at ${viewport.width}`, async ({ page, request }) => {
    await page.setViewportSize(viewport);
    const seedIndex = viewport.width === 1366 ? 3 : 4;
    const seed = await request.post(`http://127.0.0.1:18001/fake/seed-search-rerank/${seedIndex}`);
    expect(seed.ok()).toBeTruthy();
    await page.goto('/#jobs');
    const nav = page.getByRole('navigation', { name: 'Main navigation' });
    for (const group of ['Data', 'Collection', 'Processing']) {
      await expect(nav.getByRole('heading', { name: group })).toBeVisible();
    }
    const firstJob = page.locator('.job-card').first();
    await expect(firstJob).toBeVisible();
    const box = await firstJob.boundingBox();
    expect(box.y + box.height).toBeLessThanOrEqual(viewport.height);
    const filters = await page.locator('.filter-deck').boundingBox();
    expect(filters.x + filters.width).toBeLessThanOrEqual(box.x);
    const requests = [];
    page.on('request', (req) => {
      if (req.url().endsWith('/api/jobs/search')) requests.push(req.postDataJSON());
    });
    const titlesBefore = await page.locator('.job-title').allTextContents();
    const query = page.getByPlaceholder('Search Job Description...');
    await query.fill(`rerank-batch-${seedIndex}`);
    await expect(page.getByText(/Unapplied changes\. Export uses/)).toBeVisible();
    expect(requests).toHaveLength(0);
    expect(await page.locator('.job-title').allTextContents()).toEqual(titlesBefore);
    await page.getByRole('button', { name: 'Search all jobs', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Export 5 results', exact: true })).toBeVisible();
    expect(requests).toHaveLength(1);
    const successfulTitles = await page.locator('.job-title').allTextContents();
    await page.route('**/api/jobs/search', (route) => route.fulfill({ status: 503, json: { detail: 'Search temporarily unavailable' } }));
    await query.fill('failing search');
    await page.getByRole('button', { name: 'Search all jobs', exact: true }).click();
    await expect(page.getByRole('alert')).toContainText('Search temporarily unavailable');
    expect(await page.locator('.job-title').allTextContents()).toEqual(successfulTitles);
    await expect(page.getByRole('button', { name: 'Export 5 results', exact: true })).toBeEnabled();
    expect(await page.locator('main').evaluate((el) => el.scrollWidth <= el.clientWidth)).toBeTruthy();
  });
}

test('all navigation destinations remain directly accessible', async ({ page }) => {
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto('/');
  for (const [label, hash, heading] of [
    ['Dashboard', 'dashboard', 'Command Center'],
    ['Job Browser', 'jobs', 'Job Browser'],
    ['Add Job', 'add-job', 'Add Job'],
    ['Companies', 'companies', 'Companies'],
    ['Scheduler', 'scheduler', 'Scheduler'],
    ['Crawl Tasks', 'crawl-tasks', 'Crawl Tasks'],
    ['OfferToday Keywords', 'offertoday-keywords', 'OfferToday Keyword Packs'],
    ['AI Enrichment', 'ai', 'AI Enrichment'],
    ['Classification', 'classification', 'Skills to review'],
    ['Settings', 'settings', 'AI Runtime'],
  ]) {
    await page.locator('.sidebar').getByRole('button', { name: label, exact: true }).click();
    if (hash !== 'dashboard') await expect(page).toHaveURL(new RegExp(`#${hash}`));
    await expect(page.getByRole('heading', { name: heading, exact: true }).first()).toBeVisible();
    expect(await page.locator('main').evaluate((el) => el.scrollWidth <= el.clientWidth)).toBeTruthy();
  }
  expect(errors).toEqual([]);
});

test('empty AI queue explains why no new run can start', async ({ page }) => {
  await page.route('**/api/ai/overview', (route) => route.fulfill({ json: { pending_jobs: 0, ai_eligible_jobs: 10, active_runs: 0, failed_jobs: 0 } }));
  await page.route('**/api/ai/runs?monitor=true', (route) => route.fulfill({ json: { runs: [] } }));
  await page.route('**/api/ai/pending/filter-options', (route) => route.fulfill({ json: { sources: [] } }));
  await page.goto('/#ai');
  await expect(page.getByText(/No jobs are waiting for enrichment/)).toBeVisible();
  await expect(page.getByRole('button', { name: 'Run 0 filtered jobs' })).toBeDisabled();
});

test('keyword catalog failures remain actionable and never look like an empty catalog', async ({ page }) => {
  await page.route('**/api/offertoday-keyword-packs**', (route) => route.fulfill({ status: 503, json: { detail: 'Keyword catalog unavailable' } }));
  await page.goto('/#offertoday-keywords');
  await expect(page.getByRole('alert')).toContainText('Keyword catalog unavailable');
  await expect(page.getByRole('button', { name: 'Retry loading' })).toBeVisible();
  await expect(page.getByText('No matching keywords. Try a different filter.')).toHaveCount(0);
  await page.getByRole('button', { name: 'Download CSV' }).click();
  await expect(page.getByRole('alert')).toContainText('Could not download the CSV. Please retry.');
});

test('keyword retry restores the catalog and CSV changes require explicit confirmation', async ({ page }) => {
  let catalogUnavailable = true;
  let confirmations = 0;
  const catalog = { items: [{ id: 'keyword-1', classification_label: 'Information Technology', classification_id: 'offertoday:118000', keyword: 'Python', enabled: true }] };
  await page.route('**/api/offertoday-keyword-packs', (route) => {
    return catalogUnavailable
      ? route.fulfill({ status: 503, json: { detail: 'Catalog temporarily unavailable' } })
      : route.fulfill({ json: catalog });
  });
  await page.route('**/api/offertoday-keyword-packs/csv/preview', async (route) => {
    expect(route.request().postDataJSON()).toEqual({ csv_content: 'keyword\nPython\n' });
    await route.fulfill({ json: { valid: true, diff: [{ keyword: 'Python' }], confirmation_token: 'preview-token', csv_hash: 'preview-hash', resulting_enabled_counts: { 'offertoday:118000': 1 } } });
  });
  await page.route('**/api/offertoday-keyword-packs/csv/confirm', async (route) => {
    confirmations += 1;
    expect(route.request().postDataJSON()).toEqual({ confirmation_token: 'preview-token', csv_hash: 'preview-hash' });
    await route.fulfill({ json: { applied: true } });
  });
  await page.goto('/#offertoday-keywords');
  await expect(page.getByRole('alert')).toContainText('Catalog temporarily unavailable');
  catalogUnavailable = false;
  await page.getByRole('button', { name: 'Retry loading' }).click();
  await expect(page.getByRole('cell', { name: 'Python', exact: true })).toBeVisible();
  await expect(page.getByRole('alert')).toHaveCount(0);
  await page.getByRole('textbox', { name: 'Filter keywords' }).fill('no-match');
  await expect(page.getByText('No matching keywords. Try a different filter.')).toBeVisible();
  await page.getByRole('textbox', { name: 'Filter keywords' }).clear();
  await page.getByLabel('Upload CSV to preview').setInputFiles({ name: 'keywords.csv', mimeType: 'text/csv', buffer: Buffer.from('keyword\nPython\n') });
  await expect(page.getByRole('region', { name: 'CSV preview' })).toContainText('1 changes');
  expect(confirmations).toBe(0);
  await page.getByRole('button', { name: 'Confirm and apply' }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Keyword changes applied successfully.' })).toBeVisible();
  expect(confirmations).toBe(1);
  await expect(page.getByRole('region', { name: 'CSV preview' })).toHaveCount(0);
});

test('invalid keyword CSV cannot be confirmed', async ({ page }) => {
  await page.route('**/api/offertoday-keyword-packs', (route) => route.fulfill({ json: { items: [] } }));
  await page.route('**/api/offertoday-keyword-packs/csv/preview', (route) => route.fulfill({ json: { valid: false, errors: [{ row: 2, code: 'invalid_keyword', message: 'Keyword is required' }], warnings: [] } }));
  await page.goto('/#offertoday-keywords');
  await page.getByLabel('Upload CSV to preview').setInputFiles({ name: 'invalid.csv', mimeType: 'text/csv', buffer: Buffer.from('keyword\n\n') });
  await expect(page.getByRole('region', { name: 'CSV preview' })).toContainText('Keyword is required');
  await expect(page.getByRole('button', { name: 'Confirm and apply' })).toBeDisabled();
});
