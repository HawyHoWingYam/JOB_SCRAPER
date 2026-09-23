import { test, expect } from '@playwright/test';
import { interceptScheduler } from './fixtures';
import { interceptCrawl } from './crawlFixtures';

for (const width of [1366, 1440, 760]) {
  test(`Crawl task context, audit retry and cancellation acknowledgement at ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await interceptScheduler(page);
    const { requests, allowEvents, acknowledgeCancellation } = await interceptCrawl(page);
    await page.goto('/#crawl-tasks?task=linked-task&status=running&source=jobsdb&page=2');
    await expect(page.getByRole('heading', { name: 'Task Details', exact: true })).toBeVisible();
    await expect(page.getByText('This task is outside the current list page or filters.')).toBeVisible();
    await page.getByRole('button', { name: 'Audit events', exact: true }).click();
    await expect(page).toHaveURL(/view=events/);
    await expect(page.getByRole('button', { name: 'Retry events' })).toBeVisible();
    allowEvents();
    await page.getByRole('button', { name: 'Retry events' }).click();
    await expect(page.getByText('crawl.started', { exact: true })).toBeVisible();
    await page.reload();
    await expect(page.getByRole('heading', { name: 'Audit events', exact: true })).toBeVisible();
    await expect(page.getByRole('combobox', { name: 'Status', exact: true })).toHaveValue('running');
    await page.getByRole('button', { name: 'Back to task details' }).click();
    await expect(page).toHaveURL(/page=2/);
    await page.getByRole('button', { name: 'Cancel Crawl Job', exact: true }).click();
    await page.getByRole('button', { name: 'Request cancellation', exact: true }).click();
    await expect(page.getByText('Cancellation requested. Waiting for backend')).toBeVisible();
    acknowledgeCancellation();
    await expect(page.locator('.crawl-tasks-detail dd').filter({ hasText: /^cancelled$/ })).toBeVisible();
    expect(requests.filter(request => request.path.endsWith('/cancel'))).toHaveLength(1);
    expect(errors).toEqual([]);
    await page.locator('.app-main').evaluate(element => { element.scrollTop = 0; });
    await page.screenshot({ path: `/tmp/job-scraper-crawl-${width}.png`, fullPage: true });
  });
}

test('Scheduler View logs opens the exact task audit view', async ({ page }) => {
  await interceptScheduler(page);
  const { allowEvents } = await interceptCrawl(page);
  await page.goto('/#scheduler');
  await page.getByRole('button', { name: 'View logs', exact: true }).click();
  await expect(page).toHaveURL(/task=task-1&view=events/);
  await expect(page.getByRole('heading', { name: 'Audit events', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Retry events' })).toBeVisible();
    allowEvents();
    await page.getByRole('button', { name: 'Retry events' }).click();
  await expect(page.getByText('crawl.started', { exact: true })).toBeVisible();
});
