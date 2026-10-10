export const validRunName = name => typeof name === 'string' && name.length === 20 && /^auto_\d{8}_\d{6}$/.test(name);
export const preserveSelection = (rows, selected) => rows.some(row => row.name === selected) ? selected : rows[0]?.name || '';
export function replayIndex(index, action, count) {
  if (!count) return -1;
  if (action === 'reset') return 0;
  return Math.max(0, Math.min(count - 1, index + (action === 'back' ? -1 : 1)));
}
export function recordedTime(line) {
  const match = /^(?:[A-Z_]+\s+)?\[((?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d)\]/.exec(line);
  return match ? match[1] : null; // Time of day only: no inferred date, zone, or duration.
}
export function regressionRows(value) {
  return Array.isArray(value) ? value.map(item => {
    const row = item && typeof item === 'object' ? item : {};
    const text = value => typeof value === 'string' && value.trim() ? value : 'Not available';
    return { id: text(row.scenario_id), file: text(row.file), invariant: text(row.invariant),
      status: row.last_status === 'pass' ? 'Passed last replay' : row.last_status === 'fail' ? 'Failed last replay' : row.last_status === 'never_run' ? 'Never run' : 'Not available',
      at: typeof row.last_run_at === 'number' && Number.isFinite(row.last_run_at) && Number.isFinite(new Date(row.last_run_at * 1000).getTime()) ? new Date(row.last_run_at * 1000).toISOString() : 'Not available' };
  }) : null;
}
