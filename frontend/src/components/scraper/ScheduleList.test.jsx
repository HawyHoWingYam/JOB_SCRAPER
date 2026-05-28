import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import ScheduleList from './ScheduleList';

describe('ScheduleList', () => {
  it('renders active schedules first and keeps names alphabetized within each activity group', () => {
    render(
      <ScheduleList
        currentSourceSite="jobsdb"
        schedules={[
          {
            id: 'inactive-zulu',
            name: 'Zulu Nightly',
            cron_expression: '0 2 * * *',
            category_ids: [1200],
            source_site: 'jobsdb',
            crawl_phase: 'listing',
            crawl_mode: 'headed',
            is_active: false,
            last_run_at: null,
            next_run_at: null,
          },
          {
            id: 'active-beta',
            name: 'Beta Nightly',
            cron_expression: '0 2 * * *',
            category_ids: [1200],
            source_site: 'jobsdb',
            crawl_phase: 'listing',
            crawl_mode: 'headed',
            is_active: true,
            last_run_at: null,
            next_run_at: null,
          },
          {
            id: 'active-alpha',
            name: 'Alpha Nightly',
            cron_expression: '0 2 * * *',
            category_ids: [1200],
            source_site: 'jobsdb',
            crawl_phase: 'listing',
            crawl_mode: 'headed',
            is_active: true,
            last_run_at: null,
            next_run_at: null,
          },
          {
            id: 'inactive-gamma',
            name: 'Gamma Nightly',
            cron_expression: '0 2 * * *',
            category_ids: [1200],
            source_site: 'jobsdb',
            crawl_phase: 'listing',
            crawl_mode: 'headed',
            is_active: false,
            last_run_at: null,
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
      'Alpha Nightly',
      'Beta Nightly',
      'Gamma Nightly',
      'Zulu Nightly',
    ]);
  });
});
