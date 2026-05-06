import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('recharts', () => ({
  ResponsiveContainer: ({ children }) => <div data-testid="responsive-container">{children}</div>,
  PieChart: ({ children }) => <div data-testid="pie-chart">{children}</div>,
  Pie: ({ children }) => <div data-testid="pie">{children}</div>,
  Cell: () => <div data-testid="cell" />,
  Tooltip: () => <div data-testid="tooltip" />,
}));

import CategoryChart from './CategoryChart';

function mockJsonResponse(payload) {
  return Promise.resolve({
    ok: true,
    json: async () => payload,
  });
}

describe('CategoryChart', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders the dashboard category diagnostics without merging fallback buckets into other specific categories', async () => {
    globalThis.fetch = vi.fn((input) => {
      const url = String(input);

      if (url.includes('/api/v1/stats/categories/dashboard')) {
        return mockJsonResponse({
          categorized_total: 7308,
          specific_total: 5043,
          fallback_total: 2265,
          top_specific_categories: [
            {
              path: 'Information & Communication Technology / Software Development / Backend Development',
              label: 'Backend Development',
              count: 983,
              share_of_specific: 19,
            },
            {
              path: 'Information & Communication Technology / Infrastructure & Support / Systems Administration',
              label: 'Systems Administration',
              count: 764,
              share_of_specific: 15,
            },
          ],
          other_specific_categories: {
            count: 3296,
            bucket_count: 10,
            share_of_specific: 65,
          },
          fallback_buckets: [
            {
              path: 'Information & Communication Technology / General / General',
              label: 'General / General',
              count: 2262,
              share_of_categorized: 31,
              source_breakdown: [
                { source_site: 'ctgoodjobs', source_subclassification_name: null, count: 2220 },
                { source_site: 'jobsdb', source_subclassification_name: 'Other', count: 43 },
              ],
            },
          ],
        });
      }

      return Promise.reject(new Error(`Unhandled fetch: ${url}`));
    });

    render(<CategoryChart totalJobs={7308} />);

    await waitFor(() => {
      expect(screen.getByText('Jobs by AI Category')).toBeInTheDocument();
    });

    expect(screen.getByRole('heading', { name: /fallback diagnostic/i })).toBeInTheDocument();
    expect(screen.getByText('General / General')).toBeInTheDocument();
    expect(screen.getByText(/ctgoodjobs \/ no source subcategory/i)).toBeInTheDocument();
    expect(screen.getByText(/other specific categories/i)).toBeInTheDocument();
    expect(screen.queryByText(/other categories/i)).not.toBeInTheDocument();
  });
});
