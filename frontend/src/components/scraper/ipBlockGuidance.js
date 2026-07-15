import { formatScraperSourceLabel } from './listingBatchLabel';


export function buildIpBlockGuidance({ sourceSite, message } = {}) {
  const normalizedSource = `${sourceSite || ''}`.trim().toLowerCase();
  const sourceLabel = formatScraperSourceLabel(normalizedSource);
  const explicitMessage = `${message || ''}`.trim();
  const recoveryText = `Change the public IP or switch network first, confirm ${sourceLabel} is reachable, then resume this same task. Completed progress is preserved.`;
  const explicitAlreadyActionable = /change/i.test(explicitMessage)
    && /(public )?ip|network/i.test(explicitMessage)
    && /resume this same (task|crawl)/i.test(explicitMessage);

  return {
    title: `${sourceLabel} IP access is blocked.`,
    message: explicitAlreadyActionable
      ? explicitMessage
      : [explicitMessage || `${sourceLabel} rejected the current public IP or network.`, recoveryText]
          .filter(Boolean)
          .join(' '),
  };
}
