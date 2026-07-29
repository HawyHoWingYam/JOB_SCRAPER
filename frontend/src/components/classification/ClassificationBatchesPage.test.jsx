import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import ClassificationBatchesPage from './ClassificationBatchesPage';
import {
  fetchClassificationRuns,
  previewClassificationBatch,
  retryClassificationRun,
  startClassificationBatch,
  stopClassificationRun,
} from '../../api/classificationBatches';

vi.mock('../../api/classificationBatches', () => ({
  fetchClassificationRuns: vi.fn(),
  previewClassificationBatch: vi.fn(),
  retryClassificationRun: vi.fn(),
  startClassificationBatch: vi.fn(),
  stopClassificationRun: vi.fn(),
}));

describe('ClassificationBatchesPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.location.hash = '#classification';
    fetchClassificationRuns.mockResolvedValue({ items: [] });
    previewClassificationBatch.mockResolvedValue({
      domain: 'skill',
      selected_item_count: 12,
      items: [],
    });
    startClassificationBatch.mockResolvedValue({ id: 'run-new' });
    stopClassificationRun.mockResolvedValue({});
    retryClassificationRun.mockResolvedValue({});
  });

  it('defaults invalid routes to Skills without mutating a batch', async () => {
    render(
      <ClassificationBatchesPage
        routeHash="#classification?target=not-a-domain"
      />,
    );

    expect(screen.getByRole('tab', { name: 'Skills' })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    await waitFor(() => {
      expect(fetchClassificationRuns).toHaveBeenCalledWith('skill');
    });
    expect(previewClassificationBatch).not.toHaveBeenCalled();
    expect(startClassificationBatch).not.toHaveBeenCalled();
  });

  it('serializes retained domain tab changes through navigation', async () => {
    const onNavigateTarget = vi.fn();
    const user = userEvent.setup();
    render(
      <ClassificationBatchesPage
        routeHash="#classification"
        onNavigateTarget={onNavigateTarget}
      />,
    );

    await user.click(screen.getByRole('tab', { name: 'Company Industry' }));
    expect(onNavigateTarget).toHaveBeenCalledWith('company_industry');
  });

  it('previews and starts a bounded Skill candidate batch', async () => {
    const user = userEvent.setup();
    render(<ClassificationBatchesPage />);

    const start = screen.getByRole('button', { name: '开始处理' });
    expect(start).toBeDisabled();
    await user.clear(screen.getByLabelText('Classification batch limit'));
    await user.type(screen.getByLabelText('Classification batch limit'), '25');
    await user.click(screen.getByRole('button', { name: '预览' }));

    expect(await screen.findByText('这次会处理 12 项。')).toBeInTheDocument();
    expect(previewClassificationBatch).toHaveBeenCalledWith(
      'skill',
      { filters: {}, limit: 25 },
      { signal: expect.any(AbortSignal) },
    );
    await user.click(start);
    expect(startClassificationBatch).toHaveBeenCalledWith(
      'skill',
      { filters: {}, limit: 25 },
    );
  });

  it('keeps Company Industry source filters and mapping readiness', async () => {
    previewClassificationBatch.mockResolvedValueOnce({
      domain: 'company_industry',
      selected_item_count: 3,
      mapped_item_count: 1,
      unmapped_item_count: 1,
      excluded_item_count: 1,
      items: [],
    });
    const user = userEvent.setup();
    render(
      <ClassificationBatchesPage
        routeHash="#classification?target=company_industry"
      />,
    );

    await user.click(screen.getByRole('checkbox', { name: 'jobsdb' }));
    await user.click(screen.getByRole('button', { name: '预览' }));

    expect(await screen.findByText(/已选 3 家 Company/)).toBeInTheDocument();
    expect(screen.getByText(/可映射 1/)).toBeInTheDocument();
    expect(screen.getByText(/未映射 1/)).toBeInTheDocument();
    expect(screen.getByText(/规则排除 1/)).toBeInTheDocument();
    expect(previewClassificationBatch).toHaveBeenCalledWith(
      'company_industry',
      { filters: { source_sites: ['jobsdb'] }, limit: 100 },
      { signal: expect.any(AbortSignal) },
    );
    expect(screen.getByRole('button', { name: '开始处理' })).toBeEnabled();
  });

  it('invalidates and aborts a preview when the limit changes', async () => {
    previewClassificationBatch.mockReturnValueOnce(new Promise(() => {}));
    const user = userEvent.setup();
    render(<ClassificationBatchesPage />);

    await user.click(screen.getByRole('button', { name: '预览' }));
    await waitFor(() => {
      expect(previewClassificationBatch).toHaveBeenCalledTimes(1);
    });
    const { signal } = previewClassificationBatch.mock.calls[0][2];
    expect(signal.aborted).toBe(false);

    await user.clear(screen.getByLabelText('Classification batch limit'));

    expect(signal.aborted).toBe(true);
    expect(screen.getByText('还没有预览。')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '开始处理' })).toBeDisabled();
  });

  it('shows Skill Candidate failure evidence and retries only failures', async () => {
    fetchClassificationRuns.mockResolvedValue({
      items: [
        {
          id: 'run-failed',
          status: 'completed_with_failures',
          total_items: 2,
          completed_items: 1,
          failed_items: 1,
          cancelled_items: 0,
          items: [
            {
              id: 'item-2',
              subject_id: 'candidate-2',
              subject_label: 'MysteryDB',
              status: 'failed',
              error_message: 'Skill candidate placement is uncertain',
            },
          ],
        },
      ],
    });
    const user = userEvent.setup();
    render(<ClassificationBatchesPage />);

    await screen.findByText('completed_with_failures');
    await user.click(screen.getByText('查看失败原因'));
    expect(
      screen.getByText(/Skill candidate placement is uncertain/),
    ).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '只重试失败项 (1)' }));

    await waitFor(() => {
      expect(retryClassificationRun).toHaveBeenCalledWith('run-failed');
    });
  });

  it('does not show source filters for Skill processing', async () => {
    render(<ClassificationBatchesPage />);

    expect(screen.getByText(/达到 Settings 次数门槛/)).toBeInTheDocument();
    expect(
      screen.queryByRole('checkbox', { name: 'jobsdb' }),
    ).not.toBeInTheDocument();
    await waitFor(() => {
      expect(fetchClassificationRuns).toHaveBeenCalledWith('skill');
    });
  });
});
