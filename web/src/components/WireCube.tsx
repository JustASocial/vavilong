import { useEffect, useState } from "react";

/** A wireframe cube: eight dots joined by edges, tumbling in 3D. */
const VERTICES: [number, number, number][] = [
  [-1, -1, -1],
  [1, -1, -1],
  [1, 1, -1],
  [-1, 1, -1],
  [-1, -1, 1],
  [1, -1, 1],
  [1, 1, 1],
  [-1, 1, 1],
];

const EDGES: [number, number][] = [
  [0, 1],
  [1, 2],
  [2, 3],
  [3, 0],
  [4, 5],
  [5, 6],
  [6, 7],
  [7, 4],
  [0, 4],
  [1, 5],
  [2, 6],
  [3, 7],
];

const FOCUS = 4.2;
const SPREAD = 11.2;

export function WireCube({ size = 30 }: { size?: number }) {
  const [time, setTime] = useState(0);

  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    let frame = 0;
    let last = performance.now();
    const loop = (now: number) => {
      const delta = Math.min(64, now - last);
      last = now;
      setTime((value) => value + delta);
      frame = requestAnimationFrame(loop);
    };
    frame = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(frame);
  }, []);

  const yaw = time * 0.0011;
  const pitch = 0.52 + Math.sin(time * 0.00042) * 0.38;
  const cosY = Math.cos(yaw);
  const sinY = Math.sin(yaw);
  const cosX = Math.cos(pitch);
  const sinX = Math.sin(pitch);

  const rotated = VERTICES.map(([x, y, z]) => {
    const x1 = x * cosY + z * sinY;
    const z1 = z * cosY - x * sinY;
    const y1 = y * cosX - z1 * sinX;
    const z2 = y * sinX + z1 * cosX;
    return { x: x1, y: y1, z: z2 };
  });

  const points = rotated.map((point) => {
    const depth = FOCUS / (FOCUS + point.z);
    return {
      x: 16 + point.x * depth * SPREAD,
      y: 16 + point.y * depth * SPREAD,
      z: point.z,
    };
  });

  const lines = EDGES.map(([from, to]) => {
    const mid = (points[from].z + points[to].z) / 2;
    return { from, to, near: Math.min(1, Math.max(0, (1.7 - mid) / 3.4)) };
  }).sort((a, b) => a.near - b.near);

  return (
    <svg viewBox="0 0 32 32" width={size} height={size} aria-hidden focusable="false">
      {lines.map(({ from, to, near }) => (
        <line
          key={`${from}-${to}`}
          x1={points[from].x}
          y1={points[from].y}
          x2={points[to].x}
          y2={points[to].y}
          stroke="currentColor"
          strokeWidth={1.2}
          strokeLinecap="round"
          opacity={0.35 + near * 0.6}
        />
      ))}
      {points.map((point, index) => (
        <circle
          key={index}
          cx={point.x}
          cy={point.y}
          r={1.2 + Math.min(1, Math.max(0, (1.7 - point.z) / 3.4)) * 0.8}
          fill="currentColor"
          opacity={0.5 + Math.min(1, Math.max(0, (1.7 - point.z) / 3.4)) * 0.45}
        />
      ))}
    </svg>
  );
}
