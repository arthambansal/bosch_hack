import React from 'react';

const paths = {
  overview: 'M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z',
  workflow: 'M4 5h5v5H4z M15 14h5v5h-5z M9 7h8v7 M6 10v7h9',
  topology: 'M9 3h6v6H9z M2 16h6v6H2z M16 16h6v6h-6z M12 9v4 M5 16v-3h14v3',
  activity: 'M4 5h2 M10 5h10 M4 12h2 M10 12h10 M4 19h2 M10 19h10',
  telemetry: 'M3 19V5 M3 19h18 M6 14l4-5 4 3 6-7',
  shield: 'M12 3l8 3v6c0 5-8 9-8 9s-8-4-8-9V6z M8 12l3 3 5-6',
  lock: 'M6 10h12v11H6z M8 10V7a4 4 0 0 1 8 0v3 M12 14v3',
  arrow: 'M5 12h14 M14 7l5 5-5 5',
  chevron: 'M9 5l7 7-7 7',
  info: 'M12 11v6 M12 7v1 M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0',
  stop: 'M7 3h10l4 4v10l-4 4H7l-4-4V7z M9 9h6v6H9z',
  search: 'M15 15l6 6 M17 10a7 7 0 1 1-14 0 7 7 0 0 1 14 0',
  check: 'M5 12l4 4L19 6',
  clock: 'M12 7v5l3 2 M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0',
};

export function Icon({ name, size = 20, className = '' }) {
  return <svg className={className} width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[name] || paths.info} /></svg>;
}

export function EmptyState({ icon, title, children, compact = false }) {
  return <div className={`empty-state ${compact ? 'compact' : ''}`}><span className="empty-symbol"><Icon name={icon} size={26} /></span><div><h3>{title}</h3><p>{children}</p></div></div>;
}

export function SectionHeading({ eyebrow, title, description, children, id }) {
  return <div className="section-heading"><div>{eyebrow && <span className="eyebrow">{eyebrow}</span>}<h2 id={id}>{title}</h2>{description && <p>{description}</p>}</div>{children}</div>;
}
