import { useEffect, useRef, useState } from 'react';

type View = 'isometric' | 'top' | 'front' | 'right';
type Point = [number, number, number];
function project([x, y, z]: Point, view: View, angle: number): Point {
  if (view === 'top') return [x, -y, z];
  if (view === 'front') return [x, -z, -y];
  if (view === 'right') return [y, -z, x];
  const theta = angle * Math.PI / 180;
  const horizontal = x * Math.cos(theta) - y * Math.sin(theta);
  const depth = x * Math.sin(theta) + y * Math.cos(theta);
  return [horizontal, depth / Math.sqrt(3) - z * Math.sqrt(2/3), depth * Math.sqrt(2/3) + z / Math.sqrt(3)];
}

export default function MeshPreview({ triangles, total }: { triangles: unknown[]; total: number }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [view, setView] = useState<View>('isometric');
  const [angle, setAngle] = useState(45);
  const [turning, setTurning] = useState(false);
  useEffect(() => {
    if (!turning) return;
    const timer = window.setInterval(() => setAngle(previous => (previous + 2) % 360), 60);
    return () => window.clearInterval(timer);
  }, [turning]);
  useEffect(() => {
    const context = canvas.current?.getContext('2d');
    if (!context) return;
    const width = context.canvas.width, height = context.canvas.height;
    context.clearRect(0, 0, width, height);
    const faces: Point[][] = [];
    for (const face of triangles) {
      if (!Array.isArray(face) || face.length !== 3 ||
        !face.every(vertex => Array.isArray(vertex) && vertex.length === 3 && vertex.every(Number.isFinite))) continue;
      faces.push(face as Point[]);
    }
    if (!faces.length) return;
    const points = faces.flat();
    const xs = points.map(point => point[0]), ys = points.map(point => point[1]);
    const zs = points.map(point => point[2]);
    const center = [xs, ys, zs].map(axis => (Math.max(...axis) + Math.min(...axis)) / 2);
    const radius = Math.max(...points.map(([x,y,z]) => Math.hypot(x-center[0], y-center[1], z-center[2])));
    const scale = (height - 44) / (2 * radius || 1);
    const projected = faces.map(face => face.map(([x,y,z]) => project([x-center[0], y-center[1], z-center[2]], view, angle)));
    const depth = (face: Point[]) => face[0][2] + face[1][2] + face[2][2];
    projected.sort((a, b) => depth(a) - depth(b));
    context.lineWidth = 1.3;
    context.strokeStyle = '#476776'; context.fillStyle = '#c4d6dd';
    for (const face of projected) {
      context.beginPath();
      face.forEach(([x, y], index) => {
        const px = width / 2 + x * scale;
        const py = height / 2 + y * scale;
        if (index === 0) context.moveTo(px, py); else context.lineTo(px, py);
      });
      context.closePath(); context.fill(); context.stroke();
    }
  }, [triangles, view, angle]);
  return <figure className="analysis-mesh field-inspection"><h4>Inspect the recorded STL mesh</h4><label className="project-field"><span>STL preview</span>
    <select value={view} onChange={event => { setTurning(false); setView(event.target.value as View); }}>
      <option value="isometric">Orbit view</option><option value="top">Top</option>
      <option value="front">Front</option><option value="right">Right side</option>
    </select></label><canvas ref={canvas} width={880} height={440} role="img" aria-label={`${view === 'isometric' ? 'Orbit ' + angle + ' degrees' : view} projection of the recorded STL triangles`}/>
    <div className="inspection-controls"><button type="button" className="button secondary" onClick={() => {
      setView('isometric'); setTurning(!turning);
    }}>{turning ? 'Pause rotation' : 'Rotate view'}</button>
      <label>View angle {angle}°<input aria-label="Mesh viewing angle" type="range" min="0" max="359" value={angle}
        onChange={event => { setView('isometric'); setTurning(false); setAngle(Number(event.target.value)); }}/></label>
    </div>
    <figcaption>{triangles.length} of {total} mesh triangles displayed. The viewing angle rotates around the static geometry.</figcaption>
  </figure>;
}
