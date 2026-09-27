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
  const { name, mastery, uncertainty, isTarget, isXRay, isImpacted, isSelected, zoomLevel, onSelect } = data;

  let stateStyle = 'border-slate-700/60 bg-slate-900/80 text-slate-300';
  let badgeIcon = <HelpCircle className="w-3.5 h-3.5 text-slate-400" />;
  let stateLabel = 'UNKNOWN';
  let ringGlow = '';

  if (isTarget) {
    stateStyle = 'border-sky-400 bg-sky-950/90 text-sky-100 shadow-glow-cyan animate-pulse-glow';
    badgeIcon = <Target className="w-4 h-4 text-sky-400 animate-spin" style={{ animationDuration: '6s' }} />;
    stateLabel = 'TARGET';
    ringGlow = 'ring-2 ring-sky-400/50';
  } else if (mastery >= 0.75) {
    stateStyle = 'border-emerald-500/80 bg-emerald-950/80 text-emerald-100 shadow-glow-emerald';
    badgeIcon = <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />;
    stateLabel = 'MASTERED';
    ringGlow = 'ring-1 ring-emerald-500/30';
  } else if (mastery >= 0.4) {
    stateStyle = 'border-cyan-500/80 bg-cyan-950/80 text-cyan-100 shadow-glow-cyan';
    badgeIcon = <Sparkles className="w-3.5 h-3.5 text-cyan-400" />;
    stateLabel = 'DEVELOPING';
    ringGlow = 'ring-1 ring-cyan-500/30';
  } else if (uncertainty > 0.6 || mastery < 0.25) {
    stateStyle = 'border-amber-500/80 bg-amber-950/80 text-amber-100 shadow-glow-amber';
    badgeIcon = <AlertCircle className="w-3.5 h-3.5 text-amber-400" />;
    stateLabel = 'NEEDS ATTENTION';
    ringGlow = 'ring-1 ring-amber-500/40';
  }

  if (isImpacted) {
    stateStyle = 'border-rose-500 bg-rose-950/90 text-rose-100 shadow-glow-rose ring-2 ring-rose-500/60 animate-bounce';
  }

  if (isSelected) {
    ringGlow += ' ring-2 ring-white shadow-2xl scale-105';
  }

  if (zoomLevel <= 2) {
    return (
      <div
        onClick={() => onSelect(data)}
        className={`cursor-pointer group flex flex-col items-center justify-center p-2 rounded-xl border backdrop-blur-md transition-all duration-300 ${stateStyle} ${ringGlow}`}
      >
        <Handle type="target" position={Position.Top} className="!bg-slate-500 !w-2 !h-2" />
        <div className="flex items-center gap-1.5">
          {badgeIcon}
          <span className="text-xs font-semibold tracking-wide whitespace-nowrap">{name}</span>
        </div>
        <Handle type="source" position={Position.Bottom} className="!bg-slate-500 !w-2 !h-2" />
      </div>
    );
  }

  return (
    <div
      onClick={() => onSelect(data)}
      className={`cursor-pointer group relative w-64 p-3.5 rounded-2xl border backdrop-blur-xl transition-all duration-300 ${stateStyle} ${ringGlow}`}
    >
      <Handle type="target" position={Position.Top} className="!bg-sky-400 !w-2.5 !h-2.5 !-top-1.5" />

      <div className="flex items-center justify-between mb-2">
        <span className="text-[10px] font-mono tracking-widest uppercase px-2 py-0.5 rounded-md bg-slate-800/80 border border-slate-700/50 flex items-center gap-1">
          {badgeIcon}
          {stateLabel}
        </span>
        <span className="text-xs font-bold font-mono text-cyan-300">
          {Math.round(mastery * 100)}%
        </span>
      </div>

      <h4 className="text-sm font-bold tracking-tight text-white group-hover:text-cyan-300 transition-colors">
        {name}
      </h4>

      {zoomLevel >= 4 && (
        <p className="text-[11px] text-slate-300/80 line-clamp-2 mt-1 leading-relaxed">
          {data.definition}
        </p>
      )}

      <div className="mt-3 w-full bg-slate-800/80 h-1.5 rounded-full overflow-hidden border border-slate-700/40">
        <div
          className={`h-full transition-all duration-700 rounded-full ${
            mastery >= 0.75 ? 'bg-emerald-400' : mastery >= 0.4 ? 'bg-cyan-400' : 'bg-amber-400'
          }`}
          style={{ width: `${Math.max(5, mastery * 100)}%` }}
        />
      </div>

      {isXRay && (
        <div className="mt-2.5 pt-2 border-t border-slate-700/50 flex justify-between items-center text-[10px] text-slate-400 font-mono">
          <span>Uncertainty: {Math.round(uncertainty * 100)}%</span>
          <span>Prereqs: {data.prerequisites.length}</span>
        </div>
      )}

      <Handle type="source" position={Position.Bottom} className="!bg-sky-400 !w-2.5 !h-2.5 !-bottom-1.5" />
    </div>
  );
});

CustomConceptNode.displayName = 'CustomConceptNode';
