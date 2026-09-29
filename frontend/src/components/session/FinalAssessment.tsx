import React, { useState, useEffect, useCallback } from 'react';
import type { Subject } from '../../api/client';
import { ApiClient } from '../../api/client';
import {
  Trophy,
  ShieldCheck,
  ShieldAlert,
  ArrowRight,
  ArrowLeft,
  CheckCircle2,
  XCircle,
  Send,
  RefreshCw,
  X,
  Award,
  Target,
  Zap,
  HelpCircle,
} from 'lucide-react';

export interface FinalAssessmentProps {
  subject: Subject;
  learnerId: string;
  /** If provided, resume an existing active assessment instead of starting a new one */
  activeAssessmentId?: string | null;
  onComplete: (updatedMasteries: Record<string, number>) => void;
  onClose: () => void;
}

interface AssessmentQuestion {
  item_id?: string;
  question_id?: string;
  concept_ids?: string[];
  prompt?: string;
  question_text?: string;
  options?: string[];
  allow_dont_know_option?: boolean;
}

interface AssessmentResult {
  assessment_id: string;
  completed: boolean;
  total_questions: number;
  correct_count: number;
  score_pct: number;
  passed: boolean;
  concept_results: Record<
    string,
    {
      question_id: string;
      correct: boolean;
      score: number;
      correct_answer: string;
      explanation: string;
    }
  >;
  updated_masteries: Record<string, number>;
  message: string;
}

