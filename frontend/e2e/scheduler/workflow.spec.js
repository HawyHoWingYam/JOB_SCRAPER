import { test, expect } from '@playwright/test';
import { interceptScheduler } from './fixtures';

const evidence = '/tmp/job-scraper-scheduler-evidence';
for (const size of [{ width: 1366, height: 768 }, { width: 1440, height: 900 }]) {
  test(`edit, review, correct, save and restore source ${size.width}`, async ({ page }) => {
    await page.setViewportSize(size);
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const requests = await interceptScheduler(page);
    await page.goto('/#scheduler');
    await expect(page.getByRole('heading', { name: 'Morning listings' })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: `${evidence}/after-board-${size.width}.png`, fullPage: true });
    await page.getByRole('button', { name: 'Edit', exact: true }).click();
    await expect(page.getByLabel('Name', { exact: true })).toHaveValue('Morning listings');
    await expect(page).toHaveURL(/step=execution/);
    await expect(page.getByLabel('Initial state')).toHaveCount(0);
    await page.getByLabel('Name', { exact: true }).fill('Evening listings');
    await page.reload();
    await expect(page.getByLabel('Name', { exact: true })).toHaveValue('Evening listings');
    await page.getByRole('button', { name: 'Continue', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Save reviewed Automation' })).toBeEnabled();
    await page.getByRole('button', { name: 'Edit configuration' }).click();
    await page.getByLabel('Run Page Cap', { exact: true }).fill('30');
    await page.getByRole('button', { name: 'Continue', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Save reviewed Automation' })).toBeEnabled();
    await page.screenshot({ path: `${evidence}/after-review-${size.width}.png`, fullPage: true });
    await page.getByRole('button', { name: 'Save reviewed Automation' }).click();
    await expect(page.getByText(/Paused — no scheduled runs/)).toBeVisible();
    expect(requests.filter(r => r.method === 'PUT')[0].body.configuration).toMatchObject({ name: 'Evening listings', listing_settings: { run_page_cap: 30 } });
    expect(requests.filter(r => r.method === 'PUT')[0].body).not.toHaveProperty('initial_state');
    await page.getByRole('button', { name: 'Back to board', exact: true }).click();
    await expect(page).toHaveURL(/#scheduler\?source=jobsdb$/);
    expect(errors).toEqual([]);
  });
}

test('new Automation and one-off follow guided scope, review, and exact task handoff', async ({ page }) => {
  const requests = await interceptScheduler(page);
  await page.goto('/#scheduler');
  await page.getByRole('button', { name: 'New Automation', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'New Automation', exact: true })).toBeVisible();
  await page.screenshot({ path: `${evidence}/after-wizard-1280.png`, fullPage: true });
  await page.getByRole('button', { name: 'Discover listings', exact: false }).click();
  await page.getByRole('button', { name: 'Continue', exact: true }).click();
  await page.getByRole('button', { name: 'All major categories', exact: true }).click();
  await page.getByRole('button', { name: 'Continue', exact: true }).click();
  await page.getByLabel('Name', { exact: true }).fill('New schedule');
  await page.getByRole('button', { name: 'Continue', exact: true }).click();
  await page.getByRole('button', { name: 'Save reviewed Automation' }).click();
  await expect(page.getByText(/Paused — no scheduled runs/)).toBeVisible();
  await page.getByRole('button', { name: 'Back to board', exact: true }).click();
  await page.getByRole('button', { name: 'One-off Run', exact: true }).click();
  await page.getByRole('button', { name: /Discover listings now/ }).click();
  await page.getByRole('button', { name: 'Continue', exact: true }).click();
  await page.getByRole('button', { name: 'All major categories', exact: true }).click();
  await page.getByRole('button', { name: 'Continue', exact: true }).click();
  await page.getByRole('button', { name: 'Continue', exact: true }).click();
  await page.getByRole('button', { name: 'Confirm and start' }).click();
  await expect(page.getByRole('heading', { name: 'Run request accepted.' })).toBeVisible();
  await expect(page.getByRole('link', { name: 'View task' })).toHaveAttribute('href', '#crawl-tasks?task=created-task');
  expect(requests.filter(r => /\/dispatch$/.test(r.path))).toHaveLength(1);
  await expect(page.getByRole('button', { name: 'Confirm and start' })).toHaveCount(0);
});

test('run saved settings or create an independent one-off, retaining source on return', async ({ page }) => {
  const requests = await interceptScheduler(page);
  await page.goto('/#scheduler');
  await page.getByRole('button', { name: 'Run now', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Confirm and start' })).toBeEnabled();
  await expect(page.getByRole('button', { name: 'Run saved configuration', exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: 'Run with changes' }).click();
  await expect(page).toHaveURL(/scheduler\/one-off\/new/);
  expect(requests.some(r => r.method === 'PUT')).toBe(false);
  await page.goto('/#scheduler?source=offertoday');
  await page.getByRole('button', { name: 'One-off Run', exact: true }).click();
  await expect(page.getByLabel('Source', { exact: true })).toHaveValue('offertoday');
  await page.getByRole('button', { name: /Back to board/ }).click();
  await expect(page).toHaveURL(/#scheduler\?source=offertoday$/);
});

test('narrow board and keyboard step navigation remain usable', async ({ page }) => {
  await interceptScheduler(page);
  await page.setViewportSize({ width: 760, height: 900 });
  await page.goto('/#scheduler');
  await expect(page.getByRole('heading', { name: 'Morning listings' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByRole('button', { name: 'Edit', exact: true }).click();
  await expect(page.getByLabel('Name', { exact: true })).toBeEnabled();
  const taskStep = page.getByRole('button', { name: '1 Choose task' });
  await taskStep.focus();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('heading', { name: 'Choose task' })).toBeFocused();
  await expect(page).toHaveURL(/step=intent$/);
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  await page.goBack();
  await expect(page.getByLabel('Name', { exact: true })).toHaveValue('Morning listings');
});
