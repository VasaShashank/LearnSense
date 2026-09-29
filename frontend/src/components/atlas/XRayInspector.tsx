import React from 'react';
import type { ConceptNode } from '../../api/client';
import { Eye, ShieldAlert, ArrowDownRight, Sparkles } from 'lucide-react';

export interface XRayInspectorProps {
  concept: ConceptNode | null;
  downstreamCount: number;
  onTraceImpact: (conceptId: string) => void;
  isTracing: boolean;
}

export const XRayInspector: React.FC<XRayInspectorProps> = ({
  concept,
  downstreamCount,
  onTraceImpact,
  isTracing,
}) => {
  if (!concept) return null;

  const masteryPercent = Math.round(concept.mastery * 100);

  return (
    <div className="universe-panel rounded-2xl p-5 border-violet-500/30 shadow-[0_8px_32px_rgba(139,92,246,0.12)] space-y-4 animate-fade-in">
      
      {/* Header */}
      <div className="flex items-center justify-between pb-3 border-b border-white/[0.06]">
        <div className="flex items-center gap-2">
          <Eye className="w-4 h-4 text-violet-400 animate-pulse" />
          <h3 className="text-xs font-mono font-bold tracking-widest text-violet-300 uppercase">
            X-RAY TOPOLOGY SCAN
          </h3>
        </div>
        <span className="text-[9px] font-mono px-2 py-0.5 rounded bg-violet-950/80 border border-violet-500/40 text-violet-200">
          REALTIME
        </span>
      </div>

      {/* Target Concept Name & Definition */}
      <div className="space-y-1">
        <h4 className="text-sm font-display font-bold text-white leading-snug">{concept.name}</h4>
        <p className="text-xs text-universe-slate line-clamp-2 leading-relaxed font-sans">{concept.definition}</p>
      </div>

      {/* Telemetry Metrics */}
      <div className="grid grid-cols-2 gap-2 text-xs font-mono">
        <div className="p-2.5 rounded-xl bg-space-950/60 border border-white/[0.05]">
          <span className="text-universe-slate text-[9px] block">MASTERY p(know)</span>
          <span className="text-emerald-400 font-bold text-base">{masteryPercent}%</span>
        </div>
        <div className="p-2.5 rounded-xl bg-space-950/60 border border-white/[0.05]">
          <span className="text-universe-slate text-[9px] block">UNCERTAINTY σ</span>
          <span className="text-amber-400 font-bold text-base">{Math.round((concept.uncertainty ?? 0.3) * 100)}%</span>
        </div>
      </div>

      {/* Cascade Risk Banner */}
      <div className="p-3 rounded-xl bg-rose-950/30 border border-rose-500/30 flex items-start gap-2.5">
        <ShieldAlert className="w-4 h-4 text-rose-400 shrink-0 mt-0.5" />
        <div className="space-y-0.5">
          <span className="text-xs font-mono font-bold text-rose-200 block">CASCADE RISK</span>
          <p className="text-[11px] text-rose-300/80 leading-relaxed font-sans">
            Comprehension weakness directly impacts <strong className="text-white">{downstreamCount} dependent concepts</strong>.
          </p>
        </div>
      </div>

      {/* Trace Impact Action */}
      <button
        onClick={() => onTraceImpact(concept.concept_id)}
        className={`w-full py-2.5 px-3 rounded-xl text-xs font-mono font-bold tracking-wider flex items-center justify-center gap-2 transition-all duration-200 ${
          isTracing
            ? 'bg-rose-600 text-white shadow-[0_0_24px_rgba(244,63,94,0.4)] border border-rose-400'
            : 'bg-space-850 hover:bg-space-750 text-universe-text border border-white/[0.08] hover:border-rose-400/40'
        }`}
      >
        {isTracing ? (
          <>
            <Sparkles className="w-3.5 h-3.5 text-rose-200 animate-spin" />
            <span>FIRING CASCADE RAYS...</span>
          </>
        ) : (
          <>
            <ArrowDownRight className="w-3.5 h-3.5 text-cyan-400" />
            <span>TRACE DOWNSTREAM IMPACT</span>
          </>
        )}
      </button>

    </div>
  );
};
