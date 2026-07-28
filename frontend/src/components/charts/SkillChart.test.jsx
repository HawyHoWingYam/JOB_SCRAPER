import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import SkillChart from "./SkillChart";

const skillData = {
  processed_total: 100,
  matched_job_total: 72,
  match_coverage: 72,
  candidate_backlog: {
    unresolved_candidate_total: 12,
    affected_job_total: 34,
    ready_candidate_total: 3,
    ready_threshold: 5,
  },
  skills: [
    {
      code: "python",
      name: "Python",
      category: "Backend",
      count: 40,
      prevalence: 40,
      dashboard_bucket: "Backend",
    },
    {
      code: "java",
      name: "Java",
      category: "Backend",
      count: 30,
      prevalence: 30,
      dashboard_bucket: "Backend",
    },
    {
      code: "node",
      name: "Node.js",
      category: "Backend",
      count: 20,
      prevalence: 20,
      dashboard_bucket: "Backend",
    },
    {
      code: "dotnet",
      name: ".NET",
      category: "Backend",
      count: 15,
      prevalence: 15,
      dashboard_bucket: "Backend",
    },
    {
      code: "go",
      name: "Go",
      category: "Backend",
      count: 10,
      prevalence: 10,
      dashboard_bucket: "Backend",
    },
    {
      code: "uat",
      name: "User Acceptance Testing",
      category: "Product & Delivery",
      count: 8,
      prevalence: 8,
      dashboard_bucket: "Product & Delivery",
    },
    {
      code: "hidden",
      name: "Hidden Legacy",
      category: "Other",
      count: 99,
      prevalence: 99,
      dashboard_bucket: null,
    },
  ],
};

describe("SkillChart", () => {
  it("shows canonical coverage, prevalence, truthful visible counts, and expansion", async () => {
    const user = userEvent.setup();
    render(<SkillChart data={skillData} />);

    expect(
      screen.getByRole("heading", { name: "Top Matched Canonical Skills" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Canonical Skill Match Coverage"),
    ).toBeInTheDocument();
    expect(screen.getByText("72%")).toBeInTheDocument();
    expect(screen.getByText("Unresolved Skill Candidates")).toBeInTheDocument();
    expect(screen.getByText(/12/)).toBeInTheDocument();
    expect(screen.getByText("5 of 6 visible")).toBeInTheDocument();
    expect(screen.queryByText("Go")).not.toBeInTheDocument();
    expect(screen.getByText("40 Jobs · 40%")).toBeVisible();

    const expand = screen.getByRole("button", { name: "Show 1 more" });
    expect(expand).toHaveAttribute("aria-expanded", "false");
    await user.click(expand);

    expect(screen.getByText("Go")).toBeVisible();
    expect(screen.getByText("6 returned")).toBeInTheDocument();
    expect(screen.queryByText("Hidden Legacy")).not.toBeInTheDocument();
  });

  it("preserves dynamic backend-owned buckets after preferred buckets", () => {
    render(<SkillChart data={skillData} />);

    expect(
      screen
        .getAllByRole("heading", { level: 4 })
        .map((heading) => heading.textContent),
    ).toEqual(["Backend", "Product & Delivery"]);
  });

  it("preserves backend ranking order and exposes accessible values", () => {
    const rankedData = {
      ...skillData,
      skills: [
        {
          code: "z-first",
          name: "Backend First",
          category: "Backend",
          count: 10,
          prevalence: 10,
          dashboard_bucket: "Backend",
        },
        {
          code: "a-second",
          name: "Backend Second",
          category: "Backend",
          count: 10,
          prevalence: 10,
          dashboard_bucket: "Backend",
        },
      ],
    };

    render(<SkillChart data={rankedData} loading />);

    expect(
      screen.getByRole("list").querySelectorAll("li")[0],
    ).toHaveAccessibleName("Backend First: 10 Jobs, 10% prevalence");
    expect(
      screen.getByLabelText("2 returned Skills in Backend"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("status", {
        name: "",
      }),
    ).toHaveTextContent("Refreshing matched canonical Skills");
  });

  it("renders an accessible empty error state and retry", async () => {
    const user = userEvent.setup();
    const onRetry = vi.fn();
    render(<SkillChart error="HTTP 500" onRetry={onRetry} />);

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Skills data is unavailable.",
    );
    await user.click(screen.getByRole("button", { name: "Retry skills" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });
});
