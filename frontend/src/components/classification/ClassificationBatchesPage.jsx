import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  fetchClassificationRuns,
  previewClassificationBatch,
  retryClassificationRun,
  startClassificationBatch,
  stopClassificationRun,
} from '../../api/classificationBatches';
import {
  hashForClassificationRoute,
  parseClassificationRoute,
} from '../../appRoute';
import './ClassificationBatchesPage.css';

const DOMAINS = [
  {
    id: 'job_taxonomy',
    label: 'Job Taxonomy',
    description: '给还没有大分类的 Job 自动分类。',
  },
  {
    id: 'company_industry',
    label: 'Company Industry',
    description: '根据已有来源证据，为 Company 补上行业分类。',
  },
  {
    id: 'skill',
    label: 'Skills',
    description: '处理达到 Settings 次数门槛的新 Skill。',
  },
];

const ACTIVE_STATUSES = new Set(['pending', 'running', 'stopping']);
const SOURCE_OPTIONS = ['jobsdb', 'offertoday', 'ctgoodjobs'];

function buildPreviewInputs(domain, limit, sourceSites) {
  const normalizedSources = SOURCE_OPTIONS.filter((source) => sourceSites.includes(source));
  return {
    domain,
    payload: {
      limit: Number(limit),
      filters: domain === 'skill' ? {} : { source_sites: normalizedSources },
    },
  };
}

function settledCount(run) {
  return (
    Number(run?.completed_items || 0) +
    Number(run?.failed_items || 0) +
    Number(run?.cancelled_items || 0)
  );
}

function previewSummary(preview) {
  if (!preview) return '还没有预览。';
  const { inputs, result } = preview;
  if (inputs.domain !== 'company_industry') {
    return `这次会处理 ${result.selected_item_count} 项。`;
  }
  const selected = Number(result.selected_item_count || 0);
  const mapped = Number(result.mapped_item_count || 0);
  const unmapped = Number(result.unmapped_item_count || 0);
  const excluded = Number(result.excluded_item_count || 0);
  const counts = `已选 ${selected} 家 Company：可映射 ${mapped}，未映射 ${unmapped}，规则排除 ${excluded}。`;
  return mapped > 0
    ? counts
    : `${counts} 没有可用的 Company Industry Source Mapping；请先同步已审核的 manifest。`;
}

function RunCard({ run, busyAction, onStop, onRetry }) {
  if (!run) {
    return <div className="classification-empty">还没有运行记录。</div>;
  }
  const total = Number(run.total_items || 0);
  const settled = settledCount(run);
  const percent = total ? Math.min(100, Math.round((settled / total) * 100)) : 100;
  return (
    <article className="classification-run-card">
      <div className="classification-run-heading">
        <div>
          <strong>{run.status}</strong>
          <code>{run.id}</code>
        </div>
        <span>{settled} / {total}</span>
      </div>
      <div
        className="classification-progress"
        role="progressbar"
        aria-label="Classification batch progress"
        aria-valuemin="0"
        aria-valuemax="100"
        aria-valuenow={percent}
      >
        <span style={{ width: `${percent}%` }} />
      </div>
      <div className="classification-counts">
        <span>成功 {run.completed_items || 0}</span>
        <span>失败 {run.failed_items || 0}</span>
        <span>停止 {run.cancelled_items || 0}</span>
      </div>
      {(run.items || []).some((item) => item.status === 'failed') ? (
        <details>
          <summary>查看失败原因</summary>
          <ul>
            {run.items
              .filter((item) => item.status === 'failed')
              .map((item) => (
                <li key={item.id}>
                  <strong>{item.subject_label || item.subject_id}</strong>: {' '}
                  {item.error_message || item.error_code || '处理失败'}
                </li>
              ))}
          </ul>
        </details>
      ) : null}
      <div className="classification-actions">
        {ACTIVE_STATUSES.has(run.status) ? (
          <button
            type="button"
            className="secondary-button"
            disabled={busyAction}
            onClick={() => onStop(run)}
          >
            {run.status === 'stopping' ? '正在停止…' : '停止'}
          </button>
        ) : null}
        {Number(run.failed_items || 0) > 0 ? (
          <button
            type="button"
            className="primary-button"
            disabled={busyAction}
            onClick={() => onRetry(run)}
          >
            只重试失败项 ({run.failed_items})
          </button>
        ) : null}
      </div>
    </article>
  );
}

