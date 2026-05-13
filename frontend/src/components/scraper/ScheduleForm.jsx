import React, { useEffect, useState } from 'react';
import { Save, X } from 'lucide-react';
import { CRAWL_MODE_OPTIONS, resolveDefaultCrawlMode } from './crawlMode';

// Cron presets
const CRON_PRESETS = [
    { label: '每天凌晨 2 点', value: '0 2 * * *' },
    { label: '每 6 小时', value: '0 */6 * * *' },
    { label: '每 12 小时', value: '0 */12 * * *' },
    { label: '每周一早上 9 点', value: '0 9 * * 1' },
    { label: '自定义 (Custom)', value: 'custom' },
];

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
        crawlMode: resolveDefaultCrawlMode(sourceSite),
        categoryIds: [],
        maxPages: 3,
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
            crawl_mode: formData.crawlMode,
            category_ids: formData.categoryIds,
            max_pages: parseInt(formData.maxPages),
        });
    };

    return (
        <form onSubmit={handleSubmit} className="schedule-form">
            <h3>Configure New Automation</h3>
            <p className="form-hint">
                Creating automation for {sourceSite === 'ctgoodjobs' ? 'CTgoodjobs' : 'JobsDB'}.
            </p>

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
                    {CRAWL_MODE_OPTIONS.map((option) => (
                        <option key={option.value} value={option.value}>
                            {option.label}
                        </option>
                    ))}
                </select>
            </div>

            <div className="cyber-form-group">
                <label>Max Depth (Pages per Sector)</label>
                <input
                    type="number"
                    name="maxPages"
                    className="premium-input w-24"
                    value={formData.maxPages}
                    onChange={handleChange}
                    min="1"
                    max="1000"
                    disabled={isLoading}
                />
            </div>

            <div className="cyber-form-group" style={{ gridColumn: '1 / -1' }}>
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

            <div className="form-actions mt-6" style={{ display: 'flex', gap: '1rem' }}>
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
