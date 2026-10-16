import React, { useState, useEffect } from 'react';
import type { ConceptNode, TutorResponse } from '../../api/client';
import { ApiClient } from '../../api/client';
import { X, Sparkles, Lightbulb, HelpCircle, Send, FileText, Video, ExternalLink, Clock } from 'lucide-react';

export interface ContextualTutorProps {
  concept: ConceptNode | null;
  learnerId: string;
  subjectId: string;
  onClose: () => void;
}

export const ContextualTutor: React.FC<ContextualTutorProps> = ({
  concept,
  learnerId,
  subjectId,
  onClose,
}) => {
  const [messages, setMessages] = useState<
    { role: 'user' | 'tutor'; text: string; citations?: { page: number; section: string; quote: string }[]; intent?: string }[]
  >([
    {
      role: 'tutor',
      text: concept
        ? `I am your AI Pedagogical Tutor, anchored directly into "${concept.name}". Ask any question, or request a grounded explanation, intuition, hint, or notation-matched video lesson.`
        : 'I am your AI Pedagogical Tutor. Select any concept on your Knowledge Atlas to begin grounded tutoring.',
    },
  ]);

  const [inputMsg, setInputMsg] = useState<string>('');
  const [loading, setLoading] = useState<boolean>(false);
  const [resources, setResources] = useState<any[]>([]);
  const [showResources, setShowResources] = useState<boolean>(false);

  useEffect(() => {
    if (!concept) return;
    ApiClient.getConceptResources(subjectId, concept.concept_id, learnerId, 3)
      .then((res) => setResources(res || []))
      .catch((err) => console.debug('Could not load resources for concept', err));
  }, [concept, subjectId, learnerId]);

  const handleSendPrompt = async (intent: string, customText?: string) => {
    if (!concept) return;
    const userText = customText || (
      intent === 'EXPLAIN' ? `Explain the core intuition of ${concept.name}.` :
      intent === 'HINT' ? `Give me a helpful hint about applying ${concept.name}.` :
      intent === 'ANALOGY' ? `Provide an intuitive real-world analogy for ${concept.name}.` : intent
    );

    setMessages((prev) => [...prev, { role: 'user', text: userText, intent }]);
    setInputMsg('');
    setLoading(true);

    try {
      const res: TutorResponse = await ApiClient.interactWithTutor({
        learner_id: learnerId,
        subject_id: subjectId,
        concept_id: concept.concept_id,
        intent,
        user_message: customText,
      });

      const tutorText = res.status === 'NO_GROUNDED_TUTOR_EVIDENCE'
        ? (res.reason || `No direct evidence was found in the study material for "${concept.name}". LearnSense refuses to fabricate answers without source grounding.`)
        : res.response_text;

      setMessages((prev) => [
        ...prev,
        {
          role: 'tutor',
          text: tutorText,
          citations: res.source_citations,
        },
      ]);
    } catch (err) {
      console.error('Failed to get tutor response', err);
      setMessages((prev) => [
        ...prev,
        {
          role: 'tutor',
          text: 'Unable to formulate response at this moment. Verify that the knowledge representation is loaded.',
        },
      ]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-y-0 right-0 z-50 w-full max-w-md bg-space-900/95 border-l border-white/[0.08] backdrop-blur-2xl shadow-[0_0_64px_rgba(0,0,0,0.8)] p-6 flex flex-col justify-between animate-fade-in">
      
      {/* 1. Header & Context Badge */}
      <div className="space-y-4">
        <div className="flex items-center justify-between pb-3.5 border-b border-white/[0.07]">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-cyan-950/80 border border-cyan-500/40 flex items-center justify-center text-cyan-400 shadow-[0_0_12px_rgba(0,240,255,0.2)]">
              <Sparkles className="w-4 h-4" />
            </div>
            <div>
              <div className="flex items-center gap-1.5">
                <span className="text-[9px] font-mono tracking-widest text-cyan-400 uppercase font-bold">
                  GROUNDED AI COPILOT
                </span>
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
              </div>
              <h3 className="text-sm font-display font-bold text-white leading-snug">
                {concept ? concept.name : 'General Assistant'}
              </h3>
            </div>
          </div>

          <button
            onClick={onClose}
            className="p-1.5 rounded-lg bg-space-800 hover:bg-space-750 text-universe-slate hover:text-white transition-colors"
            aria-label="Close AI tutor"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Quick Context Action Pills */}
        {concept && (
          <div className="flex flex-wrap gap-1.5">
            <button
              onClick={() => handleSendPrompt('EXPLAIN')}
              className="px-2.5 py-1 rounded-lg bg-space-850 hover:bg-space-750 border border-white/[0.07] text-[11px] text-universe-text font-mono flex items-center gap-1.5 transition-all"
            >
              <Sparkles className="w-3 h-3 text-cyan-400" />
              <span>Explain Concept</span>
            </button>
            <button
              onClick={() => handleSendPrompt('HINT')}
              className="px-2.5 py-1 rounded-lg bg-space-850 hover:bg-space-750 border border-white/[0.07] text-[11px] text-universe-text font-mono flex items-center gap-1.5 transition-all"
            >
              <Lightbulb className="w-3 h-3 text-amber-400" />
              <span>Hint</span>
            </button>
            <button
              onClick={() => handleSendPrompt('ANALOGY')}
              className="px-2.5 py-1 rounded-lg bg-space-850 hover:bg-space-750 border border-white/[0.07] text-[11px] text-universe-text font-mono flex items-center gap-1.5 transition-all"
            >
              <HelpCircle className="w-3 h-3 text-emerald-400" />
              <span>Analogy</span>
            </button>
            {resources.length > 0 && (
              <button
                onClick={() => setShowResources(!showResources)}
                className={`px-2.5 py-1 rounded-lg border text-[11px] font-mono flex items-center gap-1.5 transition-all ${
                  showResources
                    ? 'bg-purple-950/80 border-purple-500/50 text-purple-300 shadow-[0_0_12px_rgba(168,85,247,0.2)]'
                    : 'bg-space-850 hover:bg-space-750 border-white/[0.07] text-universe-text'
                }`}
              >
                <Video className="w-3 h-3 text-purple-400" />
                <span>Notation Videos ({resources.length})</span>
              </button>
            )}
          </div>
        )}

        {/* Notation-Matched Videos Panel (§9) */}
        {showResources && resources.length > 0 && (
          <div className="p-3 rounded-xl bg-space-950/90 border border-purple-500/30 space-y-2.5 animate-fade-in">
            <div className="flex items-center justify-between">
              <span className="text-[10px] font-mono tracking-wider uppercase text-purple-400 font-bold flex items-center gap-1">
                <Video className="w-3.5 h-3.5" /> Notation-Matched Video Lessons
              </span>
              <span className="text-[10px] text-universe-slate font-mono">Timestamp Jumps</span>
            </div>
            {resources.map((r) => {
              const startSec = Math.floor(r.recommended_timestamp_seconds || 0);
              const jumpUrl = `${r.url}${r.url.includes('?') ? '&' : '?'}t=${startSec}`;
              return (
                <div
                  key={r.resource_id}
                  className="p-2.5 rounded-lg bg-space-900 border border-white/[0.06] space-y-1.5 hover:border-purple-500/30 transition-all"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <h4 className="text-xs font-bold text-white leading-tight">{r.title}</h4>
                      <p className="text-[10px] text-universe-slate font-mono">
                        {r.channel} • {Math.round((r.overall_score || 0) * 100)}% Match
                      </p>
                    </div>
                    <a
                      href={jumpUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="px-2 py-1 rounded bg-purple-500/20 hover:bg-purple-500/30 border border-purple-500/40 text-purple-300 text-[10px] font-mono flex items-center gap-1 shrink-0 transition-colors"
                    >
                      <Clock className="w-3 h-3" />
                      <span>
                        {Math.floor(startSec / 60)}:{(startSec % 60).toString().padStart(2, '0')}
                      </span>
                      <ExternalLink className="w-2.5 h-2.5" />
                    </a>
                  </div>
                  {r.notation_explanation && (
                    <p className="text-[10px] text-amber-300/90 font-sans italic">
                      💡 {r.notation_explanation}
                    </p>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* 2. Message Thread Feed */}
      <div className="my-4 flex-1 overflow-y-auto space-y-4 pr-1">
        {messages.map((m, idx) => (
          <div
            key={idx}
            className={`p-4 rounded-2xl text-xs leading-relaxed space-y-2.5 max-w-[90%] transition-all ${
              m.role === 'user'
                ? 'ml-auto bg-cyan-400 text-space-950 font-medium rounded-br-sm shadow-[0_4px_16px_rgba(0,240,255,0.2)]'
                : 'mr-auto bg-space-950/80 border border-white/[0.07] text-universe-text rounded-bl-sm shadow-sm'
            }`}
          >
            <p className="font-sans whitespace-pre-line">{m.text}</p>

            {/* Citations Footer */}
            {m.citations && m.citations.length > 0 && (
              <div className="pt-2 border-t border-white/[0.08] text-[10px] text-universe-slate font-mono space-y-1.5">
                <span className="text-amber-400 font-bold flex items-center gap-1 uppercase tracking-wider">
                  <FileText className="w-3 h-3" /> Grounded Evidence:
                </span>
                {m.citations.map((c, cIdx) => (
                  <div key={cIdx} className="pl-2 border-l border-amber-500/40 space-y-0.5">
                    <span className="text-amber-300/90 font-bold">Pg {c.page} {c.section ? `(§${c.section})` : ''}</span>
                    <p className="text-universe-slate/90 italic font-sans">"{c.quote}"</p>
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}

        {loading && (
          <div className="p-3.5 rounded-2xl bg-space-950/80 border border-white/[0.07] text-xs text-universe-slate font-mono flex items-center gap-2 animate-pulse">
            <Sparkles className="w-4 h-4 text-cyan-400 animate-spin" />
            <span>Formulating grounded pedagogical response...</span>
          </div>
        )}
      </div>

      {/* 3. Input Console */}
      <div className="pt-3 border-t border-white/[0.08]">
        <div className="flex items-center gap-2">
          <input
            type="text"
            placeholder="Ask anything about this concept..."
            value={inputMsg}
            onChange={(e) => setInputMsg(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && inputMsg && handleSendPrompt('CUSTOM', inputMsg)}
            className="flex-1 px-4 py-3 rounded-xl bg-space-950/90 border border-white/[0.08] text-xs text-white placeholder-universe-slate focus:outline-none focus:border-cyan-400 font-sans transition-all"
          />
          <button
            onClick={() => inputMsg && handleSendPrompt('CUSTOM', inputMsg)}
            disabled={!inputMsg}
            className="p-3 rounded-xl bg-cyan-400 hover:bg-cyan-300 disabled:opacity-40 disabled:hover:bg-cyan-400 text-space-950 font-bold transition-all shadow-[0_0_16px_rgba(0,240,255,0.25)] shrink-0"
            aria-label="Send message"
          >
            <Send className="w-4 h-4" />
          </button>
        </div>
      </div>

    </div>
  );
};
