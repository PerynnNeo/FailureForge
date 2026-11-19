import { useEffect, useRef, useState } from 'react';

type View = 'isometric' | 'top' | 'front' | 'right';
type Point = [number, number, number];
function project([x, y, z]: Point, view: View): Point {
  if (view === 'top') return [x, -y, z];
  if (view === 'front') return [x, -z, -y];
  if (view === 'right') return [y, -z, x];
  return [(x - y) / Math.sqrt(2), (x + y - 2 * z) / Math.sqrt(6), (x + y + z) / Math.sqrt(3)];
}

export default function MeshPreview({ triangles, total }: { triangles: unknown[]; total: number }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [view, setView] = useState<View>('isometric');
  useEffect(() => {
    const context = canvas.current?.getContext('2d');
    if (!context) return;
    const width = context.canvas.width, height = context.canvas.height;
    context.clearRect(0, 0, width, height);
    const faces: Point[][] = [];
    for (const face of triangles) {
      if (!Array.isArray(face) || face.length !== 3 ||
        !face.every(vertex => Array.isArray(vertex) && vertex.length === 3 && vertex.every(Number.isFinite))) continue;
      faces.push((face as Point[]).map(point => project(point, view)));
    }
    if (!faces.length) return;
    const points = faces.flat();
    const xs = points.map(point => point[0]), ys = points.map(point => point[1]);
    const minX = Math.min(...xs), minY = Math.min(...ys), maxX = Math.max(...xs), maxY = Math.max(...ys);
    const scale = Math.min((width - 52) / (maxX - minX || Number.EPSILON), (height - 44) / (maxY - minY || Number.EPSILON));
    const depth = (face: Point[]) => face[0][2] + face[1][2] + face[2][2];
    faces.sort((a, b) => depth(a) - depth(b));
    context.lineWidth = 1.3;
    context.strokeStyle = '#476776'; context.fillStyle = '#c4d6dd';
    for (const face of faces) {
      context.beginPath();
      face.forEach(([x, y], index) => {
        const px = width / 2 + (x - (minX + maxX) / 2) * scale;
        const py = height / 2 + (y - (minY + maxY) / 2) * scale;
        if (index === 0) context.moveTo(px, py); else context.lineTo(px, py);
      });
      context.closePath(); context.fill(); context.stroke();
    }
  }, [triangles, view]);
  return <figure className="analysis-mesh"><label className="project-field"><span>STL preview</span>
    <select value={view} onChange={event => setView(event.target.value as View)}>
      <option value="isometric">Isometric view</option><option value="top">Top</option>
      <option value="front">Front</option><option value="right">Right side</option>
    </select></label><canvas ref={canvas} width={880} height={440} aria-label={`${view} projection of the STL triangles`}/>
    <figcaption>{triangles.length} of {total} mesh triangles displayed.</figcaption>
  </figure>;
}
