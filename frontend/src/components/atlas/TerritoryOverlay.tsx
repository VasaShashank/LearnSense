import React from 'react';
import type { TopicTerritory } from '../../api/client';

export interface TerritoryOverlayProps {
  topics: TopicTerritory[];
  zoomLevel: number;
}

export const TerritoryOverlay: React.FC<TerritoryOverlayProps> = ({ topics, zoomLevel }) => {
  if (zoomLevel > 2) return null;

  return (
    <div className="absolute inset-0 pointer-events-none z-0 overflow-hidden opacity-30">
      <svg className="w-full h-full">
        <defs>
          <radialGradient id="territoryGlow" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#06b6d4" stopOpacity="0.15" />
            <stop offset="100%" stopColor="#0a0e17" stopOpacity="0" />
          </radialGradient>
        </defs>
        {topics.map((topic, i) => (
          <g key={topic.id} transform={`translate(${150 + i * 280}, ${120 + (i % 2) * 80})`}>
            <circle r="180" fill="url(#territoryGlow)" stroke="#06b6d4" strokeWidth="1" strokeDasharray="6 6" />
            <text
              y="-140"
              textAnchor="middle"
              className="text-xs font-mono tracking-widest fill-cyan-400 font-bold uppercase uppercase"
            >
              TERRITORY {i + 1}: {topic.name}
            </text>
          </g>
        ))}
      </svg>
    </div>
  );
};
