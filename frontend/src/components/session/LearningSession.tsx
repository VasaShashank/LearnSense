import React, { useState } from 'react';
import type { ConceptNode, Subject, ConceptLearningContent } from '../../api/client';
import { ApiClient } from '../../api/client';
import { BookOpen, GraduationCap, CheckCircle2, XCircle, ArrowRight, Sparkles, MessageSquare, ShieldAlert, Zap, RefreshCw, ArrowLeft } from 'lucide-react';

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
  allConceptIds: _allConceptIds,
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
    question_id: string;
    concept_id: string;
    question_text: string;
    options: string[];
    source_citations?: Array<{
      document_id: string;
      page: number;
      section?: string;
      block_id: string;
      quote: string;
    }>;
    no_questions?: boolean;
  } | null>(null);
  const [feedback, setFeedback] = useState<{
    submitted: boolean;
    correct: boolean;
    explanation: string;
    correct_answer?: string;
    oldMastery: number;
    newMastery: number;
  } | null>(null);

  // Fetch domain question and comprehensive learning lesson
  React.useEffect(() => {
    let isMounted = true;
    setLoadingQuestion(true);
    setLoadingContent(true);

    // Timeout for question fetch (15 seconds)
    const questionTimeout = setTimeout(() => {
      if (isMounted) {
        console.warn('Question fetch timed out after 15 seconds');
        setLoadingQuestion(false);
        setQuestion({ no_questions: true, question_id: '', concept_id: concept.concept_id, question_text: '', options: [] });
      }
    }, 15000);

    // 1. Fetch Question
    ApiClient.getConceptQuestion(subject.id, concept.concept_id)
      .then((data) => {
        clearTimeout(questionTimeout);
        if (isMounted && data) {
          setQuestion(data);
        }
      })
      .catch((err) => {
        clearTimeout(questionTimeout);
        console.warn('Could not load authentic concept question:', err);
        if (isMounted) {
          setQuestion({ no_questions: true, question_id: '', concept_id: concept.concept_id, question_text: '', options: [] });
        }
      })
      .finally(() => {
        if (isMounted) setLoadingQuestion(false);
      });

    // Timeout for content fetch (10 seconds)
    const contentTimeout = setTimeout(() => {
      if (isMounted) {
        console.warn('Content fetch timed out after 10 seconds');
        setLoadingContent(false);
      }
    }, 10000);

    // 2. Fetch Learning Lesson Content
    ApiClient.getConceptContent(subject.id, concept.concept_id)
      .then((data) => {
        clearTimeout(contentTimeout);
        if (isMounted && data) {
          setLearningContent(data);
        }
      })
      .catch((err) => {
        clearTimeout(contentTimeout);
        console.warn('Could not load concept learning content:', err);
      })
      .finally(() => {
        if (isMounted) setLoadingContent(false);
      });

    return () => {
      isMounted = false;
      clearTimeout(questionTimeout);
      clearTimeout(contentTimeout);
    };
  }, [subject.id, concept.concept_id]);

  const activeOptions = question?.options || [];

  const handleSelectOption = (index: number) => {
    if (feedback?.submitted) return;
    setSelectedOptionIdx(index);
  };

  const handleSubmitResponse = async (isDontKnow: boolean = false) => {
    if (!question || (selectedOptionIdx === null && !isDontKnow)) return;
    setIsSubmitting(true);
    const selectedOption = selectedOptionIdx !== null ? question.options[selectedOptionIdx] : undefined;

    try {
      const res = await ApiClient.submitActivityResponse({
        learner_id: learnerId,
        subject_id: subject.id,
        concept_ids: [concept.concept_id],
        question_id: question.question_id,
        selected_option: selectedOption,
        selected_index: selectedOptionIdx ?? undefined,
        is_dont_know: isDontKnow,
        request_id: `req_${concept.concept_id}`,
      });

      const newM = res.updated_masteries[concept.concept_id] ?? concept.mastery;
      const isCorrect = res.is_correct ?? false;

      setFeedback({
        submitted: true,
        correct: isCorrect,
        explanation: res.explanation || (isCorrect
          ? `Accurate understanding demonstrated for ${concept.name}.`
          : isDontKnow
          ? `Signaling 'I don't know' allows LearnSense to calibrate your knowledge state without penalty.`
          : `Review the foundational rules of ${concept.name} before attempting the next milestone.`),
        correct_answer: res.correct_answer,
        oldMastery: concept.mastery,
        newMastery: newM,
      });

      // Trigger "Knowledge Changed" state propagation
      onKnowledgeChanged(res.updated_masteries, concept.concept_id);
    } catch (err) {
      console.error('Failed to submit activity response', err);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-space-950/95 backdrop-blur-3xl overflow-y-auto flex flex-col justify-between p-4 sm:p-8 animate-fade-in">
      
      {/* Top Session Bar */}
      <div className="max-w-4xl mx-auto w-full flex items-center justify-between pb-4 border-b border-white/[0.08] gap-4">
        <div className="flex items-center gap-3">
          <button
            onClick={onCloseSession}
            className="p-2 rounded-xl bg-space-850 hover:bg-space-750 text-universe-slate hover:text-white border border-white/[0.07] transition-all"
            title="Return to Workspace"
          >
            <ArrowLeft className="w-4 h-4" />
          </button>
          <div>
            <div className="flex items-center gap-1.5">
              <span className="text-[10px] font-mono tracking-widest text-cyan-400 uppercase font-bold">
                STUDY FOCUS // {subject.title}
              </span>
            </div>
            <h2 className="text-xl sm:text-2xl font-display font-bold text-white tracking-tight">
              {concept.name}
            </h2>
          </div>
        </div>

        <div className="flex items-center gap-2.5">
          <button
            onClick={() => onAskTutor(concept.concept_id)}
            className="py-2 px-3.5 rounded-xl bg-space-850 hover:bg-space-750 text-universe-text border border-white/[0.08] text-xs font-mono flex items-center gap-1.5 transition-all shadow-sm"
          >
            <MessageSquare className="w-3.5 h-3.5 text-cyan-400" />
            <span className="hidden sm:inline">Ask AI Tutor</span>
          </button>

          <button
            onClick={onCloseSession}
            className="py-2 px-4 rounded-xl bg-cyan-400 hover:bg-cyan-300 text-space-950 text-xs font-display font-bold transition-all shadow-[0_0_16px_rgba(0,240,255,0.25)]"
          >
            Close Session
          </button>
        </div>
      </div>

      {/* Main Focus Reading Container */}
      <div className="max-w-4xl mx-auto w-full my-auto py-8 space-y-6">
        
        {/* Mode Switcher Tabs */}
        <div className="flex items-center gap-1 p-1 rounded-xl bg-space-900 border border-white/[0.07] w-fit">
          <button
            onClick={() => setActiveTab('EXPLANATION')}
            className={`py-2 px-4 rounded-lg text-xs font-medium flex items-center gap-2 transition-all ${
              activeTab === 'EXPLANATION'
                ? 'bg-space-750 text-white shadow-sm border border-white/[0.08]'
                : 'text-universe-slate hover:text-white'
            }`}
          >
            <BookOpen className="w-3.5 h-3.5 text-cyan-400" />
            <span>Study Guide & Theory</span>
          </button>

          <button
            onClick={() => setActiveTab('PRACTICE')}
            className={`py-2 px-4 rounded-lg text-xs font-medium flex items-center gap-2 transition-all ${
              activeTab === 'PRACTICE'
                ? 'bg-space-750 text-white shadow-sm border border-white/[0.08]'
                : 'text-universe-slate hover:text-white'
            }`}
          >
            <GraduationCap className="w-3.5 h-3.5 text-emerald-400" />
            <span>Adaptive Quiz</span>
          </button>
        </div>

        {/* Tab 1: Comprehensive Study Guide */}
        {activeTab === 'EXPLANATION' && (
          <div className="universe-panel rounded-3xl p-6 sm:p-10 space-y-8">
            {loadingContent ? (
              <div className="py-20 text-center space-y-4">
                <RefreshCw className="w-8 h-8 text-cyan-400 animate-spin mx-auto" />
                <h4 className="text-sm font-display font-bold text-white">Synthesizing Pedagogical Learning Guide...</h4>
                <p className="text-xs text-universe-slate max-w-sm mx-auto font-mono">
                  Extracting foundational principles, mental models, and worked problems for {concept.name}.
                </p>
              </div>
            ) : (
              <>
                {/* Core Theory & Foundation */}
                <div className="space-y-3">
                  <div className="flex items-center gap-2">
                    <Sparkles className="w-4 h-4 text-cyan-400" />
                    <h3 className="text-lg font-display font-bold text-white">
                      Conceptual Foundation
                    </h3>
                  </div>
                  <div className="text-sm text-universe-text leading-relaxed font-sans whitespace-pre-line p-5 rounded-2xl bg-space-950/60 border border-white/[0.05]">
                    {learningContent?.definition || concept.definition || 'No definition available.'}
                  </div>
                </div>

                {/* Source Evidence */}
                {learningContent?.source_evidence && learningContent.source_evidence.length > 0 && (
                  <div className="space-y-3">
                    <h4 className="text-xs font-mono font-bold text-cyan-300 uppercase flex items-center gap-2">
                      <BookOpen className="w-4 h-4 text-cyan-400" />
                      Source Evidence
                    </h4>
                    <div className="space-y-2.5">
                      {learningContent.source_evidence.map((evidence, idx) => (
                        <div
                          key={idx}
                          className="p-4 rounded-xl bg-space-950/70 border border-white/[0.05] space-y-2"
                        >
                          <div className="text-xs text-universe-text leading-relaxed font-sans whitespace-pre-line">
                            {evidence.text}
                          </div>
                          {evidence.provenance && (
                            <div className="text-[10px] font-mono text-universe-slate/60 flex items-center gap-2">
                              <span>Page {evidence.provenance.page ?? 'unknown'}</span>
                              {evidence.provenance.section && (
                                <span>· {evidence.provenance.section}</span>
                              )}
                              {evidence.provenance.block_id && (
                                <span>· {evidence.provenance.block_id}</span>
                              )}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Call-to-Action to Quiz */}
                <div className="pt-4 flex flex-wrap items-center justify-between gap-4 border-t border-white/[0.07]">
                  <div className="text-xs text-universe-slate">
                    <span className="font-mono text-universe-slate/70 mr-1">Prerequisites:</span>
                    {concept.prerequisites.length > 0
                      ? concept.prerequisites.map((p) => p.replace(/_/g, ' ')).join(', ')
                      : 'Root concept (None)'}
                  </div>

                  <button
                    onClick={() => setActiveTab('PRACTICE')}
                    className="py-3 px-6 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-space-950 font-display font-bold text-xs flex items-center gap-2 shadow-[0_0_20px_rgba(16,185,129,0.25)] transition-all"
                  >
                    <span>Practice with Adaptive Quiz</span>
                    <ArrowRight className="w-4 h-4" />
                  </button>
                </div>
              </>
            )}
          </div>
        )}

        {/* Tab 2: Adaptive Practice Quiz */}
        {activeTab === 'PRACTICE' && (
          <div className="universe-panel rounded-3xl p-6 sm:p-10 space-y-6">
            <div className="pb-4 border-b border-white/[0.07]">
              <span className="text-[10px] font-mono tracking-widest text-emerald-400 font-bold uppercase">
                {loadingQuestion ? 'ANALYZING KNOWLEDGE TOPOLOGY...' : 'ADAPTIVE MASTERY ASSESSMENT'}
              </span>
              <h3 className="text-base sm:text-lg font-display font-bold text-white mt-1 leading-snug">
                {loadingQuestion
                  ? `Loading grounded questions for ${concept.name}...`
                  : (question?.question_text || `Assessment question for ${concept.name}`)}
              </h3>
              {question?.source_citations && question.source_citations.length > 0 && (
                <div className="flex items-center gap-2 mt-2 text-[10px] text-cyan-400 font-mono">
                  <BookOpen className="w-3.5 h-3.5" />
                  <span>Grounding citation: Page {question.source_citations.map(c => c.page).join(', ')}</span>
                </div>
              )}
            </div>

            {/* Quiz Options */}
            {loadingQuestion ? (
              <div className="py-12 text-center space-y-3">
                <RefreshCw className="w-8 h-8 text-cyan-400 animate-spin mx-auto" />
                <p className="text-xs text-universe-slate font-mono">Retrieving grounded questions from question bank...</p>
              </div>
            ) : activeOptions.length === 0 ? (
              <div className="py-10 text-center space-y-3">
                <p className="text-xs text-universe-slate font-mono">
                  {question?.no_questions
                    ? `No grounded questions available for ${concept.name} yet. Try another concept or upload more material.`
                    : `No questions available for ${concept.name}.`}
                </p>
                <p className="text-[10px] text-universe-slate/60 font-mono">
                  The question bank is built from your uploaded material. Concepts with sufficient evidence will have practice questions.
                </p>
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
                      className={`w-full p-4 rounded-xl border text-left text-xs font-sans transition-all duration-200 flex items-center justify-between gap-4 ${
                        isSelected
                          ? 'border-cyan-400 bg-space-800 text-white shadow-[0_0_20px_rgba(0,240,255,0.15)]'
                          : 'border-white/[0.06] bg-space-950/70 text-universe-text hover:bg-space-850 hover:border-white/[0.12]'
                      }`}
                    >
                      <span className="leading-relaxed">{opt}</span>
                      {isSelected && <CheckCircle2 className="w-4 h-4 text-cyan-400 shrink-0" />}
                    </button>
                  );
                })}
              </div>
            )}

            {/* Submissions Control Bar */}
            {!feedback?.submitted && (
              <div className="flex items-center justify-between pt-3 border-t border-white/[0.07]">
                <button
                  onClick={() => handleSubmitResponse(true)}
                  disabled={isSubmitting}
                  className="py-2.5 px-4 rounded-xl border border-amber-500/30 bg-amber-950/30 hover:bg-amber-900/40 text-amber-200 text-xs font-mono font-medium flex items-center gap-2 transition-all"
                >
                  <ShieldAlert className="w-4 h-4 text-amber-400" />
                  <span>I don't know this concept</span>
                </button>

                <button
                  onClick={() => handleSubmitResponse(false)}
                  disabled={selectedOptionIdx === null || isSubmitting}
                  className={`py-3 px-6 rounded-xl font-display font-bold text-xs flex items-center gap-2 transition-all ${
                    selectedOptionIdx !== null
                      ? 'bg-emerald-500 hover:bg-emerald-400 text-space-950 shadow-[0_0_20px_rgba(16,185,129,0.25)] cursor-pointer'
                      : 'bg-space-850 text-universe-slate/50 border border-white/[0.05] cursor-not-allowed'
                  }`}
                >
                  <span>Submit Answer</span>
                  <ArrowRight className="w-4 h-4" />
                </button>
              </div>
            )}

            {/* Post-Submission "Knowledge Changed" Feedback Banner */}
            {feedback?.submitted && (
              <div className="p-6 rounded-2xl border border-emerald-500/40 bg-emerald-950/30 shadow-[0_0_32px_rgba(16,185,129,0.15)] space-y-4 animate-fade-in">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2.5">
                    {feedback.correct ? (
                      <CheckCircle2 className="w-5 h-5 text-emerald-400" />
                    ) : (
                      <XCircle className="w-5 h-5 text-rose-400" />
                    )}
                    <span className="text-xs font-mono font-bold text-emerald-300 uppercase tracking-widest">
                      KNOWLEDGE STATE CALIBRATED
                    </span>
                  </div>

                  <div className="flex items-center gap-2 font-mono text-xs">
                    <span className="text-universe-slate">{Math.round(feedback.oldMastery * 100)}%</span>
                    <ArrowRight className="w-3.5 h-3.5 text-cyan-400" />
                    <span className="text-emerald-300 font-bold text-sm">{Math.round(feedback.newMastery * 100)}% Mastery</span>
                  </div>
                </div>

                <p className="text-xs text-universe-text leading-relaxed font-sans">{feedback.explanation}</p>

                <div className="pt-2 flex justify-end">
                  <button
                    onClick={onCloseSession}
                    className="py-3 px-6 rounded-xl bg-cyan-400 hover:bg-cyan-300 text-space-950 font-display font-extrabold text-xs flex items-center gap-2 shadow-[0_0_20px_rgba(0,240,255,0.3)] transition-all"
                  >
                    <Zap className="w-4 h-4 fill-current" />
                    <span>Return to Knowledge Atlas</span>
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
