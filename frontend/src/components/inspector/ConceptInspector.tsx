import React from 'react';
import type { ConceptNode, TopicTerritory } from '../../api/client';
import { getConceptDisplayName } from '../../utils/conceptName';
import {
  X,
  BookOpen,
  GraduationCap,
  MessageSquare,
  CheckCircle2,
  AlertTriangle,
  FileText,
  Share2,
  Layers,
  ArrowLeft,
  ShieldAlert,
} from 'lucide-react';

export interface ConceptInspectorProps {
  concept: ConceptNode | null;
  topic?: TopicTerritory | null;
  conceptMap?: Record<string, string>;
  onClose: () => void;
  onStartLearning: (conceptId: string) => void;
  onStartPractice: (conceptId: string) => void;
  onAskTutor: (conceptId: string) => void;
  onTraceImpact: (nodeId: string) => void;
  onSelectConcept?: (concept: ConceptNode) => void;
  onBackToTopic?: () => void;
}

export const ConceptInspector: React.FC<ConceptInspectorProps> = ({
  concept,
  topic,
  conceptMap,
  onClose,
  onStartLearning,
  onStartPractice,
  onAskTutor,
  onTraceImpact,
  onSelectConcept,
  onBackToTopic,
}) => {
  if (!concept && !topic) return null;

  // ──────────────────────────────────────────────
  // CASE 1: SUBHEADING / TOPIC LEARNING PLAN VIEW
  // ──────────────────────────────────────────────
  if (topic && !concept) {
    const topicMasteryPercent = Math.round((topic.mastery ?? 0.5) * 100);
    const conceptsList = topic.concepts || [];
    const prereqs = topic.prerequisites || [];
    const dependents = topic.dependents || [];

    return (
      <div className="fixed inset-y-0 right-0 z-50 w-full max-w-lg bg-space-900/95 border-l border-white/[0.08] backdrop-blur-2xl shadow-[0_0_64px_rgba(0,0,0,0.8)] p-6 lg:p-8 overflow-y-auto flex flex-col justify-between animate-fade-in">
        <div className="space-y-6">
          {/* Header */}
          <div className="flex items-center justify-between pb-4 border-b border-white/[0.07]">
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-cyan-400 shadow-[0_0_8px_#00F0FF]" />
              <span className="text-[10px] font-mono font-bold tracking-widest text-cyan-300 uppercase">
                SUBHEADING {topic.order < 10 ? `0${topic.order}` : topic.order} // LEARNING PLAN
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

          {/* Subheading Title & Overview */}
          <div className="space-y-3">
            <div className="flex items-baseline justify-between gap-3">
              <h2 className="text-2xl font-display font-bold text-white tracking-tight leading-snug">
                {topic.name}
              </h2>
              <span className="text-sm font-mono font-bold text-cyan-400 shrink-0">
                {topicMasteryPercent}% Mastery
              </span>
            </div>

            <p className="text-xs text-universe-slate leading-relaxed font-sans">
              Curriculum module comprising <strong className="text-white font-bold">{conceptsList.length} core concepts</strong>. Master foundational concepts first to build durable comprehension along the prerequisite topology.
            </p>
          </div>

          {/* Metrics Grid */}
          <div className="grid grid-cols-2 gap-3">
            <div className="p-4 rounded-xl bg-space-850/80 border border-white/[0.06] space-y-1">
              <span className="text-[10px] font-mono text-universe-slate block">MODULE MASTERY</span>
              <div className="flex items-baseline gap-1.5">
                <span className="text-2xl font-display font-bold text-cyan-400">{topicMasteryPercent}%</span>
                <span className="text-[10px] text-universe-slate font-mono">bkt mean</span>
              </div>
            </div>

            <div className="p-4 rounded-xl bg-space-850/80 border border-white/[0.06] space-y-1">
              <span className="text-[10px] font-mono text-universe-slate block">CONCEPTS TOTAL</span>
              <div className="flex items-baseline gap-1.5">
                <span className="text-2xl font-display font-bold text-emerald-400">{conceptsList.length}</span>
                <span className="text-[10px] text-universe-slate font-mono">active units</span>
              </div>
            </div>
          </div>

          {/* Prerequisites & Downstream Cascade */}
          <div className="space-y-2.5">
            <div className="p-3.5 rounded-xl bg-space-950/60 border border-white/[0.06] space-y-1">
              <div className="flex items-center justify-between">
                <span className="text-[10px] font-mono text-universe-slate uppercase tracking-wider flex items-center gap-1.5">
                  <CheckCircle2 className="w-3.5 h-3.5 text-cyan-400" />
                  Prerequisite Subheadings ({prereqs.length})
                </span>
              </div>
              <p className="text-xs text-universe-text font-sans">
                {prereqs.length > 0 ? prereqs.map((p) => getConceptDisplayName(p, conceptMap)).join(', ') : 'None — Curriculum Root Module'}
              </p>
            </div>

            <div className="p-3.5 rounded-xl bg-space-950/60 border border-white/[0.06] space-y-1">
              <div className="flex items-center justify-between">
                <span className="text-[10px] font-mono text-universe-slate uppercase tracking-wider flex items-center gap-1.5">
                  <Share2 className="w-3.5 h-3.5 text-violet-400" />
                  Downstream Impact ({dependents.length})
                </span>
              </div>
              <p className="text-xs text-universe-text font-sans">
                {dependents.length > 0 ? dependents.map((d) => getConceptDisplayName(d, conceptMap)).join(', ') : 'Terminal Module — No dependent subheadings'}
              </p>
            </div>
          </div>

          {/* Subheading Learning Plan: Expandable Concepts List */}
          <div className="space-y-3 pt-2">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Layers className="w-4 h-4 text-cyan-400" />
                <h3 className="text-xs font-mono font-bold tracking-wider text-white uppercase">
                  EXPANDED LEARNING PLAN ({conceptsList.length} CONCEPTS)
                </h3>
              </div>
              <span className="text-[10px] font-mono text-universe-slate">Step-by-step</span>
            </div>

            <div className="space-y-2.5 max-h-[340px] overflow-y-auto pr-1">
              {conceptsList.map((c, idx) => {
                const cMastery = Math.round((c.mastery || 0) * 100);
                const isMastered = cMastery >= 75;
                const isAttention = cMastery < 35;

                return (
                  <div
                    key={c.concept_id}
                    className="p-3.5 rounded-xl bg-space-850/80 hover:bg-space-800/90 border border-white/[0.06] hover:border-cyan-500/40 transition-all space-y-2 group"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="space-y-0.5">
                        <div className="flex items-center gap-2">
                          <span className="text-[10px] font-mono text-cyan-400 font-bold">
                            {idx + 1}.
                          </span>
                          <h4 className="text-xs font-display font-bold text-white group-hover:text-cyan-300 transition-colors">
                            {c.name}
                          </h4>
                        </div>
                        {c.definition && (
                          <p className="text-[11px] text-universe-slate line-clamp-2 leading-relaxed font-sans pl-4">
                            {c.definition}
                          </p>
                        )}
                      </div>

                      <span
                        className={`text-[10px] font-mono px-2 py-0.5 rounded font-bold shrink-0 ${
                          isMastered
                            ? 'bg-emerald-950/70 text-emerald-300 border border-emerald-500/40'
                            : isAttention
                            ? 'bg-amber-950/70 text-amber-300 border border-amber-500/40'
                            : 'bg-cyan-950/70 text-cyan-300 border border-cyan-500/40'
                        }`}
                      >
                        {cMastery}%
                      </span>
                    </div>

                    {/* Quick Concept Action Buttons */}
                    <div className="flex flex-wrap items-center gap-1.5 pt-1 pl-4">
                      <button
                        onClick={() => onStartLearning(c.concept_id)}
                        className="px-2.5 py-1 rounded-lg bg-cyan-400/10 hover:bg-cyan-400 hover:text-space-950 text-cyan-300 text-[10px] font-mono font-bold border border-cyan-500/30 transition-all flex items-center gap-1"
                      >
                        <BookOpen className="w-3 h-3" />
                        <span>Study</span>
                      </button>

                      <button
                        onClick={() => onStartPractice(c.concept_id)}
                        className="px-2.5 py-1 rounded-lg bg-emerald-500/10 hover:bg-emerald-500 hover:text-space-950 text-emerald-300 text-[10px] font-mono font-bold border border-emerald-500/30 transition-all flex items-center gap-1"
                      >
                        <GraduationCap className="w-3 h-3" />
                        <span>Quiz</span>
                      </button>

                      <button
                        onClick={() => onAskTutor(c.concept_id)}
                        className="px-2.5 py-1 rounded-lg bg-space-950 hover:bg-space-750 text-universe-slate hover:text-white text-[10px] font-mono border border-white/[0.06] transition-all flex items-center gap-1"
                      >
                        <MessageSquare className="w-3 h-3 text-cyan-400" />
                        <span>Tutor</span>
                      </button>

                      {onSelectConcept && (
                        <button
                          onClick={() => onSelectConcept(c)}
                          className="px-2.5 py-1 rounded-lg bg-space-950 hover:bg-space-750 text-universe-slate hover:text-cyan-300 text-[10px] font-mono border border-white/[0.06] transition-all flex items-center gap-1 ml-auto"
                        >
                          <span>Inspect →</span>
                        </button>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        {/* Trace Impact Action Footer */}
        <div className="mt-6 pt-4 border-t border-white/[0.08] flex items-center gap-3">
          <button
            onClick={() => onTraceImpact(topic.id)}
            className="w-full py-3 px-4 rounded-xl bg-space-850 hover:bg-rose-950/80 text-rose-300 border border-rose-500/30 hover:border-rose-400 font-mono text-xs font-bold flex items-center justify-center gap-2 transition-all shadow-[0_0_20px_rgba(244,63,94,0.15)]"
          >
            <ShieldAlert className="w-4 h-4 text-rose-400" />
            <span>Trace Downstream Subheading Cascade</span>
          </button>
        </div>
      </div>
    );
  }

  // ──────────────────────────────────────────────
  // CASE 2: SINGLE CONCEPT DETAIL VIEW
  // ──────────────────────────────────────────────
  const {
    name,
    definition = '',
    mastery = 0.5,
    uncertainty = 0.3,
    prerequisites = [],
    dependents = [],
    source_references = [],
  } = concept!;

  const masteryPercent = Math.round(mastery * 100);

  return (
    <div className="fixed inset-y-0 right-0 z-50 w-full max-w-lg bg-space-900/95 border-l border-white/[0.08] backdrop-blur-2xl shadow-[0_0_64px_rgba(0,0,0,0.8)] p-6 lg:p-8 overflow-y-auto flex flex-col justify-between animate-fade-in">
      <div className="space-y-6">
        {/* Header Telemetry */}
        <div className="flex items-center justify-between pb-4 border-b border-white/[0.07]">
          <div className="flex items-center gap-2">
            {topic && onBackToTopic && (
              <button
                onClick={onBackToTopic}
                className="p-1 rounded-lg bg-space-800 hover:bg-space-750 text-cyan-400 transition-colors mr-1 flex items-center gap-1 text-[10px] font-mono"
              >
                <ArrowLeft className="w-3.5 h-3.5" />
                <span>Subheading Plan</span>
              </button>
            )}
            <span className="w-2 h-2 rounded-full bg-cyan-400 shadow-[0_0_8px_#00F0FF]" />
            <span className="text-[10px] font-mono font-bold tracking-widest text-universe-slate uppercase">
              CONCEPT X-RAY TELEMETRY
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
              <span
                className={`text-2xl font-display font-bold ${
                  uncertainty < 0.3 ? 'text-emerald-400' : uncertainty < 0.6 ? 'text-cyan-400' : 'text-amber-400'
                }`}
              >
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
                ? prerequisites.map((p) => getConceptDisplayName(p, conceptMap)).join(', ')
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
                ? dependents.map((d) => getConceptDisplayName(d, conceptMap)).join(', ')
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
          onClick={() => onStartLearning(concept!.concept_id)}
          className="py-3 px-4 rounded-xl bg-cyan-400 hover:bg-cyan-300 text-space-950 font-display font-bold text-xs flex items-center justify-center gap-2 shadow-[0_0_20px_rgba(0,240,255,0.25)] transition-all cursor-pointer"
        >
          <BookOpen className="w-4 h-4" />
          <span>Study Concept</span>
        </button>

        <button
          onClick={() => onStartPractice(concept!.concept_id)}
          className="py-3 px-4 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-space-950 font-display font-bold text-xs flex items-center justify-center gap-2 shadow-[0_0_20px_rgba(16,185,129,0.25)] transition-all cursor-pointer"
        >
          <GraduationCap className="w-4 h-4" />
          <span>Practice Quiz</span>
        </button>

        <button
          onClick={() => onAskTutor(concept!.concept_id)}
          className="py-2.5 px-4 rounded-xl bg-space-850 hover:bg-space-750 text-universe-text border border-white/[0.08] font-mono text-xs flex items-center justify-center gap-2 transition-all cursor-pointer"
        >
          <MessageSquare className="w-3.5 h-3.5 text-cyan-400" />
          <span>Ask AI Tutor</span>
        </button>

        <button
          onClick={() => onTraceImpact(concept!.concept_id)}
          className="py-2.5 px-4 rounded-xl bg-space-850 hover:bg-space-750 text-rose-300 border border-rose-500/30 hover:border-rose-400 font-mono text-xs flex items-center justify-center gap-2 transition-all cursor-pointer"
        >
          <AlertTriangle className="w-3.5 h-3.5 text-rose-400" />
          <span>Trace Impact</span>
        </button>
      </div>
    </div>
  );
};
