export const obj = v => v !== null && typeof v === 'object' && !Array.isArray(v) ? v : {};
export const arr = v => Array.isArray(v) ? v : [];
export const num = v => typeof v === 'number' && Number.isFinite(v);
export const fmt = (v, suffix = '') => num(v) ? `${Number(v.toFixed(1))}${suffix}` : 'Not available';
export const pct = v => num(v) ? `${(v * 100).toFixed(1)}%` : 'Not available';
export const running = phase => ['running', 'reporting', 'healing', 'baseline'].includes(phase);
export const localTime = timestamp => { const date = num(timestamp) ? new Date(timestamp * 1000) : null; return date && !Number.isNaN(date.getTime()) ? date.toLocaleTimeString([], { hour12: false }) : 'Not available'; };
