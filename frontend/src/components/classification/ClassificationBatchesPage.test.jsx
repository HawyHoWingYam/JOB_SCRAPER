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
    fetchClassificationRuns.mockResolvedValue({ items: [] });
    previewClassificationBatch.mockResolvedValue({
      domain: 'job_taxonomy',
      selected_item_count: 12,
      items: [],
    });
    startClassificationBatch.mockResolvedValue({ id: 'run-new' });
    stopClassificationRun.mockResolvedValue({});
    retryClassificationRun.mockResolvedValue({});
  });

  it('previews a bounded domain batch before enabling start', async () => {
    const user = userEvent.setup();
    render(<ClassificationBatchesPage />);

    const start = screen.getByRole('button', { name: '开始处理' });
    expect(start).toBeDisabled();
    await user.click(screen.getByRole('checkbox', { name: 'jobsdb' }));
    await user.clear(screen.getByLabelText('Classification batch limit'));
    await user.type(screen.getByLabelText('Classification batch limit'), '25');
    await user.click(screen.getByRole('button', { name: '预览' }));

    expect(await screen.findByText('这次会处理 12 项。')).toBeInTheDocument();
    expect(previewClassificationBatch).toHaveBeenCalledWith(
      'job_taxonomy',
      { filters: { source_sites: ['jobsdb'] }, limit: 25 },
      { signal: expect.any(AbortSignal) },
    );
    expect(start).toBeEnabled();

    await user.click(start);
    expect(startClassificationBatch).toHaveBeenCalledWith(
      'job_taxonomy',
      { filters: { source_sites: ['jobsdb'] }, limit: 25 },
    );
  });

  it('invalidates the preview when the selected Source changes', async () => {
    const user = userEvent.setup();
    render(<ClassificationBatchesPage />);

    await user.click(screen.getByRole('checkbox', { name: 'jobsdb' }));
    await user.click(screen.getByRole('button', { name: '预览' }));
    expect(await screen.findByText('这次会处理 12 项。')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '开始处理' })).toBeEnabled();

    await user.click(screen.getByRole('checkbox', { name: 'offertoday' }));

    expect(screen.getByText('还没有预览。')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '开始处理' })).toBeDisabled();
  });

  it('invalidates a preview when the classification domain changes', async () => {
    const user = userEvent.setup();
    render(<ClassificationBatchesPage />);

    await user.click(screen.getByRole('button', { name: '预览' }));
    expect(await screen.findByText('这次会处理 12 项。')).toBeInTheDocument();

    await user.click(screen.getByRole('tab', { name: 'Company Industry' }));

    expect(screen.getByText('还没有预览。')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '开始处理' })).toBeDisabled();
  });

  it('shows partial Company Industry mapping readiness and permits mapped work', async () => {
    previewClassificationBatch.mockResolvedValueOnce({
      domain: 'company_industry',
      selected_item_count: 3,
      mapped_item_count: 1,
      unmapped_item_count: 1,
      excluded_item_count: 1,
      items: [],
    });
    const user = userEvent.setup();
    render(<ClassificationBatchesPage />);

    await user.click(screen.getByRole('tab', { name: 'Company Industry' }));
    await user.click(screen.getByRole('button', { name: '预览' }));

    expect(await screen.findByText(/已选 3 家 Company/)).toBeInTheDocument();
    expect(screen.getByText(/可映射 1/)).toBeInTheDocument();
    expect(screen.getByText(/未映射 1/)).toBeInTheDocument();
    expect(screen.getByText(/规则排除 1/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '开始处理' })).toBeEnabled();
  });

  it('blocks Company Industry Start when the selected population has zero mappings', async () => {
    previewClassificationBatch.mockResolvedValueOnce({
      domain: 'company_industry',
      selected_item_count: 12,
      mapped_item_count: 0,
      unmapped_item_count: 2,
      excluded_item_count: 10,
      items: [],
    });
    const user = userEvent.setup();
    render(<ClassificationBatchesPage />);

    await user.click(screen.getByRole('tab', { name: 'Company Industry' }));
    await user.click(screen.getByRole('button', { name: '预览' }));

    expect(await screen.findByText(/没有可用的 Company Industry Source Mapping/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '开始处理' })).toBeDisabled();
  });

  it('requires a fresh preview after the limit changes, even if restored', async () => {
    const user = userEvent.setup();
    render(<ClassificationBatchesPage />);

    await user.click(screen.getByRole('button', { name: '预览' }));
    expect(await screen.findByText('这次会处理 12 项。')).toBeInTheDocument();

    const limitInput = screen.getByLabelText('Classification batch limit');
    await user.clear(limitInput);
    await user.type(limitInput, '25');
    expect(screen.getByText('还没有预览。')).toBeInTheDocument();

    await user.clear(limitInput);
    await user.type(limitInput, '100');
    expect(screen.getByText('还没有预览。')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '开始处理' })).toBeDisabled();
  });

  it('ignores a preview response after its inputs are superseded', async () => {
    let resolvePreview;
    previewClassificationBatch.mockReturnValueOnce(new Promise((resolve) => {
      resolvePreview = resolve;
    }));
    const user = userEvent.setup();
    render(<ClassificationBatchesPage />);

    await user.click(screen.getByRole('button', { name: '预览' }));
    await waitFor(() => {
      expect(previewClassificationBatch).toHaveBeenCalledTimes(1);
    });
    await user.click(screen.getByRole('checkbox', { name: 'offertoday' }));

    resolvePreview({
      domain: 'job_taxonomy',
      selected_item_count: 12,
      items: [],
    });

    await waitFor(() => {
      expect(screen.getByText('还没有预览。')).toBeInTheDocument();
    });
    expect(screen.getByRole('button', { name: '开始处理' })).toBeDisabled();
  });

  it('aborts an in-flight preview when its inputs change', async () => {
    previewClassificationBatch.mockReturnValueOnce(new Promise(() => {}));
    const user = userEvent.setup();
    render(<ClassificationBatchesPage />);

    await user.click(screen.getByRole('button', { name: '预览' }));
    await waitFor(() => {
      expect(previewClassificationBatch).toHaveBeenCalledTimes(1);
    });
    const { signal } = previewClassificationBatch.mock.calls[0][2];
    expect(signal.aborted).toBe(false);

    await user.click(screen.getByRole('checkbox', { name: 'offertoday' }));

    expect(signal.aborted).toBe(true);
    expect(screen.getByRole('button', { name: '预览' })).toBeEnabled();
  });

  it('starts with the normalized inputs accepted by the preview', async () => {
    const user = userEvent.setup();
    render(<ClassificationBatchesPage />);

    await user.click(screen.getByRole('checkbox', { name: 'offertoday' }));
    await user.click(screen.getByRole('checkbox', { name: 'jobsdb' }));
    await user.click(screen.getByRole('button', { name: '预览' }));
    expect(await screen.findByText('这次会处理 12 项。')).toBeInTheDocument();

    const expectedPayload = {
      filters: { source_sites: ['jobsdb', 'offertoday'] },
      limit: 100,
    };
    expect(previewClassificationBatch).toHaveBeenCalledWith(
      'job_taxonomy',
      expectedPayload,
      { signal: expect.any(AbortSignal) },
    );

    await user.click(screen.getByRole('button', { name: '开始处理' }));
    expect(startClassificationBatch).toHaveBeenCalledWith(
      'job_taxonomy',
      expectedPayload,
    );
  });

  it('shows failed item reasons and retries only those failures', async () => {
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
    expect(screen.getByText(/Skill candidate placement is uncertain/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '只重试失败项 (1)' }));

    await waitFor(() => {
      expect(retryClassificationRun).toHaveBeenCalledWith('run-failed');
    });
  });

  it('keeps Skill processing simple and does not show source filters', async () => {
    const user = userEvent.setup();
    render(<ClassificationBatchesPage />);
    await user.click(screen.getByRole('tab', { name: 'Skills' }));

    expect(screen.getByText(/达到 Settings 次数门槛/)).toBeInTheDocument();
    expect(screen.queryByRole('checkbox', { name: 'jobsdb' })).not.toBeInTheDocument();
    await waitFor(() => {
      expect(fetchClassificationRuns).toHaveBeenCalledWith('skill');
    });

    await user.click(screen.getByRole('button', { name: '预览' }));
    expect(await screen.findByText('这次会处理 12 项。')).toBeInTheDocument();
    expect(previewClassificationBatch).toHaveBeenCalledWith(
      'skill',
      { filters: {}, limit: 100 },
      { signal: expect.any(AbortSignal) },
    );

    await user.click(screen.getByRole('button', { name: '开始处理' }));
    expect(startClassificationBatch).toHaveBeenCalledWith(
      'skill',
      { filters: {}, limit: 100 },
    );
  });
});
