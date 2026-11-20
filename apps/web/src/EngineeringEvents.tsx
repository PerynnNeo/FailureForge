import { useEffect, useId, useState } from 'react';
import type { RefObject } from 'react';
import { frameCoordinate, sampleAt, seekTime } from './recordedEventTracks';
import type { EventTrack } from './recordedEventTracks';
import { fieldColor } from './recordedFields';
import './engineeringEvents.css';

/** Follow displayed frames while playing and native seeks while paused. */
export function useCameraClock(ref: RefObject<HTMLVideoElement | null>, url?: string, ready = true) {
  const [time, setTime] = useState(0);
  useEffect(() => {
    const video = ref.current;
    if (!video || !ready) return;
    const update = () => setTime(video.currentTime);
    let frame = 0;
    const callback: VideoFrameRequestCallback = (_, metadata) => {
      setTime(metadata.mediaTime);
      frame = video.requestVideoFrameCallback(callback);
    };
    if (video.requestVideoFrameCallback) frame = video.requestVideoFrameCallback(callback);
    else video.addEventListener('timeupdate', update);
    video.addEventListener('seeked', update);
    update();
    return () => {
      if (frame) video.cancelVideoFrameCallback(frame);
      video.removeEventListener('seeked', update);
      video.removeEventListener('timeupdate', update);
    };
  }, [ref, url, ready]);
  return time;
}

export type EventSource = { label: string; tracks: EventTrack[]; mediaTime?: number; duration?: number;
  frames?: number; seek?: (mediaTime: number) => void };
const seriesColors = ['#096478', '#a44725'];
const fmt = (value: number) => Number(value.toPrecision(7)).toString();
const axisUnit = (track: EventTrack) => track.axis === 'time' ? 's' : 'm';
const at = (track: EventTrack, index: number) => fmt(track.y[index]) + ' ' + track.unit + ' at ' + fmt(track.x[index]) + ' ' + axisUnit(track);

function plotDomain(values: number[]) {
  const low = Math.min(...values), high = Math.max(...values);
  if (low !== high) return [low, high];
  const padding = Math.max(.001, Math.abs(low) * .001);
  return [low - padding, high + padding];
}

