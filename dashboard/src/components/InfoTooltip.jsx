import React, { createContext, useContext, useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Icon } from './ui.jsx';

export const TERMS = {
  'approval gate': 'Human review of one specific proposed experiment, bound to a backend gate ID and expiry. An accepted decision is not proof that the experiment executed or recovered.',
  probes: 'Backend measurements of selected request paths. Sample count describes the supplied measurement window; passing entry probes do not establish every container or invariant is healthy.',
  'fault injection': 'An authorized disruption of a sandbox service, such as kill, pause, partition, latency, or load spike. Planned steps are not evidence that injection occurred.',
  healing: 'Applying a sandbox configuration fix followed by targeted verification. Applying a fix alone does not establish improvement.',
  compose: 'A Docker Compose configuration change for sandbox services. Code suggestions remain read-only proposals and are not automatically applied.',
  stateful: 'A service that retains application state, such as a database or queue. A fault can affect data as well as availability; statefulness comes from published topology.',
  delivery: 'Backend accounting of accepted work and stored results. A growing queue can be backlog rather than confirmed loss; inspect the published evidence.',
  'resilience score': 'The deterministic score published in the report, summarizing the measured experiments. It is not a guarantee about untested failures or production reliability.',
  signature: 'A stored pattern from a confirmed failure. Memory similarity compares evidence with that pattern rather than proving a new diagnosis.',
  'canary grace': 'The backend waiting period, in seconds, before an absent canary is suspected lost. Pending and suspected loss are different states; neither should be invented when unavailable.',
  'p95 latency': '95% of measured request response times are at or below this value, in milliseconds. Compare it with the measured baseline and published safety ceiling; missing samples are not zero latency.',
  'error rate': 'The fraction of measured requests that failed, displayed as a percentage. The published ceiling is a runtime safety limit; missing samples do not establish health.',
  baseline: 'The recorded healthy reference used for comparisons. It is separate from current samples and does not prove that the application is healthy now.',
  MTTD: 'Mean time to detect a fault, in seconds, when supplied by the backend. It describes observed detection timing; an unavailable value is not instant detection.',
  MTTR: 'Mean time to recover, in seconds, when supplied by the backend. Recovery must be measured; cleanup acknowledgement alone does not prove it.',
  'safety thresholds': 'Backend-configured ceilings for error rate, p95 response time, and fault duration. They constrain experiments; the UI displays their values and does not invent limits.',
  Governor: 'Deterministic policy checks that accept or reject a proposed experiment before execution. Human approval and the runtime guard are separate safeguards.',
  'kill switch': 'The deterministic runtime guard aborts when configured safety limits are breached. This differs from an operator STOP request, whose acknowledgement does not prove cleanup finished.',
  'Truth Oracle': 'End-to-end correctness checks using canary votes and application invariants. Its measurements can reveal user impact even when ordinary monitoring appears healthy.',
  Provenance: 'Where the snapshot and measurements came from. Fixture data is static; a connected backend alone does not establish Docker measurements or live AI use.',
  Confidence: 'The diagnosis confidence published by the backend. It is not a measured probability of correctness or evidence that remediation succeeded.',
  Similarity: 'How closely the current failure resembles a stored signature, as published by the backend. A high match is not diagnosis confidence or proof of the cause.',
  'Memory hit': 'The backend reused a stored failure signature for diagnosis. Inspect the matching evidence; a match does not itself prove recovery.',
  Rollback: 'Undoing an applied fix. A successful undo is reported as rolled_back; rollback_failed means it is still applied and recovery is unconfirmed.',
  'verification status': 'Proposed means not applied; applied means not yet proven; verified means backend comparisons improved; not_improved means improvement was not demonstrated. rolled_back means the undo completed. Inspect failure and untested evidence separately.',
  'Untested fixes': 'Experiment IDs responsible for this fix that were not re-run, for example after STOP or a budget limit. Missing comparisons mean not proven, not a proven failure.',
  Regression: 'A previously confirmed failure returning during a replay. The last replay result is historical evidence and does not certify the current run.',
  'blast radius': 'The services or components a proposed fault can affect. The Governor constrains scope using backend policy; this dashboard does not infer a safe radius.',
  'prediction check': 'Compares an agent prediction with the observed outcome. Agreement is not a measurement by itself; false means at least one published check disagreed.',
  'risk score': 'A backend-published planning score used to rank proposed faults. It is separate from measured FMEA RPN and does not prove an outcome.',
  'event replay': 'Read-only playback of recorded event text. Reading speed advances events, not original elapsed time; it does not rerun faults or control the current experiment.',
  FMEA: 'Failure Mode and Effects Analysis: ChaosPilot scores observed failure modes using severity, occurrence, and detection.',
  RPN: 'Risk Priority Number: severity × occurrence × detection. ChaosPilot computes this in code; the AI does not assign it.',
  'gray failure': 'Monitoring appears healthy while an application invariant fails, such as accepted votes not reaching Postgres.',
  monitoring: 'Health checks and probe signals reported by the backend. Healthy monitoring alone does not prove that accepted votes reach storage.',
  invariants: 'Application correctness rules checked by the Truth Oracle. False means failing; null means not measured.',
  'canary votes': 'Uniquely tagged test votes checked through storage. Counts and lag are measured by the backend; suspected loss is not a confirmed loss count.',
  canary: 'A uniquely tagged test vote checked end to end. Canary votes are excluded from user vote counts.',
  'guard ticks': 'Consecutive measured breaches of safety thresholds. Reaching the configured count trips the deterministic kill switch.',
  'root cause': 'The reported explanation for a failure, supported by quoted evidence. A diagnosis is not proof that a fix worked.',
  'agent roles': 'Reasoning agents propose and explain. Supporting code governs, executes, evaluates, verifies, and reports. Arrows show allowed routing, not completed work.',
};
export const TooltipScope = createContext('overview');

