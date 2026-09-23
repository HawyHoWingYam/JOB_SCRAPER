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
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState('');

  const loadCatalog = async () => {
    setLoading(true);
    setError('');
    try {
      setCatalog(await fetchOfferTodayKeywordPacks());
    } catch (requestError) {
      setError(requestError?.message || 'Could not load keyword packs.');
    } finally {
      setLoading(false);
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
    setNotice('');
    setError('');
    if (!file) return;
    setBusy(true);
    try {
      setPreview(await previewOfferTodayKeywordPacksCsv(await file.text()));
    } catch (requestError) {
      setError(requestError?.message || 'Could not preview the CSV.');
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
      setNotice('Keyword changes applied successfully.');
      setPreview(null);
      await loadCatalog();
    } catch (requestError) {
      setError(requestError?.message || 'Could not apply the CSV. Preview it again before retrying.');
    } finally {
      setBusy(false);
    }
  };

  const downloadCsv = async () => {
    setError('');
    try {
      saveBlob(await downloadOfferTodayKeywordPacksCsv());
    } catch (requestError) {
      setError(requestError?.message || 'Could not download the CSV. Please retry.');
    }
  };

  return (
    <section className="keyword-pack-page">
      <header>
        <h1>OfferToday Keyword Packs</h1>
        <p>Browse supplemental keywords by source classification. To make changes, download the CSV, edit it, then upload and review before applying.</p>
      </header>
      <div className="keyword-pack-toolbar glass-panel">
        <button type="button" onClick={downloadCsv}>Download CSV</button>
        <label className="primary-button">
          {busy ? 'Working…' : 'Upload CSV to preview'}
          <input type="file" accept=".csv,text/csv" disabled={busy} onChange={handleFile} />
        </label>
        <input aria-label="Filter keywords" placeholder="Filter classifications, keywords, or notes" value={filter} onChange={(event) => setFilter(event.target.value)} />
      </div>
      {error ? <p className="keyword-pack-error" role="alert">{error}</p> : null}
      {notice && <p role="status">{notice}</p>}
      {loading && <p role="status">Loading keyword packs…</p>}
      {!loading && error && !catalog && <button type="button" onClick={loadCatalog}>Retry loading</button>}
      {preview ? (
        <section className="keyword-pack-preview glass-panel" aria-label="CSV preview">
          <h2>CSV preview</h2>
          <p>{preview.valid ? `${preview.diff.length} changes will be applied together after confirmation.` : 'The CSV contains errors. No changes have been applied.'}</p>
          {(preview.errors || []).map((item, index) => <p className="keyword-pack-error" key={`${item.code}-${index}`}>Row {item.row || '?'}: {item.message || item.code}</p>)}
          {(preview.warnings || []).map((item, index) => <p key={`${item.code}-${index}`}>{item.message || item.code}</p>)}
          <pre>{JSON.stringify(preview.resulting_enabled_counts, null, 2)}</pre>
          <button type="button" className="primary-button" disabled={!preview.valid || !preview.confirmation_token || busy} onClick={confirm}>Confirm and apply</button>
        </section>
      ) : null}
      <section className="keyword-pack-table-wrap glass-panel">
        <p>Last updated: {catalog?.catalog_updated_at ? new Date(catalog.catalog_updated_at).toLocaleString() : 'Not available'}</p>
        <table>
          <thead><tr><th>Classification</th><th>Keyword</th><th>Enabled</th><th>Notes</th><th>New job IDs</th><th>Duplicate rate</th><th>Last run</th></tr></thead>
          <tbody>
            {rows.map((item) => (
              <tr key={item.id}>
                <td>{item.classification_label}<small>{item.classification_id}</small></td>
                <td>{item.keyword}</td><td>{item.enabled ? 'Yes' : 'No'}</td><td>{item.notes || '—'}</td>
                <td>{item.last_new_job_ids ?? '—'}</td><td>{item.last_duplicate_rate == null ? '—' : `${(item.last_duplicate_rate * 100).toFixed(1)}%`}</td>
                <td>{item.last_run_at ? new Date(item.last_run_at).toLocaleString() : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {!loading && !error && !rows.length ? <p>No matching keywords. Try a different filter.</p> : null}
      </section>
    </section>
  );
}
