/** @vitest-environment jsdom */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import userEvent from "@testing-library/user-event";
import { apiFetchJson } from "../../api/client";
import CrawlTasksPage, {
  AUTO_REFRESH_MS,
  CANCELLATION_REFRESH_MS,
} from "./CrawlTasksPage";
import { DRAFT_PREFIX } from "../../features/taskControl/wizard/wizardDraft";

vi.mock("../../api/client", () => ({
  apiFetchJson: vi.fn(),
}));

const listingTask = {
  crawl_job_id: "listing-task",
  status: "running",
  trigger_type: "manual",
  source_site: "jobsdb",
  crawl_mode: "headless",
  crawl_phase: "listing",
  phase: 1,
  job_ids_collected: 87,
  raw_job_ids_collected: 96,
  listings_staged: 87,
  detail_target_rows: 87,
  current_page: 2,
  total_pages: 10,
  updated_at: "2026-07-15T12:00:00Z",
};

function normalizedTaskDetail({
  id = "listing-task",
  status = "running",
  phase = "listing",
  sourceSite = "jobsdb",
  actions,
} = {}) {
  return {
    run: {
      crawl_job_id: id,
      source_site: sourceSite,
      crawl_phase: phase,
      crawl_mode: sourceSite === "ctgoodjobs" ? "headed" : "headless",
      trigger_kind: "one_off",
      status,
      queued_at: "2026-07-15T12:00:00Z",
      started_at: "2026-07-15T12:01:00Z",
      completed_at: null,
      updated_at: "2026-07-15T12:02:00Z",
      authority: { authority_kind: "legacy" },
      listing_workload: phase === "listing" ? {
        query_target_count: 2,
        page_depth: 5,
        estimated_max_pages: 10,
        run_page_cap: 10,
        pages_requested: 2,
      } : null,
      detail_snapshot: phase === "detail" ? {
        backlog_scope: { kind: "global" },
        cutoff_at: "2026-07-15T12:00:00Z",
        target_count: 4,
        fetched_count: 3,
        saved_count: 2,
        failed_count: 1,
        unavailable_count: 1,
        manual_action_count: 0,
        remaining_count: 1,
        future_eligible_count: 7,
        detail_run_cap: 5000,
      } : null,
      recovery_attempt: null,
    },
    persisted_status: status,
    operator_state: status === "cancelling" ? "cancellation_pending" : null,
    queued_at: "2026-07-15T12:00:00Z",
    started_at: "2026-07-15T12:01:00Z",
    completed_at: null,
    updated_at: "2026-07-15T12:02:00Z",
    detail_pacing: phase === "detail" ? {
      interval_min_seconds: 1,
      interval_max_seconds: 3,
      burst_size: 20,
      burst_pause_seconds: 30,
    } : null,
    issue: null,
    manual_action_guidance: null,
    recovery_attempt: null,
    actions: actions ?? (status === "running" ? [
      { action: "cancel", enabled: true, reason_code: null },
    ] : []),
  };
}

function listPayload(items = [listingTask]) {
  return {
    items,
    total: items.length,
    page: 1,
    page_size: 10,
    refreshed_at: "2026-07-15T12:00:00Z",
  };
}

function isDetailRequest(url) {
  return /\/crawl-jobs\/tasks\/[^?]+/.test(String(url));
}

function detailId(url) {
  return decodeURIComponent(String(url).split("/crawl-jobs/tasks/")[1]);
}

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.clearAllMocks();
  window.history.replaceState(null, "", "#crawl-tasks");
});

beforeEach(() => {
  window.history.replaceState(null, "", "#crawl-tasks");
  apiFetchJson.mockImplementation(async (url) => {
    if (isDetailRequest(url)) {
      return normalizedTaskDetail({ id: detailId(url) });
    }
    return listPayload();
  });
});

