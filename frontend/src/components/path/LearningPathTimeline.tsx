import React from 'react';
import type { LearningPathNode, LearningTarget } from '../../api/client';
import { CheckCircle2, Target, Lock, Play, HelpCircle, Sparkles, ArrowRight } from 'lucide-react';

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
    <div className="space-y-6 animate-fade-in">
      
      {/* 1. Header Section */}
      <div className="universe-panel rounded-3xl p-6 lg:p-8 flex flex-wrap items-center justify-between gap-6">
        <div className="space-y-1 max-w-xl">
          <div className="flex items-center gap-2">
            <Sparkles className="w-4 h-4 text-cyan-400" />
            <span className="text-[10px] font-mono tracking-widest text-cyan-300 uppercase font-bold">
              EXPEDITION VECTOR // KNOWLEDGE JOURNEY
            </span>
          </div>
          <h2 className="text-2xl sm:text-3xl font-display font-extrabold text-white tracking-tight">
            Personalized Learning Path
          </h2>
          <p className="text-xs text-universe-slate font-sans leading-relaxed">
            Cycle-safe linear progression dynamically ordered by prerequisite topology, information gain, and current mastery.
          </p>
        </div>

        {activeTarget && (
          <div className="px-4 py-2.5 rounded-2xl bg-space-850/80 border border-cyan-500/30 text-xs font-mono text-cyan-300 flex items-center gap-2.5 shadow-[0_0_16px_rgba(0,240,255,0.1)]">
            <Target className="w-4 h-4 text-cyan-400 animate-spin" style={{ animationDuration: '8s' }} />
            <span>ACTIVE TARGET: {activeTarget.concept_name || activeTarget.name || activeTarget.concept_id}</span>
          </div>
        )}
      </div>

      {/* 2. Active Target Spotlight Card */}
      {activeTarget && (
        <div className="universe-panel rounded-3xl p-6 lg:p-8 border-cyan-500/40 shadow-[0_8px_32px_rgba(0,240,255,0.1)] flex flex-col md:flex-row items-start md:items-center justify-between gap-6">
          <div className="space-y-2 max-w-2xl">
            <span className="text-[10px] font-mono tracking-widest text-cyan-400 uppercase font-bold px-2 py-0.5 rounded bg-cyan-950/70 border border-cyan-500/30">
              NEXT STEP IN JOURNEY
            </span>
            <h3 className="text-xl font-display font-bold text-white">
              {activeTarget.concept_name || activeTarget.name || activeTarget.concept_id}
            </h3>
            <p className="text-xs text-universe-slate leading-relaxed font-sans">
              <strong className="text-cyan-300 font-mono font-medium">Why now?</strong> {activeTarget.reason}
            </p>
          </div>

          <button
            onClick={() => onSelectConcept(activeTarget.concept_id)}
            className="w-full md:w-auto px-6 py-3.5 rounded-xl bg-cyan-400 hover:bg-cyan-300 text-space-950 font-display font-bold text-xs flex items-center justify-center gap-2 shadow-[0_0_24px_rgba(0,240,255,0.3)] transition-all hover:scale-[1.02] shrink-0"
          >
            <Play className="w-4 h-4 fill-current" />
            <span>Continue Journey</span>
          </button>
        </div>
      )}

      {/* 3. Milestone Expedition Path */}
      <div className="universe-panel rounded-3xl p-6 lg:p-8">
        <div className="relative pl-8 border-l border-white/[0.1] space-y-8 my-2">
          {nodes.map((node, index) => {
            const nodeName = node.concept_name || node.name || node.concept_id.replace(/_/g, ' ').toUpperCase();
            const nodeMastery = node.mastery ?? node.estimated_mastery ?? 0;
            const masteryPercent = Math.round(nodeMastery * 100);
            const prereqs = Array.isArray(node.prerequisites) ? node.prerequisites : [];
            const isTarget = node.concept_id === activeTarget?.concept_id || node.status === 'ACTIVE_TARGET' || node.status === 'IN_PROGRESS';
            const isCompleted = node.status === 'COMPLETED' || nodeMastery >= 0.75;
            const isBlocked = node.status === 'BLOCKED';

            let markerIcon = <HelpCircle className="w-3.5 h-3.5 text-universe-slate" />;
            let markerStyle = 'bg-space-900 border-white/[0.1] text-universe-slate';
            let cardStyle = 'universe-panel-interactive border-white/[0.07]';
            let badgeText = 'AVAILABLE';
            let badgeColor = 'text-universe-slate bg-space-950/80 border-white/[0.06]';

            if (isCompleted) {
              markerIcon = <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />;
              markerStyle = 'bg-space-900 border-emerald-500/60 shadow-[0_0_12px_rgba(16,185,129,0.3)]';
              cardStyle = 'bg-space-850/60 border-emerald-500/30 hover:border-emerald-400/50';
              badgeText = 'MASTERED';
              badgeColor = 'text-emerald-300 bg-emerald-950/60 border-emerald-500/40';
            } else if (isTarget) {
              markerIcon = <Target className="w-3.5 h-3.5 text-cyan-400 animate-spin" style={{ animationDuration: '8s' }} />;
              markerStyle = 'bg-space-850 border-cyan-400 shadow-[0_0_20px_rgba(0,240,255,0.4)] scale-110';
              cardStyle = 'bg-space-800/90 border-cyan-400/60 shadow-[0_0_32px_rgba(0,240,255,0.12)] ring-1 ring-cyan-400/30';
              badgeText = 'ACTIVE TARGET';
              badgeColor = 'text-cyan-300 bg-cyan-950/70 border-cyan-500/40';
            } else if (isBlocked) {
              markerIcon = <Lock className="w-3.5 h-3.5 text-universe-slate/60" />;
              markerStyle = 'bg-space-950 border-white/[0.05] opacity-50';
              cardStyle = 'bg-space-950/40 border-white/[0.04] opacity-60';
              badgeText = 'BLOCKED BY PREREQUISITES';
              badgeColor = 'text-universe-slate bg-space-950 border-white/[0.04]';
            }

            return (
              <div key={node.concept_id} className="relative group">
                
                {/* Milestone Marker Dot on Linear Vector */}
                <div
                  className={`absolute -left-[45px] top-4 w-6 h-6 rounded-full border flex items-center justify-center transition-transform group-hover:scale-110 ${markerStyle}`}
                >
                  {markerIcon}
                </div>

                {/* Milestone Content Card */}
                <div
                  onClick={() => onSelectConcept(node.concept_id)}
                  className={`p-5 rounded-2xl cursor-pointer transition-all duration-200 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 ${cardStyle}`}
                >
                  <div className="space-y-1.5 max-w-xl">
                    <div className="flex items-center gap-2">
                      <span className={`text-[10px] font-mono tracking-widest font-bold px-2 py-0.5 rounded border ${badgeColor}`}>
                        STEP {index + 1 < 10 ? `0${index + 1}` : index + 1} // {badgeText}
                      </span>
                    </div>

                    <h4 className="text-base font-display font-bold text-white group-hover:text-cyan-300 transition-colors">
                      {nodeName}
                    </h4>

                    {prereqs.length > 0 && (
                      <p className="text-[11px] text-universe-slate font-mono">
                        Requires: {prereqs.join(', ')}
                      </p>
                    )}
                  </div>

                  <div className="flex items-center gap-4 self-end sm:self-center shrink-0">
                    <div className="text-right">
                      <span className="text-xs font-mono font-bold text-white block">
                        {masteryPercent}%
                      </span>
                      <span className="text-[10px] font-mono text-universe-slate block">
                        Mastery
                      </span>
                    </div>

                    <div className="p-2 rounded-xl bg-space-900 border border-white/[0.08] text-universe-slate group-hover:text-cyan-400 group-hover:border-cyan-400/40 transition-colors">
                      <ArrowRight className="w-4 h-4" />
                    </div>
                  </div>
                </div>

              </div>
            );
          })}
        </div>
      </div>

    </div>
  );
};
