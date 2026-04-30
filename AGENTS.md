# JobsDB Scraper - Design System Rules

> **Purpose**: Guide for integrating Figma designs using Model Context Protocol
> **Last Updated**: 2026-02-04

---

## 1. Project Overview

| Aspect | Details |
|--------|---------|
| **Framework** | React 19 + Vite 7 |
| **Styling** | Plain CSS (no preprocessor) |
| **Build Tool** | Vite |
| **Package Manager** | npm |

---

## 2. Token Definitions

### Color Palette

Design tokens are defined in CSS custom properties in `frontend/src/index.css`:

```css
:root {
  /* Background Colors */
  --bg-dark: #242424;
  --bg-light: #ffffff;

  /* Text Colors */
  --text-dark: rgba(255, 255, 255, 0.87);
  --text-light: #213547;

  /* Brand Colors */
  --primary: #007bff;
  --primary-hover: #0056b3;
  --accent: #646cff;
  --accent-hover: #535bf2;

  /* Semantic Colors */
  --error: #d8000c;
  --error-bg: #ffdddd;
  --error-border: #ffcccc;
  --success: #28a745;

  /* Neutral Colors */
  --gray-100: #f9f9f9;
  --gray-200: #f5f5f5;
  --gray-300: #eee;
  --gray-400: #ddd;
  --gray-500: #ccc;
  --gray-600: #333;
}
```

### Typography

```css
:root {
  /* Font Family */
  --font-primary: system-ui, Avenir, Helvetica, Arial, sans-serif;
  --font-fallback: Arial, sans-serif;

  /* Font Sizes */
  --text-xs: 12px;
  --text-sm: 14px;
  --text-base: 16px;
  --text-lg: 18px;
  --text-xl: 24px;
  --text-2xl: 32px;
  --text-3xl: 3.2em;

  /* Font Weights */
  --font-normal: 400;
  --font-medium: 500;
  --font-bold: 700;

  /* Line Heights */
  --leading-tight: 1.1;
  --leading-normal: 1.5;
}
```

### Spacing

```css
:root {
  /* Spacing Scale */
  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-5: 20px;
  --space-6: 24px;
  --space-8: 32px;

  /* Component Spacing */
  --padding-input: 10px;
  --padding-button: 0.6em 1.2em;
  --padding-card: 1.5rem;
  --gap-form: 10px;

  /* Border Radius */
  --radius-sm: 4px;
  --radius-md: 8px;
  --radius-lg: 12px;
}
```

---

## 3. Component Library

### File Structure

```
frontend/src/
├── components/
│   ├── ResultsList.jsx    # List display component
│   └── scraper/
│       └── ScheduleManager.jsx  # Scheduler UI entry component
├── App.jsx                # Main application
├── App.css                # Component styles
└── index.css              # Global styles & tokens
```

### Component Architecture

**Pattern**: Functional components with React Hooks

```jsx
// Standard component structure
import React, { useState } from 'react';

function ComponentName({ prop1, prop2 }) {
    const [state, setState] = useState(initialValue);

    const handleEvent = (e) => {
        // Event handler logic
    };

    return (
        <div className="component-container">
            {/* JSX content */}
        </div>
    );
}

export default ComponentName;
```

### Naming Conventions

| Type | Convention | Example |
|------|------------|---------|
| Components | PascalCase | `ScheduleManager`, `ResultsList` |
| CSS Classes | kebab-case | `crawler-input-container` |
| Event Handlers | camelCase with `handle` prefix | `handleSubmit`, `handleCrawl` |
| State Variables | camelCase | `isLoading`, `results` |

---

## 4. Styling Approach

### CSS Methodology

**Approach**: Plain CSS with BEM-inspired naming

```css
/* Block */
.crawler-input-container { }

/* Element */
.crawler-input-container form { }

/* Modifier */
.results-container.error { }
```

### Component Style Pattern

Each component uses class-based styling defined in `App.css`:

```css
/* Container pattern */
.component-container {
  background: var(--gray-200);
  padding: var(--padding-card);
  border-radius: var(--radius-md);
  box-shadow: 0 2px 4px rgba(0,0,0,0.1);
}

/* Interactive elements */
.interactive-element {
  cursor: pointer;
  transition: border-color 0.25s;
}

.interactive-element:hover {
  border-color: var(--accent);
}

.interactive-element:disabled {
  background-color: var(--gray-500);
  cursor: not-allowed;
}
```

### Responsive Design

```css
/* Dark/Light mode support */
@media (prefers-color-scheme: light) {
  :root {
    color: var(--text-light);
    background-color: var(--bg-light);
  }
}

/* Minimum width constraint */
body {
  min-width: 320px;
}

/* Container max-width */
.app-container {
  max-width: 800px;
  margin: 0 auto;
}
```