describe("CrawlTasksPage list projections", () => {
  it("uses a one-minute refresh interval and keeps manual refresh", async () => {
    expect(AUTO_REFRESH_MS).toBe(60_000);
    const setIntervalSpy = vi.spyOn(window, "setInterval");
    render(<CrawlTasksPage />);

    const refreshButton = await screen.findByRole("button", { name: "Refresh" });
    expect(setIntervalSpy).toHaveBeenCalledWith(expect.any(Function), AUTO_REFRESH_MS);
    await userEvent.setup().click(refreshButton);
    await waitFor(() => {
      const listRequests = apiFetchJson.mock.calls.filter(([url]) =>
        `${url}`.includes("/crawl-jobs/tasks?"),
      );
      expect(listRequests).toHaveLength(2);
    });
  });

  it("shows raw IDs only when the list snapshot contains the optional field", async () => {
    const { unmount } = render(<CrawlTasksPage />);
    expect(await screen.findByText("Raw IDs 96")).toBeInTheDocument();
    unmount();

    apiFetchJson.mockImplementation(async (url) => {
      if (isDetailRequest(url)) return normalizedTaskDetail({ id: detailId(url) });
      return listPayload([{ ...listingTask, raw_job_ids_collected: null }]);
    });
    render(<CrawlTasksPage />);
    await screen.findByTestId("crawl-task-row-listing-task");
    expect(screen.queryByText(/Raw IDs/)).not.toBeInTheDocument();
  });

  it("keeps list metrics while rendering normalized detail data separately", async () => {
    const task = {
      ...listingTask,
      crawl_job_id: "detail-task",
      crawl_phase: "detail",
      phase: 2,
      detail_target_count: 4,
      detail_fetched_count: 3,
      detail_saved_count: 2,
      detail_failed_count: 1,
      detail_remaining_count: 0,
      detail_unavailable_count: 1,
      detail_manual_action_count: 1,
    };
    apiFetchJson.mockImplementation(async (url) => {
      if (isDetailRequest(url)) {
        return normalizedTaskDetail({ id: "detail-task", phase: "detail" });
      }
      return listPayload([task]);
    });
    render(<CrawlTasksPage />);

    expect(await screen.findByText("Detail targets 4")).toBeInTheDocument();
    expect(screen.getByText("Manual action 1")).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Immutable detail pacing" })).toBeInTheDocument();
    expect(screen.getByText(/1–3 seconds · 20 attempts · 30 seconds pause/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Finite detail snapshot" })).toBeInTheDocument();
  });

  it("renders observed zero values for common detail list metrics", async () => {
    const task = {
      ...listingTask,
      crawl_job_id: "zero-detail-task",
      source_site: "ctgoodjobs",
      crawl_mode: "headed",
      crawl_phase: "detail",
      detail_target_count: 0,
      detail_fetched_count: 0,
      detail_saved_count: 0,
      detail_failed_count: 0,
      detail_remaining_count: 0,
    };
    apiFetchJson.mockImplementation(async (url) => {
      if (isDetailRequest(url)) return normalizedTaskDetail({ id: "zero-detail-task", phase: "detail", sourceSite: "ctgoodjobs" });
      return listPayload([task]);
    });
    render(<CrawlTasksPage />);

    expect(await screen.findByText("Detail targets 0")).toBeInTheDocument();
    expect(screen.getByText("Fetched 0")).toBeInTheDocument();
    expect(screen.getByText("Saved 0")).toBeInTheDocument();
    expect(screen.getByText("Failed 0")).toBeInTheDocument();
    expect(screen.getByText("Remaining 0")).toBeInTheDocument();
  });

  it("separates an OfferToday segment from the remaining global backlog", async () => {
    const task = {
      ...listingTask,
      crawl_job_id: "offertoday-detail-task",
      status: "running",
      source_site: "offertoday",
      crawl_phase: "detail",
      detail_scope: "global",
      detail_segment_index: 2,
      detail_segment_target_rows: 5000,
      detail_backlog_remaining: 7431,
      detail_backlog_failed: 20,
      detail_backlog_manual_action_required: 11,
      detail_continuation_state: "continuing",
    };
    apiFetchJson.mockImplementation(async (url) => {
      if (isDetailRequest(url)) return normalizedTaskDetail({ id: task.crawl_job_id, phase: "detail", sourceSite: "offertoday" });
      return listPayload([task]);
    });
    render(<CrawlTasksPage />);

    expect(await screen.findByText("Segment 2 targets 5,000")).toBeInTheDocument();
    expect(screen.getByText("Backlog remaining 7,431")).toBeInTheDocument();
    expect(screen.getByText("Backlog failed 20")).toBeInTheDocument();
    expect(screen.getByText("Manual review 11")).toBeInTheDocument();
  });

  it("distinguishes a completed partial listing from a complete crawl", async () => {
    const task = {
      ...listingTask,
      crawl_job_id: "partial-listing-task",
      status: "completed",
      source_site: "offertoday",
      listing_completed: true,
      listing_partial: true,
      listing_condition_count: 23,
      listing_capped_condition_count: 5,
      listing_workload: {
        query_target_count: 23,
        page_depth: 40,
        estimated_max_pages: 920,
        run_page_cap: 1000,
        pages_requested: 408,
      },
    };
    apiFetchJson.mockImplementation(async (url) => {
      if (isDetailRequest(url)) return normalizedTaskDetail({ id: task.crawl_job_id, status: "completed", sourceSite: "offertoday" });
      return listPayload([task]);
    });
    render(<CrawlTasksPage />);

    expect(await screen.findByText("Completed with partial listing")).toBeInTheDocument();
    expect(screen.getByText("5 of 23 query targets reached the page-depth limit.")).toBeInTheDocument();
    expect(screen.getByText("Pages requested 408/920")).toBeInTheDocument();
    expect(screen.getByText("Run page cap 1,000")).toBeInTheDocument();
    expect(screen.queryByText("Listing Complete")).not.toBeInTheDocument();
  });

  it("keeps cancelled partial listings labelled by their terminal status", async () => {
    const task = {
      ...listingTask,
      crawl_job_id: "cancelled-partial-listing-task",
      status: "cancelled",
      listing_completed: false,
      listing_partial: true,
      listing_condition_count: 23,
      listing_capped_condition_count: 5,
    };
    apiFetchJson.mockImplementation(async (url) => {
      if (!isDetailRequest(url)) return listPayload([task]);
      const detail = normalizedTaskDetail({
        id: task.crawl_job_id,
        status: "cancelled",
        sourceSite: "offertoday",
        actions: [],
      });
      detail.listing_recovery = {
        version: 1,
        listing_partial: true,
        query_target_count: 23,
        capped_query_target_count: 5,
        page_depth: 40,
        pages_requested: 408,
        capped_classification_ids: ["offertoday:100001"],
        continuation_supported: false,
      };
      return detail;
    });
    render(<CrawlTasksPage />);

    expect(await screen.findByText("cancelled")).toBeInTheDocument();
    expect(screen.queryByText("Completed with partial listing")).not.toBeInTheDocument();
    expect(screen.queryByText(/reached the page-depth limit/)).not.toBeInTheDocument();
  });
});

describe("CrawlTasksPage normalized Task Details", () => {
  it("loads a deep-linked task directly even when it is absent from the list", async () => {
    window.history.replaceState(null, "", "#crawl-tasks?task=deep%2Flink%20task");
    apiFetchJson.mockImplementation(async (url) => {
      if (isDetailRequest(url)) return normalizedTaskDetail({ id: "deep/link task" });
      return listPayload([]);
    });
    render(<CrawlTasksPage />);

    expect(await screen.findByText("deep/link task")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Task Details" })).toBeInTheDocument();
    expect(apiFetchJson).toHaveBeenCalledWith(
      "/api/v1/crawl-jobs/tasks/deep%2Flink%20task",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
  });

  it("shows a structured error for an unknown deep-linked task", async () => {
    window.history.replaceState(null, "", "#crawl-tasks?task=missing-task");
    apiFetchJson.mockImplementation(async (url) => {
      if (isDetailRequest(url)) throw new Error("Task not found");
      return listPayload([]);
    });
    render(<CrawlTasksPage />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Task not found");
  });

  it("renders only safe normalized issue and manual-action guidance", async () => {
    apiFetchJson.mockImplementation(async (url) => {
      if (!isDetailRequest(url)) return listPayload();
      const detail = normalizedTaskDetail({
        id: "listing-task",
        status: "manual_action_required",
        actions: [{ action: "resume_manual_action", enabled: true, reason_code: null }],
      });
      detail.issue = {
        issue_class: "source_access",
        code: "HUMAN_VERIFICATION_REQUIRED",
        stage: "listing",
        summary: "Source verification is required.",
      };
      detail.manual_action_guidance = {
        message: "Open the source in the managed browser, then resume.",
        instructions: ["Complete the verification challenge."],
      };
      return detail;
    });
    render(<CrawlTasksPage />);

    const issueSection = (await screen.findByRole("heading", { name: "Issue" })).closest("section");
    expect(issueSection).toHaveTextContent("Source verification is required.");
    expect(screen.getByText("Complete the verification challenge.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Resume manual action" })).toBeEnabled();
    expect(screen.queryByText(/request_payload|manual_action\s*:/i)).not.toBeInTheDocument();
  });

  it("refreshes the list and normalized details after explicit recovery", async () => {
    const user = userEvent.setup();
    const recoveryDetail = normalizedTaskDetail({
      id: "listing-task",
      status: "manual_action_required",
      actions: [],
    });
    recoveryDetail.manual_action_guidance = {
      source_site: "jobsdb",
      message: "Complete the challenge, then resume.",
      instructions: ["Complete the challenge."],
      resume_supported: true,
      resume_strategies: ["fresh_profile"],
    };
    apiFetchJson.mockImplementation(async (url, options = {}) => {
      if (isDetailRequest(url)) return recoveryDetail;
      if (`${url}`.endsWith("/crawl-jobs/listing-task/resume")) {
        expect(options.method).toBe("POST");
        return { status: "queued" };
      }
      return listPayload();
    });
    render(<CrawlTasksPage />);

    const resumeButton = await screen.findByRole("button", {
      name: "Resume with Fresh Profile",
    });
    const detailRequestsBefore = apiFetchJson.mock.calls.filter(([url]) =>
      isDetailRequest(url),
    ).length;
    const listRequestsBefore = apiFetchJson.mock.calls.filter(([url]) =>
      `${url}`.includes("/crawl-jobs/tasks?"),
    ).length;

    await user.click(resumeButton);

    await waitFor(() => {
      expect(
        apiFetchJson.mock.calls.filter(([url]) => isDetailRequest(url)).length,
      ).toBeGreaterThan(detailRequestsBefore);
      expect(
        apiFetchJson.mock.calls.filter(([url]) =>
          `${url}`.includes("/crawl-jobs/tasks?"),
        ).length,
      ).toBeGreaterThan(listRequestsBefore);
    });
  });

  it("shows the fail-closed Reset diagnostic when profile liveness is unknown", async () => {
    apiFetchJson.mockImplementation(async (url) => {
      if (!isDetailRequest(url)) return listPayload();
      const detail = normalizedTaskDetail({
        id: "listing-task",
        status: "manual_action_required",
        actions: [],
      });
      detail.manual_action_guidance = {
        source_site: "jobsdb",
        stage: "browser_profile_in_use",
        message: "The worker profile needs operator review.",
        resume_supported: true,
        resume_strategies: ["fresh_profile"],
        reset_supported: false,
        reset_reason: "browser_session_reachability_unknown",
      };
      return detail;
    });
    render(<CrawlTasksPage />);

    expect(await screen.findByTestId("crawl-task-reset-unavailable")).toHaveTextContent(
      "Browser profile reset is unavailable: browser session reachability unknown.",
    );
    expect(screen.queryByRole("button", { name: "Reset Browser Profile" })).not.toBeInTheDocument();
  });

  it("offers a reviewed one-off run for capped Query Targets", async () => {
    const user = userEvent.setup();
    apiFetchJson.mockImplementation(async (url) => {
      if (!isDetailRequest(url)) {
        return listPayload([{ ...listingTask, status: "completed", listing_completed: true, listing_partial: true }]);
      }
      const detail = normalizedTaskDetail({ id: "listing-task", status: "completed", sourceSite: "offertoday" });
      detail.listing_recovery = {
        version: 1,
        listing_partial: true,
        query_target_count: 23,
        capped_query_target_count: 5,
        page_depth: 40,
        pages_requested: 408,
        capped_classification_ids: ["offertoday:100001", "offertoday:100002"],
        continuation_supported: true,
      };
      return detail;
    });
    render(<CrawlTasksPage />);

    const continueButton = await screen.findByRole("button", { name: "Continue capped query targets" });
    await user.click(continueButton);

    expect(window.location.hash).toMatch(/^#scheduler\/one-off\/new\?/);
    const draftKey = Object.keys(window.sessionStorage).find((key) => key.startsWith(DRAFT_PREFIX));
    expect(draftKey).toBeTruthy();
    const draft = JSON.parse(window.sessionStorage.getItem(draftKey));
    expect(draft).toMatchObject({
      intent: "listing",
      scope: { mode: "rules" },
      execution: { page_depth: 40, run_page_cap: 200 },
    });
    expect(draft.scope.rules).toEqual([
      { kind: "exact", classification_id: "offertoday:100001" },
      { kind: "exact", classification_id: "offertoday:100002" },
    ]);
  });

  it("uses an accessible cancellation dialog and restores focus", async () => {
    const user = userEvent.setup();
    render(<CrawlTasksPage />);
    const cancelButton = await screen.findByRole("button", { name: "Cancel Crawl Job" });

    await user.click(cancelButton);
    const dialog = screen.getByRole("dialog", { name: "Cancel this crawl?" });
    expect(dialog).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(cancelButton).toHaveFocus();

    await user.click(cancelButton);
    await user.click(screen.getByRole("button", { name: "Request cancellation" }));
    await waitFor(() => {
      expect(apiFetchJson.mock.calls.some(([url, options]) =>
        `${url}`.endsWith("/crawl-jobs/listing-task/cancel") && options?.method === "POST",
      )).toBe(true);
    });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("polls cancelling details every second and cleans the interval on unmount", async () => {
    window.history.replaceState(null, "", "#crawl-tasks?task=cancelling-task");
    const setIntervalSpy = vi.spyOn(window, "setInterval");
    const clearIntervalSpy = vi.spyOn(window, "clearInterval");
    apiFetchJson.mockImplementation(async (url) => {
      if (isDetailRequest(url)) return normalizedTaskDetail({ id: "cancelling-task", status: "cancelling" });
      return listPayload([]);
    });
    const { unmount } = render(<CrawlTasksPage />);

    expect(await screen.findByText(/Waiting for backend/)).toBeInTheDocument();
    await waitFor(() => {
      expect(setIntervalSpy).toHaveBeenCalledWith(expect.any(Function), CANCELLATION_REFRESH_MS);
    });
    const cancellationInterval = setIntervalSpy.mock.results.find((result, index) =>
      setIntervalSpy.mock.calls[index][1] === CANCELLATION_REFRESH_MS && result.value,
    )?.value;
    unmount();
    expect(clearIntervalSpy).toHaveBeenCalledWith(cancellationInterval);
  });
});
