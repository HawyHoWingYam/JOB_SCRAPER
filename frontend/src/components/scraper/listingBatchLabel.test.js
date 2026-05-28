import { describe, expect, it } from 'vitest';

import { formatListingBatchOptionLabel } from './listingBatchLabel';

describe('formatListingBatchOptionLabel', () => {
  it('includes running, failed, and manual-review detail counts when they are present', () => {
    const label = formatListingBatchOptionLabel(
      {
        source_site: 'jobsdb',
        crawl_job_id: '11111111-1111-4111-8111-111111111111',
        queued_at: '2026-05-21T08:17:57Z',
        detail_pending: 51,
        detail_running: 12,
        detail_completed: 22,
        detail_failed: 11,
        detail_manual_action_required: 6,
        listings_staged: 96,
      },
      () => '5/21/2026, 4:17:57 PM',
    );

    expect(label).toContain('96 staged / 51 pending / 12 running / 22 completed / 11 failed / 6 manual review');
  });
});
