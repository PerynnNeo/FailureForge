import { useEffect, useMemo, useState } from 'react';
import type { Candidate, Domain } from './types';
import { candidateFailureCount } from './candidateOutcomes';

const outcomeColors = ['#32846e', '#d2912b', '#cb534d'];
export function ScatterPlot({ candidates, domain, selected, onSelect }: { candidates: Candidate[]; domain: Domain; selected?: string; onSelect: (id: string) => void }) {
  const width = 720, height = 370, pad = { left: 68, right: 28, top: 22, bottom: 59 };
  const innerW = width - pad.left - pad.right, innerH = height - pad.top - pad.bottom;
  const dx = domain.main_camera_dx_m, light = domain.light_scale;
  const sx = (v: number) => pad.left + (v - dx[0]) / (dx[1] - dx[0]) * innerW;
  const sy = (v: number) => pad.top + innerH - (v - light[0]) / (light[1] - light[0]) * innerH;
  return <div className="scatter-wrap" data-tour="campaign-plot">
    <svg viewBox={`0 0 ${width} ${height}`} className="scatter" role="img" aria-label={`Measured camera and lighting changes. ${candidates.length} proposed candidates. Colored points have completed paired evaluations; gray points are unscored. No interpolation is shown.`}>
      <defs><pattern id="plot-dots" width="15" height="15" patternUnits="userSpaceOnUse"><circle cx="1" cy="1" r=".7" fill="#c7d1d9"/></pattern></defs>
      <rect x={pad.left} y={pad.top} width={innerW} height={innerH} fill="#f8fafb"/>
      <rect x={pad.left} y={pad.top} width={innerW} height={innerH} fill="url(#plot-dots)" opacity=".7"/>
      {[0, .25, .5, .75, 1].map(f => <g key={f}>
        <line x1={pad.left} y1={pad.top + f * innerH} x2={width - pad.right} y2={pad.top + f * innerH} stroke="#e0e6eb"/>
        <text x={pad.left - 13} y={pad.top + f * innerH + 5} textAnchor="end">{(light[1] - f * (light[1] - light[0])).toFixed(2)}×</text>
        <line x1={pad.left + f * innerW} y1={pad.top} x2={pad.left + f * innerW} y2={height - pad.bottom} stroke="#e0e6eb"/>
        <text x={pad.left + f * innerW} y={height - pad.bottom + 25} textAnchor="middle">{((dx[0] + f * (dx[1] - dx[0])) * 100).toFixed(1)}</text>
      </g>)}
      <text x={pad.left + innerW / 2} y={height - 9} textAnchor="middle" className="axis-label">Main camera displacement (cm)</text>
      <text transform={`translate(17 ${pad.top + innerH / 2}) rotate(-90)`} textAnchor="middle" className="axis-label">Lighting multiplier</text>
      <path d={`M${sx(0) - 7} ${sy(1)}h14M${sx(0)} ${sy(1) - 7}v14`} stroke="#263f50" strokeWidth="1.8"/>
      {candidates.filter(c => c.scene_change).map((c, index) => {
        const score = candidateFailureCount(c);
        const fill = score === null ? '#a0acb7' : outcomeColors[score];
        return <g key={c.id} className="chart-point" role="button" tabIndex={0} aria-label={`Candidate ${(c.proposal_index ?? c.index ?? index) + 1}: camera ${(c.scene_change.main_camera_dx_m * 100).toFixed(2)} centimetres, lighting ${c.scene_change.light_scale.toFixed(3)}, ${score === null ? 'incomplete' : `${score} failed states`}`} onClick={() => onSelect(c.id)} onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSelect(c.id); } }}>
          {selected === c.id && <circle cx={sx(c.scene_change.main_camera_dx_m)} cy={sy(c.scene_change.light_scale)} r="12" fill="none" stroke={fill} strokeWidth="1.5"/>}
          <circle cx={sx(c.scene_change.main_camera_dx_m)} cy={sy(c.scene_change.light_scale)} r="6" fill={fill} stroke="white" strokeWidth="2"/>
          <title>{`Candidate ${index + 1} · ${score === null ? 'incomplete' : `${score}/2 failed states`}`}</title>
        </g>;
      })}
      {!candidates.length && <g><rect x="197" y="132" width="340" height="61" rx="7" fill="white" stroke="#dce4e9"/><text x="367" y="158" textAnchor="middle" className="plot-empty-title">Your experiment starts here</text><text x="367" y="178" textAnchor="middle">Measured configurations appear as they complete.</text></g>}
    </svg>
    <div className="chart-legend"><span><i style={{ background: outcomeColors[0] }}/>0 failed states</span><span><i style={{ background: outcomeColors[1] }}/>1 failed state</span><span><i style={{ background: outcomeColors[2] }}/>2 failed states</span><span><i style={{ background: '#a0acb7' }}/>Unscored</span><span><b>+</b> Reference</span></div>
  </div>;
}

