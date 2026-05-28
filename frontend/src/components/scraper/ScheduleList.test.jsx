import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import ScheduleList from './ScheduleList';

describe('ScheduleList', () => {
  it('renders schedules in operator priority order: active with nearest next run first, then inactive by recent history', () => {
    render(
      <ScheduleList
        currentSourceSite="jobsdb"
        schedules={[
          {
            id: 'inactive-older',
            name: 'Delta Paused',
            cron_expression: '0 2 * * *',
            category_ids: [1200],
            source_site: 'jobsdb',
            crawl_phase: 'listing',
            crawl_mode: 'headed',
            is_active: false,
            last_run_at: '2026-05-26T08:00:00Z',
            next_run_at: null,
          },
          {
            id: 'active-later',
            name: 'Alpha Nightly',
            cron_expression: '0 2 * * *',
            category_ids: [1200],
            source_site: 'jobsdb',
            crawl_phase: 'listing',
            crawl_mode: 'headed',
            is_active: true,
            last_run_at: '2026-05-27T08:00:00Z',
            next_run_at: '2026-05-29T02:00:00Z',
          },
          {
            id: 'active-no-next',
            name: 'Beta Nightly',
            cron_expression: '0 2 * * *',
            category_ids: [1200],
            source_site: 'jobsdb',
            crawl_phase: 'listing',
            crawl_mode: 'headed',
            is_active: true,
            last_run_at: '2026-05-27T09:00:00Z',
            next_run_at: null,
          },
          {
            id: 'active-sooner',
            name: 'Zulu Nightly',
            cron_expression: '0 2 * * *',
            category_ids: [1200],
            source_site: 'jobsdb',
            crawl_phase: 'listing',
            crawl_mode: 'headed',
            is_active: true,
            last_run_at: '2026-05-27T10:00:00Z',
            next_run_at: '2026-05-28T02:00:00Z',
          },
          {
            id: 'inactive-recent',
            name: 'Gamma Paused',
            cron_expression: '0 2 * * *',
            category_ids: [1200],
            source_site: 'jobsdb',
            crawl_phase: 'listing',
            crawl_mode: 'headed',
            is_active: false,
            last_run_at: '2026-05-28T08:00:00Z',
            next_run_at: null,
          },
        ]}
        onToggle={vi.fn()}
        onDelete={vi.fn()}
        onRun={vi.fn()}
        onViewHistory={vi.fn()}
        isLoading={false}
      />,
    );

    const titles = screen.getAllByRole('heading', { level: 4 }).map((node) => node.textContent);

    expect(titles).toEqual([
      'Zulu Nightly',
      'Alpha Nightly',
      'Beta Nightly',
      'Gamma Paused',
      'Delta Paused',
    ]);
  });
});
