import { useState } from 'react';
import type { ReactNode } from 'react';
import { formatTime, label } from './api';
import { Icon, SectionHeading } from './components';
import type { Catalog, Health } from './types';
import { workerFor } from './workerStatus';
import { updateWorkspacePreferences } from './workspacePreferences';
import type { WorkspacePreferences } from './workspacePreferences';
import './workspaceSettings.css';

type Props = {
  preferences: WorkspacePreferences;
  connected: boolean | null;
  health: Health | null;
  catalog: Catalog | null;
  checking: boolean;
  lastChecked: string | null;
  refresh: () => Promise<void>;
};

function ServiceRow({ name, detail, state, lastSeen }: {
  name: string; detail: string; state: string; lastSeen?: string | number | null;
}) {
  const tone = ['Connected', 'Online', 'Qualified'].includes(state) ? 'available' :
    ['Disconnected', 'Pending qualification'].includes(state) ? 'attention' : 'neutral';
  return <li className="settings-service">
    <div><strong>{name}</strong><p>{detail}</p></div>
    <div className="settings-status"><span className={'settings-pill ' + tone}>{state}</span>
      {lastSeen != null && <small>Last seen {formatTime(lastSeen)}</small>}</div>
  </li>;
}

function Setting({ label: title, description, id, children }: { label: string; description: string; id: string; children: ReactNode }) {
  return <div className="settings-field"><div><label htmlFor={id}>{title}</label><p id={id + '-hint'}>{description}</p></div>{children}</div>;
}

export default function WorkspaceSettings({ preferences, connected, health, catalog, checking, lastChecked, refresh }: Props) {
  const [feedback, setFeedback] = useState('');
  function save(patch: Partial<WorkspacePreferences>) {
    const persisted = updateWorkspacePreferences(patch);
    setFeedback(persisted ? 'Preferences saved in this browser.' : 'Preference applied for this session. Browser storage is unavailable.');
  }
  const apiStatus = connected === null ? 'Checking' : connected ? 'Connected' : 'Disconnected';
  const unknown = connected === null ? 'Checking' : 'Unknown';
  const readiness = health?.readiness;
  return <div className="workspace-settings">
    <SectionHeading title="Settings" description="Manage browser preferences and check the services available to this workspace."/>
    <section className="settings-panel" aria-labelledby="settings-preferences">
      <header className="settings-heading"><Icon name="sliders" size={20}/><h3 id="settings-preferences">Browser preferences</h3></header>
      <Setting id="settings-refresh" label="Status refresh" description="How often to check the workspace connection and benchmark workers while this tab is visible.">
        <select id="settings-refresh" aria-describedby="settings-refresh-hint" value={preferences.refreshIntervalMs} onChange={e => save({refreshIntervalMs: Number(e.target.value) as WorkspacePreferences['refreshIntervalMs']})}>
          <option value={4000}>Every 4 seconds</option><option value={15000}>Every 15 seconds</option>
          <option value={60000}>Every minute</option><option value={0}>Manual</option>
        </select>
      </Setting>
      <Setting id="settings-timezone" label="Time zone" description="Time zone for dates and times shown in the workspace.">
        <select id="settings-timezone" aria-describedby="settings-timezone-hint" value={preferences.timeZone} onChange={e => save({timeZone: e.target.value as WorkspacePreferences['timeZone']})}>
          <option value="local">Device time zone</option><option value="utc">UTC</option>
        </select>
      </Setting>
      <div className="settings-feedback" role="status">{feedback || 'Preferences are stored in this browser.'}</div>
    </section>
    <section className="settings-panel" aria-labelledby="settings-runtime">
      <header className="settings-heading"><Icon name="runtime" size={20}/><h3 id="settings-runtime">Runtime status</h3>
        <button className="button secondary" type="button" onClick={() => void refresh()} disabled={checking}>
          <Icon name="refresh" size={15}/>{checking ? 'Checking…' : 'Refresh now'}
        </button></header>
      <ul className="settings-services">
        <ServiceRow name="Workspace service" detail={health?.version ? 'FailureForge API · version ' + health.version : 'Connection to the API that serves projects and saved results.'} state={apiStatus}/>
        {(['libero', 'synthetic'] as const).map(backend => {
          const worker = workerFor(health, backend);
          return <ServiceRow key={backend} name={backend === 'libero' ? 'Robot benchmark worker' : 'Diagnostic worker'}
            detail={backend === 'libero' ? 'Runs the robot policy benchmark on a qualified execution host.' : 'Runs synthetic campaigns to check the software workflow.'}
            state={worker ? worker.online ? 'Online' : 'Offline' : unknown} lastSeen={worker?.last_seen}/>;
        })}
        <ServiceRow name="Robot benchmark qualification" detail="Records whether the execution host passed qualification and camera review."
          state={readiness ? readiness.qualified ? 'Qualified' : 'Pending qualification' : unknown}/>
      </ul>
      <div className="settings-footnote">{lastChecked ? <>Last connection check <time dateTime={lastChecked}>{new Date(lastChecked).toLocaleString(undefined, {
        month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit',
        ...(preferences.timeZone === 'utc' && { timeZone: 'UTC', timeZoneName: 'short' }),
      })}</time></> : 'Waiting for the first connection check.'}</div>
    </section>
    <details className="settings-disclosure"><summary>Setup and benchmark configuration</summary>
      <div className="settings-guidance">
        <h4>Project simulations</h4><p>The workspace service runs supported CPU studies. Open a project to set up its model or run a comparison.</p>
        <a className="text-link" href="#/projects">Open projects<Icon name="chevron" size={14}/></a>
        <h4>Robot benchmarks</h4><p>To enable robot benchmarks, the host operator installs the robotics runtime, completes qualification and camera review, and starts a benchmark worker. CPU project studies can run independently.</p>
        {catalog ? <dl className="settings-config">
          <div><dt>Task</dt><dd>{label(catalog.task.name)}</dd></div>
          <div><dt>Task suite</dt><dd>{catalog.task.suite}</dd></div>
          <div><dt>Policy</dt><dd>{catalog.policy.repo_id}</dd></div>
          <div><dt>Policy revision</dt><dd className="mono">{catalog.policy.revision}</dd></div>
          {catalog.domain?.main_camera_dx_m && <div><dt>Camera offset</dt><dd>{catalog.domain.main_camera_dx_m.map(value => (100 * value).toLocaleString()).join(' to ')} cm</dd></div>}
          {catalog.domain?.light_scale && <div><dt>Lighting multiplier</dt><dd>{catalog.domain.light_scale.map(value => value.toLocaleString()).join(' to ')}×</dd></div>}
        </dl> : <p>{checking ? 'Checking benchmark configuration…' : 'Benchmark configuration is unavailable. Use Refresh now to check again.'}</p>}
      </div>
    </details>
  </div>;
}
