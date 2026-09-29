import { memo } from 'react';
import { Handle, Position } from '@xyflow/react';
import { CheckCircle2, Sparkles, AlertCircle, HelpCircle, Target } from 'lucide-react';
import type { ConceptNode } from '../../api/client';

export interface ConceptNodeData extends ConceptNode, Record<string, unknown> {
  isTarget?: boolean;
  isXRay?: boolean;
  isImpacted?: boolean;
  isSelected?: boolean;
  zoomLevel: number;
  onSelect: (concept: ConceptNode) => void;
}

export const CustomConceptNode = memo(({ data }: { data: ConceptNodeData }) => {
  const { 
    name, 
    mastery = 0.5, 
    uncertainty = 0.3, 
    isTarget, 
    isXRay, 
    isImpacted, 
    isSelected, 
    zoomLevel, 
    onSelect 
  } = data;

  const masteryPercent = Math.round(mastery * 100);

  // States
  let stateBorder = 'border-white/[0.08]';
  let stateBg = 'bg-space-850/80';
  let badgeText = 'text-universe-slate';
  let badgeIcon = <HelpCircle className="w-3 h-3 text-universe-slate" />;
  let stateLabel = 'EXPLORING';
  let haloClass = '';
  let masteryColor = 'bg-cyan-400';

  if (isTarget) {
    stateBorder = 'border-cyan-400';
    stateBg = 'bg-space-800/95';
    badgeText = 'text-cyan-300';
    badgeIcon = <Target className="w-3 h-3 text-cyan-400 animate-spin" style={{ animationDuration: '8s' }} />;
    stateLabel = 'TARGET';
    haloClass = 'halo-target ring-1 ring-cyan-400/60';
    masteryColor = 'bg-cyan-400';
  } else if (mastery >= 0.75) {
    stateBorder = 'border-emerald-500/40';
    stateBg = 'bg-space-850/85';
    badgeText = 'text-emerald-300';
    badgeIcon = <CheckCircle2 className="w-3 h-3 text-emerald-400" />;
    stateLabel = 'MASTERED';
    haloClass = 'halo-mastered';
    masteryColor = 'bg-emerald-400';
  } else if (mastery >= 0.4) {
    stateBorder = 'border-cyan-500/30';
    stateBg = 'bg-space-850/80';
    badgeText = 'text-cyan-300';
    badgeIcon = <Sparkles className="w-3 h-3 text-cyan-400" />;
    stateLabel = 'DEVELOPING';
    masteryColor = 'bg-cyan-400';
  } else if (uncertainty > 0.6 || mastery < 0.25) {
    stateBorder = 'border-amber-500/40';
    stateBg = 'bg-space-850/85';
    badgeText = 'text-amber-300';
    badgeIcon = <AlertCircle className="w-3 h-3 text-amber-400" />;
    stateLabel = 'NEEDS ATTENTION';
    haloClass = 'halo-gap';
    masteryColor = 'bg-amber-400';
  }

  if (isImpacted) {
    stateBorder = 'border-rose-500';
    stateBg = 'bg-rose-950/60';
    haloClass = 'ring-2 ring-rose-500/70 shadow-[0_0_24px_rgba(244,63,94,0.3)] animate-pulse';
    stateLabel = 'CASCADE IMPACT';
  }

  if (isSelected) {
    stateBorder = 'border-white';
    haloClass += ' ring-2 ring-white/80 shadow-[0_0_32px_rgba(255,255,255,0.2)] scale-[1.03]';
  }

  // Compact Node for Distant Zoom
  if (zoomLevel <= 2) {
    return (
      <div
        onClick={() => onSelect(data)}
        className={`cursor-pointer group flex items-center gap-2 px-3 py-1.5 rounded-lg border backdrop-blur-md transition-all duration-200 ${stateBg} ${stateBorder} ${haloClass}`}
      >
        <Handle type="target" position={Position.Top} className="!bg-cyan-400 !w-1.5 !h-1.5 !border-0" />
        {badgeIcon}
        <span className="text-xs font-display font-semibold tracking-tight text-white whitespace-nowrap">
          {name}
        </span>
        <span className="text-[10px] font-mono text-universe-slate font-bold">
          {masteryPercent}%
        </span>
        <Handle type="source" position={Position.Bottom} className="!bg-cyan-400 !w-1.5 !h-1.5 !border-0" />
      </div>
    );
  }

  // Full High-Fidelity Constellation Node
  return (
    <div
      onClick={() => onSelect(data)}
      className={`cursor-pointer group relative w-64 p-3.5 rounded-xl border backdrop-blur-xl transition-all duration-200 ${stateBg} ${stateBorder} ${haloClass}`}
    >
      <Handle type="target" position={Position.Top} className="!bg-cyan-400 !w-2 !h-2 !-top-1 !border-0 shadow-[0_0_8px_#00F0FF]" />

      {/* Header telemetry */}
      <div className="flex items-center justify-between gap-2 mb-2">
        <span className={`text-[9px] font-mono tracking-widest uppercase px-1.5 py-0.5 rounded bg-space-950/70 border border-white/[0.06] flex items-center gap-1 font-bold ${badgeText}`}>
          {badgeIcon}
          {stateLabel}
        </span>

        <span className="text-xs font-mono font-bold text-white tracking-tight">
          {masteryPercent}%
        </span>
      </div>

      {/* Concept Name */}
      <h4 className="text-xs font-display font-bold text-white group-hover:text-cyan-300 transition-colors leading-snug">
        {name}
      </h4>

      {/* Deep definition at high zoom */}
      {zoomLevel >= 4 && data.definition && (
        <p className="text-[10px] text-universe-slate mt-1 line-clamp-2 leading-relaxed font-sans">
          {data.definition}
        </p>
      )}

      {/* Mastery Progress Conduit */}
      <div className="mt-2.5 w-full bg-space-950 h-1 rounded-full overflow-hidden border border-white/[0.05]">
        <div
          className={`h-full transition-all duration-500 rounded-full ${masteryColor}`}
          style={{ width: `${Math.max(4, masteryPercent)}%` }}
        />
      </div>

      {/* X-Ray Diagnostics Footnote */}
      {isXRay && (
        <div className="mt-2 pt-2 border-t border-white/[0.06] flex justify-between items-center text-[9px] text-universe-slate font-mono">
          <span>Uncertainty: {Math.round(uncertainty * 100)}%</span>
          <span>Prereqs: {data.prerequisites.length}</span>
        </div>
      )}

      <Handle type="source" position={Position.Bottom} className="!bg-cyan-400 !w-2 !h-2 !-bottom-1 !border-0 shadow-[0_0_8px_#00F0FF]" />
    </div>
  );
});

CustomConceptNode.displayName = 'CustomConceptNode';
