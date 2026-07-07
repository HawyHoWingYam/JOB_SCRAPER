import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import ScheduleForm from './ScheduleForm';

const JOBSDB_CATEGORIES = [{ id: 1200, name: 'Engineering' }];
const CTGOODJOBS_CATEGORIES = [{ id: 'ctgoodjobs:021', name: 'Information Technology' }];
const OFFERTODAY_CATEGORIES = [{ id: 118000, name: 'Information Technology' }];

const SOURCE_CATALOG = {
  jobsdb: {
    supported_crawl_modes: ['headless', 'headed'],
    default_crawl_mode: 'headed',
    default_max_pages: 3,
    label: 'JobsDB Live',
  },
  ctgoodjobs: {
    supported_crawl_modes: ['headed'],
    default_crawl_mode: 'headed',
    default_max_pages: 3,
    label: 'CTGoodJobs Live',
  },
  offertoday: {
    supported_crawl_modes: ['headless', 'headed'],
    default_crawl_mode: 'headless',
    default_max_pages: 50,
    label: 'OfferToday Live',
  },
};

function renderScheduleForm({
  categories = JOBSDB_CATEGORIES,
  sourceSite = 'jobsdb',
  sourceCatalog = SOURCE_CATALOG,
  onSubmit = vi.fn(),
  onSourceScopedDirtyChange = vi.fn(),
} = {}) {
  return {
    onSubmit,
    onSourceScopedDirtyChange,
    ...render(
      <ScheduleForm
        categories={categories}
        sourceSite={sourceSite}
        sourceCatalog={sourceCatalog}
        onSubmit={onSubmit}
        onCancel={vi.fn()}
        onSourceScopedDirtyChange={onSourceScopedDirtyChange}
        isLoading={false}
      />,
    ),
  };
}

