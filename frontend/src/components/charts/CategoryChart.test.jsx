import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import CategoryChart from "./CategoryChart";

const categoryData = {
  population_total: 100,
  assigned_total: 80,
  unassigned_total: 20,
  assignment_coverage: 80,
  classification_ready_unassigned_total: 12,
  top_categories: [
    {
      code: "backend",
      path: "Technology / Software Engineering / Backend Development",
      label: "Backend Development",
      count: 30,
      share_of_assigned: 38,
    },
  ],
  other_categories: {
    count: 50,
    bucket_count: 2,
    share_of_assigned: 62,
    items: [
      {
        code: "security",
        path: "Technology / Infrastructure / Cybersecurity",
        label: "Cybersecurity",
        count: 28,
        share_of_assigned: 35,
      },
      {
        code: "support",
        path: "Technology / Operations / Technical Support",
        label: "Technical Support",
        count: 22,
        share_of_assigned: 28,
      },
    ],
  },
};

describe("CategoryChart", () => {
  it("leads with assignment health and exposes full canonical paths", () => {
    render(<CategoryChart data={categoryData} onSelectCategory={vi.fn()} />);

    expect(
      screen.getByRole("heading", { name: "Jobs by Canonical Job Taxonomy" }),
    ).toBeInTheDocument();
    expect(screen.getByText("80% assigned")).toBeInTheDocument();
    expect(screen.getByText("Unassigned Jobs")).toBeInTheDocument();
    expect(screen.getByText("Classification-ready")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Technology / Software Engineering / Backend Development",
      ),
    ).toBeVisible();
    expect(
      screen.getByRole("meter", {
        name: "Technology / Software Engineering / Backend Development: 38% of accepted assignments",
      }),
    ).toHaveAttribute("aria-valuenow", "38");
    expect(
      screen.getByRole("button", {
        name: "View 30 Jobs in Technology / Software Engineering / Backend Development",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/source listings may have expired/i),
    ).toBeInTheDocument();
  });

  it("announces a refresh while retaining the last successful data", () => {
    render(<CategoryChart data={categoryData} loading />);

    expect(screen.getByText("Backend Development")).toBeVisible();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Refreshing canonical assignments",
    );
  });

  it("expands Other into every counted canonical path", async () => {
    const user = userEvent.setup();
    const onSelectCategory = vi.fn();
    render(
      <CategoryChart
        data={categoryData}
        onSelectCategory={onSelectCategory}
      />,
    );

    const other = screen.getByRole("button", {
      name: /other.*50 jobs.*2 job subcategories/i,
    });
    expect(other).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("Cybersecurity")).not.toBeInTheDocument();

    await user.click(other);

    expect(other).toHaveAttribute("aria-expanded", "true");
    expect(
      screen.getByText("Technology / Infrastructure / Cybersecurity"),
    ).toBeVisible();
    expect(
      screen.getByText("Technology / Operations / Technical Support"),
    ).toBeVisible();
    await user.click(
      screen.getByRole("button", {
        name: "View 28 Jobs in Technology / Infrastructure / Cybersecurity",
      }),
    );
    expect(onSelectCategory).toHaveBeenCalledWith(
      categoryData.other_categories.items[0],
    );
    expect(other).toHaveAttribute("aria-expanded", "true");
  });

  it("retains stale data with an accessible error and retry", async () => {
    const user = userEvent.setup();
    const onRetry = vi.fn();
    render(
      <CategoryChart
        data={categoryData}
        error="HTTP 503"
        lastUpdated={Date.now()}
        onRetry={onRetry}
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Taxonomy data is stale.",
    );
    expect(screen.getByText("Backend Development")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Retry taxonomy" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });
});
