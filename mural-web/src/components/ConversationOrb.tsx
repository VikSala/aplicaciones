import React, { useEffect, useMemo, useState } from 'react';

type OrbState = 'idle' | 'listening' | 'thinking' | 'speaking';

interface ConversationOrbProps {
  state: OrbState;
  onClick?: () => void;
}

const STATE_LABELS: Record<OrbState, string> = {
  idle: 'Ready when you are',
  listening: 'Listening',
  thinking: 'Thinking',
  speaking: 'Speaking',
};

interface MeshLine {
  d: string;
  opacity: number;
}

interface MeshCell {
  x: number;
  y: number;
  size: number;
  opacity: number;
}

interface MeshFrame {
  lines: MeshLine[];
  cells: MeshCell[];
}

const ORB_PROFILES: Record<OrbState, { amp: number; speed: number; drift: number; pulse: number }> = {
  idle: { amp: 1.4, speed: 0.75, drift: 0.55, pulse: 0.28 },
  listening: { amp: 2.8, speed: 1.55, drift: 0.9, pulse: 0.62 },
  thinking: { amp: 2.3, speed: 1.1, drift: 1.2, pulse: 0.44 },
  speaking: { amp: 3.4, speed: 1.95, drift: 0.8, pulse: 0.84 },
};

function buildMesh(frameMs: number, state: OrbState): MeshFrame {
  const time = frameMs / 1000;
  const profile = ORB_PROFILES[state];
  const rows = 24;
  const cols = 33;
  const lines: MeshLine[] = [];
  const cells: MeshCell[] = [];

  for (let row = 0; row < rows; row += 1) {
    const rowRatio = row / (rows - 1);
    const ty = rowRatio * 2 - 1;
    const shell = Math.max(0, 1 - ty * ty * 0.92);
    const baseWidth = 31 * Math.pow(shell, 0.55) + 1.6;
    const rowWave = Math.sin(time * 0.56 + ty * 4.4) * profile.drift;
    const yCenter = 50 + ty * 26 + Math.cos(time * 0.38 + row * 0.42) * profile.pulse;
    const xCenter = 50 + rowWave * 1.25;

    let d = '';
    let hasPoint = false;

    for (let col = 0; col < cols; col += 1) {
      const colRatio = col / (cols - 1);
      const tx = colRatio * 2 - 1;
      const depth = Math.max(0, 1 - tx * tx - ty * ty * 0.88);
      if (depth <= 0) continue;

      const zWave =
        Math.sin(tx * 5.3 + time * profile.speed + row * 0.27) * profile.amp * depth +
        Math.cos(ty * 6.5 - time * profile.speed * 0.72 + tx * 2.1) * profile.amp * 0.62 * depth;

      const x = xCenter + tx * baseWidth + zWave * tx * 0.8;
      const y = yCenter + zWave * 0.55 + Math.sin(time * 0.46 + tx * 3.1) * profile.pulse * 0.7 * depth;

      d += `${hasPoint ? ' L ' : 'M '}${x.toFixed(2)} ${y.toFixed(2)}`;
      hasPoint = true;

      if (col % 2 === row % 2) {
        cells.push({
          x,
          y,
          size: 0.82 + depth * 1.15,
          opacity: 0.18 + depth * 0.6,
        });
      }
    }

    if (hasPoint) {
      lines.push({
        d,
        opacity: 0.14 + shell * 0.5,
      });
    }
  }

  return { lines, cells };
}

export const ConversationOrb: React.FC<ConversationOrbProps> = ({ state, onClick }) => {
  const [frameMs, setFrameMs] = useState(0);

  useEffect(() => {
    if (typeof window === 'undefined') return undefined;
    const media = window.matchMedia('(prefers-reduced-motion: reduce)');
    if (media.matches) {
      setFrameMs(0);
      return undefined;
    }

    let rafId = 0;
    let last = 0;
    const loop = (now: number) => {
      if (now - last > 42) {
        setFrameMs(now);
        last = now;
      }
      rafId = window.requestAnimationFrame(loop);
    };
    rafId = window.requestAnimationFrame(loop);

    return () => {
      window.cancelAnimationFrame(rafId);
    };
  }, []);

  const mesh = useMemo(() => buildMesh(frameMs, state), [frameMs, state]);

  return (
    <div className="orb-stage" role="status" aria-live="polite" aria-label={`Estado: ${STATE_LABELS[state]}`}>
      <button
        type="button"
        className={`mesh-orb mesh-orb--${state}`}
        onClick={onClick}
        disabled={!onClick}
        aria-label={onClick ? STATE_LABELS[state] : undefined}
      >
        <span className="mesh-orb__halo" aria-hidden="true" />
        <span className="mesh-orb__body" aria-hidden="true">
          <svg className="mesh-orb__svg" viewBox="0 0 100 100" preserveAspectRatio="xMidYMid meet">
            <g className="mesh-orb__mesh">
              {mesh.lines.map((line, index) => (
                <path
                  key={`line-${index}`}
                  d={line.d}
                  className="mesh-orb__line"
                  style={{ opacity: line.opacity } as React.CSSProperties}
                />
              ))}
              {mesh.cells.map((cell, index) => (
                <rect
                  key={`cell-${index}`}
                  x={cell.x - cell.size / 2}
                  y={cell.y - cell.size / 2}
                  width={cell.size}
                  height={cell.size}
                  rx={0.24}
                  className="mesh-orb__cell"
                  style={{ opacity: cell.opacity } as React.CSSProperties}
                />
              ))}
            </g>
          </svg>
        </span>
        <span className="mesh-orb__shine" aria-hidden="true" />
      </button>
      <p className="orb-stage__label">{STATE_LABELS[state]}</p>
    </div>
  );
};
