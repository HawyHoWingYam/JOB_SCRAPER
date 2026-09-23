import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import ClassificationBatchesPage from './ClassificationBatchesPage';
import { fetchCurrentSkillTree } from '../../api/currentTaxonomies';
import {
  approveSkillMaintenance,
  decideSkillCandidate,
  fetchSkillCandidates,
  fetchSkillMaintenanceStatus,
  previewJevSkillBackfill,
  runSkillMaintenanceNow,
  startJevSkillBackfill,
} from '../../api/skillCandidates';

vi.mock('../../api/currentTaxonomies', () => ({ fetchCurrentSkillTree: vi.fn() }));
vi.mock('../../api/skillCandidates', () => ({
  approveSkillMaintenance: vi.fn(),
  decideSkillCandidate: vi.fn(),
  fetchSkillCandidates: vi.fn(),
  fetchSkillMaintenanceStatus: vi.fn(),
  previewJevSkillBackfill: vi.fn(),
  runSkillMaintenanceNow: vi.fn(),
  startJevSkillBackfill: vi.fn(),
}));

const candidate = {
  id: 'candidate-1', canonical_raw_name: 'React', normalized_key: 'react',
  raw_variants: ['React.js'], occurrence_count: 12, distinct_job_count: 10,
  recommendations: [{ code: 'typescript', name: 'TypeScript', category: 'Frontend', technology: 'Web', score: 0.72 }],
  evidence: [{
    job_id: 'job-1', title: 'Frontend Engineer', source_site: 'jobsdb',
    evidence_excerpt: 'React is preferred for this role.',
    jev: {
      status: 'answered', model: 'typesafe/jev-1.13', request_id: 'gen-1',
      decision: { route: 'candidate', confidence: 0.82 },
    },
  }],
};
const tree = { nodes: [
  { code: 'frontend', level: 'category', labels: { en: 'Frontend' }, is_assignable: false },
  { code: 'web', level: 'technology', parent_code: 'frontend', labels: { en: 'Web' }, is_assignable: false },
  { code: 'typescript', level: 'skill', parent_code: 'web', labels: { en: 'TypeScript' }, is_assignable: true },
] };

