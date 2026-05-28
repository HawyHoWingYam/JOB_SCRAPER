import React from 'react';
import { Search, X } from 'lucide-react';

function SearchBar({ value, onChange, onSubmit, isLoading, placeholder }) {
    const handleClear = () => {
        onChange('');
    };

    const handleKeyDown = (event) => {
        if (event.key === 'Enter' && onSubmit) {
            event.preventDefault();
            onSubmit();
        }
    };

    return (
        <div className="search-bar premium-search">
            <Search className="search-icon" size={20} />
            <input
                type="text"
                placeholder={placeholder || 'Search jobs by title, company, or deep scan description...'}
                value={value || ''}
                onChange={(e) => onChange(e.target.value)}
                onKeyDown={handleKeyDown}
                disabled={isLoading}
                className="premium-input search-input"
            />
            {value && (
                <button
                    type="button"
                    className="clear-search-btn"
                    onClick={handleClear}
                    disabled={isLoading}
                    title="Clear Search"
                >
                    <X size={16} />
                </button>
            )}
        </div>
    );
}

export default SearchBar;
