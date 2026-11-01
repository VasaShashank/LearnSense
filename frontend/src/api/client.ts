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
  concept_ids?: string[];
  concepts_count?: number;
  mastery?: number;
  uncertainty?: number;
  prerequisites?: string[];
  dependents?: string[];
  description?: string;
  concepts?: ConceptNode[];
}

export interface KnowledgeGraphData {
  subject_id: string;
  topics: TopicTerritory[];
  concepts: ConceptNode[];
  relationships: { source: string; target: string; type: string; confidence?: number }[];
  topic_relationships?: { source: string; target: string; type: string; confidence?: number }[];
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

/**
 * The routing state machine, decided by the backend.
 *
 *   NO_USER / SOURCE_SELECTION  -> pick or upload a knowledge source
 *   NEEDS_CALIBRATION           -> self-assessment for that source
 *   VERIFICATION_IN_PROGRESS    -> resume the adaptive verification quiz
 *   VERIFICATION_ERROR          -> question generation failed, retry
 *   VERIFICATION_COMPLETE       -> dashboard / atlas / path
 */
export type EntryStateName =
  | 'NO_USER'
  | 'SOURCE_SELECTION'
  | 'NEEDS_CALIBRATION'
  | 'VERIFICATION_IN_PROGRESS'
  | 'VERIFICATION_ERROR'
  | 'VERIFICATION_COMPLETE';

export interface EntryState {
  learner_id: string;
  subject_id: string | null;
  subject_title?: string | null;
  has_source: boolean;
  entry_state: EntryStateName;
  needs_calibration: boolean;
  session_id: string | null;
  diagnostic_completed: boolean;
  diagnostic_score?: number | null;
  answered_count: number;
  answered_question_ids: string[];
  total_planned: number;
  diagnostic_generation_error?: string | null;
  active_assessment_id: string | null;
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
  status?: string;
  code?: string;
  error?: string;
  reason?: string;
  evidence_status?: string;
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

export interface SourceEvidenceProvenance {
  document_id: string;
  page?: number;
  block_id?: string;
  section?: string;
  evidence_ids?: string[];
}

export interface SourceEvidence {
  text: string;
  provenance: SourceEvidenceProvenance;
}

/**
 * Source-grounded learning content.
 *
 * The backend NEVER fabricates educational claims. It returns only the concept's
 * own definition and verbatim source passages with provenance. If insufficient
 * evidence exists, the API returns 422 and the frontend shows an error state.
 */
export interface ConceptLearningContent {
  concept_id: string;
  concept_name: string;
  definition: string | null;
  source_evidence: SourceEvidence[];
  grounded: boolean;
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


export interface ConceptReviewItem {
  concept_id: string;
  canonical_name: string;
  original_text: string;
  page_number: number;
  pages: number[];
  evidence_excerpt: string;
  block_id: string;
  span?: { start_offset: number; end_offset: number };
  current_canonical_mapping?: {
    canonical_concept_id: string;
    canonical_name: string;
    status: string;
    confidence: number;
    parent_topic?: string | null;
    aliases: string[];
  } | null;
  alternative_canonical_candidates: Array<{
    canonical_concept_id: string;
    canonical_name: string;
    parent_topic?: string;
    aliases: string[];
    similarity: number;
  }>;
  hierarchical_level: string;
  parent_topic_id: string;
  duplicate_candidates: Array<{ concept_id: string; name: string }>;
  review_status: 'pending_review' | 'accepted' | 'rejected' | 'duplicate' | 'needs_canonical_mapping' | 'needs_evidence_review' | 'approved_for_curriculum';
  review_notes?: string;
  reviewed_by?: string | null;
  reviewed_at?: string | null;
}

export interface DocumentReviewResponse {
  document_id: string;
  document_title: string;
  source_filename?: string;
  subject: string;
  chapter: string;
  examination: string;
  target_curriculum: string;
  total_concepts: number;
  status_counts: Record<string, number>;
  concepts: ConceptReviewItem[];
  topics: Array<{
    topic_id: string;
    name: string;
    level: number;
    parent_id?: string | null;
    concept_ids: string[];
  }>;
  prerequisites: Array<{
    source_concept_id: string;
    source_name: string;
    target_concept_id: string;
    target_name: string;
    confidence: number;
    status: 'accepted' | 'rejected' | 'candidate';
    reviewer_id?: string | null;
    reviewed_at?: string | null;
  }>;
  audit_history_count: number;
}

export interface ReviewAuditLogEntry {
  entry_id: string;
  document_id: string;
  concept_id: string;
  action: string;
  reviewer_id: string;
  timestamp: string;
  previous_status: string;
  new_status: string;
  previous_name?: string | null;
  new_name?: string | null;
  reason: string;
  notes: string;
  metadata?: Record<string, any>;
}

export interface PageEvidenceResponse {
  document_id: string;
  page_number: number;
  total_pages: number;
  blocks: Array<{
    block_id: string;
    block_type: string;
    text: string;
    section_title?: string;
  }>;
  raw_text: string;
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
    confidences?: Record<string, string>;
  }) =>
    fetchJson<{ session_id: string; know_concept_ids: string[]; unanswered_concept_ids?: string[]; verify_concept_ids?: string[]; confidences?: Record<string, string> }>('/initialization/self-assessment', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  /**
   * Per-subject onboarding gate: true when the learner has never submitted
   * self-assessment for this subject. Also reports how far the verification
   * quiz got so a refresh can resume it from server state.
   */
  getCalibrationStatus: (learnerId: string, subjectId: string): Promise<{
    learner_id: string;
    subject_id: string;
    needs_calibration: boolean;
    session_id: string | null;
    diagnostic_completed: boolean;
    diagnostic_score?: number | null;
    answered_count?: number;
    answered_question_ids?: string[];
    total_planned?: number;
    diagnostic_generation_error?: string | null;
  }> =>
    fetchJson(`/initialization/status?learner_id=${learnerId}&subject_id=${subjectId}`),

  /**
   * Server-authoritative routing state. The app renders THIS instead of
   * inferring "am I onboarded?" from local booleans, so a stale tab cannot drop
   * a learner onto the ingestion screen or past an unfinished verification.
   */
  getEntryState: (learnerId: string, subjectId?: string): Promise<EntryState> =>
    fetchJson(`/learners/${learnerId}/entry-state${subjectId ? `?subject_id=${subjectId}` : ''}`),

  /** Records the learner's current knowledge source so a reopen resumes it. */
  setActiveSubject: (learnerId: string, subjectId: string): Promise<{ learner_id: string; subject_id: string }> =>
    fetchJson(`/learners/${learnerId}/active-subject?subject_id=${encodeURIComponent(subjectId)}`, {
      method: 'POST',
    }),

  /**
   * Security: the server REQUIRES learner_id for all diagnostic operations so the
   * ownership check can never be skipped by omitting it.
   *
   * Returns the whole plan for backwards compatibility plus `next_question`,
   * `answered_count` and `answered_question_ids` so the client can render the
   * server-chosen next item and restore position after a refresh.
   */
  startDiagnostic: (sessionId: string, learnerId: string) =>
    fetchJson<{
      session_id: string;
      status: 'in_progress' | 'completed' | 'error';
      error?: string | null;
      question_count: number;
      questions: Question[];
      next_question?: Question | null;
      answered_count: number;
      answered_question_ids: string[];
      total_planned: number;
      diagnostic_completed: boolean;
      know_concepts?: string[];
      verify_concepts?: string[];
      diagnostic_priorities?: Record<string, number>;
    }>('/initialization/diagnostic/start', {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId, learner_id: learnerId }),
    }),

