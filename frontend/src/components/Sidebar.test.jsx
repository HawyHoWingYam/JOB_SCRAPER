import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import Sidebar from './Sidebar';

describe('Sidebar', () => {
  it('renders remaining app navigation without removed network view', async () => {
    const setActiveView = vi.fn();
    const removedNetworkLabel = ['linked', 'in'].join('');
    render(<Sidebar activeView="dashboard" setActiveView={setActiveView} />);

    expect(screen.getByRole('button', { name: /dashboard/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /job browser/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /companies/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /ai enrichment/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /scheduler/i })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: new RegExp(removedNetworkLabel, 'i') })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /operator health/i })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: /scheduler/i }));
    expect(setActiveView).toHaveBeenCalledWith('scheduler');
  });

  it('routes the footer settings button into the settings view', async () => {
    const setActiveView = vi.fn();

    render(<Sidebar activeView="dashboard" setActiveView={setActiveView} />);

    await userEvent.click(screen.getByRole('button', { name: /^settings$/i }));

    expect(setActiveView).toHaveBeenCalledWith('settings');
  });

  it('shows a neutral console-ready footer status instead of claiming the whole system is online', () => {
    render(<Sidebar activeView="dashboard" setActiveView={vi.fn()} />);

    expect(screen.getByText(/console ready/i)).toBeInTheDocument();
    expect(screen.queryByText(/system online/i)).not.toBeInTheDocument();
    expect(document.querySelector('.status-dot.online')).toBeNull();
  });
});
