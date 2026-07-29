import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import Dashboard from "./Dashboard";

const stats = {
  total_jobs: 12,
  enriched_jobs: 7,
  eligible_enriched_jobs: 7,
  pending_enrichment: 3,
  ai_eligible_jobs: 10,
  ineligible_jobs: 2,
};

const aiOverview = {
  active_runs: 0,
  failed_jobs: 0,
  last_completed_run: null,
};

const skills = {
  processed_total: 7,
  matched_job_total: 5,
  match_coverage: 71,
  candidate_backlog: {
    unresolved_candidate_total: 2,
    affected_job_total: 3,
    ready_candidate_total: 1,
    ready_threshold: 5,
  },
  skills: [
    {
      code: "python",
      name: "Python",
      category: "Backend",
      count: 4,
      prevalence: 57,
      dashboard_bucket: "Backend",
    },
  ],
};

function jsonResponse(payload) {
  return Promise.resolve({
    ok: true,
    status: 200,
    statusText: "OK",
    json: async () => payload,
  });
}

describe("Dashboard", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders real chart contracts and all three independently fetched sections", async () => {
    const user = userEvent.setup();
    const onNavigateToJobs = vi.fn();
    const onNavigateToClassification = vi.fn();
    globalThis.fetch = vi.fn((input) => {
      const url = String(input);
      if (url.includes("/stats/overview")) return jsonResponse(stats);
      if (url.includes("/ai/overview")) return jsonResponse(aiOverview);
      if (url.includes("/stats/skills")) return jsonResponse(skills);
      return Promise.reject(new Error(`Unhandled request: ${url}`));
    });

    render(
      <Dashboard
        onNavigateToAI={vi.fn()}
        onNavigateToClassification={onNavigateToClassification}
        onNavigateToJobs={onNavigateToJobs}
      />,
    );

    expect(await screen.findByText("Total Jobs Acquired")).toBeInTheDocument();
    expect(
      screen.getByText("Top Matched Canonical Skills"),
    ).toBeInTheDocument();
    expect(screen.getByText("Python")).toBeInTheDocument();
    expect(
      screen.queryByRole("region", { name: "Job Intelligence Governance" }),
    ).not.toBeInTheDocument();
    expect(globalThis.fetch).toHaveBeenCalledTimes(3);
    expect(await screen.findByText(/last refreshed at/i)).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "View 4 Jobs matched to Python" }),
    );
    expect(onNavigateToJobs).toHaveBeenLastCalledWith({ skillIds: ["python"] });
    await user.click(
      screen.getByRole("button", {
        name: "Open Skill Classification for 1 ready Candidates",
      }),
    );
    expect(onNavigateToClassification).toHaveBeenLastCalledWith("skill");
  });

  it("refreshes all sections while retaining and marking a failed section stale", async () => {
    const user = userEvent.setup();
    let skillRequests = 0;
    globalThis.fetch = vi.fn((input) => {
      const url = String(input);
      if (url.includes("/stats/overview")) return jsonResponse(stats);
      if (url.includes("/ai/overview")) return jsonResponse(aiOverview);
      if (url.includes("/stats/skills")) {
        skillRequests += 1;
        return skillRequests === 1
          ? jsonResponse(skills)
          : Promise.reject(new Error("skills offline"));
      }
      return Promise.reject(new Error(`Unhandled request: ${url}`));
    });

    render(<Dashboard onNavigateToAI={vi.fn()} />);
    expect(await screen.findByText("Python")).toBeVisible();

    await user.click(screen.getByRole("button", { name: "Refresh" }));

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Skills data is stale.",
    );
    expect(screen.getByText("Python")).toBeVisible();
    await waitFor(() => {
      expect(
        screen.getByText("Refresh completed with stale sections."),
      ).toBeInTheDocument();
    });
    expect(globalThis.fetch).toHaveBeenCalledTimes(6);
  });
});
