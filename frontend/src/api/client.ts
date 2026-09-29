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
  definition?: string;
  description?: string;
  topic_id?: string;
  bloom_level?: string;
  mastery: number;
  uncertainty?: number;
  prerequisites: string[];
  dependents?: string[];
  source_references?: { page: number; section: string; quote: string }[];
  status?: string;
  x?: number;
  y?: number;
  subject_id?: string;
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
  name?: string;
  concept_name?: string;
  status: 'COMPLETED' | 'ACTIVE_TARGET' | 'IN_PROGRESS' | 'AVAILABLE' | 'BLOCKED';
  mastery?: number;
  estimated_mastery?: number;
  prerequisites: string[];
}

export interface LearningPath {
  learner_id: string;
  subject_id: string;
  nodes: LearningPathNode[];
}

export interface LearningTarget {
  concept_id: string;
  name?: string;
  concept_name?: string;
  reason: string;
  estimated_minutes?: number;
}

export interface QuestionOption {
  text: string;
}

export interface Question {
  item_id?: string;
  question_id?: string;
  concept_ids: string[];
  prompt?: string;
  question_text?: string;
  options: string[];
  explanation?: string;
  allow_dont_know_option: boolean;
  // correct_answer is intentionally omitted — the server evaluates answers authoritatively
}

export interface TutorResponse {
  concept_id: string;
  concept_name: string;
  intent: string;
  mastery: number;
  response_text: string;
  suggested_actions: string[];
  source_citations: { page: number; section: string; quote: string }[];
  grounded?: boolean;
}

export interface SourceDocument {
  document_id: string;
  title: string;
  filename?: string;
  file_type?: string;
  status: 'READY' | 'PROCESSING' | 'PARTIAL' | 'ERROR';
  recovery_state: string;
  page_count: number;
  file_size_bytes: number;
  is_demo?: boolean;
}

export interface ConceptLearningContent {
  concept_id: string;
  concept_name: string;
  subject_id: string;
  overview: string;
  intuition: string;
  key_principles: string[];
  worked_example: {
    problem: string;
    steps: string[];
    solution: string;
  };
  common_misconceptions: string[];
  key_takeaway: string;
}

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api';

/** Default request timeout. A hung request used to leave the UI spinning forever. */
const REQUEST_TIMEOUT_MS = Number(import.meta.env.VITE_API_TIMEOUT_MS || 120000);

export interface ApiErrorBody {
  code?: string;
  error?: string;
  message?: string;
  recoverable?: boolean;
  details?: Record<string, unknown>;
  detail?: string | ApiErrorBody | Array<{ msg?: string }>;
}

/**
 * Error raised for any failed API call.
 *
 * Carries the backend's machine-readable `code` and `recoverable` flag so the UI can
 * distinguish "your file is unsupported" (show a form error) from "the model provider is
 * rate limited" (offer retry) from "the backend is not running" (offer reconnect).
 */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly recoverable: boolean;
  readonly details: Record<string, unknown>;

  constructor(
    message: string,
    opts: { status?: number; code?: string; recoverable?: boolean; details?: Record<string, unknown> } = {}
  ) {
    super(message);
    this.name = 'ApiError';
    this.status = opts.status ?? 0;
    this.code = opts.code ?? (this.status === 0 ? 'BACKEND_UNREACHABLE' : 'API_ERROR');
    this.recoverable = opts.recoverable ?? (this.status === 0 || this.status >= 500);
    this.details = opts.details ?? {};
  }
}

function describeNetworkFailure(endpoint: string, cause: unknown): ApiError {
  const reason = cause instanceof Error ? cause.message : String(cause);
  // A browser reports every transport failure as "Failed to fetch", which tells the
  // user nothing. Distinguish abort/timeout from a dead or blocked backend.
  if (reason === 'AbortError' || /abort/i.test(reason)) {
    return new ApiError(
      `The request to ${endpoint} timed out after ${Math.round(REQUEST_TIMEOUT_MS / 1000)}s. The backend may be busy processing a large document.`,
      { code: 'REQUEST_TIMEOUT', recoverable: true }
    );
  }
  return new ApiError(
    `Could not reach the LearnSense backend at ${API_BASE_URL}. Check that the API server is running and that CORS allows this origin. (${reason})`,
    { code: 'BACKEND_UNREACHABLE', recoverable: true }
  );
}