export const FinalAssessment: React.FC<FinalAssessmentProps> = ({
  subject,
  learnerId,
  activeAssessmentId,
  onComplete,
  onClose,
}) => {
  const [phase, setPhase] = useState<'LOADING' | 'IN_PROGRESS' | 'SUBMITTING' | 'RESULTS'>('LOADING');
  const [assessmentId, setAssessmentId] = useState<string>('');
  const [questions, setQuestions] = useState<AssessmentQuestion[]>([]);
  const [currentIdx, setCurrentIdx] = useState<number>(0);
  const [responses, setResponses] = useState<Record<string, string>>({});
  const [selectedOption, setSelectedOption] = useState<string | null>(null);
  const [result, setResult] = useState<AssessmentResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const startOrResume = useCallback(async () => {
    try {
      setPhase('LOADING');
      setError(null);
      const data = await ApiClient.startFinalAssessment(learnerId, subject.id);
      setAssessmentId(data.assessment_id);
      setQuestions(data.questions);
      setCurrentIdx(0);
      setResponses({});
      setSelectedOption(null);
      setPhase('IN_PROGRESS');
    } catch (err: any) {
      setError(err.message || 'Failed to start final assessment.');
      setPhase('IN_PROGRESS');
    }
  }, [learnerId, subject.id]);

  useEffect(() => {
    startOrResume();
  }, [startOrResume]);

  const currentQuestion = questions[currentIdx] || null;
  const qId = currentQuestion?.question_id || currentQuestion?.item_id || '';
  const qText = currentQuestion?.question_text || currentQuestion?.prompt || '';
  const qOptions = currentQuestion?.options || [];
  const totalQuestions = questions.length;
  const answeredCount = Object.keys(responses).length;

  const handleSelectOption = (opt: string) => {
    setSelectedOption(opt);
  };

  const handleConfirmAnswer = () => {
    if (!selectedOption || !qId) return;
    const newResponses = { ...responses, [qId]: selectedOption };
    setResponses(newResponses);
    setSelectedOption(null);

    if (currentIdx + 1 < totalQuestions) {
      setCurrentIdx(currentIdx + 1);
    }
  };

  const handleDontKnow = () => {
    if (!qId) return;
    const newResponses = { ...responses, [qId]: "I don't know" };
    setResponses(newResponses);
    setSelectedOption(null);

    if (currentIdx + 1 < totalQuestions) {
      setCurrentIdx(currentIdx + 1);
    }
  };

  const handleSubmitAssessment = async () => {
    setPhase('SUBMITTING');
    setError(null);
    try {
      const requestId = `final_${assessmentId}_${Date.now()}`;
      const res = await ApiClient.submitFinalAssessment({
        assessment_id: assessmentId,
        learner_id: learnerId,
        subject_id: subject.id,
        responses,
        request_id: requestId,
      });
      setResult(res);
      setPhase('RESULTS');
      onComplete(res.updated_masteries);
    } catch (err: any) {
      setError(err.message || 'Failed to submit final assessment.');
      setPhase('IN_PROGRESS');
    }
  };

  const allAnswered = answeredCount >= totalQuestions && totalQuestions > 0;

  return (
    <div className="fixed inset-0 z-[70] bg-space-950/90 backdrop-blur-xl flex items-center justify-center p-4 animate-fade-in">
      <div className="w-full max-w-3xl universe-panel rounded-3xl relative overflow-hidden shadow-[0_32px_80px_rgba(0,0,0,0.8)] border border-white/[0.08]">
        
        {/* Ambient glows */}
        <div className="absolute -top-24 -right-24 w-80 h-80 bg-violet-500/10 rounded-full blur-3xl pointer-events-none" />
        <div className="absolute -bottom-24 -left-24 w-80 h-80 bg-cyan-500/10 rounded-full blur-3xl pointer-events-none" />

        {/* Header */}
        <div className="relative z-10 p-6 pb-4 border-b border-white/[0.08] flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="p-2.5 rounded-xl bg-gradient-to-br from-violet-500/20 to-cyan-500/20 border border-violet-400/30">
              <Trophy className="w-5 h-5 text-violet-300" />
            </div>
            <div>
              <span className="text-[10px] font-mono tracking-widest text-violet-300 font-bold uppercase block">
                FINAL ASSESSMENT // {subject.title}
              </span>
              <h2 className="text-lg font-display font-bold text-white tracking-tight">
                Comprehensive Mastery Evaluation
              </h2>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 rounded-lg bg-space-850 hover:bg-space-750 border border-white/[0.06] text-universe-slate hover:text-white transition-all"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Content Area */}
        <div className="relative z-10 p-6 min-h-[400px] max-h-[70vh] overflow-y-auto">
          
          {/* LOADING */}
          {phase === 'LOADING' && (
            <div className="flex flex-col items-center justify-center py-20 space-y-4 animate-pulse">
              <RefreshCw className="w-8 h-8 text-violet-400 animate-spin" />
              <p className="text-sm font-mono text-universe-slate">Generating assessment from grounded question bank...</p>
            </div>
          )}

          {/* ERROR */}
          {error && (
            <div className="mb-4 p-4 rounded-xl bg-rose-950/50 border border-rose-500/40 text-xs text-rose-300 font-mono">
              {error}
            </div>
          )}

          {/* IN PROGRESS */}
          {phase === 'IN_PROGRESS' && currentQuestion && (
            <div className="space-y-6 animate-fade-in">
              {/* Progress Bar */}
              <div className="space-y-2">
                <div className="flex items-center justify-between text-[10px] font-mono text-universe-slate">
                  <span>QUESTION {currentIdx + 1} OF {totalQuestions}</span>
                  <span>{answeredCount} / {totalQuestions} ANSWERED</span>
                </div>
                <div className="w-full bg-space-800 h-1.5 rounded-full overflow-hidden">
                  <div
                    className="bg-gradient-to-r from-violet-400 to-cyan-400 h-full rounded-full transition-all duration-500"
                    style={{ width: `${totalQuestions > 0 ? (answeredCount / totalQuestions) * 100 : 0}%` }}
                  />
                </div>
              </div>

              {/* Question */}
              <div className="p-5 rounded-2xl bg-space-950/70 border border-white/[0.06]">
                <p className="text-sm font-sans text-universe-text leading-relaxed">{qText}</p>
              </div>

              {/* Options */}
              <div className="space-y-2.5">
                {qOptions.map((opt, idx) => {
                  const isSelected = selectedOption === opt;
                  const isAlreadyAnswered = responses[qId] === opt;
                  return (
                    <button
                      key={idx}
                      onClick={() => handleSelectOption(opt)}
                      className={`w-full p-4 rounded-xl border text-left text-sm font-sans transition-all flex items-center gap-3 ${
                        isSelected
                          ? 'bg-violet-950/60 border-violet-400/60 text-white shadow-[0_0_20px_rgba(139,92,246,0.15)]'
                          : isAlreadyAnswered
                          ? 'bg-cyan-950/30 border-cyan-400/30 text-cyan-200'
                          : 'bg-space-950/50 border-white/[0.06] text-universe-text hover:bg-space-850 hover:border-violet-400/30'
                      }`}
                    >
                      <span className={`w-7 h-7 rounded-lg border flex items-center justify-center text-xs font-mono font-bold shrink-0 ${
                        isSelected
                          ? 'bg-violet-500 border-violet-400 text-white'
                          : isAlreadyAnswered
                          ? 'bg-cyan-500/30 border-cyan-400/40 text-cyan-300'
                          : 'bg-space-900 border-white/[0.1] text-universe-slate'
                      }`}>
                        {String.fromCharCode(65 + idx)}
                      </span>
                      <span className="flex-1">{opt}</span>
                      {isAlreadyAnswered && <CheckCircle2 className="w-4 h-4 text-cyan-400 shrink-0" />}
                    </button>
                  );
                })}

                {/* Don't Know */}
                <button
                  onClick={handleDontKnow}
                  className={`w-full p-3.5 rounded-xl border border-amber-500/30 bg-amber-950/20 hover:bg-amber-900/30 text-left text-xs font-mono text-amber-200 transition-all flex items-center gap-2 ${
                    responses[qId] === "I don't know" ? 'ring-1 ring-amber-400/50' : ''
                  }`}
                >
                  <HelpCircle className="w-4 h-4 text-amber-400" />
                  <span>I don't know this concept yet</span>
                </button>
              </div>

              {/* Navigation */}
              <div className="pt-4 border-t border-white/[0.06] flex items-center justify-between gap-4">
                <button
                  onClick={() => {
                    if (currentIdx > 0) {
                      setCurrentIdx(currentIdx - 1);
                      setSelectedOption(null);
                    }
                  }}
                  disabled={currentIdx === 0}
                  className="px-4 py-2.5 rounded-xl bg-space-850 hover:bg-space-750 text-universe-text border border-white/[0.06] text-xs font-mono flex items-center gap-1.5 transition-all disabled:opacity-30"
                >
                  <ArrowLeft className="w-3.5 h-3.5" />
                  <span>Previous</span>
                </button>

                <div className="flex items-center gap-2">
                  {selectedOption && (
                    <button
                      onClick={handleConfirmAnswer}
                      className="px-5 py-2.5 rounded-xl bg-violet-500 hover:bg-violet-400 text-white font-display font-bold text-xs flex items-center gap-2 shadow-[0_0_16px_rgba(139,92,246,0.3)] transition-all"
                    >
                      <CheckCircle2 className="w-3.5 h-3.5" />
                      <span>Confirm Answer</span>
                    </button>
                  )}

                  {!selectedOption && currentIdx + 1 < totalQuestions && responses[qId] && (
                    <button
                      onClick={() => {
                        setCurrentIdx(currentIdx + 1);
                        setSelectedOption(null);
                      }}
                      className="px-4 py-2.5 rounded-xl bg-space-850 hover:bg-space-750 text-universe-text border border-white/[0.06] text-xs font-mono flex items-center gap-1.5 transition-all"
                    >
                      <span>Next</span>
                      <ArrowRight className="w-3.5 h-3.5" />
                    </button>
                  )}

                  {allAnswered && (
                    <button
                      onClick={handleSubmitAssessment}
                      className="px-6 py-3 rounded-xl bg-gradient-to-r from-violet-500 to-cyan-500 hover:from-violet-400 hover:to-cyan-400 text-white font-display font-extrabold text-xs flex items-center gap-2 shadow-[0_0_24px_rgba(139,92,246,0.3)] transition-all hover:scale-[1.02]"
                    >
                      <Send className="w-4 h-4" />
                      <span>Submit Final Assessment</span>
                    </button>
                  )}
                </div>
              </div>

              {/* Question Navigator Dots */}
              <div className="flex flex-wrap gap-1.5 justify-center pt-2">
                {questions.map((q, idx) => {
                  const id = q.question_id || q.item_id || '';
                  const isAnswered = !!responses[id];
                  const isCurrent = idx === currentIdx;
                  return (
                    <button
                      key={idx}
                      onClick={() => { setCurrentIdx(idx); setSelectedOption(null); }}
                      className={`w-6 h-6 rounded-md text-[9px] font-mono font-bold flex items-center justify-center transition-all ${
                        isCurrent
                          ? 'bg-violet-500 text-white ring-2 ring-violet-300/50'
                          : isAnswered
                          ? 'bg-cyan-500/30 text-cyan-300 border border-cyan-400/30'
                          : 'bg-space-900 text-universe-slate border border-white/[0.06]'
                      }`}
                    >
                      {idx + 1}
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {/* SUBMITTING */}
          {phase === 'SUBMITTING' && (
            <div className="flex flex-col items-center justify-center py-20 space-y-4">
              <div className="relative">
                <RefreshCw className="w-10 h-10 text-violet-400 animate-spin" />
                <Zap className="w-5 h-5 text-cyan-400 absolute -top-1 -right-1 animate-bounce" />
              </div>
              <p className="text-sm font-mono text-universe-slate">Evaluating responses and calibrating BKT mastery state...</p>
            </div>
          )}

          {/* RESULTS */}
          {phase === 'RESULTS' && result && (
            <div className="space-y-8 animate-fade-in">
              {/* Score Hero */}
              <div className={`text-center p-8 rounded-3xl border-2 ${
                result.passed
                  ? 'bg-gradient-to-br from-emerald-950/60 via-space-900 to-cyan-950/40 border-emerald-500/40'
                  : 'bg-gradient-to-br from-amber-950/50 via-space-900 to-rose-950/30 border-amber-500/30'
              }`}>
                <div className="flex justify-center mb-4">
                  {result.passed ? (
                    <div className="p-4 rounded-2xl bg-emerald-500/20 border border-emerald-400/40 shadow-[0_0_40px_rgba(16,185,129,0.2)]">
                      <Award className="w-10 h-10 text-emerald-400" />
                    </div>
                  ) : (
                    <div className="p-4 rounded-2xl bg-amber-500/20 border border-amber-400/40 shadow-[0_0_40px_rgba(245,158,11,0.2)]">
                      <Target className="w-10 h-10 text-amber-400" />
                    </div>
                  )}
                </div>

                <h3 className={`text-5xl font-display font-extrabold ${result.passed ? 'text-emerald-400' : 'text-amber-400'}`}>
                  {result.score_pct}%
                </h3>
                <p className="text-sm font-display font-bold text-white mt-1">
                  {result.passed ? 'Assessment Passed — Domain Mastery Achieved' : 'More Practice Recommended'}
                </p>
                <p className="text-xs text-universe-slate mt-2 font-sans">
                  {result.correct_count} of {result.total_questions} questions answered correctly.
                  {result.passed
                    ? ' Your BKT mastery scores have been calibrated upward.'
                    : ' Review the concepts below and continue learning to improve mastery.'}
                </p>
              </div>

              {/* Concept-Level Results */}
              <div className="space-y-3">
                <h4 className="text-xs font-mono tracking-widest text-universe-slate uppercase">
                  CONCEPT-LEVEL BREAKDOWN
                </h4>
                <div className="space-y-2">
                  {Object.entries(result.concept_results).map(([conceptId, cr]) => (
                    <div
                      key={conceptId}
                      className={`p-4 rounded-xl border flex items-start gap-3 ${
                        cr.correct
                          ? 'bg-emerald-950/30 border-emerald-500/30'
                          : 'bg-rose-950/30 border-rose-500/30'
                      }`}
                    >
                      <div className="shrink-0 mt-0.5">
                        {cr.correct ? (
                          <CheckCircle2 className="w-5 h-5 text-emerald-400" />
                        ) : (
                          <XCircle className="w-5 h-5 text-rose-400" />
                        )}
                      </div>
                      <div className="flex-1 min-w-0">
                        <h5 className="text-xs font-display font-bold text-white uppercase">
                          {conceptId.replace(/_/g, ' ')}
                        </h5>
                        {!cr.correct && cr.correct_answer && (
                          <p className="text-xs text-emerald-300 mt-1 font-mono">
                            <span className="text-universe-slate">Correct: </span>{cr.correct_answer}
                          </p>
                        )}
                        {cr.explanation && (
                          <p className="text-xs text-universe-slate mt-1 leading-relaxed font-sans">
                            {cr.explanation}
                          </p>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Updated BKT Masteries */}
              {Object.keys(result.updated_masteries).length > 0 && (
                <div className="space-y-3">
                  <h4 className="text-xs font-mono tracking-widest text-universe-slate uppercase flex items-center gap-2">
                    <Zap className="w-3.5 h-3.5 text-cyan-400" />
                    UPDATED BKT MASTERY SCORES
                  </h4>
                  <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                    {Object.entries(result.updated_masteries).map(([cid, val]) => (
                      <div key={cid} className="p-3 rounded-xl bg-space-950/60 border border-white/[0.06]">
                        <p className="text-[10px] font-mono text-universe-slate truncate">{cid.replace(/_/g, ' ')}</p>
                        <p className="text-lg font-display font-bold text-cyan-400 mt-0.5">{Math.round(val * 100)}%</p>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer for Results */}
        {phase === 'RESULTS' && (
          <div className="relative z-10 p-6 pt-4 border-t border-white/[0.08] flex items-center justify-end gap-3">
            <button
              onClick={onClose}
              className="px-6 py-3 rounded-xl bg-gradient-to-r from-cyan-400 to-sky-400 hover:from-cyan-300 hover:to-sky-300 text-space-950 font-display font-extrabold text-xs flex items-center gap-2 shadow-[0_0_20px_rgba(0,240,255,0.25)] transition-all"
            >
              <span>Return to Dashboard</span>
              <ArrowRight className="w-4 h-4" />
            </button>
          </div>
        )}
      </div>
    </div>
  );
};
