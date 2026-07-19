import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import canonicalFixture from "../fixtures/canonical_job_taxonomy_responses.json";
import companyFixture from "../fixtures/company_industry_responses.json";

import FilterPanel from "./FilterPanel";

const EMPTY_FILTERS = {
  source_site: "",
  employment_type: "",
  employment_type_codes: [],
  subcategory_ids: [],
  canonical_subcategory_ids: [],
  canonical_category_ids: [],
  canonical_domain_ids: [],
  industry: "",
  company_industry_node_ids: [],
  source_classification_ids: [],
  posted_date_from: "",
  posted_date_to: "",
  experience_years_from: "",
  experience_years_to: "",
};

function FilterPanelHarness({
  filterOptions,
  loadCompanyIndustryChildren,
  onFilterChange,
}) {
  const [filters, setFilters] = useState(EMPTY_FILTERS);

  const handleFilterChange = (nextFilters) => {
    setFilters(nextFilters);
    onFilterChange(nextFilters);
  };

  return (
    <FilterPanel
      filters={filters}
      onFilterChange={handleFilterChange}
      loadCompanyIndustryChildren={loadCompanyIndustryChildren}
      onReset={vi.fn()}
      onDatePresetChange={vi.fn()}
      filterOptions={filterOptions}
      isLoading={false}
      datePreset="any_time"
      validationError={null}
      pendingChangeCount={0}
    />
  );
}

describe("FilterPanel", () => {
  it("submits governed Employment Type codes as a multi-value filter", async () => {
    const user = userEvent.setup();
    const onFilterChange = vi.fn();

    render(
      <FilterPanelHarness
        onFilterChange={onFilterChange}
        filterOptions={{
          employment_types: [
            { code: "full_time", label: "Full-time", order: 10 },
            { code: "permanent", label: "Permanent", order: 20 },
          ],
          source_classifications: [],
          canonical_taxonomy: { domains: [] },
          company_industry_tree: { nodes: [] },
          job_subcategories: [],
          industries: [],
        }}
      />,
    );

    const employmentType = screen.getByLabelText("Employment Type");
    expect(employmentType).toHaveAttribute("multiple");
    expect(screen.getByRole("option", { name: "Full-time" })).toHaveValue(
      "full_time",
    );
    expect(screen.getByRole("option", { name: "Permanent" })).toHaveValue(
      "permanent",
    );
    expect(screen.queryByText("Job Type")).not.toBeInTheDocument();
    expect(screen.queryByText("All Job Types")).not.toBeInTheDocument();

    await user.selectOptions(employmentType, ["full_time", "permanent"]);

    expect(onFilterChange).toHaveBeenCalledWith({
      ...EMPTY_FILTERS,
      employment_type_codes: ["full_time", "permanent"],
    });
  });

  it("submits source-qualified Source Classification identities", async () => {
    const user = userEvent.setup();
    const onFilterChange = vi.fn();

    render(
      <FilterPanelHarness
        onFilterChange={onFilterChange}
        filterOptions={{
          employment_types: [],
          source_classifications: [
            {
              id: "jobsdb:6281",
              source: "jobsdb",
              label: "Information Technology",
              path: "Information Technology",
            },
            {
              id: "jobsdb:6287",
              source: "jobsdb",
              label: "Developers and Programmers",
              path: "Information Technology / Developers and Programmers",
            },
          ],
          canonical_taxonomy: { domains: [] },
          company_industry_tree: { nodes: [] },
          job_subcategories: [],
          industries: [],
        }}
      />,
    );

    const sourcePaths = screen.getByLabelText("Source Classification Paths");
    expect(sourcePaths).toHaveAttribute("multiple");
    expect(
      screen.getByRole("option", {
        name: "JobsDB · Information Technology / Developers and Programmers",
      }),
    ).toHaveValue("jobsdb:6287");

    await user.selectOptions(sourcePaths, ["jobsdb:6281", "jobsdb:6287"]);

    expect(onFilterChange).toHaveBeenLastCalledWith({
      ...EMPTY_FILTERS,
      source_classification_ids: ["jobsdb:6281", "jobsdb:6287"],
    });
  });

  it("submits hierarchical Canonical Job Taxonomy IDs by governed level", async () => {
    const user = userEvent.setup();
    const onFilterChange = vi.fn();
    const domain = canonicalFixture.tree.domains[0];
    const category = domain.categories[0];
    const subcategory = category.subcategories[0];

    render(
      <FilterPanelHarness
        onFilterChange={onFilterChange}
        filterOptions={{
          employment_types: [],
          source_classifications: [],
          canonical_taxonomy: canonicalFixture.tree,
          company_industry_tree: { nodes: [] },
          job_subcategories: [],
          industries: [],
        }}
      />,
    );

    const taxonomy = screen.getByLabelText("Canonical Job Taxonomy");
    expect(taxonomy).toHaveAttribute("multiple");
    expect(
      screen.getByRole("option", { name: "Job Domain · Accounting" }),
    ).toHaveValue(domain.id);
    expect(
      screen.getByRole("option", {
        name: "Job Category · Accounting / Financial Accounting",
      }),
    ).toHaveValue(category.id);
    expect(
      screen.getByRole("option", {
        name: "Job Subcategory · Accounting / Financial Accounting / Accounts Payable",
      }),
    ).toHaveValue(subcategory.id);

    await user.selectOptions(taxonomy, [domain.id, category.id, subcategory.id]);

    expect(onFilterChange).toHaveBeenLastCalledWith({
      ...EMPTY_FILTERS,
      canonical_domain_ids: [domain.id],
      canonical_category_ids: [category.id],
      canonical_subcategory_ids: [subcategory.id],
    });
  });

  it("selects Company Industry ancestors and lazily browses descendants", async () => {
    const user = userEvent.setup();
    const onFilterChange = vi.fn();
    const root = companyFixture.tree.nodes[0];
    const child = companyFixture.child_tree.nodes[0];
    const loadCompanyIndustryChildren = vi.fn().mockResolvedValue(
      companyFixture.child_tree,
    );

    render(
      <FilterPanelHarness
        onFilterChange={onFilterChange}
        loadCompanyIndustryChildren={loadCompanyIndustryChildren}
        filterOptions={{
          employment_types: [],
          source_classifications: [],
          canonical_taxonomy: { domains: [] },
          company_industry_tree: companyFixture.tree,
          job_subcategories: [],
          industries: [],
        }}
      />,
    );

    const companyIndustry = screen.getByRole("group", {
      name: "Company Industry",
    });
    await user.click(
      screen.getByRole("checkbox", {
        name: "J · Information and communications",
      }),
    );
    expect(onFilterChange).toHaveBeenLastCalledWith({
      ...EMPTY_FILTERS,
      company_industry_node_ids: [root.id],
    });

    await user.click(
      screen.getByRole("button", {
        name: "Browse children of J · Information and communications",
      }),
    );
    expect(loadCompanyIndustryChildren).toHaveBeenCalledWith(root.id);
    const childCheckbox = await screen.findByRole("checkbox", {
      name: "62 · Information technology service activities",
    });
    expect(companyIndustry).toContainElement(childCheckbox);

    await user.click(childCheckbox);
    expect(onFilterChange).toHaveBeenLastCalledWith({
      ...EMPTY_FILTERS,
      company_industry_node_ids: [root.id, child.id],
    });
    expect(
      screen.getByText(
        "Company Industry: J · Information and communications, 62 · Information technology service activities",
      ),
    ).toBeInTheDocument();
  });
});
