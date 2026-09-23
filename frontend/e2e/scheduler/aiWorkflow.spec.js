import { test, expect } from '@playwright/test';
import { interceptScheduler } from './fixtures';
import { interceptAI } from './aiFixtures';
import { interceptCrawl } from './crawlFixtures';

for (const width of [1366, 760]) {
  test(`AI preview, actual receipt, inspection, stop and scoped retry at ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await interceptScheduler(page);
    const requests = await interceptAI(page);
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('dialog', dialog => dialog.accept());
    await page.goto('/#ai');
    await page.getByLabel('jobsdb', { exact: true }).check();
    await expect(page.getByRole('button', { name: 'Run 48 filtered jobs' })).toBeEnabled();
    await expect(page.getByText(/Selected 50 within the limit of 50/)).toBeVisible();
    await page.getByRole('button', { name: 'Run 48 filtered jobs' }).click();
    await expect(page.getByRole('status').filter({ hasText: 'Filtered run submitted' })).toContainText('submitted for 3 jobs; 1 excluded');
    await page.getByRole('link', { name: 'Inspect submitted run created-ai' }).click();
    await expect(page.getByRole('heading', { name: 'Run details: created-ai' })).toBeFocused();
    await page.getByRole('button', { name: 'Stop this run', exact: true }).click();
    await expect(page.getByRole('status').filter({ hasText: 'Stop requested' })).toContainText('Stop requested for created-ai');
    await page.getByRole('link', { name: 'older-failed', exact: true }).click();
    await expect(page.getByText('Provider timed out', { exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Retry this run’s failed jobs (2)' }).click();
    await expect(page.getByRole('link', { name: 'Inspect submitted run retry-ai' })).toBeVisible();
    expect(requests.filter(request => request.path.endsWith('/retry-failed'))).toEqual([expect.objectContaining({ path: '/api/ai/runs/older-failed/retry-failed', method: 'POST' })]);
    expect(requests.filter(request => request.path === '/api/ai/runs' && request.method === 'POST')).toHaveLength(1);
    expect(errors).toEqual([]);
    await page.locator('.app-main').evaluate(element => { element.scrollTop = 0; });
    await page.screenshot({ path: `/tmp/job-scraper-ai-${width}.png`, fullPage: true });
  });
}

test('waiting history links to the exact upstream crawl and survives reload', async ({ page }) => {
  await interceptScheduler(page);
  await interceptCrawl(page);
  await interceptAI(page);
  await page.goto('/#ai?run=waiting-crawl');
  await expect(page.getByText('This run is waiting for an execution slot. Its jobs are already reserved.')).toBeVisible();
  await page.reload();
  await page.getByRole('link', { name: 'Open linked crawl task' }).click();
  await expect(page).toHaveURL(/#crawl-tasks\?task=task-1/);
  await expect(page.getByRole('heading', { name: 'Task Details' })).toBeVisible();
});