export function TraceChart({ samples, xLabel = 'Control step' }: { samples: Array<Record<string, unknown>>; xLabel?: string }) {
  const [compact, setCompact] = useState(false);
  useEffect(() => {
    const media = window.matchMedia('(max-width: 760px)');
    const resize = () => setCompact(media.matches);
    resize(); media.addEventListener('change', resize);
    return () => media.removeEventListener('change', resize);
  }, []);
  const series = useMemo(() => {
    const keys = samples.length ? Object.keys(samples[0]).filter(k => typeof samples[0][k] === 'number' && !['step', 'time', 'time_s', 'timestamp', 'sim_time', 'action_index'].includes(k)).slice(0, 3) : [];
    return keys.map(key => ({ key, values: samples.map((p, index) => ({ x: typeof p.step === 'number' ? p.step : index, y: Number(p[key]) })).filter(p => Number.isFinite(p.y)) }));
  }, [samples]);
  if (!series.length) return <p className="muted small">No scalar trace samples are available for plotting. The export preserves the original episode data.</p>;
  const all = series.flatMap(s => s.values);
  if (!all.length) return <p className="muted small">No finite samples are available.</p>;
  const minY = Math.min(...all.map(p => p.y)), maxY = Math.max(...all.map(p => p.y));
  const maxX = Math.max(...all.map(p => p.x)) || 1;
  const width = compact ? 390 : 700, left = 68, right = width - 20;
  const x = (v: number) => left + v / maxX * (right - left), y = (v: number) => maxY === minY ? 97.5 : 165 - (v - minY) / (maxY - minY) * 135;
  const colors = ['#3e7799', '#da7948', '#5c9480'];
  return <div className="trace-chart"><svg viewBox={`0 0 ${width} 210`} role="img" aria-label={`Plot of ${series.map(s => s.key).join(', ')}`}>
    {(minY === maxY ? [.5] : [0, .5, 1]).map(f => <g key={f}><line x1={left} x2={right} y1={30 + 135 * f} y2={30 + 135 * f} stroke="#e5eaf0"/><text x={left - 7} y={35 + 135 * f} textAnchor="end">{Number((maxY - (maxY - minY) * f).toPrecision(3))}</text></g>)}
    {series.map((s, index) => <path key={s.key} d={s.values.map((v, i) => `${i ? 'L' : 'M'}${x(v.x).toFixed(2)},${y(v.y).toFixed(2)}`).join(' ')} stroke={colors[index]} strokeWidth="2" fill="none"/>)}
    <text x={left} y="188">0</text><text x={right} y="188" textAnchor="end">{Number(maxX.toPrecision(4))}</text><text x={(left + right) / 2} y="205" textAnchor="middle">{xLabel}</text>
  </svg><div className="chart-legend">{series.map((s, i) => <span key={s.key}><i style={{ background: colors[i] }}/>{s.key.replaceAll('_', ' ')}</span>)}</div></div>;
}