export function EngineeringEvents({ sources }: { sources: EventSource[] }) {
  const titleId = useId();
  const [chosen, setChosen] = useState('');
  const names = sources[0]?.tracks.map(t => t.name).filter(n => sources.every(s => s.tracks.some(t => t.name === n))) ?? [];
  if (!names.length) return null;
  const failed = names.find(n => sources.some(s => s.tracks.some(t => t.name === n && t.first >= 0)));
  const name = names.includes(chosen) ? chosen : failed ?? names[0];
  const tracks = sources.map(s => s.tracks.find(t => t.name === name)!);
  const first = tracks[0], thermal = first.unit === 'K', temporal = first.axis === 'time';
  const axis = temporal ? 'Time from lift start (s)' : thermal ? 'Position from left end (m)' : 'Position from clamp (m)';
  const [xmin, xmax] = plotDomain(tracks.flatMap(t => [t.x[0], t.x.at(-1)!]));
  const limits = [...new Set(tracks.flatMap(t => t.limit === undefined ? [] : [t.limit]))];
  const range = tracks.flatMap(t => [Math.min(...t.y), Math.max(...t.y)]);
  const [ymin, ymax] = plotDomain([...range, ...limits, ...tracks.flatMap(t => t.peak === undefined ? [] : [t.peak])]);
  const X = (v: number) => 55 + 570 * (v - xmin) / (xmax - xmin);
  const Y = (v: number) => 125 - 95 * (v - ymin) / (ymax - ymin);
  const playheads = sources.map((s, i) => s.mediaTime === undefined ? undefined :
    frameCoordinate(tracks[i], s.mediaTime, s.duration ?? 0, s.frames ?? 0));
  const indices = playheads.map((v, i) => v === undefined ? -1 : sampleAt(tracks[i], v));
  // Single footage uses its own field extrema. Compared footage includes both fields and declared limits.
  const cameraDomain = sources.length === 1 ? range : [...range, ...limits];
  const colorMin = Math.min(...cameraDomain), colorMax = Math.max(...cameraDomain);
  return <section className="engineering-events" aria-labelledby={titleId}>
    <header><h4 id={titleId}>{name}</h4>
      {names.length > 1 && <label>Measurement <select value={name} onChange={e => setChosen(e.target.value)}>
        {names.map(n => <option key={n}>{n}</option>)}</select></label>}
    </header>
    <p>{temporal ? 'Absolute difference between platform height and target, evaluated during the recorded hold.' :
      'The camera scans a steady field. Positions run from ' + (thermal ? 'the left end of the rod.' : 'the clamped end of the beam.')}</p>
    {thermal && <div className="event-color-key" aria-label="Temperature color scale">
      <span>{fmt(colorMin)} K</span>
      <i aria-hidden="true" style={{background: colorMin === colorMax ? fieldColor(colorMin, colorMin, colorMax) : undefined}}/>
      <span>{fmt(colorMax)} K</span><span>{sources.length > 1 ? 'Both camera views' : 'Camera color scale'}</span>
    </div>}
    <svg viewBox="0 0 660 169" role="img" aria-label={name + ' in ' + first.unit + ' by ' + axis + '. Dashed lines indicate recorded limits.'}>
      <text x="12" y="16">{first.unit}</text>
      <path d="M55 30V125H625" fill="none" stroke="#82949c"/>
      {[ymin, ymax].map(y => <text key={y} x="50" y={Y(y) + 3} textAnchor="end">{fmt(y)}</text>)}
      <text x="55" y="144">{fmt(xmin)}</text><text x="625" y="144" textAnchor="end">{fmt(xmax)}</text>
      <text x="340" y="159" textAnchor="middle">{axis}</text>
      {limits.map(limit => <g key={limit}>
        <line x1="55" x2="625" y1={Y(limit)} y2={Y(limit)} stroke="#555e63" strokeDasharray="5 3"/>
        <text className="event-limit" x="623" y={Y(limit) - 4} textAnchor="end">Limit {fmt(limit)} {first.unit}</text>
      </g>)}
      {tracks.map((t, i) => <g key={i} stroke={seriesColors[i]}>
        <polyline points={t.x.map((x, j) => X(x) + ',' + Y(t.y[j])).join(' ')} fill="none" strokeWidth="2.3"/>
        {t.first >= 0 && <circle cx={X(t.x[t.first])} cy={Y(t.y[t.first])} r="5" fill="white" strokeWidth="2.5">
          <title>{sources[i].label} · first above limit · {at(t, t.first)}</title></circle>}
        {indices[i] >= 0 && <circle cx={X(t.x[indices[i]])} cy={Y(t.y[indices[i]])} r="3.5" fill={seriesColors[i]}/>}
      </g>)}
    </svg>
    <div className="event-readouts">{tracks.map((t, i) => {
      const { first: crossing, limit } = t, s = sources[i];
      const noun = temporal ? 'hold sample' : 'station';
      const media = crossing < 0 ? undefined : seekTime(t, t.x[crossing], s.duration ?? 0, s.frames ?? 0);
      return <div key={s.label}><strong style={{color: seriesColors[i]}}>{s.label}</strong>
        {limit === undefined ? <p>No acceptance limit was recorded for this measurement.</p> : <>
          <p>Limit ≤ {fmt(limit)} {t.unit}. {crossing < 0 ? 'No recorded ' + noun + ' exceeds it.' :
            <>{crossing === 0 ? 'Already above at the first ' : 'First above-limit '}{noun} · <b>{at(t, crossing)}</b>.</>}</p>
          {crossing > 0 && <small>Preceding {noun} · {at(t, crossing - 1)}.</small>}
        </>}
        {t.peak !== undefined && <small>Solver peak · {fmt(t.peak)} {t.unit}
          {t.peakPosition !== undefined && ' at ' + fmt(t.peakPosition) + ' m'}
          {limit !== undefined && ' (' + fmt(Math.abs(limit - t.peak)) + ' ' + t.unit + (t.peak > limit ? ' over limit)' : ' within limit)')}.
          {crossing < 0 && limit !== undefined && t.peak > limit && ' The exceedance lies between saved samples.'}</small>}
        {s.seek && media !== undefined && <button type="button" className="project-inline-button"
          onClick={() => s.seek?.(media)}>Show event in replay</button>}
        {playheads[i] !== undefined && <small>Camera frame · {indices[i] >= 0 ? at(t, indices[i]) :
          fmt(playheads[i]!) + ' ' + axisUnit(t) + ' outside recorded ' + (temporal ? 'hold' : 'span')}</small>}
      </div>;
    })}</div>
    {tracks.some(t => t.first >= 0) && <small>Open circles mark saved samples. The camera shows the nearest available {temporal ? 'frame at or after the selected time' : 'inspection frame'}.</small>}
  </section>;
}
