import React, { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import {
  ReactFlow,
  useReactFlow,
  ReactFlowProvider,
  Background,
  MiniMap,
  MarkerType,
  BackgroundVariant,
} from '@xyflow/react';
import type { Node, Edge } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { ApiClient, type KnowledgeGraphData, type ConceptNode, type TopicTerritory, type LearningTarget, type LearningPathNode, type LearningSequenceResponse } from '../../api/client';
import { GuidedSequenceView } from './GuidedSequenceView';
import { CustomConceptNode } from './CustomConceptNode';
import type { ConceptNodeData } from './CustomConceptNode';
import { SubheadingNode } from './SubheadingNode';
import type { SubheadingNodeData } from './SubheadingNode';
import { TopicClusterNode } from './TopicClusterNode';
import type { TopicClusterNodeData } from './TopicClusterNode';
import { AnnotationStorage, type PersonalAnnotation } from '../../utils/annotationStorage';
import {
  determineNextBestSteps,
  detectMasteredChains,
  detectCrossSubjectDiscoveries,
  type NextBestStepRecommendation,
  type MasteredChain,
  type CrossSubjectDiscovery,
} from './atlasIntelligence';
import {
  Search,
  Filter,
  Eye,
  Network,
  GitBranch,
  Route,
  BookOpen,
  Plus,
  Minus,
  Maximize2,
  Minimize2,
  Crosshair,
  Compass,
  Bookmark,
  MessageSquare,
  Award,
  ArrowRight,
  ExternalLink,
  X,
  Sparkles,
  BookMarked,
  Check,
  Map as MapIcon,
} from 'lucide-react';

export type AtlasViewMode = 'GUIDED' | 'GRAPH' | 'CHAPTERS';

export interface LearningAtlasProps {
  graphData: KnowledgeGraphData;
  activeTargetId?: string;
  nextTarget?: LearningTarget | null;
  learningPathNodes?: LearningPathNode[];
  selectedTopicId?: string;
  selectedConceptId?: string;
  onSelectTopic?: (topic: TopicTerritory | null) => void;
  onSelectConcept: (concept: ConceptNode | null) => void;
  isXRayMode: boolean;
  onToggleXRay: () => void;
  impactedConceptIds?: string[];
  onTraceImpact?: (id: string) => void;
  onStartLearning?: (conceptId: string) => void;
  onStartPractice?: (conceptId: string) => void;
  learnerId?: string;
}

const nodeTypes = {
  conceptNode: CustomConceptNode,
  subheadingNode: SubheadingNode,
  topicCluster: TopicClusterNode,
};

// Controls Dock with MiniMap Toggle
const AtlasCanvasControls: React.FC<{
  isFullscreen: boolean;
  onToggleFullscreen: () => void;
  showMiniMap: boolean;
  onToggleMiniMap: () => void;
}> = ({ isFullscreen, onToggleFullscreen, showMiniMap, onToggleMiniMap }) => {
  const { zoomIn, zoomOut, fitView } = useReactFlow();

  return (
    <div className="absolute bottom-5 right-5 z-20 flex flex-col items-center bg-space-900/90 border border-white/[0.08] rounded-2xl p-1 shadow-2xl backdrop-blur-xl">
      <button
        type="button"
        onClick={() => zoomIn({ duration: 300 })}
        className="p-2 text-slate-300 hover:text-white hover:bg-white/[0.06] rounded-xl transition-colors cursor-pointer"
        title="Zoom In"
        aria-label="Zoom In"
      >
        <Plus className="w-4 h-4" />
      </button>
      <button
        type="button"
        onClick={() => zoomOut({ duration: 300 })}
        className="p-2 text-slate-300 hover:text-white hover:bg-white/[0.06] rounded-xl transition-colors cursor-pointer"
        title="Zoom Out"
        aria-label="Zoom Out"
      >
        <Minus className="w-4 h-4" />
      </button>
      <div className="w-4 h-px bg-white/[0.08] my-0.5" />
      <button
        type="button"
        onClick={() => fitView({ duration: 400, padding: 0.15 })}
        className="p-2 text-slate-300 hover:text-cyan-400 hover:bg-white/[0.06] rounded-xl transition-colors cursor-pointer"
        title="Reset & Center View"
        aria-label="Reset & Center View"
      >
        <Crosshair className="w-4 h-4" />
      </button>
      <button
        type="button"
        onClick={onToggleMiniMap}
        className={`p-2 rounded-xl transition-colors cursor-pointer ${
          showMiniMap ? 'text-cyan-400 bg-cyan-400/10' : 'text-slate-300 hover:text-white hover:bg-white/[0.06]'
        }`}
        title="Toggle Universe Radar (MiniMap)"
        aria-label="Toggle Radar"
      >
        <MapIcon className="w-4 h-4" />
      </button>
      <button
        type="button"
        onClick={onToggleFullscreen}
        className="p-2 text-slate-300 hover:text-cyan-400 hover:bg-white/[0.06] rounded-xl transition-colors cursor-pointer"
        title={isFullscreen ? 'Exit Fullscreen' : 'Fullscreen'}
        aria-label={isFullscreen ? 'Exit Fullscreen' : 'Fullscreen'}
      >
        {isFullscreen ? <Minimize2 className="w-4 h-4" /> : <Maximize2 className="w-4 h-4" />}
      </button>
    </div>
  );
};

// Chapter Quick Jump Strip inside Canvas
const ChapterQuickJumpStrip: React.FC<{
  topics: TopicTerritory[];
  selectedTopicId?: string;
  onSelectTopic: (topic: TopicTerritory) => void;
}> = ({ topics, selectedTopicId, onSelectTopic }) => {
  const { setCenter } = useReactFlow();

  const handleJump = (topic: TopicTerritory, idx: number) => {
    onSelectTopic(topic);
    const col = Math.floor(idx / 2);
    const row = idx % 2;
    const clusterCenterX = 300 + col * 740;
    const clusterCenterY = 320 + row * 580 + (col % 2) * 80;
    setCenter(clusterCenterX, clusterCenterY, { zoom: 0.9, duration: 600 });
  };

  return (
    <div className="absolute top-[72px] left-4 right-4 z-10 flex items-center gap-2 overflow-x-auto pb-1 scrollbar-none pointer-events-auto">
      <span className="text-[10px] font-mono text-slate-400 uppercase tracking-widest pl-1 shrink-0 font-bold flex items-center gap-1">
        <Compass className="w-3 h-3 text-cyan-400" /> Chapters:
      </span>
      {topics.map((t, idx) => {
        const isSelected = selectedTopicId === t.id;
        return (
          <button
            key={t.id}
            type="button"
            onClick={() => handleJump(t, idx)}
            className={`px-3 py-1 rounded-full text-xs font-mono font-medium whitespace-nowrap transition-all border cursor-pointer backdrop-blur-md ${
              isSelected
                ? 'bg-cyan-400 text-space-950 font-bold border-cyan-300 shadow-[0_0_12px_rgba(0,240,255,0.4)]'
                : 'bg-space-900/80 hover:bg-space-850 text-slate-300 border-white/[0.07] hover:border-cyan-400/50 hover:text-white'
            }`}
          >
            <span className="opacity-60 mr-1">CH{t.order < 10 ? `0${t.order}` : t.order}</span>
            <span>{t.name}</span>
          </button>
        );
      })}
    </div>
  );
};

export const LearningAtlas: React.FC<LearningAtlasProps> = ({
  graphData,
  activeTargetId,
  nextTarget,
  learningPathNodes = [],
  selectedTopicId,
  selectedConceptId,
  onSelectTopic,
  onSelectConcept,
  isXRayMode,
  onToggleXRay,
  impactedConceptIds = [],
  onTraceImpact,
  onStartLearning,
  onStartPractice,
  learnerId = 'learner_default',
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [filterTopic, setFilterTopic] = useState<string>('ALL');

  const [viewMode, setViewMode] = useState<AtlasViewMode>('GUIDED');
  const [selectedStartingConceptId, setSelectedStartingConceptId] = useState<string | null>(null);
  const [sequenceData, setSequenceData] = useState<LearningSequenceResponse | null>(null);
  const [isSequenceLoading, setIsSequenceLoading] = useState<boolean>(false);

  // Fetch academic chapter-coherent learning sequence from backend
  useEffect(() => {
    if (!graphData?.subject_id) return;
    let isMounted = true;
    setIsSequenceLoading(true);
    ApiClient.getLearningSequence(
      graphData.subject_id,
      selectedStartingConceptId || undefined,
      learnerId
    )
      .then((res) => {
        if (isMounted) {
          setSequenceData(res);
          setIsSequenceLoading(false);
        }
      })
      .catch((err) => {
        console.warn('Failed to fetch learning sequence:', err);
        if (isMounted) setIsSequenceLoading(false);
      });
    return () => {
      isMounted = false;
    };
  }, [graphData?.subject_id, selectedStartingConceptId, learnerId]);
  const [pathFilter, setPathFilter] = useState<'ALL' | 'PREREQUISITES' | 'LEARNING_PATH'>('ALL');
  const [showBookmarksOnly, setShowBookmarksOnly] = useState<boolean>(false);
  const [isFullscreen, setIsFullscreen] = useState<boolean>(false);
  const [showMiniMap, setShowMiniMap] = useState<boolean>(false);

  // ── Stable callback refs to prevent useMemo invalidation ──
  // These break the dependency chain: useMemo no longer depends on prop callbacks
  const onSelectTopicRef = useRef(onSelectTopic);
  onSelectTopicRef.current = onSelectTopic;
  const onSelectConceptRef = useRef(onSelectConcept);
  onSelectConceptRef.current = onSelectConcept;
  const onTraceImpactRef = useRef(onTraceImpact);
  onTraceImpactRef.current = onTraceImpact;

  // ── Personal Annotations State (Feature 2) ──
  const [annotations, setAnnotations] = useState<Record<string, PersonalAnnotation>>(() =>
    AnnotationStorage.getAll(learnerId)
  );
  const [editingNoteConceptId, setEditingNoteConceptId] = useState<string | null>(null);
  const [noteInputText, setNoteInputText] = useState<string>('');

  const [prevLearnerId, setPrevLearnerId] = useState(learnerId);
  if (prevLearnerId !== learnerId) {
    setPrevLearnerId(learnerId);
    setAnnotations(AnnotationStorage.getAll(learnerId));
  }

  // ── Evidence-Based Learning Chains State (Feature 3) ──
  const [highlightedChain, setHighlightedChain] = useState<MasteredChain | null>(null);
  const [dismissedChainIds, setDismissedChainIds] = useState<Set<string>>(() => new Set<string>());

  // ── Verified Cross-Subject Discovery Drawer (Feature 4) ──
  const [activeDiscovery, setActiveDiscovery] = useState<CrossSubjectDiscovery | null>(null);

  const toggleFullscreen = () => {
    if (!containerRef.current) return;
    if (!document.fullscreenElement) {
      containerRef.current.requestFullscreen().then(() => setIsFullscreen(true)).catch(() => {});
    } else {
      document.exitFullscreen().then(() => setIsFullscreen(false)).catch(() => {});
    }
  };

  // ── Pedagogical Intelligence Derivations ──

  // 1. Next Best Step Recommendations (Feature 1)
  const nextBestSteps = useMemo<NextBestStepRecommendation[]>(() => {
    return determineNextBestSteps(graphData, nextTarget, activeTargetId);
  }, [graphData, nextTarget, activeTargetId]);

  const recommendedConceptMap = useMemo(() => {
    const map = new Map<string, NextBestStepRecommendation>();
    nextBestSteps.forEach((rec) => map.set(rec.conceptId, rec));
    return map;
  }, [nextBestSteps]);

  // 2. Mastered Connected Chains (Feature 3)
  const masteredChains = useMemo<MasteredChain[]>(() => {
    return detectMasteredChains(graphData);
  }, [graphData]);

  const unacknowledgedChain = useMemo<MasteredChain | null>(() => {
    return masteredChains.find((c) => !dismissedChainIds.has(c.id)) || null;
  }, [masteredChains, dismissedChainIds]);

  // 3. Cross-Subject Discoveries (Feature 4)
  const crossSubjectDiscoveries = useMemo<CrossSubjectDiscovery[]>(() => {
    return detectCrossSubjectDiscoveries(graphData, selectedConceptId);
  }, [graphData, selectedConceptId]);

  // Find currently selected concept object if any
  const selectedConcept = useMemo(() => {
    if (!selectedConceptId) return null;
    return (graphData.concepts || []).find((c) => c.concept_id === selectedConceptId) || null;
  }, [graphData.concepts, selectedConceptId]);

  // Selected concept's annotation
  const selectedConceptAnnotation = useMemo(() => {
    if (!selectedConceptId) return null;
    return annotations[selectedConceptId] || null;
  }, [selectedConceptId, annotations]);

  // Selected concept's recommendation if it is a Next Best Step
  const selectedConceptRecommendation = useMemo(() => {
    if (!selectedConceptId) return null;
    return recommendedConceptMap.get(selectedConceptId) || null;
  }, [selectedConceptId, recommendedConceptMap]);

  // Handle bookmark toggle
  const handleToggleBookmark = useCallback(
    (conceptId: string) => {
      const current = annotations[conceptId];
      const isCurrentlyBookmarked = Boolean(current?.isBookmarked);
      const updated = AnnotationStorage.save(learnerId, conceptId, {
        isBookmarked: !isCurrentlyBookmarked,
      });
      setAnnotations((prev) => ({ ...prev, [conceptId]: updated }));
    },
    [learnerId, annotations]
  );

  // Handle saving note
  const handleSaveNote = useCallback(
    (conceptId: string, noteText: string) => {
      const updated = AnnotationStorage.save(learnerId, conceptId, {
        note: noteText,
      });
      setAnnotations((prev) => ({ ...prev, [conceptId]: updated }));
      setEditingNoteConceptId(null);
      setNoteInputText('');
    },
    [learnerId]
  );

  // Handle removing note
  const handleRemoveNote = useCallback(
    (conceptId: string) => {
      const updated = AnnotationStorage.save(learnerId, conceptId, {
        note: '',
      });
      setAnnotations((prev) => ({ ...prev, [conceptId]: updated }));
      setEditingNoteConceptId(null);
      setNoteInputText('');
    },
    [learnerId]
  );

  // O(1) concept lookup map (avoid repeated .find() in BFS traversals)
  const conceptLookupMap = useMemo(() => {
    const map = new Map<string, ConceptNode>();
    (graphData.concepts || []).forEach((c) => map.set(c.concept_id, c));
    return map;
  }, [graphData.concepts]);

  // Compute set of all direct prerequisites and dependents of selected concept
  const { prereqIdsOfSelected, dependentIdsOfSelected, activePathConceptIds } = useMemo(() => {
    const prereqSet = new Set<string>();
    const depSet = new Set<string>();
    const pathSet = new Set<string>();

    if (selectedConceptId) {
      pathSet.add(selectedConceptId);

      // BFS using Map for O(1) lookups instead of O(N) .find()
      const queue = [selectedConceptId];
      while (queue.length > 0) {
        const currId = queue.shift()!;
        const c = conceptLookupMap.get(currId);
        if (c && c.prerequisites) {
          c.prerequisites.forEach((pId) => {
            if (!prereqSet.has(pId)) {
              prereqSet.add(pId);
              pathSet.add(pId);
              queue.push(pId);
            }
          });
        }
      }

      conceptLookupMap.forEach((c) => {
        if ((c.prerequisites || []).includes(selectedConceptId)) {
          depSet.add(c.concept_id);
          pathSet.add(c.concept_id);
        }
      });
      if (selectedConcept?.dependents) {
        selectedConcept.dependents.forEach((dId) => {
          depSet.add(dId);
          pathSet.add(dId);
        });
      }
    }

    if (activeTargetId && pathFilter === 'LEARNING_PATH') {
      pathSet.add(activeTargetId);
      const queue = [activeTargetId];
      while (queue.length > 0) {
        const currId = queue.shift()!;
        const c = conceptLookupMap.get(currId);
        if (c && c.prerequisites) {
          c.prerequisites.forEach((pId) => {
            if (!pathSet.has(pId)) {
              pathSet.add(pId);
              queue.push(pId);
            }
          });
        }
      }
    }

    return {
      prereqIdsOfSelected: prereqSet,
      dependentIdsOfSelected: depSet,
      activePathConceptIds: pathSet,
    };
  }, [conceptLookupMap, selectedConceptId, selectedConcept, activeTargetId, pathFilter]);

  // ── Ordered Learning Path Sequence ──
  const orderedLearningPathIds = useMemo<string[]>(() => {
    if (sequenceData?.sequence && sequenceData.sequence.length > 0) {
      return sequenceData.sequence.map((n) => n.concept_id);
    }
    if (learningPathNodes && learningPathNodes.length > 0) {
      return learningPathNodes.map((n) => n.concept_id);
    }
    const concepts = graphData?.concepts || [];
    if (concepts.length === 0) return [];

    const conceptIds = concepts.map((c) => c.concept_id);
    const inDegree: Record<string, number> = {};
    const adj: Record<string, string[]> = {};
    conceptIds.forEach((id) => {
      inDegree[id] = 0;
      adj[id] = [];
    });

    concepts.forEach((c) => {
      (c.prerequisites || []).forEach((pId) => {
        if (adj[pId]) {
          adj[pId].push(c.concept_id);
          inDegree[c.concept_id] = (inDegree[c.concept_id] || 0) + 1;
        }
      });
    });

    const topicOrderMap = new Map<string, number>();
    (graphData?.topics || []).forEach((t, idx) => {
      topicOrderMap.set(t.id, t.order ?? idx);
    });

    const ready: string[] = conceptIds.filter((id) => inDegree[id] === 0);
    const sortReady = (arr: string[]) => {
      arr.sort((a, b) => {
        const cA = conceptLookupMap.get(a);
        const cB = conceptLookupMap.get(b);
        const tA = cA?.topic_id ? (topicOrderMap.get(cA.topic_id) ?? 999) : 999;
        const tB = cB?.topic_id ? (topicOrderMap.get(cB.topic_id) ?? 999) : 999;
        return tA - tB;
      });
    };
    sortReady(ready);

    const result: string[] = [];
    while (ready.length > 0) {
      const curr = ready.shift()!;
      result.push(curr);
      for (const nxt of adj[curr] || []) {
        inDegree[nxt]--;
        if (inDegree[nxt] === 0) {
          ready.push(nxt);
          sortReady(ready);
        }
      }
    }

    if (result.length < conceptIds.length) {
      conceptIds.forEach((id) => {
        if (!result.includes(id)) result.push(id);
      });
    }

    return result;
  }, [learningPathNodes, graphData, conceptLookupMap]);

  const learningPathStepMap = useMemo(() => {
    const map = new Map<string, number>();
    if (sequenceData?.sequence && sequenceData.sequence.length > 0) {
      sequenceData.sequence.forEach((s) => {
        map.set(s.concept_id, s.step_number);
      });
      return map;
    }
    orderedLearningPathIds.forEach((id, idx) => {
      map.set(id, idx + 1);
    });
    return map;
  }, [sequenceData, orderedLearningPathIds]);

  // ─────────────────────────────────────────────────────────────
  // 1. COLLISION-FREE RADIAL CONSTELLATION NODE GENERATION
  // ─────────────────────────────────────────────────────────────
  const initialNodes: Node[] = useMemo(() => {
    const qLower = searchQuery.toLowerCase().trim();
    const posMap = new Map<string, { x: number; y: number }>();

    // ── CHAPTERS / SUBHEADINGS VIEW ──
    if (viewMode === 'CHAPTERS') {
      const filteredTopics = (graphData.topics || []).filter((topic) => {
        if (!qLower) return true;
        const matchesName = topic.name.toLowerCase().includes(qLower);
        const matchesConcepts = (topic.concepts || []).some(
          (c) => c.name.toLowerCase().includes(qLower) || (c.definition || '').toLowerCase().includes(qLower)
        );
        return matchesName || matchesConcepts;
      });

      const total = filteredTopics.length;
      const cols = total <= 4 ? 2 : total <= 9 ? 3 : 4;

      return filteredTopics.map((topic, index) => {
        const col = index % cols;
        const row = Math.floor(index / cols);
        const x = 160 + col * 400;
        const y = 160 + row * 270;
        posMap.set(topic.id, { x, y });

        const isTarget = (topic.concept_ids || []).includes(activeTargetId || '') || topic.id === activeTargetId;
        const isSelected = topic.id === selectedTopicId;
        const isImpacted = impactedConceptIds.includes(topic.id);

        return {
          id: topic.id,
          type: 'subheadingNode',
          position: { x, y },
          data: {
            ...topic,
            isTarget,
            isSelected,
            isImpacted,
            isXRay: isXRayMode,
            zoomLevel: 3,
            onSelect: (t: TopicTerritory) => {
              if (onSelectTopicRef.current) onSelectTopicRef.current(t);
            },
            onTraceImpact: onTraceImpactRef.current,
          } as SubheadingNodeData,
        };
      });
    }

    // ── GRAPH VIEW: TOPIC CLUSTERS + CIRCULAR CONCEPT CONSTELLATIONS ──
    const nodesRes: Node[] = [];

    const conceptsByTopic: Record<string, ConceptNode[]> = {};
    (graphData.concepts || []).forEach((c) => {
      const tId = c.topic_id || 'general';
      if (!conceptsByTopic[tId]) conceptsByTopic[tId] = [];
      conceptsByTopic[tId].push(c);
    });

    const topicsToDisplay = (graphData.topics || []).filter((topic) => {
      if (filterTopic !== 'ALL' && topic.id !== filterTopic) return false;
      return true;
    });

    const effectiveTopics: TopicTerritory[] =
      topicsToDisplay.length > 0
        ? topicsToDisplay
        : [
            {
              id: 'general',
              name: 'Core Curriculum',
              order: 1,
              concepts: graphData.concepts || [],
            },
          ];

    // Layout topic clusters with generous spacing (no collisions!)
    effectiveTopics.forEach((topic, topicIdx) => {
      const topicConcepts = conceptsByTopic[topic.id] || topic.concepts || [];
      if (topicConcepts.length === 0) return;

      const col = Math.floor(topicIdx / 2);
      const row = topicIdx % 2;
      const clusterCenterX = 300 + col * 740;
      const clusterCenterY = 320 + row * 580 + (col % 2) * 80;

      // Identify Core Concept
      const coreConcept =
        topicConcepts.find(
          (c) =>
            c.name.toLowerCase() === topic.name.toLowerCase() ||
            topic.name.toLowerCase().includes(c.name.toLowerCase())
        ) || topicConcepts[0];

      // Secondary concepts
      const secondaryConcepts = topicConcepts.filter((c) => c.concept_id !== coreConcept.concept_id);
      const numSecondary = secondaryConcepts.length;

      // Dynamic radial radius depending on concept count
      const orbitRadius = numSecondary <= 3 ? 150 : numSecondary <= 6 ? 180 : 210;

      const coords: { x: number; y: number }[] = [];
      coords.push({ x: clusterCenterX, y: clusterCenterY });
      posMap.set(coreConcept.concept_id, { x: clusterCenterX, y: clusterCenterY });

      // Calculate radial positions and assign optimal label positions
      const secondaryPositions = secondaryConcepts.map((secConcept, secIdx) => {
        const angle = (secIdx * (2 * Math.PI)) / Math.max(1, numSecondary) - Math.PI / 2;
        const posX = clusterCenterX + orbitRadius * Math.cos(angle);
        const posY = clusterCenterY + orbitRadius * Math.sin(angle);
        coords.push({ x: posX, y: posY });
        posMap.set(secConcept.concept_id, { x: posX, y: posY });

        // Normalize angle to [0, 2pi) to determine label direction
        const normAngle = ((angle % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI);
        let labelPosition: 'right' | 'left' | 'top' | 'bottom' = 'right';

        if (normAngle >= 1.75 * Math.PI || normAngle <= 0.25 * Math.PI) {
          labelPosition = 'top';
        } else if (normAngle > 0.25 * Math.PI && normAngle < 0.75 * Math.PI) {
          labelPosition = 'right';
        } else if (normAngle >= 0.75 * Math.PI && normAngle <= 1.25 * Math.PI) {
          labelPosition = 'bottom';
        } else {
          labelPosition = 'left';
        }

        return { concept: secConcept, posX, posY, labelPosition };
      });

      // Compute generous cluster bounding box
      let minX = Infinity;
      let maxX = -Infinity;
      let minY = Infinity;
      let maxY = -Infinity;

      coords.forEach((p) => {
        if (p.x < minX) minX = p.x;
        if (p.x > maxX) maxX = p.x;
        if (p.y < minY) minY = p.y;
        if (p.y > maxY) maxY = p.y;
      });

      const clusterPaddingX = 100;
      const clusterPaddingY = 70;
      const hullX = minX - clusterPaddingX;
      const hullY = minY - clusterPaddingY;
      const hullWidth = maxX - minX + clusterPaddingX * 2 + 80;
      const hullHeight = maxY - minY + clusterPaddingY * 2;

      const isTopicFocused = selectedTopicId === topic.id;
      const isTopicDimmed =
        (selectedConceptId &&
          !activePathConceptIds.has(coreConcept.concept_id) &&
          !topicConcepts.some((c) => activePathConceptIds.has(c.concept_id))) ||
        (filterTopic !== 'ALL' && filterTopic !== topic.id);

      // 1. Topic Cluster Hull Node (Behind nodes, zIndex: -1)
      nodesRes.push({
        id: `cluster-${topic.id}`,
        type: 'topicCluster',
        position: { x: hullX, y: hullY },
        data: {
          topic,
          colorIndex: topicIdx,
          width: hullWidth,
          height: hullHeight,
          isFocused: isTopicFocused,
          isDimmed: Boolean(isTopicDimmed),
          onSelectTopic: (t: TopicTerritory) => {
            if (onSelectTopicRef.current) onSelectTopicRef.current(t);
          },
        } as TopicClusterNodeData,
        draggable: false,
        selectable: false,
        focusable: false,
        zIndex: -1,
      });

      // Helper to generate ConceptNode
      const createConceptNode = (
        concept: ConceptNode,
        posX: number,
        posY: number,
        isCore: boolean,
        labelPosition: 'right' | 'left' | 'top' | 'bottom' = 'right'
      ) => {
        const matchesSearch =
          !qLower ||
          concept.name.toLowerCase().includes(qLower) ||
          (concept.definition || '').toLowerCase().includes(qLower);

        const annotation = annotations[concept.concept_id];
        const isBookmarked = Boolean(annotation?.isBookmarked);
        const hasPersonalNote = Boolean(annotation?.note);
        const personalNote = annotation?.note;

        const rec = recommendedConceptMap.get(concept.concept_id);
        const isRecommendedNext = Boolean(rec);
        const recommendationReason = rec?.reason;

        const isSelected = concept.concept_id === selectedConceptId;
        const isTarget = concept.concept_id === activeTargetId;
        const isImpacted = impactedConceptIds.includes(concept.concept_id);
        const isPrereq = prereqIdsOfSelected.has(concept.concept_id);
        const isDep = dependentIdsOfSelected.has(concept.concept_id);

        let isDimmed = false;
        if (!matchesSearch) {
          isDimmed = true;
        } else if (showBookmarksOnly && !isBookmarked && !hasPersonalNote) {
          isDimmed = true;
        } else if (highlightedChain) {
          isDimmed = !highlightedChain.conceptIds.includes(concept.concept_id);
        } else if (selectedStartingConceptId && sequenceData?.sequence) {
          const inActiveSequence = sequenceData.sequence.some((s) => s.concept_id === concept.concept_id);
          if (!inActiveSequence && !isSelected) {
            isDimmed = true;
          }
        } else if (selectedConceptId) {
          isDimmed = !isSelected && !isPrereq && !isDep && !activePathConceptIds.has(concept.concept_id);
        }

        return {
          id: concept.concept_id,
          type: 'conceptNode',
          position: { x: posX, y: posY },
          data: {
            ...concept,
            isCore,
            labelPosition,
            isTarget,
            isRecommendedNext,
            recommendationReason,
            isBookmarked,
            hasPersonalNote,
            personalNote,
            isSelected,
            isImpacted,
            isPrerequisiteOfSelected: isPrereq,
            isDependentOfSelected: isDep,
            isDimmed,
            isXRay: isXRayMode,
            topicName: topic.name,
            learningStep: learningPathStepMap.get(concept.concept_id),
            isLearningPathActive: pathFilter === 'LEARNING_PATH',
            zoomLevel: 3,
            onSelect: (c: ConceptNode) => {
              onSelectConceptRef.current(c);
            },
          } as ConceptNodeData,
          zIndex: isSelected ? 30 : isRecommendedNext ? 25 : isCore ? 20 : 10,
        };
      };

      // 2. Core Concept Node
      nodesRes.push(createConceptNode(coreConcept, clusterCenterX, clusterCenterY, true, 'right'));

      // 3. Secondary Concept Nodes
      secondaryPositions.forEach(({ concept, posX, posY, labelPosition }) => {
        nodesRes.push(createConceptNode(concept, posX, posY, false, labelPosition));
      });
    });

    return nodesRes;
  }, [
    viewMode,
    graphData.topics,
    graphData.concepts,
    searchQuery,
    filterTopic,
    selectedTopicId,
    selectedConceptId,
    activeTargetId,
    impactedConceptIds,
    isXRayMode,
    pathFilter,
    learningPathStepMap,
    showBookmarksOnly,
    highlightedChain,
    annotations,
    recommendedConceptMap,
    activePathConceptIds,
    prereqIdsOfSelected,
    dependentIdsOfSelected,
    // Callbacks removed — stabilized via refs to prevent recomputation
  ]);

  // Pure position map derived from initialNodes for optimal edge handle selection
  const nodePositionMap = useMemo(() => {
    const map = new Map<string, { x: number; y: number }>();
    initialNodes.forEach((n) => {
      map.set(n.id, { x: n.position.x, y: n.position.y });
    });
    return map;
  }, [initialNodes]);

  // ─────────────────────────────────────────────────────────────
  // 2. SMOOTH BEZIER ENERGY CONDUIT EDGES
  // ─────────────────────────────────────────────────────────────
  const initialEdges: Edge[] = useMemo(() => {
    const edgesRes: Edge[] = [];
    const seenEdges = new Set<string>();
    const visibleNodeIds = new Set(initialNodes.map((n) => n.id));
    const posMap = nodePositionMap;

    const isLearningPathFilter = pathFilter === 'LEARNING_PATH';

    const addEdge = (
      src: string,
      tgt: string,
      edgeType: 'prerequisite' | 'related' | 'part_of' | 'learning_step' = 'prerequisite'
    ) => {
      const edgeKey = `${src}->${tgt}:${edgeType}`;
      if (seenEdges.has(edgeKey) || src === tgt) return;
      if (!visibleNodeIds.has(src) || !visibleNodeIds.has(tgt)) return;
      seenEdges.add(edgeKey);

      const isSrcImpacted = impactedConceptIds.includes(src);
      const isTgtImpacted = impactedConceptIds.includes(tgt);
      const isCascade = isSrcImpacted && isTgtImpacted;

      const isChainEdge =
        highlightedChain &&
        highlightedChain.conceptIds.includes(src) &&
        highlightedChain.conceptIds.includes(tgt);

      const isDirectPrereqEdge = selectedConceptId === tgt && prereqIdsOfSelected.has(src);
      const isDirectDepEdge = selectedConceptId === src && dependentIdsOfSelected.has(tgt);
      const isOnActivePrereqPath = activePathConceptIds.has(src) && activePathConceptIds.has(tgt);
      const isLearningStepEdge = edgeType === 'learning_step';

      const srcConcept = conceptLookupMap.get(src);
      const tgtConcept = conceptLookupMap.get(tgt);
      const isCrossChapter = Boolean(
        srcConcept?.topic_id && tgtConcept?.topic_id && srcConcept.topic_id !== tgtConcept.topic_id
      );

      // Filtering semantics:
      // In PREREQUISITES mode, show all structural prerequisite relationships
      if (pathFilter === 'PREREQUISITES' && edgeType !== 'prerequisite') return;

      // In LEARNING_PATH mode, show prerequisite edges and sequential learning progression edges.
      // Filter out internal cluster part_of edges to keep focus on the progression sequence.
      if (pathFilter === 'LEARNING_PATH' && edgeType === 'part_of') return;

      const isHighlightPath =
        isDirectPrereqEdge ||
        isDirectDepEdge ||
        (isOnActivePrereqPath && Boolean(selectedConceptId || activeTargetId)) ||
        (isLearningPathFilter && isLearningStepEdge);

      const hasSelection = Boolean(selectedConceptId) || Boolean(highlightedChain);
      const isDimmed = hasSelection && !isHighlightPath && !isChainEdge;

      // Determine optimal handles based on relative geometry
      const srcPos = posMap.get(src);
      const tgtPos = posMap.get(tgt);
      let sourceHandle = 'right';
      let targetHandle = 'left';

      if (srcPos && tgtPos) {
        const dx = tgtPos.x - srcPos.x;
        const dy = tgtPos.y - srcPos.y;
        if (Math.abs(dx) > Math.abs(dy)) {
          sourceHandle = dx > 0 ? 'right' : 'left-src';
          targetHandle = dx > 0 ? 'left' : 'right-tgt';
        } else {
          sourceHandle = dy > 0 ? 'bottom' : 'top-src';
          targetHandle = dy > 0 ? 'top' : 'bottom-tgt';
        }
      }

      // Edge Styling
      let strokeColor = 'rgba(148, 163, 184, 0.35)';
      let strokeWidth = 1.4;
      let strokeDasharray: string | undefined = undefined;
      let animated = false;

      if (isCascade) {
        strokeColor = '#F43F5E';
        strokeWidth = 3.0;
        animated = true;
      } else if (isChainEdge) {
        strokeColor = '#10B981';
        strokeWidth = 3.2;
        animated = true;
      } else if (isLearningStepEdge) {
        strokeColor = isDimmed ? 'rgba(0, 240, 255, 0.3)' : '#00F0FF';
        strokeWidth = isDimmed ? 1.8 : 3.2;
        strokeDasharray = '8 4';
        animated = true;
      } else if (isHighlightPath) {
        strokeColor = isDirectDepEdge ? '#38BDF8' : '#00F0FF';
        strokeWidth = 3.2;
        animated = true;
      } else if (edgeType === 'prerequisite') {
        if (isCrossChapter) {
          strokeColor = isDimmed ? 'rgba(168, 85, 247, 0.25)' : '#A855F7';
          strokeWidth = isDimmed ? 1.0 : 2.2;
        } else if (isLearningPathFilter) {
          strokeColor = isDimmed ? 'rgba(51, 65, 85, 0.2)' : 'rgba(56, 189, 248, 0.65)';
          strokeWidth = isDimmed ? 1.0 : 1.8;
        } else {
          strokeColor = isDimmed ? 'rgba(51, 65, 85, 0.15)' : 'rgba(100, 116, 139, 0.45)';
          strokeWidth = isDimmed ? 0.9 : 1.4;
        }
      } else if (edgeType === 'part_of') {
        strokeColor = isDimmed ? 'rgba(51, 65, 85, 0.15)' : 'rgba(148, 163, 184, 0.3)';
        strokeWidth = 1.2;
        strokeDasharray = '4 4';
      } else {
        strokeColor = isDimmed ? 'rgba(51, 65, 85, 0.15)' : 'rgba(148, 163, 184, 0.35)';
        strokeWidth = 1.2;
      }

      edgesRes.push({
        id: `e-${src}-${tgt}-${edgeType}`,
        source: src,
        target: tgt,
        sourceHandle,
        targetHandle,
        type: 'default', // Smooth organic Bezier curves
        animated,
        style: {
          stroke: strokeColor,
          strokeWidth,
          strokeDasharray,
          filter: isChainEdge
            ? 'drop-shadow(0 0 10px rgba(16,185,129,0.85))'
            : isHighlightPath
            ? 'drop-shadow(0 0 10px rgba(0,240,255,0.85))'
            : isLearningStepEdge
            ? 'drop-shadow(0 0 8px rgba(0,240,255,0.75))'
            : undefined,
          transition: 'all 0.3s ease',
        },
        markerEnd: {
          type: MarkerType.ArrowClosed,
          color: strokeColor,
          width: isChainEdge || isHighlightPath || isLearningStepEdge ? 18 : 13,
          height: isChainEdge || isHighlightPath || isLearningStepEdge ? 18 : 13,
        },
        zIndex: isChainEdge ? 30 : isHighlightPath ? 25 : isLearningStepEdge ? 20 : 1,
      });
    };

    if (viewMode === 'CHAPTERS') {
      (graphData.topics || []).forEach((topic) => {
        (topic.prerequisites || []).forEach((prereqId) => {
          addEdge(prereqId, topic.id, 'prerequisite');
        });
      });

      (graphData.topic_relationships || []).forEach((rel) => {
        const type = rel.type === 'prerequisite' ? 'prerequisite' : 'related';
        addEdge(rel.source, rel.target, type);
      });
    } else {
      (graphData.concepts || []).forEach((concept) => {
        (concept.prerequisites || []).forEach((prereqId) => {
          addEdge(prereqId, concept.concept_id, 'prerequisite');
        });
      });

      (graphData.relationships || []).forEach((rel) => {
        const relType =
          rel.type === 'prerequisite' ? 'prerequisite' : rel.type === 'part_of' ? 'part_of' : 'related';
        addEdge(rel.source, rel.target, relType);
      });

      // Internal Cluster Hierarchical Edges
      (graphData.topics || []).forEach((topic) => {
        const topicConcepts = (graphData.concepts || []).filter((c) => (c.topic_id || 'general') === topic.id);
        if (topicConcepts.length > 1) {
          const coreConcept =
            topicConcepts.find(
              (c) =>
                c.name.toLowerCase() === topic.name.toLowerCase() ||
                topic.name.toLowerCase().includes(c.name.toLowerCase())
            ) || topicConcepts[0];

          topicConcepts.forEach((sec) => {
            if (sec.concept_id !== coreConcept.concept_id) {
              const hasExistingLink = (graphData.relationships || []).some(
                (r) =>
                  (r.source === coreConcept.concept_id && r.target === sec.concept_id) ||
                  (r.source === sec.concept_id && r.target === coreConcept.concept_id)
              );
              if (!hasExistingLink && !sec.prerequisites.includes(coreConcept.concept_id)) {
                addEdge(coreConcept.concept_id, sec.concept_id, 'part_of');
              }
            }
          });
        }
      });

      // In LEARNING_PATH mode: generate sequential trajectory step edges between ordered learning path nodes
      if (pathFilter === 'LEARNING_PATH' && orderedLearningPathIds.length > 1) {
        for (let i = 0; i < orderedLearningPathIds.length - 1; i++) {
          const sId = orderedLearningPathIds[i];
          const tId = orderedLearningPathIds[i + 1];
          addEdge(sId, tId, 'learning_step');
        }
      }
    }

    return edgesRes;
  }, [
    viewMode,
    graphData.topics,
    graphData.topic_relationships,
    graphData.concepts,
    graphData.relationships,
    initialNodes,
    selectedConceptId,
    activeTargetId,
    pathFilter,
    highlightedChain,
    activePathConceptIds,
    prereqIdsOfSelected,
    dependentIdsOfSelected,
    impactedConceptIds,
    nodePositionMap,
    orderedLearningPathIds,
  ]);

  // Controlled mode: ReactFlow receives nodes/edges directly from useMemo.
  // No-op change handlers — we don't need ReactFlow's internal state management.
  const handleNodesChange = useCallback(() => {}, []);
  const handleEdgesChange = useCallback(() => {}, []);

  const handlePaneClick = useCallback(() => {
    onSelectConcept(null);
    if (onSelectTopic) onSelectTopic(null);
    setHighlightedChain(null);
    setActiveDiscovery(null);
  }, [onSelectConcept, onSelectTopic]);

  const bookmarkedCount = useMemo(() => {
    return Object.values(annotations).filter((a) => a.isBookmarked || a.note).length;
  }, [annotations]);

  return (
    <div
      ref={containerRef}
      className={`relative w-full rounded-3xl border border-white/[0.08] bg-[#050811] overflow-hidden shadow-[0_24px_64px_rgba(0,0,0,0.9)] transition-all ${
        isFullscreen ? 'h-screen fixed inset-0 z-50 rounded-none' : 'h-[740px]'
      }`}
    >
      <ReactFlowProvider>
        {/* Floating Top Control HUD */}
        <div className="absolute top-3 left-4 right-4 z-20 flex flex-wrap items-center justify-between gap-3 p-2.5 rounded-2xl bg-space-900/90 border border-white/[0.08] backdrop-blur-xl shadow-xl">
          <div className="flex flex-wrap items-center gap-2.5">
            {/* View Mode Switcher Pills */}
            <div className="flex items-center p-1 rounded-xl bg-space-950/80 border border-white/[0.08]">
              <button
                type="button"
                onClick={() => setViewMode('GUIDED')}
                className={`px-3 py-1.5 rounded-lg text-xs font-mono font-bold flex items-center gap-1.5 transition-all cursor-pointer ${
                  viewMode === 'GUIDED'
                    ? 'bg-cyan-400 text-space-950 shadow-[0_0_16px_rgba(0,240,255,0.4)]'
                    : 'text-slate-400 hover:text-white'
                }`}
              >
                <Route className="w-3.5 h-3.5" />
                <span>Guided Sequence</span>
              </button>
              <button
                type="button"
                onClick={() => setViewMode('GRAPH')}
                className={`px-3 py-1.5 rounded-lg text-xs font-mono font-bold flex items-center gap-1.5 transition-all cursor-pointer ${
                  viewMode === 'GRAPH'
                    ? 'bg-cyan-400 text-space-950 shadow-[0_0_16px_rgba(0,240,255,0.4)]'
                    : 'text-slate-400 hover:text-white'
                }`}
              >
                <Network className="w-3.5 h-3.5" />
                <span>Interactive Graph</span>
              </button>
              <button
                type="button"
                onClick={() => setViewMode('CHAPTERS')}
                className={`px-3 py-1.5 rounded-lg text-xs font-mono font-bold flex items-center gap-1.5 transition-all cursor-pointer ${
                  viewMode === 'CHAPTERS'
                    ? 'bg-cyan-400 text-space-950 shadow-[0_0_16px_rgba(0,240,255,0.4)]'
                    : 'text-slate-400 hover:text-white'
                }`}
              >
                <BookOpen className="w-3.5 h-3.5" />
                <span>Chapter View ({graphData.topics?.length || 0})</span>
              </button>
            </div>

            {/* Starting Concept Selector (Interactive Graph Mode) */}
            {viewMode === 'GRAPH' && (
              <div className="hidden lg:flex items-center gap-1.5 bg-space-950/80 px-2.5 py-1 rounded-xl border border-white/[0.08] text-xs">
                <Compass className="w-3.5 h-3.5 text-cyan-400 shrink-0" />
                <select
                  value={selectedStartingConceptId || ''}
                  onChange={(e) => setSelectedStartingConceptId(e.target.value || null)}
                  className="bg-transparent text-slate-200 text-xs focus:outline-none cursor-pointer pr-1 font-sans max-w-[170px] truncate"
                  aria-label="Select starting concept"
                >
                  <option value="" className="bg-space-900 text-white">
                    Start: All Curriculum
                  </option>
                  {(graphData.concepts || []).map((c) => (
                    <option key={c.concept_id} value={c.concept_id} className="bg-space-900 text-white">
                      Start: {c.name}
                    </option>
                  ))}
                </select>
                {selectedStartingConceptId && (
                  <button
                    type="button"
                    onClick={() => setSelectedStartingConceptId(null)}
                    className="text-slate-400 hover:text-white text-xs p-0.5"
                    title="Reset to full curriculum"
                  >
                    <X className="w-3 h-3" />
                  </button>
                )}
              </div>
            )}

            {/* Path Filter Toggles */}
            {viewMode === 'GRAPH' && (
              <div className="hidden sm:flex items-center p-1 rounded-xl bg-space-950/80 border border-white/[0.08]">
                <button
                  type="button"
                  onClick={() => setPathFilter(pathFilter === 'PREREQUISITES' ? 'ALL' : 'PREREQUISITES')}
                  className={`px-2.5 py-1.5 rounded-lg text-xs font-mono font-medium flex items-center gap-1.5 transition-all cursor-pointer ${
                    pathFilter === 'PREREQUISITES'
                      ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-400/40'
                      : 'text-slate-400 hover:text-white'
                  }`}
                  title="Filter to prerequisite paths only"
                >
                  <GitBranch className="w-3.5 h-3.5" />
                  <span>Prerequisite Paths</span>
                </button>
                <button
                  type="button"
                  onClick={() => setPathFilter(pathFilter === 'LEARNING_PATH' ? 'ALL' : 'LEARNING_PATH')}
                  className={`px-2.5 py-1.5 rounded-lg text-xs font-mono font-medium flex items-center gap-1.5 transition-all cursor-pointer ${
                    pathFilter === 'LEARNING_PATH'
                      ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-400/40'
                      : 'text-slate-400 hover:text-white'
                  }`}
                  title="Highlight active target vector"
                >
                  <Route className="w-3.5 h-3.5" />
                  <span>Learning Paths</span>
                </button>
              </div>
            )}

            {/* Feature 2: Bookmarks Filter Pill */}
            {bookmarkedCount > 0 && viewMode === 'GRAPH' && (
              <button
                type="button"
                onClick={() => setShowBookmarksOnly(!showBookmarksOnly)}
                className={`px-2.5 py-1.5 rounded-xl text-xs font-mono font-medium flex items-center gap-1.5 border transition-all cursor-pointer ${
                  showBookmarksOnly
                    ? 'bg-amber-500/20 text-amber-300 border-amber-400/40 shadow-[0_0_12px_rgba(245,158,11,0.3)]'
                    : 'bg-space-950/80 text-slate-300 border-white/[0.08] hover:text-amber-300'
                }`}
                title="Filter to your personal bookmarks and notes"
              >
                <BookMarked className="w-3.5 h-3.5 text-amber-400" />
                <span>Bookmarks ({bookmarkedCount})</span>
              </button>
            )}

            {/* Concept Search */}
            <div className="relative flex items-center">
              <Search className="absolute left-3 w-3.5 h-3.5 text-slate-400" />
              <input
                type="text"
                placeholder={viewMode === 'CHAPTERS' ? 'Search chapters...' : 'Search concepts...'}
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="pl-8 pr-4 py-1.5 text-xs rounded-xl bg-space-950/80 border border-white/[0.08] text-white placeholder-slate-400 focus:outline-none focus:border-cyan-400 w-36 sm:w-52 font-sans transition-all"
              />
            </div>

            {/* Chapter Filter Dropdown */}
            {viewMode === 'GRAPH' && graphData.topics?.length > 0 && (
              <div className="flex items-center gap-1 bg-space-950/80 px-2.5 py-1.5 rounded-xl border border-white/[0.08] text-xs">
                <Filter className="w-3 h-3 text-slate-400 mr-1" />
                <select
                  value={filterTopic}
                  onChange={(e) => setFilterTopic(e.target.value)}
                  className="bg-transparent text-slate-200 text-xs focus:outline-none cursor-pointer pr-1 font-mono"
                  aria-label="Filter chapters"
                >
                  <option value="ALL" className="bg-space-900 text-white">
                    All Chapters ({graphData.topics.length})
                  </option>
                  {graphData.topics.map((t) => (
                    <option key={t.id} value={t.id} className="bg-space-900 text-white">
                      {t.name}
                    </option>
                  ))}
                </select>
              </div>
            )}
          </div>

          {/* Right Tools: X-Ray Diagnostic Toggle */}
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onToggleXRay}
              className={`px-3 py-1.5 rounded-xl text-xs font-mono font-bold tracking-wider flex items-center gap-1.5 transition-all duration-200 cursor-pointer ${
                isXRayMode
                  ? 'bg-violet-600 text-white shadow-[0_0_20px_rgba(139,92,246,0.5)] border border-violet-400/60'
                  : 'bg-space-950/80 text-slate-300 border border-white/[0.08] hover:text-white hover:bg-space-850'
              }`}
            >
              <Eye className={`w-3.5 h-3.5 ${isXRayMode ? 'text-violet-200 animate-pulse' : 'text-slate-400'}`} />
              <span>X-RAY DIAGNOSTICS</span>
            </button>
          </div>
        </div>

        {/* Quick-Nav Chapter Jump Bar inside Canvas */}
        {viewMode === 'GRAPH' && graphData.topics?.length > 1 && (
          <ChapterQuickJumpStrip
            topics={graphData.topics}
            selectedTopicId={selectedTopicId}
            onSelectTopic={(t) => {
              if (onSelectTopic) onSelectTopic(t);
            }}
          />
        )}

        {/* ── Feature 3: Evidence-Based Learning Chains Milestone Banner ── */}
        {unacknowledgedChain && !highlightedChain && (
          <div className="absolute top-28 left-6 z-20 max-w-md p-3.5 rounded-2xl bg-space-900/95 border border-emerald-500/40 shadow-2xl backdrop-blur-xl animate-fade-in flex items-start justify-between gap-3">
            <div className="flex items-start gap-2.5">
              <div className="p-2 rounded-xl bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 shrink-0">
                <Award className="w-4 h-4" />
              </div>
              <div className="space-y-1">
                <div className="flex items-center gap-1.5">
                  <span className="text-[10px] font-mono uppercase tracking-widest text-emerald-400 font-bold">
                    Curriculum Milestone
                  </span>
                  <span className="text-[9px] font-mono px-1.5 py-0.2 rounded bg-emerald-950 text-emerald-300 border border-emerald-500/30">
                    Verified
                  </span>
                </div>
                <h4 className="text-xs font-display font-bold text-white">
                  {unacknowledgedChain.length} Connected Concepts Mastered
                </h4>
                <p className="text-[11px] text-slate-300 font-sans leading-relaxed">
                  {unacknowledgedChain.conceptNames.join(' → ')}
                </p>
                <div className="flex items-center gap-2 pt-1">
                  <button
                    type="button"
                    onClick={() => setHighlightedChain(unacknowledgedChain)}
                    className="px-2.5 py-1 rounded-lg bg-emerald-500 text-space-950 font-mono text-[10px] font-bold hover:bg-emerald-400 transition-colors cursor-pointer flex items-center gap-1"
                  >
                    <span>Inspect Chain</span>
                    <ArrowRight className="w-3 h-3" />
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setDismissedChainIds((prev) => new Set(prev).add(unacknowledgedChain.id));
                    }}
                    className="px-2 py-1 rounded-lg text-slate-400 hover:text-white font-mono text-[10px] transition-colors cursor-pointer"
                  >
                    Dismiss
                  </button>
                </div>
              </div>
            </div>
            <button
              type="button"
              onClick={() => {
                setDismissedChainIds((prev) => new Set(prev).add(unacknowledgedChain.id));
              }}
              className="text-slate-400 hover:text-white p-1"
              aria-label="Close milestone banner"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        )}

        {/* Highlighted Chain Clear Action */}
        {highlightedChain && (
          <div className="absolute top-28 left-6 z-20 flex items-center gap-2 p-2 px-3 rounded-xl bg-emerald-950/90 border border-emerald-500/50 shadow-xl text-xs font-mono text-emerald-200 backdrop-blur-xl">
            <Award className="w-4 h-4 text-emerald-400" />
            <span>Viewing Mastered Chain ({highlightedChain.length} nodes)</span>
            <button
              type="button"
              onClick={() => setHighlightedChain(null)}
              className="ml-2 text-emerald-300 hover:text-white text-xs underline cursor-pointer"
            >
              Reset View
            </button>
          </div>
        )}

        {/* ── Feature 1: Next Best Step Quick Action Dock ── */}
        {nextBestSteps.length > 0 && !selectedConcept && (
          <div className="absolute top-28 right-6 z-20 flex items-center gap-2">
            {nextBestSteps.map((rec) => {
              const concept = (graphData.concepts || []).find((c) => c.concept_id === rec.conceptId);
              if (!concept) return null;
              return (
                <button
                  key={rec.conceptId}
                  type="button"
                  onClick={() => onSelectConcept(concept)}
                  className="group flex items-center gap-2 px-3 py-1.5 rounded-xl bg-space-900/90 hover:bg-space-850 border border-cyan-500/40 hover:border-cyan-400 shadow-lg backdrop-blur-xl text-left transition-all cursor-pointer"
                  title={rec.reason}
                >
                  <Compass className="w-3.5 h-3.5 text-cyan-400 group-hover:rotate-45 transition-transform" />
                  <div className="flex flex-col">
                    <span className="text-[9px] font-mono text-cyan-300 font-bold uppercase tracking-wider">
                      Next Best Step
                    </span>
                    <span className="text-xs font-display font-semibold text-white truncate max-w-[150px]">
                      {rec.conceptName}
                    </span>
                  </div>
                </button>
              );
            })}
          </div>
        )}

        {/* ── Feature 1 & 2: Selected Concept Action Panel (Bottom Center) ── */}
        {selectedConcept && (
          <div className="absolute bottom-5 left-1/2 -translate-x-1/2 z-20 flex flex-wrap items-center gap-2 p-2 rounded-2xl bg-space-900/95 border border-white/[0.1] shadow-2xl backdrop-blur-2xl animate-fade-in max-w-xl">
            <div className="px-2.5 py-1 border-r border-white/[0.08] max-w-[200px]">
              <span className="text-[9px] font-mono text-slate-400 uppercase tracking-widest block">
                Selected Concept
              </span>
              <h4 className="text-xs font-display font-bold text-white truncate">
                {selectedConcept.name}
              </h4>
            </div>

            {selectedConceptRecommendation && (
              <div className="px-2.5 py-1 text-[11px] font-sans text-cyan-200 border-r border-white/[0.08] max-w-xs leading-tight">
                <span className="text-[9px] font-mono text-cyan-300 uppercase font-bold tracking-wider block">
                  Next Step Reason:
                </span>
                <span className="line-clamp-1">{selectedConceptRecommendation.reason}</span>
              </div>
            )}

            <button
              type="button"
              onClick={() => handleToggleBookmark(selectedConcept.concept_id)}
              className={`p-2 rounded-xl text-xs font-mono font-medium flex items-center gap-1.5 transition-colors cursor-pointer ${
                selectedConceptAnnotation?.isBookmarked
                  ? 'bg-amber-400 text-space-950 font-bold shadow-[0_0_12px_rgba(245,158,11,0.5)]'
                  : 'bg-space-850 hover:bg-space-800 text-slate-300 hover:text-white border border-white/[0.08]'
              }`}
              title={selectedConceptAnnotation?.isBookmarked ? 'Remove bookmark' : 'Bookmark this concept'}
            >
              <Bookmark className="w-3.5 h-3.5" />
              <span>{selectedConceptAnnotation?.isBookmarked ? 'Bookmarked' : 'Bookmark'}</span>
            </button>

            <button
              type="button"
              onClick={() => {
                setEditingNoteConceptId(selectedConcept.concept_id);
                setNoteInputText(selectedConceptAnnotation?.note || '');
              }}
              className={`p-2 rounded-xl text-xs font-mono font-medium flex items-center gap-1.5 transition-colors cursor-pointer ${
                selectedConceptAnnotation?.note
                  ? 'bg-amber-500/20 text-amber-300 border border-amber-400/40'
                  : 'bg-space-850 hover:bg-space-800 text-slate-300 hover:text-white border border-white/[0.08]'
              }`}
              title="Add or edit your private note"
            >
              <MessageSquare className="w-3.5 h-3.5" />
              <span>{selectedConceptAnnotation?.note ? 'Edit Note' : 'Add Note'}</span>
            </button>

            {crossSubjectDiscoveries.length > 0 && (
              <button
                type="button"
                onClick={() => setActiveDiscovery(crossSubjectDiscoveries[0])}
                className="p-2 rounded-xl bg-purple-500/20 hover:bg-purple-500/30 text-purple-300 border border-purple-400/40 text-xs font-mono font-medium flex items-center gap-1.5 transition-colors cursor-pointer"
                title="Verified Interdisciplinary Discovery"
              >
                <Sparkles className="w-3.5 h-3.5 text-purple-400" />
                <span>Explore Further</span>
              </button>
            )}

            {onStartLearning && (
              <button
                type="button"
                onClick={() => onStartLearning(selectedConcept.concept_id)}
                className="px-3 py-1.5 rounded-xl bg-cyan-400 hover:bg-cyan-300 text-space-950 font-mono text-xs font-bold transition-all shadow-md flex items-center gap-1 cursor-pointer ml-auto"
              >
                <span>Study</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </button>
            )}

            {onStartPractice && (
              <button
                type="button"
                onClick={() => onStartPractice(selectedConcept.concept_id)}
                className="px-3 py-1.5 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-space-950 font-mono text-xs font-bold transition-all shadow-md flex items-center gap-1 cursor-pointer"
              >
                <span>Practice</span>
              </button>
            )}

            <button
              type="button"
              onClick={() => onSelectConcept(null)}
              className="p-1.5 text-slate-400 hover:text-white rounded-lg transition-colors"
              aria-label="Deselect concept"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        )}

        {/* ── Feature 2: Personal Note Editor Dialog ── */}
        {editingNoteConceptId && (
          <div className="absolute inset-0 z-40 bg-space-950/70 backdrop-blur-sm flex items-center justify-center p-4 animate-fade-in">
            <div className="w-full max-w-md p-5 rounded-2xl bg-space-900 border border-white/10 shadow-2xl space-y-4 text-left">
              <div className="flex items-center justify-between pb-3 border-b border-white/[0.08]">
                <div className="flex items-center gap-2">
                  <Bookmark className="w-4 h-4 text-amber-400" />
                  <h3 className="text-xs font-mono font-bold text-white uppercase tracking-wider">
                    Personal Concept Note
                  </h3>
                </div>
                <button
                  type="button"
                  onClick={() => setEditingNoteConceptId(null)}
                  className="text-slate-400 hover:text-white"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>

              <div className="space-y-1">
                <span className="text-[10px] font-mono text-slate-400 uppercase tracking-widest">
                  Target Concept
                </span>
                <p className="text-sm font-display font-bold text-white">
                  {(graphData.concepts || []).find((c) => c.concept_id === editingNoteConceptId)?.name}
                </p>
                <p className="text-[11px] text-slate-400 font-sans">
                  Private note stored locally. Clearly separated from authoritative curriculum definitions.
                </p>
              </div>

              <div className="space-y-1.5">
                <textarea
                  rows={3}
                  maxLength={280}
                  value={noteInputText}
                  onChange={(e) => setNoteInputText(e.target.value)}
                  placeholder="e.g. Review this before the next differentiation test..."
                  className="w-full p-3 text-xs rounded-xl bg-space-950 border border-white/[0.1] text-white placeholder-slate-500 focus:outline-none focus:border-amber-400 font-sans leading-relaxed resize-none"
                />
                <div className="flex justify-between items-center text-[10px] font-mono text-slate-400">
                  <span>Maximum 280 characters</span>
                  <span>{noteInputText.length}/280</span>
                </div>
              </div>

              <div className="flex items-center justify-between pt-2 border-t border-white/[0.08]">
                {annotations[editingNoteConceptId]?.note ? (
                  <button
                    type="button"
                    onClick={() => handleRemoveNote(editingNoteConceptId)}
                    className="text-xs font-mono text-rose-400 hover:text-rose-300 underline cursor-pointer"
                  >
                    Delete Note
                  </button>
                ) : (
                  <span />
                )}

                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => setEditingNoteConceptId(null)}
                    className="px-3 py-1.5 rounded-xl bg-space-850 hover:bg-space-800 text-slate-300 font-mono text-xs transition-colors cursor-pointer"
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    onClick={() => handleSaveNote(editingNoteConceptId, noteInputText)}
                    className="px-4 py-1.5 rounded-xl bg-amber-400 hover:bg-amber-300 text-space-950 font-mono text-xs font-bold transition-all shadow-md cursor-pointer flex items-center gap-1.5"
                  >
                    <Check className="w-3.5 h-3.5 stroke-[2.5]" />
                    <span>Save Note</span>
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* ── Feature 4: Verified Cross-Subject Discovery Modal ── */}
        {activeDiscovery && (
          <div className="absolute inset-0 z-40 bg-space-950/70 backdrop-blur-sm flex items-center justify-center p-4 animate-fade-in">
            <div className="w-full max-w-lg p-6 rounded-2xl bg-space-900 border border-purple-500/40 shadow-2xl space-y-4 text-left">
              <div className="flex items-center justify-between pb-3 border-b border-white/[0.08]">
                <div className="flex items-center gap-2">
                  <Sparkles className="w-4 h-4 text-purple-400" />
                  <span className="text-xs font-mono font-bold text-purple-300 uppercase tracking-wider">
                    Verified Cross-Subject Discovery
                  </span>
                </div>
                <button
                  type="button"
                  onClick={() => setActiveDiscovery(null)}
                  className="text-slate-400 hover:text-white"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>

              <div className="space-y-2">
                <div className="flex items-center gap-2 text-xs font-mono text-slate-300">
                  <span className="px-2 py-0.5 rounded bg-space-800 text-white font-bold">
                    {activeDiscovery.sourceConceptName}
                  </span>
                  <span className="text-purple-400 font-bold">
                    — {activeDiscovery.relationshipType} →
                  </span>
                  <span className="px-2 py-0.5 rounded bg-space-800 text-white font-bold">
                    {activeDiscovery.targetConceptName}
                  </span>
                </div>

                <div className="p-3.5 rounded-xl bg-purple-950/40 border border-purple-500/30 text-xs text-purple-200 leading-relaxed font-sans">
                  {activeDiscovery.explanation}
                </div>

                <div className="p-2.5 rounded-xl bg-space-950/70 border border-white/[0.06] text-[11px] font-sans text-slate-400 space-y-1">
                  <span className="font-semibold text-slate-300 block font-mono text-[9px] uppercase tracking-wider">
                    Curriculum Boundary Guidance
                  </span>
                  <p>
                    This is an optional interdisciplinary application verified in source materials. It is not an unmastered prerequisite and does not impede your core curriculum progression.
                  </p>
                </div>
              </div>

              <div className="flex items-center justify-between pt-2 border-t border-white/[0.08]">
                <button
                  type="button"
                  onClick={() => setActiveDiscovery(null)}
                  className="px-3 py-1.5 rounded-xl bg-space-850 hover:bg-space-800 text-slate-300 font-mono text-xs transition-colors cursor-pointer"
                >
                  Close Discovery
                </button>

                {(() => {
                  const targetConcept = (graphData.concepts || []).find(
                    (c) => c.concept_id === activeDiscovery.targetConceptId
                  );
                  if (!targetConcept) return null;
                  return (
                    <button
                      type="button"
                      onClick={() => {
                        onSelectConcept(targetConcept);
                        setActiveDiscovery(null);
                      }}
                      className="px-3 py-1.5 rounded-xl bg-purple-500 hover:bg-purple-400 text-space-950 font-mono text-xs font-bold transition-all shadow-md flex items-center gap-1.5 cursor-pointer"
                    >
                      <span>Focus Concept</span>
                      <ExternalLink className="w-3.5 h-3.5" />
                    </button>
                  );
                })()}
              </div>
            </div>
          </div>
        )}

        {/* Guided Sequence View presentation */}
        {viewMode === 'GUIDED' ? (
          <div className="w-full h-full overflow-y-auto p-6 pt-24 pb-16 scrollbar-thin scrollbar-thumb-white/10">
            <div className="max-w-4xl mx-auto">
              <GuidedSequenceView
                sequenceData={sequenceData}
                isLoading={isSequenceLoading}
                selectedStartingConceptId={selectedStartingConceptId}
                onSelectStartingConcept={(cid) => setSelectedStartingConceptId(cid)}
                onStartLearning={onStartLearning}
                onStartPractice={onStartPractice}
                onSwitchToGraphView={(focusConceptId) => {
                  setViewMode('GRAPH');
                  if (focusConceptId) {
                    const c = (graphData.concepts || []).find((item) => item.concept_id === focusConceptId);
                    if (c) onSelectConcept(c);
                  }
                }}
                allConcepts={graphData.concepts || []}
              />
            </div>
          </div>
        ) : (
        /* Main React Flow Graph Canvas */
        <ReactFlow
          nodes={initialNodes}
          edges={initialEdges}
          nodeTypes={nodeTypes}
          onNodesChange={handleNodesChange}
          onEdgesChange={handleEdgesChange}
          onPaneClick={handlePaneClick}
          fitView
          fitViewOptions={{ padding: 0.16 }}
          minZoom={0.15}
          maxZoom={2.4}
          className="w-full h-full bg-[#050811]"
        >
          <Background variant={BackgroundVariant.Dots} gap={28} size={1.2} color="#111827" />

          {/* MiniMap / Universe Radar */}
          {showMiniMap && (
            <MiniMap
              nodeColor={(node) => {
                if (node.type === 'topicCluster') return 'transparent';
                const d = node.data as ConceptNodeData;
                if (d.isSelected) return '#F59E0B';
                if (d.isTarget || d.isRecommendedNext) return '#00F0FF';
                if ((d.mastery ?? 0) >= 0.75) return '#10B981';
                if ((d.mastery ?? 0) >= 0.35) return '#06B6D4';
                return '#334155';
              }}
              maskColor="rgba(5, 8, 17, 0.85)"
              className="!bottom-20 !right-5 !bg-space-950/90 !border !border-white/[0.1] !rounded-2xl !shadow-2xl !overflow-hidden backdrop-blur-xl"
              style={{ width: 180, height: 120 }}
            />
          )}

          <AtlasCanvasControls
            isFullscreen={isFullscreen}
            onToggleFullscreen={toggleFullscreen}
            showMiniMap={showMiniMap}
            onToggleMiniMap={() => setShowMiniMap(!showMiniMap)}
          />
        </ReactFlow>
        )}

        {/* Scientific Dock Legend (Bottom-Left in Graph View) */}
        {viewMode === 'GRAPH' && (
        <div className="absolute bottom-5 left-5 z-20 flex flex-wrap items-center gap-4 px-4 py-2.5 rounded-2xl bg-space-900/90 border border-white/[0.08] text-[11px] font-mono text-slate-300 shadow-xl backdrop-blur-xl">
          {/* Node Status */}
          <div className="flex items-center gap-3 pr-3 border-r border-white/[0.08]">
            <span className="text-[10px] text-slate-400 uppercase tracking-widest font-bold">Node Status</span>
            
            {/* Mastered Star */}
            <div className="flex items-center gap-1.5" title="Mastered: solid star with check badge">
              <svg viewBox="0 0 100 100" className="w-3.5 h-3.5 shrink-0 overflow-visible">
                <path
                  d="M 50,4 C 50,34 66,50 96,50 C 66,50 50,66 50,96 C 50,66 34,50 4,50 C 34,50 50,34 50,4 Z"
                  fill="#10B981"
                  stroke="#6EE7B7"
                  strokeWidth="2.5"
                />
              </svg>
              <span>Mastered</span>
            </div>

            {/* Learning Star (Split Fill) */}
            <div className="flex items-center gap-1.5" title="Learning: partial illuminated fill">
              <svg viewBox="0 0 100 100" className="w-3.5 h-3.5 shrink-0 overflow-visible">
                <defs>
                  <linearGradient id="legend-learning-grad" x1="0" y1="1" x2="0" y2="0">
                    <stop offset="0%" stopColor="#00F0FF" />
                    <stop offset="50%" stopColor="#0284C7" />
                    <stop offset="50%" stopColor="#0F172A" />
                    <stop offset="100%" stopColor="#0A0F1D" />
                  </linearGradient>
                </defs>
                <path
                  d="M 50,4 C 50,34 66,50 96,50 C 66,50 50,66 50,96 C 50,66 34,50 4,50 C 34,50 50,34 50,4 Z"
                  fill="url(#legend-learning-grad)"
                  stroke="#38BDF8"
                  strokeWidth="2.5"
                />
              </svg>
              <span>Learning</span>
            </div>

            {/* Not Assessed Star (Muted Outline) */}
            <div className="flex items-center gap-1.5" title="Not assessed: muted outline">
              <svg viewBox="0 0 100 100" className="w-3.5 h-3.5 shrink-0 overflow-visible">
                <path
                  d="M 50,4 C 50,34 66,50 96,50 C 66,50 50,66 50,96 C 50,66 34,50 4,50 C 34,50 50,34 50,4 Z"
                  fill="rgba(15, 23, 42, 0.6)"
                  stroke="rgba(148, 163, 184, 0.6)"
                  strokeWidth="2.5"
                />
              </svg>
              <span>Not assessed</span>
            </div>

            {/* Selected Star */}
            <div className="flex items-center gap-1.5" title="Selected: amber star halo">
              <svg viewBox="0 0 100 100" className="w-3.5 h-3.5 shrink-0 overflow-visible">
                <path
                  d="M 50,4 C 50,34 66,50 96,50 C 66,50 50,66 50,96 C 50,66 34,50 4,50 C 34,50 50,34 50,4 Z"
                  fill="#F59E0B"
                  stroke="#FDE68A"
                  strokeWidth="2.5"
                />
                <circle cx="50" cy="50" r="48" fill="none" stroke="#F59E0B" strokeWidth="2" opacity="0.6" />
              </svg>
              <span>Selected</span>
            </div>
          </div>

          {/* Indicators */}
          <div className="flex items-center gap-3 pr-3 border-r border-white/[0.08]">
            <div className="flex items-center gap-1.5 text-cyan-300">
              <Compass className="w-3.5 h-3.5 text-cyan-400" />
              <span>Recommended</span>
            </div>
            <div className="flex items-center gap-1.5 text-amber-300">
              <Bookmark className="w-3.5 h-3.5 text-amber-400" />
              <span>Personal note</span>
            </div>
          </div>

          {/* Edge Type */}
          <div className="flex items-center gap-3">
            <span className="text-[10px] text-slate-400 uppercase tracking-widest font-bold">Edge Type</span>
            <div className="flex items-center gap-1.5 text-cyan-300">
              <svg width="20" height="10" className="overflow-visible">
                <line x1="0" y1="5" x2="14" y2="5" stroke="#38BDF8" strokeWidth="1.8" />
                <polygon points="14,2 19,5 14,8" fill="#38BDF8" />
              </svg>
              <span>Prereq</span>
            </div>
            <div className="flex items-center gap-1.5 text-purple-300">
              <svg width="20" height="10" className="overflow-visible">
                <line x1="0" y1="5" x2="14" y2="5" stroke="#A855F7" strokeWidth="2.0" />
                <polygon points="14,2 19,5 14,8" fill="#A855F7" />
              </svg>
              <span>Bridge</span>
            </div>
            <div className="flex items-center gap-1.5 text-slate-400">
              <svg width="20" height="10" className="overflow-visible">
                <line x1="0" y1="5" x2="14" y2="5" stroke="rgba(148, 163, 184, 0.6)" strokeWidth="1.2" strokeDasharray="3 3" />
                <polygon points="14,2 19,5 14,8" fill="rgba(148, 163, 184, 0.6)" />
              </svg>
              <span>Cluster</span>
            </div>
          </div>
        </div>
        )}
      </ReactFlowProvider>
    </div>
  );
};
