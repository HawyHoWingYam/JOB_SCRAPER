/** @vitest-environment jsdom */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import userEvent from "@testing-library/user-event";
import { apiFetchJson } from "../../api/client";
import CrawlTasksPage, { AUTO_REFRESH_MS } from "./CrawlTasksPage";

vi.mock("../../api/client", () => ({
  apiFetchJson: vi.fn(),
}));

const listingTask = {
  crawl_job_id: "listing-task",
  status: "running",
  source_site: "jobsdb",
  crawl_mode: "headless",
  phase: 1,
  job_ids_collected: 87,
  raw_job_ids_collected: 96,
  listings_staged: 87,
  detail_target_rows: 87,
  current_page: 2,
  total_pages: 10,
  updated_at: "2026-07-15T12:00:00Z",
};

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.clearAllMocks();
});
beforeEach(() => {
  Object.defineProperty(window.navigator, "clipboard", {
    configurable: true,
    value: { writeText: vi.fn().mockResolvedValue(undefined) },
  });
  apiFetchJson.mockImplementation(async (url) => {
    if (`${url}`.includes("/capabilities")) {
      return {
        manual_actions: {
          helper_url: "http://127.0.0.1:47652",
          health_url: "http://127.0.0.1:47652/health",
          manual_start_workdir: "backend",
          manual_start_command:
            "python -m app.workers.run_manual_action_helper",
        },
      };
    }
    if (`${url}`.includes("/health")) {
      return { status: "ok" };
    }
    return {
      items: [listingTask],
      total: 1,
      page: 1,
      page_size: 10,
      refreshed_at: "2026-07-15T12:00:00Z",
    };
  });
});

describe("CrawlTasksPage metric summaries", () => {
  it("uses a one-minute refresh interval and keeps the manual refresh action", async () => {
    expect(AUTO_REFRESH_MS).toBe(60_000);
    const setIntervalSpy = vi.spyOn(window, "setInterval");

    render(<CrawlTasksPage />);

    const refreshButton = await screen.findByRole("button", {
      name: "Refresh",
    });
    expect(refreshButton).toBeInTheDocument();
    expect(setIntervalSpy).toHaveBeenCalledWith(
      expect.any(Function),
      AUTO_REFRESH_MS,
    );

    await userEvent.setup().click(refreshButton);
    await waitFor(() => {
      const taskRequests = apiFetchJson.mock.calls.filter(([url]) =>
        `${url}`.includes("/crawl-jobs/tasks"),
      );
      expect(taskRequests).toHaveLength(2);
    });

    setIntervalSpy.mockRestore();
  });

  it("shows raw IDs only when the snapshot contains the optional field", async () => {
    render(<CrawlTasksPage />);
    expect(await screen.findByText("Raw IDs 96")).toBeInTheDocument();

    cleanup();
    apiFetchJson.mockResolvedValueOnce({
      items: [{ ...listingTask, raw_job_ids_collected: null }],
      total: 1,
      page: 1,
      page_size: 10,
    });
    render(<CrawlTasksPage />);
    await screen.findByTestId("crawl-task-row-listing-task");
    expect(screen.queryByText("Raw IDs 0")).not.toBeInTheDocument();
    expect(screen.queryByText("Raw IDs 96")).not.toBeInTheDocument();
  });

  it("uses the detail layout for detail snapshots and legacy numeric phase", async () => {
    apiFetchJson.mockResolvedValueOnce({
      items: [
        {
          crawl_job_id: "detail-task",
          status: "running",
          source_site: "jobsdb",
          crawl_mode: "headless",
          phase: 2,
          detail_target_count: 4,
          detail_fetched_count: 3,
          detail_saved_count: 2,
          detail_failed_count: 1,
          detail_remaining_count: 0,
          detail_unavailable_count: 1,
          detail_manual_action_count: 1,
          updated_at: "2026-07-15T12:00:00Z",
        },
      ],
      total: 1,
      page: 1,
      page_size: 10,
    });
    render(<CrawlTasksPage />);

    expect(await screen.findByText("Detail targets 4")).toBeInTheDocument();
    expect(screen.getByText("Fetched 3")).toBeInTheDocument();
    expect(screen.getByText("Saved 2")).toBeInTheDocument();
    expect(screen.getByText("Failed 1")).toBeInTheDocument();
    expect(screen.getByText("Remaining 0")).toBeInTheDocument();
    expect(screen.getByText("Unavailable 1")).toBeInTheDocument();
    expect(screen.getByText("Manual action 1")).toBeInTheDocument();
    expect(screen.getByTestId("crawl-task-detail-metrics")).toHaveTextContent(
      "Detail targets 4 | Fetched 3 | Saved 2 | Failed 1 | Remaining 0 | Unavailable 1 | Manual action 1",
    );
  });

  it("renders observed zero values for every common detail metric", async () => {
    apiFetchJson.mockResolvedValueOnce({
      items: [
        {
          crawl_job_id: "zero-detail-task",
          status: "running",
          source_site: "ctgoodjobs",
          crawl_mode: "headed",
          request_payload: { crawl_phase: "detail" },
          detail_target_count: 0,
          detail_fetched_count: 0,
          detail_saved_count: 0,
          detail_failed_count: 0,
          detail_remaining_count: 0,
          detail_unavailable_count: 0,
          detail_manual_action_count: 0,
          updated_at: "2026-07-15T12:00:00Z",
        },
      ],
      total: 1,
      page: 1,
      page_size: 10,
    });
    render(<CrawlTasksPage />);

    expect(await screen.findByText("Detail targets 0")).toBeInTheDocument();
    expect(screen.getByText("Fetched 0")).toBeInTheDocument();
    expect(screen.getByText("Saved 0")).toBeInTheDocument();
    expect(screen.getByText("Failed 0")).toBeInTheDocument();
    expect(screen.getByText("Remaining 0")).toBeInTheDocument();
  });

  it("separates an OfferToday segment from the remaining global backlog", async () => {
    const detailTask = {
      crawl_job_id: "offertoday-detail-task",
      status: "running",
      source_site: "offertoday",
      crawl_mode: "headless",
      phase: 2,
      request_payload: { crawl_phase: "detail", detail_scope: "global" },
      detail_scope: "global",
      detail_target_rows: 5000,
      detail_segment_index: 2,
      detail_segments_completed: 1,
      detail_segment_target_rows: 5000,
      detail_backlog_remaining: 7431,
      detail_backlog_failed: 20,
      detail_backlog_manual_action_required: 11,
      detail_continuation_state: "continuing",
      updated_at: "2026-07-15T12:00:00Z",
    };
    apiFetchJson.mockImplementation(async (url) => {
      if (`${url}`.includes("/capabilities")) {
        return { manual_actions: {} };
      }
      return {
        items: [detailTask],
        total: 1,
        page: 1,
        page_size: 10,
      };
    });

    render(<CrawlTasksPage />);

    expect(
      await screen.findAllByText("Job Detail Crawl · Global backlog"),
    ).not.toHaveLength(0);
    expect(screen.getByText("Segment 2 targets 5,000")).toBeInTheDocument();
    expect(screen.getByText("Backlog remaining 7,431")).toBeInTheDocument();
    expect(screen.getByText("Backlog failed 20")).toBeInTheDocument();
    expect(screen.getByText("Manual review 11")).toBeInTheDocument();
  });
});

