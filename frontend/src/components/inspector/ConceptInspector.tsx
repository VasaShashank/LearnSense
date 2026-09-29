import React from 'react';
import type { ConceptNode } from '../../api/client';
import { X, BookOpen, GraduationCap, MessageSquare, CheckCircle2, AlertTriangle, FileText, Share2 } from 'lucide-react';

export interface ConceptInspectorProps {
  concept: ConceptNode | null;
  onClose: () => void;
  onStartLearning: (conceptId: string) => void;
  onStartPractice: (conceptId: string) => void;
  onAskTutor: (conceptId: string) => void;
  onTraceImpact: (conceptId: string) => void;
}

export const ConceptInspector: React.FC<ConceptInspectorProps> = ({
  concept,
  onClose,
  onStartLearning,
  onStartPractice,
  onAskTutor,
  onTraceImpact,
}) => {
  if (!concept) return null;

  const {
    name,
    definition = '',
    mastery = 0.5,
    uncertainty = 0.3,
    prerequisites = [],
    dependents = [],
    source_references = [],
  } = concept;

  const masteryPercent = Math.round(mastery * 100);

  return (
    <div className="fixed inset-y-0 right-0 z-50 w-full max-w-lg bg-space-900/95 border-l border-white/[0.08] backdrop-blur-2xl shadow-[0_0_64px_rgba(0,0,0,0.8)] p-6 lg:p-8 overflow-y-auto flex flex-col justify-between animate-fade-in">
      <div className="space-y-6">
        
        {/* Header Telemetry */}
        <div className="flex items-center justify-between pb-4 border-b border-white/[0.07]">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-cyan-400 shadow-[0_0_8px_#00F0FF]" />
            <span className="text-[10px] font-mono font-bold tracking-widest text-universe-slate uppercase">
              KNOWLEDGE TELEMETRY // CONCEPT X-RAY
            </span>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg bg-space-800 hover:bg-space-750 text-universe-slate hover:text-white transition-colors"
            aria-label="Close inspector"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Concept Title & Definition */}
        <div className="space-y-3">
          <div className="flex items-baseline justify-between gap-3">
            <h2 className="text-2xl font-display font-bold text-white tracking-tight leading-snug">
              {name}
            </h2>
            <span className="text-sm font-mono font-bold text-cyan-400 shrink-0">
              {masteryPercent}% Mastery
            </span>
          </div>

          <div className="p-4 rounded-xl bg-space-950/70 border border-white/[0.05] text-xs text-universe-slate leading-relaxed font-sans">
            {definition || 'No definition text recorded for this unit.'}
          </div>
        </div>

        {/* Precision Metrics Grid */}
        <div className="grid grid-cols-2 gap-3">
          <div className="p-4 rounded-xl bg-space-850/80 border border-white/[0.06] space-y-1">
            <span className="text-[10px] font-mono text-universe-slate block">BKT PROBABILITY</span>
            <div className="flex items-baseline gap-1.5">
              <span className="text-2xl font-display font-bold text-cyan-400">{masteryPercent}%</span>
              <span className="text-[10px] text-universe-slate font-mono">p(know)</span>
            </div>
          </div>

          <div className="p-4 rounded-xl bg-space-850/80 border border-white/[0.06] space-y-1">
            <span className="text-[10px] font-mono text-universe-slate block">UNCERTAINTY SPREAD</span>
            <div className="flex items-baseline gap-1.5">
              <span className={`text-2xl font-display font-bold ${uncertainty < 0.3 ? 'text-emerald-400' : uncertainty < 0.6 ? 'text-cyan-400' : 'text-amber-400'}`}>
                {Math.round(uncertainty * 100)}%
              </span>
              <span className="text-[10px] text-universe-slate font-mono">σ bound</span>
            </div>
          </div>
        </div>

        {/* Prerequisite & Downstream Topological Hierarchy */}
        <div className="space-y-3">
          <div className="p-3.5 rounded-xl bg-space-950/60 border border-white/[0.06] space-y-1.5">
            <div className="flex items-center justify-between">
              <span className="text-[10px] font-mono text-universe-slate uppercase tracking-wider flex items-center gap-1.5">
                <CheckCircle2 className="w-3.5 h-3.5 text-cyan-400" />
                Prerequisites ({prerequisites.length})
              </span>
            </div>
            <p className="text-xs text-universe-text font-sans">
              {prerequisites.length > 0
                ? prerequisites.map((p) => p.replace(/_/g, ' ')).join(', ')
                : 'None — Root foundational concept'}
            </p>
          </div>

          <div className="p-3.5 rounded-xl bg-space-950/60 border border-white/[0.06] space-y-1.5">
            <div className="flex items-center justify-between">
              <span className="text-[10px] font-mono text-universe-slate uppercase tracking-wider flex items-center gap-1.5">
                <Share2 className="w-3.5 h-3.5 text-violet-400" />
                Downstream Impact ({dependents.length})
              </span>
            </div>
            <p className="text-xs text-universe-text font-sans">
              {dependents.length > 0
                ? dependents.map((d) => d.replace(/_/g, ' ')).join(', ')
                : 'Terminal concept — No dependent nodes'}
            </p>
          </div>
        </div>

        {/* Source References & Grounding */}
        {source_references.length > 0 && (
          <div className="p-3.5 rounded-xl bg-space-950/60 border border-white/[0.06] space-y-2">
            <span className="text-[10px] font-mono text-amber-400 uppercase tracking-wider flex items-center gap-1.5">
              <FileText className="w-3.5 h-3.5" />
              Grounded Source Citations ({source_references.length})
            </span>
            <div className="space-y-2">
              {source_references.map((ref, idx) => (
                <div key={idx} className="text-[11px] text-universe-slate pl-2.5 border-l border-amber-500/40 font-mono">
                  Pg {ref.page} {ref.section ? `• §${ref.section}` : ''}: <span className="text-universe-text font-sans">"{ref.quote}"</span>
                </div>
              ))}
            </div>
          </div>
        )}

      </div>

      {/* Primary Action Matrix */}
      <div className="mt-8 pt-4 border-t border-white/[0.08] grid grid-cols-2 gap-2.5">
        <button
          onClick={() => onStartLearning(concept.concept_id)}
          className="py-3 px-4 rounded-xl bg-cyan-400 hover:bg-cyan-300 text-space-950 font-display font-bold text-xs flex items-center justify-center gap-2 shadow-[0_0_20px_rgba(0,240,255,0.25)] transition-all"
        >
          <BookOpen className="w-4 h-4" />
          <span>Study Concept</span>
        </button>

        <button
          onClick={() => onStartPractice(concept.concept_id)}
          className="py-3 px-4 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-space-950 font-display font-bold text-xs flex items-center justify-center gap-2 shadow-[0_0_20px_rgba(16,185,129,0.25)] transition-all"
        >
          <GraduationCap className="w-4 h-4" />
          <span>Practice Quiz</span>
        </button>

        <button
          onClick={() => onAskTutor(concept.concept_id)}
          className="py-2.5 px-4 rounded-xl bg-space-850 hover:bg-space-750 text-universe-text border border-white/[0.08] font-mono text-xs flex items-center justify-center gap-2 transition-all"
        >
          <MessageSquare className="w-3.5 h-3.5 text-cyan-400" />
          <span>Ask AI Tutor</span>
        </button>

        <button
          onClick={() => onTraceImpact(concept.concept_id)}
          className="py-2.5 px-4 rounded-xl bg-space-850 hover:bg-space-750 text-rose-300 border border-rose-500/30 hover:border-rose-400 font-mono text-xs flex items-center justify-center gap-2 transition-all"
        >
          <AlertTriangle className="w-3.5 h-3.5 text-rose-400" />
          <span>Trace Impact</span>
        </button>
      </div>

    </div>
  );
};
