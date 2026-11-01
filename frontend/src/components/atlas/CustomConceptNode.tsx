import { memo, useState } from 'react';
import { Handle, Position } from '@xyflow/react';
import type { ConceptNode } from '../../api/client';
import { Check, Compass, Bookmark, MessageSquare, Route } from 'lucide-react';

export interface ConceptNodeData extends ConceptNode, Record<string, unknown> {
  isCore?: boolean;
  nodeType?: 'core' | 'standard' | 'supporting';
  labelPosition?: 'right' | 'left' | 'top' | 'bottom';
  isTarget?: boolean;
  isRecommendedNext?: boolean;
  recommendationReason?: string;
  isBookmarked?: boolean;
  hasPersonalNote?: boolean;
  personalNote?: string;
  isXRay?: boolean;
  isImpacted?: boolean;
  isSelected?: boolean;
  isPrerequisiteOfSelected?: boolean;
  isDependentOfSelected?: boolean;
  isDimmed?: boolean;
  learningStep?: number;
  isLearningPathActive?: boolean;
  topicName?: string;
  zoomLevel: number;
  onSelect: (concept: ConceptNode) => void;
}

export const CustomConceptNode = memo(({ data }: { data: ConceptNodeData }) => {
  const {
    name,
    mastery = 0.0,
    uncertainty = 0.3,
    isCore = false,
    labelPosition = 'right',
    isTarget,
    isRecommendedNext,
    recommendationReason,
    isBookmarked,
    hasPersonalNote,
    personalNote,
    isXRay,
    isImpacted,
    isSelected,
    isPrerequisiteOfSelected,
    isDependentOfSelected,
    isDimmed,
    topicName,
    bloom_level,
    prerequisites = [],
    learningStep,
    isLearningPathActive,
    onSelect,
  } = data;

  const [isHovered, setIsHovered] = useState(false);
  const masteryPercent = Math.round(mastery * 100);

  // Four authentic progress-responsive learner states
  const isMastered = mastery >= 0.75;
  const isLearning = mastery >= 0.35 && !isMastered;
  const isNotAssessed = !isMastered && !isLearning;

  // Derive node role: Core concept (large star) vs Standard concept (small star) vs Supporting concept (circle)
  const isStandardCandidate = Boolean(
    (data.dependents && data.dependents.length > 0) ||
    (prerequisites && prerequisites.length > 1) ||
    isRecommendedNext ||
    isTarget
  );

  const effectiveNodeType: 'core' | 'standard' | 'supporting' =
    data.nodeType ? data.nodeType : isCore ? 'core' : isStandardCandidate ? 'standard' : 'supporting';

  // Modest 15-25% visual scale increase
  // Core star: 56px (previous 48px -> ~17% increase)
  // Standard star: 34px (previous 28px -> ~21% increase)
  // Supporting circle: 24px marker with 40px clickable hit area
  let markerSize = 34;
  let visualWidth = 'w-[34px] h-[34px]';
  let hitAreaSize = 'w-[44px] h-[44px]';

  if (effectiveNodeType === 'core') {
    markerSize = 56;
    visualWidth = 'w-[56px] h-[56px]';
    hitAreaSize = 'w-[60px] h-[60px]';
  } else if (effectiveNodeType === 'supporting') {
    markerSize = 24;
    visualWidth = 'w-[24px] h-[24px]';
    hitAreaSize = 'w-[40px] h-[40px]';
  }

  const markerHalf = markerSize / 2;
  const gradientId = `star-grad-${data.concept_id || Math.random().toString(36).slice(2, 7)}`;

  // Status visual tokens for tooltips & badges
  let statusText = 'Not assessed';
  let statusBadgeBg = 'bg-slate-800 text-slate-300 border-slate-700';

  if (isMastered) {
    statusText = 'Mastered';
    statusBadgeBg = 'bg-emerald-950/80 text-emerald-300 border-emerald-500/40';
  } else if (isLearning) {
    statusText = 'Learning';
    statusBadgeBg = 'bg-cyan-950/80 text-cyan-300 border-cyan-500/40';
  }

  // Dynamic Label Layout Styles
  let containerFlex = 'flex-row items-center';
  let labelMargin = 'ml-3 text-left';
  let labelMaxWidth = isCore ? 'max-w-[220px]' : 'max-w-[180px]';

  if (labelPosition === 'left') {
    containerFlex = 'flex-row-reverse items-center';
    labelMargin = 'mr-3 text-right';
  } else if (labelPosition === 'top') {
    containerFlex = 'flex-col-reverse items-center';
    labelMargin = 'mb-2 text-center';
    labelMaxWidth = 'max-w-[190px]';
  } else if (labelPosition === 'bottom') {
    containerFlex = 'flex-col items-center';
    labelMargin = 'mt-2 text-center';
    labelMaxWidth = 'max-w-[190px]';
  }

  return (
    <div
      onClick={(e) => {
        e.stopPropagation();
        onSelect(data);
      }}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      className={`group relative flex select-none cursor-pointer transition-all duration-300 ${containerFlex} ${
        isDimmed ? 'opacity-25' : 'opacity-100'
      }`}
    >
      {/* Visual Marker Container with Comfortable Click Hit Area */}
      <div className={`relative flex items-center justify-center shrink-0 ${hitAreaSize}`}>
        {/* React Flow Connection Handles Positioned at Star Center */}
        <Handle
          id="top"
          type="target"
          position={Position.Top}
          className="!w-1 !h-1 !bg-transparent !border-0 !opacity-0"
          style={{ top: `${markerHalf}px`, left: `${markerHalf}px` }}
        />
        <Handle
          id="top-src"
          type="source"
          position={Position.Top}
          className="!w-1 !h-1 !bg-transparent !border-0 !opacity-0"
          style={{ top: `${markerHalf}px`, left: `${markerHalf}px` }}
        />
        <Handle
          id="left"
          type="target"
          position={Position.Left}
          className="!w-1 !h-1 !bg-transparent !border-0 !opacity-0"
          style={{ top: `${markerHalf}px`, left: `${markerHalf}px` }}
        />
        <Handle
          id="left-src"
          type="source"
          position={Position.Left}
          className="!w-1 !h-1 !bg-transparent !border-0 !opacity-0"
          style={{ top: `${markerHalf}px`, left: `${markerHalf}px` }}
        />
        <Handle
          id="right"
          type="source"
          position={Position.Right}
          className="!w-1 !h-1 !bg-transparent !border-0 !opacity-0"
          style={{ top: `${markerHalf}px`, left: `${markerHalf}px` }}
        />
        <Handle
          id="right-tgt"
          type="target"
          position={Position.Right}
          className="!w-1 !h-1 !bg-transparent !border-0 !opacity-0"
          style={{ top: `${markerHalf}px`, left: `${markerHalf}px` }}
        />
        <Handle
          id="bottom"
          type="source"
          position={Position.Bottom}
          className="!w-1 !h-1 !bg-transparent !border-0 !opacity-0"
          style={{ top: `${markerHalf}px`, left: `${markerHalf}px` }}
        />
        <Handle
          id="bottom-tgt"
          type="target"
          position={Position.Bottom}
          className="!w-1 !h-1 !bg-transparent !border-0 !opacity-0"
          style={{ top: `${markerHalf}px`, left: `${markerHalf}px` }}
        />

        {/* Selected Concept Thin Outer Ring / Subtle Halo */}
        {isSelected && (
          <div
            className={`absolute rounded-full border-2 border-amber-400 shadow-[0_0_22px_rgba(245,158,11,0.65)] pointer-events-none transition-all duration-300 ${
              effectiveNodeType === 'core'
                ? 'w-[72px] h-[72px] -inset-[6px]'
                : effectiveNodeType === 'standard'
                ? 'w-[48px] h-[48px] -inset-[2px]'
                : 'w-[36px] h-[36px] inset-[2px]'
            }`}
          />
        )}

        {/* Recommended-Next Subtle Cyan Outer Halo */}
        {isRecommendedNext && !isSelected && (
          <div
            className={`absolute rounded-full border border-cyan-400/70 shadow-[0_0_16px_rgba(0,240,255,0.4)] pointer-events-none transition-all duration-300 ${
              effectiveNodeType === 'core'
                ? 'w-[70px] h-[70px] -inset-[5px]'
                : effectiveNodeType === 'standard'
                ? 'w-[46px] h-[46px] -inset-[1px]'
                : 'w-[34px] h-[34px] inset-[3px]'
            }`}
          />
        )}

        {/* Impacted Cascade Risk Halo (X-Ray Mode) */}
        {isImpacted && (
          <div
            className={`absolute rounded-full border-2 border-rose-500 shadow-[0_0_20px_rgba(244,63,94,0.7)] pointer-events-none animate-pulse ${
              effectiveNodeType === 'core'
                ? 'w-[72px] h-[72px] -inset-[6px]'
                : 'w-[48px] h-[48px] -inset-[2px]'
            }`}
          />
        )}

        {/* Topological Highlight Overlays (Prerequisite or Dependent of Selected Node) */}
        {(isPrerequisiteOfSelected || isDependentOfSelected) && !isSelected && (
          <div
            className={`absolute rounded-full pointer-events-none ${
              isPrerequisiteOfSelected
                ? 'border border-cyan-400/80 shadow-[0_0_14px_rgba(0,240,255,0.5)]'
                : 'border border-sky-400/70 shadow-[0_0_14px_rgba(56,189,248,0.4)]'
            } ${
              effectiveNodeType === 'core'
                ? 'w-[68px] h-[68px] -inset-[4px]'
                : 'w-[44px] h-[44px] inset-0'
            }`}
          />
        )}

        {/* ─────────────────────────────────────────────────────────────
            NODE VISUAL RENDERING: STARS (Core & Standard) OR CIRCLES (Supporting)
            ───────────────────────────────────────────────────────────── */}
        {effectiveNodeType === 'supporting' ? (
          /* Supporting Concept: Restrained Circular Marker with Concentric Core */
          <div
            className={`relative flex items-center justify-center rounded-full border transition-all duration-300 ${visualWidth} ${
              isMastered
                ? 'bg-gradient-to-br from-emerald-400 to-teal-700 border-emerald-300 shadow-[0_0_12px_rgba(16,185,129,0.4)]'
                : isLearning
                ? 'bg-gradient-to-b from-space-900 via-cyan-950 to-cyan-500 border-cyan-300 shadow-[0_0_12px_rgba(0,240,255,0.35)]'
                : 'bg-space-900/80 border-slate-600/80 shadow-sm'
            } group-hover:scale-110`}
          >
            {/* Inner Concentric Core Point */}
            <span
              className={`w-2 h-2 rounded-full ${
                isMastered ? 'bg-white shadow-[0_0_6px_#fff]' : isLearning ? 'bg-cyan-300 shadow-[0_0_6px_#00F0FF]' : 'bg-slate-400'
              }`}
            />
          </div>
        ) : (
          /* Core & Standard Concepts: Crisp 4-Point Celestial Geometric Star */
          <div
            className={`relative flex items-center justify-center transition-transform duration-300 group-hover:scale-105 ${visualWidth}`}
          >
            <svg
              viewBox="0 0 100 100"
              className="w-full h-full overflow-visible drop-shadow-[0_2px_8px_rgba(0,0,0,0.7)]"
            >
              <defs>
                {/* Mastered Star Gradient */}
                <linearGradient id={`${gradientId}-mastered`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#34D399" />
                  <stop offset="60%" stopColor="#10B981" />
                  <stop offset="100%" stopColor="#059669" />
                </linearGradient>

                {/* Progress-Responsive Two-Tone Split Fill for Learning State */}
                <linearGradient id={`${gradientId}-learning`} x1="0" y1="1" x2="0" y2="0">
                  <stop offset="0%" stopColor="#00F0FF" stopOpacity="0.95" />
                  <stop offset="52%" stopColor="#0284C7" stopOpacity="0.9" />
                  <stop offset="52%" stopColor="#0F172A" stopOpacity="0.75" />
                  <stop offset="100%" stopColor="#0A0F1D" stopOpacity="0.6" />
                </linearGradient>

                {/* Selected Star Warm Amber Gradient */}
                <linearGradient id={`${gradientId}-selected`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#FCD34D" />
                  <stop offset="100%" stopColor="#D97706" />
                </linearGradient>
              </defs>

              {/* Underlying Star Geometry */}
              <path
                d="M 50,4 C 50,34 66,50 96,50 C 66,50 50,66 50,96 C 50,66 34,50 4,50 C 34,50 50,34 50,4 Z"
                fill={
                  isSelected
                    ? `url(#${gradientId}-selected)`
                    : isMastered
                    ? `url(#${gradientId}-mastered)`
                    : isLearning
                    ? `url(#${gradientId}-learning)`
                    : 'rgba(15, 23, 42, 0.65)'
                }
                stroke={
                  isSelected
                    ? '#FDE68A'
                    : isImpacted
                    ? '#F43F5E'
                    : isMastered
                    ? '#6EE7B7'
                    : isLearning
                    ? '#38BDF8'
                    : 'rgba(148, 163, 184, 0.45)'
                }
                strokeWidth={effectiveNodeType === 'core' ? 2.5 : 2}
                strokeLinejoin="round"
                strokeLinecap="round"
              />

              {/* Subtle Core Star Luminous Center Pip */}
              {effectiveNodeType === 'core' && !isNotAssessed && (
                <circle
                  cx="50"
                  cy="50"
                  r="4.5"
                  fill="#FFFFFF"
                  opacity={isMastered ? 0.95 : 0.85}
                  className="filter drop-shadow-[0_0_4px_rgba(255,255,255,0.8)]"
                />
              )}
            </svg>
          </div>
        )}

        {/* ─────────────────────────────────────────────────────────────
            DIRECTLY RELATED STATE INDICATORS
            ───────────────────────────────────────────────────────────── */}

        {/* A. Mastered: Small Check Indicator Badge (Legible without overwhelming star) */}
        {isMastered && (
          <span
            className={`absolute -bottom-1 -right-1 rounded-full bg-emerald-600 border border-emerald-300 text-white flex items-center justify-center shadow-md z-10 ${
              effectiveNodeType === 'core' ? 'w-4 h-4' : 'w-3.5 h-3.5'
            }`}
            title="Mastered concept"
          >
            <Check className={`${effectiveNodeType === 'core' ? 'w-2.5 h-2.5' : 'w-2 h-2'} stroke-[3.5] text-white`} />
          </span>
        )}

        {/* B. Recommended Next: Small Recommendation Indicator Badge */}
        {isRecommendedNext && !isSelected && (
          <span
            className={`absolute -top-1.5 -right-1.5 rounded-full bg-cyan-400 text-space-950 flex items-center justify-center shadow-[0_0_10px_#00F0FF] z-10 ${
              effectiveNodeType === 'core' ? 'w-4 h-4' : 'w-3.5 h-3.5'
            }`}
            title="Recommended next learning step"
          >
            <Compass className={`${effectiveNodeType === 'core' ? 'w-2.5 h-2.5' : 'w-2 h-2'} stroke-[2.5]`} />
          </span>
        )}

        {/* Personal Note / Bookmark Badge */}
        {(isBookmarked || hasPersonalNote) && (
          <span
            className={`absolute ${
              isMastered ? '-bottom-1 -left-1' : '-bottom-1 -right-1'
            } w-3.5 h-3.5 rounded-full bg-amber-400 text-space-950 flex items-center justify-center shadow-[0_0_8px_#F59E0B] z-10`}
            title={hasPersonalNote ? 'Bookmarked with personal note' : 'Bookmarked concept'}
          >
            {hasPersonalNote ? (
              <MessageSquare className="w-2 h-2 fill-current" />
            ) : (
              <Bookmark className="w-2 h-2 fill-current" />
            )}
          </span>
        )}
      </div>

      {/* Glassmorphic Concept Label (Never obscured by crossing lines) */}
      <div
        className={`transition-colors duration-200 pointer-events-none ${labelMargin} ${labelMaxWidth}`}
      >
        <div className="inline-block bg-space-950/70 border border-white/[0.05] backdrop-blur-[3px] px-2 py-0.5 rounded-lg shadow-sm">
          <span
            className={`block leading-snug drop-shadow-[0_2px_4px_rgba(0,0,0,0.9)] ${isCore
                ? 'text-sm font-display font-bold text-white tracking-tight'
                : 'text-xs font-sans font-medium text-slate-100 group-hover:text-cyan-200'
              } ${isSelected ? '!text-amber-200 !font-bold' : ''}`}
          >
            {name}
          </span>

          {/* Learning Path Step Badge */}
          {isLearningPathActive && learningStep !== undefined && (
            <span className="inline-flex items-center gap-1 text-[9px] font-mono text-cyan-300 font-bold uppercase tracking-wider mt-0.5">
              <Route className="w-2.5 h-2.5 text-cyan-400" />
              <span>Step {learningStep}</span>
              {isTarget && <span className="text-amber-300 ml-1 font-bold">★ Up Next</span>}
            </span>
          )}

          {/* "Recommended next" label under concept title */}
          {!isLearningPathActive && isRecommendedNext && (
            <span className="inline-flex items-center gap-1 text-[9px] font-mono text-cyan-300 font-bold uppercase tracking-wider mt-0.5">
              <Compass className="w-2.5 h-2.5 text-cyan-400" />
              <span>Recommended next</span>
            </span>
          )}
        </div>
      </div>

      {/* Scientific Tooltip on Hover */}
      {isHovered && (
        <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-3 z-50 pointer-events-none w-64 p-3.5 rounded-2xl bg-space-900/95 border border-white/10 shadow-[0_16px_40px_rgba(0,0,0,0.9)] backdrop-blur-2xl animate-fade-in text-left">
          <div className="flex items-center justify-between gap-1 mb-1.5">
            <span className="text-[10px] font-mono text-cyan-400 font-bold uppercase tracking-wider truncate">
              {topicName || 'Concept'}
            </span>
            <span
              className={`text-[9px] font-mono font-bold px-1.5 py-0.5 rounded border ${statusBadgeBg}`}
            >
              {statusText}
            </span>
          </div>

          <h5 className="text-xs font-display font-bold text-white leading-snug mb-2">
            {name}
          </h5>

          {/* Recommendation Explanation */}
          {isRecommendedNext && recommendationReason && (
            <div className="mb-2 p-2 rounded-xl bg-cyan-950/80 border border-cyan-500/35 text-[10px] text-cyan-200 font-sans leading-relaxed">
              <strong className="font-semibold text-cyan-300 block mb-0.5 flex items-center gap-1 font-mono text-[9px] uppercase tracking-wider">
                <Compass className="w-2.5 h-2.5" /> Recommended Next:
              </strong>
              {recommendationReason}
            </div>
          )}

          {/* Personal Note Preview */}
          {personalNote && (
            <div className="mb-2 p-2 rounded-xl bg-amber-950/60 border border-amber-500/35 text-[10px] text-amber-200 font-sans leading-relaxed">
              <span className="font-semibold text-amber-300 block mb-0.5 font-mono text-[9px] uppercase tracking-wider flex items-center gap-1">
                <Bookmark className="w-2.5 h-2.5" /> Personal Note (Private):
              </span>
              "{personalNote}"
            </div>
          )}

          <div className="space-y-1.5 pt-1.5 border-t border-white/[0.08] text-[10px] font-mono text-slate-300">
            <div className="flex justify-between items-center">
              <span className="text-slate-400">Learner Mastery:</span>
              <span
                className={`font-bold ${isMastered ? 'text-emerald-400' : isLearning ? 'text-cyan-400' : 'text-slate-400'
                  }`}
              >
                {masteryPercent}%
              </span>
            </div>

            {isXRay && (
              <div className="flex justify-between items-center">
                <span className="text-slate-400">Uncertainty σ:</span>
                <span className="text-amber-400 font-bold">
                  {Math.round(uncertainty * 100)}%
                </span>
              </div>
            )}

            <div className="flex justify-between items-center">
              <span className="text-slate-400">Prerequisites:</span>
              <span className="text-white font-bold">{prerequisites.length} concepts</span>
            </div>

            {bloom_level && (
              <div className="flex justify-between items-center">
                <span className="text-slate-400">Cognitive Level:</span>
                <span className="text-purple-300 uppercase font-semibold">{bloom_level}</span>
              </div>
            )}
          </div>

          <div className="mt-2.5 pt-1.5 text-[9px] font-sans text-cyan-400/80 flex items-center justify-between border-t border-white/[0.05]">
            <span>Click to select concept</span>
            {isBookmarked && <span className="text-amber-400 font-mono text-[9px]">★ Bookmarked</span>}
          </div>
        </div>
      )}
    </div>
  );
});

CustomConceptNode.displayName = 'CustomConceptNode';