export default function InfoTooltip({ term, children, triggerContent, triggerClassName }) {
  const scope = useContext(TooltipScope);
  const id = useId(), trigger = useRef(null), bubble = useRef(null), timer = useRef(null);
  const focused = useRef(false), pinned = useRef(false);
  const [open, setOpen] = useState(false), [position, setPosition] = useState({ left: 12, top: 12 });
  const show = () => { clearTimeout(timer.current); setOpen(true); };
  const close = () => { clearTimeout(timer.current); if (!focused.current && !pinned.current) timer.current = setTimeout(() => setOpen(false), 120); };
  useEffect(() => () => clearTimeout(timer.current), []);
  useEffect(() => { clearTimeout(timer.current); pinned.current = false; setOpen(false); }, [scope]);
  useLayoutEffect(() => {
    if (!open) return;
    function place() {
      const anchor = trigger.current.getBoundingClientRect(), box = bubble.current.getBoundingClientRect();
      const left = Math.max(12, Math.min(anchor.left, window.innerWidth - box.width - 12));
      const top = anchor.bottom + box.height + 20 < window.innerHeight ? anchor.bottom + 8 : Math.max(12, anchor.top - box.height - 8);
      setPosition({ left, top });
    }
    place(); window.addEventListener('resize', place); window.addEventListener('scroll', place, true);
    function dismiss(event) {
      if (event.key === 'Escape' || (event.type === 'pointerdown' && !trigger.current.contains(event.target) && !bubble.current.contains(event.target))) {
        clearTimeout(timer.current); pinned.current = false; setOpen(false);
      }
    }
    document.addEventListener('keydown', dismiss); document.addEventListener('pointerdown', dismiss);
    return () => { window.removeEventListener('resize', place); window.removeEventListener('scroll', place, true); document.removeEventListener('keydown', dismiss); document.removeEventListener('pointerdown', dismiss); };
  }, [open]);
  return <span className="info-tooltip"><button ref={trigger} type="button" className={triggerClassName || "info-trigger"} aria-label={`${triggerContent ? 'Inspect' : 'Explain'} ${term}`} aria-describedby={open ? id : undefined}
    onFocus={() => { focused.current = true; show(); }} onBlur={() => { focused.current = false; pinned.current = false; close(); }} onPointerEnter={show} onPointerLeave={close}
    onClick={() => { pinned.current = true; show(); }}>{triggerContent || <Icon name="info" size={15} />}</button>
    {open && createPortal(<span ref={bubble} id={id} role="tooltip" className="info-bubble" style={position} onPointerEnter={show} onPointerLeave={close}><strong>{term}</strong>{children || TERMS[term] || 'Not available'}</span>, document.body)}
  </span>;
}
