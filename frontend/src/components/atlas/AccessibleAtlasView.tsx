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
    <div className="w-full p-6 rounded-3xl border border-slate-800 bg-slate-950 text-slate-200">
      <div className="mb-4 pb-3 border-b border-slate-800">
        <h3 className="text-lg font-bold text-white">Structured Knowledge Atlas (Accessible View)</h3>
        <p className="text-xs text-slate-400">
          Structured alternative view of concepts, mastery levels, prerequisite dependencies, and downstream impact for screen readers and keyboard navigation.
        </p>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs font-mono border-collapse">
          <thead>
            <tr className="border-b border-slate-800 text-slate-400 uppercase tracking-wider">
              <th className="py-2.5 px-3">Concept Name</th>
              <th className="py-2.5 px-3">Status</th>
              <th className="py-2.5 px-3">Mastery</th>
              <th className="py-2.5 px-3">Prerequisites</th>
              <th className="py-2.5 px-3">Downstream</th>
              <th className="py-2.5 px-3 text-right">Action</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/60">
            {graphData.concepts.map((concept) => {
              let statusBadge = (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-slate-800 text-slate-400">
                  <HelpCircle className="w-3 h-3" /> Unknown
                </span>
              );

              if (concept.mastery >= 0.75) {
                statusBadge = (
                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-emerald-950 text-emerald-300 border border-emerald-800">
                    <CheckCircle2 className="w-3 h-3 text-emerald-400" /> Mastered
                  </span>
                );
              } else if (concept.mastery >= 0.4) {
                statusBadge = (
                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-cyan-950 text-cyan-300 border border-cyan-800">
                    <Sparkles className="w-3 h-3 text-cyan-400" /> Developing
                  </span>
                );
              } else {
                statusBadge = (
                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-amber-950 text-amber-300 border border-amber-800">
                    <AlertCircle className="w-3 h-3 text-amber-400" /> Needs Attention
                  </span>
                );
              }

              return (
                <tr key={concept.concept_id} className="hover:bg-slate-900/60 transition-colors">
                  <td className="py-3 px-3 font-semibold text-white">{concept.name}</td>
                  <td className="py-3 px-3">{statusBadge}</td>
                  <td className="py-3 px-3 text-cyan-300 font-bold">{Math.round(concept.mastery * 100)}%</td>
                  <td className="py-3 px-3 text-slate-400">
                    {concept.prerequisites.length > 0 ? concept.prerequisites.join(', ') : 'None (Foundational)'}
                  </td>
                  <td className="py-3 px-3 text-slate-400">
                    {concept.dependents.length > 0 ? concept.dependents.join(', ') : 'None'}
                  </td>
                  <td className="py-3 px-3 text-right">
                    <button
                      onClick={() => onSelectConcept(concept)}
                      className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-sky-300 font-bold flex items-center gap-1 ml-auto"
                      aria-label={`Inspect ${concept.name}`}
                    >
                      <span>Inspect</span>
                      <ArrowRight className="w-3.5 h-3.5" />
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
