import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import FilterPanel from "./FilterPanel";

const EMPTY_FILTERS = {
  source_site: "",
  employment_type: "",
  subcategory_ids: [],
  industry: "",
  posted_date_from: "",
  posted_date_to: "",
  experience_years_from: "",
  experience_years_to: "",
};

describe("FilterPanel", () => {
  it("renders structured and legacy employment options as selectable labels", async () => {
    const user = userEvent.setup();
    const onFilterChange = vi.fn();

    render(
      <FilterPanel
        filters={EMPTY_FILTERS}
        onFilterChange={onFilterChange}
        onReset={vi.fn()}
        onDatePresetChange={vi.fn()}
        filterOptions={{
          employment_types: [
            { code: "full_time", label: "Full-time", order: 10 },
            "Permanent",
          ],
          job_subcategories: [],
          industries: [],
        }}
        isLoading={false}
        datePreset="any_time"
        validationError={null}
        pendingChangeCount={0}
      />,
    );

    const jobType = screen.getByLabelText("Job Type");
    expect(screen.getByRole("option", { name: "Full-time" })).toHaveValue(
      "Full-time",
    );
    expect(screen.getByRole("option", { name: "Permanent" })).toHaveValue(
      "Permanent",
    );
    expect(screen.queryByText("[object Object]")).not.toBeInTheDocument();

    await user.selectOptions(jobType, "Full-time");

    expect(onFilterChange).toHaveBeenCalledWith({
      ...EMPTY_FILTERS,
      employment_type: "Full-time",
    });
  });
});
