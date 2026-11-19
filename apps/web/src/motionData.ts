type Data = Record<string, unknown>;
export type Point3 = [number, number, number];
export type View = 'Isometric' | 'XY' | 'XZ' | 'YZ';
export type JointSeries = { name: string; unit: string; child?: string; values: number[] };
export type Log = { name: string; times: number[]; measured: number[]; predicted?: number[]; command?: number[] };
export type Motion =
  | { kind: 'lift'; times: number[]; height: number[]; head?: number[]; motor?: number[];
      target?: number; tolerance?: number; payload?: number; holdStart?: number }
  | { kind: 'robot'; times: number[]; joints: JointSeries[]; tip?: Point3[]; tipName: string }
  | { kind: 'response'; logs: Log[] }
  | { kind: 'signals'; times: number[]; channels: { name: string; values: number[] }[] };

function record(value: unknown): Data {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Data : {};
}
const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);
const number = (value: unknown) => finite(value) ? value : undefined;
function samples(value: unknown, length: number): number[] | undefined {
  return Array.isArray(value) && value.length === length && value.every(finite) ? value : undefined;
}
function clock(value: unknown): number[] | undefined {
  if (!Array.isArray(value) || value.length < 2 || !value.every((t, i) => finite(t) && (!i || t > value[i-1]))) return;
  return value;
}
function points(value: unknown, length: number): Point3[] | undefined {
  if (!Array.isArray(value) || value.length !== length || !value.every(p => Array.isArray(p) && p.length === 3 && p.every(finite))) return;
  return value as Point3[];
}

export function readMotion(result: Data): Motion | null {
  const series = record(result.series), fixture = record(result.fixture);
  if (result.fixture && 'position_m' in series && ('target_m' in fixture || 'applied_head_force_n' in series)) {
    const times = clock(series.time_s);
    const height = times && samples(series.position_m, times.length);
    if (!times || !height) return null;
    const tolerance = number(fixture.error_limit_m);
    return { kind: 'lift', times, height, head: samples(series.applied_head_force_n, times.length),
      motor: samples(series.actuator_force_n, times.length), target: number(fixture.target_m),
      tolerance: tolerance !== undefined && tolerance >= 0 ? tolerance : undefined,
      holdStart: number(fixture.arrival_deadline_s), payload: number(record(result.summary).payload_kg) };
  }
  const trajectory = record(result.trajectory);
  if (trajectory.joint_positions) {
    const times = clock(trajectory.time_s);
    if (!times) return null;
    const model = record(result.model);
    const metadata = Array.isArray(model.joints) ? model.joints.map(record) : [];
    const joints: JointSeries[] = [];
    for (const [name, values] of Object.entries(record(trajectory.joint_positions))) {
      const valid = samples(values, times.length);
      if (!valid) continue;
      const joint = metadata.find(item => item.name === name);
      const unit = typeof joint?.unit === 'string' ? joint.unit : '';
      joints.push({ name, unit, child: typeof joint?.child === 'string' ? joint.child : undefined, values: valid });
    }
    const tip = points(trajectory.tip_xyz_m, times.length);
    if (!tip && !joints.length) return null;
    return { kind: 'robot', times, joints, tip, tipName: typeof model.tip_link === 'string' ? model.tip_link : 'Tip' };
  }
  const traces = record(result.traces);
  const logs: Log[] = [];
  for (const [key, name] of [['validation', 'Held-out measurements'], ['fit', 'Training measurements']]) {
    const trace = record(traces[key]);
    const times = clock(trace.time_s), measured = times && samples(trace.position_rad, times.length);
    if (times && measured) logs.push({ name, times, measured, predicted: samples(trace.predicted_rad, times.length),
      command: samples(trace.command_rad, times.length) });
  }
  if (logs.length) return { kind: 'response', logs };
  for (const block of [series, trajectory, traces, result]) {
    const times = clock(block.time_s);
    if (!times) continue;
    const channels = [];
    for (const [name, value] of Object.entries(block)) {
      const values = name !== 'time_s' && samples(value, times.length);
      if (values) channels.push({ name, values });
    }
    if (channels.length) return { kind: 'signals', times, channels };
  }
  return null;
}

// Choose an actual recorded sample, including for stepped commands and applied forces.
export function frameAt(times: number[], time: number): number {
  let lo = 0, hi = times.length - 1;
  while (lo < hi) {
    const mid = Math.ceil((lo + hi) / 2);
    if (times[mid] <= time) lo = mid;
    else hi = mid - 1;
  }
  return lo;
}

export type ReplayLink = { name: string; parentIndex: number; positions: Point3[] };
export function readLinks(raw: unknown, times: number[]): ReplayLink[] | null {
  const body = record(raw), returned = samples(body.time_s, times.length);
  if (!returned || !returned.every((t, index) => t === times[index]) || !Array.isArray(body.links) || !body.links.length) return null;
  const entries = body.links.map(record);
  const names = entries.map(link => link.name);
  if (!names.includes(body.root_link) || new Set(names).size !== names.length) return null;
  const links: ReplayLink[] = [];
  for (const entry of entries) {
    const positions = points(entry.xyz_m, times.length), parentIndex = names.indexOf(entry.parent);
    if (typeof entry.name !== 'string' || !positions ||
        (entry.name === body.root_link ? entry.parent !== null : parentIndex < 0 || entry.name === entry.parent)) return null;
    links.push({ name: entry.name, parentIndex, positions });
  }
  return links;
}

export function projectPoint([x, y, z]: Point3, view: View): [number, number] {
  if (view === 'XY') return [x, y];
  if (view === 'XZ') return [x, z];
  if (view === 'YZ') return [y, z];
  return [(x - y) / Math.sqrt(2), (2*z - x - y) / Math.sqrt(6)];
}
