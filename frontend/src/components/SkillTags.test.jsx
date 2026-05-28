import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import SkillTags from './SkillTags';

describe('SkillTags', () => {
  it('expands hidden skills when the more control is clicked', async () => {
    const user = userEvent.setup();

    render(
      <SkillTags
        skills={['Python', 'Terraform', 'AWS', 'Azure', 'Docker', 'Kubernetes', 'Jenkins']}
        maxDisplay={5}
      />,
    );

    expect(screen.getByText('Python')).toBeInTheDocument();
    expect(screen.getByText('Docker')).toBeInTheDocument();
    expect(screen.queryByText('Kubernetes')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /\+2 more/i })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /\+2 more/i }));

    expect(screen.getByText('Kubernetes')).toBeInTheDocument();
    expect(screen.getByText('Jenkins')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /show less/i })).toHaveAttribute('aria-expanded', 'true');
  });
});
