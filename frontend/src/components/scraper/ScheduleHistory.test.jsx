import { fireEvent, render, screen } from '@testing-library/react';
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

    expect(screen.getByText(/request snapshot/i)).toBeInTheDocument();
    expect(screen.getByText(/source/i)).toBeInTheDocument();
    expect(screen.getByText(/^jobsdb$/i)).toBeInTheDocument();
    expect(screen.getByText(/phase/i)).toBeInTheDocument();
    expect(screen.getByText(/^detail$/i)).toBeInTheDocument();
    expect(screen.getByText(/mode/i)).toBeInTheDocument();
    expect(screen.getByText(/^headed$/i)).toBeInTheDocument();
    expect(screen.getByText(/categories/i)).toBeInTheDocument();
    expect(screen.getByText(/2 selected/i)).toBeInTheDocument();
    expect(screen.getByText(/detail batch/i)).toBeInTheDocument();
    expect(screen.getByText(/listing-batch-777/i)).toBeInTheDocument();
    expect(screen.getByText(/detail limit/i)).toBeInTheDocument();
    expect(screen.getByText(/80/i)).toBeInTheDocument();
    expect(screen.getByText(/crawl job/i)).toBeInTheDocument();
    expect(screen.getByText(/crawl-job-123/i)).toBeInTheDocument();
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
});
