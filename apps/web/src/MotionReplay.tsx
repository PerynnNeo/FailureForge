import { useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { Icon } from './components';
import { frameAt, projectPoint, readLinks, readMotion } from './motionData';
import type { JointSeries, Log, Motion, Point3, ReplayLink, View } from './motionData';
import './motionReplay.css';

const decimal = new Intl.NumberFormat('en', { maximumFractionDigits: 4 });
const stamp = new Intl.NumberFormat('en', { minimumFractionDigits: 2, maximumFractionDigits: 4 });
const value = (v: number, unit = '') => decimal.format(v) + (unit ? ' ' + unit : '');
const teal = '#167b78', orange = '#c86128';
type Reading = { name: string; text: string; color?: string };

function Readings({ items }: { items: Reading[] }) {
  return <dl className="motion-readings">{items.map(item => <div key={item.name}>
    <dt>{item.color && <i aria-hidden="true" style={{ background: item.color }}/>}{item.name}</dt>
    <dd>{item.text}</dd>
  </div>)}</dl>;
}

function Player({ times, title, tool, children }: {
  times: number[]; title: string; tool?: ReactNode; children: (frame: number) => ReactNode;
}) {
  const [frame, setFrame] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [rate, setRate] = useState(1);
  const index = Math.min(frame, times.length - 1);
  const cursor = useRef(0);
  const section = useRef<HTMLElement>(null);
  function seek(next: number) { cursor.current = next; setFrame(next); }
  useEffect(() => {
    if (!playing) return;
    const startTime = times[Math.min(cursor.current, times.length - 1)];
    const startTick = performance.now();
    let request = 0;
    function tick(now: number) {
      if (document.hidden || section.current?.closest('[hidden]')) { setPlaying(false); return; }
      const t = startTime + (now - startTick) * rate / 1000;
      seek(frameAt(times, t));
      if (t >= times[times.length - 1]) setPlaying(false);
      else request = requestAnimationFrame(tick);
    }
    const onVisibility = () => { if (document.hidden) setPlaying(false); };
    request = requestAnimationFrame(tick);
    document.addEventListener('visibilitychange', onVisibility);
    return () => { cancelAnimationFrame(request); document.removeEventListener('visibilitychange', onVisibility); };
  }, [playing, times, rate]);
  const elapsed = times[index] - times[0], duration = times[times.length - 1] - times[0];
  return <section className="motion-replay" ref={section} aria-label="Motion replay">
    <header><div><h4>Motion replay</h4><p>{title}</p></div>{tool}</header>
    {children(index)}
    <div className="motion-controls">
      <button type="button" className="motion-play" aria-label={playing ? 'Pause motion replay' : 'Play motion replay'}
        onClick={() => { if (!playing && index === times.length - 1) seek(0); setPlaying(!playing); }}>
        <Icon name={playing ? 'pause' : 'play'} size={17}/><span>{playing ? 'Pause' : 'Play'}</span>
      </button>
      <input type="range" min={0} max={times.length - 1} step={1} value={index} aria-label="Replay frame"
        aria-valuetext={`${stamp.format(elapsed)} seconds elapsed, sample ${index + 1} of ${times.length}`}
        onChange={event => { setPlaying(false); seek(Number(event.target.value)); }}/>
      <output className="motion-time" aria-label="Playback time" aria-live="off">{stamp.format(elapsed)} / {stamp.format(duration)} s</output>
      <select value={rate} aria-label="Playback speed" onChange={event => setRate(Number(event.target.value))}>
        {[0.25, 0.5, 1, 2].map(speed => <option key={speed} value={speed}>{speed}×</option>)}
      </select>
    </div>
  </section>;
}

type Lift = Extract<Motion, { kind: 'lift' }>;
function LiftReplay({ data }: { data: Lift }) {
  const [bottom, top] = useMemo(() => {
    let low = data.target === undefined ? 0 : Math.min(0, data.target - (data.tolerance ?? 0));
    let high = data.target === undefined ? 0 : Math.max(0, data.target + (data.tolerance ?? 0));
    for (const z of data.height) { low = Math.min(low, z); high = Math.max(high, z); }
    return [low, high];
  }, [data]);
  const y = (m: number) => 184 - 108 * (m - bottom) / (top - bottom || 1);
  const title = data.payload === undefined ? 'Lift carriage · side view' : `Lift carriage · ${value(data.payload, 'kg')} payload · side view`;
  return <Player times={data.times} title={title}>{frame => {
    const height = data.height[frame], carriage = y(height), head = data.head?.[frame], motor = data.motor?.[frame];
    const parcelHeight = data.payload !== undefined && data.payload > 0 ? 27 : 0;
    const arrowEnd = carriage - parcelHeight - 5;
    const arrowSize = Math.max(8, Math.min(37, 7 * (head ?? 0)));
    const readings: Reading[] = [{ name: 'Carriage height', text: value(1000 * height, 'mm'), color: teal }];
    if (data.target !== undefined) readings.push({ name: 'Target height', text: value(1000 * data.target) +
      (data.tolerance === undefined ? ' mm' : ' ± ' + value(1000 * data.tolerance, 'mm')) });
    if (head !== undefined) readings.push({ name: 'Head force ↓', text: value(head, 'N'), color: orange });
    if (motor !== undefined) readings.push({ name: 'Motor force', text: value(motor, 'N') });
    return <>
      <div className="motion-screen">
        <svg viewBox="0 0 430 214" aria-label="Side view showing sampled carriage height and applied head force" role="img">
          {data.holdStart !== undefined && <text className="motion-svg-label" x="410" y="23" textAnchor="end">
            {data.times[frame] < data.holdStart ? 'Lift phase' : 'Hold phase'}</text>}
          <g className="motion-axis">
            <path d="M63 57V191M59 184h9M59 76h9"/>
            <text x="53" y="188" textAnchor="end">{value(bottom * 1000)}</text>
            <text x="53" y="80" textAnchor="end">{value(top * 1000)}</text>
            <text x="63" y="43" textAnchor="middle">mm</text>
          </g>
          <path d="M109 44v153h17V44z" fill="#c4d2d8" stroke="#758a94" strokeWidth="1.5"/>
          <path d="M117 46v149" stroke="#f1f5f4" strokeWidth="3"/>
          <path d="M92 197h153l8 7H84z" fill="#7f949c" stroke="#617780"/>
          {data.target !== undefined && <g>
            {data.tolerance !== undefined && <rect x="136" width="203" y={y(data.target + data.tolerance)}
              height={y(data.target - data.tolerance) - y(data.target + data.tolerance)} fill="#a1cec0" opacity=".44"/>}
            <path d={`M136 ${y(data.target)}H340`} stroke="#398674" strokeDasharray="5 4"/>
            <text x="347" y={y(data.target)+4} className="motion-svg-label">Target</text>
          </g>}
          <g transform={`translate(0 ${carriage})`}>
            <rect x="102" y="-1" width="31" height="15" rx="3" fill="#3e5963"/>
            <path d="M124 0h153v7l-9 3H124z" fill={teal} stroke="#116460" strokeWidth="1.5"/>
            <circle cx="117" cy="6" r="3" fill="#bccbd0"/>
            {parcelHeight > 0 && <g>
              <rect x="169" y={-parcelHeight} width="69" height={parcelHeight} rx="2" fill="#d9a66d" stroke="#9e744b"/>
              <path d={`M198 ${-parcelHeight}h10v10h-10z`} fill="#f1d4a7"/>
            </g>}
            <path d="M286 0h13" stroke={teal} strokeWidth="2"/>
            <circle cx="286" cy="0" r="3.5" fill={teal}/>
          </g>
          {head !== undefined && head > 0 && <g stroke={orange} strokeWidth="3.5" strokeLinecap="round" fill="none">
            <path d={`M204 ${arrowEnd-arrowSize}v${arrowSize}m-5 -5 5 5 5 -5`}/>
          </g>}
        </svg>
      </div>
      <Readings items={readings}/>
    </>;
  }}</Player>;
}

type Hand = { name: string; angle: number; color: string; length: number };
function Dial({ hands }: { hands: Hand[] }) {
  return <svg className="motion-dial" viewBox="0 0 220 172" role="img" aria-label="Angular position in the joint frame">
    <circle cx="110" cy="85" r="59" fill="#f8fbfb" stroke="#b5c6c9" strokeWidth="2"/>
    {Array.from({ length: 24 }, (_, i) => <path key={i} d={i%6 === 0 ? 'M162 85h7' : 'M165 85h4'}
      stroke="#8da4aa" strokeWidth={i%6 === 0 ? 2 : 1} transform={`rotate(${15*i} 110 85)`}/>)}
    <text x="177" y="89" className="motion-svg-label">0</text>
    {hands.map(hand => <path key={hand.name} d={`M110 85h${hand.length}`}
      transform={`rotate(${-hand.angle * 180 / Math.PI} 110 85)`} stroke={hand.color} strokeWidth="4" strokeLinecap="round"/>)}
    <circle cx="110" cy="85" r="5" fill="#324f59"/>
  </svg>;
}

function ResponseReplay({ logs }: { logs: Log[] }) {
  const [selected, setSelected] = useState(0);
  const log = logs[selected] ?? logs[0];
  const chooser = logs.length > 1 && <select aria-label="Response recording" value={selected}
    onChange={event => setSelected(Number(event.target.value))}>{logs.map((item, i) => <option key={item.name} value={i}>{item.name}</option>)}</select>;
  return <Player key={log.name} times={log.times} title={logs.length > 1 ? 'Measured joint response · angular schematic' : log.name + ' · angular schematic'} tool={chooser}>{frame => {
    const hands: Hand[] = [];
    if (log.command) hands.push({ name: 'Command', angle: log.command[frame], color: '#788891', length: 55 });
    if (log.predicted) hands.push({ name: 'Predicted', angle: log.predicted[frame], color: orange, length: 44 });
    hands.push({ name: 'Measured', angle: log.measured[frame], color: teal, length: 34 });
    return <><div className="motion-screen"><Dial hands={hands}/></div>
      <Readings items={hands.map(hand => ({ name: hand.name, color: hand.color, text: value(hand.angle, 'rad') }))}/></>;
  }}</Player>;
}

function CoordinateTrace({ values, times, frame, unit }: { values: number[]; times: number[]; frame: number; unit: string }) {
  const plot = useMemo(() => {
    let min = Infinity, max = -Infinity;
    for (const v of values) { min = Math.min(min, v); max = Math.max(max, v); }
    const x = (i: number) => 28 + 344 * (times[i] - times[0]) / (times[times.length - 1] - times[0]);
    const y = (i: number) => max === min ? 86 : 144 - 112 * (values[i] - min) / (max - min);
    return { min, max, x, y, line: values.map((_, i) => x(i) + ',' + y(i)).join(' ') };
  }, [values, times]);
  return <svg viewBox="0 0 430 172" role="img" aria-label="Recorded values over time with current sample marked">
    <path d="M28 32v112h344" fill="none" stroke="#9fb3bb"/>
    <polyline points={plot.line} fill="none" stroke={teal} strokeWidth="2"/>
    <path d={`M${plot.x(frame)} 25v122`} stroke={orange} strokeDasharray="3 3"/>
    <circle cx={plot.x(frame)} cy={plot.y(frame)} r="5" fill={orange} stroke="white"/>
    <text className="motion-svg-label" x="380" y="37">{value(plot.max)}</text>
    {plot.min !== plot.max && <text className="motion-svg-label" x="380" y="148">{value(plot.min)}</text>}
    {unit && <text className="motion-svg-label" x="28" y="19">{unit}</text>}
  </svg>;
}

type Robot = Extract<Motion, { kind: 'robot' }>;
function RobotStage({ data, links, view, joint, frame }: {
  data: Robot; links: ReplayLink[] | null; view: View; joint?: JointSeries; frame: number;
}) {
  const scene = useMemo(() => {
    let xMin = Infinity, xMax = -Infinity, yMin = Infinity, yMax = -Infinity;
    for (const trace of [...(links ?? []).map(link => link.positions), data.tip ?? []]) {
      for (const point of trace) {
        const [x, y] = projectPoint(point, view);
        xMin = Math.min(xMin, x); xMax = Math.max(xMax, x);
        yMin = Math.min(yMin, y); yMax = Math.max(yMax, y);
      }
    }
    const spanPerPixel = Math.max((xMax - xMin) / 322, (yMax - yMin) / 129);
    const zoom = spanPerPixel > 0 ? 1 / spanPerPixel : 1;
    const at = (point: Point3) => {
      const [x, y] = projectPoint(point, view);
      return [215 + (x - (xMax + xMin)/2) * zoom, 93 - (y - (yMax + yMin)/2) * zoom];
    };
    return { at, trail: data.tip?.map(p => at(p).join(',')).join(' ') };
  }, [data, links, view]);
  const positions = links?.map(link => scene.at(link.positions[frame]));
  const tip = data.tip && scene.at(data.tip[frame]);
  return <svg viewBox="0 0 430 186" role="img" aria-label={links ? 'Recorded robot link positions and tool path' : 'Recorded tool path and current position'}>
    {scene.trail && <polyline points={scene.trail} fill="none" stroke={teal} strokeDasharray="3 3" strokeWidth="2"/>}
    {positions && links?.map((link, i) => {
      const parent = positions[link.parentIndex], [x, y] = positions[i];
      return parent && <line key={link.name} x1={parent[0]} y1={parent[1]} x2={x} y2={y}
        stroke="#536f7b" strokeWidth="5" strokeLinecap="round"/>;
    })}
    {positions && links?.map((link, i) => <circle key={link.name} cx={positions[i][0]} cy={positions[i][1]} r="3.7"
      fill={link.name === joint?.child ? orange : '#f7fbfa'} stroke="#49636e" strokeWidth="1.5"><title>{link.name}</title></circle>)}
    {tip && <circle cx={tip[0]} cy={tip[1]} r="5.3" fill={teal} stroke="white" strokeWidth="1.5"><title>{data.tipName}</title></circle>}
  </svg>;
}

function JointGauge({ joint, frame }: { joint: JointSeries; frame: number }) {
  const bounds = useMemo(() => {
    let low = joint.values[0], high = low;
    for (const v of joint.values) { low = Math.min(low, v); high = Math.max(high, v); }
    return { low, high };
  }, [joint]);
  if (joint.unit === 'rad') return <Dial hands={[{ name: joint.name, angle: joint.values[frame], length: 50, color: orange }]}/>;
  const width = bounds.high - bounds.low;
  const x = width ? 40 + 220 * (joint.values[frame] - bounds.low) / width : 150;
  return <svg viewBox="0 0 300 136" role="img" aria-label="Joint coordinate along its recorded range">
    <path d="M40 67h220" stroke="#7d959e" strokeWidth="5"/>
    <path d="M40 55v24m220 -24v24" stroke="#5e7982" strokeWidth="2"/>
    <rect x={x-8} y="56" width="16" height="22" rx="3" fill={orange}/>
    <text x="40" y="102" className="motion-svg-label" textAnchor="middle">{value(bounds.low, joint.unit)}</text>
    {width > 0 && <text x="260" y="102" className="motion-svg-label" textAnchor="middle">{value(bounds.high, joint.unit)}</text>}
  </svg>;
}

function RobotReplay({ data, geometryUrl }: { data: Robot; geometryUrl?: string }) {
  const [selected, setSelected] = useState(''), [view, setView] = useState<View>('Isometric');
  const [geometry, setGeometry] = useState<{ url: string; body: unknown } | null>(null);
  useEffect(() => {
    if (!geometryUrl) return;
    const controller = new AbortController();
    void fetch(geometryUrl, { signal: controller.signal }).then(async response => {
      if (!response.ok) return;
      const body: unknown = await response.json();
      if (!controller.signal.aborted) setGeometry({ url: geometryUrl, body });
    }).catch(() => { /* The verified joint and tip traces remain available. */ });
    return () => controller.abort();
  }, [geometryUrl]);
  const links = useMemo(() => geometry && geometry.url === geometryUrl ? readLinks(geometry.body, data.times) : null,
    [geometry, geometryUrl, data.times]);
  const joint = data.joints.find(j => j.name === selected) ?? data.joints[0];
  const spatial = !!(links || data.tip);
  const title = links ? 'Robot link-frame schematic' : data.tip ? 'Recorded tip path' : 'Joint-coordinate schematic';
  const tools = <div className="motion-selects">
    {data.joints.length > 1 && <select aria-label="Replay joint" value={joint.name} onChange={event => setSelected(event.target.value)}>
      {data.joints.map(j => <option key={j.name}>{j.name}</option>)}</select>}
    {spatial && <select aria-label="Replay projection" value={view} onChange={event => setView(event.target.value as View)}>
      {(['Isometric', 'XY', 'XZ', 'YZ'] as const).map(v => <option key={v}>{v}</option>)}</select>}
  </div>;
  return <Player times={data.times} title={title} tool={tools}>{frame => {
    const readings: Reading[] = joint ? [{ name: joint.name, text: value(joint.values[frame], joint.unit), color: orange }] : [];
    if (data.tip) readings.push({ name: data.tipName + ' · X / Y / Z', color: teal,
      text: data.tip[frame].map(v => decimal.format(v * 1000)).join(' / ') + ' mm' });
    return <>
      <div className="motion-views">
        {spatial && <div className="motion-screen"><RobotStage data={data} links={links} view={view} joint={joint} frame={frame}/></div>}
        {!links && joint && <div className="motion-screen"><JointGauge joint={joint} frame={frame}/></div>}
      </div>
      <Readings items={readings}/>
    </>;
  }}</Player>;
}

function SignalReplay({ data }: { data: Extract<Motion, { kind: 'signals' }> }) {
  const [name, setName] = useState('');
  const channel = data.channels.find(c => c.name === name) ?? data.channels[0];
  return <Player times={data.times} title="Recorded signal over time" tool={data.channels.length > 1 &&
    <select aria-label="Replay signal" value={channel.name} onChange={event => setName(event.target.value)}>
      {data.channels.map(c => <option key={c.name}>{c.name}</option>)}</select>}>{frame => <>
    <div className="motion-screen"><CoordinateTrace times={data.times} values={channel.values} frame={frame} unit=""/></div>
    <Readings items={[{ name: channel.name, text: value(channel.values[frame]), color: teal }]}/>
  </>}</Player>;
}

export function MotionReplay({ result, geometryUrl }: { result: Record<string, unknown>; geometryUrl?: string }) {
  const data = useMemo(() => readMotion(result), [result]);
  if (!data) return null;
  switch (data.kind) {
    case 'lift': return <LiftReplay data={data}/>;
    case 'robot': return <RobotReplay data={data} geometryUrl={geometryUrl}/>;
    case 'response': return <ResponseReplay logs={data.logs}/>;
    case 'signals': return <SignalReplay data={data}/>;
  }
}
