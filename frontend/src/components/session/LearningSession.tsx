import React, { useState } from 'react';
import type { ConceptNode, Subject } from '../../api/client';
import { ApiClient } from '../../api/client';
import { BookOpen, GraduationCap, CheckCircle2, XCircle, ArrowRight, Sparkles, MessageSquare, ShieldAlert, Zap } from 'lucide-react';

export interface LearningSessionProps {
  concept: ConceptNode;
  subject: Subject;
  allConceptIds: string[];
  learnerId: string;
  onAskTutor: (conceptId: string) => void;
  onKnowledgeChanged: (updatedMasteries: Record<string, number>, targetConceptId: string) => void;
  onCloseSession: () => void;
}

export const LearningSession: React.FC<LearningSessionProps> = ({
  concept,
  subject,
  allConceptIds,
  learnerId,
  onAskTutor,
  onKnowledgeChanged,
  onCloseSession,
}) => {
  const [activeTab, setActiveTab] = useState<'EXPLANATION' | 'PRACTICE'>('EXPLANATION');
  const [selectedOptionIdx, setSelectedOptionIdx] = useState<number | null>(null);
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [feedback, setFeedback] = useState<{
    submitted: boolean;
    correct: boolean;
    explanation: string;
    oldMastery: number;
    newMastery: number;
  } | null>(null);

  // Dynamic question generated for current concept
  const mockOptions = [
    `A fundamental analytical law establishing the principles of ${concept.name}.`,
    `An optional decorative formula used strictly in graphic design.`,
    `A historic approximation superseded by modern numerical methods.`,
    `An unrelated configuration parameter.`,
  ];

  const handleSelectOption = (index: number) => {
    if (feedback?.submitted) return;
    setSelectedOptionIdx(index);
  };

  const handleSubmitResponse = async (isDontKnow: boolean = false) => {
    setIsSubmitting(true);
    const correctness = isDontKnow ? 0.0 : selectedOptionIdx === 0 ? 1.0 : 0.0;

    try {
      const res = await ApiClient.submitActivityResponse({
        learner_id: learnerId,
        subject_id: subject.id,
        concept_ids: [concept.concept_id],
        correctness,
        all_subject_concept_ids: allConceptIds,
        request_id: `req_${concept.concept_id}_${Date.now()}`,
      });

      const newM = res.updated_masteries[concept.concept_id] ?? concept.mastery;

      setFeedback({
        submitted: true,
        correct: correctness === 1.0,
        explanation: correctness === 1.0
          ? `Excellent! You demonstrated accurate understanding of ${concept.name}.`
          : isDontKnow
          ? `Signaling 'I don't know' allows Taproot to accurately record your baseline without penalty.`
          : `Not quite. Review the core relation of ${concept.name} before attempting the next target.`,
        oldMastery: concept.mastery,
        newMastery: newM,
      });

      // Trigger signature "Knowledge Changed" product moment on Atlas
      onKnowledgeChanged(res.updated_masteries, concept.concept_id);
    } catch (err) {
      console.error('Failed to submit activity response', err);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-slate-950/95 backdrop-blur-2xl p-6 overflow-y-auto flex flex-col justify-between">
      {/* Top Session Header */}
      <div className="max-w-4xl mx-auto w-full flex items-center justify-between pb-4 border-b border-slate-800">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-xl bg-cyan-950 border border-cyan-500/40 text-cyan-400">
            <BookOpen className="w-5 h-5" />
          </div>
          <div>
            <span className="text-[10px] font-mono tracking-widest text-slate-400 uppercase">
              STUDY SESSION • {subject.title}
            </span>
            <h2 className="text-xl font-black text-white">{concept.name}</h2>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={() => onAskTutor(concept.concept_id)}
            className="py-2 px-3.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 text-xs font-bold flex items-center gap-1.5 transition-all"
          >
            <MessageSquare className="w-4 h-4 text-cyan-400" />
            <span>Ask AI Tutor</span>
          </button>

          <button
            onClick={onCloseSession}
            className="py-2 px-4 rounded-xl bg-cyan-500 hover:bg-cyan-400 text-slate-950 text-xs font-bold transition-all shadow-glow-cyan"
          >
            Return to Workspace
          </button>
        </div>
      </div>

      {/* Main Workspace Workspace Card */}
      <div className="max-w-4xl mx-auto w-full my-auto py-6 space-y-6">
        {/* Navigation Tabs */}
        <div className="flex items-center gap-2 p-1 rounded-2xl bg-slate-900 border border-slate-800 w-fit">
          <button
            onClick={() => setActiveTab('EXPLANATION')}
            className={`py-2 px-5 rounded-xl text-xs font-bold flex items-center gap-2 transition-all ${
              activeTab === 'EXPLANATION'
                ? 'bg-cyan-500 text-slate-950 shadow-glow-cyan'
                : 'text-slate-400 hover:text-white'
            }`}
          >
            <BookOpen className="w-4 h-4" />
            <span>Concept Explanation</span>
          </button>

          <button
            onClick={() => setActiveTab('PRACTICE')}
            className={`py-2 px-5 rounded-xl text-xs font-bold flex items-center gap-2 transition-all ${
              activeTab === 'PRACTICE'
                ? 'bg-emerald-500 text-slate-950 shadow-glow-emerald'
                : 'text-slate-400 hover:text-white'
            }`}
          >
            <GraduationCap className="w-4 h-4" />
            <span>Adaptive Assessment</span>
          </button>
        </div>

        {/* Tab 1: Concept Explanation */}
        {activeTab === 'EXPLANATION' && (
          <div className="p-8 rounded-3xl bg-slate-900/80 border border-slate-800 shadow-2xl space-y-5">
            <h3 className="text-lg font-bold text-white flex items-center gap-2">
              <Sparkles className="w-5 h-5 text-cyan-400" />
              Core Educational Definition
            </h3>
            <p className="text-sm text-slate-200 leading-relaxed font-sans">{concept.definition}</p>

            <div className="p-4 rounded-2xl bg-slate-950/80 border border-slate-800/80 space-y-2">
              <span className="text-xs font-mono font-bold text-slate-400 uppercase">
                Prerequisite Foundations
              </span>
              <p className="text-xs text-slate-300">
                {concept.prerequisites.length > 0
                  ? concept.prerequisites.map((p) => p.replace(/_/g, ' ')).join(', ')
                  : 'This is a foundational concept with no strict prerequisites.'}
              </p>
            </div>

            <div className="pt-4 flex justify-end">
              <button
                onClick={() => setActiveTab('PRACTICE')}
                className="py-3 px-6 rounded-2xl bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-extrabold text-xs flex items-center gap-2 shadow-glow-emerald transition-all"
              >
                <span>Test Knowledge Now</span>
                <ArrowRight className="w-4 h-4" />
              </button>
            </div>
          </div>
        )}

        {/* Tab 2: Adaptive Practice Quiz */}
        {activeTab === 'PRACTICE' && (
          <div className="p-8 rounded-3xl bg-slate-900/80 border border-slate-800 shadow-2xl space-y-6">
            <div className="pb-3 border-b border-slate-800">
              <span className="text-[10px] font-mono tracking-widest text-emerald-400 font-bold uppercase">
                ADAPTIVE QUIZ QUESTION
              </span>
              <h3 className="text-base font-bold text-white mt-1">
                Which option accurately defines {concept.name}?
              </h3>
            </div>

            {/* Quiz Options */}
            <div className="space-y-3">
              {mockOptions.map((opt, idx) => {
                const isSelected = selectedOptionIdx === idx;
                return (
                  <button
                    key={idx}
                    onClick={() => handleSelectOption(idx)}
                    disabled={feedback?.submitted}
                    className={`w-full p-4 rounded-2xl border text-left text-xs font-medium transition-all duration-300 flex items-center justify-between gap-4 ${
                      isSelected
                        ? 'border-cyan-400 bg-cyan-950/60 text-white shadow-glow-cyan'
                        : 'border-slate-800 bg-slate-950/60 text-slate-300 hover:bg-slate-800'
                    }`}
                  >
                    <span>{opt}</span>
                    {isSelected && <CheckCircle2 className="w-4 h-4 text-cyan-400 shrink-0" />}
                  </button>
                );
              })}
            </div>

            {/* "I Don't Know" Button (Part 23 Requirement) */}
            {!feedback?.submitted && (
              <div className="flex items-center justify-between pt-2">
                <button
                  onClick={() => handleSubmitResponse(true)}
                  disabled={isSubmitting}
                  className="py-2.5 px-4 rounded-xl border border-amber-500/40 bg-amber-950/30 hover:bg-amber-900/50 text-amber-200 text-xs font-mono font-bold flex items-center gap-2 transition-all"
                >
                  <ShieldAlert className="w-4 h-4 text-amber-400" />
                  <span>I don't know this option</span>
                </button>

                <button
                  onClick={() => handleSubmitResponse(false)}
                  disabled={selectedOptionIdx === null || isSubmitting}
                  className={`py-3 px-6 rounded-2xl font-bold text-xs flex items-center gap-2 transition-all ${
                    selectedOptionIdx !== null
                      ? 'bg-emerald-500 hover:bg-emerald-400 text-slate-950 shadow-glow-emerald cursor-pointer'
                      : 'bg-slate-800 text-slate-500 cursor-not-allowed'
                  }`}
                >
                  <span>Submit Answer</span>
                  <ArrowRight className="w-4 h-4" />
                </button>
              </div>
            )}

            {/* Post-Submission "Knowledge Changed" Feedback Banner */}
            {feedback?.submitted && (
              <div className="p-5 rounded-2xl border border-emerald-500/40 bg-emerald-950/40 shadow-glow-emerald animate-pulse-glow space-y-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    {feedback.correct ? (
                      <CheckCircle2 className="w-5 h-5 text-emerald-400" />
                    ) : (
                      <XCircle className="w-5 h-5 text-rose-400" />
                    )}
                    <span className="text-xs font-mono font-bold text-emerald-300 uppercase tracking-widest">
                      KNOWLEDGE STATE UPDATED
                    </span>
                  </div>

                  <div className="flex items-center gap-2 font-mono text-xs">
                    <span className="text-slate-400">{Math.round(feedback.oldMastery * 100)}%</span>
                    <ArrowRight className="w-3.5 h-3.5 text-cyan-400" />
                    <span className="text-emerald-300 font-extrabold">{Math.round(feedback.newMastery * 100)}% Mastery</span>
                  </div>
                </div>

                <p className="text-xs text-slate-200 leading-relaxed">{feedback.explanation}</p>

                <div className="pt-2 flex justify-end">
                  <button
                    onClick={onCloseSession}
                    className="py-2.5 px-5 rounded-xl bg-cyan-500 hover:bg-cyan-400 text-slate-950 font-extrabold text-xs flex items-center gap-2 shadow-glow-cyan transition-all"
                  >
                    <Zap className="w-4 h-4 fill-current" />
                    <span>See Changed Knowledge Atlas</span>
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};
