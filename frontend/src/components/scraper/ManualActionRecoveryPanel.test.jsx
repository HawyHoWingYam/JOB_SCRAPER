/** @vitest-environment jsdom */

import React from "react";
import { act, cleanup, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ManualActionRecoveryPanel, { MANUAL_ACTION_POLL_MS } from "./ManualActionRecoveryPanel";
import {
  getManualActionHelperHealth,
  getManualActionReuseStatus,
} from "./crawlTaskActions";

vi.mock("./crawlTaskActions", () => ({
  closeManualActionWindows: vi.fn(),
  DEFAULT_MANUAL_ACTION_HELPER_START_COMMAND: "python3 helper",
  DEFAULT_MANUAL_ACTION_HELPER_START_WORKDIR: "backend",
  DEFAULT_MANUAL_ACTION_HELPER_URL: "http://127.0.0.1:47652",
  getManualActionHelperHealth: vi.fn(),
  getManualActionReuseStatus: vi.fn(),
  openManualActionBrowser: vi.fn(),
  resetBrowserProfile: vi.fn(),
  resumeCrawlJob: vi.fn(),
}));

const task = {
  crawl_job_id: "jobsdb-manual-task",
  source_site: "jobsdb",
  manual_action: {
    source_site: "jobsdb",
    resume_supported: true,
    reuse_open_browser_supported: true,
    reset_supported: false,
    resume_strategies: ["fresh_profile", "reuse_open_browser"],
  },
};

const capability = {
  helper_url: "http://127.0.0.1:47652",
  health_url: "http://127.0.0.1:47652/health",
  manual_start_workdir: "backend",
  manual_start_command: "python3 helper",
};

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.clearAllMocks();
});

beforeEach(() => {
  vi.useFakeTimers();
  let healthChecks = 0;
  getManualActionHelperHealth.mockImplementation(async () => {
    healthChecks += 1;
    return healthChecks === 1
      ? { available: false, reason: "helper_unreachable" }
      : { available: true };
  });
  getManualActionReuseStatus.mockResolvedValue({
    available: false,
    reason: "no_live_browser",
  });
});

describe("ManualActionRecoveryPanel helper health", () => {
  it("detects a helper started after the initial offline probe without copying again", async () => {
    render(
      <ManualActionRecoveryPanel
        task={task}
        capability={capability}
        onTaskChanged={vi.fn()}
        recoveryAttempt={null}
        recoveryAttemptError={null}
      />,
    );

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.getByText("Host helper is offline")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Open Verification Browser" }),
    ).not.toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(MANUAL_ACTION_POLL_MS);
    });

    expect(
      screen.getByText("Helper online — open the verification browser"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Open Verification Browser" }),
    ).toBeInTheDocument();
  });
});
