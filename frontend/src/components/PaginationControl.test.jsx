import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import PaginationControl from './PaginationControl';

describe('PaginationControl', () => {
  it('submits a clamped page number when Go is pressed', () => {
    const onPageChange = vi.fn();

    render(
      <PaginationControl
        page={2}
        totalPages={5}
        totalItems={120}
        summaryText="Page 2 of 5"
        isLoading={false}
        onPageChange={onPageChange}
      />,
    );

    fireEvent.change(screen.getByLabelText(/jump to page/i), {
      target: { value: '99' },
    });
    fireEvent.click(screen.getByRole('button', { name: /go/i }));

    expect(onPageChange).toHaveBeenCalledWith(5);
  });

  it('does not submit when the clamped page matches the current page', () => {
    const onPageChange = vi.fn();

    render(
      <PaginationControl
        page={5}
        totalPages={5}
        totalItems={120}
        summaryText="Page 5 of 5"
        isLoading={false}
        onPageChange={onPageChange}
      />,
    );

    fireEvent.change(screen.getByLabelText(/jump to page/i), {
      target: { value: '99' },
    });
    fireEvent.click(screen.getByRole('button', { name: /go/i }));

    expect(onPageChange).not.toHaveBeenCalled();
  });

  it('submits when enter is pressed inside the page input', () => {
    const onPageChange = vi.fn();

    render(
      <PaginationControl
        page={1}
        totalPages={5}
        totalItems={120}
        summaryText="Page 1 of 5"
        isLoading={false}
        onPageChange={onPageChange}
      />,
    );

    fireEvent.change(screen.getByLabelText(/jump to page/i), {
      target: { value: '3' },
    });
    fireEvent.keyDown(screen.getByLabelText(/jump to page/i), {
      key: 'Enter',
      code: 'Enter',
    });

    expect(onPageChange).toHaveBeenCalledWith(3);
  });

  it('disables the input and go button while loading', () => {
    render(
      <PaginationControl
        page={1}
        totalPages={5}
        totalItems={120}
        summaryText="Page 1 of 5"
        isLoading
        onPageChange={vi.fn()}
      />,
    );

    expect(screen.getByLabelText(/jump to page/i)).toBeDisabled();
    expect(screen.getByRole('button', { name: /go/i })).toBeDisabled();
  });

  it('hides the control when hideWhenSinglePage is enabled and there is only one page', () => {
    const { container } = render(
      <PaginationControl
        page={1}
        totalPages={1}
        totalItems={20}
        summaryText="Page 1 of 1"
        hideWhenSinglePage
        isLoading={false}
        onPageChange={vi.fn()}
      />,
    );

    expect(container).toBeEmptyDOMElement();
  });
});
