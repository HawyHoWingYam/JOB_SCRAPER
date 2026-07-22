import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({
  previewCanonicalTaxonomyRecovery: vi.fn(),
  createCanonicalTaxonomyRecoveryRun: vi.fn(),
  fetchCanonicalTaxonomyRecoveryRun: vi.fn(),
  retryCanonicalTaxonomyRecoveryRun: vi.fn(),
}));

vi.mock('../../api/jobIntelligence', () => api);

import CanonicalTaxonomyRecoveryPanel from './CanonicalTaxonomyRecoveryPanel';

const scope = {
  sourceSites: ['offertoday'],
  sourceClassificationIds: ['offertoday:118000'],
  jobIds: ['job-1', 'job-2'],
  reason: 'classifier_provenance_missing',
  pendingLimit: 5000,
};

describe('CanonicalTaxonomyRecoveryPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.previewCanonicalTaxonomyRecovery.mockResolvedValue({
      selected_count: 2,
      scope_fingerprint: 'scope-hash',
      taxonomy_revision: { id: 'taxonomy-1' },
      mapping_revision: { id: 'mapping-1' },
      counts_by_reason: {
        classifier_output_invalid: 1,
        classifier_provenance_missing: 1,
      },
      sample: [{ job_id: 'job-1', title: 'Backend Engineer', company_name: 'Acme' }],
    });
    api.createCanonicalTaxonomyRecoveryRun.mockResolvedValue({
      id: 'run-1',
      status: 'pending',
      total_items: 2,
      completed_items: 0,
      failed_items: 0,
    });
  });

  it('requires preview and explicit confirmation before queueing taxonomy-only work', async () => {
    const user = userEvent.setup();
    render(<CanonicalTaxonomyRecoveryPanel scope={scope} />);

    await user.click(screen.getByRole('button', { name: 'Preview AI taxonomy recovery' }));
    expect(await screen.findByText('Preview: 2 Jobs would be processed')).toBeInTheDocument();
    expect(screen.getByText(/does not rerun Skills, Summary, or Experience/)).toBeInTheDocument();

    const confirm = screen.getByRole('button', { name: 'Confirm and queue 2 Jobs' });
    expect(confirm).toBeDisabled();
    await user.click(screen.getByRole('checkbox'));
    await user.click(confirm);

    expect(api.createCanonicalTaxonomyRecoveryRun).toHaveBeenCalledWith(
      scope,
      {
        expectedScopeFingerprint: 'scope-hash',
        taxonomyRevisionId: 'taxonomy-1',
        mappingRevisionId: 'mapping-1',
      },
    );
    expect(await screen.findByText('Recovery run pending')).toBeInTheDocument();
  });

  it('does not offer taxonomy recovery for source evidence failures', () => {
    render(
      <CanonicalTaxonomyRecoveryPanel
        scope={{ ...scope, reason: 'source_catalog_provenance_missing' }}
      />,
    );
    expect(screen.queryByText('Re-run Job Taxonomy only')).not.toBeInTheDocument();
  });
});
