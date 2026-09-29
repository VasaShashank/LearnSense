import React from 'react';
import type { KnowledgeGraphData, ConceptNode } from '../../api/client';
import { CheckCircle2, Sparkles, AlertCircle, HelpCircle, ArrowRight } from 'lucide-react';

export interface AccessibleAtlasViewProps {
  graphData: KnowledgeGraphData;
  onSelectConcept: (concept: ConceptNode) => void;
}

export const AccessibleAtlasView: React.FC<AccessibleAtlasViewProps> = ({
  graphData,
  onSelectConcept,
}) => {
  return (
    <div className="w-full universe-panel rounded-3xl p-6 lg:p-8 text-universe-text space-y-6 animate-fade-in">
      <div className="pb-4 border-b border-white/[0.07] space-y-1">
        <h3 className="text-lg font-display font-bold text-white">
          Structured Knowledge Atlas (Accessible Data Table)
        </h3>
        <p className="text-xs text-universe-slate font-sans leading-relaxed">
          Screen-reader optimized tabular view of conceptual nodes, Bayesian mastery estimates, prerequisite trees, and downstream impact.
        </p>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs font-mono border-collapse">
          <thead>
            <tr className="border-b border-white/[0.08] text-universe-slate uppercase tracking-wider text-[10px]">
              <th className="py-3 px-3">Concept Name</th>
              <th className="py-3 px-3">Status</th>
              <th className="py-3 px-3">Mastery</th>
              <th className="py-3 px-3">Prerequisites</th>
              <th className="py-3 px-3">Downstream</th>
              <th className="py-3 px-3 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/[0.05]">
            {graphData.concepts.map((concept) => {
              let statusBadge = (
                <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded bg-space-850 text-universe-slate border border-white/[0.06]">
                  <HelpCircle className="w-3 h-3" /> Unknown
                </span>
              );

              if (concept.mastery >= 0.75) {
                statusBadge = (
                  <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded bg-emerald-950/60 text-emerald-300 border border-emerald-500/40">
                    <CheckCircle2 className="w-3 h-3 text-emerald-400" /> Mastered
                  </span>
                );
              } else if (concept.mastery >= 0.4) {
                statusBadge = (
                  <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded bg-cyan-950/60 text-cyan-300 border border-cyan-500/40">
                    <Sparkles className="w-3 h-3 text-cyan-400" /> Developing
                  </span>
                );
              } else {
                statusBadge = (
                  <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded bg-amber-950/60 text-amber-300 border border-amber-500/40">
                    <AlertCircle className="w-3 h-3 text-amber-400" /> Gap Attention
                  </span>
                );
              }

              return (
                <tr key={concept.concept_id} className="hover:bg-space-850/60 transition-colors">
                  <td className="py-3.5 px-3 font-display font-bold text-white text-xs">{concept.name}</td>
                  <td className="py-3.5 px-3 text-[11px]">{statusBadge}</td>
                  <td className="py-3.5 px-3 text-cyan-300 font-bold">{Math.round(concept.mastery * 100)}%</td>
                  <td className="py-3.5 px-3 text-universe-slate text-[11px]">
                    {concept.prerequisites.length > 0 ? concept.prerequisites.join(', ') : 'None (Root)'}
                  </td>
                  <td className="py-3.5 px-3 text-universe-slate text-[11px]">
                    {concept.dependents && concept.dependents.length > 0 ? concept.dependents.join(', ') : 'None'}
                  </td>
                  <td className="py-3.5 px-3 text-right">
                    <button
                      onClick={() => onSelectConcept(concept)}
                      className="px-3 py-1.5 rounded-lg bg-space-850 hover:bg-cyan-400 hover:text-space-950 text-cyan-300 font-mono font-bold flex items-center gap-1 ml-auto border border-white/[0.07] transition-all"
                      aria-label={`Inspect ${concept.name}`}
                    >
                      <span>Inspect</span>
                      <ArrowRight className="w-3 h-3" />
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
};
