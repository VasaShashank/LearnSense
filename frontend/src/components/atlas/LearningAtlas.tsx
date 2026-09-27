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
import { CustomConceptNode } from './CustomConceptNode';
import type { ConceptNodeData } from './CustomConceptNode';
import { TerritoryOverlay } from './TerritoryOverlay';
import type { KnowledgeGraphData, ConceptNode } from '../../api/client';
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
      const matchesSearch = c.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        c.definition.toLowerCase().includes(searchQuery.toLowerCase());
      const matchesTopic = filterTopic === 'ALL' || c.topic_id === filterTopic;

      if (matchesSearch && matchesTopic) {
        if (!topicGrouped[c.topic_id]) topicGrouped[c.topic_id] = [];
        topicGrouped[c.topic_id].push(c);
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
            stroke: isPrereqImpacted ? '#f43f5e' : isTargetEdge ? '#38bdf8' : isXRayMode ? '#8b5cf6' : '#334155',
            strokeWidth: isPrereqImpacted ? 3 : isTargetEdge ? 2.5 : 1.5,
            strokeDasharray: isXRayMode ? '4 4' : undefined,
          },
          markerEnd: {
            type: MarkerType.ArrowClosed,
            color: isPrereqImpacted ? '#f43f5e' : isTargetEdge ? '#38bdf8' : '#64748b',
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
    <div className="relative w-full h-[680px] rounded-3xl border border-slate-800 bg-slate-950 overflow-hidden shadow-2xl">
      <TerritoryOverlay topics={graphData.topics} zoomLevel={zoomLevel} />

      <div className="absolute top-4 left-4 right-4 z-20 flex flex-wrap items-center justify-between gap-3 p-3 rounded-2xl glass-panel shadow-lg">
        <div className="flex items-center gap-3">
          <div className="relative flex items-center">
            <Search className="absolute left-3 w-4 h-4 text-slate-400" />
            <input
              type="text"
              placeholder="Search knowledge territory..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-9 pr-4 py-1.5 text-xs rounded-xl bg-slate-900/80 border border-slate-700/60 text-white placeholder-slate-400 focus:outline-none focus:border-cyan-400 w-52 transition-all"
            />
          </div>

          <div className="flex items-center gap-1 bg-slate-900/80 p-1 rounded-xl border border-slate-700/60 text-xs">
            <Filter className="w-3.5 h-3.5 text-slate-400 ml-1" />
            <select
              value={filterTopic}
              onChange={(e) => setFilterTopic(e.target.value)}
              className="bg-transparent text-slate-200 text-xs focus:outline-none cursor-pointer pr-1"
            >
              <option value="ALL" className="bg-slate-900">All Topics</option>
              {graphData.topics.map((t) => (
                <option key={t.id} value={t.id} className="bg-slate-900">
                  {t.name}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <div className="px-3 py-1 rounded-xl bg-slate-900/80 border border-slate-700/60 text-[11px] font-mono text-slate-300 flex items-center gap-1.5">
            <Layers className="w-3.5 h-3.5 text-cyan-400" />
            <span>ZOOM LEVEL {zoomLevel}/4</span>
          </div>

          <button
            onClick={onToggleXRay}
            className={`px-3 py-1.5 rounded-xl text-xs font-bold tracking-wide flex items-center gap-1.5 transition-all duration-300 ${
              isXRayMode
                ? 'bg-violet-600 text-white shadow-glow-rose ring-2 ring-violet-400/50'
                : 'bg-slate-800 text-slate-300 border border-slate-700 hover:bg-slate-700'
            }`}
          >
            <Eye className={`w-4 h-4 ${isXRayMode ? 'text-violet-200 animate-pulse' : 'text-slate-400'}`} />
            <span>X-RAY MODE</span>
          </button>
        </div>
      </div>

      <ReactFlow
        nodes={initialNodes}
        edges={initialEdges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onMove={(_, viewport) => handleViewportChange(viewport)}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        minZoom={0.3}
        maxZoom={2.0}
        className="w-full h-full"
      >
        <Background variant={BackgroundVariant.Dots} gap={24} size={1.5} color="#1e293b" />
        <Controls position="bottom-right" className="!mb-4 !mr-4" />
      </ReactFlow>

      <div className="absolute bottom-4 left-4 z-20 flex items-center gap-4 px-4 py-2 rounded-xl glass-panel text-[11px] font-mono text-slate-300">
        <div className="flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-full bg-emerald-400 shadow-glow-emerald" />
          <span>Mastered</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-full bg-cyan-400 shadow-glow-cyan" />
          <span>Developing</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-full bg-amber-400 shadow-glow-amber" />
          <span>Needs Attention</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-full bg-sky-400 animate-ping" style={{ animationDuration: '3s' }} />
          <span>Current Target</span>
        </div>
      </div>
    </div>
  );
};