export default function ClassificationBatchesPage({
  routeHash = typeof window === 'undefined' ? '#classification' : window.location.hash,
  onNavigateTarget,
}) {
  const routeTarget = parseClassificationRoute(routeHash).target;
  const [domain, setDomain] = useState(routeTarget);
  const [limit, setLimit] = useState('100');
  const [sourceSites, setSourceSites] = useState([]);
  const [preview, setPreview] = useState(null);
  const [runs, setRuns] = useState([]);
  const [loading, setLoading] = useState(false);
  const [busyAction, setBusyAction] = useState(false);
  const [error, setError] = useState('');
  const previewRequestGeneration = useRef(0);
  const previewAbortController = useRef(null);
  const domainInfo = useMemo(
    () => DOMAINS.find((item) => item.id === domain),
    [domain],
  );
  const currentPreviewInputs = useMemo(
    () => buildPreviewInputs(domain, limit, sourceSites),
    [domain, limit, sourceSites],
  );

  const refreshRuns = useCallback(async () => {
    const response = await fetchClassificationRuns(domain);
    setRuns(Array.isArray(response?.items) ? response.items : []);
  }, [domain]);

  const invalidatePreview = useCallback(() => {
    previewRequestGeneration.current += 1;
    previewAbortController.current?.abort();
    previewAbortController.current = null;
    setPreview(null);
    setLoading(false);
  }, []);

  useEffect(() => () => {
    previewRequestGeneration.current += 1;
    previewAbortController.current?.abort();
  }, []);

  useEffect(() => {
    setDomain((current) => (current === routeTarget ? current : routeTarget));
  }, [routeTarget]);

  useEffect(() => {
    invalidatePreview();
    setError('');
    refreshRuns().catch((requestError) => setError(requestError.message));
  }, [invalidatePreview, refreshRuns]);

  useEffect(() => {
    if (!runs.some((run) => ACTIVE_STATUSES.has(run.status))) return undefined;
    const timer = window.setInterval(() => {
      refreshRuns().catch(() => {});
    }, 2000);
    return () => window.clearInterval(timer);
  }, [refreshRuns, runs]);

  const handlePreview = async () => {
    const requestGeneration = previewRequestGeneration.current + 1;
    previewRequestGeneration.current = requestGeneration;
    const requestInputs = currentPreviewInputs;
    previewAbortController.current?.abort();
    const controller = new AbortController();
    previewAbortController.current = controller;
    setLoading(true);
    setError('');
    try {
      const response = await previewClassificationBatch(
        requestInputs.domain,
        requestInputs.payload,
        { signal: controller.signal },
      );
      if (previewRequestGeneration.current === requestGeneration) {
        setPreview({ inputs: requestInputs, result: response });
      }
    } catch (requestError) {
      if (previewRequestGeneration.current === requestGeneration) {
        setPreview(null);
        setError(requestError.message);
      }
    } finally {
      if (previewRequestGeneration.current === requestGeneration) {
        previewAbortController.current = null;
        setLoading(false);
      }
    }
  };

  const handleStart = async () => {
    setBusyAction(true);
    setError('');
    try {
      await startClassificationBatch(preview.inputs.domain, preview.inputs.payload);
      setPreview(null);
      await refreshRuns();
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusyAction(false);
    }
  };

  const handleStop = async (run) => {
    setBusyAction(true);
    try {
      await stopClassificationRun(run.id);
      await refreshRuns();
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusyAction(false);
    }
  };

  const handleRetry = async (run) => {
    setBusyAction(true);
    try {
      await retryClassificationRun(run.id);
      await refreshRuns();
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusyAction(false);
    }
  };

  const canStart = Boolean(preview) && (
    preview.inputs.domain === 'company_industry'
      ? Number(preview.result.mapped_item_count || 0) > 0
      : Number(preview.result.selected_item_count || 0) > 0
  );

  const handleDomainChange = (nextDomain) => {
    if (domain === nextDomain) return;
    invalidatePreview();
    setDomain(nextDomain);
    if (nextDomain === 'company_industry') return;
    if (onNavigateTarget) {
      onNavigateTarget(nextDomain);
    } else if (typeof window !== 'undefined') {
      window.location.hash = hashForClassificationRoute(nextDomain);
    }
  };

  return (
    <section className="classification-page">
      <header>
        <p className="eyebrow">JOB INTELLIGENCE</p>
        <h1>自动分类</h1>
        <p>先预览数量，再开始处理。失败项可以单独重试。</p>
      </header>

      <div className="classification-tabs" role="tablist" aria-label="Classification type">
        {DOMAINS.map((item) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            aria-selected={domain === item.id}
            className={domain === item.id ? 'active' : ''}
            onClick={() => handleDomainChange(item.id)}
          >
            {item.label}
          </button>
        ))}
      </div>

      <div className="classification-grid">
        <section className="classification-panel glass-panel">
          <h2>{domainInfo.label}</h2>
          <p>{domainInfo.description}</p>
          {domain !== 'skill' ? (
            <fieldset>
              <legend>来源（不选就是全部）</legend>
              {SOURCE_OPTIONS.map((source) => (
                <label key={source}>
                  <input
                    type="checkbox"
                    checked={sourceSites.includes(source)}
                    onChange={(event) => {
                      invalidatePreview();
                      setSourceSites((current) => (
                        event.target.checked
                          ? [...current, source]
                          : current.filter((item) => item !== source)
                      ));
                    }}
                  />
                  {source}
                </label>
              ))}
            </fieldset>
          ) : null}
          <label className="classification-limit">
            <span>这次最多处理</span>
            <input
              aria-label="Classification batch limit"
              type="number"
              min="1"
              max="5000"
              value={limit}
              onChange={(event) => {
                invalidatePreview();
                setLimit(event.target.value);
              }}
            />
          </label>
          <button type="button" className="secondary-button" onClick={handlePreview} disabled={loading}>
            {loading ? '正在预览…' : '预览'}
          </button>
          <div className="classification-preview" aria-live="polite">
            {previewSummary(preview)}
          </div>
          <button
            type="button"
            className="primary-button"
            onClick={handleStart}
            disabled={busyAction || !canStart}
          >
            开始处理
          </button>
          {error ? <p className="classification-error" role="alert">{error}</p> : null}
        </section>

        <section className="classification-panel glass-panel" aria-label="Classification run monitor">
          <h2>运行进度</h2>
          <RunCard
            run={runs[0]}
            busyAction={busyAction}
            onStop={handleStop}
            onRetry={handleRetry}
          />
        </section>
      </div>
    </section>
  );
}