describe('ClassificationBatchesPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    fetchSkillCandidates.mockResolvedValue({ threshold: 10, recommendation_limit: 5, evidence_limit: 5, items: [candidate] });
    fetchCurrentSkillTree.mockResolvedValue(tree);
    fetchSkillMaintenanceStatus.mockResolvedValue({
      eligibility: { enabled: true, eligible_count: 1, minimum_count: 50, can_start: false, reason: 'insufficient_candidates' },
      latest_batch: null,
    });
    runSkillMaintenanceNow.mockResolvedValue({ dispatched: false, reason: 'insufficient_candidates', batch: null });
    previewJevSkillBackfill.mockResolvedValue({ eligible_count: 12, already_current_count: 30, reserved_count: 2, selected_item_count: 12 });
    startJevSkillBackfill.mockResolvedValue({ id: 'backfill-run-1', total_items: 12 });
    approveSkillMaintenance.mockResolvedValue({ status: 'applied', applied_changes: [], held_for_approval_count: 0 });
    decideSkillCandidate.mockResolvedValue({ resolved_skill_code: 'typescript' });
  });

  it('renders a compact candidate list and evidence panel', async () => {
    render(<ClassificationBatchesPage />);
    expect(await screen.findByRole('heading', { name: 'Skills to review' })).toBeInTheDocument();
    expect(screen.getByText('Frontend Engineer')).toBeInTheDocument();
    expect(screen.getByText('React is preferred for this role.')).toBeInTheDocument();
    expect(screen.getByText('Jev recommends keeping this Candidate')).toBeInTheDocument();
    expect(screen.getByText('Confidence 82%')).toBeInTheDocument();
    expect(screen.getByText('receipt gen-1')).toBeInTheDocument();
    expect(screen.getByText('Up to 1 matches')).toBeInTheDocument();
    expect(screen.getByLabelText('Search Candidates')).toBeInTheDocument();
  });

  it.each(['empty', 'failed'])('distinguishes initial loading from a %s Candidate queue', async (outcome) => {
    let finish;
    fetchSkillCandidates.mockImplementation(() => new Promise((resolve, reject) => {
      finish = () => outcome === 'empty'
        ? resolve({ items: [], total: 0, threshold: 10 })
        : reject(new Error('Candidate queue unavailable'));
    }));
    render(<ClassificationBatchesPage />);
    expect(screen.getByText('Loading…')).toBeVisible();
    expect(screen.queryByText('There are no Skills to review.')).not.toBeInTheDocument();
    finish();
    if (outcome === 'empty') {
      expect(await screen.findByText('There are no Skills to review.')).toBeVisible();
      expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    } else {
      expect(await screen.findByRole('alert')).toHaveTextContent('Candidate queue unavailable');
      expect(screen.queryByText('There are no Skills to review.')).not.toBeInTheDocument();
    }
  });

  it('confirms a recommended existing Skill and removes the candidate', async () => {
    const user = userEvent.setup();
    render(<ClassificationBatchesPage />);
    await screen.findByRole('heading', { name: 'Skills to review' });
    await user.click(await screen.findByRole('button', { name: /TypeScript/ }));
    await user.click(screen.getByRole('button', { name: 'Save and next' }));
    await waitFor(() => expect(decideSkillCandidate).toHaveBeenCalledWith('candidate-1', {
      action: 'match_existing', skill_code: 'typescript',
    }));
    await waitFor(() => expect(screen.queryByRole('heading', { name: 'React' })).not.toBeInTheDocument());
  });

  it('requires a structured reason for generic and rejection decisions', async () => {
    const user = userEvent.setup();
    render(<ClassificationBatchesPage />);
    await screen.findByRole('heading', { name: 'Skills to review' });
    await user.click(screen.getByRole('button', { name: 'Generic term' }));
    expect(screen.getByRole('button', { name: 'Save and next' })).toBeDisabled();
    await user.selectOptions(screen.getByLabelText('Reason'), 'general_capability');
    await user.click(screen.getByRole('button', { name: 'Save and next' }));
    expect(decideSkillCandidate).toHaveBeenCalledWith('candidate-1', {
      action: 'generic', generic_tag: 'general_capability',
    });
  });

  it('supports creating under existing Technology with explicit aliases', async () => {
    const user = userEvent.setup();
    render(<ClassificationBatchesPage />);
    await screen.findByRole('heading', { name: 'Skills to review' });
    await user.click(screen.getByRole('button', { name: 'Create new Skill' }));
    await user.click(screen.getByRole('option', { name: 'Frontend → Web' }));
    await user.click(screen.getByLabelText('React.js'));
    await user.click(screen.getByRole('button', { name: 'Save and next' }));
    expect(decideSkillCandidate).toHaveBeenCalledWith('candidate-1', expect.objectContaining({
      action: 'create', category_code: 'frontend', technology_code: 'web', name: 'React', aliases: ['React.js'],
    }));
  });

  it('keeps candidate review available when maintenance status fails', async () => {
    fetchSkillMaintenanceStatus.mockRejectedValueOnce(new Error('Maintenance offline'));
    render(<ClassificationBatchesPage />);
    expect(await screen.findByText('Frontend Engineer')).toBeInTheDocument();
    expect(await screen.findByText(/Could not load maintenance status: Maintenance offline/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Run maintenance now' })).toBeDisabled();
    expect(screen.getByText('Jev recommends keeping this Candidate')).toBeInTheDocument();
  });

  it('reports an unavailable taxonomy clearly', async () => {
    fetchCurrentSkillTree.mockResolvedValueOnce({ nodes: [] });
    render(<ClassificationBatchesPage />);
    expect(await screen.findByRole('alert')).toHaveTextContent('taxonomy is not ready');
  });

  it('paginates the candidate queue instead of relying on page scrolling', async () => {
    const user = userEvent.setup();
    fetchSkillCandidates
      .mockResolvedValueOnce({ threshold: 10, total_count: 30, items: [candidate] })
      .mockResolvedValueOnce({ threshold: 10, total_count: 30, items: [{ ...candidate, id: 'candidate-2', canonical_raw_name: 'Python' }] });
    render(<ClassificationBatchesPage />);
    expect(await screen.findByRole('button', { name: 'Next page' })).toBeEnabled();
    await user.click(screen.getByRole('button', { name: 'Next page' }));
    await waitFor(() => expect(fetchSkillCandidates).toHaveBeenLastCalledWith(expect.objectContaining({ limit: 25, offset: 25 })));
    expect(await screen.findByRole('heading', { name: 'Python' })).toBeInTheDocument();
  });

  it('runs a free maintenance eligibility path without treating it as approval', async () => {
    const user = userEvent.setup();
    render(<ClassificationBatchesPage />);
    await screen.findByRole('heading', { name: 'Skills to review' });

    await user.click(screen.getByRole('button', { name: 'Run maintenance now' }));

    await waitFor(() => expect(runSkillMaintenanceNow).toHaveBeenCalledTimes(1));
    expect(await screen.findByRole('status')).toHaveTextContent('No provider call: insufficient_candidates.');
  });

  it('shows the complete new-Skill diff before aggregate approval', async () => {
    fetchSkillMaintenanceStatus.mockResolvedValueOnce({
      eligibility: { enabled: true, eligible_count: 1, minimum_count: 1, can_start: true },
      latest_batch: {
        id: 'batch-1', status: 'ready_for_approval', auto_applied_count: 0,
        held_for_approval_count: 1, taxonomy_snapshot_sha256: 'abcdef1234567890',
        settings_snapshot: { model: 'strong/model' },
        proposals: [{
          candidate_id: 'candidate-1', candidate_name: 'NovelDB', action: 'propose_new',
          technology_code: 'backend.databases', confidence: 0.97, parent_confidence: 0.94,
        }],
      },
    });

    render(<ClassificationBatchesPage />);

    const diff = await screen.findByLabelText('Proposed Skill changes');
    expect(diff).toHaveTextContent('Batch batch-1 · taxonomy abcdef123456');
    expect(diff).toHaveTextContent('NovelDB');
    expect(diff).toHaveTextContent('Create under backend.databases');
    expect(diff).toHaveTextContent('confidence 97%');
    expect(diff).toHaveTextContent('parent confidence 94%');
    expect(screen.getByRole('button', { name: 'Approve proposed Skills' })).toBeVisible();
  });

  it('previews a free bounded historical backfill before queueing it', async () => {
    const user = userEvent.setup();
    render(<ClassificationBatchesPage />);
    await screen.findByRole('heading', { name: 'Skills to review' });

    await user.clear(screen.getByLabelText('Jev Skill backfill limit'));
    await user.type(screen.getByLabelText('Jev Skill backfill limit'), '12');
    await user.click(screen.getByRole('button', { name: 'Preview backfill' }));

    await waitFor(() => expect(previewJevSkillBackfill).toHaveBeenCalledWith(12));
    expect(screen.getByText(/12 eligible · 30 already current · 2 reserved · 12 selected/)).toBeVisible();
    expect(screen.getByRole('status')).toHaveTextContent('free database read');
    await user.click(screen.getByRole('button', { name: 'Start bounded backfill' }));
    await waitFor(() => expect(startJevSkillBackfill).toHaveBeenCalledWith(12));
    expect(await screen.findByRole('status')).toHaveTextContent('backfill-run-1');
  });
});
