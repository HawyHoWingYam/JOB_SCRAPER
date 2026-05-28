import { render, screen, within } from '@testing-library/react';
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

  it('shows explicit run-state labels and timing placeholders instead of ambiguous dashes', () => {
    render(
      <ScheduleList
        currentSourceSite="jobsdb"
        schedules={[
          {
            id: 'active-never-run',
            name: 'Fresh Active',
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
            id: 'inactive-never-run',
            name: 'Fresh Paused',
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

    const cards = screen.getAllByText(/fresh /i).map((node) => node.closest('.schedule-card'));
    expect(cards[0]).not.toBeNull();
    expect(cards[1]).not.toBeNull();

    expect(within(cards[0]).getByText('Active')).toBeInTheDocument();
    expect(within(cards[0]).getByText('Never')).toBeInTheDocument();
    expect(within(cards[0]).getByText('Pending scheduler')).toBeInTheDocument();

    expect(within(cards[1]).getAllByText('Paused').length).toBeGreaterThanOrEqual(2);
    expect(within(cards[1]).getByText('Never')).toBeInTheDocument();
  });

  it('shows relative run timing hints for schedules with real timestamps', () => {
    vi.spyOn(Date, 'now').mockReturnValue(new Date('2026-05-28T00:00:00Z').getTime());

    render(
      <ScheduleList
        currentSourceSite="jobsdb"
        schedules={[
          {
            id: 'active-timing',
            name: 'Timing Focus',
            cron_expression: '0 2 * * *',
            category_ids: [1200],
            source_site: 'jobsdb',
            crawl_phase: 'listing',
            crawl_mode: 'headed',
            is_active: true,
            last_run_at: '2026-05-27T18:00:00Z',
            next_run_at: '2026-05-28T12:00:00Z',
          },
        ]}
        onToggle={vi.fn()}
        onDelete={vi.fn()}
        onRun={vi.fn()}
        onViewHistory={vi.fn()}
        isLoading={false}
      />,
    );

    const card = screen.getByRole('heading', { level: 4, name: 'Timing Focus' }).closest('.schedule-card');
    expect(card).not.toBeNull();
    expect(within(card).getByText('6h ago')).toBeInTheDocument();
    expect(within(card).getByText('In 12h')).toBeInTheDocument();
  });

  it('shows readable sector summaries instead of only raw category counts', () => {
    render(
      <ScheduleList
        currentSourceSite="jobsdb"
        categories={[
          { id: 1200, name: 'Engineering' },
          { id: 1300, name: 'Marketing' },
          { id: 1400, name: 'Design' },
        ]}
        schedules={[
          {
            id: 'summary-target',
            name: 'Sector Rich',
            cron_expression: '0 2 * * *',
            category_ids: [1200, 1300, 1400],
            source_site: 'jobsdb',
            crawl_phase: 'listing',
            crawl_mode: 'headed',
            is_active: true,
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

    const card = screen.getByRole('heading', { level: 4, name: 'Sector Rich' }).closest('.schedule-card');
    expect(card).not.toBeNull();
    expect(within(card).getByText('Engineering, Marketing, +1 more')).toBeInTheDocument();
  });

  it('shows the latest execution outcome and recent volume on the schedule card', () => {
    vi.spyOn(Date, 'now').mockReturnValue(new Date('2026-05-28T12:00:00Z').getTime());

    render(
      <ScheduleList
        currentSourceSite="jobsdb"
        schedules={[
          {
            id: 'outcome-rich',
            name: 'Outcome Focus',
            cron_expression: '0 2 * * *',
            category_ids: [1200],
            source_site: 'jobsdb',
            crawl_phase: 'listing',
            crawl_mode: 'headed',
            is_active: true,
            last_run_at: '2026-05-28T08:00:00Z',
            next_run_at: '2026-05-29T08:00:00Z',
            latest_execution_status: 'completed_with_ai_failures',
            latest_execution_started_at: '2026-05-28T08:00:00Z',
            latest_execution_completed_at: '2026-05-28T08:05:00Z',
            latest_execution_jobs_scraped: 12,
            latest_execution_jobs_saved: 11,
          },
        ]}
        onToggle={vi.fn()}
        onDelete={vi.fn()}
        onRun={vi.fn()}
        onViewHistory={vi.fn()}
        isLoading={false}
      />,
    );

    const card = screen.getByRole('heading', { level: 4, name: 'Outcome Focus' }).closest('.schedule-card');
    expect(card).not.toBeNull();
    expect(within(card).getByText('Last outcome')).toBeInTheDocument();
    const outcomeSummary = within(card).getByText('Last outcome').closest('.schedule-execution-summary');
    expect(outcomeSummary).not.toBeNull();
    expect(within(outcomeSummary).getByText('Completed With AI Failures')).toBeInTheDocument();
    expect(within(outcomeSummary).getByText('12 scraped / 11 ingested')).toBeInTheDocument();
    expect(within(outcomeSummary).getByText('4h ago')).toBeInTheDocument();
  });

  it('shows dead-lettered totals in the latest execution summary when ingest settled with failures', () => {
    vi.spyOn(Date, 'now').mockReturnValue(new Date('2026-05-28T12:00:00Z').getTime());

    render(
      <ScheduleList
        currentSourceSite="ctgoodjobs"
        schedules={[
          {
            id: 'outcome-dead-letter',
            name: 'CTGoodJobs Recovery',
            cron_expression: '0 2 * * *',
            category_ids: ['ctgoodjobs:021'],
            source_site: 'ctgoodjobs',
            crawl_phase: 'detail',
            crawl_mode: 'headed',
            is_active: true,
            last_run_at: '2026-05-28T08:00:00Z',
            next_run_at: '2026-05-29T08:00:00Z',
            latest_execution_status: 'completed',
            latest_execution_started_at: '2026-05-28T08:00:00Z',
            latest_execution_completed_at: '2026-05-28T08:05:00Z',
            latest_execution_jobs_scraped: 100,
            latest_execution_jobs_saved: 30,
            latest_execution_jobs_dead_lettered: 70,
          },
        ]}
        onToggle={vi.fn()}
        onDelete={vi.fn()}
        onRun={vi.fn()}
        onViewHistory={vi.fn()}
        isLoading={false}
      />,
    );

    const card = screen.getByRole('heading', { level: 4, name: 'CTGoodJobs Recovery' }).closest('.schedule-card');
    expect(card).not.toBeNull();
    const outcomeSummary = within(card).getByText('Last outcome').closest('.schedule-execution-summary');
    expect(outcomeSummary).not.toBeNull();
    expect(within(outcomeSummary).getByText('100 scraped / 30 ingested / 70 dead-lettered')).toBeInTheDocument();
  });

  it('shows staged backlog totals for listing runs instead of empty scraped/ingested counts', () => {
    vi.spyOn(Date, 'now').mockReturnValue(new Date('2026-05-28T12:00:00Z').getTime());

    render(
      <ScheduleList
        currentSourceSite="jobsdb"
        schedules={[
          {
            id: 'outcome-backlog',
            name: 'JobsDB ICT E2E',
            cron_expression: '0 2 * * *',
            category_ids: [6281],
            source_site: 'jobsdb',
            crawl_phase: 'listing',
            crawl_mode: 'headed',
            is_active: false,
            last_run_at: '2026-05-28T08:00:00Z',
            next_run_at: null,
            latest_execution_status: 'completed',
            latest_execution_started_at: '2026-05-28T08:00:00Z',
            latest_execution_completed_at: '2026-05-28T08:05:00Z',
            latest_execution_jobs_scraped: 0,
            latest_execution_jobs_saved: 0,
            latest_execution_listings_staged: 96,
            latest_execution_detail_pending: 89,
            latest_execution_detail_completed: 7,
          },
        ]}
        onToggle={vi.fn()}
        onDelete={vi.fn()}
        onRun={vi.fn()}
        onViewHistory={vi.fn()}
        isLoading={false}
      />,
    );

    const card = screen.getByRole('heading', { level: 4, name: 'JobsDB ICT E2E' }).closest('.schedule-card');
    expect(card).not.toBeNull();
    const outcomeSummary = within(card).getByText('Last outcome').closest('.schedule-execution-summary');
    expect(outcomeSummary).not.toBeNull();
    expect(within(outcomeSummary).getByText('96 staged / 89 pending details / 7 completed details')).toBeInTheDocument();
  });

  it('shows running detail totals in the latest execution summary when backlog is actively being consumed', () => {
    vi.spyOn(Date, 'now').mockReturnValue(new Date('2026-05-28T12:00:00Z').getTime());

    render(
      <ScheduleList
        currentSourceSite="jobsdb"
        schedules={[
          {
            id: 'outcome-running-backlog',
            name: 'JobsDB Recovery In Flight',
            cron_expression: '0 2 * * *',
            category_ids: [6281],
            source_site: 'jobsdb',
            crawl_phase: 'listing',
            crawl_mode: 'headed',
            is_active: true,
            last_run_at: '2026-05-28T08:00:00Z',
            next_run_at: '2026-05-29T08:00:00Z',
            latest_execution_status: 'running',
            latest_execution_started_at: '2026-05-28T08:00:00Z',
            latest_execution_jobs_scraped: 0,
            latest_execution_jobs_saved: 0,
            latest_execution_listings_staged: 96,
            latest_execution_detail_pending: 51,
            latest_execution_detail_running: 12,
            latest_execution_detail_completed: 22,
          },
        ]}
        onToggle={vi.fn()}
        onDelete={vi.fn()}
        onRun={vi.fn()}
        onViewHistory={vi.fn()}
        isLoading={false}
      />,
    );

    const card = screen.getByRole('heading', { level: 4, name: 'JobsDB Recovery In Flight' }).closest('.schedule-card');
    expect(card).not.toBeNull();
    const outcomeSummary = within(card).getByText('Last outcome').closest('.schedule-execution-summary');
    expect(outcomeSummary).not.toBeNull();
    expect(
      within(outcomeSummary).getByText('96 staged / 51 pending details / 12 running details / 22 completed details')
    ).toBeInTheDocument();
  });

  it('shows an awaiting-counts summary for active executions before the first counters arrive', () => {
    vi.spyOn(Date, 'now').mockReturnValue(new Date('2026-05-28T12:00:00Z').getTime());

    render(
      <ScheduleList
        currentSourceSite="jobsdb"
        schedules={[
          {
            id: 'outcome-awaiting-counts',
            name: 'JobsDB Warm Start',
            cron_expression: '0 2 * * *',
            category_ids: [6281],
            source_site: 'jobsdb',
            crawl_phase: 'listing',
            crawl_mode: 'headed',
            is_active: true,
            last_run_at: '2026-05-28T08:00:00Z',
            next_run_at: '2026-05-29T08:00:00Z',
            latest_execution_status: 'running',
            latest_execution_started_at: '2026-05-28T11:59:30Z',
            latest_execution_jobs_scraped: 0,
            latest_execution_jobs_saved: 0,
          },
        ]}
        onToggle={vi.fn()}
        onDelete={vi.fn()}
        onRun={vi.fn()}
        onViewHistory={vi.fn()}
        isLoading={false}
      />,
    );

    const card = screen.getByRole('heading', { level: 4, name: 'JobsDB Warm Start' }).closest('.schedule-card');
    expect(card).not.toBeNull();
    const outcomeSummary = within(card).getByText('Last outcome').closest('.schedule-execution-summary');
    expect(outcomeSummary).not.toBeNull();
    expect(within(outcomeSummary).getByText('Running')).toBeInTheDocument();
    expect(within(outcomeSummary).getByText('Awaiting first counts')).toBeInTheDocument();
    expect(within(outcomeSummary).queryByText('0 scraped / 0 ingested')).not.toBeInTheDocument();
  });
});
