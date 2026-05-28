import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import SearchBar from './SearchBar';

describe('SearchBar', () => {
  it('uses a job-oriented default placeholder when none is provided', () => {
    render(
      <SearchBar
        value=""
        onChange={vi.fn()}
        onSubmit={vi.fn()}
        isLoading={false}
      />
    );

    expect(
      screen.getByPlaceholderText(/search jobs by title, company, or deep scan description/i)
    ).toBeInTheDocument();
  });

  it('clears the current value when the clear button is pressed', () => {
    const onChange = vi.fn();

    render(
      <SearchBar
        value="backend"
        onChange={onChange}
        onSubmit={vi.fn()}
        isLoading={false}
      />
    );

    fireEvent.click(screen.getByRole('button', { name: /clear search/i }));

    expect(onChange).toHaveBeenCalledWith('');
  });
});