  /**
   * Record ONE verification answer. The server grades it against the question
   * bank and returns the next ADAPTIVELY selected item, so the quiz reacts to the
   * previous answer and a refresh resumes rather than restarts.
   *
   * There is intentionally no `correctness` parameter: a client cannot assert its
   * own mastery here.
   */
  submitDiagnosticAnswer: (
    sessionId: string,
    learnerId: string,
    questionId: string,
    selectedOption: string | null,
    isDontKnow: boolean,
  ) =>
    fetchJson<{
      session_id: string;
      question_id: string;
      concept_ids: string[];
      is_correct: boolean;
      duplicate_submission: boolean;
      answered_count: number;
      total_planned: number;
      complete: boolean;
      next_question?: Question | null;
      diagnostic_completed?: boolean;
      diagnostic_score?: number | null;
      updated_masteries?: Record<string, number>;
    }>('/initialization/diagnostic/answer', {
      method: 'POST',
      body: JSON.stringify({
        session_id: sessionId,
        learner_id: learnerId,
        question_id: questionId,
        selected_option: selectedOption,
        is_dont_know: isDontKnow,
      }),
    }),

  submitDiagnostic: (sessionId: string, learnerId: string, responses: Record<string, number>) =>
    fetchJson<{ session_id: string; diagnostic_completed: boolean; diagnostic_score: number; updated_masteries: Record<string, number> }>(
      '/initialization/diagnostic/submit',
      {
        method: 'POST',
        body: JSON.stringify({ session_id: sessionId, learner_id: learnerId, responses }),
      }
    ),

