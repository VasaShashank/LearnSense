import { memo } from 'react';
import type { TopicTerritory } from '../../api/client';
import { Layers } from 'lucide-react';

export interface TopicClusterColor {
  id: string;
  fill: string;
  gradientStop1: string;
  gradientStop2: string;
  stroke: string;
  pillBg: string;
  pillBorder: string;
  pillText: string;
  glow: string;
  accent: string;
}

const TOPIC_CLUSTER_PALETTES: TopicClusterColor[] = [
  {
    id: 'blue',
    fill: 'rgba(59, 130, 246, 0.05)',
    gradientStop1: 'rgba(59, 130, 246, 0.12)',
    gradientStop2: 'rgba(15, 23, 42, 0)',
    stroke: 'rgba(96, 165, 250, 0.38)',
    pillBg: 'rgba(15, 23, 42, 0.88)',
    pillBorder: 'rgba(96, 165, 250, 0.55)',
    pillText: '#93c5fd',
    glow: 'rgba(59, 130, 246, 0.35)',
    accent: '#3b82f6',
  },
  {
    id: 'teal',
    fill: 'rgba(20, 184, 166, 0.05)',
    gradientStop1: 'rgba(20, 184, 166, 0.12)',
    gradientStop2: 'rgba(15, 23, 42, 0)',
    stroke: 'rgba(45, 212, 191, 0.38)',
    pillBg: 'rgba(15, 23, 42, 0.88)',
    pillBorder: 'rgba(45, 212, 191, 0.55)',
    pillText: '#5eead4',
    glow: 'rgba(20, 184, 166, 0.35)',
    accent: '#14b8a6',
  },
  {
    id: 'purple',
    fill: 'rgba(139, 92, 246, 0.05)',
    gradientStop1: 'rgba(139, 92, 246, 0.12)',
    gradientStop2: 'rgba(15, 23, 42, 0)',
    stroke: 'rgba(167, 139, 250, 0.38)',
    pillBg: 'rgba(15, 23, 42, 0.88)',
    pillBorder: 'rgba(167, 139, 250, 0.55)',
    pillText: '#c4b5fd',
    glow: 'rgba(139, 92, 246, 0.35)',
    accent: '#8b5cf6',
  },
  {
    id: 'amber',
    fill: 'rgba(245, 158, 11, 0.05)',
    gradientStop1: 'rgba(245, 158, 11, 0.12)',
    gradientStop2: 'rgba(15, 23, 42, 0)',
    stroke: 'rgba(251, 191, 36, 0.38)',
    pillBg: 'rgba(15, 23, 42, 0.88)',
    pillBorder: 'rgba(251, 191, 36, 0.55)',
    pillText: '#fde68a',
    glow: 'rgba(245, 158, 11, 0.35)',
    accent: '#f59e0b',
  },
  {
    id: 'emerald',
    fill: 'rgba(16, 185, 129, 0.05)',
    gradientStop1: 'rgba(16, 185, 129, 0.12)',
    gradientStop2: 'rgba(15, 23, 42, 0)',
    stroke: 'rgba(52, 211, 153, 0.38)',
    pillBg: 'rgba(15, 23, 42, 0.88)',
    pillBorder: 'rgba(52, 211, 153, 0.55)',
    pillText: '#6ee7b7',
    glow: 'rgba(16, 185, 129, 0.35)',
    accent: '#10b981',
  },
  {
    id: 'cyan',
    fill: 'rgba(6, 182, 212, 0.05)',
    gradientStop1: 'rgba(6, 182, 212, 0.12)',
    gradientStop2: 'rgba(15, 23, 42, 0)',
    stroke: 'rgba(34, 211, 238, 0.38)',
    pillBg: 'rgba(15, 23, 42, 0.88)',
    pillBorder: 'rgba(34, 211, 238, 0.55)',
    pillText: '#67e8f9',
    glow: 'rgba(6, 182, 212, 0.35)',
    accent: '#06b6d4',
  },
  {
    id: 'rose',
    fill: 'rgba(244, 63, 94, 0.05)',
    gradientStop1: 'rgba(244, 63, 94, 0.12)',
    gradientStop2: 'rgba(15, 23, 42, 0)',
    stroke: 'rgba(251, 113, 133, 0.38)',
    pillBg: 'rgba(15, 23, 42, 0.88)',
    pillBorder: 'rgba(251, 113, 133, 0.55)',
    pillText: '#fecdd3',
    glow: 'rgba(244, 63, 94, 0.35)',
    accent: '#f43f5e',
  },
];

export interface TopicClusterNodeData extends Record<string, unknown> {
  topic: TopicTerritory;
  colorIndex: number;
  width: number;
  height: number;
  isFocused?: boolean;
  isDimmed?: boolean;
  onSelectTopic?: (topic: TopicTerritory) => void;
}

