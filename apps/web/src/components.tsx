import type { ReactNode } from 'react';
import { label } from './api';

type IconName = 'overview' | 'campaign' | 'runtime' | 'plus' | 'search' | 'close' | 'check' | 'download' | 'play' | 'pause' | 'refresh' | 'sliders' | 'info' | 'terminal' | 'external' | 'chevron' | 'alert' | 'layers' | 'file' | 'camera' | 'menu' | 'stop' | 'copy';
const paths: Record<IconName, ReactNode> = {
  overview: <><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/></>,
  campaign: <><path d="M4 20V4m0 16h16M8 15l4-5 4 3 4-7"/><circle cx="8" cy="15" r="1"/><circle cx="12" cy="10" r="1"/><circle cx="16" cy="13" r="1"/></>,
  runtime: <><rect x="5" y="5" width="14" height="14" rx="3"/><path d="M9 1v4m6-4v4M9 19v4m6-4v4M1 9h4m-4 6h4m14-6h4m-4 6h4"/><rect x="9" y="9" width="6" height="6" rx="1"/></>,
  plus: <path d="M12 5v14M5 12h14"/>, search: <><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/></>,
  close: <path d="m6 6 12 12M6 18 18 6"/>, check: <path d="m5 12 4 4L19 6"/>,
  download: <><path d="M12 3v12m-5-5 5 5 5-5M4 15v5h16v-5"/></>, play: <path d="m8 4 12 8-12 8z"/>, pause: <><path d="M8 4v16M16 4v16"/></>,
  refresh: <><path d="M20 10a8 8 0 0 0-14-5L3 8m0-5v5h5M4 14a8 8 0 0 0 14 5l3-3m0 5v-5h-5"/></>,
  sliders: <><path d="M5 3v4m0 6v8M12 3v10m0 6v2M19 3v2m0 6v10"/><circle cx="5" cy="10" r="3"/><circle cx="12" cy="16" r="3"/><circle cx="19" cy="8" r="3"/></>,
  info: <><circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10v.1"/></>,
  terminal: <><rect x="3" y="4" width="18" height="16" rx="2"/><path d="m7 9 3 3-3 3m6 0h4"/></>,
  external: <><path d="M14 3h7v7m0-7L10 14M11 3H4v17h17v-7"/></>,
  chevron: <path d="m9 5 7 7-7 7"/>, alert: <><path d="m12 3 10 18H2zM12 9v5m0 3v.1"/></>,
  layers: <><path d="m12 3 10 5-10 5L2 8zm-10 9 10 5 10-5M2 16l10 5 10-5"/></>,
  file: <><path d="M14 2H5v20h14V7zm0 0v5h5M8 12h8m-8 4h8"/></>,
  camera: <><rect x="2" y="6" width="20" height="15" rx="2"/><path d="m7 6 2-3h6l2 3"/><circle cx="12" cy="13" r="4"/></>,
  menu: <path d="M4 6h16M4 12h16M4 18h16"/>, stop: <rect x="5" y="5" width="14" height="14" rx="2"/>,
  copy: <><rect x="8" y="8" width="12" height="13" rx="2"/><path d="M16 8V3H3v13h5"/></>,
};
export function Icon({ name, size = 20, className = '' }: { name: IconName; size?: number; className?: string }) {
  return <svg className={className} width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}
export function Status({ value }: { value: string }) {
  const tone = ['completed', 'success', 'verified', 'confirmed', 'ready', 'succeeded', 'reproduced', 'accepted'].includes(value) ? 'green' : ['running', 'queued', 'pending', 'searching', 'reducing', 'confirming'].includes(value) ? 'blue' : ['failed', 'failure', 'error', 'infrastructure_error', 'horizon_exhausted', 'terminated_without_success', 'unstable'].includes(value) ? 'red' : 'neutral';
  return <span className={`status status-${tone}`}>{['running', 'searching', 'reducing', 'confirming'].includes(value) && <span className="live-dot"/>}{label(value)}</span>;
}
export function BackendBadge({ backend }: { backend?: string }) {
  return <span className={`backend-badge ${backend === 'synthetic' ? 'synthetic' : ''}`}>{backend === 'synthetic' ? 'Synthetic validation' : 'Robot experiment'}</span>;
}
export function Empty({ icon = 'campaign', title, children, action }: { icon?: IconName; title: string; children: ReactNode; action?: ReactNode }) {
  return <div className="empty"><div className="empty-icon"><Icon name={icon} size={27}/></div><h3>{title}</h3><p>{children}</p>{action}</div>;
}
export function Notice({ children, tone = 'info' }: { children: ReactNode; tone?: 'info' | 'warning' | 'error' }) {
  return <div className={`notice notice-${tone}`} role={tone === 'error' ? 'alert' : undefined}><Icon name={tone === 'info' ? 'info' : 'alert'} size={19}/><div>{children}</div></div>;
}
export function SectionHeading({ eyebrow, title, description, action }: { eyebrow?: string; title: string; description?: string; action?: ReactNode }) {
  return <div className="section-heading"><div>{eyebrow && <span className="eyebrow">{eyebrow}</span>}<h2>{title}</h2>{description && <p>{description}</p>}</div>{action}</div>;
}
export function Loading() { return <div className="loading" role="status"><span className="spinner"/>Loading investigation data…</div>; }
