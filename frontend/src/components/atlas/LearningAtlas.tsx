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
import type { KnowledgeGraphData, ConceptNode } from '../../api/client';
import { CustomConceptNode } from './CustomConceptNode';
import type { ConceptNodeData } from './CustomConceptNode';
import { TerritoryOverlay } from './TerritoryOverlay';
import { Layers, Eye, Search, Filter } from 'lucide-react';

export interface LearningAtlasProps {
  graphData: KnowledgeGraphData;
  activeTargetId?: string;
  selectedConceptId?: string;
  onSelectConcept: (concept: ConceptNode) => void;
  isXRayMode: boolean;
  onToggleXRay: () => void;
  impactedConceptIds?: string[];
}

const nodeTypes = {
  conceptNode: CustomConceptNode,
};

export const LearningAtlas: React.FC<LearningAtlasProps> = ({
  graphData,
  activeTargetId,
  selectedConceptId,
  onSelectConcept,
  isXRayMode,
  onToggleXRay,
  impactedConceptIds = [],
}) => {
  const [zoomLevel, setZoomLevel] = useState<number>(3);
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [filterTopic, setFilterTopic] = useState<string>('ALL');

  const initialNodes: Node[] = useMemo(() => {
    const topicGrouped: Record<string, ConceptNode[]> = {};
    graphData.concepts.forEach((c) => {
      const def = c.definition || c.description || '';
      const matchesSearch = c.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        def.toLowerCase().includes(searchQuery.toLowerCase());
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
  }, [graphData.concepts, searchQuery, filterTopic, activeTargetId, selectedConceptId, impactedConceptIds, isXRayMode, zoomLevel, onSelectConcept]);

  const initialEdges: Edge[] = useMemo(() => {
    const edgesRes: Edge[] = [];
    graphData.concepts.forEach((concept) => {
      concept.prerequisites.forEach((prereqId) => {
        const isPrereqImpacted = impactedConceptIds.includes(prereqId);
        const isTargetEdge = concept.concept_id === activeTargetId;

        edgesRes.push({
          id: `e-${prereqId}-${concept.concept_id}`,
          source: prereqId,
          target: concept.concept_id,
          animated: isTargetEdge || isPrereqImpacted || isXRayMode,
          style: {
            stroke: isPrereqImpacted ? '#F43F5E' : isTargetEdge ? '#00F0FF' : isXRayMode ? '#8B5CF6' : '#2A364F',
            strokeWidth: isPrereqImpacted ? 2.5 : isTargetEdge ? 2 : 1.2,
            strokeDasharray: isXRayMode ? '4 4' : undefined,
          },
          markerEnd: {
            type: MarkerType.ArrowClosed,
            color: isPrereqImpacted ? '#F43F5E' : isTargetEdge ? '#00F0FF' : '#5A667A',
            width: 14,
            height: 14,
          },
        });
      });
    });
    return edgesRes;
  }, [graphData.concepts, activeTargetId, impactedConceptIds, isXRayMode]);

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
      
      {/* Dynamic Territory Regional Overlays */}
      <TerritoryOverlay topics={graphData.topics} zoomLevel={zoomLevel} />

      {/* Floating Control HUD */}
      <div className="absolute top-4 left-4 right-4 z-20 flex flex-wrap items-center justify-between gap-3 p-2.5 rounded-2xl universe-panel shadow-lg">
        <div className="flex items-center gap-3">
          {/* Search Box */}
          <div className="relative flex items-center">
            <Search className="absolute left-3 w-3.5 h-3.5 text-universe-slate" />
            <input
              type="text"
              placeholder="Search knowledge territory..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-8 pr-4 py-1.5 text-xs rounded-xl bg-space-850/90 border border-white/[0.07] text-white placeholder-universe-slate focus:outline-none focus:border-cyan-400 w-48 sm:w-60 font-sans transition-all"
            />
          </div>

          {/* Topic Filter */}
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
        minZoom={0.25}
        maxZoom={2.0}
        className="w-full h-full bg-space-950"
      >
        <Background variant={BackgroundVariant.Dots} gap={28} size={1.2} color="#162238" />
        <Controls position="bottom-right" className="!mb-4 !mr-4" />
      </ReactFlow>

      {/* Floating Legend Dock */}
      <div className="absolute bottom-4 left-4 z-20 flex items-center gap-4 px-4 py-2 rounded-xl universe-panel text-[10px] font-mono text-universe-slate">
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
          <span>Gap Attention</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full bg-cyan-400 animate-ping" style={{ animationDuration: '3s' }} />
          <span>Target Vector</span>
        </div>
      </div>
    </div>
  );
};
