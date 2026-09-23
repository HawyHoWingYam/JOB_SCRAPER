import { expect, it } from 'vitest';
import { buildSettingsRoute, parseSettingsRoute } from './settingsRoute';
it('round trips section, profile and exact AI return identity', () => {
  const route = { section: 'ai-runtime', profile: 'jobs', returnToAI: true, returnRun: 'opaque/run' };
  expect(parseSettingsRoute(buildSettingsRoute(route))).toEqual(route);
});
it('ignores unsupported sections and arbitrary return destinations', () => {
  expect(parseSettingsRoute('#settings?section=unknown&return=https://example.com&profile=wrong')).toEqual({ section: 'ai-runtime', profile: null, returnToAI: false, returnRun: null });
});
