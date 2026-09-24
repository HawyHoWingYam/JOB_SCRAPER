import { expect, test } from '@playwright/test';


test('manually starts and completes a source-preserving duplicate batch', async ({
  page,
  request,
}) => {
  const seededResponse = await request.post(
    'http://127.0.0.1:18001/fake/seed-duplicate-pair/8',
  );
  expect(seededResponse.ok()).toBeTruthy();
  const seeded = await seededResponse.json();
  const settings = await request.put(
    'http://127.0.0.1:18001/api/settings/ai',
    {
      data: {
        jev: {
          enabled: true,
          endpoint: 'http://127.0.0.1:18001/fake/systemone',
          api_key: 'operations-e2e-secret',
          duplicate_enabled: true,
          duplicate_candidate_limit: 1,
          duplicate_corpus_limit: 100,
        },
      },
    },
  );
  expect(settings.ok()).toBeTruthy();
  await request.post('http://127.0.0.1:18001/fake/mode/normal');

  const before = await request.get('http://127.0.0.1:18001/fake/requests');
  const beforeCount = (await before.json()).count;

  await page.goto('/#jev');
  await expect(page.getByRole('heading', { name: 'Jev Operations', exact: true })).toBeVisible();
  await page.getByLabel('Skills correction').uncheck();
  await page.getByLabel('Possible same vacancy').check();
  await page.getByLabel('Explicit Job UUIDs').fill(seeded.left_job_id);
  await page.getByRole('button', { name: 'Start Jev batch…' }).click();
  await expect(page.getByRole('dialog')).toContainText('Possible same vacancy');
  const beforeConfirmation = await request.get('http://127.0.0.1:18001/fake/requests');
  expect((await beforeConfirmation.json()).count).toBe(beforeCount);
  await page.getByRole('dialog').getByRole('button', { name: 'Confirm and start' }).click();
  const batch = page.getByLabel(/Jev batch /).first();
  await expect(batch).toContainText('completed', { timeout: 30_000 });
  await expect(batch).toContainText('1 of 1 finished');
  await expect(batch).toContainText('Possible same vacancy');

  const afterStart = await request.get('http://127.0.0.1:18001/fake/requests');
  const providerAudit = await afterStart.json();
  expect(providerAudit.count).toBe(beforeCount + 1);
  expect(providerAudit.requests.at(-1)).toEqual(expect.objectContaining({
    path: '/fake/systemone',
    has_bearer: true,
    question_names: ['decision'],
  }));

  await page.goto('/#jobs');
  await page.getByRole('button', {
    name: 'View Senior Backend Engineer E2E 8 at Duplicate E2E Company 8',
  }).click();
  await expect(page.getByText('ctgoodjobs:e2e-duplicate-right-8')).toBeVisible();
  await expect(page.getByText('Jev proposal — pending review')).toBeVisible();
  await page.getByRole('button', { name: 'Confirm association' }).click();
  await expect(page.getByText('Confirmed same vacancy')).toBeVisible();
  await expect(page.getByText(/both source Jobs remain available/i)).toBeVisible();
});
