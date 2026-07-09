import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';

function timestampSlug(date = new Date()) {
  return date.toISOString().replace(/[:.]/g, '-');
}

export async function writeSmokeArtifacts({
  artifactsDir,
  scenario,
  summary,
  page,
  eventLog = [],
}) {
  const outputDir = path.resolve(artifactsDir || '../.tmp/live-smoke');
  await mkdir(outputDir, { recursive: true });

  const fileBase = `${timestampSlug()}-${scenario.source}-${scenario.phase}`;
  const screenshotPath = path.join(outputDir, `${fileBase}.png`);
  const summaryPath = path.join(outputDir, `${fileBase}.json`);
  const eventLogPath = path.join(outputDir, `${fileBase}.events.json`);

  if (page) {
    await page.screenshot({ path: screenshotPath, fullPage: true });
  }

  await writeFile(
    summaryPath,
    `${JSON.stringify({ ...summary, screenshot_path: screenshotPath }, null, 2)}\n`,
    'utf8'
  );
  await writeFile(eventLogPath, `${JSON.stringify(eventLog, null, 2)}\n`, 'utf8');

  return {
    outputDir,
    screenshotPath,
    summaryPath,
    eventLogPath,
  };
}
