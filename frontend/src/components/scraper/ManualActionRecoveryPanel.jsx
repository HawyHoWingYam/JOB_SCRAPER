import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  Check,
  Clipboard,
  MonitorPlay,
  RefreshCcw,
  RotateCcw,
  Unplug,
} from "lucide-react";
import { formatScraperSourceLabel } from "./listingBatchLabel";
import {
  closeManualActionWindows,
  DEFAULT_MANUAL_ACTION_HELPER_START_COMMAND,
  DEFAULT_MANUAL_ACTION_HELPER_START_WORKDIR,
  DEFAULT_MANUAL_ACTION_HELPER_URL,
  getManualActionHelperHealth,
  getManualActionReuseStatus,
  openManualActionBrowser,
  resetBrowserProfile,
  resumeCrawlJob,
} from "./crawlTaskActions";

export const MANUAL_ACTION_POLL_MS = 2_000;

function extractErrorMessage(error, fallbackMessage) {
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return fallbackMessage;
}

function buildHelperStartCommand(workdir, command) {
  const escapedWorkdir = `${workdir}`.replace(/"/g, '\\"');
  return `cd "${escapedWorkdir}"; ${command}`;
}

function formatManualActionInstructions(value) {
  if (Array.isArray(value)) {
    return value
      .map((item) => `${item}`.trim())
      .filter(Boolean)
      .join(" ");
  }
  return `${value || ""}`.trim();
}

function formatRecoveryTimestamp(value) {
  if (!value) {
    return "time unavailable";
  }
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime())
    ? `${value}`
    : parsed.toLocaleString("en-US");
}

function RecoveryStep({ label, state, current }) {
  return (
    <div
      className={`manual-action-step state-${state}`}
      aria-current={current ? "step" : undefined}
    >
      <span className="manual-action-step-marker" aria-hidden="true">
        {state === "complete" ? <Check size={14} /> : null}
      </span>
      <span>{label}</span>
    </div>
  );
}

