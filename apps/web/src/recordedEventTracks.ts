import type { RunDetail } from './analysisInputs';
import { readMotion } from './motionData.ts';
import { object, spatialField } from './recordedFields.ts';

export type EventTrack = {
  name: string; unit: string; axis: 'time' | 'position'; x: number[]; y: number[];
  start: number; end: number; limit?: number; first: number; peak?: number; peakPosition?: number;
};

function number(value: unknown, factor = 1) {
  return typeof value === 'number' && Number.isFinite(value) ? value * factor : undefined;
}

function track(data: Omit<EventTrack, 'first'>): EventTrack {
  const { limit } = data;
  return { ...data, first: limit === undefined ? -1 : data.y.findIndex(value => value > limit) };
}

export function engineeringTracks(run?: RunDetail | null): EventTrack[] {
  const result = run?.result;
  if (!run || !result || run.status !== 'completed' || run.error || run.assessment_error ||
      object(result.numerical_diagnostics).passed === false) return [];
  const summary = object(result.summary);
  if (run.adapter === 'packaging_lift' || run.adapter === 'packaging_lift_timed_v2') {
    const motion = readMotion(result), endHold = number(object(result.fixture).end_time_s);
    if (motion?.kind !== 'lift' || motion.target === undefined || motion.holdStart === undefined ||
        endHold === undefined || endHold <= motion.holdStart) return [];
    const { target, holdStart, times } = motion;
    const from = times.findIndex(t => t >= holdStart);
    if (from < 0) return [];
    const x = times.slice(from).filter(t => t <= endHold);
    if (!x.length) return [];
    return [track({name: 'Height error during hold', unit: 'mm', axis: 'time',
      x, y: x.map((_, i) => 1000 * Math.abs(motion.height[from + i] - target)),
      start: times[0], end: times.at(-1)!, limit: number(motion.tolerance, 1000), peak: number(summary.max_hold_error_m, 1000)})];
  }
  const field = spatialField(result);
  if (!field || run.adapter !== result.kind) return [];
  const { positions: x, values } = field;
  const common = { axis: 'position' as const, x, start: x[0], end: x.at(-1)! };
  const inputs = object(result.inputs ?? run.inputs);
  if (field.kind === 'rod') return [track({ ...common, name: 'Temperature along the rod', unit: 'K',
    y: values, limit: number(inputs.max_temperature_k), peak: number(summary.continuous_peak_temperature_k),
    peakPosition: number(summary.continuous_peak_position_m) })];
  const tracks = [track({ ...common, name: 'Absolute beam deflection', unit: 'mm',
    y: values.map(v => 1000 * Math.abs(v)), limit: number(inputs.max_displacement_m, 1000),
    peak: number(summary.continuous_max_abs_displacement_m, 1000) })];
  const { stressLeft, stressRight } = field;
  if (stressLeft && stressRight) tracks.push(track({ ...common, name: 'Absolute surface stress', unit: 'MPa',
    y: x.map((_, i) => 1e-6 * Math.max(Math.abs(stressRight[i - 1] ?? 0), Math.abs(stressLeft[i] ?? 0))),
    limit: number(inputs.max_surface_stress_pa, 1e-6), peak: number(summary.continuous_max_surface_stress_pa, 1e-6) }));
  return tracks;
}

/** The camera encoder samples scene time at i/(N-1), then encodes N equally long frames. */
export function frameCoordinate(track: EventTrack, mediaTime: number, duration: number, frames: number) {
  if (!(frames >= 2 && duration > 0)) return;
  // Browsers may round a decoded frame timestamp to the nearest microsecond.
  const i = Math.max(0, Math.min(frames - 1, Math.floor(mediaTime / duration * frames + 1e-4)));
  return track.start + (track.end - track.start) * i / (frames - 1);
}

export function seekTime(track: EventTrack, coordinate: number, duration: number, frames: number) {
  if (!(frames >= 2 && duration > 0)) return;
  const f = (coordinate - track.start) / (track.end - track.start) * (frames - 1);
  // The lift renderer holds the latest saved sample. Seek to the first frame at or after the event.
  const i = track.axis === 'time' ? Math.ceil(f - 1e-10) : Math.round(f);
  return (Math.max(0, Math.min(frames - 1, i)) + .25) * duration / frames;
}

export function sampleAt(track: EventTrack, coordinate: number) {
  if (coordinate < track.x[0] || coordinate > track.x.at(-1)!) return -1;
  let i = 0;
  while (i + 1 < track.x.length && track.x[i + 1] <= coordinate) i++;
  if (track.axis === 'position' && i + 1 < track.x.length &&
      coordinate - track.x[i] > track.x[i + 1] - coordinate) i++;
  return i;
}
