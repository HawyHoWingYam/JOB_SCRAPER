import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import ScrapeProgressPanel from './ScrapeProgressPanel';

class MockEventSource {
  static instances = [];

  constructor(url) {
    this.url = url;
    this.onopen = null;
    this.onmessage = null;
    this.onerror = null;
    this.close = vi.fn();
    MockEventSource.instances.push(this);
  }

  emitOpen() {
    this.onopen?.();
  }

  emitMessage(payload) {
    this.onmessage?.({ data: JSON.stringify(payload) });
  }

  emitError() {
    this.onerror?.(new Event('error'));
  }
}

function latestEventSource() {
  return MockEventSource.instances.at(-1);
}

describe('ScrapeProgressPanel', () => {
  beforeEach(() => {
    MockEventSource.instances = [];
    vi.stubGlobal('EventSource', MockEventSource);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('renders initial progress immediately before the first SSE payload arrives', () => {
    const { unmount } = render(
      <ScrapeProgressPanel
        isVisible
        initialProgress={{
          engineering: {
            status: 'running',
            category_name: 'Engineering',
            phase: 2,
            jobs_scraped: 3,
            total_jobs: 10,
            elapsed_seconds: 12,
            phase_rate: 0.4,
          },
        }}
        onClose={vi.fn()}
      />
    );

    expect(screen.getByText('Engineering')).toBeInTheDocument();
    expect(screen.getByText(/3\/10 jobs/i)).toBeInTheDocument();

    unmount();
  });

  it('hydrates from initialProgress updates while visible if no progress has been received yet', () => {
    const { rerender, unmount } = render(
      <ScrapeProgressPanel isVisible initialProgress={{}} onClose={vi.fn()} />
    );

    expect(screen.getByText(/no active scraping tasks/i)).toBeInTheDocument();

    rerender(
      <ScrapeProgressPanel
        isVisible
        initialProgress={{
          engineering: {
            status: 'running',
            category_name: 'Engineering',
            phase: 2,
            jobs_scraped: 4,
            total_jobs: 12,
            elapsed_seconds: 10,
            phase_rate: 0.8,
          },
        }}
        onClose={vi.fn()}
      />
    );

    expect(screen.getByText('Engineering')).toBeInTheDocument();
    expect(screen.getByText(/4\/12 jobs/i)).toBeInTheDocument();

    unmount();
  });

  it('renders chained AI progress after the save phase and exposes a run jump action', async () => {
    const onNavigateToAI = vi.fn();
    const user = userEvent.setup();

    const { unmount } = render(
      <ScrapeProgressPanel isVisible onClose={vi.fn()} onNavigateToAI={onNavigateToAI} />
    );

    const stream = latestEventSource();
    expect(stream.url).toBe('/api/v1/scrape/progress/stream');
    act(() => {
      stream.emitOpen();
      stream.emitMessage({
        all: {
          engineering: {
            status: 'ai_running',
            category_name: 'Engineering',
            phase: 5,
            jobs_scraped: 6,
            ai_run_id: 'run-123',
            ai_completed_items: 2,
            ai_failed_items: 1,
            ai_total_items: 6,
            elapsed_seconds: 42,
            phase_rate: 0.5,
          },
        },
      });
    });

    expect(await screen.findByText(/ai enrichment/i)).toBeInTheDocument();
    expect(screen.getByText(/3\/6 items processed/i)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /view ai run/i }));

    expect(onNavigateToAI).toHaveBeenCalledWith('run-123');

    unmount();
  });

  it('renders completed_with_ai_failures as a distinct terminal state', async () => {
    const { unmount } = render(<ScrapeProgressPanel isVisible onClose={vi.fn()} />);

    const stream = latestEventSource();
    act(() => {
      stream.emitOpen();
      stream.emitMessage({
        all: {
          design: {
            status: 'completed_with_ai_failures',
            category_name: 'Design',
            phase: 5,
            jobs_scraped: 4,
            ai_run_id: 'run-456',
            ai_completed_items: 3,
            ai_failed_items: 1,
            ai_total_items: 4,
            completed_at: '2026-04-15T12:00:00Z',
          },
        },
      });
    });

    expect(await screen.findByText(/completed with ai failures/i)).toBeInTheDocument();
    expect(screen.getByText(/3 succeeded · 1 failed/i)).toBeInTheDocument();

    unmount();
  });

  it('does not reconnect after the panel is hidden', () => {
    vi.useFakeTimers();
    const { rerender, unmount } = render(<ScrapeProgressPanel isVisible onClose={vi.fn()} />);

    const stream = latestEventSource();

    act(() => {
      stream.emitError();
    });

    rerender(<ScrapeProgressPanel isVisible={false} onClose={vi.fn()} />);

    act(() => {
      vi.advanceTimersByTime(3000);
    });

    expect(MockEventSource.instances).toHaveLength(1);

    unmount();
    vi.useRealTimers();
  });

  it('calls onClose with "closed" when the server closes the stream', () => {
    const onClose = vi.fn();

    const { unmount } = render(<ScrapeProgressPanel isVisible onClose={onClose} />);

    const stream = latestEventSource();
    act(() => {
      stream.emitOpen();
      stream.emitMessage({ closed: true });
    });

    expect(onClose).toHaveBeenCalledWith('closed');

    unmount();
  });

  it('does not fire recovery timeout after the server has already closed the stream', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-04-30T12:00:00.000Z'));
    const onClose = vi.fn();

    const { unmount } = render(
      <ScrapeProgressPanel
        isVisible
        recoveryStartedAt="2026-04-30T11:59:56.000Z"
        recoveryWindowMs={5000}
        onClose={onClose}
      />
    );

    const stream = latestEventSource();
    act(() => {
      stream.emitOpen();
      stream.emitMessage({ closed: true });
      vi.advanceTimersByTime(2000);
    });

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledWith('closed');

    unmount();
    vi.useRealTimers();
  });

  it('ignores late errors from a stream after it has already closed', () => {
    vi.useFakeTimers();
    const onClose = vi.fn();

    const { unmount } = render(<ScrapeProgressPanel isVisible onClose={onClose} />);

    const stream = latestEventSource();
    act(() => {
      stream.emitOpen();
      stream.emitMessage({ closed: true });
      stream.emitError();
      vi.advanceTimersByTime(3000);
    });

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledWith('closed');
    expect(MockEventSource.instances).toHaveLength(1);

    unmount();
    vi.useRealTimers();
  });

  it('ignores late callbacks from an errored stream before reconnect completes', () => {
    vi.useFakeTimers();

    const { unmount } = render(<ScrapeProgressPanel isVisible onClose={vi.fn()} />);

    const stream = latestEventSource();
    act(() => {
      stream.emitError();
      stream.emitError();
      vi.advanceTimersByTime(3000);
    });

    expect(MockEventSource.instances).toHaveLength(2);

    unmount();
    vi.useRealTimers();
  });

  it('renders recovery copy while reconnecting without any recovered progress yet', () => {
    vi.useFakeTimers();

    const { unmount } = render(
      <ScrapeProgressPanel
        isVisible
        recoveryStartedAt="2026-04-30T12:00:00.000Z"
        recoveryWindowMs={15000}
        onClose={vi.fn()}
      />
    );

    expect(
      screen.getByText('Reconnecting to active Direct Override...')
    ).toBeInTheDocument();

    unmount();
    vi.useRealTimers();
  });

  it('closes with "recovery_timeout" when the recovery grace window expires without progress', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-04-30T12:00:00.000Z'));
    const onClose = vi.fn();

    const { unmount } = render(
      <ScrapeProgressPanel
        isVisible
        recoveryStartedAt="2026-04-30T11:59:56.000Z"
        recoveryWindowMs={5000}
        onClose={onClose}
      />
    );

    act(() => {
      vi.advanceTimersByTime(999);
    });
    expect(onClose).not.toHaveBeenCalled();

    act(() => {
      vi.advanceTimersByTime(1);
    });

    expect(onClose).toHaveBeenCalledWith('recovery_timeout');

    unmount();
    vi.useRealTimers();
  });

  it('does not close by default when recoveryWindowMs is missing', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-04-30T12:00:00.000Z'));
    const onClose = vi.fn();

    const { unmount } = render(
      <ScrapeProgressPanel
        isVisible
        recoveryStartedAt="2026-04-30T11:59:00.000Z"
        onClose={onClose}
      />
    );

    act(() => {
      vi.advanceTimersByTime(30000);
    });

    expect(onClose).not.toHaveBeenCalled();

    unmount();
    vi.useRealTimers();
  });

  it('does not trigger recovery timeout once progress is already available', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-04-30T12:00:00.000Z'));
    const onClose = vi.fn();

    const { unmount } = render(
      <ScrapeProgressPanel
        isVisible
        initialProgress={{
          engineering: {
            status: 'running',
            category_name: 'Engineering',
            phase: 1,
            current_page: 1,
            total_pages: 4,
            job_ids_collected: 25,
            elapsed_seconds: 5,
            phase_rate: 1.2,
          },
        }}
        recoveryStartedAt="2026-04-30T11:59:50.000Z"
        recoveryWindowMs={5000}
        onClose={onClose}
      />
    );

    act(() => {
      vi.advanceTimersByTime(10000);
    });

    expect(onClose).not.toHaveBeenCalled();

    unmount();
    vi.useRealTimers();
  });

  it('does not reconnect the stream when onClose gets a new function identity', () => {
    const firstOnClose = vi.fn();
    const secondOnClose = vi.fn();
    const { rerender, unmount } = render(
      <ScrapeProgressPanel isVisible onClose={firstOnClose} />
    );

    const firstStream = latestEventSource();

    rerender(<ScrapeProgressPanel isVisible onClose={secondOnClose} />);

    expect(MockEventSource.instances).toHaveLength(1);
    expect(firstStream.close).not.toHaveBeenCalled();

    unmount();
  });
});