export default function ManualActionRecoveryPanel({
  task,
  capability,
  onTaskChanged,
  recoveryAttempt,
  recoveryAttemptError,
}) {
  const resumeSupported = task?.manual_action?.resume_supported === true;
  const reuseSupported =
    resumeSupported &&
    task?.manual_action?.reuse_open_browser_supported === true;
  const resetSupported =
    task?.manual_action?.reset_supported === true;
  const resetReason = `${task?.manual_action?.reset_reason || ""}`.trim();
  const taskId = task?.crawl_job_id;
  const sourceLabel = formatScraperSourceLabel(
    task?.manual_action?.source_site || task?.source_site,
  );
  const helperUrl = capability?.helper_url || DEFAULT_MANUAL_ACTION_HELPER_URL;
  const helperHealthUrl = capability?.health_url || `${helperUrl}/health`;
  const helperStartWorkdir =
    capability?.manual_start_workdir ||
    DEFAULT_MANUAL_ACTION_HELPER_START_WORKDIR;
  const helperStartCommand =
    capability?.manual_start_command ||
    DEFAULT_MANUAL_ACTION_HELPER_START_COMMAND;
  const helperStartCommandWithDirectory = useMemo(
    () => buildHelperStartCommand(helperStartWorkdir, helperStartCommand),
    [helperStartCommand, helperStartWorkdir],
  );

  const [helperHealth, setHelperHealth] = useState({
    status: "checking",
    detail: null,
  });
  const [reuseState, setReuseState] = useState({
    status: "unknown",
    detail: null,
  });
  const [pollHelper, setPollHelper] = useState(false);
  const [pollReuse, setPollReuse] = useState(false);
  const [actionState, setActionState] = useState({
    pending: null,
    error: null,
    notice: null,
  });

  const checkHelperHealth = useCallback(
    async ({ showChecking = true } = {}) => {
      if (!reuseSupported) {
        return { available: false, reason: "reuse_not_supported" };
      }
      if (showChecking) {
        setHelperHealth({ status: "checking", detail: null });
      }
      const health = await getManualActionHelperHealth({
        helperUrl,
        healthUrl: helperHealthUrl,
      });
      setHelperHealth({
        status: health.available ? "online" : "offline",
        detail: health.available ? null : health.error || health.reason,
      });
      return health;
    },
    [helperHealthUrl, helperUrl, reuseSupported],
  );

  const checkReuseStatus = useCallback(
    async ({ surfaceError = true } = {}) => {
      if (!reuseSupported || !taskId) {
        return null;
      }

      setReuseState({ status: "checking", detail: null });
      try {
        const payload = await getManualActionReuseStatus(taskId, helperUrl);
        setReuseState({
          status: payload?.available === true ? "connected" : "disconnected",
          detail: payload?.available === true ? null : payload?.reason || null,
        });
        return payload;
      } catch (error) {
        const detail = extractErrorMessage(
          error,
          "Failed to check browser connection",
        );
        setHelperHealth({ status: "offline", detail });
        setReuseState({ status: "unknown", detail: null });
        if (surfaceError) {
          setActionState({ pending: null, error: detail, notice: null });
        }
        return null;
      }
    },
    [helperUrl, reuseSupported, taskId],
  );

  useEffect(() => {
    setPollHelper(false);
    setPollReuse(false);
    setActionState({ pending: null, error: null, notice: null });
    setReuseState({ status: "unknown", detail: null });

    if (!reuseSupported) {
      setHelperHealth({ status: "offline", detail: null });
      return;
    }
    void checkHelperHealth();
  }, [checkHelperHealth, reuseSupported, taskId]);

  useEffect(() => {
    if (!pollHelper || helperHealth.status === "online") {
      return undefined;
    }

    let cancelled = false;
    let timeoutId;

    async function pollLoop() {
      timeoutId = window.setTimeout(async () => {
        if (cancelled) {
          return;
        }
        const health = await checkHelperHealth({ showChecking: false });
        if (!cancelled && !health.available) {
          void pollLoop();
        }
      }, MANUAL_ACTION_POLL_MS);
    }

    void pollLoop();
    return () => {
      cancelled = true;
      window.clearTimeout(timeoutId);
    };
  }, [checkHelperHealth, helperHealth.status, pollHelper]);

  useEffect(() => {
    if (helperHealth.status !== "online" || !reuseSupported) {
      return;
    }
    setPollHelper(false);
    void checkReuseStatus({ surfaceError: false });
  }, [checkReuseStatus, helperHealth.status, reuseSupported]);

  useEffect(() => {
    if (
      !pollReuse ||
      helperHealth.status !== "online" ||
      reuseState.status === "connected"
    ) {
      return undefined;
    }

    let cancelled = false;
    let timeoutId;

    async function pollLoop() {
      timeoutId = window.setTimeout(async () => {
        if (cancelled) {
          return;
        }
        const payload = await checkReuseStatus({ surfaceError: false });
        if (!cancelled && payload?.available !== true) {
          void pollLoop();
        }
      }, MANUAL_ACTION_POLL_MS);
    }

    void pollLoop();
    return () => {
      cancelled = true;
      window.clearTimeout(timeoutId);
    };
  }, [checkReuseStatus, helperHealth.status, pollReuse, reuseState.status]);

  async function runAction(
    actionKey,
    actionLabel,
    action,
    { refreshTask = false } = {},
  ) {
    setActionState({ pending: actionKey, error: null, notice: null });
    try {
      const result = await action();
      setActionState({
        pending: null,
        error: null,
        notice: `${actionLabel} requested.`,
      });
      if (refreshTask) {
        await onTaskChanged?.(actionKey);
      }
      return { ok: true, result };
    } catch (error) {
      const detail = extractErrorMessage(
        error,
        `Failed to ${actionLabel.toLowerCase()}`,
      );
      setActionState({ pending: null, error: detail, notice: null });
      return { ok: false, result: null };
    }
  }

  async function handleCopyHelperCommand() {
    setActionState({ pending: "copy_helper", error: null, notice: null });
    try {
      if (!window.navigator?.clipboard?.writeText) {
        throw new Error(
          "Clipboard access is unavailable. Copy the command from Advanced troubleshooting.",
        );
      }
      await window.navigator.clipboard.writeText(helperStartCommandWithDirectory);
      setActionState({
        pending: null,
        error: null,
        notice:
          "Helper command copied. Paste it into a terminal; this page is checking for the helper.",
      });
      setPollHelper(true);
    } catch (error) {
      setActionState({
        pending: null,
        error: extractErrorMessage(error, "Failed to copy the helper command"),
        notice: null,
      });
    }
  }

  async function handleOpenBrowser() {
    const outcome = await runAction("open_browser", "Open browser", () =>
      openManualActionBrowser(taskId, helperUrl),
    );
    if (!outcome.ok) {
      setHelperHealth((current) => ({
        status: "offline",
        detail: current.detail || "Manual-action helper is unavailable",
      }));
      return;
    }
    setPollReuse(true);
    const payload = await checkReuseStatus();
    if (payload?.available === true) {
      setPollReuse(false);
    }
  }

  async function handleCloseProfileWindows() {
    const confirmed = window.confirm(
      `Close the dedicated ${sourceLabel} browser profile windows for crawl job ${taskId}?`,
    );
    if (!confirmed) {
      return;
    }
    const outcome = await runAction(
      "close_windows",
      "Close profile windows",
      () => closeManualActionWindows(taskId, helperUrl),
    );
    if (outcome.ok) {
      setPollReuse(false);
      setReuseState({
        status: "disconnected",
        detail: "profile_windows_closed",
      });
    }
  }

  async function handleResetProfile() {
    const confirmed = window.confirm(
      `Reset the safe ${sourceLabel} browser profile for crawl job ${taskId}? Completed crawl progress will be preserved.`,
    );
    if (!confirmed) {
      return;
    }
    const outcome = await runAction(
      "reset_profile",
      "Reset browser profile",
      () => resetBrowserProfile(taskId),
      { refreshTask: true },
    );
    if (outcome.ok) {
      setPollReuse(false);
      setReuseState({ status: "disconnected", detail: "profile_reset" });
    }
  }

  const primaryStep =
    helperHealth.status !== "online"
      ? "start_helper"
      : reuseState.status === "connected"
        ? "resume_with_open_browser"
        : "open_browser";
  const anyPending = actionState.pending !== null;
  const resumePending = `${actionState.pending || ""}`.startsWith("resume_");
  const recoveryOutcomePending = recoveryAttempt?.status === "pending";
  const resumeDisabled = anyPending || recoveryOutcomePending;
  const instructions = formatManualActionInstructions(
    task?.manual_action?.instructions,
  );
  const recoveryStrategy = `${recoveryAttempt?.strategy || "unknown"}`.replace(
    /_/g,
    " ",
  );
  const recoveryStage = `${recoveryAttempt?.stage || "unknown"}`.replace(
    /_/g,
    " ",
  );
  const recoveryClassification = `${
    recoveryAttempt?.classification || "unclassified"
  }`.replace(/_/g, " ");

  return (
    <section
      className="manual-action-recovery"
      data-testid="manual-action-recovery"
    >
      <div className="manual-action-recovery-heading">
        <div>
          <div className="manual-action-eyebrow">Manual recovery</div>
          <h3>Get this {sourceLabel} crawl moving again</h3>
        </div>
        {reuseSupported && (
          <div className="manual-action-steps" aria-label="Recovery progress">
            <RecoveryStep
              label="Helper"
              state={helperHealth.status === "online" ? "complete" : "active"}
              current={primaryStep === "start_helper"}
            />
            <RecoveryStep
              label="Browser"
              state={
                reuseState.status === "connected"
                  ? "complete"
                  : helperHealth.status === "online"
                    ? "active"
                    : "pending"
              }
              current={primaryStep === "open_browser"}
            />
            <RecoveryStep
              label="Resume"
              state={reuseState.status === "connected" ? "active" : "pending"}
              current={primaryStep === "resume_with_open_browser"}
            />
          </div>
        )}
      </div>

      {resumePending && (
        <div
          className="crawl-tasks-banner crawl-tasks-banner-warning"
          role="status"
        >
          Resume request in progress...
        </div>
      )}

      {!resumePending && recoveryAttempt && (
        <div
          className="crawl-tasks-banner crawl-tasks-banner-warning"
          data-testid="crawl-task-recovery-attempt"
          role="status"
        >
          <strong>
            Resume #{recoveryAttempt.sequenceNo} · {recoveryStrategy}
          </strong>
          {recoveryAttempt.status === "pending" ? (
            <div>
              Accepted {formatRecoveryTimestamp(recoveryAttempt.requestedAt)};
              waiting for the crawl outcome.
            </div>
          ) : (
            <div>
              Returned to manual action{" "}
              {formatRecoveryTimestamp(recoveryAttempt.outcomeAt)}:{" "}
              {recoveryStage} · {recoveryClassification}
              {recoveryAttempt.message ? ` — ${recoveryAttempt.message}` : ""}
            </div>
          )}
        </div>
      )}

      {recoveryAttemptError && (
        <div
          className="crawl-tasks-banner crawl-tasks-banner-error"
          role="alert"
        >
          Recovery attempt history unavailable: {recoveryAttemptError}
        </div>
      )}

      {reuseSupported ? (
        <div className="manual-action-primary-step">
          {primaryStep === "start_helper" && (
            <>
              <strong>
                {helperHealth.status === "checking"
                  ? "Checking the host helper..."
                  : "Host helper is offline"}
              </strong>
              <p>
                Copy the start command, then paste it into a terminal from the
                repository root. It starts in <code>{helperStartWorkdir}</code>;
                this page will detect it automatically.
              </p>
              <button
                type="button"
                className="manual-action-primary-button"
                data-testid="crawl-task-copy-helper-command"
                disabled={anyPending || helperHealth.status === "checking"}
                onClick={() => void handleCopyHelperCommand()}
              >
                <Clipboard size={16} aria-hidden="true" />
                <span>
                  {pollHelper
                    ? "Copy Command Again"
                    : "Copy Helper Start Command"}
                </span>
              </button>
            </>
          )}

          {primaryStep === "open_browser" && (
            <>
              <strong>
                {reuseState.status === "checking"
                  ? "Checking for an open browser..."
                  : "Helper online — open the verification browser"}
              </strong>
              <p>
                Open the dedicated {sourceLabel} browser and complete any login,
                WAF, or IP challenge there.
              </p>
              <button
                type="button"
                className="manual-action-primary-button"
                data-testid="crawl-task-open-browser"
                disabled={anyPending || reuseState.status === "checking"}
                onClick={() => void handleOpenBrowser()}
              >
                <MonitorPlay size={16} aria-hidden="true" />
                <span>Open Verification Browser</span>
              </button>
            </>
          )}

          {primaryStep === "resume_with_open_browser" && (
            <>
              <strong>Browser connected — site access is not verified</strong>
              <p>
                Finish the required action in the {sourceLabel} browser. When
                the site works there, explicitly resume this crawl using that
                open browser.
              </p>
              <button
                type="button"
                className="manual-action-primary-button"
                data-testid="crawl-task-resume-open-browser"
                disabled={resumeDisabled}
                onClick={() =>
                  void runAction(
                    "resume_open_browser",
                    "Resume using open browser",
                    () => resumeCrawlJob(taskId, "reuse_open_browser"),
                    { refreshTask: true },
                  )
                }
              >
                <RotateCcw size={16} aria-hidden="true" />
                <span>Resume Task with Open Browser</span>
              </button>
            </>
          )}
        </div>
      ) : (
        <div className="manual-action-primary-step">
          <strong>Operator review required</strong>
          <p>
            {instructions ||
              "This task does not expose reusable-browser recovery."}
          </p>
          {!resumeSupported && (
            <div
              className="crawl-tasks-action-note"
              data-testid="crawl-task-resume-unsupported"
            >
              This manual action cannot be resumed automatically.
            </div>
          )}
        </div>
      )}

      {resumeSupported && (
        <div className="manual-action-fallback">
          <div>
            <strong>Alternative: start with a fresh profile</strong>
            <p>
              This does not reuse the open browser and may encounter the same
              login, WAF, or IP challenge again.
            </p>
          </div>
          <button
            type="button"
            className="manual-action-secondary-button"
            data-testid="crawl-task-resume-fresh"
            disabled={resumeDisabled}
            onClick={() =>
              void runAction(
                "resume_fresh",
                "Resume with fresh profile",
                () => resumeCrawlJob(taskId, "fresh_profile"),
                { refreshTask: true },
              )
            }
          >
            <RotateCcw size={16} aria-hidden="true" />
            <span>Resume with Fresh Profile</span>
          </button>
        </div>
      )}

      {resetSupported && (
        <div className="manual-action-fallback">
          <div>
            <strong>Profile lock detected — safe reset available</strong>
            <p>
              Reset clears the stale worker profile state without deleting
              completed crawl progress.
            </p>
          </div>
          <button
            type="button"
            className="manual-action-secondary-button"
            data-testid="crawl-task-reset-profile"
            disabled={anyPending || recoveryOutcomePending}
            onClick={() => void handleResetProfile()}
          >
            <RotateCcw size={16} aria-hidden="true" />
            <span>Reset Browser Profile</span>
          </button>
        </div>
      )}

      {resetReason && !resetSupported && (
        <div
          className="crawl-tasks-action-note"
          data-testid="crawl-task-reset-unavailable"
          role="status"
        >
          Browser profile reset is unavailable: {resetReason.replace(/_/g, " ")}.
        </div>
      )}

      {actionState.error && (
        <div
          className="crawl-tasks-banner crawl-tasks-banner-error"
          role="alert"
        >
          {actionState.error}
        </div>
      )}
      {actionState.notice && (
        <div
          className="crawl-tasks-banner crawl-tasks-banner-success"
          role="status"
        >
          {actionState.notice}
        </div>
      )}

      {reuseSupported && (
        <details className="manual-action-advanced">
          <summary>Advanced troubleshooting</summary>
          <div className="manual-action-diagnostics">
            <div>
              <span>Working directory</span>
              <code>{helperStartWorkdir}</code>
            </div>
            <div>
              <span>Start command</span>
              <code>{helperStartCommand}</code>
            </div>
            <div>
              <span>Health endpoint</span>
              <code>{helperHealthUrl}</code>
            </div>
            <div>
              <span>Helper status</span>
              <code>
                {helperHealth.status}
                {helperHealth.detail ? ` — ${helperHealth.detail}` : ""}
              </code>
            </div>
            <div>
              <span>Browser connection</span>
              <code>
                {reuseState.status}
                {reuseState.detail ? ` — ${reuseState.detail}` : ""}
              </code>
            </div>
          </div>
          <div className="manual-action-advanced-actions">
            <button
              type="button"
              data-testid="crawl-task-retry-helper-health"
              disabled={anyPending || helperHealth.status === "checking"}
              onClick={() => void checkHelperHealth()}
            >
              <RefreshCcw size={16} aria-hidden="true" />
              <span>Check Helper Health</span>
            </button>
            <button
              type="button"
              data-testid="crawl-task-check-reuse-status"
              disabled={anyPending || helperHealth.status !== "online"}
              onClick={() => void checkReuseStatus()}
            >
              <RefreshCcw size={16} aria-hidden="true" />
              <span>Check Browser Connection</span>
            </button>
            <button
              type="button"
              data-testid="crawl-task-close-profile-windows"
              disabled={anyPending || helperHealth.status !== "online"}
              onClick={() => void handleCloseProfileWindows()}
            >
              <Unplug size={16} aria-hidden="true" />
              <span>Close Profile Windows</span>
            </button>
          </div>
        </details>
      )}
    </section>
  );
}
