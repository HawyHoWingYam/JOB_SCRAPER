import React, { useEffect, useMemo, useState } from 'react';
import {
  confirmOfferTodayKeywordPacksCsv,
  downloadOfferTodayKeywordPacksCsv,
  fetchOfferTodayKeywordPacks,
  previewOfferTodayKeywordPacksCsv,
} from '../../api/offertodayKeywordPacks';
import './OfferTodayKeywordPacksPage.css';

function saveBlob(blob) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = 'offertoday-keyword-packs.csv';
  link.click();
  URL.revokeObjectURL(url);
}

export default function OfferTodayKeywordPacksPage() {
  const [catalog, setCatalog] = useState(null);
  const [filter, setFilter] = useState('');
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const loadCatalog = async () => {
    setError('');
    try {
      setCatalog(await fetchOfferTodayKeywordPacks());
    } catch (requestError) {
      setError(requestError?.message || '关键词目录加载失败');
    }
  };

  useEffect(() => { loadCatalog(); }, []);

  const rows = useMemo(() => {
    const needle = filter.trim().toLocaleLowerCase();
    return (catalog?.items || []).filter((item) => !needle || [
      item.classification_label,
      item.classification_id,
      item.keyword,
      item.notes,
    ].some((value) => String(value || '').toLocaleLowerCase().includes(needle)));
  }, [catalog, filter]);

  const handleFile = async (event) => {
    const file = event.target.files?.[0];
    setPreview(null);
    setError('');
    if (!file) return;
    setBusy(true);
    try {
      setPreview(await previewOfferTodayKeywordPacksCsv(await file.text()));
    } catch (requestError) {
      setError(requestError?.message || 'CSV 预览失败');
    } finally {
      setBusy(false);
      event.target.value = '';
    }
  };

  const confirm = async () => {
    setBusy(true);
    setError('');
    try {
      await confirmOfferTodayKeywordPacksCsv(preview);
      setPreview(null);
      await loadCatalog();
    } catch (requestError) {
      setError(requestError?.message || 'CSV 应用失败，请重新预览');
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="keyword-pack-page">
      <header>
        <h1>OfferToday Keyword Packs</h1>
        <p>统一维护所有大分类的补充关键词。这里只读展示，修改必须经过 CSV 预览和确认。</p>
      </header>
      <div className="keyword-pack-toolbar glass-panel">
        <button type="button" onClick={async () => saveBlob(await downloadOfferTodayKeywordPacksCsv())}>下载 CSV</button>
        <label className="primary-button">
          {busy ? '处理中…' : '上传 CSV 预览'}
          <input type="file" accept=".csv,text/csv" disabled={busy} onChange={handleFile} />
        </label>
        <input aria-label="筛选关键词" placeholder="筛选分类、关键词或备注" value={filter} onChange={(event) => setFilter(event.target.value)} />
      </div>
      {error ? <p className="keyword-pack-error" role="alert">{error}</p> : null}
      {preview ? (
        <section className="keyword-pack-preview glass-panel" aria-label="CSV 预览">
          <h2>CSV 预览</h2>
          <p>{preview.valid ? `共 ${preview.diff.length} 项变更，确认后一次性应用。` : 'CSV 有错误，目录尚未改变。'}</p>
          {(preview.errors || []).map((item, index) => <p className="keyword-pack-error" key={`${item.code}-${index}`}>第 {item.row || '?'} 行：{item.message || item.code}</p>)}
          {(preview.warnings || []).map((item, index) => <p key={`${item.code}-${index}`}>{item.message || item.code}</p>)}
          <pre>{JSON.stringify(preview.resulting_enabled_counts, null, 2)}</pre>
          <button type="button" className="primary-button" disabled={!preview.valid || !preview.confirmation_token || busy} onClick={confirm}>确认应用</button>
        </section>
      ) : null}
      <section className="keyword-pack-table-wrap glass-panel">
        <p>目录更新时间：{catalog?.catalog_updated_at ? new Date(catalog.catalog_updated_at).toLocaleString() : '尚无'}</p>
        <table>
          <thead><tr><th>大分类</th><th>Keyword</th><th>启用</th><th>备注</th><th>新增 ID</th><th>重复率</th><th>最近运行</th></tr></thead>
          <tbody>
            {rows.map((item) => (
              <tr key={item.id}>
                <td>{item.classification_label}<small>{item.classification_id}</small></td>
                <td>{item.keyword}</td><td>{item.enabled ? '是' : '否'}</td><td>{item.notes || '—'}</td>
                <td>{item.last_new_job_ids ?? '—'}</td><td>{item.last_duplicate_rate == null ? '—' : `${(item.last_duplicate_rate * 100).toFixed(1)}%`}</td>
                <td>{item.last_run_at ? new Date(item.last_run_at).toLocaleString() : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {!rows.length ? <p>没有匹配的关键词。</p> : null}
      </section>
    </section>
  );
}
