import type { KnowledgeGraphData, ConceptNode, LearningTarget } from '../../api/client';

export interface NextBestStepRecommendation {
  conceptId: string;
  conceptName: string;
  reason: string;
  category: 'ACTIVE_TARGET' | 'READY_TO_ADVANCE' | 'FOUNDATION_REVIEW';
  prerequisiteCount: number;
  completedPrerequisites: number;
}

export interface MasteredChain {
  id: string;
  conceptIds: string[];
  conceptNames: string[];
  length: number;
}

export interface CrossSubjectDiscovery {
  id: string;
  sourceConceptId: string;
  sourceConceptName: string;
  targetConceptId: string;
  targetConceptName: string;
  relationshipType: string;
  explanation: string;
}

const MASTERY_THRESHOLD = 0.75;

/**
 * Identify 1-2 legitimate Next Best Step recommendations derived from the
 * existing learning target and topological prerequisite mastery evidence.
 */
export function determineNextBestSteps(
  graphData: KnowledgeGraphData,
  nextTarget?: LearningTarget | null,
  activeTargetId?: string
): NextBestStepRecommendation[] {
  const recommendations: NextBestStepRecommendation[] = [];
  const conceptMap = new Map<string, ConceptNode>();
  (graphData.concepts || []).forEach((c) => conceptMap.set(c.concept_id, c));

  const targetId = activeTargetId || nextTarget?.concept_id;

  // 1. Primary Recommendation: Authoritative Learning Target from API
  if (targetId && conceptMap.has(targetId)) {
    const targetConcept = conceptMap.get(targetId)!;
    const prereqs = targetConcept.prerequisites || [];
    const completedPrereqs = prereqs.filter((pId) => {
      const p = conceptMap.get(pId);
      return p ? p.mastery >= MASTERY_THRESHOLD : false;
    }).length;

    const reason =
      nextTarget?.reason ||
      (prereqs.length > 0 && completedPrereqs === prereqs.length
        ? 'You have completed the required prerequisites for this concept.'
        : 'Recommended next target based on your active curriculum trajectory.');

    recommendations.push({
      conceptId: targetConcept.concept_id,
      conceptName: targetConcept.name,
      reason,
      category: 'ACTIVE_TARGET',
      prerequisiteCount: prereqs.length,
      completedPrerequisites: completedPrereqs,
    });
  }

  // 2. Secondary Recommendation: Topological readiness
  // Identify a non-mastered concept whose prerequisites are 100% verified mastered
  for (const c of graphData.concepts || []) {
    if (recommendations.some((r) => r.conceptId === c.concept_id)) continue;
    if (c.mastery >= MASTERY_THRESHOLD) continue;

    const prereqs = c.prerequisites || [];
    if (prereqs.length === 0) continue; // Skip root concepts if target exists

    const allPrereqsMastered = prereqs.every((pId) => {
      const p = conceptMap.get(pId);
      return p ? p.mastery >= MASTERY_THRESHOLD : false;
    });

    if (allPrereqsMastered) {
      recommendations.push({
        conceptId: c.concept_id,
        conceptName: c.name,
        reason: 'You have completed the required prerequisites for this concept.',
        category: 'READY_TO_ADVANCE',
        prerequisiteCount: prereqs.length,
        completedPrerequisites: prereqs.length,
      });
      break; // Cap at maximum 2 recommendations total
    }
  }

  // 3. Fallback: If still under 2 and no ready concept found, check for a foundation review candidate
  if (recommendations.length < 2) {
    for (const c of graphData.concepts || []) {
      if (recommendations.some((r) => r.conceptId === c.concept_id)) continue;
      // High uncertainty or low mastery in foundational position
      if (c.mastery < 0.35 && (c.dependents || []).length >= 2) {
        recommendations.push({
          conceptId: c.concept_id,
          conceptName: c.name,
          reason: 'Your recent comprehension signals suggest reviewing this foundation.',
          category: 'FOUNDATION_REVIEW',
          prerequisiteCount: (c.prerequisites || []).length,
          completedPrerequisites: 0,
        });
        break;
      }
    }
  }

  return recommendations.slice(0, 2);
}

/**
 * Detect connected chains of genuinely mastered concepts (mastery >= 0.75).
 * Derives only from verified learner state.
 */
export function detectMasteredChains(graphData: KnowledgeGraphData): MasteredChain[] {
  const conceptMap = new Map<string, ConceptNode>();
  (graphData.concepts || []).forEach((c) => {
    if (c.mastery >= MASTERY_THRESHOLD) {
      conceptMap.set(c.concept_id, c);
    }
  });

  if (conceptMap.size < 2) return [];

  const chains: MasteredChain[] = [];
  const visited = new Set<string>();

  // Trace prerequisite paths between mastered concepts
  for (const [cId, concept] of conceptMap.entries()) {
    if (visited.has(cId)) continue;

    const currentChain: string[] = [cId];
    let curr = concept;

    // Follow mastered downstream dependents
    while (curr) {
      const nextMasteredId = (curr.dependents || []).find((dId) => conceptMap.has(dId) && !currentChain.includes(dId));
      if (nextMasteredId) {
        currentChain.push(nextMasteredId);
        curr = conceptMap.get(nextMasteredId)!;
      } else {
        break;
      }
    }

    if (currentChain.length >= 2) {
      currentChain.forEach((id) => visited.add(id));
      chains.push({
        id: currentChain.join('->'),
        conceptIds: currentChain,
        conceptNames: currentChain.map((id) => conceptMap.get(id)?.name || id),
        length: currentChain.length,
      });
    }
  }

  // Return chains sorted by length descending
  return chains.sort((a, b) => b.length - a.length);
}

/**
 * Identify genuine cross-subject / interdisciplinary relationships present in graphData.
 * Only returns verified relationships already present in canonical graph relationships or source evidence.
 */
export function detectCrossSubjectDiscoveries(
  graphData: KnowledgeGraphData,
  selectedConceptId?: string
): CrossSubjectDiscovery[] {
  const conceptMap = new Map<string, ConceptNode>();
  (graphData.concepts || []).forEach((c) => conceptMap.set(c.concept_id, c));

  const discoveries: CrossSubjectDiscovery[] = [];

  for (const rel of graphData.relationships || []) {
    const isInterdisciplinary =
      rel.type === 'cross_subject' ||
      rel.type === 'interdisciplinary' ||
      rel.type === 'application' ||
      rel.type === 'cross_topic';

    const source = conceptMap.get(rel.source);
    const target = conceptMap.get(rel.target);

    // Also check if relationship links concepts across different topics with an application link
    const isCrossTopic = source && target && source.topic_id && target.topic_id && source.topic_id !== target.topic_id;

    if (isInterdisciplinary || (isCrossTopic && rel.type === 'application')) {
      if (source && target) {
        discoveries.push({
          id: `${rel.source}-${rel.target}`,
          sourceConceptId: source.concept_id,
          sourceConceptName: source.name,
          targetConceptId: target.concept_id,
          targetConceptName: target.name,
          relationshipType: rel.type.replace('_', ' ').toUpperCase(),
          explanation: `Verified interdisciplinary connection linking "${source.name}" with practical application in "${target.name}".`,
        });
      }
    }
  }

  // If a specific concept is selected, prioritize discoveries involving that concept
  if (selectedConceptId) {
    return discoveries.filter(
      (d) => d.sourceConceptId === selectedConceptId || d.targetConceptId === selectedConceptId
    );
  }

  return discoveries;
}
