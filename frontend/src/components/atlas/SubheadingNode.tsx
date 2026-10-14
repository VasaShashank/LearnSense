import { memo } from 'react';
import { Handle, Position } from '@xyflow/react';
import { Layers, CheckCircle2, Sparkles, AlertCircle, Target, ArrowRight, ShieldAlert } from 'lucide-react';
import type { TopicTerritory } from '../../api/client';

export interface SubheadingNodeData extends TopicTerritory, Record<string, unknown> {
  isTarget?: boolean;
  isXRay?: boolean;
  isImpacted?: boolean;
  isSelected?: boolean;
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
    zoomLevel,
    onSelect,
    onTraceImpact,
  } = data;

  const masteryPercent = Math.round(mastery * 100);

  // Status Styling
  let stateBorder = 'border-white/[0.1]';
  let stateBg = 'bg-space-900/90';
  let badgeText = 'text-universe-slate';
  let badgeIcon = <Layers className="w-3 h-3 text-universe-slate" />;
  let stateLabel = 'EXPLORING';
  let haloClass = '';
  let masteryColor = 'bg-cyan-400';

  if (isTarget) {
    stateBorder = 'border-cyan-400';
    stateBg = 'bg-space-850/95';
    badgeText = 'text-cyan-300';
    badgeIcon = <Target className="w-3 h-3 text-cyan-400 animate-spin" style={{ animationDuration: '8s' }} />;
    stateLabel = 'ACTIVE TARGET';
    haloClass = 'halo-target ring-2 ring-cyan-400/60 shadow-[0_0_24px_rgba(0,240,255,0.25)]';
    masteryColor = 'bg-cyan-400';
  } else if (mastery >= 0.75) {
    stateBorder = 'border-emerald-500/40';
    stateBg = 'bg-space-900/90';
    badgeText = 'text-emerald-300';
    badgeIcon = <CheckCircle2 className="w-3 h-3 text-emerald-400" />;
    stateLabel = 'MASTERED';
    haloClass = 'halo-mastered shadow-[0_0_20px_rgba(16,185,129,0.15)]';
    masteryColor = 'bg-emerald-400';
  } else if (mastery >= 0.4) {
    stateBorder = 'border-cyan-500/30';
    stateBg = 'bg-space-900/90';
    badgeText = 'text-cyan-300';
    badgeIcon = <Sparkles className="w-3 h-3 text-cyan-400" />;
    stateLabel = 'DEVELOPING';
    masteryColor = 'bg-cyan-400';
  } else if (uncertainty > 0.6 || mastery < 0.25) {
    stateBorder = 'border-amber-500/40';
    stateBg = 'bg-space-900/90';
    badgeText = 'text-amber-300';
    badgeIcon = <AlertCircle className="w-3 h-3 text-amber-400" />;
    stateLabel = 'NEEDS ATTENTION';
    haloClass = 'halo-gap shadow-[0_0_20px_rgba(245,158,11,0.15)]';
    masteryColor = 'bg-amber-400';
  }

  if (isImpacted) {
    stateBorder = 'border-rose-500';
    stateBg = 'bg-rose-950/70';
    haloClass = 'ring-2 ring-rose-500/80 shadow-[0_0_32px_rgba(244,63,94,0.4)] animate-pulse';
    stateLabel = 'CASCADE IMPACT';
  }

  if (isSelected) {
    stateBorder = 'border-cyan-300';
    haloClass += ' ring-2 ring-cyan-400/80 shadow-[0_0_36px_rgba(0,240,255,0.35)] scale-[1.02]';
  }

  // Compact Node for Distant Zoom
  if (zoomLevel <= 2) {
    return (
      <div
        onClick={() => onSelect(data)}
        className={`cursor-pointer group flex items-center gap-2.5 px-3.5 py-2 rounded-xl border backdrop-blur-xl transition-all duration-200 ${stateBg} ${stateBorder} ${haloClass}`}
      >
        <Handle type="target" position={Position.Top} className="!bg-cyan-400 !w-2 !h-2 !border-0 shadow-[0_0_8px_#00F0FF]" />
        <Handle type="target" position={Position.Left} className="!bg-cyan-400 !w-2 !h-2 !border-0 shadow-[0_0_8px_#00F0FF]" />
        {badgeIcon}
        <div className="flex flex-col">
          <span className="text-[9px] font-mono font-bold text-cyan-400 uppercase tracking-widest">
            SUBHEADING {order < 10 ? `0${order}` : order}
          </span>
          <span className="text-xs font-display font-bold text-white whitespace-nowrap">
            {name}
          </span>
        </div>
        <span className="text-[10px] font-mono text-cyan-300 font-bold ml-1">
          {masteryPercent}%
        </span>
        <Handle type="source" position={Position.Right} className="!bg-cyan-400 !w-2 !h-2 !border-0 shadow-[0_0_8px_#00F0FF]" />
        <Handle type="source" position={Position.Bottom} className="!bg-cyan-400 !w-2 !h-2 !border-0 shadow-[0_0_8px_#00F0FF]" />
      </div>
    );
  }

  // Full High-Fidelity Subheading Card Node
  return (
    <div
      onClick={() => onSelect(data)}
      className={`cursor-pointer group relative w-72 p-4 rounded-2xl border backdrop-blur-2xl transition-all duration-300 hover:scale-[1.02] ${stateBg} ${stateBorder} ${haloClass}`}
    >
      <Handle type="target" position={Position.Top} className="!bg-cyan-400 !w-2.5 !h-2.5 !-top-1.5 !border-0 shadow-[0_0_10px_#00F0FF]" />
      <Handle type="target" position={Position.Left} className="!bg-cyan-400 !w-2.5 !h-2.5 !-left-1.5 !border-0 shadow-[0_0_10px_#00F0FF]" />

      {/* Header Telemetry */}
      <div className="flex items-center justify-between gap-2 mb-2.5">
        <span className="text-[9px] font-mono tracking-widest uppercase px-2 py-0.5 rounded-md bg-space-950/80 border border-white/[0.08] text-cyan-300 font-bold">
          SUBHEADING {order < 10 ? `0${order}` : order}
        </span>

        <span className={`text-[9px] font-mono tracking-wider uppercase px-2 py-0.5 rounded-md bg-space-950/80 border border-white/[0.08] flex items-center gap-1 font-bold ${badgeText}`}>
          {badgeIcon}
          {stateLabel}
        </span>
      </div>

      {/* Subheading Title */}
      <h3 className="text-sm font-display font-extrabold text-white group-hover:text-cyan-200 transition-colors leading-snug line-clamp-2">
        {name}
      </h3>

      {/* Concept Count & Prerequisite Topology */}
      <div className="mt-2.5 flex items-center justify-between text-[10px] font-mono text-universe-slate">
        <span className="flex items-center gap-1.5 text-universe-slate">
          <Layers className="w-3 h-3 text-cyan-400" />
          <strong className="text-white font-bold">{concepts_count}</strong> Concepts
        </span>

        <span className="text-[9px] text-universe-slate/80">
          {prerequisites.length > 0 ? `← ${prerequisites.length} Prereqs` : 'Root'} 
          {dependents.length > 0 ? ` • ${dependents.length} Downstream →` : ''}
        </span>
      </div>

      {/* Mastery Progress Bar */}
      <div className="mt-2.5 space-y-1">
        <div className="flex items-center justify-between text-[10px] font-mono">
          <span className="text-universe-slate">Module Mastery</span>
          <span className="text-cyan-300 font-bold">{masteryPercent}%</span>
        </div>
        <div className="w-full bg-space-950 h-1.5 rounded-full overflow-hidden border border-white/[0.06]">
          <div
            className={`h-full transition-all duration-500 rounded-full ${masteryColor}`}
            style={{ width: `${Math.max(4, masteryPercent)}%` }}
          />
        </div>
      </div>

      {/* Interactive Expand Action */}
      <div className="mt-3.5 pt-2.5 border-t border-white/[0.06] flex items-center justify-between text-[10px] font-mono">
        <span className="text-cyan-400 font-bold group-hover:text-cyan-300 flex items-center gap-1">
          <span>Expand Learning Plan</span>
          <ArrowRight className="w-3 h-3 group-hover:translate-x-0.5 transition-transform" />
        </span>

        {onTraceImpact && (
          <button
            onClick={(e) => {
              e.stopPropagation();
              onTraceImpact(id);
            }}
            className="px-2 py-0.5 rounded bg-space-950 hover:bg-rose-950/80 text-rose-300 border border-rose-500/30 hover:border-rose-400 transition-colors flex items-center gap-1 text-[9px]"
            title="Trace downstream dependency cascade"
          >
            <ShieldAlert className="w-2.5 h-2.5 text-rose-400" />
            <span>Trace</span>
          </button>
        )}
      </div>

      <Handle type="source" position={Position.Right} className="!bg-cyan-400 !w-2.5 !h-2.5 !-right-1.5 !border-0 shadow-[0_0_10px_#00F0FF]" />
      <Handle type="source" position={Position.Bottom} className="!bg-cyan-400 !w-2.5 !h-2.5 !-bottom-1.5 !border-0 shadow-[0_0_10px_#00F0FF]" />
    </div>
  );
});
