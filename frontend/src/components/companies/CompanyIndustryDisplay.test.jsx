import { render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import productFixture from '../../fixtures/job_intelligence_product_surfaces.json';
import CompanyDetailModal from './CompanyDetailModal';
import CompanySummaryCard from './CompanySummaryCard';

function renderCompany(company) {
  render(
    <>
      <CompanySummaryCard
        company={company}
        status="ready"
        statusLabel="AI Ready"
        onClick={vi.fn()}
      />
      <CompanyDetailModal
        company={company}
        statusLabel="AI Ready"
        statusClassName="ready"
        descriptionText={company.ai_description || 'No AI description available'}
        onClose={vi.fn()}
      />
    </>,
  );

  return {
    card: screen.getByRole('button', { name: `Open details for ${company.name}` }),
    dialog: screen.getByRole('dialog', { name: company.name }),
  };
}

describe('Company Industry read-only display', () => {
  it('renders an explicit Primary plus additional governed assignments with full breadcrumbs', () => {
    const { card, dialog } = renderCompany(productFixture.companies[0]);

    expect(card).toHaveTextContent(
      'Primary · J · Information and communications +1',
    );
    expect(within(dialog).getByRole('heading', { name: 'Company Industries' }))
      .toBeInTheDocument();
    expect(dialog).toHaveTextContent('J · Information and communications');
    expect(dialog).toHaveTextContent('K · Financial and insurance activities');
    expect(dialog).toHaveTextContent('Primary Company Industry');
    expect(dialog).toHaveTextContent('Additional Company Industry');
    expect(within(dialog).getByRole('link', { name: 'Open Company Industries' }))
      .toHaveAttribute('href', '#job-intelligence/company-industries');
    expect(screen.queryByText('Legacy evidence only')).not.toBeInTheDocument();
  });

  it('renders Unassigned with a read-only review link and never promotes scalar evidence', () => {
    const { card, dialog } = renderCompany(productFixture.companies[1]);

    expect(card).toHaveTextContent('Company Industry: Unassigned');
    expect(dialog).toHaveTextContent('No governed Company Industry assignment');
    expect(within(dialog).getByRole('link', { name: 'Open Industry review item' }))
      .toHaveAttribute(
        'href',
        '#job-intelligence/company-industries?item=33000000-0000-0000-0000-000000000020',
      );
    expect(screen.queryByText('Legacy Retail evidence')).not.toBeInTheDocument();
    expect(within(dialog).queryByRole('button', { name: /assign|approve|reject/i }))
      .not.toBeInTheDocument();
  });

  it('renders explicit unavailable state without falling back to legacy Industry', () => {
    const { card, dialog } = renderCompany(productFixture.companies[2]);

    expect(card).toHaveTextContent('Company Industry: Unavailable');
    expect(dialog).toHaveTextContent(
      'Unavailable (COMPANY_INDUSTRY_TAXONOMY_NOT_ACTIVE)',
    );
    expect(screen.queryByText('Legacy Manufacturing evidence')).not.toBeInTheDocument();
  });
});
