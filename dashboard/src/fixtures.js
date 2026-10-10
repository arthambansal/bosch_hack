const loaders = Object.freeze({
  approval_pending: () => import('../fixtures/approval_pending.json'),
  completed_with_fixes: () => import('../fixtures/completed_with_fixes.json'),
  gray_failure: () => import('../fixtures/gray_failure.json'),
  idle: () => import('../fixtures/idle.json'),
  mystery_revealed: () => import('../fixtures/mystery_revealed.json'),
  rollback_failed: () => import('../fixtures/rollback_failed.json'),
});
export const FIXTURE_NAMES = Object.freeze(Object.keys(loaders));
export function fixtureSelection(search = '') {
  const params = new URLSearchParams(search);
  if (!params.has('fixture')) return null;
  const names = params.getAll('fixture'), name = names[0];
  return { name, valid: names.length === 1 && Object.hasOwn(loaders, name) };
}
export async function loadFixture(selection) {
  if (!selection?.valid || !Object.hasOwn(loaders, selection.name)) throw new Error('Unknown fixture. Permitted names: ' + FIXTURE_NAMES.join(', ') + '. Live data has not been substituted.');
  const state = (await loaders[selection.name]()).default;
  if (!state || typeof state !== 'object' || Array.isArray(state)) throw new Error('Invalid fixture snapshot.');
  return structuredClone(state);
}
