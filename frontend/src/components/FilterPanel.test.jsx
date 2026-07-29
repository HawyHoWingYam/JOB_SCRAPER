import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import taxonomyFixture from "../fixtures/current_taxonomy_responses.json";

import FilterPanel from "./FilterPanel";

const EMPTY_FILTERS = {
  source_site: "",
  employment_type: "",
  employment_type_codes: [],
  subcategory_ids: [],
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
            { id: "full_time", code: "full_time", label: "Full-time", count: 3, order: 10 },
            { id: "permanent", code: "permanent", label: "Permanent", count: 2, order: 20 },
          ],
          source_classifications: [],
          company_industry_tree: { nodes: [] },
          job_subcategories: [],
          industries: [],
        }}
      />,
    );

    const employmentType = screen.getByRole("button", {
      name: "Employment Type, 0 selected",
    });
    expect(employmentType).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("Job Type")).not.toBeInTheDocument();
    expect(screen.queryByText("All Job Types")).not.toBeInTheDocument();

    await user.click(employmentType);
    await user.click(screen.getByRole("checkbox", { name: "Full-time (3 jobs)" }));
    await user.click(screen.getByRole("checkbox", { name: "Permanent (2 jobs)" }));

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
              parent_id: null,
              count: 8,
            },
            {
              id: "jobsdb:6287",
              source: "jobsdb",
              label: "Developers and Programmers",
              path: "Information Technology / Developers and Programmers",
              parent_id: "jobsdb:6281",
              count: 5,
            },
          ],
          company_industry_tree: { nodes: [] },
          job_subcategories: [],
          industries: [],
        }}
      />,
    );

    await user.click(screen.getByRole("button", {
      name: "Source Classification Paths, 0 selected",
    }));
    await user.type(
      screen.getByRole("searchbox", { name: "Search Source Classification Paths" }),
      "programmers",
    );
    await user.click(screen.getByRole("checkbox", {
      name: "JobsDB · Information Technology / Developers and Programmers (5 jobs)",
    }));

    expect(onFilterChange).toHaveBeenLastCalledWith({
      ...EMPTY_FILTERS,
      source_classification_ids: ["jobsdb:6287"],
    });
  });

  it("lets a selected Company Industry parent cover its descendants", async () => {
    const user = userEvent.setup();
    const onFilterChange = vi.fn();
    const root = taxonomyFixture.company_tree.nodes[0];
    const child = taxonomyFixture.company_child_tree.nodes[0];

    render(
      <FilterPanelHarness
        onFilterChange={onFilterChange}
        filterOptions={{
          employment_types: [],
          source_classifications: [],
          company_industry_tree: taxonomyFixture.company_tree,
          company_industries: [
            {
              id: root.id,
              label: root.labels.en,
              parent_id: null,
              level: root.level,
              count: 4,
            },
            {
              id: child.id,
              label: child.labels.en,
              parent_id: root.id,
              level: child.level,
              count: 2,
            },
          ],
          job_subcategories: [],
          industries: [],
        }}
      />,
    );

    await user.click(screen.getByRole("button", {
      name: "Company Industry, 0 selected",
    }));
    await user.click(
      screen.getByRole("checkbox", {
        name: "J · Information and communications (4 jobs)",
      }),
    );
    expect(onFilterChange).toHaveBeenLastCalledWith({
      ...EMPTY_FILTERS,
      company_industry_node_ids: [root.id],
    });

    await user.click(
      screen.getByRole("button", {
        name: "Show children of J · Information and communications",
      }),
    );
    const childCheckbox = screen.getByRole("checkbox", {
      name: "62 · Information technology service activities (2 jobs)",
    });
    expect(childCheckbox).toBeDisabled();
    expect(
      screen.getByText(
        "Company Industry: J · Information and communications",
      ),
    ).toBeInTheDocument();
  });
});