describe("CrawlTasksPage manual-action helper health", () => {
  it("guides helper recovery without automatically opening a browser or resuming", async () => {
    let helperOnline = false;
    let browserConnected = false;
    const manualTask = {
      crawl_job_id: "offertoday-manual-task",
      status: "manual_action_required",
      source_site: "offertoday",
      crawl_mode: "headed",
      request_payload: { crawl_phase: "detail" },
      manual_action: {
        resume_supported: true,
        reuse_open_browser_supported: true,
        classification: "ip_blocked",
      },
      updated_at: "2026-07-15T12:00:00Z",
    };
    apiFetchJson.mockImplementation(async (url) => {
      if (`${url}`.includes("/capabilities")) {
        return {
          manual_actions: {
            helper_url: "http://127.0.0.1:47652",
            health_url: "http://127.0.0.1:47652/health",
            manual_start_workdir: "backend",
            manual_start_command:
              "python -m app.workers.run_manual_action_helper",
          },
        };
      }
      if (`${url}`.includes("/health")) {
        if (!helperOnline) {
          throw new TypeError("Failed to fetch");
        }
        return { status: "ok" };
      }
      if (`${url}`.includes("/manual-actions/open-browser")) {
        browserConnected = true;
        return { status: "live", debug_port: 9222 };
      }
      if (`${url}`.includes("/manual-actions/reuse-status")) {
        return browserConnected
          ? { available: true, status: "live" }
          : { available: false, reason: "live_browser_not_found" };
      }
      if (`${url}`.includes("/resume")) {
        return { status: "dispatching" };
      }
      return {
        items: [manualTask],
        total: 1,
        page: 1,
        page_size: 10,
      };
    });

    render(<CrawlTasksPage />);

    expect(
      await screen.findByText("Host helper is offline"),
    ).toBeInTheDocument();
    expect(screen.getByTestId("crawl-task-copy-helper-command")).toBeEnabled();
    expect(screen.getByTestId("crawl-task-resume-fresh")).toBeEnabled();
    expect(
      screen.getByText(/does not reuse the open browser/i),
    ).toBeInTheDocument();

    const advanced = screen
      .getByText("Advanced troubleshooting")
      .closest("details");
    expect(advanced).not.toHaveAttribute("open");

    vi.useFakeTimers();
    await act(async () => {
      fireEvent.click(screen.getByTestId("crawl-task-copy-helper-command"));
      await Promise.resolve();
    });
    expect(window.navigator.clipboard.writeText).toHaveBeenCalledWith(
      "Set-Location 'backend'; python -m app.workers.run_manual_action_helper",
    );

    helperOnline = true;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2_000);
    });
    vi.useRealTimers();

    expect(screen.getByTestId("crawl-task-open-browser")).toBeEnabled();
    expect(
      apiFetchJson.mock.calls.some(([url]) =>
        `${url}`.includes("/open-browser"),
      ),
    ).toBe(false);
    expect(
      apiFetchJson.mock.calls.some(([url]) => `${url}`.includes("/resume")),
    ).toBe(false);

    const user = userEvent.setup();
    await user.click(screen.getByTestId("crawl-task-open-browser"));
    await act(async () => {});
    expect(
      screen.getByText("Browser connected — site access is not verified"),
    ).toBeInTheDocument();
    expect(
      apiFetchJson.mock.calls.some(([url]) => `${url}`.includes("/resume")),
    ).toBe(false);

    await user.click(screen.getByTestId("crawl-task-resume-open-browser"));
    await act(async () => {});
    const resumeRequest = apiFetchJson.mock.calls.find(([url]) =>
      `${url}`.includes("/resume"),
    );
    expect(resumeRequest?.[1]?.body).toBe(
      JSON.stringify({ strategy: "reuse_open_browser" }),
    );
  });

  it("keeps a simpler fresh-profile path for manual actions without browser reuse", async () => {
    const manualTask = {
      crawl_job_id: "jobsdb-manual-task",
      status: "manual_action_required",
      source_site: "jobsdb",
      crawl_mode: "headed",
      manual_action: {
        resume_supported: true,
        reuse_open_browser_supported: false,
        instructions: "Review the source page before resuming.",
      },
      updated_at: "2026-07-15T12:00:00Z",
    };
    apiFetchJson.mockImplementation(async (url) => {
      if (`${url}`.includes("/capabilities")) {
        return { manual_actions: {} };
      }
      return { items: [manualTask], total: 1, page: 1, page_size: 10 };
    });

    render(<CrawlTasksPage />);

    expect(
      await screen.findByText("Operator review required"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Review the source page before resuming."),
    ).toBeInTheDocument();
    expect(screen.getByTestId("crawl-task-resume-fresh")).toBeEnabled();
    expect(
      screen.queryByTestId("crawl-task-copy-helper-command"),
    ).not.toBeInTheDocument();
    expect(
      apiFetchJson.mock.calls.some(([url]) => `${url}`.includes("/health")),
    ).toBe(false);
  });

  it("confirms profile cleanup and crawl cancellation before sending either request", async () => {
    const manualTask = {
      crawl_job_id: "offertoday-confirm-task",
      status: "manual_action_required",
      source_site: "offertoday",
      crawl_mode: "headed",
      manual_action: {
        resume_supported: true,
        reuse_open_browser_supported: true,
      },
      updated_at: "2026-07-15T12:00:00Z",
    };
    apiFetchJson.mockImplementation(async (url) => {
      if (`${url}`.includes("/capabilities")) {
        return { manual_actions: {} };
      }
      if (`${url}`.includes("/health")) {
        return { status: "ok" };
      }
      if (`${url}`.includes("/manual-actions/reuse-status")) {
        return { available: true, status: "live" };
      }
      if (
        `${url}`.includes("/close-profile-windows") ||
        `${url}`.includes("/cancel")
      ) {
        return { status: "ok" };
      }
      return { items: [manualTask], total: 1, page: 1, page_size: 10 };
    });
    const confirmSpy = vi
      .spyOn(window, "confirm")
      .mockReturnValueOnce(false)
      .mockReturnValueOnce(true)
      .mockReturnValueOnce(false)
      .mockReturnValueOnce(true);
    const user = userEvent.setup();

    render(<CrawlTasksPage />);
    expect(
      await screen.findByText(
        "Browser connected — site access is not verified",
      ),
    ).toBeInTheDocument();
    await user.click(screen.getByText("Advanced troubleshooting"));

    const closeButton = screen.getByTestId("crawl-task-close-profile-windows");
    await user.click(closeButton);
    expect(
      apiFetchJson.mock.calls.some(([url]) =>
        `${url}`.includes("/close-profile-windows"),
      ),
    ).toBe(false);
    await user.click(closeButton);
    await waitFor(() => {
      expect(
        apiFetchJson.mock.calls.some(([url]) =>
          `${url}`.includes("/close-profile-windows"),
        ),
      ).toBe(true);
    });

    const cancelButton = screen.getByTestId("crawl-task-cancel");
    await user.click(cancelButton);
    expect(
      apiFetchJson.mock.calls.some(([url]) => `${url}`.includes("/cancel")),
    ).toBe(false);
    await user.click(cancelButton);
    await waitFor(() => {
      expect(
        apiFetchJson.mock.calls.some(([url]) => `${url}`.includes("/cancel")),
      ).toBe(true);
    });

    expect(confirmSpy).toHaveBeenNthCalledWith(
      1,
      expect.stringContaining(
        "Close the dedicated OfferToday browser profile windows",
      ),
    );
    expect(confirmSpy).toHaveBeenNthCalledWith(
      3,
      expect.stringContaining("Cancel crawl job offertoday-confirm-task"),
    );
  });
});
