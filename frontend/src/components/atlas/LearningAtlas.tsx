import React, { useState, useMemo, useEffect } from 'react';
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

  // Compute Node Layout with spacious grid
  const initialNodes: Node[] = useMemo(() => {
    const topicGrouped: Record<string, ConceptNode[]> = {};

    graphData.concepts.forEach((c) => {
      const matchesSearch =
        c.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        c.definition.toLowerCase().includes(searchQuery.toLowerCase());
      const matchesTopic = filterTopic === 'ALL' || c.topic_id === filterTopic;

      if (matchesSearch && matchesTopic) {
        const topId = c.topic_id || 'default_topic';
        if (!topicGrouped[topId]) topicGrouped[topId] = [];
        topicGrouped[topId].push(c);
      }
    });

    const nodesRes: Node[] = [];
    let topicIndex = 0;

    Object.entries(topicGrouped).forEach(([, concepts]) => {
      const startX = 160 + topicIndex * 450;
      concepts.forEach((concept, conceptIdx) => {
        const x = startX + (conceptIdx % 2) * 60;
        const y = 140 + conceptIdx * 210;

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
    graphData.concepts,
    searchQuery,
    filterTopic,
    activeTargetId,
    selectedConceptId,
    impactedConceptIds,
    isXRayMode,
    zoomLevel,
    onSelectConcept,
  ]);

  // Compute Prerequisite Edges
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
            stroke: isPrereqImpacted ? '#f43f5e' : isTargetEdge ? '#38bdf8' : isXRayMode ? '#8b5cf6' : '#06b6d4',
            strokeWidth: isPrereqImpacted ? 3.5 : isTargetEdge ? 3 : 2,
            strokeDasharray: isXRayMode ? '6 6' : undefined,
          },
          markerEnd: {
            type: MarkerType.ArrowClosed,
            color: isPrereqImpacted ? '#f43f5e' : isTargetEdge ? '#38bdf8' : '#06b6d4',
          },
        });
      });
    });
    return edgesRes;
  }, [graphData.concepts, activeTargetId, impactedConceptIds, isXRayMode]);

  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);

  // Sync React Flow nodes and edges when state updates
  useEffect(() => {
    setNodes(initialNodes);
    setEdges(initialEdges);
  }, [initialNodes, initialEdges, setNodes, setEdges]);

  return (
    <div className="relative w-full h-[720px] rounded-3xl border-2 border-slate-800 bg-slate-950 overflow-hidden shadow-2xl">
      {/* Background Cartographic Territory Overlay */}
      <TerritoryOverlay topics={graphData.topics} />

      {/* Top Controls Bar */}
      <div className="absolute top-4 left-4 right-4 z-30 flex flex-wrap items-center justify-between gap-3 p-3.5 rounded-2xl glass-panel shadow-2xl border border-slate-700/80">
        <div className="flex items-center gap-3">
          <div className="relative flex items-center">
            <Search className="absolute left-3 w-4 h-4 text-cyan-400" />
            <input
              type="text"
              placeholder="Search knowledge territory..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-9 pr-4 py-1.5 text-xs rounded-xl bg-slate-900 border border-slate-700 text-white placeholder-slate-400 focus:outline-none focus:border-cyan-400 w-56 transition-all"
            />
          </div>

          <div className="flex items-center gap-1 bg-slate-900 p-1 rounded-xl border border-slate-700 text-xs">
            <Filter className="w-3.5 h-3.5 text-cyan-400 ml-1" />
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
          <div className="px-3.5 py-1.5 rounded-xl bg-slate-900 border border-slate-700 text-xs font-mono text-slate-200 flex items-center gap-1.5">
            <Layers className="w-3.5 h-3.5 text-cyan-400" />
            <span>ZOOM {zoomLevel}/4</span>
          </div>

          <button
            onClick={onToggleXRay}
            className={`px-4 py-1.5 rounded-xl text-xs font-extrabold tracking-wide flex items-center gap-1.5 transition-all duration-300 ${
              isXRayMode
                ? 'bg-violet-600 text-white shadow-glow-rose ring-2 ring-violet-400'
                : 'bg-slate-800 text-slate-200 border border-slate-700 hover:bg-slate-700'
            }`}
          >
            <Eye className={`w-4 h-4 ${isXRayMode ? 'text-violet-200 animate-pulse' : 'text-slate-400'}`} />
            <span>X-RAY MODE</span>
          </button>
        </div>
      </div>

      {/* Main React Flow Canvas */}
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onMove={(_, viewport) => {
          if (viewport.zoom < 0.6) setZoomLevel(1);
          else if (viewport.zoom < 0.9) setZoomLevel(2);
          else if (viewport.zoom < 1.3) setZoomLevel(3);
          else setZoomLevel(4);
        }}
        fitView
        fitViewOptions={{ padding: 0.3 }}
        minZoom={0.2}
        maxZoom={2.0}
        className="w-full h-full"
      >
        <Background variant={BackgroundVariant.Dots} gap={28} size={2} color="#334155" />
        <Controls position="bottom-right" className="!mb-4 !mr-4" />
      </ReactFlow>

      {/* Bottom Status Legend */}
      <div className="absolute bottom-4 left-4 z-30 flex items-center gap-5 px-4 py-2.5 rounded-xl glass-panel text-xs font-mono font-bold text-slate-200 border border-slate-700/80">
        <div className="flex items-center gap-2">
          <span className="w-3 h-3 rounded-full bg-emerald-400 shadow-glow-emerald" />
          <span>Mastered</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-3 h-3 rounded-full bg-cyan-400 shadow-glow-cyan" />
          <span>Developing</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-3 h-3 rounded-full bg-amber-400 shadow-glow-amber" />
          <span>Needs Attention</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-3 h-3 rounded-full bg-sky-400 animate-ping" style={{ animationDuration: '2.5s' }} />
          <span>Active Target</span>
        </div>
      </div>
    </div>
  );
};
