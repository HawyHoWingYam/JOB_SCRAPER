import React, { useEffect, useRef, useState } from 'react';
import { Save, X } from 'lucide-react';
import { getCrawlModeOptionsForSource, resolveDefaultCrawlMode } from './crawlMode';
import { CRAWL_PHASE_OPTIONS, resolveDefaultCrawlPhase } from './crawlPhase';
import { resolveDefaultMaxPages } from './maxPages';

const EMPTY_SOURCE_CATALOG = {};

// Cron presets
const CRON_PRESETS = [
    { label: 'Daily at 02:00', value: '0 2 * * *' },
    { label: 'Every 6 hours', value: '0 */6 * * *' },
    { label: 'Every 12 hours', value: '0 */12 * * *' },
    { label: 'Mondays at 09:00', value: '0 9 * * 1' },
    { label: 'Custom', value: 'custom' },
];

function formatSourceLabel(sourceSite) {
    if (sourceSite === 'offertoday') return 'OfferToday';
    return sourceSite === 'ctgoodjobs' ? 'CTgoodjobs' : 'JobsDB';
}

function resolveSourceLabel(sourceSite, sourceCatalog = EMPTY_SOURCE_CATALOG) {
    return sourceCatalog[sourceSite]?.label || formatSourceLabel(sourceSite);
}

