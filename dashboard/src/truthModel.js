import { obj, num } from './data.js';
import { textValue } from './viewModel.js';
export const timestamp = value => num(value) && Number.isFinite(new Date(value * 1000).getTime()) ? new Date(value * 1000).toLocaleString([], { hour12: false }) : 'Not available';
export function truthPresentation(value) {
  const truth = obj(value), canaries = obj(truth.canaries);
  return {
    status: ['ok', 'diverged', 'down', 'unknown'].includes(truth.status) ? truth.status : null,
    monitoring: ['healthy', 'degraded', 'unknown'].includes(truth.monitoring) ? truth.monitoring : null,
    canaries: Object.fromEntries(['sent', 'stored', 'pending', 'suspected_lost', 'last_lag_s', 'grace_s'].map(key => [key, num(canaries[key]) ? canaries[key] : 'Not available'])),
    invariants: Array.isArray(truth.invariants) ? truth.invariants.map(item => ({ name: textValue(obj(item).name), detail: textValue(obj(item).detail), status: obj(item).ok === false ? 'Failing' : obj(item).ok === true ? 'Passed' : 'Not available' })) : [],
    divergedAt: timestamp(truth.diverged_at), updatedAt: timestamp(truth.updated_at),
    inconsistent: truth.status === 'diverged' && truth.monitoring !== 'healthy',
  };
}
