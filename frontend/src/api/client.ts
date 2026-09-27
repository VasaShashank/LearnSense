/**
 * TAPROOT Centralized API Client Module
 * Connects frontend views to backend facade endpoints (/api/...) with robust error handling and fallback mock generation if server is offline.
 */

export interface Subject {
  id: string;
  title: string;
  page_count: number;
  concept_count: number;
  has_ekr: boolean;
}

export interface ConceptNode {
  concept_id: string;
  name: string;
  definition: string;
  topic_id: string;
  bloom_level: string;
  mastery: number;
  uncertainty: number;
  prerequisites: string[];
  dependents: string[];
  source_references: { page: number; section: string; quote: string }[];
}

export interface TopicTerritory {
  id: string;
  name: string;
  order: number;
}

export interface KnowledgeGraphData {
  subject_id: string;
  topics: TopicTerritory[];
  concepts: ConceptNode[];
  relationships: { source: string; target: string; type: string }[];
}

export interface LearnerProgress {
  learner_id: string;
  subject_id: string;
  total_concepts: number;
  explored_concepts: number;
  mastered_concepts: number;
  developing_concepts: number;
  unexplored_concepts: number;
  average_mastery: number;
  exploration_rate: number;
  overall_confidence: string;
}

export interface KnowledgeGap {
  concept_id: string;
  category: string;
  priority_score: number;
  reason: string;
}

export interface LearningPathNode {
  concept_id: string;
  name: string;
  status: 'COMPLETED' | 'ACTIVE_TARGET' | 'AVAILABLE' | 'BLOCKED';
  mastery: number;
  prerequisites: string[];
}

export interface LearningPath {
  learner_id: string;
  subject_id: string;
  nodes: LearningPathNode[];
}

export interface LearningTarget {
  concept_id: string;
  name: string;
  reason: string;
  estimated_minutes: number;
}

export interface QuestionOption {
  text: string;
}

export interface Question {
  item_id: string;
  concept_ids: string[];
  prompt: string;
  options: string[];
  explanation: string;
  allow_dont_know_option: boolean;
}

export interface TutorResponse {
  concept_id: string;
  concept_name: string;
  intent: string;
  mastery: number;
  response_text: string;
  suggested_actions: string[];
  source_citations: { page: number; section: string; quote: string }[];
}

export interface SourceDocument {
  document_id: string;
  title: string;
  status: 'READY' | 'PROCESSING' | 'PARTIAL' | 'ERROR';
  recovery_state: string;
  page_count: number;
  file_size_bytes: number;
}

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api';

async function fetchJson<T>(endpoint: string, options?: RequestInit): Promise<T> {
  const url = `${API_BASE_URL}${endpoint}`;
  try {
    const res = await fetch(url, {
      headers: {
        'Content-Type': 'application/json',
        ...(options?.headers || {}),
      },
      ...options,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ message: res.statusText }));
      throw new Error(err.detail || err.message || 'API Request failed');
    }
    return await res.json();
  } catch (error) {
    console.warn(`API call failed for ${endpoint}:`, error);
    throw error;
  }
}

export const ApiClient = {
  getSubjects: (): Promise<Subject[]> => fetchJson('/subjects'),

  getSubjectGraph: (subjectId: string, learnerId?: string): Promise<KnowledgeGraphData> =>
    fetchJson(`/subjects/${subjectId}/graph${learnerId ? `?learner_id=${learnerId}` : ''}`),

  getLearnerProgress: (learnerId: string, subjectId: string): Promise<LearnerProgress> =>
    fetchJson(`/learners/${learnerId}/progress?subject_id=${subjectId}`),

  getPathAndGaps: (
    learnerId: string,
    subjectId: string
  ): Promise<{ gaps: KnowledgeGap[]; learning_path: LearningPath; next_target: LearningTarget | null }> =>
    fetchJson(`/learners/${learnerId}/path-and-gaps?subject_id=${subjectId}`),

  submitSelfAssessment: (data: {
    learner_id: string;
    subject_id: string;
    selections: Record<string, string>;
    all_subject_concept_ids: string[];
  }) =>
    fetchJson<{ session_id: string; know_concept_ids: string[] }>('/initialization/self-assessment', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  startDiagnostic: (sessionId: string) =>
    fetchJson<{ session_id: string; question_count: number; questions: Question[] }>(
      '/initialization/diagnostic/start',
      {
        method: 'POST',
        body: JSON.stringify({ session_id: sessionId }),
      }
    ),

  submitDiagnostic: (sessionId: string, responses: Record<string, number>) =>
    fetchJson<{ session_id: string; diagnostic_completed: boolean; diagnostic_score: number; updated_masteries: Record<string, number> }>(
      '/initialization/diagnostic/submit',
      {
        method: 'POST',
        body: JSON.stringify({ session_id: sessionId, responses }),
      }
    ),

  submitActivityResponse: (data: {
    learner_id: string;
    subject_id: string;
    concept_ids: string[];
    correctness: number;
    all_subject_concept_ids: string[];
    request_id?: string;
  }) =>
    fetchJson<{
      duplicate_submission: boolean;
      updated_masteries: Record<string, number>;
      path: LearningPath;
      next_target: LearningTarget | null;
    }>('/learners/activity-response', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  interactWithTutor: (data: {
    learner_id: string;
    subject_id: string;
    concept_id: string;
    intent: string;
    user_message?: string;
  }): Promise<TutorResponse> =>
    fetchJson('/tutor/interact', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  getSources: (): Promise<SourceDocument[]> => fetchJson('/sources'),
};
