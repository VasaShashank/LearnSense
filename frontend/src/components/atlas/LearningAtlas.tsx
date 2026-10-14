import React, { useState, useMemo, useCallback } from 'react';
import {
  ReactFlow,
  Controls,
  Background,
  useNodesState,
  useEdgesState,
  MarkerType,
  BackgroundVariant,
} from '@xyflow/react';
import type { Node, Edge } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import type { KnowledgeGraphData, ConceptNode, TopicTerritory } from '../../api/client';
import { CustomConceptNode } from './CustomConceptNode';
import type { ConceptNodeData } from './CustomConceptNode';
import { SubheadingNode } from './SubheadingNode';
import type { SubheadingNodeData } from './SubheadingNode';
import { TerritoryOverlay } from './TerritoryOverlay';
import { Layers, Eye, Search, Filter, Compass, Network } from 'lucide-react';

export interface LearningAtlasProps {
  graphData: KnowledgeGraphData;
  activeTargetId?: string;
  selectedTopicId?: string;
  selectedConceptId?: string;
  onSelectTopic?: (topic: TopicTerritory) => void;
  onSelectConcept: (concept: ConceptNode) => void;
  isXRayMode: boolean;
  onToggleXRay: () => void;
  impactedConceptIds?: string[];
  onTraceImpact?: (id: string) => void;
}

const nodeTypes = {
  conceptNode: CustomConceptNode,
  subheadingNode: SubheadingNode,
};

