import React, { useState } from 'react';
import type { ConceptNode, TutorResponse } from '../../api/client';
import { ApiClient } from '../../api/client';
import { X, Sparkles, Lightbulb, HelpCircle, Send, FileText } from 'lucide-react';

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
    { role: 'user' | 'tutor'; text: string; citations?: { page: number; section: string; quote: string }[] }[]
  >([
    {
      role: 'tutor',
      text: concept
        ? `Hello! I am your Taproot AI Tutor. I am anchored to ${concept.name}. How can I assist your learning?`
        : 'Hello! I am your Taproot AI Tutor. Select a concept on the Atlas to begin targeted tutoring.',
    },
  ]);

  const [inputMsg, setInputMsg] = useState<string>('');
  const [loading, setLoading] = useState<boolean>(false);

  const handleSendPrompt = async (intent: string, customText?: string) => {
    if (!concept) return;
    const userText = customText || intent;
    setMessages((prev) => [...prev, { role: 'user', text: userText }]);
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

      setMessages((prev) => [
        ...prev,
        {
          role: 'tutor',
          text: res.response_text,
          citations: res.source_citations,
        },
      ]);
    } catch (err) {
      console.error('Failed to get tutor response', err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-y-0 right-0 z-50 w-full max-w-md bg-slate-900/95 border-l border-slate-800 backdrop-blur-2xl shadow-2xl p-6 flex flex-col justify-between">
      {/* Header */}
      <div>
        <div className="flex items-center justify-between pb-4 border-b border-slate-800">
          <div className="flex items-center gap-2">
            <Sparkles className="w-5 h-5 text-cyan-400" />
            <div>
              <span className="text-[10px] font-mono tracking-widest text-cyan-400 uppercase font-bold">
                CONTEXT-AWARE AI TUTOR
              </span>
              <h3 className="text-sm font-bold text-white">
                {concept ? concept.name : 'General Assistant'}
              </h3>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-400 hover:text-white"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Quick Context Prompts */}
        {concept && (
          <div className="mt-4 flex flex-wrap gap-1.5">
            <button
              onClick={() => handleSendPrompt('EXPLAIN')}
              className="px-2.5 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 text-[11px] text-slate-200 font-mono flex items-center gap-1"
            >
              <Sparkles className="w-3 h-3 text-cyan-400" /> Explain this
            </button>
            <button
              onClick={() => handleSendPrompt('HINT')}
              className="px-2.5 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 text-[11px] text-slate-200 font-mono flex items-center gap-1"
            >
              <Lightbulb className="w-3 h-3 text-amber-400" /> Give me a hint
            </button>
            <button
              onClick={() => handleSendPrompt('ANALOGY')}
              className="px-2.5 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 text-[11px] text-slate-200 font-mono flex items-center gap-1"
            >
              <HelpCircle className="w-3 h-3 text-emerald-400" /> Give me an analogy
            </button>
          </div>
        )}
      </div>

      {/* Message Chat Feed */}
      <div className="my-4 flex-1 overflow-y-auto space-y-3 pr-2">
        {messages.map((m, idx) => (
          <div
            key={idx}
            className={`p-3.5 rounded-2xl text-xs leading-relaxed max-w-[88%] ${
              m.role === 'user'
                ? 'ml-auto bg-cyan-600 text-slate-950 font-semibold'
                : 'mr-auto bg-slate-950/80 border border-slate-800 text-slate-200'
            }`}
          >
            <p>{m.text}</p>
            {m.citations && m.citations.length > 0 && (
              <div className="mt-2 pt-2 border-t border-slate-800/80 text-[10px] text-slate-400 font-mono space-y-1">
                <span className="text-amber-400 flex items-center gap-1">
                  <FileText className="w-3 h-3" /> Source Citations:
                </span>
                {m.citations.map((c, cIdx) => (
                  <p key={cIdx} className="pl-2 border-l border-amber-500/40">
                    Page {c.page} ({c.section}): "{c.quote}"
                  </p>
                ))}
              </div>
            )}
          </div>
        ))}
        {loading && (
          <div className="p-3 rounded-xl bg-slate-950 border border-slate-800 text-xs text-slate-400 font-mono animate-pulse">
            AI Tutor is formulating contextual response...
          </div>
        )}
      </div>

      {/* Input Box */}
      <div className="pt-3 border-t border-slate-800 flex items-center gap-2">
        <input
          type="text"
          placeholder="Ask a question about this concept..."
          value={inputMsg}
          onChange={(e) => setInputMsg(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && inputMsg && handleSendPrompt('CUSTOM', inputMsg)}
          className="flex-1 px-4 py-2.5 rounded-xl bg-slate-950 border border-slate-800 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-cyan-400"
        />
        <button
          onClick={() => inputMsg && handleSendPrompt('CUSTOM', inputMsg)}
          className="p-2.5 rounded-xl bg-cyan-500 hover:bg-cyan-400 text-slate-950 font-bold transition-all shadow-glow-cyan"
        >
          <Send className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
};
