import { useEffect, useMemo, useState } from 'react';
import { ArrowDown, ArrowUp, Check, ChevronRight, Search, SkipForward, X } from 'lucide-react';
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
import './ClassificationBatchesPage.css';

const GENERIC_REASONS = [
  ['general_capability', '通用能力'],
  ['responsibility', '职责描述'],
  ['job_attribute', '职位属性'],
  ['not_a_skill', '非技能'],
];
const REJECTION_REASONS = [
  ['noise', '噪声'],
  ['parse_error', '解析错误'],
  ['too_specific', '过于具体'],
  ['inappropriate', '敏感或不适合'],
];

function nodeLabel(node) {
  return node?.labels?.en || node?.labels?.en_HK || node?.code || '';
}

function jevStatusLabel(item) {
  if (!item?.jev) return '未经过 Jev';
  if (item.jev.status === 'answered') {
    const route = item.jev.decision?.route;
    if (route === 'candidate') return 'Jev 建议保留 Candidate';
    if (route === 'match_existing') return 'Jev 建议现有 Skill';
    return 'Jev 已回答';
  }
  if (item.jev.status === 'unavailable') return 'Jev 暂不可用';
  if (item.jev.status === 'invalid') return 'Jev 回答无效';
  return `Jev ${item.jev.status}`;
}

function proposalSummary(proposal) {
  if (proposal.action === 'propose_new') {
    return proposal.technology_code
      ? `Create under ${proposal.technology_code}`
      : 'Conflict: no valid parent Technology';
  }
  if (proposal.action === 'insufficient') return 'Unresolved: insufficient evidence';
  if (proposal.action === 'stale') return 'Conflict: Candidate changed';
  if (proposal.action === 'invalid') return 'Conflict: invalid Jev answer';
  return `Held: ${proposal.action || 'unknown action'}`;
}

function normalizedBackfillLimit(value) {
  return Math.max(1, Math.min(5000, Number(value) || 1));
}

function CandidateList({ candidates, selectedId, onSelect }) {
  return (
    <div className="skill-review-list" role="listbox" aria-label="待确认 Skill">
      {candidates.map((candidate) => (
        <button
          type="button"
          role="option"
          aria-selected={candidate.id === selectedId}
          className={`skill-review-list-item ${candidate.id === selectedId ? 'selected' : ''}`}
          key={candidate.id}
          onClick={() => onSelect(candidate.id)}
        >
          <span className="skill-review-list-copy">
            <strong>{candidate.canonical_raw_name}</strong>
            <small>{Number(candidate.distinct_job_count).toLocaleString()} 份 Job</small>
          </span>
          <ChevronRight size={17} aria-hidden="true" />
        </button>
      ))}
    </div>
  );
}

