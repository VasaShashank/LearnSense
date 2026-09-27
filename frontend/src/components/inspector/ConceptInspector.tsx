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

  const { name, definition, mastery, uncertainty, prerequisites, dependents, source_references } = concept;

  return (
    <div className="fixed inset-y-0 right-0 z-50 w-full max-w-md bg-slate-900/95 border-l border-slate-800 backdrop-blur-2xl shadow-2xl p-6 overflow-y-auto flex flex-col justify-between transition-all duration-300">
      <div>
        {/* Header */}
        <div className="flex items-center justify-between pb-4 border-b border-slate-800">
          <div className="flex items-center gap-2">
            <span className="w-2.5 h-2.5 rounded-full bg-cyan-400 shadow-glow-cyan" />
            <h3 className="text-xs font-mono font-bold tracking-widest text-slate-400 uppercase">
              CONCEPT INSPECTOR
            </h3>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-400 hover:text-white transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Title & Definition */}
        <div className="mt-5">
          <h2 className="text-xl font-bold text-white tracking-tight">{name}</h2>
          <p className="text-xs text-slate-300/80 leading-relaxed mt-2 p-3 rounded-xl bg-slate-950/60 border border-slate-800/60">
            {definition}
          </p>
        </div>

        {/* Analytics Breakdown Grid */}
        <div className="grid grid-cols-2 gap-3 mt-5">
          <div className="p-3.5 rounded-2xl bg-slate-950/80 border border-slate-800">
            <span className="text-[10px] font-mono text-slate-400 block">MASTERY</span>
            <div className="flex items-baseline gap-1 mt-1">
              <span className="text-2xl font-extrabold text-cyan-400">{Math.round(mastery * 100)}%</span>
              <span className="text-[10px] text-slate-500 font-mono">BKT score</span>
            </div>
          </div>

          <div className="p-3.5 rounded-2xl bg-slate-950/80 border border-slate-800">
            <span className="text-[10px] font-mono text-slate-400 block">CONFIDENCE</span>
            <div className="flex items-baseline gap-1 mt-1">
              <span className="text-2xl font-extrabold text-emerald-400">
                {uncertainty < 0.3 ? 'HIGH' : uncertainty < 0.6 ? 'MED' : 'LOW'}
              </span>
            </div>
          </div>
        </div>

        {/* Prerequisites & Downstream concepts */}
        <div className="mt-5 space-y-3">
          <div className="p-3 rounded-xl bg-slate-950/60 border border-slate-800">
            <h4 className="text-xs font-mono font-semibold text-slate-400 mb-1.5 flex items-center gap-1.5">
              <CheckCircle2 className="w-3.5 h-3.5 text-cyan-400" />
              PREREQUISITES ({prerequisites.length})
            </h4>
            <p className="text-xs text-slate-300">
              {prerequisites.length > 0
                ? prerequisites.map((p) => p.replace('_', ' ')).join(', ')
                : 'None (Foundational core concept)'}
            </p>
          </div>

          <div className="p-3 rounded-xl bg-slate-950/60 border border-slate-800">
            <h4 className="text-xs font-mono font-semibold text-slate-400 mb-1.5 flex items-center gap-1.5">
              <Share2 className="w-3.5 h-3.5 text-violet-400" />
              DOWNSTREAM DEPENDENTS ({dependents.length})
            </h4>
            <p className="text-xs text-slate-300">
              {dependents.length > 0
                ? dependents.map((d) => d.replace('_', ' ')).join(', ')
                : 'Terminal concept'}
            </p>
          </div>
        </div>

        {/* Source References */}
        {source_references.length > 0 && (
          <div className="mt-5 p-3 rounded-xl bg-slate-950/60 border border-slate-800">
            <h4 className="text-xs font-mono font-semibold text-slate-400 mb-1.5 flex items-center gap-1.5">
              <FileText className="w-3.5 h-3.5 text-amber-400" />
              SUPPORTING SOURCE CITATIONS
            </h4>
            {source_references.map((ref, idx) => (
              <div key={idx} className="text-[11px] text-slate-300/80 mt-1 pl-2 border-l border-amber-500/40">
                Page {ref.page} ({ref.section}): "{ref.quote}"
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Action Bar */}
      <div className="mt-6 pt-4 border-t border-slate-800 grid grid-cols-2 gap-2">
        <button
          onClick={() => onStartLearning(concept.concept_id)}
          className="py-2.5 px-3 rounded-xl bg-cyan-500 hover:bg-cyan-400 text-slate-950 font-bold text-xs flex items-center justify-center gap-1.5 shadow-glow-cyan transition-all"
        >
          <BookOpen className="w-4 h-4" />
          <span>Learn</span>
        </button>

        <button
          onClick={() => onStartPractice(concept.concept_id)}
          className="py-2.5 px-3 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-bold text-xs flex items-center justify-center gap-1.5 shadow-glow-emerald transition-all"
        >
          <GraduationCap className="w-4 h-4" />
          <span>Practice Quiz</span>
        </button>

        <button
          onClick={() => onAskTutor(concept.concept_id)}
          className="py-2.5 px-3 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 font-bold text-xs flex items-center justify-center gap-1.5 transition-all"
        >
          <MessageSquare className="w-4 h-4 text-cyan-400" />
          <span>Ask Tutor</span>
        </button>

        <button
          onClick={() => onTraceImpact(concept.concept_id)}
          className="py-2.5 px-3 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 font-bold text-xs flex items-center justify-center gap-1.5 transition-all"
        >
          <AlertTriangle className="w-4 h-4 text-rose-400" />
          <span>Trace Impact</span>
        </button>
      </div>
    </div>
  );
};
