import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import GovernedTargetPicker from './GovernedTargetPicker';

describe('GovernedTargetPicker', () => {
  it('replaces stale visible options when the governed options change', () => {
    const onChange = vi.fn();
    const { rerender } = render(
      <GovernedTargetPicker
        options={[{ value: 'old-target', label: 'Old target' }]}
        value="old-target"
        onChange={onChange}
      />,
    );

    rerender(
      <GovernedTargetPicker
        options={[{ value: 'new-target', label: 'New target' }]}
        value="new-target"
        onChange={onChange}
      />,
    );

    expect(screen.getByRole('option', { name: 'New target' })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: 'Old target' })).not.toBeInTheDocument();
  });
});
