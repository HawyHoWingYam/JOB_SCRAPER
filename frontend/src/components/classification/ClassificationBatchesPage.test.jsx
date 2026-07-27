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
    );
    expect(start).toBeEnabled();

    await user.click(start);
    expect(startClassificationBatch).toHaveBeenCalledWith(
      'job_taxonomy',
      { filters: { source_sites: ['jobsdb'] }, limit: 25 },
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
  });
});
