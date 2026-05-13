import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import ScheduleForm from './ScheduleForm';

const JOBSDB_CATEGORIES = [{ id: 1200, name: 'Engineering' }];
const CTGOODJOBS_CATEGORIES = [{ id: 'ctgoodjobs:021', name: 'Information Technology' }];

describe('ScheduleForm', () => {
  it('clears category selections when sourceSite changes but preserves max pages', () => {
    const onSubmit = vi.fn();
    const onDirty = vi.fn();

    const { rerender } = render(
      <ScheduleForm
        categories={JOBSDB_CATEGORIES}
        sourceSite="jobsdb"
        onSubmit={onSubmit}
        onCancel={vi.fn()}
        onSourceScopedDirtyChange={onDirty}
        isLoading={false}
      />,
    );

    fireEvent.change(screen.getByRole('textbox'), {
      target: { value: 'Nightly scrape' },
    });
    fireEvent.click(screen.getByRole('checkbox', { name: /engineering/i }));
    fireEvent.change(screen.getByRole('spinbutton'), { target: { value: '5' } });

    rerender(
      <ScheduleForm
        categories={CTGOODJOBS_CATEGORIES}
        sourceSite="ctgoodjobs"
        onSubmit={onSubmit}
        onCancel={vi.fn()}
        onSourceScopedDirtyChange={onDirty}
        isLoading={false}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /create automation/i }));

    expect(onSubmit).toHaveBeenCalledWith({
      name: 'Nightly scrape',
      cron_expression: '0 2 * * *',
      crawl_mode: 'headed',
      category_ids: [],
      max_pages: 5,
    });
  });

  it('reports source-scoped dirtiness from category selections only', () => {
    const onDirty = vi.fn();

    render(
      <ScheduleForm
        categories={JOBSDB_CATEGORIES}
        sourceSite="jobsdb"
        onSubmit={vi.fn()}
        onCancel={vi.fn()}
        onSourceScopedDirtyChange={onDirty}
        isLoading={false}
      />,
    );

    fireEvent.change(screen.getByRole('textbox'), {
      target: { value: 'Nightly scrape' },
    });

    expect(onDirty).not.toHaveBeenCalledWith(true);

    fireEvent.click(screen.getByRole('checkbox', { name: /engineering/i }));

    expect(onDirty).toHaveBeenLastCalledWith(true);
  });

  it('defaults crawl mode by source and lets the operator override it', () => {
    const onSubmit = vi.fn();

    const { rerender } = render(
      <ScheduleForm
        categories={JOBSDB_CATEGORIES}
        sourceSite="jobsdb"
        onSubmit={onSubmit}
        onCancel={vi.fn()}
        onSourceScopedDirtyChange={vi.fn()}
        isLoading={false}
      />,
    );

    expect(screen.getByRole('combobox', { name: /crawl mode/i })).toHaveValue('headed');

    fireEvent.change(screen.getByRole('combobox', { name: /crawl mode/i }), {
      target: { value: 'headless' },
    });
    fireEvent.change(screen.getByRole('textbox'), {
      target: { value: 'JobsDB Manual' },
    });
    fireEvent.click(screen.getByRole('button', { name: /create automation/i }));

    expect(onSubmit).toHaveBeenLastCalledWith({
      name: 'JobsDB Manual',
      cron_expression: '0 2 * * *',
      crawl_mode: 'headless',
      category_ids: [],
      max_pages: 3,
    });

    rerender(
      <ScheduleForm
        categories={CTGOODJOBS_CATEGORIES}
        sourceSite="ctgoodjobs"
        onSubmit={onSubmit}
        onCancel={vi.fn()}
        onSourceScopedDirtyChange={vi.fn()}
        isLoading={false}
      />,
    );

    expect(screen.getByRole('combobox', { name: /crawl mode/i })).toHaveValue('headed');
  });
});