function ScheduleForm({
    onSubmit,
    onCancel,
    categories,
    isLoading,
    sourceSite,
    sourceCatalog = EMPTY_SOURCE_CATALOG,
    onSourceScopedDirtyChange,
}) {
    const [formData, setFormData] = useState({
        name: '',
        cronPreset: '0 2 * * *',
        customCron: '',
        crawlPhase: resolveDefaultCrawlPhase(),
        crawlMode: '',
        categoryIds: [],
        maxPages: resolveDefaultMaxPages(sourceSite, sourceCatalog),
        detailLimit: 100,
    });
    const previousSourceSiteRef = useRef(sourceSite);
    const dirtyFieldsRef = useRef({
        crawlMode: false,
        maxPages: false,
    });

    useEffect(() => {
        onSourceScopedDirtyChange?.(formData.categoryIds.length > 0);
    }, [formData.categoryIds, onSourceScopedDirtyChange]);

    useEffect(() => {
        const crawlModeOptions = getCrawlModeOptionsForSource(sourceSite, sourceCatalog);
        const nextDefaultCrawlMode = resolveDefaultCrawlMode(sourceSite, sourceCatalog);
        const nextDefaultMaxPages = resolveDefaultMaxPages(sourceSite, sourceCatalog);

        setFormData(prev => {
            const previousSourceSite = previousSourceSiteRef.current;
            const currentMaxPages = Number.parseInt(`${prev.maxPages ?? ''}`, 10);
            const isCurrentCrawlModeValid = crawlModeOptions.some((option) => option.value === prev.crawlMode);
            const isCurrentMaxPagesValid = Number.isInteger(currentMaxPages) && currentMaxPages > 0;
            const shouldAdoptSourceDefaultCrawlMode =
                !prev.crawlMode
                || !dirtyFieldsRef.current.crawlMode
                || !isCurrentCrawlModeValid;
            const shouldAdoptSourceDefaultMaxPages =
                !dirtyFieldsRef.current.maxPages
                || !isCurrentMaxPagesValid;

            if (shouldAdoptSourceDefaultCrawlMode) {
                dirtyFieldsRef.current.crawlMode = false;
            }

            if (shouldAdoptSourceDefaultMaxPages) {
                dirtyFieldsRef.current.maxPages = false;
            }

            return {
                ...prev,
                crawlMode: shouldAdoptSourceDefaultCrawlMode ? nextDefaultCrawlMode : prev.crawlMode,
                categoryIds: previousSourceSite === sourceSite ? prev.categoryIds : [],
                maxPages: shouldAdoptSourceDefaultMaxPages ? nextDefaultMaxPages : prev.maxPages,
            };
        });
        previousSourceSiteRef.current = sourceSite;
    }, [sourceCatalog, sourceSite]);

    const handleChange = (e) => {
        const { name, value } = e.target;
        if (name === 'crawlMode') {
            dirtyFieldsRef.current.crawlMode = true;
        }
        if (name === 'maxPages') {
            dirtyFieldsRef.current.maxPages = true;
        }
        setFormData(prev => ({ ...prev, [name]: value }));
    };

    const handleCategoryChange = (categoryId) => {
        setFormData(prev => ({
            ...prev,
            categoryIds: prev.categoryIds.includes(categoryId)
                ? prev.categoryIds.filter(id => id !== categoryId)
                : [...prev.categoryIds, categoryId]
        }));
    };

    const handleSubmit = (e) => {
        e.preventDefault();
        const cronExpression = formData.cronPreset === 'custom'
            ? formData.customCron
            : formData.cronPreset;
        const maxPages = Number.parseInt(`${formData.maxPages}`, 10);
        const detailLimit = Number.parseInt(`${formData.detailLimit}`, 10);

        onSubmit({
            name: formData.name,
            cron_expression: cronExpression,
            crawl_phase: formData.crawlPhase,
            crawl_mode: formData.crawlMode || resolveDefaultCrawlMode(sourceSite, sourceCatalog),
            category_ids: formData.categoryIds,
            max_pages: Number.isInteger(maxPages) ? maxPages : resolveDefaultMaxPages(sourceSite, sourceCatalog),
            detail_limit: Number.isInteger(detailLimit) ? detailLimit : 100,
        });
    };

    const sourceLabel = resolveSourceLabel(sourceSite, sourceCatalog);
    const isDetailPhase = formData.crawlPhase === 'detail';
    const recurringGuidance = `Use automations for recurring crawls on ${sourceLabel}.`;
    const phaseGuidance = isDetailPhase
        ? 'Detail crawl consumes staged listings into full records.'
        : 'Job ID crawl stages listing URLs first.';
    const volumeGuidance = isDetailPhase
        ? 'How many staged listings this automation should expand per run.'
        : 'Pages per run for each selected sector.';
    const crawlModeOptions = getCrawlModeOptionsForSource(sourceSite, sourceCatalog);

    return (
        <form onSubmit={handleSubmit} className="schedule-form">
            <h3>Configure New Automation</h3>
            <p className="form-hint">
                Creating automation for {sourceLabel}.
            </p>

            <div className="override-summary-panel schedule-form-guidance schedule-form-wide">
                <span className="scheduler-panel-kicker">Recurring Crawl Guidance</span>
                <strong className="override-summary-title">{recurringGuidance}</strong>
                <p className="form-hint">{phaseGuidance}</p>
                <p className="form-hint">{volumeGuidance}</p>
            </div>

            <div className="cyber-form-group">
                <label>Task Designation</label>
                <input
                    type="text"
                    name="name"
                    className="premium-input"
                    value={formData.name}
                    onChange={handleChange}
                    placeholder="e.g. Daily Tech Sector Scan"
                    required
                    disabled={isLoading}
                />
            </div>

            <div className="cyber-form-group">
                <label>Execution Frequency</label>
                <select
                    name="cronPreset"
                    className="premium-select"
                    value={formData.cronPreset}
                    onChange={handleChange}
                    disabled={isLoading}
                >
                    {CRON_PRESETS.map(preset => (
                        <option key={preset.value} value={preset.value}>
                            {preset.label}
                        </option>
                    ))}
                </select>
            </div>

            {formData.cronPreset === 'custom' && (
                <div className="cyber-form-group">
                    <label>Custom Cron Expression</label>
                    <input
                        type="text"
                        name="customCron"
                        className="premium-input"
                        value={formData.customCron}
                        onChange={handleChange}
                        placeholder="e.g. 0 */4 * * *"
                        required
                        disabled={isLoading}
                    />
                </div>
            )}

            <div className="cyber-form-group">
                <label htmlFor="schedule-crawl-phase">Crawl Phase</label>
                <select
                    id="schedule-crawl-phase"
                    name="crawlPhase"
                    className="premium-select"
                    value={formData.crawlPhase}
                    onChange={handleChange}
                    disabled={isLoading}
                    aria-label="Crawl Phase"
                >
                    {CRAWL_PHASE_OPTIONS.map((option) => (
                        <option key={option.value} value={option.value}>
                            {option.label}
                        </option>
                    ))}
                </select>
            </div>

            <div className="cyber-form-group">
                <label htmlFor="schedule-crawl-mode">Crawl Mode</label>
                <select
                    id="schedule-crawl-mode"
                    name="crawlMode"
                    className="premium-select"
                    value={formData.crawlMode}
                    onChange={handleChange}
                    disabled={isLoading}
                    aria-label="Crawl Mode"
                >
                    {crawlModeOptions.map((option) => (
                        <option key={option.value} value={option.value}>
                            {option.label}
                        </option>
                    ))}
                </select>
            </div>

            <div className="cyber-form-group">
                <label>{formData.crawlPhase === 'detail' ? 'Detail Batch Size' : 'Max Depth (Pages per Sector)'}</label>
                <input
                    type="number"
                    name={formData.crawlPhase === 'detail' ? 'detailLimit' : 'maxPages'}
                    className="premium-input w-24"
                    value={formData.crawlPhase === 'detail' ? formData.detailLimit : formData.maxPages}
                    onChange={handleChange}
                    min="1"
                    max={formData.crawlPhase === 'detail' ? '5000' : '9999'}
                    disabled={isLoading}
                />
            </div>

            {categories.length > 0 && (
                <div className="cyber-form-group schedule-form-wide">
                    <label>Target Sectors</label>
                    <div className="category-checkbox-grid">
                        {categories.map(cat => (
                            <label key={cat.id} className="cyber-checkbox-label">
                                <input
                                    type="checkbox"
                                    checked={formData.categoryIds.includes(cat.id)}
                                    onChange={() => handleCategoryChange(cat.id)}
                                    disabled={isLoading}
                                />
                                <span className="checkbox-text">{cat.name}</span>
                            </label>
                        ))}
                    </div>
                </div>
            )}

            <div className="form-actions mt-6">
                <button type="submit" disabled={isLoading} className="cyber-btn primary-glow">
                    <Save size={16} /> {isLoading ? 'Building...' : 'Create Automation'}
                </button>
                <button type="button" onClick={onCancel} disabled={isLoading} className="cyber-btn">
                    <X size={16} /> Cancel
                </button>
            </div>
        </form>
    );
}

export default ScheduleForm;
