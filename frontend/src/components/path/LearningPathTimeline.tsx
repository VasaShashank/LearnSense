import React from 'react';
import type { LearningPathNode, LearningTarget } from '../../api/client';
import { CheckCircle2, Target, Lock, Play, HelpCircle, Sparkles } from 'lucide-react';

export interface LearningPathTimelineProps {
  nodes: LearningPathNode[];
  activeTarget: LearningTarget | null;
  onSelectConcept: (conceptId: string) => void;
}

export const LearningPathTimeline: React.FC<LearningPathTimelineProps> = ({
  nodes,
  activeTarget,
  onSelectConcept,
}) => {
  return (
    <div className="p-6 rounded-3xl border border-slate-800 bg-slate-950 text-slate-100">
      <div className="flex items-center justify-between pb-4 border-b border-slate-800">
        <div>
          <h3 className="text-lg font-bold text-white flex items-center gap-2">
            <Sparkles className="w-5 h-5 text-cyan-400" />
            Personalized Learning Journey Path
          </h3>
          <p className="text-xs text-slate-400 mt-1">
            Prerequisite-aware, cycle-safe linear sequence generated dynamically by Phase 4 reasoning.
          </p>
        </div>
        {activeTarget && (
          <div className="px-3 py-1.5 rounded-xl bg-sky-950/80 border border-sky-500/50 text-xs font-mono text-sky-200 flex items-center gap-2">
            <Target className="w-4 h-4 text-sky-400 animate-spin" style={{ animationDuration: '6s' }} />
            <span>ACTIVE TARGET: {activeTarget.concept_name || activeTarget.name || activeTarget.concept_id}</span>
          </div>
        )}
      </div>

      {/* Active Next Target Highlight Card */}
      {activeTarget && (
        <div className="mt-5 p-4 rounded-2xl bg-gradient-to-r from-sky-950/90 via-slate-900 to-indigo-950/80 border border-sky-500/40 shadow-glow-cyan flex flex-wrap items-center justify-between gap-4">
          <div>
            <span className="text-[10px] font-mono tracking-widest text-sky-400 uppercase font-bold">
              YOUR NEXT MOVE
            </span>
            <h4 className="text-base font-extrabold text-white mt-0.5">
              {activeTarget.concept_name || activeTarget.name || activeTarget.concept_id}
            </h4>
            <p className="text-xs text-slate-300/90 mt-1 leading-relaxed">
              <strong className="text-sky-300">Why?</strong> {activeTarget.reason}
            </p>
          </div>
          <button
            onClick={() => onSelectConcept(activeTarget.concept_id)}
            className="py-2.5 px-5 rounded-xl bg-sky-400 hover:bg-sky-300 text-slate-950 font-bold text-xs flex items-center gap-2 shadow-glow-cyan transition-all"
          >
            <Play className="w-4 h-4 fill-current" />
            <span>Continue Target</span>
          </button>
        </div>
      )}

      {/* Timeline Nodes */}
      <div className="mt-6 relative pl-6 border-l-2 border-slate-800 space-y-6">
        {nodes.map((node, index) => {
          const nodeName = node.concept_name || node.name || node.concept_id.replace(/_/g, ' ').toUpperCase();
          const nodeMastery = node.mastery ?? node.estimated_mastery ?? 0;
          const prereqs = Array.isArray(node.prerequisites) ? node.prerequisites : [];
          const isTarget = node.concept_id === activeTarget?.concept_id || node.status === 'ACTIVE_TARGET' || node.status === 'IN_PROGRESS';
          const isCompleted = node.status === 'COMPLETED' || nodeMastery >= 0.75;
          const isBlocked = node.status === 'BLOCKED';

          let icon = <HelpCircle className="w-4 h-4 text-slate-400" />;
          let statusBg = 'bg-slate-900 border-slate-700 text-slate-300';
          let statusText = 'AVAILABLE';

          if (isCompleted) {
            icon = <CheckCircle2 className="w-4 h-4 text-emerald-400" />;
            statusBg = 'bg-emerald-950/60 border-emerald-500/50 text-emerald-200';
            statusText = 'COMPLETED';
          } else if (isTarget) {
            icon = <Target className="w-4 h-4 text-sky-400" />;
            statusBg = 'bg-sky-950/80 border-sky-400 text-sky-100 shadow-glow-cyan';
            statusText = 'CURRENT TARGET';
          } else if (isBlocked) {
            icon = <Lock className="w-4 h-4 text-slate-500" />;
            statusBg = 'bg-slate-900/40 border-slate-800 text-slate-500 opacity-60';
            statusText = 'BLOCKED BY PREREQUISITES';
          }

          return (
            <div key={node.concept_id} className="relative group">
              {/* Timeline Marker Circle */}
              <div
                className={`absolute -left-[31px] top-1 w-6 h-6 rounded-full border flex items-center justify-center ${statusBg}`}
              >
                {icon}
              </div>

              {/* Node Card */}
              <div
                onClick={() => onSelectConcept(node.concept_id)}
                className={`p-4 rounded-2xl border cursor-pointer transition-all duration-300 hover:border-cyan-400/60 ${statusBg}`}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] font-mono tracking-widest font-bold px-2 py-0.5 rounded bg-slate-950/60 border border-slate-800">
                      STEP {index + 1} • {statusText}
                    </span>
                  </div>
                  <span className="text-xs font-mono font-bold text-cyan-300">
                    {Math.round(nodeMastery * 100)}% Mastery
                  </span>
                </div>

                <h4 className="text-sm font-bold text-white mt-2 group-hover:text-cyan-300 transition-colors">
                  {nodeName}
                </h4>

                {prereqs.length > 0 && (
                  <p className="text-[11px] text-slate-400 mt-1 font-mono">
                    Prereqs: {prereqs.join(', ')}
                  </p>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
