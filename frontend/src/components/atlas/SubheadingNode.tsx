import { memo } from 'react';
import { Handle, Position } from '@xyflow/react';
import { Check, ShieldAlert, Sparkles, Layers } from 'lucide-react';
import type { TopicTerritory } from '../../api/client';

export interface SubheadingNodeData extends TopicTerritory, Record<string, unknown> {
  isTarget?: boolean;
  isXRay?: boolean;
  isImpacted?: boolean;
  isSelected?: boolean;
  isDimmed?: boolean;
  zoomLevel: number;
  onSelect: (topic: TopicTerritory) => void;
  onTraceImpact?: (topicId: string) => void;
}

export const SubheadingNode = memo(({ data }: { data: SubheadingNodeData }) => {
  const {
    id,
    name,
    order = 1,
    concepts_count = 0,
    mastery = 0.5,
    uncertainty = 0.3,
    prerequisites = [],
    dependents = [],
    isTarget,
    isImpacted,
    isSelected,
    isDimmed,
    isXRay,
    onSelect,
    onTraceImpact,
  } = data;

  const masteryPercent = Math.round(mastery * 100);
  const isMastered = mastery >= 0.75;
  const isDeveloping = mastery >= 0.35 && !isMastered;

  let stateBorder = 'border-white/[0.08]';
  let stateBg = 'bg-space-900/90';
  let nodeBadgeColor = 'bg-slate-700 text-slate-300';
  let haloClass = '';

  if (isSelected) {
    stateBorder = 'border-amber-400';
    stateBg = 'bg-space-850/95';
    haloClass = 'ring-2 ring-amber-400/90 ring-offset-2 ring-offset-space-950 shadow-[0_0_24px_rgba(245,158,11,0.5)]';
  } else if (isTarget) {
    stateBorder = 'border-cyan-400';
    stateBg = 'bg-space-850/95';
    haloClass = 'ring-2 ring-cyan-400/80 ring-offset-2 ring-offset-space-950 shadow-[0_0_20px_rgba(0,240,255,0.4)] animate-pulse';
  } else if (isMastered) {
    stateBorder = 'border-emerald-500/40';
    nodeBadgeColor = 'bg-emerald-950 text-emerald-300 border-emerald-500/40';
  } else if (isDeveloping) {
    stateBorder = 'border-cyan-500/30';
    nodeBadgeColor = 'bg-cyan-950 text-cyan-300 border-cyan-500/40';
  }

  if (isImpacted) {
    stateBorder = 'border-rose-500';
    stateBg = 'bg-rose-950/70';
    haloClass = 'ring-2 ring-rose-500/80 shadow-[0_0_24px_rgba(244,63,94,0.4)] animate-pulse';
  }

  return (
    <div
      onClick={(e) => {
        e.stopPropagation();
        onSelect(data);
      }}
      className={`cursor-pointer group relative w-72 p-4 rounded-2xl border backdrop-blur-xl transition-all duration-300 hover:scale-[1.02] ${stateBg} ${stateBorder} ${haloClass} ${
        isDimmed ? 'opacity-30' : 'opacity-100'
      }`}
    >
      <Handle
        type="target"
        position={Position.Left}
        className="!bg-cyan-400 !w-2.5 !h-2.5 !-left-1.5 !border-0 shadow-[0_0_8px_#00F0FF]"
      />
      <Handle
        type="target"
        position={Position.Top}
        className="!bg-cyan-400 !w-2.5 !h-2.5 !-top-1.5 !border-0 shadow-[0_0_8px_#00F0FF]"
      />

      {/* Header */}
      <div className="flex items-center justify-between gap-2 mb-2">
        <span className="text-[10px] font-mono tracking-widest uppercase px-2 py-0.5 rounded bg-space-950/80 border border-white/[0.08] text-cyan-300 font-bold">
          CHAPTER {order < 10 ? `0${order}` : order}
        </span>

        <span
          className={`text-[9px] font-mono tracking-wider uppercase px-2 py-0.5 rounded border font-bold flex items-center gap-1 ${nodeBadgeColor}`}
        >
          {isMastered ? (
            <>
              <Check className="w-2.5 h-2.5 text-emerald-400 stroke-[3]" /> Mastered
            </>
          ) : isDeveloping ? (
            <>
              <Sparkles className="w-2.5 h-2.5 text-cyan-400" /> Learning
            </>
          ) : (
            'Not Started'
          )}
        </span>
      </div>

      {/* Topic Name */}
      <h3 className="text-sm font-display font-bold text-white group-hover:text-cyan-200 transition-colors leading-snug line-clamp-2">
        {name}
      </h3>

      {/* Concept Count & Prerequisite Topology */}
      <div className="mt-2.5 flex items-center justify-between text-[10px] font-mono text-universe-slate">
        <span className="flex items-center gap-1.5 text-slate-300">
          <Layers className="w-3 h-3 text-cyan-400" />
          <strong className="text-white font-bold">{concepts_count || data.concepts?.length || 0}</strong> Concepts
        </span>

        <span className="text-[9px] text-slate-400">
          {prerequisites.length > 0 ? `← ${prerequisites.length} Prereqs` : 'Foundational'}
          {dependents.length > 0 ? ` • ${dependents.length} Downstream →` : ''}
        </span>
      </div>

      {/* Mastery Progress Bar */}
      <div className="mt-2.5 space-y-1">
        <div className="flex items-center justify-between text-[10px] font-mono">
          <span className="text-slate-400">Chapter Mastery</span>
          <span
            className={`font-bold ${
              isMastered ? 'text-emerald-400' : isDeveloping ? 'text-cyan-300' : 'text-slate-400'
            }`}
          >
            {masteryPercent}%
          </span>
        </div>
        <div className="w-full bg-space-950 h-1.5 rounded-full overflow-hidden border border-white/[0.06]">
          <div
            className={`h-full transition-all duration-500 rounded-full ${
              isMastered ? 'bg-emerald-400' : isDeveloping ? 'bg-cyan-400' : 'bg-slate-600'
            }`}
            style={{ width: `${Math.max(4, masteryPercent)}%` }}
          />
        </div>
      </div>

      {/* X-Ray Diagnostics or Trace Action */}
      {isXRay && (
        <div className="mt-2.5 pt-2 border-t border-white/[0.06] flex items-center justify-between text-[9px] font-mono text-slate-400">
          <span>Uncertainty: {Math.round(uncertainty * 100)}%</span>
          {onTraceImpact && (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onTraceImpact(id);
              }}
              className="px-2 py-0.5 rounded bg-space-950 hover:bg-rose-950/80 text-rose-300 border border-rose-500/30 hover:border-rose-400 transition-colors flex items-center gap-1"
            >
              <ShieldAlert className="w-2.5 h-2.5 text-rose-400" />
              <span>Trace Risk</span>
            </button>
          )}
        </div>
      )}

      <Handle
        type="source"
        position={Position.Right}
        className="!bg-cyan-400 !w-2.5 !h-2.5 !-right-1.5 !border-0 shadow-[0_0_8px_#00F0FF]"
      />
      <Handle
        type="source"
        position={Position.Bottom}
        className="!bg-cyan-400 !w-2.5 !h-2.5 !-bottom-1.5 !border-0 shadow-[0_0_8px_#00F0FF]"
      />
    </div>
  );
});

SubheadingNode.displayName = 'SubheadingNode';
