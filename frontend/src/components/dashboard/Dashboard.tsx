import React from 'react';
import type { Subject, LearnerProgress, KnowledgeGap, LearningTarget } from '../../api/client';
import { Play, Sparkles, AlertTriangle, BookOpen, Compass } from 'lucide-react';

export interface DashboardProps {
  currentSubject: Subject;
  progress: LearnerProgress | null;
  gaps: KnowledgeGap[];
  nextTarget: LearningTarget | null;
  onNavigateToAtlas: () => void;
  onNavigateToPath: () => void;
  onNavigateToSession: (conceptId: string) => void;
  onNavigateToSources: () => void;
}

export const Dashboard: React.FC<DashboardProps> = ({
  currentSubject,
  progress,
  gaps,
  nextTarget,
  onNavigateToAtlas,
  onNavigateToPath,
  onNavigateToSession,
  onNavigateToSources,
}) => {
  return (
    <div className="space-y-6">
      {/* Header Banner */}
      <div className="p-8 rounded-3xl bg-gradient-to-r from-slate-900 via-slate-950 to-indigo-950/80 border border-slate-800 relative overflow-hidden shadow-2xl">
        <div className="relative z-10 flex flex-wrap items-center justify-between gap-6">
          <div>
            <div className="flex items-center gap-2">
              <span className="w-2.5 h-2.5 rounded-full bg-cyan-400 shadow-glow-cyan" />
              <span className="text-xs font-mono font-bold tracking-widest text-cyan-300 uppercase">
                ACTIVE SUBJECT: {currentSubject.title}
              </span>
            </div>
            <h1 className="text-2xl sm:text-3xl font-extrabold text-white mt-2 tracking-tight">
              Where Am I in My Learning Journey?
            </h1>
            <p className="text-xs text-slate-300/80 mt-1 max-w-xl leading-relaxed">
              Taproot dynamically estimates your knowledge landscape, detects weak prerequisite connections, and plans your next move.
            </p>
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={onNavigateToAtlas}
              className="py-3 px-5 rounded-2xl bg-cyan-500 hover:bg-cyan-400 text-slate-950 font-bold text-xs flex items-center gap-2 shadow-glow-cyan transition-all"
            >
              <Compass className="w-4 h-4" />
              <span>Explore Atlas</span>
            </button>

            <button
              onClick={onNavigateToSources}
              className="py-3 px-5 rounded-2xl bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 font-bold text-xs flex items-center gap-2 transition-all"
            >
              <BookOpen className="w-4 h-4 text-cyan-400" />
              <span>Source Library</span>
            </button>
          </div>
        </div>
      </div>

      {/* Prominent "YOUR NEXT MOVE" Card (Part 18 Requirement) */}
      {nextTarget && (
        <div className="p-6 rounded-3xl bg-gradient-to-r from-sky-950/90 via-slate-900 to-indigo-950/90 border border-sky-400/50 shadow-glow-cyan flex flex-wrap items-center justify-between gap-6">
          <div className="max-w-xl">
            <div className="flex items-center gap-2">
              <Sparkles className="w-4 h-4 text-sky-400" />
              <span className="text-xs font-mono font-bold tracking-widest text-sky-400 uppercase">
                YOUR NEXT MOVE
              </span>
            </div>
            <h3 className="text-xl font-black text-white mt-1">{nextTarget.concept_name || nextTarget.name || nextTarget.concept_id}</h3>
            <p className="text-xs text-slate-200 mt-2 leading-relaxed">
              <strong className="text-sky-300">Why?</strong> {nextTarget.reason}
            </p>
          </div>

          <button
            onClick={() => onNavigateToSession(nextTarget.concept_id)}
            className="py-3.5 px-6 rounded-2xl bg-sky-400 hover:bg-sky-300 text-slate-950 font-extrabold text-xs flex items-center gap-2 shadow-glow-cyan transition-all scale-105"
          >
            <Play className="w-4 h-4 fill-current" />
            <span>Continue Target</span>
          </button>
        </div>
      )}

      {/* Analytics Overview Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="p-5 rounded-2xl border border-slate-800 bg-slate-950/80">
          <span className="text-[10px] font-mono text-slate-400 block">DEMONSTRATED MASTERY</span>
          <div className="flex items-baseline gap-2 mt-2">
            <span className="text-3xl font-extrabold text-emerald-400">
              {progress ? Math.round(progress.average_mastery * 100) : 0}%
            </span>
            <span className="text-xs text-slate-400 font-mono">BKT probability</span>
          </div>
        </div>

        <div className="p-5 rounded-2xl border border-slate-800 bg-slate-950/80">
          <span className="text-[10px] font-mono text-slate-400 block">EXPLORATION RATE</span>
          <div className="flex items-baseline gap-2 mt-2">
            <span className="text-3xl font-extrabold text-cyan-400">
              {progress ? Math.round(progress.exploration_rate * 100) : 0}%
            </span>
            <span className="text-xs text-slate-400 font-mono">
              {progress?.explored_concepts || 0}/{progress?.total_concepts || 0}
            </span>
          </div>
        </div>

        <div className="p-5 rounded-2xl border border-slate-800 bg-slate-950/80">
          <span className="text-[10px] font-mono text-slate-400 block">MASTERED CONCEPTS</span>
          <div className="flex items-baseline gap-2 mt-2">
            <span className="text-3xl font-extrabold text-emerald-400">
              {progress?.mastered_concepts || 0}
            </span>
            <span className="text-xs text-slate-400 font-mono">Verified solid</span>
          </div>
        </div>

        <div className="p-5 rounded-2xl border border-slate-800 bg-slate-950/80">
          <span className="text-[10px] font-mono text-slate-400 block">ACTIVE GAPS</span>
          <div className="flex items-baseline gap-2 mt-2">
            <span className="text-3xl font-extrabold text-amber-400">{gaps.length}</span>
            <span className="text-xs text-slate-400 font-mono">Needs attention</span>
          </div>
        </div>
      </div>

      {/* Active Knowledge Gaps List */}
      {gaps.length > 0 && (
        <div className="p-6 rounded-3xl border border-slate-800 bg-slate-950">
          <div className="flex items-center justify-between pb-4 border-b border-slate-800">
            <h3 className="text-base font-bold text-white flex items-center gap-2">
              <AlertTriangle className="w-5 h-5 text-amber-400" />
              Prioritized Knowledge Gaps ({gaps.length})
            </h3>
            <button
              onClick={onNavigateToPath}
              className="text-xs font-mono text-cyan-400 hover:underline"
            >
              View Full Path →
            </button>
          </div>

          <div className="mt-4 space-y-3">
            {gaps.slice(0, 3).map((gap) => (
              <div
                key={gap.concept_id}
                onClick={() => onNavigateToSession(gap.concept_id)}
                className="p-4 rounded-2xl border border-amber-500/30 bg-amber-950/20 hover:bg-amber-950/40 cursor-pointer transition-all flex items-center justify-between gap-4"
              >
                <div>
                  <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-amber-900/60 border border-amber-500/40 text-amber-300">
                    {gap.category} • PRIORITY {Math.round(gap.priority_score * 100)}
                  </span>
                  <h4 className="text-sm font-bold text-white mt-1 uppercase">
                    {gap.concept_id.replace(/_/g, ' ')}
                  </h4>
                  <p className="text-xs text-slate-300 mt-0.5 leading-relaxed">{gap.reason}</p>
                </div>
                <Play className="w-4 h-4 text-amber-400 shrink-0" />
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};
