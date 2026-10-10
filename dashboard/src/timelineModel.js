import { arr, obj, num } from './data.js';
export const TIMELINE_STAGES = ['Fault injection', 'Detection', 'Kill switch', 'Probe recovery'];
// These are explicit producer messages, never predictions or inferred timings.
export function timelineEvidence(events) {
  return arr(events).flatMap((event, index) => {
    const { t, kind, msg } = obj(event);
    if (!num(t) || !Number.isFinite(new Date(t * 1000).getTime()) || typeof msg !== 'string') return [];
    const text = msg.replace(/^\[\d{2}:\d{2}:\d{2}\]\s*/, '');
    let stage = null;
    if (['inject', 'fault'].includes(kind) && /^INJECT .+ OK$/.test(text)) stage = 'Fault injection';
    else if (kind === 'guard' && /(?:KILL SWITCH[.:]|manual kill switch \(STOP file\))/.test(text)) stage = 'Kill switch';
    else if (kind === 'guard' && /^(?:guard \d+\/\d+:|CASCADE FAILURE:|DATA LOSS:)/.test(text)) stage = 'Detection';
    else if (kind === 'ok' && /^Recovered in \d+(?:\.\d+)?s$/.test(text)) stage = 'Probe recovery';
    return stage ? [{ t, kind, msg, stage, key: `${index}:${t}` }] : [];
  }).sort((a, b) => a.t - b.t);
}