function messageFromBody(body: ApiErrorBody | undefined, status: number, statusText: string): ApiError {
  if (!body) {
    return new ApiError(`API request failed with HTTP ${status} ${statusText}.`, { status });
  }

  // FastAPI's typed handler returns { error, code, message, recoverable, details }.
  if (body.code || body.error) {
    const code = body.code || body.error || 'API_ERROR';
    return new ApiError(body.message || `API request failed (${code}).`, {
      status,
      code,
      recoverable: body.recoverable,
      details: body.details,
    });
  }

  // Legacy shape: detail is a string.
  if (typeof body.detail === 'string') {
    return new ApiError(body.detail, { status });
  }

  // FastAPI validation errors: detail is a list of {msg, loc}.
  if (Array.isArray(body.detail) && body.detail.length > 0) {
    const first = body.detail[0];
    return new ApiError(
      `The request was rejected: ${first?.msg || JSON.stringify(body.detail)}`,
      { status, code: 'REQUEST_VALIDATION_FAILED' }
    );
  }

  // detail as an object (e.g. wrapped HTTPException) - never stringify to "[object Object]".
  if (body.detail && typeof body.detail === 'object') {
    const inner = body.detail as ApiErrorBody;
    return new ApiError(inner.message || 'API request failed.', {
      status,
      code: inner.code,
      recoverable: inner.recoverable,
      details: inner.details,
    });
  }

  return new ApiError(body.message || `API request failed with HTTP ${status} ${statusText}.`, { status });
}

async function request<T>(endpoint: string, options?: RequestInit): Promise<T> {
  const url = `${API_BASE_URL}${endpoint}`;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

  try {
    const res = await fetch(url, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...(options?.headers || {}),
      },
      signal: controller.signal,
    });

    if (!res.ok) {
      const body = (await res.json().catch(() => undefined)) as ApiErrorBody | undefined;
      throw messageFromBody(body, res.status, res.statusText);
    }

    if (res.status === 204) {
      return undefined as T;
    }
    return (await res.json()) as T;
  } catch (error) {
    if (error instanceof ApiError) {
      console.warn(`API call failed for ${endpoint} [${error.code}]:`, error.message);
      throw error;
    }
    const apiError = describeNetworkFailure(endpoint, error);
    console.warn(`API call failed for ${endpoint} [${apiError.code}]:`, apiError.message);
    throw apiError;
  } finally {
    clearTimeout(timer);
  }
}