  /**
   * Submit diagnostic with raw option text for server-side authoritative evaluation.
   * This is the production flow — the server evaluates correctness, never the client.
   */
  submitDiagnosticRaw: (sessionId: string, learnerId: string, responses: Record<string, string>) =>
    fetchJson<{ session_id: string; diagnostic_completed: boolean; diagnostic_score: number; updated_masteries: Record<string, number> }>(
      '/initialization/diagnostic/submit',
      {
        method: 'POST',
        body: JSON.stringify({ session_id: sessionId, learner_id: learnerId, responses }),
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

  getConceptQuestion: (subjectId: string, conceptId: string, learnerId?: string): Promise<{
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
    no_questions?: boolean;
    source?: string;
  }> => fetchJson(`/subjects/${subjectId}/concepts/${conceptId}/question${learnerId ? `?learner_id=${encodeURIComponent(learnerId)}` : ''}`),

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
          // Display the stage message from backend if available
          const stage = poll.stage || 'processing...';
          const progress = poll.progress_pct ?? 0;
          onProgress?.(`${stage} (${progress}%)`);
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
    /**
     * True only when the learner has actually COMPLETED verification.
     * A concept state alone is not onboarding -- reading a graph creates one.
     */
    is_onboarded: boolean;
    /**
     * SERVER-AUTHORITATIVE ROUTING STATE. The UI renders this.
     * SOURCE_SELECTION | NEEDS_CALIBRATION | VERIFICATION_IN_PROGRESS
     * | VERIFICATION_ERROR | VERIFICATION_COMPLETE
     */
    entry_state: EntryStateName;
    subject_id: string | null;
    progress: LearnerProgress | null;
    active_assessment_id: string | null;
    active_init_session?: {
      session_id: string;
      subject_id: string;
      know_concept_ids: string[];
      unanswered_concept_ids: string[];
      verify_concept_ids: string[];
      diagnostic_completed: boolean;
      diagnostic_question_ids: string[];
    } | null;
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
    submitted_responses?: Record<string, string>;
    current_question_index?: number;
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

  /**
   * Notation-matched educational video recommendations with timestamp jump links (§9).
   */
  getConceptResources: (
    subjectId: string,
    conceptId: string,
    learnerId?: string,
    topK = 5
  ): Promise<Array<{
    resource_id: string;
    title: string;
    url: string;
    provider: string;
    channel: string;
    duration_seconds: number;
    overall_score: number;
    concept_score: number;
    notation_score: number;
    prerequisite_score: number;
    pedagogical_fit_score: number;
    recommended_timestamp_seconds?: number;
    timestamp_end_seconds?: number;
    matched_segment_text?: string;
    notation_explanation: string;
    matched_formulas: string[];
    match_reasons: string[];
  }>> =>
    fetchJson(
      `/subjects/${subjectId}/concepts/${conceptId}/resources?top_k=${topK}${learnerId ? `&learner_id=${learnerId}` : ''}`
    ),

  /**
   * Get class-level collective knowledge tracing state for teachers (§10.1).
   */
  getClassKnowledgeState: (classId: string, subjectId?: string): Promise<{
    class_id: string;
    subject_id: string;
    subject_title: string;
    total_enrolled: number;
    active_learners: number;
    overall_class_readiness: number;
    concept_distributions: Record<string, any>;
    prerequisite_gap_clusters: any[];
    misconception_clusters: any[];
  }> =>
    fetchJson(`/classes/${classId}/knowledge-state${subjectId ? `?subject_id=${subjectId}` : ''}`),

  /**
   * Generate evidence-grounded Teaching Optimizer intervention plan (§10.2).
   */
  generateTeachingPlan: (
    classId: string,
    data: { subject_id?: string; target_concept_id?: string; duration_minutes?: number }
  ): Promise<any> =>
    fetchJson(`/classes/${classId}/teaching-optimizer/plan`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  /**
   * Approve an instructional intervention plan (§10.3).
   */
  approveTeachingPlan: (
    classId: string,
    interventionId: string,
    teacherNotes?: string
  ): Promise<any> =>
    fetchJson(`/classes/${classId}/interventions/${interventionId}/approve`, {
      method: 'POST',
      body: JSON.stringify({ teacher_notes: teacherNotes }),
    }),

  /**
   * Evaluate learning gains after intervention (§10.3).
   */
  evaluateIntervention: (
    classId: string,
    interventionId: string,
    targetConceptId: string
  ): Promise<any> =>
    fetchJson(`/classes/${classId}/interventions/${interventionId}/evaluate`, {
      method: 'POST',
      body: JSON.stringify({ target_concept_id: targetConceptId }),
    }),

  /**
   * Dynamically aggregated student learning insights for a specific class cohort.
   * Returns difficulty tiers, misconception patterns, attempt volumes, and
   * evidence-based teaching recommendations computed from real class knowledge states.
   */
  getStudentLearningInsights: (classId: string, subjectId?: string): Promise<Array<{
    concept_name: string;
    concept_id: string;
    total_attempts: number;
    common_mistakes: { mistake: string; frequency_pct: number }[];
    avg_first_try_accuracy: number;
    avg_time_to_master_minutes: number;
    difficulty_tier: 'EASY' | 'MODERATE' | 'HARD' | 'VERY_HARD';
    teaching_recommendations: string[];
  }>> =>
    fetchJson(`/classes/${classId}/student-learning-insights${subjectId ? `?subject_id=${subjectId}` : ''}`),

  /**
   * Individual student mastery, concept scores, and intervention guidance for a class.
   */
  getClassStudentsMastery: (classId: string, subjectId?: string): Promise<Array<{
    learner_id: string;
    name: string;
    role: string;
    avatar: string;
    average_mastery: number;
    accuracy_pct: number;
    total_concepts: number;
    mastered_concepts: number;
    developing_concepts: number;
    struggling_concepts: number;
    total_attempts: number;
    total_correct: number;
    assigned_tier: string;
    recommended_intervention: string;
    weakest_concept?: {
      concept_id: string;
      name: string;
      mastery: number;
    };
    concept_breakdown: Array<{
      concept_id: string;
      concept_name: string;
      mastery: number;
      status: 'MASTERED' | 'DEVELOPING' | 'STRUGGLING';
      attempts: number;
      correct: number;
      incorrect: number;
      confidence: number;
      uncertainty: number;
    }>;
  }>> =>
    fetchJson(`/classes/${classId}/student-mastery${subjectId ? `?subject_id=${subjectId}` : ''}`),

  /**
   * Platform-wide aggregated student learning insights (no class required).
   * Used by independent visiting educators without institutional class access.
   */
  getGlobalStudentLearningInsights: (subjectId?: string): Promise<Array<{
    concept_name: string;
    concept_id: string;
    total_attempts: number;
    common_mistakes: { mistake: string; frequency_pct: number }[];
    avg_first_try_accuracy: number;
    avg_time_to_master_minutes: number;
    difficulty_tier: 'EASY' | 'MODERATE' | 'HARD' | 'VERY_HARD';
    teaching_recommendations: string[];
  }>> =>
    fetchJson(`/student-learning-insights${subjectId ? `?subject_id=${subjectId}` : ''}`),

  /**
   * List all registered classes for teacher oversight.
   */
  listClasses: (): Promise<Array<{
    class_id: string;
    subject_id: string;
    class_name: string;
    enrolled_learner_ids: string[];
    updated_at: string;
  }>> =>
    fetchJson('/classes'),

  /**
   * Register or update a classroom cohort roster.
   */
  registerClass: (data: {
    subject_id: string;
    class_name: string;
    enrolled_learner_ids: string[];
  }): Promise<any> =>
    fetchJson('/classes', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  /**
   * List multi-tenant organizations for B2B institutional view.
   */
  listOrganizations: (): Promise<Array<{
    org_id: string;
    name: string;
    domain?: string;
    created_at_iso: string;
  }>> =>
    fetchJson('/institutions/organizations'),

  /**
   * List institutional course classes.
   */
  listInstitutionClasses: (orgId?: string): Promise<Array<{
    class_id: string;
    org_id: string;
    subject_id: string;
    title: string;
    teacher_ids: string[];
    created_at_iso: string;
  }>> =>
    fetchJson(`/institutions/classes${orgId ? `?org_id=${orgId}` : ''}`),

  /**
   * Create an institutional course class / cohort.
   */
  createInstitutionClass: (data: {
    org_id: string;
    subject_id: string;
    title: string;
    teacher_ids: string[];
    creator_user_id: string;
    enrolled_learner_ids?: string[];
  }): Promise<any> =>
    fetchJson('/institutions/classes', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  /**
   * Get class roster with RBAC verification.
   */
  getClassRoster: (classId: string, callerUserId: string): Promise<{ class_id: string; roster: string[] }> =>
    fetchJson(`/institutions/classes/${classId}/roster?caller_user_id=${encodeURIComponent(callerUserId)}`),

  /**
   * Enroll a learner in an institutional class.
   */
  enrollLearnerInClass: (classId: string, learnerId: string, enrollerUserId: string): Promise<any> =>
    fetchJson(`/institutions/classes/${classId}/enroll`, {
      method: 'POST',
      body: JSON.stringify({ learner_id: learnerId, enroller_user_id: enrollerUserId }),
    }),

  /**
   * Get preconfigured personas for switching between Student, Teacher, and B2B Admin modes.
   */

  /**
   * Concept Verification & Curriculum Review (Person 2)
   */
  getDocumentReviewItems: (documentId: string): Promise<DocumentReviewResponse> =>
    fetchJson('/curriculum/documents/' + encodeURIComponent(documentId) + '/review-items'),

  applyConceptReviewDecision: (
    documentId: string,
    payload: {
      concept_id: string;
      decision: string;
      reviewer_id: string;
      reason?: string;
      new_name?: string;
      duplicate_of_concept_id?: string;
      target_canonical_id?: string;
      new_hierarchical_level?: string;
      new_parent_topic_id?: string;
      status?: string;
    }
  ): Promise<any> =>
    fetchJson('/curriculum/documents/' + encodeURIComponent(documentId) + '/review/decision', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  applyPrerequisiteReviewDecision: (
    documentId: string,
    payload: {
      source_concept_id: string;
      target_concept_id: string;
      action: 'approve' | 'reject' | 'add' | 'remove';
      reviewer_id: string;
      reason?: string;
    }
  ): Promise<any> =>
    fetchJson('/curriculum/documents/' + encodeURIComponent(documentId) + '/review/prerequisite', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  approveBatchConcepts: (
    documentId: string,
    payload: { reviewer_id: string; reason?: string }
  ): Promise<any> =>
    fetchJson('/curriculum/documents/' + encodeURIComponent(documentId) + '/review/approve-batch', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  getDocumentReviewAuditHistory: (
    documentId: string
  ): Promise<{ document_id: string; count: number; entries: ReviewAuditLogEntry[] }> =>
    fetchJson('/curriculum/documents/' + encodeURIComponent(documentId) + '/review/audit-history'),

  getDocumentPageEvidence: (
    documentId: string,
    pageNumber: number
  ): Promise<PageEvidenceResponse> =>
    fetchJson('/curriculum/documents/' + encodeURIComponent(documentId) + '/pages/' + pageNumber + '/evidence'),

  getPersonas: (): Promise<Array<{
    id: string;
    name: string;
    role: 'LEARNER' | 'TEACHER' | 'ADMIN';
    title: string;
    avatar: string;
    org_name: string;
    email: string;
  }>> =>
    fetchJson('/auth/personas'),
};


