import { describe, expect, it } from "vitest";

import { deriveLatestRecoveryAttempt } from "./recoveryAttemptUtils";

describe("deriveLatestRecoveryAttempt", () => {
  it("returns no attempt when the task has never been resumed", () => {
    expect(
      deriveLatestRecoveryAttempt([
        { sequence_no: 1, event_type: "crawl.requested", payload: {} },
      ]),
    ).toBeNull();
  });

  it("reports the latest accepted resume while no later outcome exists", () => {
    expect(
      deriveLatestRecoveryAttempt([
        {
          sequence_no: 8,
          event_type: "crawl.resume_requested",
          created_at: "2026-07-16T00:35:00Z",
          payload: { strategy: "reuse_open_browser" },
        },
        { sequence_no: 9, event_type: "crawl.requested", payload: {} },
      ]),
    ).toEqual({
      status: "pending",
      sequenceNo: 8,
      strategy: "reuse_open_browser",
      requestedAt: "2026-07-16T00:35:00Z",
    });
  });

  it("shows the manual-action reason that resolved the latest attempt", () => {
    expect(
      deriveLatestRecoveryAttempt([
        {
          sequence_no: 8,
          event_type: "crawl.resume_requested",
          created_at: "2026-07-16T00:35:00Z",
          payload: { strategy: "reuse_open_browser" },
        },
        {
          sequence_no: 11,
          event_type: "crawl.manual_action_required",
          created_at: "2026-07-16T00:35:03Z",
          payload: {
            manual_action: {
              stage: "reuse_open_browser_unavailable",
              classification: "human_verification",
              message: "The reusable browser session is unavailable.",
            },
          },
        },
      ]),
    ).toEqual({
      status: "manual_action_required",
      sequenceNo: 8,
      strategy: "reuse_open_browser",
      requestedAt: "2026-07-16T00:35:00Z",
      outcomeSequenceNo: 11,
      outcomeAt: "2026-07-16T00:35:03Z",
      stage: "reuse_open_browser_unavailable",
      classification: "human_verification",
      message: "The reusable browser session is unavailable.",
    });
  });

  it("ignores an older failed attempt when a newer resume is pending", () => {
    expect(
      deriveLatestRecoveryAttempt([
        {
          sequence_no: 8,
          event_type: "crawl.resume_requested",
          payload: { strategy: "fresh_profile" },
        },
        {
          sequence_no: 11,
          event_type: "crawl.manual_action_required",
          payload: { manual_action: { stage: "browser_profile_in_use" } },
        },
        {
          sequence_no: 12,
          event_type: "crawl.resume_requested",
          created_at: "2026-07-16T00:35:31Z",
          payload: { strategy: "reuse_open_browser" },
        },
      ]),
    ).toEqual({
      status: "pending",
      sequenceNo: 12,
      strategy: "reuse_open_browser",
      requestedAt: "2026-07-16T00:35:31Z",
    });
  });
});
