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
    vi.unstubAllGlobals();
  });

  it('renders chained AI progress after the save phase and exposes a run jump action', async () => {
    const onNavigateToAI = vi.fn();
    const user = userEvent.setup();

    render(<ScrapeProgressPanel isVisible onClose={vi.fn()} onNavigateToAI={onNavigateToAI} />);

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
  });

  it('renders completed_with_ai_failures as a distinct terminal state', async () => {
    render(<ScrapeProgressPanel isVisible onClose={vi.fn()} />);

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
  });

  it('does not reconnect after the panel is hidden', () => {
    vi.useFakeTimers();
    const { rerender } = render(<ScrapeProgressPanel isVisible onClose={vi.fn()} />);

    const stream = latestEventSource();

    act(() => {
      stream.emitError();
    });

    rerender(<ScrapeProgressPanel isVisible={false} onClose={vi.fn()} />);

    act(() => {
      vi.advanceTimersByTime(3000);
    });

    expect(MockEventSource.instances).toHaveLength(1);

    vi.useRealTimers();
  });
});
