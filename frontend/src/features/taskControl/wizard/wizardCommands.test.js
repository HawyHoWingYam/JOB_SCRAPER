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

  it('accepts one OfferToday category and leaves adaptive cap review to the server', () => {
    const offerClassifications = {
      sourceSite: 'offertoday',
      classifications: [
        { id: 'offertoday:118000', label: 'Information Technology', active: true },
        { id: 'offertoday:119000', label: 'Sales', active: true },
      ],
    };
    const offerDraft = {
      ...listingDraft(),
      flow: 'one_off',
      source_site: 'offertoday',
      scope: { mode: 'selected', classification_ids: ['offertoday:118000'] },
      execution: { crawl_mode: 'headless', page_depth: 100, run_page_cap: 3600 },
    };
    expect(buildOneOffRun(offerDraft, offerClassifications).listing_settings).toMatchObject({
      page_depth: 100,
      run_page_cap: 3600,
    });
    expect(() => buildOneOffRun({
      ...offerDraft,
      scope: {
        mode: 'selected',
        classification_ids: ['offertoday:118000', 'offertoday:119000'],
      },
    }, offerClassifications)).toThrow(/exactly one/);
    expect(() => buildOneOffRun({
      ...offerDraft,
      scope: { mode: 'all', classification_ids: [] },
    }, offerClassifications)).toThrow(/exactly one/);
    expect(buildOneOffRun({
      ...offerDraft,
      execution: { ...offerDraft.execution, run_page_cap: 3599 },
    }, offerClassifications).listing_settings.run_page_cap).toBe(3599);
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
