import process from 'node:process';

import { chromium } from 'playwright';

import { buildScenario, buildScenarioMatrix } from './scenarioMatrix.mjs';
import { classifyOutcome } from './outcomeClassifier.mjs';
import { writeSmokeArtifacts } from './reportWriter.mjs';
import {
  handleManualAction,
  launchDetailFromScheduler,
  launchListingFromScheduler,
} from './uiDriver.mjs';
import { waitForTaskToSettle } from './taskMonitor.mjs';

const EXIT_FAILURE_ISSUE_CLASSES = new Set(['infrastructure_failure', 'unknown_failure']);

function parseArgs(argv) {
  const options = {
    baseUrl: process.env.LIVE_SMOKE_BASE_URL || 'http://127.0.0.1:5173',
    artifactsDir: '../.tmp/live-smoke',
    allowManualRecovery: false,
    matrix: false,
    headless: process.env.PLAYWRIGHT_HEADLESS === '1',
    timeoutMs: undefined,
  };

  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];

    if (argument === '--matrix') {
      options.matrix = true;
      continue;
    }
    if (argument === '--allow-manual') {
      options.allowManualRecovery = true;
      continue;
    }
    if (argument === '--headless') {
      options.headless = true;
      continue;
    }

    const nextValue = argv[index + 1];
    if (nextValue == null) {
      throw new Error(`Missing value for ${argument}`);
    }

    switch (argument) {
      case '--source':
        options.source = nextValue;
        index += 1;
        break;
      case '--phase':
        options.phase = nextValue;
        index += 1;
        break;
      case '--base-url':
        options.baseUrl = nextValue;
        index += 1;
        break;
      case '--artifacts-dir':
        options.artifactsDir = nextValue;
        index += 1;
        break;
      case '--timeout-ms':
        options.timeoutMs = Number(nextValue);
        index += 1;
        break;
      default:
        throw new Error(`Unknown argument: ${argument}`);
    }
  }

  if (!options.matrix && (!options.source || !options.phase)) {
    throw new Error('Single-run mode requires --source and --phase');
  }

  return options;
}

async function runScenario(browser, scenario) {
  const context = await browser.newContext();
  const page = await context.newPage();
  const eventLog = [];
  const summary = {
    source: scenario.source,
    phase: scenario.phase,
    crawl_job_id: null,
    final_status: 'not_started',
    issue_class: 'infrastructure_failure',
  };

  const appendEvent = (step, detail = {}) => {
    eventLog.push({
      at: new Date().toISOString(),
      step,
      detail,
    });
  };

  try {
    appendEvent('scenario.started', {
      source: scenario.source,
      phase: scenario.phase,
      baseUrl: scenario.baseUrl,
    });

    let listingLaunch = null;
    let taskSnapshot = null;
    if (scenario.phase === 'detail') {
      appendEvent('listing.bootstrap_requested');
      listingLaunch = await launchListingFromScheduler(page, scenario);
      summary.crawl_job_id = listingLaunch.crawlJobId;
      appendEvent('listing.launched', listingLaunch);

      const listingTask = await waitForTaskToSettle(page, scenario, {
        crawlJobId: listingLaunch.crawlJobId,
        timeoutMs: scenario.timeoutMs,
      });
      appendEvent('listing.settled', listingTask);

      const listingOutcome = classifyOutcome(listingTask);
      if (listingOutcome !== 'success') {
        taskSnapshot = listingTask;
      }
    }

    if (!taskSnapshot) {
      const launchResult =
        scenario.phase === 'detail'
          ? await launchDetailFromScheduler(page, scenario, {
              listingBatchId: listingLaunch?.crawlJobId,
            })
          : await launchListingFromScheduler(page, scenario);
      summary.crawl_job_id = launchResult.crawlJobId;
      appendEvent('crawl.launched', launchResult);

      taskSnapshot = await waitForTaskToSettle(page, scenario, {
        crawlJobId: launchResult.crawlJobId,
        timeoutMs: scenario.timeoutMs,
      });
      appendEvent('crawl.settled', taskSnapshot);

      if (taskSnapshot.status === 'manual_action_required' && scenario.allowManualRecovery) {
        const manualActionOutcome = await handleManualAction(page, scenario);
        appendEvent('manual_action.handled', { outcome: manualActionOutcome });

        taskSnapshot = await waitForTaskToSettle(page, scenario, {
          crawlJobId: launchResult.crawlJobId,
          timeoutMs: scenario.timeoutMs,
        });
        appendEvent('crawl.settled_after_manual_action', taskSnapshot);
      }
    }

    summary.final_status = taskSnapshot.status;
    summary.issue_class = classifyOutcome(taskSnapshot);
    summary.issue_code = taskSnapshot.issueCode || null;
    summary.issue_stage = taskSnapshot.issueStage || null;
    summary.latest_issue_text = taskSnapshot.latestIssueText || null;
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    summary.final_status = 'failed';
    summary.issue_class = 'infrastructure_failure';
    summary.latest_issue_text = detail;
    appendEvent('scenario.failed', { detail });
  }

  const artifactPaths = await writeSmokeArtifacts({
    artifactsDir: scenario.artifactsDir,
    scenario,
    summary,
    page,
    eventLog,
  });

  await context.close();
  return {
    ...summary,
    ...artifactPaths,
  };
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const scenarios = options.matrix
    ? buildScenarioMatrix(options)
    : [buildScenario(options)];

  const browser = await chromium.launch({
    headless: options.headless,
  });

  const results = [];
  try {
    for (const scenario of scenarios) {
      const result = await runScenario(browser, scenario);
      results.push(result);
      process.stdout.write(`${JSON.stringify(result)}\n`);
    }
  } finally {
    await browser.close();
  }

  const hasFailures = results.some((result) =>
    EXIT_FAILURE_ISSUE_CLASSES.has(result.issue_class)
  );
  if (hasFailures) {
    process.exitCode = 1;
  }
}

await main();
