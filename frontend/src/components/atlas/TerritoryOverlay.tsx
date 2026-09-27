import React from 'react';
import type { TopicTerritory } from '../../api/client';

export interface TerritoryOverlayProps {
  topics: TopicTerritory[];
}

export const TerritoryOverlay: React.FC<TerritoryOverlayProps> = ({ topics }) => {
  const territoryColors = [
    { fill: 'rgba(6, 182, 212, 0.12)', stroke: '#06b6d4', text: '#38bdf8' },
    { fill: 'rgba(16, 185, 129, 0.12)', stroke: '#10b981', text: '#34d399' },
    { fill: 'rgba(245, 158, 11, 0.12)', stroke: '#f59e0b', text: '#fbbf24' },
    { fill: 'rgba(139, 92, 246, 0.12)', stroke: '#8b5cf6', text: '#a78bfa' },
  ];

  return (
    <div className="absolute inset-0 pointer-events-none z-0 overflow-hidden">
      <svg className="w-full h-full">
        {topics.map((topic, i) => {
          const color = territoryColors[i % territoryColors.length];
          const cx = 300 + i * 450;
          const cy = 320 + (i % 2) * 60;

          return (
            <g key={topic.id} transform={`translate(${cx}, ${cy})`}>
              {/* Territory Landmass Ellipse Hull */}
              <ellipse
                rx="210"
                ry="260"
                fill={color.fill}
                stroke={color.stroke}
                strokeWidth="2"
                strokeDasharray="8 8"
                className="transition-all duration-700 opacity-80"
              />

              {/* Territory Title Banner */}
              <rect
                x="-140"
                y="-280"
                width="280"
                height="32"
                rx="12"
                fill="#0f172a"
                stroke={color.stroke}
                strokeWidth="1.5"
                className="shadow-2xl"
              />
              <text
                x="0"
                y="-259"
                textAnchor="middle"
                fill={color.text}
                className="text-xs font-mono font-black tracking-widest uppercase"
              >
                TERRITORY {i + 1}: {topic.name}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
};
