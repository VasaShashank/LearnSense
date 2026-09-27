import React, { useState } from 'react';
import type { ConceptNode, Subject, ConceptLearningContent } from '../../api/client';
import { ApiClient } from '../../api/client';
import { BookOpen, GraduationCap, CheckCircle2, XCircle, ArrowRight, Sparkles, MessageSquare, ShieldAlert, Zap, RefreshCw, Lightbulb, AlertTriangle } from 'lucide-react';

export interface LearningSessionProps {
  concept: ConceptNode;
  subject: Subject;
  allConceptIds: string[];
  learnerId: string;
  initialTab?: 'EXPLANATION' | 'PRACTICE';
  onAskTutor: (conceptId: string) => void;
  onKnowledgeChanged: (updatedMasteries: Record<string, number>, targetConceptId: string) => void;
  onCloseSession: () => void;
}

export const LearningSession: React.FC<LearningSessionProps> = ({
  concept,
  subject,
  allConceptIds,
  learnerId,
  initialTab = 'EXPLANATION',
  onAskTutor,
  onKnowledgeChanged,
  onCloseSession,
}) => {
  const [activeTab, setActiveTab] = useState<'EXPLANATION' | 'PRACTICE'>(initialTab);

  React.useEffect(() => {
    setActiveTab(initialTab);
  }, [initialTab, concept.concept_id]);
  const [selectedOptionIdx, setSelectedOptionIdx] = useState<number | null>(null);
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [loadingQuestion, setLoadingQuestion] = useState<boolean>(true);
  const [loadingContent, setLoadingContent] = useState<boolean>(true);
  const [learningContent, setLearningContent] = useState<ConceptLearningContent | null>(null);
  const [question, setQuestion] = useState<{
    question_text: string;
    options: string[];
    correct_answer: string;
    explanation: string;
  } | null>(null);
  const [feedback, setFeedback] = useState<{
    submitted: boolean;
    correct: boolean;
    explanation: string;
    oldMastery: number;
    newMastery: number;
  } | null>(null);

  // Fetch authentic domain question and comprehensive learning content
  React.useEffect(() => {
    let isMounted = true;
    setLoadingQuestion(true);
    setLoadingContent(true);

    // 1. Fetch Question
    ApiClient.getConceptQuestion(subject.id, concept.concept_id)
      .then((data) => {
        if (isMounted && data) {
          setQuestion(data);
        }
      })
      .catch((err) => {
        console.warn('Could not load authentic concept question, using fallback', err);
      })
      .finally(() => {
        if (isMounted) setLoadingQuestion(false);
      });

    // 2. Fetch Learning Lesson Content
    ApiClient.getConceptContent(subject.id, concept.concept_id)
      .then((data) => {
        if (isMounted && data) {
          setLearningContent(data);
        }
      })
      .catch((err) => {
        console.warn('Could not load concept learning content', err);
      })
      .finally(() => {
        if (isMounted) setLoadingContent(false);
      });

    return () => {
      isMounted = false;
    };
  }, [subject.id, concept.concept_id]);

  const activeOptions = question?.options || [];


  const handleSelectOption = (index: number) => {
    if (feedback?.submitted) return;
    setSelectedOptionIdx(index);
  };

  const handleSubmitResponse = async (isDontKnow: boolean = false) => {
    setIsSubmitting(true);
    const isCorrect = selectedOptionIdx !== null && question
      ? question.options[selectedOptionIdx]?.trim() === question.correct_answer?.trim()
      : selectedOptionIdx === 0;

    const correctness = isDontKnow ? 0.0 : isCorrect ? 1.0 : 0.0;

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
          ? (question?.explanation || `Excellent! You demonstrated accurate understanding of ${concept.name}.`)
          : isDontKnow
          ? `Signaling 'I don't know' allows LearnSense to accurately identify your baseline knowledge gaps without penalty.`
          : (question?.explanation
              ? `Incorrect. ${question.explanation}`
              : `Review the core relationships of ${concept.name} before attempting the next target.`),
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
            className={`py-2.5 px-5 rounded-xl text-xs font-bold flex items-center gap-2 transition-all ${
              activeTab === 'EXPLANATION'
                ? 'bg-cyan-500 text-slate-950 shadow-glow-cyan'
                : 'text-slate-400 hover:text-white'
            }`}
          >
            <BookOpen className="w-4 h-4" />
            <span>Learning Content & Study Guide</span>
          </button>

          <button
            onClick={() => setActiveTab('PRACTICE')}
            className={`py-2.5 px-5 rounded-xl text-xs font-bold flex items-center gap-2 transition-all ${
              activeTab === 'PRACTICE'
                ? 'bg-emerald-500 text-slate-950 shadow-glow-emerald'
                : 'text-slate-400 hover:text-white'
            }`}
          >
            <GraduationCap className="w-4 h-4" />
            <span>Practice Questions & Adaptive Quiz</span>
          </button>
        </div>

        {/* Tab 1: Comprehensive Concept Lesson Guide */}
        {activeTab === 'EXPLANATION' && (
          <div className="p-8 rounded-3xl bg-slate-900/90 border border-slate-800 shadow-2xl space-y-7">
            {loadingContent ? (
              <div className="py-16 text-center space-y-4">
                <RefreshCw className="w-8 h-8 text-cyan-400 animate-spin mx-auto" />
                <h4 className="text-sm font-bold text-white">Synthesizing Pedagogical Learning Guide...</h4>
                <p className="text-xs text-slate-400 max-w-sm mx-auto font-mono">
                  Groq LLM is extracting theoretical foundations, worked examples, and mental models for {concept.name}.
                </p>
              </div>
            ) : (
              <>
                {/* 1. Overview & Theoretical Framework */}
                <div className="space-y-3">
                  <div className="flex items-center gap-2">
                    <Sparkles className="w-5 h-5 text-cyan-400" />
                    <h3 className="text-lg font-extrabold text-white">
                      Core Theory & Conceptual Foundation
                    </h3>
                  </div>
                  <div className="text-sm text-slate-200 leading-relaxed font-sans whitespace-pre-line space-y-2 bg-slate-950/40 p-5 rounded-2xl border border-slate-800/80">
                    {learningContent?.overview || concept.definition}
                  </div>
                </div>

                {/* 2. Mental Model & Intuition */}
                {learningContent?.intuition && (
                  <div className="p-5 rounded-2xl bg-gradient-to-r from-amber-950/40 via-slate-950 to-slate-900 border border-amber-500/40 space-y-2 shadow-glow-amber">
                    <h4 className="text-xs font-mono font-bold text-amber-300 uppercase flex items-center gap-2">
                      <Lightbulb className="w-4 h-4 text-amber-400 shrink-0" />
                      Intuitive Mental Model & The "Why"
                    </h4>
                    <p className="text-xs text-slate-200 leading-relaxed">
                      {learningContent.intuition}
                    </p>
                  </div>
                )}

                {/* 3. Key Principles & Governing Rules */}
                {learningContent?.key_principles && learningContent.key_principles.length > 0 && (
                  <div className="space-y-3">
                    <h4 className="text-xs font-mono font-bold text-cyan-300 uppercase flex items-center gap-2">
                      <CheckCircle2 className="w-4 h-4 text-cyan-400" />
                      Core Principles & Mathematical Rules
                    </h4>
                    <div className="grid grid-cols-1 gap-2.5">
                      {learningContent.key_principles.map((principle, idx) => (
                        <div
                          key={idx}
                          className="p-3.5 rounded-xl bg-slate-950/80 border border-slate-800 text-xs text-slate-200 flex items-start gap-3"
                        >
                          <span className="w-5 h-5 rounded-full bg-cyan-950 border border-cyan-500/50 text-cyan-300 text-[10px] font-mono flex items-center justify-center shrink-0 mt-0.5">
                            {idx + 1}
                          </span>
                          <span className="leading-relaxed">{principle}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* 4. Step-by-Step Worked Example */}
                {learningContent?.worked_example && (
                  <div className="p-5 rounded-2xl bg-slate-950/80 border border-slate-800 space-y-4">
                    <h4 className="text-xs font-mono font-bold text-violet-300 uppercase flex items-center gap-2">
                      <BookOpen className="w-4 h-4 text-violet-400" />
                      Step-by-Step Worked Problem
                    </h4>

                    <div className="p-3 rounded-xl bg-violet-950/30 border border-violet-500/30 text-xs font-mono text-violet-200">
                      <strong>Problem:</strong> {learningContent.worked_example.problem}
                    </div>

                    <div className="space-y-2">
                      {learningContent.worked_example.steps.map((step, sIdx) => (
                        <div key={sIdx} className="text-xs text-slate-300 pl-3 border-l-2 border-slate-700 leading-relaxed">
                          {step}
                        </div>
                      ))}
                    </div>

                    <div className="p-3 rounded-xl bg-emerald-950/40 border border-emerald-500/40 text-xs text-emerald-200 font-mono">
                      <strong>Solution:</strong> {learningContent.worked_example.solution}
                    </div>
                  </div>
                )}

                {/* 5. Common Pitfalls & Misconceptions */}
                {learningContent?.common_misconceptions && learningContent.common_misconceptions.length > 0 && (
                  <div className="p-5 rounded-2xl bg-rose-950/30 border border-rose-500/40 space-y-2.5">
                    <h4 className="text-xs font-mono font-bold text-rose-300 uppercase flex items-center gap-2">
                      <AlertTriangle className="w-4 h-4 text-rose-400 shrink-0" />
                      Common Misconceptions & Traps to Avoid
                    </h4>
                    <ul className="space-y-1.5 list-disc list-inside text-xs text-rose-100/90 leading-relaxed">
                      {learningContent.common_misconceptions.map((misc, mIdx) => (
                        <li key={mIdx}>{misc}</li>
                      ))}
                    </ul>
                  </div>
                )}

                {/* 6. Key Takeaway */}
                {learningContent?.key_takeaway && (
                  <div className="p-4 rounded-2xl bg-gradient-to-r from-emerald-950/60 to-slate-900 border border-emerald-500/50 flex items-center gap-3">
                    <Zap className="w-5 h-5 text-emerald-400 shrink-0" />
                    <div>
                      <span className="text-[10px] font-mono text-emerald-400 uppercase tracking-wider block">
                        KEY TAKEAWAY & RULE OF THUMB
                      </span>
                      <p className="text-xs font-bold text-white mt-0.5">
                        {learningContent.key_takeaway}
                      </p>
                    </div>
                  </div>
                )}

                {/* Prerequisites Reminder & Call-to-Action */}
                <div className="pt-2 flex flex-wrap items-center justify-between gap-4 border-t border-slate-800">
                  <div className="text-xs text-slate-400">
                    <span className="font-mono text-slate-500 mr-1">Prerequisites:</span>
                    {concept.prerequisites.length > 0
                      ? concept.prerequisites.map((p) => p.replace(/_/g, ' ')).join(', ')
                      : 'None (Foundational core concept)'}
                  </div>

                  <button
                    onClick={() => setActiveTab('PRACTICE')}
                    className="py-3 px-6 rounded-2xl bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-black text-xs flex items-center gap-2 shadow-glow-emerald transition-all"
                  >
                    <span>Ready to Practice? Take Adaptive Quiz</span>
                    <ArrowRight className="w-4 h-4" />
                  </button>
                </div>
              </>
            )}
          </div>
        )}

        {/* Tab 2: Adaptive Practice Quiz */}
        {activeTab === 'PRACTICE' && (
          <div className="p-8 rounded-3xl bg-slate-900/80 border border-slate-800 shadow-2xl space-y-6">
            <div className="pb-3 border-b border-slate-800">
              <span className="text-[10px] font-mono tracking-widest text-emerald-400 font-bold uppercase">
                {loadingQuestion ? 'GENERATING QUESTION...' : 'ADAPTIVE QUIZ QUESTION'}
              </span>
              <h3 className="text-base font-bold text-white mt-1 leading-snug">
                {loadingQuestion
                  ? `Analyzing concept fundamentals for ${concept.name}...`
                  : (question?.question_text || `Which statement accurately characterizes ${concept.name}?`)}
              </h3>
            </div>

            {/* Quiz Options */}
            {loadingQuestion ? (
              <div className="py-10 text-center space-y-3">
                <RefreshCw className="w-8 h-8 text-cyan-400 animate-spin mx-auto" />
                <p className="text-xs text-slate-300 font-mono">Generating concept-specific assessment with Groq LLM...</p>
              </div>
            ) : activeOptions.length === 0 ? (
              <div className="py-8 text-center text-xs text-slate-400 font-mono">
                No active assessment questions available for this concept.
              </div>
            ) : (
              <div className="space-y-3">
                {activeOptions.map((opt, idx) => {
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
                      <span className="leading-relaxed">{opt}</span>
                      {isSelected && <CheckCircle2 className="w-4 h-4 text-cyan-400 shrink-0" />}
                    </button>
                  );
                })}
              </div>
            )}

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
