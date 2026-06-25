import React, { useEffect, useState } from 'react';
import { Save, X } from 'lucide-react';
import { getCrawlModeOptionsForSource, resolveDefaultCrawlMode } from './crawlMode';
import { CRAWL_PHASE_OPTIONS, resolveDefaultCrawlPhase } from './crawlPhase';

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

function ScheduleForm({
    onSubmit,
    onCancel,
    categories,
    isLoading,
    sourceSite,
    onSourceScopedDirtyChange,
}) {
    const [formData, setFormData] = useState({
        name: '',
        cronPreset: '0 2 * * *',
        customCron: '',
        crawlPhase: resolveDefaultCrawlPhase(),
        crawlMode: resolveDefaultCrawlMode(sourceSite),
        categoryIds: [],
        maxPages: 3,
        detailLimit: 100,
    });

    useEffect(() => {
        onSourceScopedDirtyChange?.(formData.categoryIds.length > 0);
    }, [formData.categoryIds, onSourceScopedDirtyChange]);

    useEffect(() => {
        setFormData(prev => ({
            ...prev,
            crawlMode: resolveDefaultCrawlMode(sourceSite),
            categoryIds: [],
        }));
    }, [sourceSite]);

    const handleChange = (e) => {
        const { name, value } = e.target;
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

        onSubmit({
            name: formData.name,
            cron_expression: cronExpression,
            crawl_phase: formData.crawlPhase,
            crawl_mode: formData.crawlMode,
            category_ids: formData.categoryIds,
            max_pages: parseInt(formData.maxPages),
            detail_limit: parseInt(formData.detailLimit),
        });
    };

    const sourceLabel = formatSourceLabel(sourceSite);
    const isDetailPhase = formData.crawlPhase === 'detail';
    const recurringGuidance = `Use automations for recurring crawls on ${sourceLabel}.`;
    const phaseGuidance = isDetailPhase
        ? 'Detail crawl consumes staged listings into full records.'
        : 'Job ID crawl stages listing URLs first.';
    const volumeGuidance = isDetailPhase
        ? 'How many staged listings this automation should expand per run.'
        : 'Pages per run for each selected sector.';
    const crawlModeOptions = getCrawlModeOptionsForSource(sourceSite);

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
                    max={formData.crawlPhase === 'detail' ? '5000' : '1000'}
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