function MaintenancePanel({ payload, busy, feedback, onRun, onApprove }) {
  const eligibility = payload?.eligibility || {};
  const batch = payload?.latest_batch;
  return (
    <section className="skill-maintenance-panel" aria-label="Jev Skill maintenance">
      <div>
        <strong>Jev taxonomy maintenance</strong>
        <p>
          {eligibility.eligible_count ?? 0} exceptions · starts at {eligibility.minimum_count ?? 50}
          {eligibility.enabled ? '' : ' · disabled in Settings'}
        </p>
        {batch && (
          <>
            <small>
              Latest: {batch.status} · {batch.auto_applied_count} auto-applied · {batch.held_for_approval_count} awaiting aggregate approval
            </small>
            <small>
              {batch.receipt?.model || batch.settings_snapshot?.model || 'unknown model'}
              {batch.receipt?.request_id ? ` · receipt ${batch.receipt.request_id}` : ''}
              {batch.receipt?.usage?.cost != null ? ` · cost USD ${Number(batch.receipt.usage.cost).toFixed(5)}` : ''}
            </small>
            {batch.proposals?.length > 0 && (
              <div className="skill-maintenance-diff" aria-label="Proposed Skill changes">
                <strong>Approval diff</strong>
                <small>
                  Batch {batch.id} · taxonomy {batch.taxonomy_snapshot_sha256?.slice(0, 12) || 'unknown'}
                </small>
                <ul>
                  {batch.proposals.map((proposal) => (
                    <li key={`${proposal.candidate_id}-${proposal.action}`}>
                      <span>{proposal.candidate_name || proposal.candidate_id}</span>
                      <small>
                        {proposalSummary(proposal)}
                        {proposal.confidence != null ? ` · confidence ${(Number(proposal.confidence) * 100).toFixed(0)}%` : ''}
                        {proposal.parent_confidence != null ? ` · parent confidence ${(Number(proposal.parent_confidence) * 100).toFixed(0)}%` : ''}
                      </small>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </>
        )}
        {feedback && <small role="status">{feedback}</small>}
      </div>
      <div className="skill-maintenance-actions">
        <button type="button" onClick={onRun} disabled={busy || !eligibility.enabled}>
          {busy === 'run' ? 'Running maintenance…' : 'Run maintenance now'}
        </button>
        {batch?.status === 'ready_for_approval' && (
          <button type="button" onClick={() => onApprove(batch.id)} disabled={Boolean(busy)}>
            {busy === 'approve' ? 'Approving…' : 'Approve proposed Skills'}
          </button>
        )}
      </div>
    </section>
  );
}

function BackfillPanel({ limit, plan, busy, feedback, onLimit, onPreview, onStart }) {
  return (
    <section className="skill-maintenance-panel" aria-label="Historical Jev Skill backfill">
      <div>
        <strong>Historical Jev Skill backfill</strong>
        <p>Classify an oldest-first bounded slice through the existing enrichment worker.</p>
        {plan && (
          <small>
            {plan.eligible_count} eligible · {plan.already_current_count} already current · {plan.reserved_count} reserved · {plan.selected_item_count} selected
          </small>
        )}
        {feedback && <small role="status">{feedback}</small>}
      </div>
      <div className="skill-maintenance-actions">
        <label className="skill-backfill-limit">
          <span>Backfill limit</span>
          <input
            aria-label="Jev Skill backfill limit"
            type="number"
            min="1"
            max="5000"
            value={limit}
            onChange={(event) => onLimit(event.target.value)}
          />
        </label>
        <button type="button" onClick={onPreview} disabled={Boolean(busy)}>
          {busy === 'preview' ? 'Previewing…' : 'Preview backfill'}
        </button>
        <button type="button" onClick={onStart} disabled={Boolean(busy) || !plan?.selected_item_count}>
          {busy === 'start' ? 'Queueing…' : 'Start bounded backfill'}
        </button>
      </div>
    </section>
  );
}

function SearchableOptionList({ label, placeholder, options, value, onChange, renderOption }) {
  const [query, setQuery] = useState('');
  const filtered = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    return needle
      ? options.filter((option) => renderOption(option).toLocaleLowerCase().includes(needle))
      : options;
  }, [options, query, renderOption]);
  return (
    <div className="skill-option-picker">
      <label className="skill-review-field">
        <span>{label}</span>
        <div className="skill-review-search skill-option-search">
          <Search size={15} aria-hidden="true" />
          <input aria-label={label} placeholder={placeholder} value={query} onChange={(event) => setQuery(event.target.value)} />
        </div>
      </label>
      <div className="skill-option-list" role="listbox" aria-label={`${label}选项`}>
        {filtered.slice(0, 80).map((option) => {
          const optionValue = option.code;
          return (
            <button type="button" role="option" aria-selected={value === optionValue} className={value === optionValue ? 'selected' : ''} key={optionValue} onClick={() => onChange(optionValue)}>
              {renderOption(option)}
            </button>
          );
        })}
        {!filtered.length && <p className="skill-review-muted">没有匹配的选项。</p>}
        {filtered.length > 80 && <p className="skill-review-muted">请输入关键词缩小范围。</p>}
      </div>
    </div>
  );
}

function ReviewPanel({ candidate, nodes, onResolved, onSkip, onClose }) {
  const [action, setAction] = useState('');
  const [skillCode, setSkillCode] = useState('');
  const [technologyCode, setTechnologyCode] = useState('');
  const [name, setName] = useState(candidate.canonical_raw_name);
  const [aliases, setAliases] = useState([]);
  const [reason, setReason] = useState('');
  const [note, setNote] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    setAction('');
    setSkillCode('');
    setTechnologyCode('');
    setName(candidate.canonical_raw_name);
    setAliases([]);
    setReason('');
    setNote('');
    setError('');
  }, [candidate.id, candidate.canonical_raw_name]);

  const skills = useMemo(
    () => nodes.filter((node) => node.level === 'skill' && node.is_assignable),
    [nodes],
  );
  const technologies = useMemo(
    () => nodes.filter((node) => node.level === 'technology' && node.is_active !== false),
    [nodes],
  );
  const byCode = useMemo(() => Object.fromEntries(nodes.map((node) => [node.code, node])), [nodes]);
  const variants = useMemo(
    () => [...new Set([candidate.canonical_raw_name, ...(candidate.raw_variants || [])])],
    [candidate],
  );

  const valid =
    (action === 'match_existing' && skillCode) ||
    (action === 'create' && technologyCode && name.trim()) ||
    (action === 'generic' && reason) ||
    (action === 'reject' && reason);

  const submit = async () => {
    if (!valid || saving) return;
    setSaving(true);
    setError('');
    const payload = { action };
    if (action === 'match_existing') payload.skill_code = skillCode;
    if (action === 'create') {
      const technology = byCode[technologyCode];
      payload.technology_code = technologyCode;
      payload.category_code = technology?.parent_code || null;
      payload.name = name.trim();
      payload.aliases = aliases;
    }
    if (action === 'generic') payload.generic_tag = reason;
    if (action === 'reject') payload.rejection_reason = reason;
    if (note.trim()) payload.decision_note = note.trim();
    try {
      await decideSkillCandidate(candidate.id, payload);
      onResolved(candidate.id);
    } catch (nextError) {
      setError(nextError?.message || '无法保存 Skill 决定。');
    } finally {
      setSaving(false);
    }
  };

  useEffect(() => {
    const handleKeyDown = (event) => {
      if (event.key === 'Escape') onClose();
      if (event.key === 'Enter' && valid && !['INPUT', 'TEXTAREA', 'SELECT'].includes(event.target.tagName)) {
        event.preventDefault();
        submit();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  });

  const chooseMatch = (code) => {
    setAction('match_existing');
    setSkillCode(code);
  };

  return (
    <aside className="skill-review-panel" aria-label={`${candidate.canonical_raw_name} 处理面板`}>
      <header className="skill-review-panel-header">
        <div>
          <span className="skill-review-kicker">正在确认</span>
          <h2>{candidate.canonical_raw_name}</h2>
          <p>{candidate.distinct_job_count} 份 Job · {candidate.occurrence_count} 次出现</p>
        </div>
        <button type="button" className="skill-review-icon-button" onClick={onClose} aria-label="关闭处理面板"><X size={18} /></button>
      </header>

      <section className="skill-review-section">
        <div className="skill-review-section-title"><h3>代表性 evidence</h3><span>最多 {candidate.evidence?.length || 0} 条</span></div>
        <div className="skill-evidence-list">
          {(candidate.evidence || []).map((item) => (
            <div key={item.job_id} className="skill-evidence-row">
              <div className="skill-evidence-heading">
                <strong>{item.title || '未命名 Job'}</strong>
                <small>{item.source_site}</small>
              </div>
              {item.evidence_excerpt && <p>{item.evidence_excerpt}</p>}
              <div className="skill-evidence-jev">
                <span>{jevStatusLabel(item)}</span>
                {item.jev?.decision?.confidence != null && (
                  <small>置信 {Math.round(item.jev.decision.confidence * 100)}%</small>
                )}
                {item.jev?.model && <small>{item.jev.model}</small>}
                {item.jev?.request_id && <small>receipt {item.jev.request_id}</small>}
              </div>
            </div>
          ))}
          {!candidate.evidence?.length && <p className="skill-review-muted">暂无可展示的 Job evidence。</p>}
        </div>
        {variants.length > 0 && <p className="skill-review-variants">原始写法：{variants.join('、')}</p>}
      </section>

      <section className="skill-review-section">
        <div className="skill-review-section-title"><h3>推荐已有 Skill</h3><span>最多 {candidate.recommendations?.length || 0} 个</span></div>
        <div className="skill-recommendation-list">
          {(candidate.recommendations || []).map((item) => (
            <button type="button" key={item.code} className={`skill-recommendation ${skillCode === item.code ? 'selected' : ''}`} onClick={() => chooseMatch(item.code)}>
              <span><strong>{item.name}</strong><small>{[item.category, item.technology].filter(Boolean).join(' → ')}</small></span>
              <span className="skill-match-score">{Math.round(item.score * 100)}%</span>
            </button>
          ))}
          {!candidate.recommendations?.length && <p className="skill-review-muted">没有足够相似的已有 Skill。</p>}
        </div>
        <SearchableOptionList
          label="搜索全部已有 Skill"
          placeholder="输入名称或关键词…"
          options={skills}
          value={skillCode}
          onChange={chooseMatch}
          renderOption={(skill) => {
            const technology = byCode[skill.parent_code];
            const category = byCode[technology?.parent_code];
            return `${nodeLabel(category)} → ${nodeLabel(technology)} → ${nodeLabel(skill)}`;
          }}
        />
      </section>

      <section className="skill-review-section">
        <h3>其他处理方式</h3>
        <div className="skill-action-tabs" role="group" aria-label="处理方式">
          <button type="button" aria-pressed={action === 'create'} onClick={() => setAction('create')}>创建新 Skill</button>
          <button type="button" aria-pressed={action === 'generic'} onClick={() => { setAction('generic'); setReason(''); }}>通用词</button>
          <button type="button" aria-pressed={action === 'reject'} onClick={() => { setAction('reject'); setReason(''); }}>拒绝</button>
        </div>

        {action === 'create' && (
          <div className="skill-review-form-stack">
            <SearchableOptionList label="已有 Category → Technology" placeholder="搜索父级路径…" options={technologies} value={technologyCode} onChange={setTechnologyCode} renderOption={(technology) => `${nodeLabel(byCode[technology.parent_code])} → ${nodeLabel(technology)}`} />
            <label className="skill-review-field"><span>新 Skill 名称</span><input value={name} onChange={(event) => setName(event.target.value)} /></label>
            <fieldset className="skill-alias-fieldset"><legend>确认 Alias</legend>{variants.filter((variant) => variant !== name).map((variant) => <label key={variant}><input type="checkbox" checked={aliases.includes(variant)} onChange={(event) => setAliases((current) => event.target.checked ? [...current, variant] : current.filter((item) => item !== variant))} />{variant}</label>)}</fieldset>
          </div>
        )}

        {(action === 'generic' || action === 'reject') && (
          <div className="skill-review-form-stack">
            <label className="skill-review-field"><span>原因</span><select value={reason} onChange={(event) => setReason(event.target.value)}><option value="">请选择</option>{(action === 'generic' ? GENERIC_REASONS : REJECTION_REASONS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
            <label className="skill-review-field"><span>备注（可选）</span><textarea value={note} maxLength={500} onChange={(event) => setNote(event.target.value)} /></label>
          </div>
        )}
      </section>

      {error && <p className="skill-candidate-error" role="alert">{error}</p>}
      <footer className="skill-review-panel-footer">
        <button type="button" className="skill-review-secondary" onClick={onSkip}><SkipForward size={16} />跳过</button>
        <button type="button" className="skill-review-primary" onClick={submit} disabled={!valid || saving}><Check size={16} />{saving ? '保存中…' : '保存并下一个'}</button>
      </footer>
    </aside>
  );
}

export default function ClassificationBatchesPage() {
  const [payload, setPayload] = useState(null);
  const [nodes, setNodes] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [query, setQuery] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(0);
  const [maintenance, setMaintenance] = useState(null);
  const [maintenanceBusy, setMaintenanceBusy] = useState('');
  const [maintenanceFeedback, setMaintenanceFeedback] = useState('');
  const [backfillLimit, setBackfillLimit] = useState(50);
  const [backfillPlan, setBackfillPlan] = useState(null);
  const [backfillBusy, setBackfillBusy] = useState('');
  const [backfillFeedback, setBackfillFeedback] = useState('');
  const pageSize = 25;

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([fetchSkillCandidates({ limit: pageSize, offset: page * pageSize, signal: controller.signal }), fetchCurrentSkillTree({ signal: controller.signal }), fetchSkillMaintenanceStatus({ signal: controller.signal })])
      .then(([candidates, tree, maintenancePayload]) => {
        setPayload(candidates);
        setNodes(tree.nodes || []);
        setMaintenance(maintenancePayload);
        setSelectedId(candidates.items?.[0]?.id || null);
        setError('');
      })
      .catch((nextError) => { if (nextError?.name !== 'AbortError') setError(nextError?.message || '无法加载 Skill Candidate。'); })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [page]);

  const items = useMemo(() => payload?.items || [], [payload?.items]);
  const filtered = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    return needle ? items.filter((item) => item.canonical_raw_name.toLocaleLowerCase().includes(needle)) : items;
  }, [items, query]);
  const selected = items.find((item) => item.id === selectedId) || null;
  const totalPages = Math.max(1, Math.ceil(Number(payload?.total_count || items.length) / pageSize));

  const move = (offset) => {
    if (!filtered.length) return;
    const index = Math.max(0, filtered.findIndex((item) => item.id === selectedId));
    setSelectedId(filtered[(index + offset + filtered.length) % filtered.length].id);
  };

  useEffect(() => {
    const handleKeyDown = (event) => {
      if (['INPUT', 'TEXTAREA', 'SELECT'].includes(event.target.tagName)) return;
      if (event.key === 'ArrowDown') { event.preventDefault(); move(1); }
      if (event.key === 'ArrowUp') { event.preventDefault(); move(-1); }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  });

  const removeResolved = (candidateId) => {
    setPayload((current) => {
      const index = current.items.findIndex((item) => item.id === candidateId);
      const nextItems = current.items.filter((item) => item.id !== candidateId);
      setSelectedId(nextItems[Math.min(index, nextItems.length - 1)]?.id || null);
      return { ...current, items: nextItems };
    });
  };

  const runMaintenance = async () => {
    setMaintenanceBusy('run');
    setMaintenanceFeedback('');
    try {
      const result = await runSkillMaintenanceNow();
      if (result.batch) {
        setMaintenance((current) => ({ ...current, latest_batch: result.batch }));
        setMaintenanceFeedback(`Maintenance finished: ${result.batch.auto_applied_count} auto-applied, ${result.batch.held_for_approval_count} awaiting approval.`);
        const appliedIds = new Set((result.batch.applied_changes || []).map((item) => item.candidate_id));
        setPayload((current) => ({ ...current, items: current.items.filter((item) => !appliedIds.has(item.id)) }));
      } else {
        setMaintenanceFeedback(`No provider call: ${result.reason}.`);
      }
    } catch (nextError) {
      setMaintenanceFeedback(nextError?.message || 'Unable to run Skill maintenance.');
    } finally {
      setMaintenanceBusy('');
    }
  };

  const approveMaintenance = async (batchId) => {
    setMaintenanceBusy('approve');
    setMaintenanceFeedback('');
    try {
      const batch = await approveSkillMaintenance(batchId);
      setMaintenance((current) => ({ ...current, latest_batch: batch }));
      setMaintenanceFeedback(`Aggregate approval saved. ${batch.held_for_approval_count} proposals remain.`);
      const appliedIds = new Set((batch.applied_changes || []).map((item) => item.candidate_id));
      setPayload((current) => ({ ...current, items: current.items.filter((item) => !appliedIds.has(item.id)) }));
    } catch (nextError) {
      setMaintenanceFeedback(nextError?.message || 'Unable to approve maintenance batch.');
    } finally {
      setMaintenanceBusy('');
    }
  };

  const previewBackfill = async () => {
    setBackfillBusy('preview');
    setBackfillFeedback('');
    try {
      const limit = normalizedBackfillLimit(backfillLimit);
      setBackfillLimit(limit);
      const plan = await previewJevSkillBackfill(limit);
      setBackfillPlan(plan);
      setBackfillFeedback('Preview is a free database read; no Jev request was sent.');
    } catch (nextError) {
      setBackfillFeedback(nextError?.message || 'Unable to preview historical backfill.');
    } finally {
      setBackfillBusy('');
    }
  };

  const startBackfill = async () => {
    setBackfillBusy('start');
    setBackfillFeedback('');
    try {
      const limit = normalizedBackfillLimit(backfillLimit);
      setBackfillLimit(limit);
      const result = await startJevSkillBackfill(limit);
      if (result.status === 'empty') {
        setBackfillFeedback('No eligible historical Jobs remain.');
        setBackfillPlan((current) => current && ({ ...current, selected_item_count: 0 }));
      } else {
        setBackfillFeedback(`Queued ${result.total_items} Jobs in run ${result.id}. Monitor it in AI Enrichment.`);
        setBackfillPlan((current) => current && ({ ...current, selected_item_count: 0 }));
      }
    } catch (nextError) {
      setBackfillFeedback(nextError?.message || 'Unable to start historical backfill.');
    } finally {
      setBackfillBusy('');
    }
  };

  return (
    <section className="classification-page">
      <header className="classification-header">
        <div><p className="eyebrow">JOB INTELLIGENCE</p><h1>待确认 Skill</h1><p>只显示出现在至少 {payload?.threshold ?? 10} 份 Job、仍需要人工判断的新词。每页 {pageSize} 条。</p></div>
        <div className="skill-review-progress"><strong>{items.length}</strong><span>待确认</span></div>
      </header>

      <MaintenancePanel
        payload={maintenance}
        busy={maintenanceBusy}
        feedback={maintenanceFeedback}
        onRun={runMaintenance}
        onApprove={approveMaintenance}
      />

      <BackfillPanel
        limit={backfillLimit}
        plan={backfillPlan}
        busy={backfillBusy}
        feedback={backfillFeedback}
        onLimit={setBackfillLimit}
        onPreview={previewBackfill}
        onStart={startBackfill}
      />

      {loading && <p>加载中…</p>}
      {error && <p role="alert" className="skill-candidate-error">{error}</p>}
      {!loading && !error && nodes.length === 0 && <p role="alert" className="skill-candidate-error">Skill taxonomy 尚未就绪，暂时无法确认 Candidate。</p>}
      {!loading && !error && nodes.length > 0 && items.length === 0 && <p className="classification-empty">目前没有需要确认的 Skill。</p>}

      {!loading && !error && items.length > 0 && (
        <div className="skill-review-workspace">
          <section className="skill-review-sidebar">
            <div className="skill-review-search"><Search size={17} /><input aria-label="搜索 Candidate" placeholder="搜索 Candidate" value={query} onChange={(event) => setQuery(event.target.value)} /></div>
            <div className="skill-review-nav"><span>{filtered.length} / {payload?.total_count ?? items.length} 项</span><div><button type="button" onClick={() => move(-1)} aria-label="上一个 Candidate"><ArrowUp size={15} /></button><button type="button" onClick={() => move(1)} aria-label="下一个 Candidate"><ArrowDown size={15} /></button></div></div>
            <CandidateList candidates={filtered} selectedId={selectedId} onSelect={setSelectedId} />
          </section>
          {selected ? <ReviewPanel candidate={selected} nodes={nodes} onResolved={removeResolved} onSkip={() => move(1)} onClose={() => setSelectedId(null)} /> : <div className="skill-review-placeholder"><p>选择一个 Candidate 开始确认。</p></div>}
        </div>
      )}
      {!loading && !error && totalPages > 1 && <nav className="skill-review-pagination" aria-label="Candidate 分页"><button type="button" disabled={page === 0} onClick={() => setPage((current) => current - 1)}>上一页</button><span>第 {page + 1} / {totalPages} 页</span><button type="button" disabled={page + 1 >= totalPages} onClick={() => setPage((current) => current + 1)}>下一页</button></nav>}
    </section>
  );
}
