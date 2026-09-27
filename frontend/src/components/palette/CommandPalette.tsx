import React, { useState, useEffect } from 'react';
import type { ConceptNode, SourceDocument } from '../../api/client';
import { Search, Compass, BookOpen, MessageSquare, X } from 'lucide-react';

export interface CommandPaletteProps {
  isOpen: boolean;
  onClose: () => void;
  concepts: ConceptNode[];
  sources: SourceDocument[];
  onSelectConcept: (concept: ConceptNode) => void;
  onNavigateToAtlas: () => void;
  onNavigateToSources: () => void;
  onAskTutor: (conceptId: string) => void;
}

export const CommandPalette: React.FC<CommandPaletteProps> = ({
  isOpen,
  onClose,
  concepts,
  sources,
  onSelectConcept,
  onNavigateToAtlas,
  onNavigateToSources,
  onAskTutor,
}) => {
  const [query, setQuery] = useState<string>('');

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        if (isOpen) onClose();
      } else if (e.key === 'Escape' && isOpen) {
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const filteredConcepts = concepts.filter(
    (c) => c.name.toLowerCase().includes(query.toLowerCase()) || (c.definition || c.description || '').toLowerCase().includes(query.toLowerCase())
  );

  const filteredSources = sources.filter((s) => s.title.toLowerCase().includes(query.toLowerCase()));

  return (
    <div className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-md p-4 flex items-start justify-center pt-20">
      <div className="w-full max-w-xl rounded-2xl bg-slate-900 border border-slate-700 shadow-2xl overflow-hidden">
        {/* Search Input Bar */}
        <div className="p-4 border-b border-slate-800 flex items-center gap-3">
          <Search className="w-5 h-5 text-cyan-400" />
          <input
            type="text"
            autoFocus
            placeholder="Search concepts, sources, or quick actions (Cmd + K)..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="flex-1 bg-transparent text-sm text-white placeholder-slate-500 focus:outline-none"
          />
          <button onClick={onClose} className="p-1 rounded bg-slate-800 text-slate-400 hover:text-white text-xs">
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Results Feed */}
        <div className="max-h-80 overflow-y-auto p-3 space-y-4 text-xs font-sans">
          {/* Quick Shortcuts */}
          {!query && (
            <div>
              <span className="text-[10px] font-mono font-bold text-slate-500 uppercase tracking-widest px-2">
                QUICK ACTIONS
              </span>
              <div className="mt-2 space-y-1">
                <button
                  onClick={() => {
                    onNavigateToAtlas();
                    onClose();
                  }}
                  className="w-full p-2.5 rounded-xl hover:bg-slate-800 text-left text-slate-200 flex items-center gap-2"
                >
                  <Compass className="w-4 h-4 text-cyan-400" /> Open Learning Atlas Map
                </button>
                <button
                  onClick={() => {
                    onNavigateToSources();
                    onClose();
                  }}
                  className="w-full p-2.5 rounded-xl hover:bg-slate-800 text-left text-slate-200 flex items-center gap-2"
                >
                  <BookOpen className="w-4 h-4 text-emerald-400" /> View Source Document Library
                </button>
              </div>
            </div>
          )}

          {/* Concepts Section */}
          {filteredConcepts.length > 0 && (
            <div>
              <span className="text-[10px] font-mono font-bold text-slate-500 uppercase tracking-widest px-2">
                CONCEPTS ({filteredConcepts.length})
              </span>
              <div className="mt-2 space-y-1">
                {filteredConcepts.slice(0, 5).map((c) => (
                  <div
                    key={c.concept_id}
                    onClick={() => {
                      onSelectConcept(c);
                      onClose();
                    }}
                    className="p-2.5 rounded-xl hover:bg-slate-800 cursor-pointer flex items-center justify-between text-slate-200"
                  >
                    <div>
                      <h5 className="font-bold text-white">{c.name}</h5>
                      <p className="text-[11px] text-slate-400 line-clamp-1">{c.definition}</p>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-cyan-400 font-mono font-bold">{Math.round(c.mastery * 100)}%</span>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          onAskTutor(c.concept_id);
                          onClose();
                        }}
                        className="p-1 rounded bg-slate-950 border border-slate-800 text-slate-400 hover:text-cyan-400"
                      >
                        <MessageSquare className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Sources Section */}
          {filteredSources.length > 0 && (
            <div>
              <span className="text-[10px] font-mono font-bold text-slate-500 uppercase tracking-widest px-2">
                SOURCES ({filteredSources.length})
              </span>
              <div className="mt-2 space-y-1">
                {filteredSources.map((s) => (
                  <div
                    key={s.document_id}
                    onClick={() => {
                      onNavigateToSources();
                      onClose();
                    }}
                    className="p-2.5 rounded-xl hover:bg-slate-800 cursor-pointer flex items-center gap-2 text-slate-200"
                  >
                    <BookOpen className="w-4 h-4 text-amber-400" />
                    <span>{s.title}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
