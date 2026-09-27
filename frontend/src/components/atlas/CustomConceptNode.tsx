import { memo } from 'react';
import { Handle, Position } from '@xyflow/react';
import { CheckCircle2, Sparkles, AlertCircle, HelpCircle, Target, GitCommit } from 'lucide-react';
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
  const { name, mastery, uncertainty, isTarget, isXRay, isImpacted, isSelected, onSelect } = data;

  // Rich visual color themes based on mastery & state
  let stateStyle = 'border-slate-700 bg-slate-900/90 text-slate-200 shadow-xl';
  let badgeBg = 'bg-slate-800 text-slate-400 border-slate-700';
  let badgeIcon = <HelpCircle className="w-3.5 h-3.5 text-slate-400" />;
  let stateLabel = 'UNEXPLORED';
  let barGradient = 'from-slate-600 to-slate-400';
  let glowEffect = '';

  if (isTarget) {
    stateStyle = 'border-sky-400 bg-gradient-to-b from-sky-950/90 via-slate-900 to-indigo-950/95 text-sky-100 ring-2 ring-sky-400 shadow-glow-cyan animate-pulse-glow';
    badgeBg = 'bg-sky-500/20 text-sky-300 border-sky-400/50';
    badgeIcon = <Target className="w-4 h-4 text-sky-400 animate-spin" style={{ animationDuration: '6s' }} />;
    stateLabel = 'ACTIVE TARGET';
    barGradient = 'from-sky-500 to-cyan-300';
    glowEffect = 'shadow-[0_0_30px_rgba(56,189,248,0.5)]';
  } else if (mastery >= 0.75) {
    stateStyle = 'border-emerald-500/90 bg-gradient-to-b from-emerald-950/90 via-slate-900 to-teal-950/95 text-emerald-100 ring-1 ring-emerald-500/50 shadow-glow-emerald';
    badgeBg = 'bg-emerald-500/20 text-emerald-300 border-emerald-500/50';
    badgeIcon = <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />;
    stateLabel = 'MASTERED';
    barGradient = 'from-emerald-500 to-teal-300';
    glowEffect = 'shadow-[0_0_25px_rgba(16,185,129,0.35)]';
  } else if (mastery >= 0.4) {
    stateStyle = 'border-cyan-500/90 bg-gradient-to-b from-cyan-950/90 via-slate-900 to-sky-950/95 text-cyan-100 ring-1 ring-cyan-500/50 shadow-glow-cyan';
    badgeBg = 'bg-cyan-500/20 text-cyan-300 border-cyan-500/50';
    badgeIcon = <Sparkles className="w-3.5 h-3.5 text-cyan-400" />;
    stateLabel = 'DEVELOPING';
    barGradient = 'from-cyan-500 to-sky-300';
    glowEffect = 'shadow-[0_0_25px_rgba(6,182,212,0.35)]';
  } else if (uncertainty > 0.6 || mastery < 0.25) {
    stateStyle = 'border-amber-500/90 bg-gradient-to-b from-amber-950/90 via-slate-900 to-yellow-950/95 text-amber-100 ring-1 ring-amber-500/50 shadow-glow-amber';
    badgeBg = 'bg-amber-500/20 text-amber-300 border-amber-500/50';
    badgeIcon = <AlertCircle className="w-3.5 h-3.5 text-amber-400" />;
    stateLabel = 'NEEDS ATTENTION';
    barGradient = 'from-amber-500 to-yellow-300';
    glowEffect = 'shadow-[0_0_25px_rgba(245,158,11,0.35)]';
  }

  if (isImpacted) {
    stateStyle = 'border-rose-500 bg-gradient-to-b from-rose-950 via-slate-900 to-red-950 text-rose-100 ring-4 ring-rose-500 shadow-glow-rose animate-bounce';
  }

  if (isSelected) {
    stateStyle += ' scale-110 ring-4 ring-white z-50';
  }

  return (
    <div
      onClick={(e) => {
        e.stopPropagation();
        onSelect(data);
      }}
      className={`cursor-pointer group relative w-72 p-4 rounded-2xl border-2 backdrop-blur-2xl transition-all duration-300 hover:scale-105 hover:z-40 ${stateStyle} ${glowEffect}`}
    >
      {/* Top Handle */}
      <Handle
        type="target"
        position={Position.Top}
        className="!bg-cyan-400 !w-3 !h-3 !-top-2 !border-2 !border-slate-900"
      />

      {/* Header Tag & Mastery Percentage */}
      <div className="flex items-center justify-between mb-2">
        <span className={`text-[10px] font-mono tracking-widest font-extrabold uppercase px-2.5 py-0.5 rounded-lg border flex items-center gap-1.5 ${badgeBg}`}>
          {badgeIcon}
          {stateLabel}
        </span>
        <span className="text-sm font-extrabold font-mono text-cyan-300 tracking-tight">
          {Math.round(mastery * 100)}%
        </span>
      </div>

      {/* Title */}
      <h3 className="text-base font-extrabold text-white tracking-tight group-hover:text-cyan-300 transition-colors leading-snug">
        {name}
      </h3>

      {/* Definition Summary */}
      <p className="text-xs text-slate-300/80 line-clamp-2 mt-1.5 leading-relaxed font-sans">
        {data.definition}
      </p>

      {/* Animated Mastery Progress Bar */}
      <div className="mt-3.5 w-full bg-slate-950/80 h-2 rounded-full overflow-hidden border border-slate-700/60 p-0.5">
        <div
          className={`h-full rounded-full bg-gradient-to-r ${barGradient} transition-all duration-700 shadow-sm`}
          style={{ width: `${Math.max(8, mastery * 100)}%` }}
        />
      </div>

      {/* Bottom Metadata & X-Ray Row */}
      <div className="mt-3 pt-2.5 border-t border-slate-700/50 flex items-center justify-between text-[11px] font-mono text-slate-400">
        <div className="flex items-center gap-1">
          <GitCommit className="w-3.5 h-3.5 text-cyan-400" />
          <span>{data.prerequisites.length} Prereqs</span>
        </div>
        {isXRay && (
          <span className="text-amber-400 font-bold">
            Uncertainty: {Math.round(uncertainty * 100)}%
          </span>
        )}
      </div>

      {/* Bottom Handle */}
      <Handle
        type="source"
        position={Position.Bottom}
        className="!bg-cyan-400 !w-3 !h-3 !-bottom-2 !border-2 !border-slate-900"
      />
    </div>
  );
});

CustomConceptNode.displayName = 'CustomConceptNode';