describe('ScheduleForm', () => {
  it('uses supplied sourceCatalog defaults for real form mounts', async () => {
    const { rerender } = renderScheduleForm({
      categories: JOBSDB_CATEGORIES,
      sourceSite: 'jobsdb',
    });

    await waitFor(() => {
      expect(screen.getByRole('combobox', { name: /crawl mode/i })).toHaveValue('headed');
    });
    expect(screen.getByRole('spinbutton')).toHaveValue(3);
    expect(screen.getByText(/creating automation for jobsdb live/i)).toBeInTheDocument();

    rerender(
      <ScheduleForm
        categories={OFFERTODAY_CATEGORIES}
        sourceSite="offertoday"
        sourceCatalog={SOURCE_CATALOG}
        onSubmit={vi.fn()}
        onCancel={vi.fn()}
        onSourceScopedDirtyChange={vi.fn()}
        isLoading={false}
      />,
    );

    await waitFor(() => {
      expect(screen.getByRole('combobox', { name: /crawl mode/i })).toHaveValue('headless');
    });
    expect(screen.getByRole('spinbutton')).toHaveValue(50);
    expect(screen.getByText(/creating automation for offertoday live/i)).toBeInTheDocument();
  });

  it('adopts backend defaults when sourceCatalog arrives later and fields are untouched', async () => {
    const delayedSourceCatalog = {
      ...SOURCE_CATALOG,
      jobsdb: {
        ...SOURCE_CATALOG.jobsdb,
        default_max_pages: 11,
      },
    };

    const { rerender } = renderScheduleForm({
      sourceCatalog: {},
      sourceSite: 'jobsdb',
    });

    expect(screen.getByRole('combobox', { name: /crawl mode/i })).toHaveValue('headless');
    expect(screen.getByRole('spinbutton')).toHaveValue(3);

    rerender(
      <ScheduleForm
        categories={JOBSDB_CATEGORIES}
        sourceSite="jobsdb"
        sourceCatalog={delayedSourceCatalog}
        onSubmit={vi.fn()}
        onCancel={vi.fn()}
        onSourceScopedDirtyChange={vi.fn()}
        isLoading={false}
      />,
    );

    await waitFor(() => {
      expect(screen.getByRole('combobox', { name: /crawl mode/i })).toHaveValue('headed');
    });
    expect(screen.getByRole('spinbutton')).toHaveValue(11);
  });

  it('does not overwrite dirty crawl mode or max pages when sourceCatalog arrives later', async () => {
    const delayedSourceCatalog = {
      ...SOURCE_CATALOG,
      jobsdb: {
        ...SOURCE_CATALOG.jobsdb,
        default_max_pages: 11,
      },
    };

    const { rerender } = renderScheduleForm({
      sourceCatalog: {},
      sourceSite: 'jobsdb',
    });

    fireEvent.change(screen.getByRole('combobox', { name: /crawl mode/i }), {
      target: { value: 'headless' },
    });
    fireEvent.change(screen.getByRole('spinbutton'), {
      target: { value: '4' },
    });
    fireEvent.change(screen.getByRole('spinbutton'), {
      target: { value: '3' },
    });

    rerender(
      <ScheduleForm
        categories={JOBSDB_CATEGORIES}
        sourceSite="jobsdb"
        sourceCatalog={delayedSourceCatalog}
        onSubmit={vi.fn()}
        onCancel={vi.fn()}
        onSourceScopedDirtyChange={vi.fn()}
        isLoading={false}
      />,
    );

    await waitFor(() => {
      expect(screen.getByRole('combobox', { name: /crawl mode/i })).toHaveValue('headless');
    });
    expect(screen.getByRole('spinbutton')).toHaveValue(3);
  });

  it('preserves valid dirty crawl mode and max pages when sourceSite changes', async () => {
    const onSubmit = vi.fn();
    const onDirty = vi.fn();

    const { rerender } = renderScheduleForm({
      onSubmit,
      onSourceScopedDirtyChange: onDirty,
      sourceSite: 'jobsdb',
      categories: JOBSDB_CATEGORIES,
    });

    await waitFor(() => {
      expect(screen.getByRole('combobox', { name: /crawl mode/i })).toHaveValue('headed');
    });

    fireEvent.change(screen.getByRole('textbox'), {
      target: { value: 'Cross-source scrape' },
    });
    fireEvent.click(screen.getByRole('checkbox', { name: /engineering/i }));
    fireEvent.change(screen.getByRole('combobox', { name: /crawl mode/i }), {
      target: { value: 'headless' },
    });
    fireEvent.change(screen.getByRole('combobox', { name: /crawl mode/i }), {
      target: { value: 'headed' },
    });
    fireEvent.change(screen.getByRole('spinbutton'), {
      target: { value: '4' },
    });
    fireEvent.change(screen.getByRole('spinbutton'), {
      target: { value: '3' },
    });

    rerender(
      <ScheduleForm
        categories={OFFERTODAY_CATEGORIES}
        sourceSite="offertoday"
        sourceCatalog={SOURCE_CATALOG}
        onSubmit={onSubmit}
        onCancel={vi.fn()}
        onSourceScopedDirtyChange={onDirty}
        isLoading={false}
      />,
    );

    await waitFor(() => {
      expect(screen.getByRole('combobox', { name: /crawl mode/i })).toHaveValue('headed');
    });
    expect(screen.getByRole('spinbutton')).toHaveValue(3);

    fireEvent.click(screen.getByRole('button', { name: /create automation/i }));

    expect(onSubmit).toHaveBeenCalledWith({
      name: 'Cross-source scrape',
      cron_expression: '0 2 * * *',
      crawl_phase: 'listing',
      crawl_mode: 'headed',
      category_ids: [],
      max_pages: 3,
      detail_limit: 100,
    });
  });

  it('reports source-scoped dirtiness from category selections only', () => {
    const onDirty = vi.fn();

    renderScheduleForm({
      onSourceScopedDirtyChange: onDirty,
    });

    fireEvent.change(screen.getByRole('textbox'), {
      target: { value: 'Nightly scrape' },
    });

    expect(onDirty).not.toHaveBeenCalledWith(true);

    fireEvent.click(screen.getByRole('checkbox', { name: /engineering/i }));

    expect(onDirty).toHaveBeenLastCalledWith(true);
  });

  it('defaults OfferToday to 50 max pages and submits that value', async () => {
    const onSubmit = vi.fn();

    renderScheduleForm({
      categories: OFFERTODAY_CATEGORIES,
      sourceSite: 'offertoday',
      onSubmit,
    });

    await waitFor(() => {
      expect(screen.getByRole('combobox', { name: /crawl mode/i })).toHaveValue('headless');
    });
    expect(screen.getByRole('spinbutton')).toHaveValue(50);

    fireEvent.change(screen.getByRole('textbox'), {
      target: { value: 'OfferToday scan' },
    });
    fireEvent.click(screen.getByRole('button', { name: /create automation/i }));

    expect(onSubmit).toHaveBeenLastCalledWith({
      name: 'OfferToday scan',
      cron_expression: '0 2 * * *',
      crawl_phase: 'listing',
      crawl_mode: 'headless',
      category_ids: [],
      max_pages: 50,
      detail_limit: 100,
    });
  });

  it('renders recurring automation guidance and phase-specific helper copy', () => {
    renderScheduleForm({
      sourceSite: 'jobsdb',
    });

    expect(screen.getByText(/use automations for recurring crawls on jobsdb live/i)).toBeInTheDocument();
    expect(screen.getByText(/job id crawl stages listing urls first/i)).toBeInTheDocument();
    expect(screen.getByText(/pages per run for each selected sector/i)).toBeInTheDocument();

    fireEvent.change(screen.getByRole('combobox', { name: /crawl phase/i }), {
      target: { value: 'detail' },
    });

    expect(screen.getByText(/detail crawl consumes staged listings into full records/i)).toBeInTheDocument();
    expect(screen.getByText(/how many staged listings this automation should expand per run/i)).toBeInTheDocument();
  });

  it('defaults crawl mode by source and lets the operator override it', async () => {
    const onSubmit = vi.fn();

    const { rerender } = renderScheduleForm({
      categories: JOBSDB_CATEGORIES,
      sourceSite: 'jobsdb',
      onSubmit,
    });

    await waitFor(() => {
      expect(screen.getByRole('combobox', { name: /crawl mode/i })).toHaveValue('headed');
    });

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
      crawl_phase: 'listing',
      crawl_mode: 'headless',
      category_ids: [],
      max_pages: 3,
      detail_limit: 100,
    });

    rerender(
      <ScheduleForm
        categories={CTGOODJOBS_CATEGORIES}
        sourceSite="ctgoodjobs"
        sourceCatalog={SOURCE_CATALOG}
        onSubmit={onSubmit}
        onCancel={vi.fn()}
        onSourceScopedDirtyChange={vi.fn()}
        isLoading={false}
      />,
    );

    await waitFor(() => {
      expect(screen.getByRole('combobox', { name: /crawl mode/i })).toHaveValue('headed');
    });
    expect(screen.queryByRole('option', { name: /headless/i })).not.toBeInTheDocument();
    expect(screen.getByRole('option', { name: /headed/i })).toBeInTheDocument();
  });

  it('submits detail schedules with detail_limit and phase metadata', async () => {
    const onSubmit = vi.fn();

    renderScheduleForm({
      sourceSite: 'jobsdb',
      onSubmit,
    });

    await waitFor(() => {
      expect(screen.getByRole('combobox', { name: /crawl mode/i })).toHaveValue('headed');
    });

    fireEvent.change(screen.getByRole('combobox', { name: /crawl phase/i }), {
      target: { value: 'detail' },
    });
    fireEvent.change(screen.getByRole('textbox'), {
      target: { value: 'Detail backlog' },
    });
    fireEvent.change(screen.getByRole('spinbutton'), { target: { value: '250' } });
    fireEvent.click(screen.getByRole('button', { name: /create automation/i }));

    expect(onSubmit).toHaveBeenCalledWith({
      name: 'Detail backlog',
      cron_expression: '0 2 * * *',
      crawl_phase: 'detail',
      crawl_mode: 'headed',
      category_ids: [],
      max_pages: 3,
      detail_limit: 250,
    });
  });
});