const fetchJson = <T,>(endpoint: string, options?: RequestInit): Promise<T> =>
  request<T>(endpoint, options);

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

  /**
   * Submit diagnostic with raw option text for server-side authoritative evaluation.
   * This is the production flow — the server evaluates correctness, never the client.
   */
  submitDiagnosticRaw: (sessionId: string, responses: Record<string, string>) =>
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
    question_id?: string;
    selected_option?: string;
    selected_index?: number;
    is_dont_know?: boolean;
    correctness?: number;
    all_subject_concept_ids?: string[];
    request_id?: string;
  }) =>
    fetchJson<{
      duplicate_submission: boolean;
      is_correct?: boolean;
      correct_answer?: string;
      explanation?: string;
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

  getConceptQuestion: (subjectId: string, conceptId: string): Promise<{
    question_id: string;
    concept_id: string;
    question_text: string;
    options: string[];
    source_citations?: Array<{
      document_id: string;
      page: number;
      section?: string;
      block_id: string;
      quote: string;
    }>;
  }> => fetchJson(`/subjects/${subjectId}/concepts/${conceptId}/question`),

  getConceptContent: (subjectId: string, conceptId: string): Promise<ConceptLearningContent> =>
    fetchJson(`/subjects/${subjectId}/concepts/${conceptId}/content`),

  getSources: (): Promise<SourceDocument[]> => fetchJson('/sources'),

  cancelUpload: (jobId: string): Promise<{ job_id: string; status: string; message: string }> =>
    fetchJson(`/sources/upload/cancel/${jobId}`, { method: 'POST' }),

  /**
   * Uploads a document. The backend runs the full Phase 1 -> Phase 2 -> Phase 3 chain,
   * which can take a while for large files, so this uses a longer timeout than reads.
   */
  uploadSource: async (
    file: File,
    onProgress?: (stage: string) => void
  ): Promise<{
    document_id: string;
    filename: string;
    title: string;
    status: string;
    page_count: number;
    block_count: number;
    concept_count: number;
    grounded_concept_count: number;
    topic_count: number;
    reused: boolean;
  }> => {
    const formData = new FormData();
    formData.append('file', file);
    onProgress?.('uploading');

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 10 * 60 * 1000);
    try {
      const res = await fetch(`${API_BASE_URL}/sources/upload`, {
        method: 'POST',
        body: formData,
        signal: controller.signal,
      });
      if (!res.ok) {
        const body = (await res.json().catch(() => undefined)) as ApiErrorBody | undefined;
        throw messageFromBody(body, res.status, res.statusText);
      }
      const data = await res.json();

      // --- Async job pattern: backend returns {job_id, status: "processing"} ---
      if (data.job_id && data.status === 'processing') {
        onProgress?.('processing');
        const jobId: string = data.job_id;
        const deadline = Date.now() + 10 * 60 * 1000; // 10 min max
        while (Date.now() < deadline) {
          await new Promise(r => setTimeout(r, 3000));
          const pollRes = await fetch(`${API_BASE_URL}/sources/upload/status/${jobId}`);
          if (!pollRes.ok) continue;
          const poll = await pollRes.json();
          if (poll.status === 'done' && poll.result) return poll.result;
          if (poll.status === 'error') throw new ApiError(poll.error || 'Ingestion failed.');
          const elapsed = Math.round(poll.elapsed_seconds ?? 0);
          onProgress?.(`processing (${elapsed}s elapsed…)`);
        }
        throw new ApiError('Ingestion timed out after 10 minutes.');
      }

      // --- Legacy sync pattern: result returned directly ---
      return data;
    } catch (error) {
      if (error instanceof ApiError) {
        console.warn(`Source upload failed [${error.code}]:`, error.message);
        throw error;
      }
      throw describeNetworkFailure('/sources/upload', error);
    } finally {
      clearTimeout(timer);
    }
  },

  /** Health probe used by the connection banner. */
  checkBackend: async (): Promise<{ ok: boolean; error?: ApiError }> => {
    try {
      await fetchJson('/health');
      return { ok: true };
    } catch (error) {
      return { ok: false, error: error instanceof ApiError ? error : new ApiError(String(error)) };
    }
  },

  /**
   * Resume learner state after browser refresh.
   * Returns persisted progress, onboarding status, and any active assessment.
   */
  resumeLearner: (learnerId: string, subjectId?: string): Promise<{
    learner_id: string;
    has_state: boolean;
    is_onboarded: boolean;
    subject_id: string | null;
    progress: LearnerProgress | null;
    active_assessment_id: string | null;
  }> =>
    fetchJson(`/learners/${learnerId}/resume${subjectId ? `?subject_id=${subjectId}` : ''}`),

  /**
   * Start (or resume) a Final Assessment for a subject.
   * Returns questions with correct_answer and explanation stripped.
   */
  startFinalAssessment: (learnerId: string, subjectId: string): Promise<{
    assessment_id: string;
    subject_id: string;
    resumed: boolean;
    question_count: number;
    questions: Array<{
      item_id?: string;
      question_id?: string;
      concept_ids?: string[];
      prompt?: string;
      question_text?: string;
      options?: string[];
      allow_dont_know_option?: boolean;
    }>;
  }> =>
    fetchJson('/assessment/final/start', {
      method: 'POST',
      body: JSON.stringify({ learner_id: learnerId, subject_id: subjectId }),
    }),

  /**
   * Submit final assessment responses for server-side authoritative evaluation.
   */
  submitFinalAssessment: (data: {
    assessment_id: string;
    learner_id: string;
    subject_id: string;
    responses: Record<string, string>;
    request_id?: string;
  }): Promise<{
    assessment_id: string;
    duplicate_submission: boolean;
    completed: boolean;
    total_questions: number;
    correct_count: number;
    score_pct: number;
    passed: boolean;
    concept_results: Record<string, { question_id: string; correct: boolean; score: number; correct_answer: string; explanation: string }>;
    updated_masteries: Record<string, number>;
    message: string;
  }> =>
    fetchJson('/assessment/final/submit', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  /**
   * Get final assessment status / scorecard.
   */
  getFinalAssessmentStatus: (assessmentId: string, learnerId?: string): Promise<{
    assessment_id: string;
    learner_id: string;
    subject_id: string;
    completed: boolean;
    score_pct: number | null;
    passed: boolean | null;
    total_questions: number;
    correct_count: number;
    concept_results: Record<string, any>;
  }> =>
    fetchJson(`/assessment/final/status/${assessmentId}${learnerId ? `?learner_id=${learnerId}` : ''}`),
};

