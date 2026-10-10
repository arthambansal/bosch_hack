import { obj, arr, num } from './data.js';
import { activeNodeId, nodeLabel, WORKFLOW_NODES } from './workflow.js';

export const VIEWS = Object.freeze([
  { id: 'overview', label: 'Overview', icon: 'overview' },
  { id: 'agents', label: 'Agents', icon: 'workflow' },
  { id: 'experiments', label: 'Experiments', icon: 'telemetry' },
  { id: 'diagnostics', label: 'Diagnostics', icon: 'search' },
  { id: 'recovery', label: 'Recovery', icon: 'shield' },
  { id: 'history', label: 'History', icon: 'clock' },
]);
export const textValue = value => typeof value === 'string' && value.trim() ? value : 'Not available';

// Manual-activation tabs: arrows move focus, Enter/Space selects the view.
export function nextTabIndex(index, key) {
  if (key === 'Home') return 0;
  if (key === 'End') return VIEWS.length - 1;
  if (key === 'ArrowRight') return (index + 1) % VIEWS.length;
  if (key === 'ArrowLeft') return (index + VIEWS.length - 1) % VIEWS.length;
  return null;
}

export function statusPresentation(live, now = Date.now()) {
  const state = obj(live.state);
  const fresh = live.status === 'connected' && num(live.received)
    && now >= live.received && now - live.received < 2000;
  const finished = ['completed', 'stopped'].includes(state.run_status) || ['ran', 'stopped', 'idle', 'healed'].includes(state.phase);
  const node = activeNodeId(state.agent_active);
  return {
    fresh,
    run: textValue(state.run_status), phase: textValue(state.phase),
    agent: fresh && !finished && state.run_status !== 'stopping'
      && WORKFLOW_NODES.some(item => item.id === node) ? nodeLabel(node) : 'Not available',
    experiment: textValue(obj(state.experiment).name || obj(state.experiment).id),
    experimentCurrent: fresh && !finished && state.run_status !== 'stopping',
    guard: obj(state.guard).tripped === true ? 'Tripped' : obj(state.guard).tripped === false ? 'Not tripped' : 'Not available',
  };
}

// Only explicit [AgentName] messages are attributed to an agent. Route arrows
// and being the active agent never establish a completed decision or outcome.
export function agentEvents(state, label) {
  return arr(state.events).filter(event => typeof obj(event).msg === 'string'
    && event.msg.replace(/^\[\d{2}:\d{2}:\d{2}\]\s*/, '').startsWith(`[${label}]`));
}
