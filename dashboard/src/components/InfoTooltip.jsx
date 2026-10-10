import React, { createContext, useContext, useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Icon } from './ui.jsx';

export const TERMS = {
  FMEA: 'Failure Mode and Effects Analysis: ChaosPilot scores observed failure modes using severity, occurrence, and detection.',
  RPN: 'Risk Priority Number: severity × occurrence × detection. ChaosPilot computes this in code; the AI does not assign it.',
  'gray failure': 'Monitoring appears healthy while an application invariant fails, such as accepted votes not reaching Postgres.',
  canary: 'A uniquely tagged test vote checked end to end. Canary votes are excluded from user vote counts.',
  'guard ticks': 'Consecutive measured breaches of safety thresholds. Reaching the configured count trips the deterministic kill switch.',
  'root cause': 'The reported explanation for a failure, supported by quoted evidence. A diagnosis is not proof that a fix worked.',
  'agent roles': 'Reasoning agents propose and explain. Supporting code governs, executes, evaluates, verifies, and reports. Arrows show allowed routing, not completed work.',
};
export const TooltipScope = createContext('overview');

export default function InfoTooltip({ term, children }) {
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
  return <span className="info-tooltip"><button ref={trigger} type="button" className="info-trigger" aria-label={`Explain ${term}`} aria-describedby={open ? id : undefined}
    onFocus={() => { focused.current = true; show(); }} onBlur={() => { focused.current = false; pinned.current = false; close(); }} onPointerEnter={show} onPointerLeave={close}
    onClick={() => { pinned.current = true; show(); }}><Icon name="info" size={15} /></button>
    {open && createPortal(<span ref={bubble} id={id} role="tooltip" className="info-bubble" style={position} onPointerEnter={show} onPointerLeave={close}><strong>{term}</strong>{children || TERMS[term] || 'Not available'}</span>, document.body)}
  </span>;
}
