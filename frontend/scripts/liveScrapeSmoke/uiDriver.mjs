function escapeRegExp(value) {
  return `${value}`.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

async function ensureDirectOverridePanel(page) {
  const phaseSelect = page.getByTestId('direct-override-phase');
  if (await phaseSelect.count()) {
    return;
  }

  await page.getByTestId('direct-override-toggle').click();
  await phaseSelect.waitFor();
}

async function waitForEnabled(locator, timeoutMs = 10000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (!(await locator.isDisabled())) {
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`Timed out waiting for ${await locator.getAttribute('data-testid')} to enable`);
}

async function selectPreferredCategories(page, preferredLabels = []) {
  if (!preferredLabels.length) {
    return null;
  }

  const deadline = Date.now() + 10000;

  while (Date.now() < deadline) {
    for (const label of preferredLabels) {
      const checkbox = page.getByRole('checkbox', {
        name: new RegExp(escapeRegExp(label), 'i'),
      });
      if ((await checkbox.count()) === 0) {
        continue;
      }
      await checkbox.first().check();
      return label;
    }

    await page.waitForTimeout(250);
  }

  throw new Error(
    `Unable to locate preferred categories for live smoke: ${preferredLabels.join(', ')}`
  );
}

async function launchCrawlFromScheduler(page, scenario, phase, { listingBatchId } = {}) {
  await page.goto(`${scenario.baseUrl}/#scheduler`, { waitUntil: 'domcontentloaded' });
  await page.getByTestId('scheduler-source-site').waitFor();
  await page.getByTestId('scheduler-source-site').selectOption(scenario.source);
  await ensureDirectOverridePanel(page);
  await page.getByTestId('direct-override-phase').selectOption(phase);
  await page.getByTestId('direct-override-mode').selectOption(scenario.crawlMode);
  await page.getByTestId('direct-override-limit').fill(
    String(phase === 'detail' ? scenario.detailLimit : scenario.maxPages)
  );

  if (!scenario.leaveCategoriesBlank) {
    await selectPreferredCategories(page, scenario.preferredCategoryLabels);
  }

  if (phase === 'detail' && listingBatchId) {
    const listingBatchSelect = page.getByTestId('direct-override-listing-batch');
    if ((await listingBatchSelect.count()) > 0) {
      await listingBatchSelect.selectOption(listingBatchId);
    }
  }

  const startButton = page.getByTestId('direct-override-start');
  await waitForEnabled(startButton);

  const [response] = await Promise.all([
    page.waitForResponse(
      (response) =>
        response.url().endsWith('/api/v1/crawl-jobs') &&
        response.request().method() === 'POST'
    ),
    startButton.click(),
  ]);
  const responseHeaders = response.headers();

  if (!response.ok()) {
    let detail = `${response.status()} ${response.statusText()}`;
    try {
      const payload = await response.json();
      detail = payload?.detail || payload?.message || detail;
    } catch {
      // Ignore non-JSON bodies and preserve the HTTP detail.
    }
    throw new Error(`Failed to launch ${scenario.source} ${phase} smoke: ${detail}`);
  }

  const crawlJobId = responseHeaders['x-crawl-job-id'] || responseHeaders['X-Crawl-Job-Id'];
  if (!crawlJobId) {
    throw new Error(`Missing X-Crawl-Job-Id header for ${scenario.source} ${phase} smoke`);
  }

  return { crawlJobId };
}

function waitForOperatorContinue(message) {
  process.stdout.write(`${message}\nPress Enter to continue...\n`);
  return new Promise((resolve) => {
    process.stdin.resume();
    process.stdin.once('data', () => {
      process.stdin.pause();
      resolve();
    });
  });
}

export async function launchListingFromScheduler(page, scenario) {
  return launchCrawlFromScheduler(page, scenario, 'listing');
}

export async function launchDetailFromScheduler(page, scenario, { listingBatchId }) {
  return launchCrawlFromScheduler(page, scenario, 'detail', { listingBatchId });
}

export async function openCrawlTasks(page, scenario) {
  await page.goto(`${scenario.baseUrl}/#crawl-tasks`, { waitUntil: 'domcontentloaded' });
  await page.getByTestId('crawl-tasks-filter-source').waitFor();
}

export async function handleManualAction(page, scenario) {
  if (!scenario.allowManualRecovery) {
    return 'manual_action_required';
  }

  if ((await page.getByTestId('crawl-task-open-browser').count()) > 0) {
    await page.getByTestId('crawl-task-open-browser').click();
  }

  await waitForOperatorContinue(
    `Complete the manual browser action for ${scenario.source} ${scenario.phase}, then resume here.`
  );

  if ((await page.getByTestId('crawl-task-resume-open-browser').count()) > 0) {
    await page.getByTestId('crawl-task-resume-open-browser').click();
    return 'resume_requested';
  }

  return 'manual_action_required';
}
