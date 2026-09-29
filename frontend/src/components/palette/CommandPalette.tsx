import React, { useState, useEffect } from 'react';
import type { ConceptNode, SourceDocument } from '../../api/client';
import { Search, BookOpen, MessageSquare, X, Orbit } from 'lucide-react';

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
    <div className="fixed inset-0 z-50 bg-space-950/80 backdrop-blur-xl p-4 flex items-start justify-center pt-24 animate-fade-in">
      <div className="w-full max-w-xl universe-panel-solid rounded-3xl border border-white/[0.1] shadow-[0_32px_80px_rgba(0,0,0,0.8)] overflow-hidden">
        
        {/* Search Input Bar */}
        <div className="p-4 border-b border-white/[0.07] flex items-center gap-3 bg-space-900/60">
          <Search className="w-4 h-4 text-cyan-400 shrink-0 ml-1" />
          <input
            type="text"
            autoFocus
            placeholder="Search knowledge concepts, sources, or jump to actions..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="flex-1 bg-transparent text-xs text-white placeholder-universe-slate focus:outline-none font-sans"
          />
          <button 
            onClick={onClose} 
            className="p-1.5 rounded-lg bg-space-800 hover:bg-space-700 text-universe-slate hover:text-white transition-colors"
            aria-label="Close command palette"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>

        {/* Results Feed */}
        <div className="max-h-80 overflow-y-auto p-3 space-y-4 text-xs font-sans">
          {/* Quick Shortcuts */}
          {!query && (
            <div className="space-y-1">
              <span className="text-[10px] font-mono font-bold text-universe-slate/70 uppercase tracking-widest px-2.5">
                SPATIAL SHORTCUTS
              </span>
              <div className="space-y-1">
                <button
                  onClick={() => {
                    onNavigateToAtlas();
                    onClose();
                  }}
                  className="w-full p-2.5 rounded-xl hover:bg-space-800 text-left text-universe-text flex items-center justify-between group transition-colors"
                >
                  <div className="flex items-center gap-2.5">
                    <Orbit className="w-4 h-4 text-cyan-400" /> 
                    <span>Open Knowledge Atlas Map</span>
                  </div>
                  <span className="text-[10px] font-mono text-universe-slate group-hover:text-white">↵</span>
                </button>
                <button
                  onClick={() => {
                    onNavigateToSources();
                    onClose();
                  }}
                  className="w-full p-2.5 rounded-xl hover:bg-space-800 text-left text-universe-text flex items-center justify-between group transition-colors"
                >
                  <div className="flex items-center gap-2.5">
                    <BookOpen className="w-4 h-4 text-emerald-400" /> 
                    <span>View Grounded Source Library</span>
                  </div>
                  <span className="text-[10px] font-mono text-universe-slate group-hover:text-white">↵</span>
                </button>
              </div>
            </div>
          )}

          {/* Concepts Section */}
          {filteredConcepts.length > 0 && (
            <div className="space-y-1">
              <span className="text-[10px] font-mono font-bold text-universe-slate/70 uppercase tracking-widest px-2.5">
                KNOWLEDGE CONCEPTS ({filteredConcepts.length})
              </span>
              <div className="space-y-1">
                {filteredConcepts.slice(0, 5).map((c) => (
                  <div
                    key={c.concept_id}
                    onClick={() => {
                      onSelectConcept(c);
                      onClose();
                    }}
                    className="p-2.5 rounded-xl hover:bg-space-800 cursor-pointer flex items-center justify-between text-universe-text group transition-colors"
                  >
                    <div className="pr-4">
                      <h5 className="font-display font-bold text-white group-hover:text-cyan-300 transition-colors">{c.name}</h5>
                      <p className="text-[11px] text-universe-slate line-clamp-1">{c.definition}</p>
                    </div>
                    <div className="flex items-center gap-2.5 shrink-0">
                      <span className="text-cyan-400 font-mono font-bold text-[11px]">{Math.round(c.mastery * 100)}%</span>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          onAskTutor(c.concept_id);
                          onClose();
                        }}
                        className="p-1.5 rounded-lg bg-space-950 border border-white/[0.08] text-universe-slate hover:text-cyan-400 transition-colors"
                        title="Ask AI Tutor"
                      >
                        <MessageSquare className="w-3 h-3" />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Sources Section */}
          {filteredSources.length > 0 && (
            <div className="space-y-1">
              <span className="text-[10px] font-mono font-bold text-universe-slate/70 uppercase tracking-widest px-2.5">
                GROUNDED SOURCES ({filteredSources.length})
              </span>
              <div className="space-y-1">
                {filteredSources.map((s) => (
                  <div
                    key={s.document_id}
                    onClick={() => {
                      onNavigateToSources();
                      onClose();
                    }}
                    className="p-2.5 rounded-xl hover:bg-space-800 cursor-pointer flex items-center gap-2.5 text-universe-text group transition-colors"
                  >
                    <BookOpen className="w-4 h-4 text-amber-400" />
                    <span className="group-hover:text-white transition-colors">{s.title}</span>
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