export const LearningAtlas: React.FC<LearningAtlasProps> = ({
  graphData,
  activeTargetId,
  selectedTopicId,
  selectedConceptId,
  onSelectTopic,
  onSelectConcept,
  isXRayMode,
  onToggleXRay,
  impactedConceptIds = [],
  onTraceImpact,
}) => {
  const [zoomLevel, setZoomLevel] = useState<number>(3);
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [filterTopic, setFilterTopic] = useState<string>('ALL');
  // Default to SUBHEADINGS view so the graph is never clogged with 459 nodes
  const [viewMode, setViewMode] = useState<'SUBHEADINGS' | 'CONCEPTS'>('SUBHEADINGS');

  // Compute Nodes based on View Mode
  const initialNodes: Node[] = useMemo(() => {
    const qLower = searchQuery.toLowerCase().trim();

    // 1. SUBHEADINGS VIEW: Represent only the high-level subheadings as primary nodes
    if (viewMode === 'SUBHEADINGS') {
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
        const x = 120 + col * 360;
        const y = 140 + row * 230;

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
            zoomLevel,
            onSelect: (t: TopicTerritory) => {
              if (onSelectTopic) onSelectTopic(t);
            },
            onTraceImpact,
          } as SubheadingNodeData,
        };
      });
    }

    // 2. CONCEPTS VIEW: Granular view of individual concepts grouped by topic
    const topicGrouped: Record<string, ConceptNode[]> = {};
    (graphData.concepts || []).forEach((c) => {
      const def = c.definition || c.description || '';
      const matchesSearch = !qLower || c.name.toLowerCase().includes(qLower) || def.toLowerCase().includes(qLower);
      const tId = c.topic_id || 'general';
      const matchesTopic = filterTopic === 'ALL' || tId === filterTopic;

      if (matchesSearch && matchesTopic) {
        if (!topicGrouped[tId]) topicGrouped[tId] = [];
        topicGrouped[tId].push(c);
      }
    });

    const nodesRes: Node[] = [];
    let topicIndex = 0;

    Object.entries(topicGrouped).forEach(([, concepts]) => {
      const startX = 120 + topicIndex * 380;
      concepts.forEach((concept, conceptIdx) => {
        const x = startX + (conceptIdx % 2) * 120;
        const y = 140 + conceptIdx * 140;

        const isTarget = concept.concept_id === activeTargetId;
        const isSelected = concept.concept_id === selectedConceptId;
        const isImpacted = impactedConceptIds.includes(concept.concept_id);

        nodesRes.push({
          id: concept.concept_id,
          type: 'conceptNode',
          position: { x, y },
          data: {
            ...concept,
            isTarget,
            isSelected,
            isImpacted,
            isXRay: isXRayMode,
            zoomLevel,
            onSelect: onSelectConcept,
          } as ConceptNodeData,
        });
      });
      topicIndex++;
    });

    return nodesRes;
  }, [
    viewMode,
    graphData.topics,
    graphData.concepts,
    searchQuery,
    filterTopic,
    activeTargetId,
    selectedTopicId,
    selectedConceptId,
    impactedConceptIds,
    isXRayMode,
    zoomLevel,
    onSelectTopic,
    onSelectConcept,
    onTraceImpact,
  ]);

  // Compute Edges based on View Mode
  const initialEdges: Edge[] = useMemo(() => {
    const edgesRes: Edge[] = [];
    const seenEdges = new Set<string>();
    const visibleNodeIds = new Set(initialNodes.map((n) => n.id));

    const addEdge = (src: string, tgt: string, isTopicEdge = false) => {
      const edgeKey = `${src}->${tgt}`;
      if (seenEdges.has(edgeKey) || src === tgt) return;
      if (!visibleNodeIds.has(src) || !visibleNodeIds.has(tgt)) return;
      seenEdges.add(edgeKey);

      const isSrcImpacted = impactedConceptIds.includes(src);
      const isTgtImpacted = impactedConceptIds.includes(tgt);
      const isCascadePath = isSrcImpacted && isTgtImpacted;
      const isTargetEdge = tgt === activeTargetId;

      const strokeColor = isCascadePath || isSrcImpacted
        ? '#F43F5E'
        : isTargetEdge
        ? '#00F0FF'
        : isXRayMode
        ? '#8B5CF6'
        : isTopicEdge
        ? '#00E5FF'
        : 'rgba(0, 240, 255, 0.45)';

      edgesRes.push({
        id: `e-${src}-${tgt}`,
        source: src,
        target: tgt,
        animated: isCascadePath || isTargetEdge || isSrcImpacted || isXRayMode,
        style: {
          stroke: strokeColor,
          strokeWidth: isCascadePath ? 3.0 : isSrcImpacted ? 2.5 : isTargetEdge ? 2.2 : isTopicEdge ? 2.0 : 1.5,
          strokeDasharray: isXRayMode ? '4 4' : undefined,
        },
        markerEnd: {
          type: MarkerType.ArrowClosed,
          color: strokeColor,
          width: isTopicEdge ? 16 : 14,
          height: isTopicEdge ? 16 : 14,
        },
      });
    };

    if (viewMode === 'SUBHEADINGS') {
      // Connect Subheading prerequisite edges
      (graphData.topics || []).forEach((topic) => {
        (topic.prerequisites || []).forEach((prereqId) => {
          addEdge(prereqId, topic.id, true);
        });
      });

      (graphData.topic_relationships || []).forEach((rel) => {
        addEdge(rel.source, rel.target, true);
      });
    } else {
      // Connect Concept-level prerequisite edges
      (graphData.concepts || []).forEach((concept) => {
        (concept.prerequisites || []).forEach((prereqId) => {
          addEdge(prereqId, concept.concept_id);
        });
      });

      (graphData.relationships || []).forEach((rel) => {
        addEdge(rel.source, rel.target);
      });
    }

    return edgesRes;
  }, [viewMode, graphData.topics, graphData.topic_relationships, graphData.concepts, graphData.relationships, initialNodes, activeTargetId, impactedConceptIds, isXRayMode]);

  const [, , onNodesChange] = useNodesState(initialNodes);
  const [, , onEdgesChange] = useEdgesState(initialEdges);

  const handleViewportChange = useCallback((viewport: { zoom: number }) => {
    if (viewport.zoom < 0.5) setZoomLevel(1);
    else if (viewport.zoom < 0.8) setZoomLevel(2);
    else if (viewport.zoom < 1.3) setZoomLevel(3);
    else setZoomLevel(4);
  }, []);

  return (
    <div className="relative w-full h-[720px] rounded-3xl border border-white/[0.08] bg-space-950 overflow-hidden shadow-[0_24px_64px_rgba(0,0,0,0.8)]">
      
      {/* Regional Overlays for Concepts View */}
      {viewMode === 'CONCEPTS' && <TerritoryOverlay topics={graphData.topics} zoomLevel={zoomLevel} />}

      {/* Floating Control HUD */}
      <div className="absolute top-4 left-4 right-4 z-20 flex flex-wrap items-center justify-between gap-3 p-2.5 rounded-2xl universe-panel shadow-lg">
        <div className="flex flex-wrap items-center gap-3">
          {/* View Mode Switcher Pill */}
          <div className="flex items-center p-1 rounded-xl bg-space-850/90 border border-white/[0.08]">
            <button
              onClick={() => setViewMode('SUBHEADINGS')}
              className={`px-3 py-1.5 rounded-lg text-xs font-mono font-bold flex items-center gap-1.5 transition-all ${
                viewMode === 'SUBHEADINGS'
                  ? 'bg-cyan-400 text-space-950 shadow-[0_0_16px_rgba(0,240,255,0.4)]'
                  : 'text-universe-slate hover:text-white'
              }`}
            >
              <Network className="w-3.5 h-3.5" />
              <span>Subheadings DAG ({graphData.topics?.length || 0})</span>
            </button>
            <button
              onClick={() => setViewMode('CONCEPTS')}
              className={`px-3 py-1.5 rounded-lg text-xs font-mono font-bold flex items-center gap-1.5 transition-all ${
                viewMode === 'CONCEPTS'
                  ? 'bg-cyan-400 text-space-950 shadow-[0_0_16px_rgba(0,240,255,0.4)]'
                  : 'text-universe-slate hover:text-white'
              }`}
            >
              <Compass className="w-3.5 h-3.5" />
              <span>All Concepts ({graphData.concepts?.length || 0})</span>
            </button>
          </div>

          {/* Search Box */}
          <div className="relative flex items-center">
            <Search className="absolute left-3 w-3.5 h-3.5 text-universe-slate" />
            <input
              type="text"
              placeholder={viewMode === 'SUBHEADINGS' ? 'Search subheadings or concepts...' : 'Search concepts...'}
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-8 pr-4 py-1.5 text-xs rounded-xl bg-space-850/90 border border-white/[0.07] text-white placeholder-universe-slate focus:outline-none focus:border-cyan-400 w-44 sm:w-56 font-sans transition-all"
            />
          </div>

          {/* Topic Filter (for concepts mode) */}
          {viewMode === 'CONCEPTS' && (
            <div className="flex items-center gap-1 bg-space-850/90 px-2 py-1 rounded-xl border border-white/[0.07] text-xs">
              <Filter className="w-3 h-3 text-universe-slate mr-1" />
              <select
                value={filterTopic}
                onChange={(e) => setFilterTopic(e.target.value)}
                className="bg-transparent text-universe-text text-xs focus:outline-none cursor-pointer pr-2 font-mono"
              >
                <option value="ALL" className="bg-space-900">All Topics ({graphData.topics.length})</option>
                {graphData.topics.map((t) => (
                  <option key={t.id} value={t.id} className="bg-space-900">
                    {t.name}
                  </option>
                ))}
              </select>
            </div>
          )}
        </div>

        {/* Right Tools: Zoom Metric & X-Ray Mode */}
        <div className="flex items-center gap-2">
          <div className="px-2.5 py-1 rounded-xl bg-space-850/80 border border-white/[0.06] text-[10px] font-mono text-universe-slate flex items-center gap-1.5">
            <Layers className="w-3 h-3 text-cyan-400" />
            <span>LAYER {zoomLevel}/4</span>
          </div>

          <button
            onClick={onToggleXRay}
            className={`px-3 py-1.5 rounded-xl text-xs font-mono font-bold tracking-wider flex items-center gap-1.5 transition-all duration-200 ${
              isXRayMode
                ? 'bg-violet-600 text-white shadow-[0_0_20px_rgba(139,92,246,0.4)] border border-violet-400/60'
                : 'bg-space-850 text-universe-slate border border-white/[0.07] hover:text-white hover:bg-space-800'
            }`}
          >
            <Eye className={`w-3.5 h-3.5 ${isXRayMode ? 'text-violet-200 animate-pulse' : 'text-universe-slate'}`} />
            <span>X-RAY SCAN</span>
          </button>
        </div>
      </div>

      {/* Main React Flow Graph Canvas */}
      <ReactFlow
        nodes={initialNodes}
        edges={initialEdges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onMove={(_, viewport) => handleViewportChange(viewport)}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        minZoom={0.2}
        maxZoom={2.0}
        className="w-full h-full bg-space-950"
      >
        <Background variant={BackgroundVariant.Dots} gap={28} size={1.2} color="#162238" />
        <Controls position="bottom-right" className="!mb-4 !mr-4" />
      </ReactFlow>

      {/* Floating Legend Dock */}
      <div className="absolute bottom-4 left-4 z-20 flex flex-wrap items-center gap-4 px-4 py-2 rounded-xl universe-panel text-[10px] font-mono text-universe-slate shadow-lg">
        <div className="flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full bg-emerald-400 shadow-[0_0_8px_#10B981]" />
          <span>Mastered</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full bg-cyan-400 shadow-[0_0_8px_#00F0FF]" />
          <span>Developing</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full bg-amber-400 shadow-[0_0_8px_#F59E0B]" />
          <span>Attention</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full bg-rose-500 shadow-[0_0_8px_#F43F5E] animate-pulse" />
          <span>Cascade Impact</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full bg-cyan-400 animate-ping" style={{ animationDuration: '3s' }} />
          <span>Target Vector</span>
        </div>
      </div>
    </div>
  );
};
