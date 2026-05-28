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

  it('shows zero-second durations explicitly and formats scraped/saved execution volume', () => {
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

    expect(screen.getByText('0s')).toBeInTheDocument();
    expect(screen.getByText('12,345 / 6,789')).toBeInTheDocument();
  });
});