---

## 5. Asset Management

### Directory Structure

```
frontend/
├── src/assets/       # Source assets (imported in JS)
│   └── react.svg
├── public/           # Static assets (served directly)
│   └── vite.svg
```

### Asset Import Pattern

```jsx
// SVG as React component (recommended)
import Logo from './assets/logo.svg';

// In component
<img src={Logo} alt="Logo" />
```

### Image Guidelines

| Type | Location | Usage |
|------|----------|-------|
| Icons/Logos | `src/assets/` | Import in components |
| Static Images | `public/` | Reference by URL path |
| Dynamic Images | External URL | Fetch from API |

---

## 6. Icon System

### Current State

No dedicated icon library installed. Options for implementation:

**Recommended**: Install `lucide-react` or `react-icons`

```bash
npm install lucide-react
```

```jsx
// Usage pattern
import { Search, Loader, AlertCircle } from 'lucide-react';

<Search size={20} color="var(--primary)" />
```

### Icon Naming Convention

| Category | Prefix | Example |
|----------|--------|---------|
| Action | `icon-` | `icon-search`, `icon-submit` |
| Status | `status-` | `status-loading`, `status-error` |
| Navigation | `nav-` | `nav-home`, `nav-back` |

---

## 7. Button Styles

### Primary Button

```css
.btn-primary {
  padding: 10px 20px;
  background-color: var(--primary);
  color: white;
  border: none;
  border-radius: var(--radius-sm);
  cursor: pointer;
  font-size: var(--text-base);
  font-weight: var(--font-bold);
}

.btn-primary:hover {
  background-color: var(--primary-hover);
}

.btn-primary:disabled {
  background-color: var(--gray-500);
  cursor: not-allowed;
}
```

### Button Variants

| Variant | Class | Use Case |
|---------|-------|----------|
| Primary | `.start-btn` | Main actions |
| Secondary | `.btn-secondary` | Secondary actions |
| Danger | `.btn-danger` | Destructive actions |

---

## 8. Form Elements

### Input Fields

```css
.input-field {
  flex: 1;
  padding: var(--padding-input);
  border: 1px solid var(--gray-400);
  border-radius: var(--radius-sm);
  font-size: var(--text-base);
}

.input-field:focus {
  outline: 2px solid var(--primary);
  border-color: var(--primary);
}

.input-field:disabled {
  background-color: var(--gray-200);
  cursor: not-allowed;
}
```

### Form Layout

```css
.form-container {
  display: flex;
  gap: var(--gap-form);
}
```

---

## 9. Card Components

### Standard Card

```css
.card {
  background: white;
  border: 1px solid var(--gray-300);
  padding: var(--padding-card);
  border-radius: var(--radius-md);
}

.card-header {
  margin-bottom: var(--space-4);
}

.card-body {
  /* Content area */
}

.card-footer {
  margin-top: var(--space-4);
  border-top: 1px solid var(--gray-300);
  padding-top: var(--space-4);
}
```

### Card Variants

```css
.card.error {
  border-color: var(--error-border);
  background-color: #fff5f5;
}

.card.success {
  border-color: var(--success);
  background-color: #f0fff4;
}
```

---

## 10. Figma Integration Guidelines

### When Implementing Figma Designs

1. **Extract tokens first**: Map Figma colors/spacing to CSS variables
2. **Use existing patterns**: Match to established component patterns
3. **Maintain consistency**: Follow naming conventions

### Color Mapping

| Figma Token | CSS Variable |
|-------------|--------------|
| Primary/Blue | `--primary` |
| Error/Red | `--error` |
| Background/Dark | `--bg-dark` |
| Text/Primary | `--text-dark` |

### Spacing Mapping

| Figma Spacing | CSS Variable |
|---------------|--------------|
| 4px | `--space-1` |
| 8px | `--space-2` |
| 16px | `--space-4` |
| 24px | `--space-6` |

---

## 11. Future Enhancements (Planned)

Based on the project plan, the following will be added:

- **Recharts**: For data visualization
- **React Router**: For navigation
- **TanStack Query**: For data fetching
- **WebSocket**: For real-time updates

### Planned Component Structure

```
frontend/src/
├── components/
│   ├── layout/        # Header, Footer, Sidebar
│   ├── dashboard/     # Stats, Charts, SkillCloud
│   ├── jobs/          # JobList, JobCard, JobDetail
│   ├── scraper/       # ScrapeForm, ProgressBar
│   └── ui/            # Button, Input, Card (shared)
├── pages/             # Route pages
├── hooks/             # Custom hooks
├── api/               # API client
└── utils/             # Helpers
```

---

*Document generated for Figma MCP integration*
