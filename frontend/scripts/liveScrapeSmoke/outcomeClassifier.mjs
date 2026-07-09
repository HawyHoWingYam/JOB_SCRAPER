const SUCCESS_STATUSES = new Set(['completed', 'ai_running', 'completed_with_ai_failures']);

function normalizeToken(value) {
  return `${value || ''}`
    .trim()
    .toLowerCase()
    .replace(/\s+/g, '_');
}

function normalizeText(value) {
  return `${value || ''}`.trim().toLowerCase();
}

export function isTerminalTaskStatus(status) {
  const normalizedStatus = normalizeToken(status);
  return (
    SUCCESS_STATUSES.has(normalizedStatus) ||
    normalizedStatus === 'failed' ||
    normalizedStatus === 'manual_action_required' ||
    normalizedStatus === 'cancelled'
  );
}

export function classifyOutcome(task = {}) {
  const issueClass = normalizeToken(task.issueClass || task.issue_class);
  const issueCode = normalizeToken(task.issueCode || task.issue_code);
  const status = normalizeToken(task.status);
  const issueText = normalizeText(
    task.latestIssueText ||
      task.latest_issue_text ||
      task.error ||
      task.status_reason
  );

  if (issueClass) {
    return issueClass;
  }

  if (issueCode === '2520') {
    return 'detail_unavailable';
  }

  if (issueCode === '1002' || issueText.includes('login expired')) {
    return 'session_expired';
  }

  if (issueCode === '-1000035' || issueText.includes('ip blocked') || issueText.includes('ip block')) {
    return 'ip_blocked';
  }

  if (issueText.includes('waf') || issueText.includes('captcha') || issueText.includes('verify')) {
    return 'waf_challenge';
  }

  if (status === 'manual_action_required') {
    return 'manual_action_required';
  }

  if (SUCCESS_STATUSES.has(status)) {
    return 'success';
  }

  if (status === 'failed' || issueText) {
    return 'infrastructure_failure';
  }

  return 'unknown_failure';
}
