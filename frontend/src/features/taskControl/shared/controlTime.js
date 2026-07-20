export const DEFAULT_TIMEZONE = 'Asia/Hong_Kong';

export function formatControlDateTime(value, timeZone = DEFAULT_TIMEZONE) {
  if (!value) return 'Not available';
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return 'Invalid date';
  return new globalThis.Intl.DateTimeFormat('en-HK', {
    year: 'numeric',
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    timeZone,
    timeZoneName: 'short',
  }).format(date);
}

export function schedulePresetSummary(cron, timeZone = DEFAULT_TIMEZONE) {
  const label = {
    '0 * * * *': 'Every hour',
    '0 2 * * *': 'Daily at 02:00',
    '0 4 * * *': 'Daily at 04:00',
    '0 9 * * 1-5': 'Weekdays at 09:00',
    '0 9 * * 1': 'Mondays at 09:00',
  }[cron] || `Custom cron: ${cron}`;
  return `${label} · ${timeZone}`;
}