export const TopicClusterNode = memo(({ data }: { data: TopicClusterNodeData }) => {
  const { topic, colorIndex, width, height, isFocused, isDimmed, onSelectTopic } = data;
  const palette = TOPIC_CLUSTER_PALETTES[colorIndex % TOPIC_CLUSTER_PALETTES.length];
  const gradientId = `cluster-grad-${topic.id}-${colorIndex}`;

  const conceptCount = topic.concepts_count || topic.concepts?.length || 0;

  return (
    <div
      style={{
        width,
        height,
        pointerEvents: 'none',
      }}
      className={`relative transition-all duration-500 ${
        isDimmed ? 'opacity-25' : 'opacity-100'
      }`}
    >
      {/* Soft Nebula Atmosphere & Boundary */}
      <svg
        width={width}
        height={height}
        className="absolute inset-0 w-full h-full overflow-visible pointer-events-none"
      >
        <defs>
          <radialGradient
            id={gradientId}
            cx="50%"
            cy="50%"
            r="60%"
            fx="50%"
            fy="50%"
          >
            <stop offset="0%" stopColor={palette.gradientStop1} />
            <stop offset="70%" stopColor={palette.fill} />
            <stop offset="100%" stopColor={palette.gradientStop2} />
          </radialGradient>
        </defs>

        {/* Ambient Nebula Fill */}
        <rect
          x="2"
          y="2"
          width={Math.max(10, width - 4)}
          height={Math.max(10, height - 4)}
          rx="44"
          ry="44"
          fill={`url(#${gradientId})`}
        />

        {/* Luminous Boundary Stroke */}
        <rect
          x="2"
          y="2"
          width={Math.max(10, width - 4)}
          height={Math.max(10, height - 4)}
          rx="44"
          ry="44"
          fill="none"
          stroke={palette.stroke}
          strokeWidth={isFocused ? 2.0 : 1.2}
          strokeDasharray="8 6"
          style={{
            filter: isFocused
              ? `drop-shadow(0 0 16px ${palette.glow})`
              : `drop-shadow(0 0 8px ${palette.glow})`,
          }}
        />

        {/* Scientific Observatory Coordinate Crosses in 4 Corners */}
        <g stroke={palette.accent} strokeWidth="1" opacity="0.4">
          {/* Top-Left Cross */}
          <line x1="28" y1="24" x2="28" y2="32" />
          <line x1="24" y1="28" x2="32" y2="28" />

          {/* Top-Right Cross */}
          <line x1={width - 28} y1="24" x2={width - 28} y2="32" />
          <line x1={width - 32} y1="28" x2={width - 24} y2="28" />

          {/* Bottom-Left Cross */}
          <line x1="28" y1={height - 28} x2="28" y2={height - 20} />
          <line x1="24" y1={height - 24} x2="32" y2={height - 24} />

          {/* Bottom-Right Cross */}
          <line x1={width - 28} y1={height - 28} x2={width - 28} y2={height - 20} />
          <line x1={width - 32} y1={height - 24} x2={width - 24} y2={height - 24} />
        </g>
      </svg>

      {/* Floating Glassmorphic Chapter Pill Header */}
      <div className="absolute -top-4 left-1/2 -translate-x-1/2 z-10 pointer-events-auto">
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            if (onSelectTopic) onSelectTopic(topic);
          }}
          style={{
            backgroundColor: palette.pillBg,
            borderColor: palette.pillBorder,
            color: palette.pillText,
            boxShadow: `0 8px 24px rgba(0,0,0,0.6), 0 0 16px ${palette.glow}`,
          }}
          className="group flex items-center gap-2 px-4 py-1.5 rounded-full text-xs font-display font-bold tracking-wide border backdrop-blur-xl hover:scale-105 transition-all cursor-pointer whitespace-nowrap"
          title={`Chapter: ${topic.name} — Click to focus`}
        >
          <span
            style={{ backgroundColor: palette.accent }}
            className="w-2 h-2 rounded-full shadow-[0_0_8px_currentColor] animate-pulse"
          />
          <span className="font-mono text-[10px] tracking-widest text-slate-400 group-hover:text-white uppercase">
            CH {topic.order < 10 ? `0${topic.order}` : topic.order}
          </span>
          <span className="text-white font-bold max-w-[240px] truncate">
            {topic.name}
          </span>
          {conceptCount > 0 && (
            <span
              style={{ backgroundColor: 'rgba(255,255,255,0.08)' }}
              className="ml-1 px-1.5 py-0.5 rounded-md text-[10px] font-mono text-slate-300 flex items-center gap-1"
            >
              <Layers className="w-2.5 h-2.5" />
              <span>{conceptCount}</span>
            </span>
          )}
        </button>
      </div>
    </div>
  );
});

TopicClusterNode.displayName = 'TopicClusterNode';
