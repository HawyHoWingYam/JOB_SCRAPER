import { describe, expect, it } from 'vitest';
import {
  buildAutomationConfiguration,
  buildOneOffRun,
  pairedDetailDraft,
} from './wizardCommands';

const published = {
  revision: { id: 'revision-1', sourceSite: 'jobsdb' },
  catalog: {
    sourceSite: 'jobsdb',
    capabilities: { supportsAllScope: true },
  },
};

function listingDraft() {
  return {
    flow: 'automation', mode: 'create', automation_id: null,
    expected_revision: null, source_site: 'jobsdb', intent: 'listing',
    scope: { mode: 'all', rules: [] },
    execution: { crawl_mode: 'headless', page_depth: 2, run_page_cap: 50 },
    schedule: {
      name: 'JobsDB listing', description: '', cron_expression: '0 4 * * *',
      timezone: 'Asia/Hong_Kong', initial_state: 'paused',
    },
  };
}

describe('wizard command builders', () => {
  it('emits an explicit reviewed listing command', () => {
    const configuration = buildAutomationConfiguration(listingDraft(), published);
    expect(configuration.scope).toEqual({
      version: 1, source_site: 'jobsdb', reviewed_catalog_revision_id: 'revision-1',
      mode: 'all', rules: [],
    });
    expect(configuration.listing_settings.run_page_cap).toBe(50);
    expect(configuration.detail_settings).toBeNull();
  });

  it('rejects empty and cross-source scope and preserves explicit CTgoodjobs mode', () => {
    const empty = { ...listingDraft(), scope: { mode: 'rules', rules: [] } };
    expect(() => buildOneOffRun(empty, published)).toThrow(/Choose explicit all/);
    const crossSource = { ...listingDraft(), source_site: 'offertoday' };
    expect(() => buildOneOffRun(crossSource, published)).toThrow(/Source must agree/);
    const ctPublished = {
      revision: { id: 'revision-ct', sourceSite: 'ctgoodjobs' },
      catalog: { sourceSite: 'ctgoodjobs', capabilities: { supportsAllScope: true } },
    };
    const ct = { ...listingDraft(), flow: 'one_off', source_site: 'ctgoodjobs' };
    expect(buildOneOffRun(ct, ctPublished).listing_settings.crawl_mode).toBe('headless');
  });

  it('paired detail draft copies no plan or runtime authority', () => {
    const draft = { ...listingDraft(), plan_id: 'plan-1', runtime: { status: 'running' } };
    const paired = pairedDetailDraft(draft);
    expect(paired.intent).toBe('detail');
    expect(paired.execution.backlog_kind).toBe('crawl_scope');
    expect(paired.execution.plan_id).toBeUndefined();
    expect(paired.execution.runtime).toBeUndefined();
  });
});
