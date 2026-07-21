import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('recharts', () => ({
  ResponsiveContainer: ({ children }) => <div data-testid="responsive-container">{children}</div>,
  BarChart: ({ children }) => <div data-testid="bar-chart">{children}</div>,
  CartesianGrid: () => <div data-testid="grid" />,
  XAxis: () => <div data-testid="x-axis" />,
  YAxis: () => <div data-testid="y-axis" />,
  Tooltip: () => <div data-testid="tooltip" />,
  Bar: ({ children }) => <div data-testid="bar">{children}</div>,
  Cell: () => <div data-testid="cell" />,
}));

import SkillChart from './SkillChart';

function mockJsonResponse(payload) {
  return Promise.resolve({
    ok: true,
    json: async () => payload,
  });
}

describe('SkillChart', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('groups skills into narrower dashboard buckets and shows overflow counts', async () => {
    globalThis.fetch = vi.fn((input) => {
      const url = String(input);

      if (url.includes('/api/v1/stats/skills')) {
        return mockJsonResponse({
          skills: [
            { name: 'Python', category: 'Backend', count: 1015, dashboard_bucket: 'Backend' },
            { name: 'Java', category: 'Backend', count: 695, dashboard_bucket: 'Backend' },
            { name: 'C#', category: 'Backend', count: 398, dashboard_bucket: 'Backend' },
            { name: 'Node.js', category: 'Backend', count: 269, dashboard_bucket: 'Backend' },
            { name: 'API Development', category: 'Backend', count: 210, dashboard_bucket: 'Backend' },
            { name: 'SQL', category: 'Database', count: 794, dashboard_bucket: 'Database' },
            { name: 'MySQL', category: 'Database', count: 284, dashboard_bucket: 'Database' },
            { name: 'Linux', category: 'DevOps', count: 626, dashboard_bucket: 'Systems & Network' },
            { name: 'Azure', category: 'DevOps', count: 443, dashboard_bucket: 'Platform & Cloud' },
            { name: 'AWS', category: 'DevOps', count: 440, dashboard_bucket: 'Platform & Cloud' },
            { name: 'Docker', category: 'DevOps', count: 274, dashboard_bucket: 'Platform & Cloud' },
            { name: 'Kubernetes', category: 'DevOps', count: 288, dashboard_bucket: 'Platform & Cloud' },
            { name: 'Microsoft 365', category: 'DevOps', count: 238, dashboard_bucket: 'Platform & Cloud' },
            { name: 'Windows', category: 'DevOps', count: 396, dashboard_bucket: 'Systems & Network' },
            { name: 'Firewalls', category: 'DevOps', count: 364, dashboard_bucket: 'Security & Identity' },
            { name: 'JavaScript', category: 'Frontend', count: 421, dashboard_bucket: 'Frontend' },
            { name: 'React', category: 'Frontend', count: 337, dashboard_bucket: 'Frontend' },
            { name: 'HTML', category: 'Frontend', count: 260, dashboard_bucket: 'Frontend' },
            { name: 'Troubleshooting', category: 'Support & Operations', count: 418, dashboard_bucket: 'Support' },
            { name: 'Incident Management', category: 'Support & Operations', count: 311, dashboard_bucket: 'Support' },
            { name: 'Power BI', category: 'Data', count: 252, dashboard_bucket: 'Data' },
            { name: 'Machine Learning', category: 'Data', count: 357, dashboard_bucket: 'Data' },
          ],
        });
      }

      return Promise.reject(new Error(`Unhandled fetch: ${url}`));
    });

    render(<SkillChart />);

    await waitFor(() => {
      expect(screen.getByText('Top Requested Skills')).toBeInTheDocument();
    });

    expect(screen.getByText(/backend/i)).toBeInTheDocument();
    expect(screen.getByText(/database/i)).toBeInTheDocument();
    expect(screen.getByText(/platform & cloud/i)).toBeInTheDocument();
    expect(screen.getByText(/22 skills shown/i)).toBeInTheDocument();
    expect(screen.getAllByText(/\+1 more/i).length).toBeGreaterThan(0);
    expect(screen.queryByText(/top 15/i)).not.toBeInTheDocument();
  });

  it('counts only actually rendered grouped skills in the summary badge', async () => {
    globalThis.fetch = vi.fn((input) => {
      const url = String(input);

      if (url.includes('/api/v1/stats/skills')) {
        return mockJsonResponse({
          skills: [
            { name: 'Python', category: 'Backend', count: 1015, dashboard_bucket: 'Backend' },
            { name: 'SQL', category: 'Database', count: 794, dashboard_bucket: 'Database' },
            { name: 'Legacy Skill', category: 'Unmapped', count: 200, dashboard_bucket: null },
          ],
        });
      }

      return Promise.reject(new Error(`Unhandled fetch: ${url}`));
    });

    render(<SkillChart />);

    await waitFor(() => {
      expect(screen.getByText('Top Requested Skills')).toBeInTheDocument();
    });

    expect(screen.getByText(/2 skills shown/i)).toBeInTheDocument();
    expect(screen.queryByText(/3 skills shown/i)).not.toBeInTheDocument();
    expect(screen.queryByText('Legacy Skill')).not.toBeInTheDocument();
  });

  it('renders dynamic dashboard buckets after the predefined buckets', async () => {
    globalThis.fetch = vi.fn((input) => {
      const url = String(input);

      if (url.includes('/api/v1/stats/skills')) {
        return mockJsonResponse({
          skills: [
            { name: 'Python', category: 'Backend', count: 1015, dashboard_bucket: 'Backend' },
            {
              name: 'User Acceptance Testing',
              category: 'Product & Delivery',
              count: 65,
              dashboard_bucket: 'Product & Delivery',
            },
          ],
        });
      }

      return Promise.reject(new Error(`Unhandled fetch: ${url}`));
    });

    render(<SkillChart />);

    await waitFor(() => {
      expect(screen.getByText('Product & Delivery')).toBeInTheDocument();
    });

    expect(screen.getByText('User Acceptance Testing')).toBeInTheDocument();
    expect(screen.getAllByRole('heading', { level: 4 }).map((heading) => heading.textContent)).toEqual([
      'Backend',
      'Product & Delivery',
    ]);
  });
});
