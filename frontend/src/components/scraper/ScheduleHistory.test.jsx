import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import ScheduleHistory from './ScheduleHistory';

describe('ScheduleHistory', () => {
  it('renders compact request snapshot details for schedule executions', () => {
    render(
      <ScheduleHistory
        scheduleName="JobsDB Nightly"
        onClose={vi.fn()}
        executions={[
          {
            id: 'execution-1',
            schedule_id: 'schedule-1',
            crawl_job_id: 'crawl-job-123',
            status: 'completed',
            started_at: '2026-05-22T01:00:00Z',
            completed_at: '2026-05-22T01:05:00Z',
            duration_seconds: 300,
            jobs_scraped: 42,
            jobs_saved: 40,
            phase1_completed: true,
            phase2_completed: true,
            phase3_completed: false,
            phase4_completed: true,
            phase5_completed: false,
            ids_collected: 52,
            jobs_classified: 0,
            error_message: null,
            created_at: '2026-05-22T01:00:00Z',
            request_payload_snapshot: {
              source_site: 'jobsdb',
              crawl_phase: 'detail',
              crawl_mode: 'headed',
              category_ids: [1200, 6281],
              detail_limit: 80,
              source_listing_crawl_job_id: 'listing-batch-777',
            },
          },
        ]}
      />,
    );

    const snapshot = screen.getByText(/request snapshot/i).closest('.execution-request-snapshot');
    expect(snapshot).not.toBeNull();
    expect(within(snapshot).getByText(/source/i)).toBeInTheDocument();
    expect(within(snapshot).getByText(/^jobsdb$/i)).toBeInTheDocument();
    expect(within(snapshot).getByText(/phase/i)).toBeInTheDocument();
    expect(within(snapshot).getByText(/^detail$/i)).toBeInTheDocument();
    expect(within(snapshot).getByText(/mode/i)).toBeInTheDocument();
    expect(within(snapshot).getByText(/^headed$/i)).toBeInTheDocument();
    expect(within(snapshot).getByText(/categories/i)).toBeInTheDocument();
    expect(within(snapshot).getByText(/2 selected/i)).toBeInTheDocument();
    expect(within(snapshot).getByText(/detail batch/i)).toBeInTheDocument();
    expect(within(snapshot).getByText(/listing-batch-777/i)).toBeInTheDocument();
    expect(within(snapshot).getByText(/detail limit/i)).toBeInTheDocument();
    expect(within(snapshot).getByText(/80/i)).toBeInTheDocument();
    expect(within(snapshot).getByText(/crawl job/i)).toBeInTheDocument();
    expect(within(snapshot).getByText(/crawl-job-123/i)).toBeInTheDocument();
  });

  it('closes the modal when the close button is pressed', () => {
    const onClose = vi.fn();

    render(
      <ScheduleHistory
        scheduleName="JobsDB Nightly"
        onClose={onClose}
        executions={[]}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /close history/i }));

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('does not invent a zero-category snapshot when category_ids were not captured', () => {
    render(
      <ScheduleHistory
        scheduleName="JobsDB Nightly"
        onClose={vi.fn()}
        executions={[
          {
            id: 'execution-no-category-snapshot',
            schedule_id: 'schedule-1',
            crawl_job_id: 'crawl-job-456',
            status: 'completed',
            started_at: '2026-05-22T01:00:00Z',
            completed_at: '2026-05-22T01:00:00Z',
            duration_seconds: 0,
            jobs_scraped: 12,
            jobs_saved: 11,
            phase1_completed: true,
            phase2_completed: true,
            phase3_completed: false,
            phase4_completed: true,
            phase5_completed: false,
            ids_collected: 12,
            jobs_classified: 0,
            error_message: null,
            created_at: '2026-05-22T01:00:00Z',
            request_payload_snapshot: {},
          },
        ]}
      />
    );

    const snapshot = screen.getByText(/request snapshot/i).closest('.execution-request-snapshot');
    expect(snapshot).not.toBeNull();
    expect(within(snapshot).queryByText(/categories/i)).not.toBeInTheDocument();
    expect(within(snapshot).queryByText(/0 selected/i)).not.toBeInTheDocument();
    expect(within(snapshot).getByText(/crawl job/i)).toBeInTheDocument();
  });

  it('shows zero-second durations explicitly and labels authoritative execution counts', () => {
    render(
      <ScheduleHistory
        scheduleName="JobsDB Nightly"
        onClose={vi.fn()}
        executions={[
          {
            id: 'execution-2',
            schedule_id: 'schedule-1',
            crawl_job_id: 'crawl-job-456',
            status: 'completed',
            started_at: '2026-05-22T01:00:00Z',
            completed_at: '2026-05-22T01:00:00Z',
            duration_seconds: 0,
            jobs_scraped: 12345,
            jobs_saved: 6789,
            phase1_completed: true,
            phase2_completed: true,
            phase3_completed: true,
            phase4_completed: true,
            phase5_completed: false,
            ids_collected: 12345,
            jobs_classified: 0,
            error_message: null,
            created_at: '2026-05-22T01:00:00Z',
            request_payload_snapshot: {},
          },
        ]}
      />,
    );

    const executionRow = screen.getByText('0s').closest('tr');
    expect(executionRow).not.toBeNull();
    expect(within(executionRow).getByText('IDs')).toBeInTheDocument();
    expect(within(executionRow).getAllByText('12,345').length).toBeGreaterThan(1);
    expect(within(executionRow).getByText('Scraped')).toBeInTheDocument();
    expect(within(executionRow).getByText('Ingested')).toBeInTheDocument();
    expect(within(executionRow).getByText('6,789')).toBeInTheDocument();
    expect(within(executionRow).queryByText('Classified')).not.toBeInTheDocument();
  });

  it('shows dead-lettered execution counts when ingest settled with failures', () => {
    render(
      <ScheduleHistory
        scheduleName="CTGoodJobs Recovery"
        onClose={vi.fn()}
        executions={[
          {
            id: 'execution-dead-letter',
            schedule_id: 'schedule-1',
            crawl_job_id: 'crawl-job-456',
            status: 'completed',
            started_at: '2026-05-22T01:00:00Z',
            completed_at: '2026-05-22T01:05:00Z',
            duration_seconds: 300,
            jobs_scraped: 100,
            jobs_saved: 30,
            jobs_settled: 100,
            jobs_dead_lettered: 70,
            phase1_completed: true,
            phase2_completed: true,
            phase3_completed: false,
            phase4_completed: true,
            phase5_completed: false,
            ids_collected: 100,
            jobs_classified: 0,
            error_message: null,
            created_at: '2026-05-22T01:00:00Z',
            request_payload_snapshot: {},
          },
        ]}
      />,
    );

    const executionRow = screen.getByText('Dead-lettered').closest('tr');
    expect(executionRow).not.toBeNull();
    expect(within(executionRow).getByText('70')).toBeInTheDocument();
    expect(within(executionRow).getByText('Ingested')).toBeInTheDocument();
    expect(within(executionRow).getByText('30')).toBeInTheDocument();
  });

  it('shows listing backlog counts for executions that staged downstream detail work', () => {
    render(
      <ScheduleHistory
        scheduleName="JobsDB ICT E2E"
        onClose={vi.fn()}
        executions={[
          {
            id: 'execution-backlog',
            schedule_id: 'schedule-1',
            crawl_job_id: 'crawl-job-789',
            status: 'completed',
            started_at: '2026-05-22T01:00:00Z',
            completed_at: '2026-05-22T01:05:00Z',
            duration_seconds: 300,
            jobs_scraped: 0,
            jobs_saved: 0,
            listings_staged: 96,
            detail_pending: 89,
            detail_completed: 7,
            phase1_completed: true,
            phase2_completed: true,
            phase3_completed: false,
            phase4_completed: true,
            phase5_completed: false,
            ids_collected: 96,
            jobs_classified: 0,
            error_message: null,
            created_at: '2026-05-22T01:00:00Z',
            request_payload_snapshot: {},
          },
        ]}
      />,
    );

    const executionRow = screen.getByText('Staged').closest('tr');
    expect(executionRow).not.toBeNull();
    expect(within(executionRow).getAllByText('96').length).toBeGreaterThanOrEqual(2);
    expect(within(executionRow).getByText('Pending details')).toBeInTheDocument();
    expect(within(executionRow).getByText('89')).toBeInTheDocument();
    expect(within(executionRow).getByText('Completed details')).toBeInTheDocument();
    expect(within(executionRow).getByText('7')).toBeInTheDocument();
    expect(within(executionRow).queryByText('Scraped')).not.toBeInTheDocument();
    expect(within(executionRow).queryByText('Ingested')).not.toBeInTheDocument();
  });

  it('shows an awaiting-counts marker instead of zero scraped and ingested values for fresh running executions', () => {
    render(
      <ScheduleHistory
        scheduleName="JobsDB Warm Start"
        onClose={vi.fn()}
        executions={[
          {
            id: 'execution-awaiting-counts',
            schedule_id: 'schedule-1',
            crawl_job_id: 'crawl-job-awaiting',
            status: 'running',
            started_at: '2026-05-22T01:00:00Z',
            completed_at: null,
            duration_seconds: null,
            jobs_scraped: 0,
            jobs_saved: 0,
            phase1_completed: false,
            phase2_completed: false,
            phase3_completed: false,
            phase4_completed: false,
            phase5_completed: false,
            ids_collected: 0,
            jobs_classified: 0,
            error_message: null,
            created_at: '2026-05-22T01:00:00Z',
            request_payload_snapshot: {},
          },
        ]}
      />
    );

    const executionRow = screen.getByText('Running').closest('tr');
    expect(executionRow).not.toBeNull();
    expect(within(executionRow).getByText('Awaiting first counts')).toBeInTheDocument();
    expect(within(executionRow).queryByText('Scraped')).not.toBeInTheDocument();
    expect(within(executionRow).queryByText('Ingested')).not.toBeInTheDocument();
  });

  it('includes phase5 in the execution phase summary and surfaces ids/classified counts', () => {
    render(
      <ScheduleHistory
        scheduleName="JobsDB Nightly"
        onClose={vi.fn()}
        executions={[
          {
            id: 'execution-3',
            schedule_id: 'schedule-1',
            crawl_job_id: 'crawl-job-789',
            status: 'completed',
            started_at: '2026-05-22T01:00:00Z',
            completed_at: '2026-05-22T01:05:00Z',
            duration_seconds: 300,
            jobs_scraped: 42,
            jobs_saved: 40,
            phase1_completed: true,
            phase2_completed: true,
            phase3_completed: true,
            phase4_completed: true,
            phase5_completed: true,
            ids_collected: 52,
            jobs_classified: 39,
            error_message: null,
            created_at: '2026-05-22T01:00:00Z',
            request_payload_snapshot: {},
          },
        ]}
      />,
    );

    expect(screen.getByText(/collect ids -> fetch details -> ai classify -> persist data -> ai enrich/i)).toBeInTheDocument();
    const executionRow = screen.getByText(/collect ids -> fetch details -> ai classify -> persist data -> ai enrich/i).closest('tr');
    expect(executionRow).not.toBeNull();
    expect(within(executionRow).getByText('Classified')).toBeInTheDocument();
    expect(within(executionRow).getByText('39')).toBeInTheDocument();
  });

  it('renders completed_with_ai_failures as a distinct execution status', () => {
    render(
      <ScheduleHistory
        scheduleName="JobsDB Nightly"
        onClose={vi.fn()}
        executions={[
          {
            id: 'execution-4',
            schedule_id: 'schedule-1',
            crawl_job_id: 'crawl-job-999',
            status: 'completed_with_ai_failures',
            started_at: '2026-05-22T01:00:00Z',
            completed_at: '2026-05-22T01:05:00Z',
            duration_seconds: 300,
            jobs_scraped: 42,
            jobs_saved: 40,
            phase1_completed: true,
            phase2_completed: true,
            phase3_completed: false,
            phase4_completed: true,
            phase5_completed: true,
            ids_collected: 52,
            jobs_classified: 0,
            error_message: null,
            created_at: '2026-05-22T01:00:00Z',
            request_payload_snapshot: {},
          },
        ]}
      />,
    );

    expect(screen.getByText(/completed with ai failures/i)).toBeInTheDocument();
  });

  it('does not imply ai classify in the phase summary when no classified count is available', () => {
    render(
      <ScheduleHistory
        scheduleName="JobsDB Nightly"
        onClose={vi.fn()}
        executions={[
          {
            id: 'execution-5',
            schedule_id: 'schedule-1',
            crawl_job_id: 'crawl-job-111',
            status: 'completed',
            started_at: '2026-05-22T01:00:00Z',
            completed_at: '2026-05-22T01:05:00Z',
            duration_seconds: 300,
            jobs_scraped: 42,
            jobs_saved: 40,
            phase1_completed: true,
            phase2_completed: true,
            phase3_completed: true,
            phase4_completed: true,
            phase5_completed: false,
            ids_collected: 52,
            jobs_classified: 0,
            error_message: null,
            created_at: '2026-05-22T01:00:00Z',
            request_payload_snapshot: {},
          },
        ]}
      />,
    );

    expect(screen.getByText(/collect ids -> fetch details -> persist data/i)).toBeInTheDocument();
    expect(screen.queryByText(/ai classify/i)).not.toBeInTheDocument();
  });

  it('shows stage listings instead of fetch details for listing-phase executions that only build backlog', () => {
    render(
      <ScheduleHistory
        scheduleName="JobsDB ICT E2E"
        onClose={vi.fn()}
        executions={[
          {
            id: 'execution-listing-phase',
            schedule_id: 'schedule-1',
            crawl_job_id: 'crawl-job-222',
            status: 'completed',
            started_at: '2026-05-22T01:00:00Z',
            completed_at: '2026-05-22T01:05:00Z',
            duration_seconds: 300,
            jobs_scraped: 0,
            jobs_saved: 0,
            listings_staged: 96,
            detail_pending: 89,
            detail_completed: 7,
            phase1_completed: true,
            phase2_completed: true,
            phase3_completed: false,
            phase4_completed: true,
            phase5_completed: false,
            ids_collected: 96,
            jobs_classified: 0,
            error_message: null,
            created_at: '2026-05-22T01:00:00Z',
            request_payload_snapshot: {
              crawl_phase: 'listing',
            },
          },
        ]}
      />,
    );

    expect(screen.getByText(/collect ids -> stage listings/i)).toBeInTheDocument();
    expect(screen.queryByText(/fetch details/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/persist data/i)).not.toBeInTheDocument();
  });
});
