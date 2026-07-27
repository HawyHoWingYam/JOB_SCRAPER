import { describe, expect, it } from 'vitest';
import {
  buildAutomationConfiguration,
  buildOneOffRun,
  pairedDetailDraft,
} from './wizardCommands';

const classifications = {
  sourceSite: 'jobsdb',
  classifications: [
    { id: 'jobsdb:6281', label: 'Information Technology', active: true },
  ],
};

function listingDraft() {
  return {
    flow: 'automation', mode: 'create', automation_id: null,
    source_site: 'jobsdb', intent: 'listing',
    scope: { mode: 'all', classification_ids: [] },
    execution: { crawl_mode: 'headless', page_depth: 2, run_page_cap: 50 },
    schedule: {
      name: 'JobsDB listing', description: '', cron_expression: '0 4 * * *',
      timezone: 'Asia/Hong_Kong', initial_state: 'paused',
    },
  };
}

describe('wizard command builders', () => {
  it('emits an ordinary all-category listing command', () => {
    const configuration = buildAutomationConfiguration(listingDraft(), classifications);
    expect(configuration.scope).toEqual({
      source_site: 'jobsdb', mode: 'all', classification_ids: [],
    });
    expect(configuration.listing_settings.run_page_cap).toBe(50);
    expect(configuration.detail_settings).toBeNull();
  });

  it('rejects empty and cross-source scope and preserves explicit CTgoodjobs mode', () => {
    const empty = { ...listingDraft(), scope: { mode: 'selected', classification_ids: [] } };
    expect(() => buildOneOffRun(empty, classifications)).toThrow(/Choose all categories/);
    const crossSource = { ...listingDraft(), source_site: 'offertoday' };
    expect(() => buildOneOffRun(crossSource, classifications)).toThrow(/Source must agree/);
    const ctClassifications = {
      sourceSite: 'ctgoodjobs',
      classifications: [],
    };
    const ct = { ...listingDraft(), flow: 'one_off', source_site: 'ctgoodjobs' };
    expect(buildOneOffRun(ct, ctClassifications).listing_settings.crawl_mode).toBe('headless');
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
