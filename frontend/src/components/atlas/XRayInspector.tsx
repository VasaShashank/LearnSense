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

  return (
    <div className="p-4 rounded-2xl border border-violet-500/40 bg-slate-950/90 backdrop-blur-2xl shadow-glow-rose text-white">
      <div className="flex items-center justify-between pb-3 border-b border-violet-500/30">
        <div className="flex items-center gap-2">
          <Eye className="w-4 h-4 text-violet-400 animate-pulse" />
          <h3 className="text-xs font-mono font-bold tracking-widest text-violet-300 uppercase">
            X-RAY DEEP INSPECTOR
          </h3>
        </div>
        <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-violet-900/60 border border-violet-500/40 text-violet-200">
          RAW GRAPH
        </span>
      </div>

      <div className="mt-3 space-y-2.5">
        <div>
          <h4 className="text-sm font-bold text-white">{concept.name}</h4>
          <p className="text-[11px] text-slate-400 mt-0.5 line-clamp-2">{concept.definition}</p>
        </div>

        <div className="grid grid-cols-2 gap-2 text-xs font-mono">
          <div className="p-2 rounded-xl bg-slate-900/80 border border-slate-800">
            <span className="text-slate-400 text-[10px] block">DEMONSTRATED MASTERY</span>
            <span className="text-emerald-400 font-bold text-sm">{Math.round(concept.mastery * 100)}%</span>
          </div>
          <div className="p-2 rounded-xl bg-slate-900/80 border border-slate-800">
            <span className="text-slate-400 text-[10px]">UNCERTAINTY BOUND</span>
            <span className="text-amber-400 font-bold text-sm block">{Math.round(concept.uncertainty * 100)}%</span>
          </div>
        </div>

        {/* Downstream Impact Alert Box */}
        <div className="p-3 rounded-xl bg-rose-950/40 border border-rose-500/40 flex items-start gap-2.5">
          <ShieldAlert className="w-5 h-5 text-rose-400 shrink-0 mt-0.5" />
          <div>
            <span className="text-xs font-bold text-rose-200 block">CASCADE IMPACT</span>
            <p className="text-[11px] text-rose-300/80 leading-relaxed">
              Weakness in this concept directly affects <strong className="text-white">{downstreamCount} downstream concepts</strong>.
            </p>
          </div>
        </div>

        {/* Trace Impact Action Button */}
        <button
          onClick={() => onTraceImpact(concept.concept_id)}
          className={`w-full py-2.5 px-3 rounded-xl text-xs font-bold tracking-wide flex items-center justify-center gap-2 transition-all duration-300 ${
            isTracing
              ? 'bg-rose-600 text-white shadow-glow-rose ring-2 ring-rose-400'
              : 'bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700'
          }`}
        >
          {isTracing ? (
            <>
              <Sparkles className="w-4 h-4 text-rose-200 animate-spin" />
              <span>TRACING CASCADE RAYS...</span>
            </>
          ) : (
            <>
              <ArrowDownRight className="w-4 h-4 text-cyan-400" />
              <span>TRACE DOWNSTREAM IMPACT</span>
            </>
          )}
        </button>
      </div>
    </div>
  );
};
