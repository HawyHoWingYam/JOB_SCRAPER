function eventSequence(event) {
  const sequence = Number(event?.sequence_no);
  return Number.isFinite(sequence) ? sequence : -1;
}

function eventPayload(event) {
  return event?.payload && typeof event.payload === "object"
    ? event.payload
    : {};
}

export function deriveLatestRecoveryAttempt(events) {
  if (!Array.isArray(events)) {
    return null;
  }

  const latestResume = events.reduce((latest, event) => {
    if (event?.event_type !== "crawl.resume_requested") {
      return latest;
    }
    return !latest || eventSequence(event) > eventSequence(latest)
      ? event
      : latest;
  }, null);

  if (!latestResume) {
    return null;
  }

  const sequenceNo = eventSequence(latestResume);
  const resumePayload = eventPayload(latestResume);
  const baseAttempt = {
    status: "pending",
    sequenceNo,
    strategy: `${resumePayload.strategy || ""}` || null,
    requestedAt: latestResume.created_at || null,
  };

  const manualActionOutcome = events.reduce((earliest, event) => {
    const sequence = eventSequence(event);
    if (
      event?.event_type !== "crawl.manual_action_required" ||
      sequence <= sequenceNo
    ) {
      return earliest;
    }
    return !earliest || sequence < eventSequence(earliest) ? event : earliest;
  }, null);

  if (!manualActionOutcome) {
    return baseAttempt;
  }

  const outcomePayload = eventPayload(manualActionOutcome);
  const manualAction =
    outcomePayload.manual_action &&
    typeof outcomePayload.manual_action === "object"
      ? outcomePayload.manual_action
      : {};

  return {
    ...baseAttempt,
    status: "manual_action_required",
    outcomeSequenceNo: eventSequence(manualActionOutcome),
    outcomeAt: manualActionOutcome.created_at || null,
    stage: `${manualAction.stage || ""}` || null,
    classification: `${manualAction.classification || ""}` || null,
    message: `${manualAction.message || outcomePayload.error || ""}` || null,
  };
}
