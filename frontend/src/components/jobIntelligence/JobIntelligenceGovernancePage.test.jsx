import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import canonicalFixture from '../../fixtures/canonical_job_taxonomy_responses.json';
import companyFixture from '../../fixtures/company_industry_responses.json';
import productFixture from '../../fixtures/job_intelligence_product_surfaces.json';
import skillFixture from '../../fixtures/skill_governance_responses.json';

const api = vi.hoisted(() => ({
  fetchGovernanceSummary: vi.fn(),
  fetchCanonicalReviewItems: vi.fn(),
  fetchSkillCandidates: vi.fn(),
  fetchCompanyIndustryReviewItems: vi.fn(),
  fetchCanonicalReviewItem: vi.fn(),
  fetchCanonicalAudit: vi.fn(),
  fetchCanonicalTree: vi.fn(),
  decideCanonicalReviewItem: vi.fn(),
  fetchSkillCandidate: vi.fn(),
  fetchSkillAudit: vi.fn(),
  fetchSkillTree: vi.fn(),
  fetchSkillRecommendations: vi.fn(),
  decideSkillCandidate: vi.fn(),
  fetchCompanyIndustryReviewItem: vi.fn(),
  fetchCompanyIndustryAudit: vi.fn(),
  fetchCompanyIndustryTree: vi.fn(),
  fetchCompanyIndustryMappings: vi.fn(),
  decideCompanyIndustryReviewItem: vi.fn(),
  inspectSourceCatalogProvenance: vi.fn(),
  applySourceCatalogProvenance: vi.fn(),
}));

vi.mock('../../api/jobIntelligence', async () => {
  const actual = await vi.importActual('../../api/jobIntelligence');
  return {
    ...actual,
    ...api,
  };
});

import JobIntelligenceGovernancePage from './JobIntelligenceGovernancePage';

