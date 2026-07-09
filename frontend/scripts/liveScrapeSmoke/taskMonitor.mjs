import { isTerminalTaskStatus } from './outcomeClassifier.mjs';
import { openCrawlTasks } from './uiDriver.mjs';

function normalizeToken(value) {
  return `${value || ''}`
    .trim()
    .toLowerCase()
    .replace(/\s+/g, '_');
}

async function readTestIdText(page, testId) {
  const locator = page.getByTestId(testId);
  if ((await locator.count()) === 0) {
    return null;
  }
  return `${(await locator.textContent()) || ''}`.trim() || null;
}

async function readSelectedTaskStatus(page) {
  const statusLabel = page.locator('.crawl-tasks-detail-grid dd').first();
  if ((await statusLabel.count()) === 0) {
    return null;
  }
  return normalizeToken(await statusLabel.textContent());
}

export async function waitForTaskToSettle(page, scenario, { crawlJobId, timeoutMs, pollMs = 3000 }) {
  const deadline = Date.now() + timeoutMs;
  await openCrawlTasks(page, scenario);
  await page.getByTestId('crawl-tasks-filter-source').selectOption(scenario.source);

  while (Date.now() < deadline) {
    const refreshButton = page.getByRole('button', { name: /refresh/i });
    if ((await refreshButton.count()) > 0) {
      await refreshButton.click();
    }

    const taskRow = page.getByTestId(`crawl-task-row-${crawlJobId}`);
    if ((await taskRow.count()) > 0) {
      await taskRow.click();

      const taskSnapshot = {
        crawlJobId,
        status: await readSelectedTaskStatus(page),
        issueClass: normalizeToken(await readTestIdText(page, 'crawl-task-issue-class')),
        issueCode: normalizeToken(await readTestIdText(page, 'crawl-task-issue-code')),
        issueStage: normalizeToken(await readTestIdText(page, 'crawl-task-issue-stage')),
        latestIssueText: await readTestIdText(page, 'crawl-task-latest-issue-text'),
      };

      if (taskSnapshot.issueClass === 'none') {
        taskSnapshot.issueClass = null;
      }
      if (taskSnapshot.issueCode === 'none') {
        taskSnapshot.issueCode = null;
      }
      if (taskSnapshot.issueStage === 'none') {
        taskSnapshot.issueStage = null;
      }

      if (isTerminalTaskStatus(taskSnapshot.status)) {
        return taskSnapshot;
      }
    }

    await page.waitForTimeout(pollMs);
  }

  throw new Error(
    `Timed out waiting for crawl task ${crawlJobId} to settle for ${scenario.source} ${scenario.phase}`
  );
}