describe('JobIntelligenceGovernancePage', () => {
  beforeEach(() => {
    window.location.hash = '#job-intelligence/job-taxonomy';
    api.fetchGovernanceSummary.mockReset();
    api.fetchCanonicalReviewItems.mockReset();
    api.fetchSkillCandidates.mockReset();
    api.fetchCompanyIndustryReviewItems.mockReset();
    api.fetchCanonicalReviewItem.mockReset();
    api.fetchCanonicalAudit.mockReset();
    api.fetchCanonicalTree.mockReset();
    api.decideCanonicalReviewItem.mockReset();
    api.fetchSkillCandidate.mockReset();
    api.fetchSkillAudit.mockReset();
    api.fetchSkillTree.mockReset();
    api.fetchSkillRecommendations.mockReset();
    api.decideSkillCandidate.mockReset();
    api.fetchCompanyIndustryReviewItem.mockReset();
    api.fetchCompanyIndustryAudit.mockReset();
    api.fetchCompanyIndustryTree.mockReset();
    api.fetchCompanyIndustryMappings.mockReset();
    api.decideCompanyIndustryReviewItem.mockReset();
    api.inspectSourceCatalogProvenance.mockReset();
    api.applySourceCatalogProvenance.mockReset();
    api.fetchGovernanceSummary.mockResolvedValue(productFixture.summary);
    api.fetchCanonicalReviewItems.mockResolvedValue({
      items: [],
      next_cursor: null,
      total: 0,
    });
    api.fetchSkillCandidates.mockResolvedValue({
      items: [],
      next_cursor: null,
      total: 0,
    });
    api.fetchCompanyIndustryReviewItems.mockResolvedValue({
      items: [],
      next_cursor: null,
      total: 0,
    });
    api.fetchCanonicalReviewItem.mockResolvedValue(
      canonicalFixture.review_page.items[0],
    );
    api.fetchCanonicalAudit.mockResolvedValue(productFixture.canonical_audit);
    api.fetchCanonicalTree.mockResolvedValue(canonicalFixture.tree);
    api.decideCanonicalReviewItem.mockResolvedValue({
      subject: { status: 'insufficient_evidence' },
      resulting_projection: null,
      audit_event_id: '90000000-0000-0000-0000-000000000001',
      version: 2,
      replayed: false,
    });
    api.fetchSkillCandidate.mockResolvedValue(
      skillFixture.candidate_page.items[0],
    );
    api.fetchSkillAudit.mockResolvedValue({ items: [], next_cursor: null });
    api.fetchSkillTree.mockResolvedValue(skillFixture.tree);
    api.fetchSkillRecommendations.mockResolvedValue(
      skillFixture.candidate_page.items[0].recommendations,
    );
    api.decideSkillCandidate.mockResolvedValue({
      subject: { status: 'resolved_merged' },
      resulting_projection: null,
      audit_event_id: '90000000-0000-0000-0000-000000000002',
      version: 2,
      replayed: false,
    });
    api.fetchCompanyIndustryReviewItem.mockResolvedValue(
      companyFixture.review_page.items[0],
    );
    api.fetchCompanyIndustryAudit.mockResolvedValue({
      items: [],
      next_cursor: null,
    });
    api.fetchCompanyIndustryTree.mockResolvedValue(companyFixture.tree);
    api.fetchCompanyIndustryMappings.mockResolvedValue(companyFixture.mappings);
    api.decideCompanyIndustryReviewItem.mockResolvedValue({
      subject: { status: 'assigned' },
      resulting_projection: null,
      audit_event_id: '90000000-0000-0000-0000-000000000003',
      version: 2,
      replayed: false,
    });
    api.inspectSourceCatalogProvenance.mockResolvedValue({
      selection: {
        effective_item_count: 0,
        excluded_item_count: 1,
      },
      report: {
        jobs_inspected: 1,
        repairable_jobs: 1,
        already_bound_paths: 0,
        missing_path_jobs: 0,
        unknown_identity_jobs: [],
        write_blockers: [],
        revision_id: 'revision-1',
        revision_fingerprint: 'fingerprint-1',
        repairable_job_ids: ['job-1'],
      },
    });
    api.applySourceCatalogProvenance.mockResolvedValue({
      selection: { effective_item_count: 1, excluded_item_count: 0 },
      repair: { changed_jobs: 1 },
    });
  });

  it('renders the trusted-local shell and deep-linkable peer areas', async () => {
    const user = userEvent.setup();
    render(<JobIntelligenceGovernancePage />);

    expect(
      await screen.findByRole('heading', {
        name: 'Job Intelligence Governance',
      }),
    ).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent(
      'Governance decision routes are not authenticated',
    );
    expect(screen.getByText('6 pending decisions')).toBeInTheDocument();
    expect(
      screen.getByRole('tab', { name: /Job Taxonomy Review 2/ }),
    ).toHaveAttribute('aria-selected', 'true');
    expect(api.fetchCanonicalReviewItems).toHaveBeenCalledWith(
      expect.objectContaining({ status: ['active'] }),
      expect.any(Object),
    );
    expect(
      await screen.findByText('No pending Job Taxonomy Review items.'),
    ).toBeInTheDocument();

    await user.click(screen.getByRole('tab', { name: /Skill Candidates 3/ }));

    await waitFor(() => {
      expect(window.location.hash).toBe(
        '#job-intelligence/skill-candidates',
      );
      expect(api.fetchSkillCandidates).toHaveBeenCalledWith(
        expect.objectContaining({ status: ['pending'] }),
        expect.any(Object),
      );
    });
    expect(
      await screen.findByText('No pending Skill Candidates items.'),
    ).toBeInTheDocument();
  });

  it('renders a deep-linked item even when the current queue is empty', async () => {
    const reviewItem = canonicalFixture.review_page.items[0];
    window.location.hash = `#job-intelligence/job-taxonomy?item=${reviewItem.id}`;

    render(<JobIntelligenceGovernancePage />);

    expect(
      await screen.findByRole('heading', { name: 'Evidence' }),
    ).toBeInTheDocument();
    expect(document.querySelector('.governance-workspace-grid'))
      .toHaveClass('has-selected-item');
    expect(screen.getByText('No pending Job Taxonomy Review items.'))
      .toBeInTheDocument();
    expect(api.fetchCanonicalReviewItem).toHaveBeenCalledWith(
      reviewItem.id,
      expect.any(Object),
    );
  });

  it('deep-links queue search and cursor pagination through the domain adapter', async () => {
    const user = userEvent.setup();
    const candidate = skillFixture.candidate_page.items[0];
    window.location.hash = '#job-intelligence/skill-candidates';
    api.fetchSkillCandidates.mockResolvedValue({
      items: [candidate],
      next_cursor: 'cursor-2',
      total: 2,
    });

    render(<JobIntelligenceGovernancePage />);

    const search = await screen.findByRole('searchbox', {
      name: 'Search Skill Candidates',
    });
    await user.type(search, 'rust async');
    await user.click(screen.getByRole('button', { name: 'Apply queue filter' }));

    await waitFor(() => {
      expect(window.location.hash).toBe(
        '#job-intelligence/skill-candidates?q=rust+async',
      );
      expect(api.fetchSkillCandidates).toHaveBeenLastCalledWith(
        expect.objectContaining({
          status: ['pending'],
          search: 'rust async',
          limit: 10,
        }),
        expect.any(Object),
      );
    });

    await user.click(screen.getByRole('button', { name: 'Next queue page' }));

    await waitFor(() => {
      expect(window.location.hash).toBe(
        '#job-intelligence/skill-candidates?q=rust+async&cursor=cursor-2',
      );
      expect(api.fetchSkillCandidates).toHaveBeenLastCalledWith(
        expect.objectContaining({
          status: ['pending'],
          search: 'rust async',
          cursor: 'cursor-2',
          limit: 10,
        }),
        expect.any(Object),
      );
    });
  });

  it('shows ten-item page controls and preserves the scoped route on a page jump', async () => {
    const user = userEvent.setup();
    window.location.hash = '#job-intelligence/job-taxonomy?source_site=offertoday&source_classification_id=offertoday%3A118000&source_classification_label=%E8%B3%87%E8%A8%8A%E7%A7%91%E6%8A%80&reason=source_catalog_provenance_missing&page=1';
    api.fetchCanonicalReviewItems.mockResolvedValue({
      items: [],
      next_cursor: null,
      total: 25,
      page: 1,
      limit: 10,
      offset: 0,
      page_count: 3,
    });

    render(<JobIntelligenceGovernancePage />);

    expect(await screen.findByText('Page')).toBeInTheDocument();
    expect(screen.getByText(/資訊科技 \(offertoday:118000\)/)).toBeInTheDocument();
    expect(screen.getByText(/Choose any row to begin reviewing evidence/)).toBeInTheDocument();
    expect(screen.getByText('Showing 0 of 25 matching items')).toBeInTheDocument();
    const pageInput = screen.getByRole('spinbutton', { name: 'Queue page number' });
    await user.clear(pageInput);
    await user.type(pageInput, '3');
    await user.click(screen.getByRole('button', { name: 'Go' }));

    await waitFor(() => {
      expect(window.location.hash).toBe(
        '#job-intelligence/job-taxonomy?source_site=offertoday&source_classification_id=offertoday%3A118000&source_classification_label=%E8%B3%87%E8%A8%8A%E7%A7%91%E6%8A%80&reason=source_catalog_provenance_missing&page=3',
      );
      expect(api.fetchCanonicalReviewItems).toHaveBeenLastCalledWith(
        expect.objectContaining({
          reason: ['source_catalog_provenance_missing'],
          page: 3,
          limit: 10,
        }),
        expect.any(Object),
      );
      expect(api.fetchCanonicalReviewItems.mock.calls.at(-1)[0])
        .not.toHaveProperty('sourceClassificationLabel');
    });
  });

  it('does not auto-select the first scoped row and keeps missing labels readable', async () => {
    const user = userEvent.setup();
    const reviewItem = {
      ...canonicalFixture.review_page.items[0],
      job_title: null,
      company_name: null,
    };
    window.location.hash = '#job-intelligence/job-taxonomy?source_site=offertoday&source_classification_id=offertoday%3A118000&source_classification_label=Information%20Technology&reason=source_catalog_provenance_missing';
    api.fetchCanonicalReviewItems.mockResolvedValue({
      items: [reviewItem],
      next_cursor: null,
      total: 1,
      page: 1,
      limit: 10,
      offset: 0,
      page_count: 1,
    });
    api.fetchCanonicalReviewItem.mockResolvedValue(reviewItem);

    render(<JobIntelligenceGovernancePage />);

    const row = await screen.findByRole('button', {
      name: /Job details unavailable/,
    });
    expect(row).toHaveAttribute('aria-pressed', 'false');
    expect(row).toHaveTextContent('Company unavailable');
    expect(screen.getByText(/Choose any row to begin reviewing evidence/))
      .toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Evidence' }))
      .not.toBeInTheDocument();

    await user.click(row);

    const evidenceHeading = await screen.findByRole('heading', { name: 'Evidence' });
    const evidencePanel = evidenceHeading.closest('section');
    expect(evidencePanel).toBeInTheDocument();
    expect(within(evidencePanel).getByText('Job details unavailable'))
      .toBeInTheDocument();
    expect(within(evidencePanel).getByText('Company unavailable'))
      .toBeInTheDocument();
  });

  it('routes source provenance evidence to inspect and confirm instead of taxonomy decisions', async () => {
    const user = userEvent.setup();
    const item = {
      ...canonicalFixture.review_page.items[0],
      reasons: ['source_catalog_provenance_missing'],
    };
    window.location.hash = `#job-intelligence/job-taxonomy?source_site=offertoday&source_classification_id=offertoday%3A118000&reason=source_catalog_provenance_missing&job_id=${item.job_id}&pending_limit=50&item=${item.id}`;
    api.fetchCanonicalReviewItem.mockResolvedValue(item);
    api.fetchCanonicalReviewItems.mockResolvedValue({
      items: [item],
      next_cursor: null,
      total: 1,
      page: 1,
      limit: 10,
      offset: 0,
      page_count: 1,
    });

    render(<JobIntelligenceGovernancePage />);

    expect(await screen.findByText(/source classification evidence is not yet safe/i)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Assign existing Job Subcategory' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Check whether this batch can be repaired' }));
    expect(await screen.findByText('Safe to repair')).toBeInTheDocument();
    expect(api.inspectSourceCatalogProvenance).toHaveBeenCalledWith(
      expect.objectContaining({
        source_sites: ['offertoday'],
        source_classification_ids: ['offertoday:118000'],
        job_ids: [item.job_id],
        reason: 'source_catalog_provenance_missing',
      }),
      50,
    );
    await user.click(screen.getByRole('checkbox'));
    await user.click(screen.getByRole('button', { name: 'Confirm provenance repair' }));

    await waitFor(() => {
      expect(api.applySourceCatalogProvenance).toHaveBeenCalledWith(
        expect.objectContaining({ source_sites: ['offertoday'] }),
        expect.objectContaining({
          revisionId: 'revision-1',
          expectedFingerprint: 'fingerprint-1',
          repairableJobIds: ['job-1'],
        }),
      );
    });
    expect(await screen.findByRole('link', { name: 'Return to AI Enrichment' }))
      .toHaveAttribute('href', '#ai');
  });

  it('supports queue arrow-key focus and explicit narrow-detail back navigation', async () => {
    const user = userEvent.setup();
    const firstCandidate = skillFixture.candidate_page.items[0];
    const secondCandidate = {
      ...firstCandidate,
      id: '50000000-0000-0000-0000-000000000099',
      canonical_raw_name: 'Tokio',
      normalized_key: 'tokio',
    };
    window.location.hash = '#job-intelligence/skill-candidates?q=rust';
    api.fetchSkillCandidates.mockResolvedValue({
      items: [firstCandidate, secondCandidate],
      next_cursor: null,
      total: 2,
    });

    render(<JobIntelligenceGovernancePage />);

    const first = await screen.findByRole('button', {
      name: new RegExp(firstCandidate.canonical_raw_name),
    });
    const second = screen.getByRole('button', {
      name: new RegExp(secondCandidate.canonical_raw_name),
    });
    first.focus();
    await user.keyboard('{ArrowDown}');
    expect(second).toHaveFocus();
    await user.keyboard('{Home}');
    expect(first).toHaveFocus();

    await user.click(first);
    expect(
      await screen.findByRole('heading', { name: 'Evidence' }),
    ).toBeInTheDocument();
    expect(window.location.hash).toBe(
      `#job-intelligence/skill-candidates?item=${firstCandidate.id}&q=rust`,
    );

    const back = screen.getByRole('button', {
      name: 'Back to Skill Candidates queue',
    });
    expect(back).toHaveClass('governance-narrow-back');
    await user.click(back);

    await waitFor(() => {
      expect(window.location.hash).toBe(
        '#job-intelligence/skill-candidates?q=rust',
      );
      expect(first).toHaveFocus();
    });
  });

  it('links the tab panel and supports roving arrow-key navigation', async () => {
    const user = userEvent.setup();
    render(<JobIntelligenceGovernancePage />);

    const taxonomyTab = await screen.findByRole('tab', {
      name: /Job Taxonomy Review 2/,
    });
    const skillTab = screen.getByRole('tab', { name: /Skill Candidates 3/ });
    const panel = screen.getByRole('tabpanel', { name: /Job Taxonomy Review 2/ });

    expect(taxonomyTab).toHaveAttribute('tabindex', '0');
    expect(skillTab).toHaveAttribute('tabindex', '-1');
    expect(taxonomyTab).toHaveAttribute('aria-controls', panel.id);
    expect(panel).toHaveAttribute('aria-labelledby', taxonomyTab.id);

    taxonomyTab.focus();
    await user.keyboard('{ArrowRight}');

    await waitFor(() => {
      expect(window.location.hash).toBe('#job-intelligence/skill-candidates');
      expect(skillTab).toHaveFocus();
      expect(skillTab).toHaveAttribute('aria-selected', 'true');
      expect(skillTab).toHaveAttribute('tabindex', '0');
      expect(taxonomyTab).toHaveAttribute('tabindex', '-1');
    });
  });

  it('normalizes non-Error summary and queue failures into stable messages', async () => {
    api.fetchGovernanceSummary.mockRejectedValue('summary transport failed');
    api.fetchCanonicalReviewItems.mockRejectedValue({
      code: 'CANONICAL_QUEUE_UNAVAILABLE',
    });

    render(<JobIntelligenceGovernancePage />);

    expect(await screen.findByText(
      'Governance summary unavailable: summary transport failed',
    )).toHaveAttribute('role', 'status');
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Could not load Job Taxonomy Review: CANONICAL_QUEUE_UNAVAILABLE',
    );
  });

  it('reviews and confirms a canonical decision through the governed contract', async () => {
    const user = userEvent.setup();
    api.fetchCanonicalReviewItems.mockResolvedValue(
      canonicalFixture.review_page,
    );
    render(<JobIntelligenceGovernancePage />);

    const reviewItem = canonicalFixture.review_page.items[0];
    await user.click(
      await screen.findByRole('button', {
        name: new RegExp(reviewItem.job_title),
      }),
    );

    expect(
      await screen.findByRole('heading', { name: 'Evidence' }),
    ).toBeInTheDocument();
    expect(
      screen.getAllByText('classifier_provenance_missing').length,
    ).toBeGreaterThan(0);
    expect(screen.getByText('Accounts Payable')).toBeInTheDocument();
    await user.click(screen.getByText('View technical evidence'));
    expect(screen.getByText(reviewItem.job_id)).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Audit timeline' })).toBeInTheDocument();

    await user.click(
      screen.getByRole('button', { name: 'Mark insufficient evidence' }),
    );

    const dialog = screen.getByRole('alertdialog', {
      name: 'Confirm governance decision',
    });
    expect(dialog).toHaveTextContent('1 Job');
    expect(dialog).toHaveTextContent('classifier_provenance_missing');
    expect(dialog).toHaveTextContent(
      'The Job remains Unassigned until new evidence is reviewed',
    );

    await user.click(
      screen.getByRole('button', { name: 'Confirm decision' }),
    );

    await waitFor(() => {
      expect(api.decideCanonicalReviewItem).toHaveBeenCalledWith(
        reviewItem.id,
        expect.objectContaining({
          action: 'mark_insufficient_evidence',
          expectedVersion: 1,
        }),
        expect.any(Object),
      );
    });
    expect(await screen.findByRole('status')).toHaveTextContent(
      'Decision recorded',
    );
    await waitFor(() => {
      expect(screen.getByRole('searchbox', { name: 'Filter by Job ID' }))
        .toHaveFocus();
    });
  });

  it('keeps decision-dialog focus contained and restores its trigger on Escape', async () => {
    const user = userEvent.setup();
    api.fetchCanonicalReviewItems.mockResolvedValue(canonicalFixture.review_page);
    render(<JobIntelligenceGovernancePage />);

    const reviewItem = canonicalFixture.review_page.items[0];
    await user.click(await screen.findByRole('button', {
      name: new RegExp(reviewItem.job_title),
    }));
    await screen.findByRole('heading', { name: 'Evidence' });
    const trigger = screen.getByRole('button', { name: 'Mark insufficient evidence' });
    await user.click(trigger);

    const dialog = screen.getByRole('alertdialog', {
      name: 'Confirm governance decision',
    });
    const cancel = within(dialog).getByRole('button', { name: 'Cancel' });
    const confirm = within(dialog).getByRole('button', { name: 'Confirm decision' });
    expect(dialog).toHaveAttribute('aria-describedby');
    expect(document.getElementById(dialog.getAttribute('aria-describedby')))
      .toHaveTextContent('The Job remains Unassigned until new evidence is reviewed');
    expect(cancel).toHaveFocus();

    confirm.focus();
    await user.tab();
    expect(cancel).toHaveFocus();
    screen.getByRole('tab', { name: /Skill Candidates 3/ }).focus();
    await user.tab();
    expect(cancel).toHaveFocus();

    await user.keyboard('{Escape}');
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
    await waitFor(() => expect(trigger).toHaveFocus());
  });

  it('names partial detail failures and disables only target-dependent actions', async () => {
    const user = userEvent.setup();
    const reviewItem = canonicalFixture.review_page.items[0];
    api.fetchCanonicalReviewItems.mockResolvedValue(canonicalFixture.review_page);
    api.fetchCanonicalAudit.mockRejectedValue(new Error('audit service offline'));
    api.fetchCanonicalTree.mockRejectedValue({
      code: 'CANONICAL_TARGETS_UNAVAILABLE',
    });
    render(<JobIntelligenceGovernancePage />);

    await user.click(await screen.findByRole('button', {
      name: new RegExp(reviewItem.job_title),
    }));

    expect(await screen.findByText('Audit timeline: audit service offline'))
      .toBeInTheDocument();
    expect(screen.getByText('Governed targets: CANONICAL_TARGETS_UNAVAILABLE'))
      .toBeInTheDocument();
    expect(screen.getByRole('button', {
      name: 'Assign existing Job Subcategory',
    })).toBeDisabled();
    expect(screen.getByRole('button', {
      name: 'Mark insufficient evidence',
    })).toBeEnabled();
  });

  it('shows the active HSIC tree and reviewed Source Industry mappings', async () => {
    const user = userEvent.setup();
    const reviewItem = companyFixture.review_page.items[0];
    window.location.hash = '#job-intelligence/company-industries';
    api.fetchCompanyIndustryReviewItems.mockResolvedValue(
      companyFixture.review_page,
    );
    render(<JobIntelligenceGovernancePage />);

    await user.click(
      await screen.findByRole('button', {
        name: new RegExp(reviewItem.raw_value),
      }),
    );

    expect(
      await screen.findByRole('heading', { name: 'Company Industry context' }),
    ).toBeInTheDocument();
    expect(screen.getByText(companyFixture.revision.release_key)).toBeInTheDocument();
    expect(
      screen.getByText('J · Information and communications'),
    ).toBeInTheDocument();
    expect(screen.getByText('Software consultancy')).toBeInTheDocument();
    expect(
      screen.getByText(companyFixture.mappings[0].target_node_id),
    ).toBeInTheDocument();
  });

  it.each([
    {
      actionLabel: 'Assign existing Company Industry',
      action: 'assign_existing_industry',
      requiresTarget: true,
    },
    {
      actionLabel: 'Assign as Primary Company Industry',
      action: 'assign_existing_primary_industry',
      requiresTarget: true,
    },
    {
      actionLabel: 'Approve mapping and assign',
      action: 'approve_mapping_and_assign',
      requiresTarget: true,
    },
    {
      actionLabel: 'Approve mapping and assign Primary',
      action: 'approve_mapping_and_assign_primary',
      requiresTarget: true,
    },
    {
      actionLabel: 'Mark insufficient evidence',
      action: 'mark_insufficient_evidence',
      requiresTarget: false,
    },
    {
      actionLabel: 'Mark as not Company Industry',
      action: 'mark_not_company_industry',
      requiresTarget: false,
    },
  ])('confirms the $action Company Industry action', async ({
    actionLabel,
    action,
    requiresTarget,
  }) => {
    const user = userEvent.setup();
    const reviewItem = companyFixture.review_page.items[0];
    window.location.hash = '#job-intelligence/company-industries';
    api.fetchCompanyIndustryReviewItems.mockResolvedValue(
      companyFixture.review_page,
    );
    render(<JobIntelligenceGovernancePage />);

    await user.click(
      await screen.findByRole('button', {
        name: new RegExp(reviewItem.raw_value),
      }),
    );
    await screen.findByRole('heading', { name: 'Evidence' });
    await user.click(screen.getByRole('button', { name: actionLabel }));
    await user.click(screen.getByRole('button', { name: 'Confirm decision' }));

    await waitFor(() => {
      expect(api.decideCompanyIndustryReviewItem).toHaveBeenCalledOnce();
    });
    const [subjectId, values] =
      api.decideCompanyIndustryReviewItem.mock.calls[0];
    expect(subjectId).toBe(reviewItem.id);
    expect(values).toEqual(
      expect.objectContaining({
        action,
        expectedVersion: reviewItem.version,
      }),
    );
    if (requiresTarget) {
      expect(values.targetId).toBe(companyFixture.tree.nodes[0].id);
    } else {
      expect(values).not.toHaveProperty('targetId');
    }
  });

  it('closes a stale Company Industry decision and reloads its evidence', async () => {
    const user = userEvent.setup();
    const reviewItem = companyFixture.review_page.items[0];
    window.location.hash = '#job-intelligence/company-industries';
    api.fetchCompanyIndustryReviewItems.mockResolvedValue(
      companyFixture.review_page,
    );
    api.decideCompanyIndustryReviewItem.mockRejectedValue(
      Object.assign(new Error('Stale governance decision'), {
        status: 409,
        code: 'GOVERNANCE_DECISION_STALE_VERSION',
      }),
    );
    render(<JobIntelligenceGovernancePage />);

    await user.click(
      await screen.findByRole('button', {
        name: new RegExp(reviewItem.raw_value),
      }),
    );
    await screen.findByRole('heading', { name: 'Evidence' });
    await user.click(
      screen.getByRole('button', { name: 'Mark insufficient evidence' }),
    );
    await user.click(screen.getByRole('button', { name: 'Confirm decision' }));

    expect(
      await screen.findByText(
        'This item changed before confirmation. Evidence was reloaded; review the latest version.',
      ),
    ).toBeInTheDocument();
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
    await waitFor(() => {
      expect(api.fetchCompanyIndustryReviewItem).toHaveBeenCalledTimes(2);
    });
  });

  it('loads Company Industry descendants only when the operator browses a root', async () => {
    const user = userEvent.setup();
    const reviewItem = companyFixture.review_page.items[0];
    const root = companyFixture.tree.nodes[0];
    const child = companyFixture.child_tree.nodes[0];
    window.location.hash = '#job-intelligence/company-industries';
    api.fetchCompanyIndustryReviewItems.mockResolvedValue(
      companyFixture.review_page,
    );
    api.fetchCompanyIndustryTree.mockImplementation((filters = {}) =>
      Promise.resolve(
        filters.parentId === root.id
          ? companyFixture.child_tree
          : companyFixture.tree,
      ),
    );
    render(<JobIntelligenceGovernancePage />);

    await user.click(
      await screen.findByRole('button', {
        name: new RegExp(reviewItem.raw_value),
      }),
    );
    await screen.findByRole('heading', { name: 'Evidence' });
    await user.click(
      screen.getByRole('button', {
        name: 'Assign existing Company Industry',
      }),
    );
    await user.click(
      screen.getByRole('button', { name: 'Show child Industries' }),
    );

    expect(
      await screen.findByRole('option', {
        name: '62 · Information technology service activities',
      }),
    ).toBeInTheDocument();
    expect(
      within(screen.getByRole('alertdialog')).getByText(
        'J · Information and communications',
      ),
    ).toBeInTheDocument();
    expect(api.fetchCompanyIndustryTree).toHaveBeenCalledWith(
      { parentId: root.id },
      undefined,
    );

    await user.click(screen.getByRole('button', { name: 'Confirm decision' }));
    await waitFor(() => {
      expect(api.decideCompanyIndustryReviewItem).toHaveBeenCalledWith(
        reviewItem.id,
        expect.objectContaining({ targetId: child.id }),
        expect.any(Object),
      );
    });
  });

  it.each([
    {
      actionLabel: 'Merge into governed Skill',
      expected: () => ({
        action: 'merge_existing',
        targetSkillId:
          skillFixture.tree.categories[0].technologies[0].skills[0].id,
      }),
    },
    {
      actionLabel: 'Create governed Skill',
      fill: async (user) => {
        await user.type(screen.getByLabelText('Skill Category code'), 'backend');
        await user.type(
          screen.getByLabelText('Technology code'),
          'backend.rust',
        );
        await user.type(screen.getByLabelText('Stable Skill code'), 'backend.rust.rust');
        await user.type(screen.getByLabelText('Skill name'), 'Rust');
        await user.type(screen.getByLabelText('Aliases'), 'Rustlang, Rust Language');
      },
      expected: () => ({
        action: 'create_skill',
        createTarget: {
          category_code: 'backend',
          technology_code: 'backend.rust',
          stable_code: 'backend.rust.rust',
          name: 'Rust',
          aliases: ['Rustlang', 'Rust Language'],
        },
      }),
    },
    {
      actionLabel: 'Classify as generic',
      fill: async (user) => {
        await user.type(screen.getByLabelText('Generic tag'), 'Programming concept');
      },
      expected: () => ({
        action: 'classify_generic',
        genericTag: 'Programming concept',
      }),
    },
    {
      actionLabel: 'Reject candidate',
      fill: async (user) => {
        await user.type(
          screen.getByLabelText('Rejection reason'),
          'Not technical evidence',
        );
      },
      expected: () => ({
        action: 'reject',
        rejectionReason: 'Not technical evidence',
      }),
    },
  ])('confirms the $actionLabel Skill Candidate action', async ({
    actionLabel,
    fill,
    expected,
  }) => {
    const user = userEvent.setup();
    const candidate = skillFixture.candidate_page.items[0];
    window.location.hash = '#job-intelligence/skill-candidates';
    api.fetchSkillCandidates.mockResolvedValue({
      items: [candidate],
      next_cursor: null,
      total: 1,
    });
    render(<JobIntelligenceGovernancePage />);

    await user.click(
      await screen.findByRole('button', { name: new RegExp(candidate.canonical_raw_name) }),
    );
    await screen.findByRole('heading', { name: 'Evidence' });
    await user.click(screen.getByRole('button', { name: actionLabel }));
    if (fill) await fill(user);
    await user.click(screen.getByRole('button', { name: 'Confirm decision' }));

    await waitFor(() => {
      expect(api.decideSkillCandidate).toHaveBeenCalledWith(
        candidate.id,
        expect.objectContaining({
          ...expected(),
          expectedVersion: candidate.version,
        }),
        expect.any(Object),
      );
    });
  });
});
