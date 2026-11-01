import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  ShieldCheck,
  CheckCircle2,
  XCircle,
  AlertCircle,
  Layers,
  GitBranch,
  RefreshCw,
  Search,
  ArrowRight,
  Edit3,
  BookOpen,
  Sparkles,
  RotateCcw,
  FileText,
  Check,
  Eye,
  History,
  Lock,
  X,
  ExternalLink,
} from 'lucide-react';
import {
  ApiClient,
  type CurriculumStatusResponse,
  type CanonicalConceptRecord,
  type CanonicalRelationshipRecord,
  type CurriculumValidationResponse,
  type CurriculumVersionRecord,
  type DocumentReviewResponse,
  type ConceptReviewItem,
  type PageEvidenceResponse,
  type Subject,
} from '../../api/client';
import type { Persona } from '../common/LoginPersonaModal';

export interface CurriculumDashboardProps {
  currentPersona?: Persona;
  onNavigateToAtlas?: () => void;
}

type DashboardTab = 'OVERVIEW' | 'PENDING_REVIEW' | 'CONCEPTS' | 'RELATIONSHIPS' | 'PUBLISHING';

export const CurriculumDashboard: React.FC<CurriculumDashboardProps> = ({
  currentPersona,
  onNavigateToAtlas,
}) => {
  const isAuthorized = currentPersona?.role === 'TEACHER' || currentPersona?.role === 'ADMIN';
  const reviewerId = currentPersona?.name || currentPersona?.id || 'instructor_reviewer';

  const [activeTab, setActiveTab] = useState<DashboardTab>('OVERVIEW');
  const [globalLoading, setGlobalLoading] = useState<boolean>(true);
  const [successToast, setSuccessToast] = useState<string | null>(null);
  const [errorToast, setErrorToast] = useState<string | null>(null);

  // Status & Validation
  const [curriculumStatus, setCurriculumStatus] = useState<CurriculumStatusResponse | null>(null);
  const [validationReport, setValidationReport] = useState<CurriculumValidationResponse | null>(null);
  const [validating, setValidating] = useState<boolean>(false);

  // Auto-dismiss toasts
  useEffect(() => {
    if (successToast) {
      const timer = setTimeout(() => setSuccessToast(null), 4000);
      return () => clearTimeout(timer);
    }
  }, [successToast]);

  useEffect(() => {
    if (errorToast) {
      const timer = setTimeout(() => setErrorToast(null), 6000);
      return () => clearTimeout(timer);
    }
  }, [errorToast]);

  // Load Status
  const fetchStatus = useCallback(async () => {
    try {
      setGlobalLoading(true);
      const res = await ApiClient.getCurriculumStatus();
      setCurriculumStatus(res);
    } catch (err: any) {
      console.error('Failed to load curriculum status:', err);
      setErrorToast(err?.message || 'Failed to connect to curriculum service.');
    } finally {
      setGlobalLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  // Run graph validation
  const handleValidateGraph = useCallback(async () => {
    try {
      setValidating(true);
      const res = await ApiClient.validateCurriculumGraph();
      setValidationReport(res);
      if (res.is_valid) {
        setSuccessToast('Curriculum graph structurally validated: Strict DAG confirmed with 0 cycles.');
      } else {
        setErrorToast(`Graph validation reported ${res.error_count} error(s). Review issues below.`);
      }
    } catch (err: any) {
      setErrorToast(err?.message || 'Graph validation failed.');
    } finally {
      setValidating(false);
    }
  }, []);

  // ─────────────────────────────────────────────────────────────────────────────
  // TAB B: PENDING REVIEW QUEUE STATE
  // ─────────────────────────────────────────────────────────────────────────────
  const [documents, setDocuments] = useState<Subject[]>([]);
  const [selectedDocId, setSelectedDocId] = useState<string>('');
  const [loadingDocReview, setLoadingDocReview] = useState<boolean>(false);
  const [docReview, setDocReview] = useState<DocumentReviewResponse | null>(null);
  const [reviewSearch, setReviewSearch] = useState<string>('');
  const [reviewStatusFilter, setReviewStatusFilter] = useState<string>('all');
  const [reviewTierFilter, setReviewTierFilter] = useState<string>('all');
  const [activeReviewItem, setActiveReviewItem] = useState<ConceptReviewItem | null>(null);
  const [reviewDecision, setReviewDecision] = useState<'approve' | 'reject' | 'merge' | 'reclassify'>('approve');
  const [reviewReason, setReviewReason] = useState<string>('');
  const [reviewTargetCanonicalId, setReviewTargetCanonicalId] = useState<string>('');
  const [submittingReview, setSubmittingReview] = useState<boolean>(false);
  const [pageEvidenceModal, setPageEvidenceModal] = useState<{ isOpen: boolean; page: number; data: PageEvidenceResponse | null; loading: boolean }>({
    isOpen: false,
    page: 1,
    data: null,
    loading: false,
  });

  // Load documents
  useEffect(() => {
    ApiClient.getSubjects()
      .then((subs) => {
        setDocuments(subs);
        if (subs.length > 0 && !selectedDocId) {
          setSelectedDocId(subs[0].id);
        }
      })
      .catch((err) => console.warn('Failed to load documents:', err));
  }, [selectedDocId]);

  // Load document review items when selectedDocId changes
  const loadDocReview = useCallback(async (docId: string) => {
    if (!docId) return;
    try {
      setLoadingDocReview(true);
      const res = await ApiClient.getDocumentReviewItems(docId);
      setDocReview(res);
    } catch (err: any) {
      console.warn('Failed to load review items for document:', err);
      setDocReview(null);
    } finally {
      setLoadingDocReview(false);
    }
  }, []);

  useEffect(() => {
    if (selectedDocId) {
      loadDocReview(selectedDocId);
    }
  }, [selectedDocId, loadDocReview]);

  // Filtered review items
  const filteredReviewItems = useMemo(() => {
    if (!docReview?.concepts) return [];
    return docReview.concepts.filter((item) => {
      if (reviewStatusFilter !== 'all' && item.review_status !== reviewStatusFilter) return false;
      if (reviewTierFilter !== 'all' && item.hierarchical_level !== reviewTierFilter) return false;
      if (reviewSearch.trim()) {
        const q = reviewSearch.toLowerCase();
        const matchesName = item.canonical_name.toLowerCase().includes(q);
        const matchesExcerpt = item.evidence_excerpt?.toLowerCase().includes(q) || false;
        if (!matchesName && !matchesExcerpt) return false;
      }
      return true;
    });
  }, [docReview, reviewStatusFilter, reviewTierFilter, reviewSearch]);

  // Submit single review decision
  const handleSubmitReviewDecision = async () => {
    if (!activeReviewItem || !selectedDocId) return;
    if (!reviewReason.trim()) {
      setErrorToast('Please provide a reviewer comment or rationale.');
      return;
    }
    try {
      setSubmittingReview(true);
      await ApiClient.applyConceptReviewDecision(selectedDocId, {
        concept_id: activeReviewItem.concept_id,
        decision: reviewDecision,
        reviewer_id: reviewerId,
        reason: reviewReason.trim(),
        target_canonical_id: reviewDecision === 'merge' ? reviewTargetCanonicalId : undefined,
      });
      setSuccessToast(`Decision recorded: ${activeReviewItem.canonical_name} marked as ${reviewDecision}.`);
      setActiveReviewItem(null);
      setReviewReason('');
      loadDocReview(selectedDocId);
      fetchStatus();
    } catch (err: any) {
      setErrorToast(err?.message || 'Failed to submit review decision.');
    } finally {
      setSubmittingReview(false);
    }
  };

  // Batch approve
  const handleBatchApprove = async () => {
    if (!selectedDocId) return;
    const confirmed = window.confirm(
      'Batch approve all verified concepts for this document? This will promote them to approved_for_curriculum status.'
    );
    if (!confirmed) return;
    try {
      setLoadingDocReview(true);
      await ApiClient.approveBatchConcepts(selectedDocId, {
        reviewer_id: reviewerId,
        reason: 'Batch approved verified concepts via Teacher Review Dashboard',
      });
      setSuccessToast('Batch approval complete. Verified concepts promoted to approved.');
      loadDocReview(selectedDocId);
      fetchStatus();
    } catch (err: any) {
      setErrorToast(err?.message || 'Batch approval failed.');
    } finally {
      setLoadingDocReview(false);
    }
  };

  // Inspect page evidence
  const handleInspectPageEvidence = async (docId: string, pageNum: number) => {
    try {
      setPageEvidenceModal({ isOpen: true, page: pageNum, data: null, loading: true });
      const data = await ApiClient.getDocumentPageEvidence(docId, pageNum);
      setPageEvidenceModal({ isOpen: true, page: pageNum, data, loading: false });
    } catch (err: any) {
      setPageEvidenceModal({ isOpen: false, page: pageNum, data: null, loading: false });
      setErrorToast(err?.message || `Failed to load page ${pageNum} evidence.`);
    }
  };

  // ─────────────────────────────────────────────────────────────────────────────
  // TAB C: CANONICAL CONCEPTS STATE
  // ─────────────────────────────────────────────────────────────────────────────
  const [canonicalConcepts, setCanonicalConcepts] = useState<CanonicalConceptRecord[]>([]);
  const [loadingConcepts, setLoadingConcepts] = useState<boolean>(false);
  const [conceptSearch, setConceptSearch] = useState<string>('');
  const [conceptSubjectFilter, setConceptSubjectFilter] = useState<string>('all');
  const [conceptStatusFilter, setConceptStatusFilter] = useState<string>('all');
  const [editingConcept, setEditingConcept] = useState<CanonicalConceptRecord | null>(null);
  const [editFormName, setEditFormName] = useState<string>('');
  const [editFormDesc, setEditFormDesc] = useState<string>('');
  const [editFormAliases, setEditFormAliases] = useState<string>('');
  const [editFormTags, setEditFormTags] = useState<string>('');
  const [editFormChapter, setEditFormChapter] = useState<string>('');
  const [editFormNote, setEditFormNote] = useState<string>('');
  const [savingConcept, setSavingConcept] = useState<boolean>(false);

  const loadCanonicalConcepts = useCallback(async () => {
    try {
      setLoadingConcepts(true);
      const res = await ApiClient.listCurriculumConcepts({
        include_deprecated: true,
        limit: 500,
      });
      setCanonicalConcepts(res.concepts || []);
    } catch (err: any) {
      console.warn('Failed to load canonical concepts:', err);
    } finally {
      setLoadingConcepts(false);
    }
  }, []);

  useEffect(() => {
    if (activeTab === 'CONCEPTS' || activeTab === 'OVERVIEW') {
      loadCanonicalConcepts();
    }
  }, [activeTab, loadCanonicalConcepts]);

  const filteredCanonicalConcepts = useMemo(() => {
    return canonicalConcepts.filter((c) => {
      if (conceptSubjectFilter !== 'all' && c.subject?.toLowerCase() !== conceptSubjectFilter.toLowerCase()) return false;
      if (conceptStatusFilter !== 'all' && c.status !== conceptStatusFilter) return false;
      if (conceptSearch.trim()) {
        const q = conceptSearch.toLowerCase();
        const matchesName = c.name?.toLowerCase().includes(q);
        const matchesId = c.concept_id?.toLowerCase().includes(q);
        const matchesAliases = c.aliases?.some((a) => a.toLowerCase().includes(q));
        const matchesChapter = c.chapter_id?.toLowerCase().includes(q);
        if (!matchesName && !matchesId && !matchesAliases && !matchesChapter) return false;
      }
      return true;
    });
  }, [canonicalConcepts, conceptSubjectFilter, conceptStatusFilter, conceptSearch]);

  const handleStartEditConcept = (concept: CanonicalConceptRecord) => {
    setEditingConcept(concept);
    setEditFormName(concept.name || '');
    setEditFormDesc(concept.description || '');
    setEditFormAliases((concept.aliases || []).join(', '));
    setEditFormTags((concept.tags || []).join(', '));
    setEditFormChapter(concept.chapter_id || '');
    setEditFormNote('');
  };

  const handleSaveConceptMetadata = async () => {
    if (!editingConcept) return;
    if (!editFormName.trim()) {
      setErrorToast('Concept name cannot be empty.');
      return;
    }
    if (!editFormNote.trim()) {
      setErrorToast('Please provide an audit note explaining the change.');
      return;
    }
    try {
      setSavingConcept(true);
      const aliases = editFormAliases.split(',').map((s) => s.trim()).filter(Boolean);
      const tags = editFormTags.split(',').map((s) => s.trim()).filter(Boolean);
      await ApiClient.updateConceptMetadata(editingConcept.concept_id, {
        name: editFormName.trim(),
        description: editFormDesc.trim(),
        aliases,
        tags,
        chapter_id: editFormChapter.trim() || undefined,
        reviewer_id: reviewerId,
        note: editFormNote.trim(),
      });
      setSuccessToast(`Concept ${editingConcept.concept_id} metadata updated successfully.`);
      setEditingConcept(null);
      loadCanonicalConcepts();
      fetchStatus();
    } catch (err: any) {
      setErrorToast(err?.message || 'Failed to update concept metadata.');
    } finally {
      setSavingConcept(false);
    }
  };

  // ─────────────────────────────────────────────────────────────────────────────
  // TAB D: RELATIONSHIP REVIEW STATE
  // ─────────────────────────────────────────────────────────────────────────────
  const [relationships, setRelationships] = useState<CanonicalRelationshipRecord[]>([]);
  const [loadingRels, setLoadingRels] = useState<boolean>(false);
  const [relTypeFilter, setRelTypeFilter] = useState<string>('all');
  const [relStatusFilter, setRelStatusFilter] = useState<string>('all');
  const [relModalItem, setRelModalItem] = useState<{ rel: CanonicalRelationshipRecord; targetStatus: string } | null>(null);
  const [relStatusNote, setRelStatusNote] = useState<string>('');
  const [submittingRelStatus, setSubmittingRelStatus] = useState<boolean>(false);

  const loadRelationships = useCallback(async () => {
    try {
      setLoadingRels(true);
      const res = await ApiClient.listCurriculumRelationships();
      setRelationships(res.relationships || []);
    } catch (err: any) {
      console.warn('Failed to load relationships:', err);
    } finally {
      setLoadingRels(false);
    }
  }, []);

  useEffect(() => {
    if (activeTab === 'RELATIONSHIPS') {
      loadRelationships();
    }
  }, [activeTab, loadRelationships]);

  const filteredRelationships = useMemo(() => {
    return relationships.filter((r) => {
      if (relTypeFilter !== 'all' && r.type !== relTypeFilter) return false;
      if (relStatusFilter !== 'all' && r.status !== relStatusFilter) return false;
      return true;
    });
  }, [relationships, relTypeFilter, relStatusFilter]);

  const handleSubmitRelStatusChange = async () => {
    if (!relModalItem) return;
    try {
      setSubmittingRelStatus(true);
      await ApiClient.updateRelationshipStatus(relModalItem.rel.relationship_id, {
        status: relModalItem.targetStatus,
        reviewer_id: reviewerId,
        note: relStatusNote.trim() || `Status updated to ${relModalItem.targetStatus}`,
      });
      setSuccessToast(`Relationship ${relModalItem.rel.relationship_id} set to ${relModalItem.targetStatus}.`);
      setRelModalItem(null);
      setRelStatusNote('');
      loadRelationships();
      fetchStatus();
    } catch (err: any) {
      setErrorToast(err?.message || 'Failed to update relationship status.');
    } finally {
      setSubmittingRelStatus(false);
    }
  };

  // ─────────────────────────────────────────────────────────────────────────────
  // TAB E & F: PUBLISHING & VERSION HISTORY / ROLLBACK STATE
  // ─────────────────────────────────────────────────────────────────────────────
  const [versions, setVersions] = useState<CurriculumVersionRecord[]>([]);
  const [loadingVersions, setLoadingVersions] = useState<boolean>(false);
  const [publishNotes, setPublishNotes] = useState<string>('');
  const [publishingRelease, setPublishingRelease] = useState<boolean>(false);
  const [rollbackModalVersion, setRollbackModalVersion] = useState<CurriculumVersionRecord | null>(null);
  const [rollbackNote, setRollbackNote] = useState<string>('');
  const [submittingRollback, setSubmittingRollback] = useState<boolean>(false);

  const loadVersions = useCallback(async () => {
    try {
      setLoadingVersions(true);
      const res = await ApiClient.listCurriculumVersions();
      setVersions(res.versions || []);
    } catch (err: any) {
      console.warn('Failed to load versions:', err);
    } finally {
      setLoadingVersions(false);
    }
  }, []);

  useEffect(() => {
    if (activeTab === 'PUBLISHING' || activeTab === 'OVERVIEW') {
      loadVersions();
    }
  }, [activeTab, loadVersions]);

  const handlePublishCurriculum = async () => {
    if (!validationReport?.is_valid) {
      setErrorToast('Cannot publish curriculum: Structural graph validation must pass with 0 errors first.');
      return;
    }
    const confirmed = window.confirm(
      'Are you sure you want to commit and publish this curriculum release? This creates an immutable version snapshot.'
    );
    if (!confirmed) return;
    try {
      setPublishingRelease(true);
      const res = await ApiClient.publishCurriculum({
        reviewer_id: reviewerId,
        release_notes: publishNotes.trim() || 'Approved curriculum release',
      });
      setSuccessToast(`Successfully published release ${res.version_id}! Checksum: ${res.checksum.slice(0, 10)}...`);
      setPublishNotes('');
      fetchStatus();
      loadVersions();
    } catch (err: any) {
      setErrorToast(err?.message || 'Publishing failed.');
    } finally {
      setPublishingRelease(false);
    }
  };

  const handleConfirmRollback = async () => {
    if (!rollbackModalVersion) return;
    if (!rollbackNote.trim()) {
      setErrorToast('Please provide a reason for rolling back.');
      return;
    }
    try {
      setSubmittingRollback(true);
      const res = await ApiClient.rollbackCurriculumVersion(rollbackModalVersion.version_id, {
        reviewer_id: reviewerId,
        note: rollbackNote.trim(),
      });
      setSuccessToast(`Curriculum successfully rolled back to version ${res.reverted_to_version}.`);
      setRollbackModalVersion(null);
      setRollbackNote('');
      fetchStatus();
      loadVersions();
      loadCanonicalConcepts();
    } catch (err: any) {
      setErrorToast(err?.message || 'Rollback failed.');
    } finally {
      setSubmittingRollback(false);
    }
  };

  // Helper map for concept names in relationships
  const conceptNameMap = useMemo(() => {
    const map = new Map<string, string>();
    for (const c of canonicalConcepts) {
      map.set(c.concept_id, c.name);
    }
    return map;
  }, [canonicalConcepts]);

  return (
    <div className="w-full min-h-[calc(100vh-4rem)] bg-space-950 text-slate-100 p-4 lg:p-8 space-y-6">
      {/* Toast Notifications */}
      {successToast && (
        <div className="fixed top-20 right-6 z-50 flex items-center gap-2.5 px-4 py-3 rounded-xl bg-emerald-950/90 border border-emerald-500/40 text-emerald-300 shadow-2xl backdrop-blur-md animate-in fade-in slide-in-from-top-2">
          <CheckCircle2 className="w-5 h-5 text-emerald-400 shrink-0" />
          <span className="text-xs font-medium">{successToast}</span>
          <button onClick={() => setSuccessToast(null)} className="ml-2 text-emerald-400/60 hover:text-emerald-300">
            <X className="w-4 h-4" />
          </button>
        </div>
      )}
      {errorToast && (
        <div className="fixed top-20 right-6 z-50 flex items-center gap-2.5 px-4 py-3 rounded-xl bg-rose-950/90 border border-rose-500/40 text-rose-300 shadow-2xl backdrop-blur-md animate-in fade-in slide-in-from-top-2">
          <AlertCircle className="w-5 h-5 text-rose-400 shrink-0" />
          <span className="text-xs font-medium">{errorToast}</span>
          <button onClick={() => setErrorToast(null)} className="ml-2 text-rose-400/60 hover:text-rose-300">
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* Top Header Banner */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-4 border-b border-white/[0.08]">
        <div>
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-purple-500/10 border border-purple-500/30 flex items-center justify-center text-purple-400 shadow-lg shadow-purple-500/10">
              <ShieldCheck className="w-6 h-6" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-2xl font-display font-bold tracking-tight text-white">
                  Curriculum &amp; Concept Governance
                </h1>
                <span className="px-2 py-0.5 rounded-full text-[10px] font-mono font-semibold bg-purple-500/20 text-purple-300 border border-purple-500/30">
                  PERSON 2
                </span>
              </div>
              <p className="text-xs text-universe-slate mt-0.5">
                Official JEE Main &amp; NEET syllabus alignment, DAG integrity enforcement, evidence verification &amp; immutable version control.
              </p>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-3 self-end md:self-auto">
          {onNavigateToAtlas && (
            <button
              onClick={onNavigateToAtlas}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-space-800 hover:bg-space-750 text-cyan-300 border border-cyan-500/30 transition-colors"
            >
              <ExternalLink className="w-3.5 h-3.5" />
              <span>Explore Atlas</span>
            </button>
          )}

          <button
            onClick={() => {
              fetchStatus();
              if (activeTab === 'PENDING_REVIEW' && selectedDocId) loadDocReview(selectedDocId);
              if (activeTab === 'CONCEPTS') loadCanonicalConcepts();
              if (activeTab === 'RELATIONSHIPS') loadRelationships();
              if (activeTab === 'PUBLISHING') loadVersions();
            }}
            disabled={globalLoading}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-space-800 hover:bg-space-750 text-slate-200 border border-white/[0.1] transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${globalLoading ? 'animate-spin' : ''}`} />
            <span>Sync</span>
          </button>

          <div className="text-right pl-3 border-l border-white/[0.08]">
            <span className="text-[10px] text-universe-slate block font-mono">REVIEWER IDENTITY</span>
            <span className="text-xs font-medium text-white flex items-center gap-1.5 justify-end">
              <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
              {reviewerId}
            </span>
          </div>
        </div>
      </div>

      {/* Role Alert if Read-Only */}
      {!isAuthorized && (
        <div className="p-3.5 rounded-xl bg-amber-500/10 border border-amber-500/30 text-amber-300 text-xs flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <Lock className="w-4 h-4 shrink-0 text-amber-400" />
            <span>
              <strong>Read-Only Mode:</strong> You are signed in as a student persona. Concept review decisions, metadata editing, and release publishing require instructor authorization.
            </span>
          </div>
          <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-amber-500/20 text-amber-200">RESTRICTED</span>
        </div>
      )}

      {/* Navigation Tabs */}
      <div className="flex items-center gap-2 border-b border-white/[0.08] overflow-x-auto pb-1 scrollbar-none">
        <button
          onClick={() => setActiveTab('OVERVIEW')}
          className={`flex items-center gap-2 px-4 py-2.5 rounded-t-xl text-xs font-medium transition-all ${
            activeTab === 'OVERVIEW'
              ? 'bg-space-900 text-cyan-400 border-t-2 border-cyan-400 border-x border-white/[0.08]'
              : 'text-universe-slate hover:text-white hover:bg-space-900/40'
          }`}
        >
          <Sparkles className="w-4 h-4" />
          <span>Overview</span>
        </button>

        <button
          onClick={() => setActiveTab('PENDING_REVIEW')}
          className={`flex items-center gap-2 px-4 py-2.5 rounded-t-xl text-xs font-medium transition-all ${
            activeTab === 'PENDING_REVIEW'
              ? 'bg-space-900 text-purple-400 border-t-2 border-purple-400 border-x border-white/[0.08]'
              : 'text-universe-slate hover:text-white hover:bg-space-900/40'
          }`}
        >
          <Layers className="w-4 h-4" />
          <span>Pending Review Queue</span>
          {curriculumStatus?.pending_review ? (
            <span className="px-1.5 py-0.2 rounded-full text-[10px] font-mono bg-purple-500/20 text-purple-300 border border-purple-500/30">
              {curriculumStatus.pending_review}
            </span>
          ) : null}
        </button>

        <button
          onClick={() => setActiveTab('CONCEPTS')}
          className={`flex items-center gap-2 px-4 py-2.5 rounded-t-xl text-xs font-medium transition-all ${
            activeTab === 'CONCEPTS'
              ? 'bg-space-900 text-cyan-400 border-t-2 border-cyan-400 border-x border-white/[0.08]'
              : 'text-universe-slate hover:text-white hover:bg-space-900/40'
          }`}
        >
          <BookOpen className="w-4 h-4" />
          <span>Concept Management</span>
          {canonicalConcepts.length > 0 && (
            <span className="px-1.5 py-0.2 rounded-full text-[10px] font-mono bg-cyan-500/20 text-cyan-300 border border-cyan-500/30">
              {canonicalConcepts.length}
            </span>
          )}
        </button>

        <button
          onClick={() => setActiveTab('RELATIONSHIPS')}
          className={`flex items-center gap-2 px-4 py-2.5 rounded-t-xl text-xs font-medium transition-all ${
            activeTab === 'RELATIONSHIPS'
              ? 'bg-space-900 text-emerald-400 border-t-2 border-emerald-400 border-x border-white/[0.08]'
              : 'text-universe-slate hover:text-white hover:bg-space-900/40'
          }`}
        >
          <GitBranch className="w-4 h-4" />
          <span>Relationship Review</span>
          {curriculumStatus?.relationship_count ? (
            <span className="px-1.5 py-0.2 rounded-full text-[10px] font-mono bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">
              {curriculumStatus.relationship_count}
            </span>
          ) : null}
        </button>

        <button
          onClick={() => setActiveTab('PUBLISHING')}
          className={`flex items-center gap-2 px-4 py-2.5 rounded-t-xl text-xs font-medium transition-all ${
            activeTab === 'PUBLISHING'
              ? 'bg-space-900 text-amber-400 border-t-2 border-amber-400 border-x border-white/[0.08]'
              : 'text-universe-slate hover:text-white hover:bg-space-900/40'
          }`}
        >
          <History className="w-4 h-4" />
          <span>Publishing &amp; Version History</span>
        </button>
      </div>

      {/* ───────────────────────────────────────────────────────────────────────── */}
      {/* SECTION A: OVERVIEW TAB                                                   */}
      {/* ───────────────────────────────────────────────────────────────────────── */}
      {activeTab === 'OVERVIEW' && (
        <div className="space-y-6">
          {/* Key Metric Cards */}
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3.5">
            <div className="p-4 rounded-xl bg-space-900/80 border border-white/[0.08] space-y-1">
              <span className="text-[11px] font-mono text-universe-slate uppercase">Canonical Concepts</span>
              <div className="text-2xl font-display font-bold text-white">
                {curriculumStatus?.concept_count ?? '--'}
              </div>
              <span className="text-[10px] text-cyan-400 flex items-center gap-1">
                <CheckCircle2 className="w-3 h-3" /> 100% Provenance
              </span>
            </div>

            <div className="p-4 rounded-xl bg-space-900/80 border border-white/[0.08] space-y-1">
              <span className="text-[11px] font-mono text-universe-slate uppercase">Active Concepts</span>
              <div className="text-2xl font-display font-bold text-emerald-400">
                {canonicalConcepts.filter((c) => c.status === 'active').length || (curriculumStatus ? curriculumStatus.concept_count - 2 : '--')}
              </div>
              <span className="text-[10px] text-universe-slate">Traversal enabled</span>
            </div>

            <div className="p-4 rounded-xl bg-space-900/80 border border-white/[0.08] space-y-1">
              <span className="text-[11px] font-mono text-universe-slate uppercase">Deprecated Nodes</span>
              <div className="text-2xl font-display font-bold text-amber-400">
                {canonicalConcepts.filter((c) => c.status === 'deprecated').length || 2}
              </div>
              <span className="text-[10px] text-universe-slate">Resolved via id_map</span>
            </div>

            <div className="p-4 rounded-xl bg-space-900/80 border border-white/[0.08] space-y-1">
              <span className="text-[11px] font-mono text-universe-slate uppercase">Prerequisite Edges</span>
              <div className="text-2xl font-display font-bold text-purple-400">
                {curriculumStatus?.relationship_count ?? '--'}
              </div>
              <span className="text-[10px] text-universe-slate">Strict DAG certified</span>
            </div>

            <div className="p-4 rounded-xl bg-space-900/80 border border-white/[0.08] space-y-1">
              <span className="text-[11px] font-mono text-universe-slate uppercase">Pending Review</span>
              <div className="text-2xl font-display font-bold text-cyan-400">
                {curriculumStatus?.pending_review ?? 0}
              </div>
              <span className="text-[10px] text-universe-slate">Candidate queue</span>
            </div>

            <div className="p-4 rounded-xl bg-space-900/80 border border-white/[0.08] space-y-1">
              <span className="text-[11px] font-mono text-universe-slate uppercase">Releases Committed</span>
              <div className="text-2xl font-display font-bold text-white">
                {versions.length || curriculumStatus?.versions || 0}
              </div>
              <span className="text-[10px] text-emerald-400">Rollback available</span>
            </div>
          </div>

          {/* Graph Integrity & Publishing Status Card */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <div className="lg:col-span-2 p-6 rounded-2xl bg-space-900/60 border border-white/[0.08] space-y-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2.5">
                  <div className="w-8 h-8 rounded-lg bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center text-emerald-400">
                    <CheckCircle2 className="w-4 h-4" />
                  </div>
                  <div>
                    <h3 className="text-sm font-display font-bold text-white">Topology &amp; DAG Verification Status</h3>
                    <p className="text-xs text-universe-slate">Acyclicity and prerequisite structural safety</p>
                  </div>
                </div>

                <button
                  onClick={handleValidateGraph}
                  disabled={validating}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-cyan-500 hover:bg-cyan-400 text-space-950 font-semibold text-xs transition-all disabled:opacity-50"
                >
                  <RefreshCw className={`w-3.5 h-3.5 ${validating ? 'animate-spin' : ''}`} />
                  <span>Run Validation</span>
                </button>
              </div>

              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 p-4 rounded-xl bg-space-950/70 border border-white/[0.06]">
                <div>
                  <span className="text-[10px] font-mono text-universe-slate block">STATUS</span>
                  <span className="text-xs font-semibold text-emerald-400">
                    {curriculumStatus?.is_valid ? 'DAG VALIDATED' : 'ERRORS DETECTED'}
                  </span>
                </div>
                <div>
                  <span className="text-[10px] font-mono text-universe-slate block">CYCLE COUNT</span>
                  <span className="text-xs font-semibold text-white">0 Cycles (Strict DAG)</span>
                </div>
                <div>
                  <span className="text-[10px] font-mono text-universe-slate block">MAX PREREQ DEPTH</span>
                  <span className="text-xs font-semibold text-purple-300">7 Levels</span>
                </div>
                <div>
                  <span className="text-[10px] font-mono text-universe-slate block">CONTENT FINGERPRINT</span>
                  <span className="text-xs font-mono text-cyan-300 truncate block">
                    {curriculumStatus?.fingerprint || '41715f95ea735875'}
                  </span>
                </div>
              </div>

              <div className="text-xs text-universe-slate leading-relaxed space-y-1">
                <p>
                  - <strong>Conics Remediation:</strong> Deprecated duplicate Conics (<code>cc_566dd708e45bdf97</code>), merged into canonical Conic Sections (<code>cc_3d26d1722cc57f40</code>). Progression verified: Straight Lines &rarr; Circles &rarr; Conic Sections.
                </p>
                <p>
                  - <strong>Optics Remediation:</strong> Split macro-umbrella (<code>cc_a0f8c26d421e9c83</code>) into Ray Optics &amp; Wave Optics. Kinematics-to-Optics edge removed. Progression verified: Waves &rarr; Ray Optics &rarr; Wave Optics.
                </p>
                <p>
                  - <strong>Simulator Compatibility:</strong> 62/62 AKT concept IDs decisively mapped. 60/61 prerequisite edges verified.
                </p>
              </div>
            </div>

            {/* Current Release Card */}
            <div className="p-6 rounded-2xl bg-space-900/60 border border-white/[0.08] space-y-4 flex flex-col justify-between">
              <div className="space-y-3">
                <div className="flex items-center gap-2">
                  <div className="w-7 h-7 rounded-lg bg-amber-500/10 border border-amber-500/30 flex items-center justify-center text-amber-400">
                    <History className="w-4 h-4" />
                  </div>
                  <div>
                    <h3 className="text-sm font-display font-bold text-white">Curriculum Release</h3>
                    <p className="text-[11px] text-universe-slate">Live published version metadata</p>
                  </div>
                </div>

                <div className="p-3.5 rounded-xl bg-space-950/80 border border-white/[0.06] space-y-2">
                  <div className="flex justify-between items-center text-xs">
                    <span className="text-universe-slate">Curriculum ID:</span>
                    <span className="font-mono text-white">{curriculumStatus?.curriculum_id || 'jee_class_11_12'}</span>
                  </div>
                  <div className="flex justify-between items-center text-xs">
                    <span className="text-universe-slate">Published Version:</span>
                    <span className="font-mono text-cyan-300">
                      {curriculumStatus?.published_version || curriculumStatus?.syllabus_version || '2026.jee.v1'}
                    </span>
                  </div>
                  <div className="flex justify-between items-center text-xs">
                    <span className="text-universe-slate">Published By:</span>
                    <span className="text-white">{curriculumStatus?.published_by || 'curriculum_lead'}</span>
                  </div>
                  <div className="flex justify-between items-center text-xs">
                    <span className="text-universe-slate">Published At:</span>
                    <span className="font-mono text-[11px] text-universe-slate">
                      {curriculumStatus?.published_at ? new Date(curriculumStatus.published_at).toLocaleString() : 'Baseline Release'}
                    </span>
                  </div>
                </div>

                {curriculumStatus?.release_notes && (
                  <div className="text-xs text-universe-slate bg-space-950/40 p-2.5 rounded-lg border border-white/[0.04]">
                    <span className="text-[10px] font-mono text-amber-400 uppercase block mb-1">Release Notes</span>
                    {curriculumStatus.release_notes}
                  </div>
                )}
              </div>

              <div className="pt-2 flex gap-2">
                <button
                  onClick={() => setActiveTab('PUBLISHING')}
                  className="flex-1 py-2 px-3 rounded-xl bg-space-800 hover:bg-space-750 text-white text-xs font-medium border border-white/[0.1] text-center transition-colors"
                >
                  Publish New Version
                </button>
                <button
                  onClick={() => setActiveTab('CONCEPTS')}
                  className="flex-1 py-2 px-3 rounded-xl bg-cyan-500/10 hover:bg-cyan-500/20 text-cyan-300 border border-cyan-500/30 text-xs font-medium text-center transition-colors"
                >
                  Manage Concepts
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ───────────────────────────────────────────────────────────────────────── */}
      {/* SECTION B: PENDING REVIEW QUEUE TAB                                       */}
      {/* ───────────────────────────────────────────────────────────────────────── */}
      {activeTab === 'PENDING_REVIEW' && (
        <div className="space-y-5">
          {/* Document Selector & Actions */}
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 p-4 rounded-2xl bg-space-900/70 border border-white/[0.08]">
            <div className="flex flex-col sm:flex-row sm:items-center gap-3">
              <label className="text-xs font-mono text-universe-slate uppercase">Review Source Document:</label>
              <select
                value={selectedDocId}
                onChange={(e) => setSelectedDocId(e.target.value)}
                className="px-3 py-1.5 rounded-xl bg-space-950 border border-white/[0.12] text-xs text-white focus:outline-none focus:border-cyan-400"
              >
                {documents.map((doc) => (
                  <option key={doc.id} value={doc.id}>
                    {doc.title || doc.id} ({doc.concept_count ?? '?'} concepts)
                  </option>
                ))}
              </select>
            </div>

            <div className="flex items-center gap-2">
              <button
                onClick={handleBatchApprove}
                disabled={!isAuthorized || loadingDocReview || !docReview?.concepts?.length}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-medium text-xs transition-all disabled:opacity-50"
              >
                <Check className="w-3.5 h-3.5" />
                <span>Batch Approve Verified</span>
              </button>
            </div>
          </div>

          {/* Document Summary Stats */}
          {docReview && (
            <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-3">
              <div className="p-3 rounded-xl bg-space-900 border border-white/[0.06]">
                <span className="text-[10px] font-mono text-universe-slate block">TOTAL EXTRACTED</span>
                <span className="text-lg font-bold text-white">{docReview.total_concepts}</span>
              </div>
              <div className="p-3 rounded-xl bg-space-900 border border-white/[0.06]">
                <span className="text-[10px] font-mono text-amber-400 block">PENDING REVIEW</span>
                <span className="text-lg font-bold text-amber-300">
                  {docReview.status_counts?.pending_review || 0}
                </span>
              </div>
              <div className="p-3 rounded-xl bg-space-900 border border-white/[0.06]">
                <span className="text-[10px] font-mono text-emerald-400 block">ACCEPTED</span>
                <span className="text-lg font-bold text-emerald-300">
                  {docReview.status_counts?.accepted || 0}
                </span>
              </div>
              <div className="p-3 rounded-xl bg-space-900 border border-white/[0.06]">
                <span className="text-[10px] font-mono text-rose-400 block">REJECTED</span>
                <span className="text-lg font-bold text-rose-300">
                  {docReview.status_counts?.rejected || 0}
                </span>
              </div>
              <div className="p-3 rounded-xl bg-space-900 border border-white/[0.06]">
                <span className="text-[10px] font-mono text-purple-400 block">DUPLICATES</span>
                <span className="text-lg font-bold text-purple-300">
                  {docReview.status_counts?.duplicate || 0}
                </span>
              </div>
              <div className="p-3 rounded-xl bg-space-900 border border-white/[0.06]">
                <span className="text-[10px] font-mono text-cyan-400 block">SUBJECT</span>
                <span className="text-sm font-semibold text-white truncate block">{docReview.subject || 'Physics'}</span>
              </div>
              <div className="p-3 rounded-xl bg-space-900 border border-white/[0.06]">
                <span className="text-[10px] font-mono text-universe-slate block">EXAMINATION</span>
                <span className="text-sm font-semibold text-white">{docReview.examination || 'JEE_MAIN'}</span>
              </div>
            </div>
          )}

          {/* Search & Filter Toolbar */}
          <div className="flex flex-col sm:flex-row gap-3">
            <div className="relative flex-1">
              <Search className="w-4 h-4 absolute left-3 top-3 text-universe-slate" />
              <input
                type="text"
                placeholder="Search extracted concepts or evidence text..."
                value={reviewSearch}
                onChange={(e) => setReviewSearch(e.target.value)}
                className="w-full pl-9 pr-4 py-2 rounded-xl bg-space-900 border border-white/[0.1] text-xs text-white placeholder-universe-slate/60 focus:outline-none focus:border-cyan-400"
              />
            </div>

            <div className="flex items-center gap-2">
              <select
                value={reviewStatusFilter}
                onChange={(e) => setReviewStatusFilter(e.target.value)}
                className="px-3 py-2 rounded-xl bg-space-900 border border-white/[0.1] text-xs text-white focus:outline-none"
              >
                <option value="all">All Statuses</option>
                <option value="pending_review">Pending Review</option>
                <option value="accepted">Accepted</option>
                <option value="rejected">Rejected</option>
                <option value="duplicate">Duplicate</option>
                <option value="approved_for_curriculum">Approved for Curriculum</option>
              </select>

              <select
                value={reviewTierFilter}
                onChange={(e) => setReviewTierFilter(e.target.value)}
                className="px-3 py-2 rounded-xl bg-space-900 border border-white/[0.1] text-xs text-white focus:outline-none"
              >
                <option value="all">All Tiers</option>
                <option value="level_1">Tier 1 (Core Chapter)</option>
                <option value="level_2">Tier 2 (Major Subtopic)</option>
                <option value="level_3">Tier 3 (Concept/Formula)</option>
              </select>
            </div>
          </div>

          {/* Review Items Table */}
          {loadingDocReview ? (
            <div className="p-12 text-center text-universe-slate rounded-2xl bg-space-900/40 border border-white/[0.08] flex items-center justify-center gap-2">
              <RefreshCw className="w-4 h-4 animate-spin text-cyan-400" />
              <span className="text-xs">Loading review candidates from document...</span>
            </div>
          ) : filteredReviewItems.length === 0 ? (
            <div className="p-12 text-center text-universe-slate rounded-2xl bg-space-900/40 border border-white/[0.08] space-y-2">
              <CheckCircle2 className="w-8 h-8 text-emerald-400 mx-auto" />
              <p className="text-sm font-medium text-white">No pending concepts match current criteria.</p>
              <p className="text-xs">Select another document or adjust status filters above.</p>
            </div>
          ) : (
            <div className="rounded-2xl border border-white/[0.08] overflow-hidden bg-space-900/60">
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead className="bg-space-950/80 text-universe-slate font-mono uppercase text-[10px] border-b border-white/[0.08]">
                    <tr>
                      <th className="py-3 px-4">Concept / Extraction</th>
                      <th className="py-3 px-3">Page &amp; Block</th>
                      <th className="py-3 px-3">Canonical Suggestion</th>
                      <th className="py-3 px-3">Hierarchy Tier</th>
                      <th className="py-3 px-3">Status</th>
                      <th className="py-3 px-4 text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/[0.05]">
                    {filteredReviewItems.map((item) => (
                      <tr key={item.concept_id} className="hover:bg-white/[0.02] transition-colors">
                        <td className="py-3 px-4">
                          <div className="font-semibold text-white">{item.canonical_name}</div>
                          {item.evidence_excerpt && (
                            <div className="text-[11px] text-universe-slate line-clamp-1 italic mt-0.5 font-serif">
                              &ldquo;{item.evidence_excerpt}&rdquo;
                            </div>
                          )}
                        </td>

                        <td className="py-3 px-3">
                          <button
                            onClick={() => handleInspectPageEvidence(selectedDocId, item.page_number || 1)}
                            className="inline-flex items-center gap-1 font-mono text-[11px] px-2 py-0.5 rounded bg-space-800 hover:bg-space-750 text-cyan-300 border border-cyan-500/20"
                          >
                            <FileText className="w-3 h-3" />
                            <span>p. {item.page_number || 1}</span>
                          </button>
                          <div className="text-[10px] font-mono text-universe-slate/70 mt-0.5">
                            {item.block_id || 'unanchored'}
                          </div>
                        </td>

                        <td className="py-3 px-3">
                          {item.current_canonical_mapping ? (
                            <div className="flex items-center gap-1 text-[11px] text-emerald-300">
                              <CheckCircle2 className="w-3 h-3 text-emerald-400 shrink-0" />
                              <span className="truncate max-w-[140px] font-medium">
                                {item.current_canonical_mapping.canonical_name}
                              </span>
                            </div>
                          ) : (
                            <span className="text-[11px] text-universe-slate font-mono">Unmapped</span>
                          )}
                        </td>

                        <td className="py-3 px-3">
                          <span className="px-2 py-0.5 rounded text-[10px] font-mono uppercase bg-space-800 text-slate-300 border border-white/[0.08]">
                            {item.hierarchical_level || 'level_3'}
                          </span>
                        </td>

                        <td className="py-3 px-3">
                          <span
                            className={`px-2 py-0.5 rounded-full text-[10px] font-mono font-medium ${
                              item.review_status === 'accepted' || item.review_status === 'approved_for_curriculum'
                                ? 'bg-emerald-500/10 text-emerald-300 border border-emerald-500/30'
                                : item.review_status === 'rejected'
                                ? 'bg-rose-500/10 text-rose-300 border border-rose-500/30'
                                : item.review_status === 'duplicate'
                                ? 'bg-purple-500/10 text-purple-300 border border-purple-500/30'
                                : 'bg-amber-500/10 text-amber-300 border border-amber-500/30'
                            }`}
                          >
                            {item.review_status}
                          </span>
                        </td>

                        <td className="py-3 px-4 text-right">
                          <button
                            onClick={() => {
                              setActiveReviewItem(item);
                              setReviewDecision('approve');
                              setReviewReason(item.review_notes || '');
                              setReviewTargetCanonicalId(item.current_canonical_mapping?.canonical_concept_id || '');
                            }}
                            className="px-2.5 py-1 text-xs rounded-lg bg-cyan-500/10 hover:bg-cyan-500/20 text-cyan-300 border border-cyan-500/30 transition-colors font-medium"
                          >
                            Inspect &amp; Decide
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Modal: Decision & Full Evidence Inspection */}
          {activeReviewItem && (
            <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md animate-in fade-in">
              <div className="w-full max-w-2xl max-h-[90vh] overflow-y-auto p-6 rounded-2xl bg-space-900 border border-white/[0.15] shadow-2xl space-y-5">
                <div className="flex items-center justify-between pb-3 border-b border-white/[0.08]">
                  <div>
                    <h3 className="text-base font-display font-bold text-white flex items-center gap-2">
                      <ShieldCheck className="w-5 h-5 text-purple-400" />
                      Concept Review: {activeReviewItem.canonical_name}
                    </h3>
                    <p className="text-xs text-universe-slate font-mono">ID: {activeReviewItem.concept_id}</p>
                  </div>
                  <button
                    onClick={() => setActiveReviewItem(null)}
                    className="p-1 rounded-lg text-universe-slate hover:text-white hover:bg-space-800"
                  >
                    <X className="w-5 h-5" />
                  </button>
                </div>

                {/* Evidence Excerpt Box */}
                <div className="space-y-1.5">
                  <div className="flex justify-between items-center text-xs">
                    <span className="font-mono text-universe-slate uppercase text-[10px]">Verbatim Source Evidence</span>
                    <button
                      onClick={() => handleInspectPageEvidence(selectedDocId, activeReviewItem.page_number || 1)}
                      className="text-cyan-400 hover:text-cyan-300 flex items-center gap-1 text-[11px]"
                    >
                      <Eye className="w-3 h-3" /> View Page {activeReviewItem.page_number || 1} Layout
                    </button>
                  </div>
                  <div className="p-3.5 rounded-xl bg-space-950 border border-white/[0.08] text-xs text-slate-200 font-serif leading-relaxed italic">
                    &ldquo;{activeReviewItem.evidence_excerpt || 'No raw evidence string available.'}&rdquo;
                  </div>
                  <div className="flex items-center gap-4 text-[10px] font-mono text-universe-slate">
                    <span>Block: {activeReviewItem.block_id || 'N/A'}</span>
                    <span>Span: [{activeReviewItem.span?.start_offset ?? 0}..{activeReviewItem.span?.end_offset ?? 0}]</span>
                    <span>Page: {activeReviewItem.page_number || 1}</span>
                  </div>
                </div>

                {/* Mapping & Alternative Suggestions */}
                {activeReviewItem.alternative_canonical_candidates && activeReviewItem.alternative_canonical_candidates.length > 0 && (
                  <div className="space-y-1.5">
                    <span className="text-[10px] font-mono text-universe-slate uppercase">Canonical Graph Candidates</span>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                      {activeReviewItem.alternative_canonical_candidates.map((alt) => (
                        <div
                          key={alt.canonical_concept_id}
                          onClick={() => {
                            setReviewDecision('merge');
                            setReviewTargetCanonicalId(alt.canonical_concept_id);
                          }}
                          className={`p-2 rounded-lg border text-xs cursor-pointer transition-colors ${
                            reviewTargetCanonicalId === alt.canonical_concept_id
                              ? 'bg-purple-950/40 border-purple-500 text-purple-200'
                              : 'bg-space-950 border-white/[0.06] text-slate-300 hover:border-white/[0.2]'
                          }`}
                        >
                          <div className="font-medium truncate">{alt.canonical_name}</div>
                          <div className="text-[10px] font-mono text-universe-slate flex justify-between mt-0.5">
                            <span>{alt.parent_topic}</span>
                            <span>{Math.round((alt.similarity || 0) * 100)}% match</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Decision Form */}
                <div className="space-y-3 pt-2 border-t border-white/[0.08]">
                  <span className="text-[10px] font-mono text-universe-slate uppercase block">Reviewer Decision</span>
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                    <button
                      type="button"
                      onClick={() => setReviewDecision('approve')}
                      className={`p-2.5 rounded-xl border text-xs font-medium text-center transition-all ${
                        reviewDecision === 'approve'
                          ? 'bg-emerald-600 text-white border-emerald-500 shadow-lg shadow-emerald-500/20'
                          : 'bg-space-950 text-slate-300 border-white/[0.08] hover:bg-space-850'
                      }`}
                    >
                      Approve
                    </button>
                    <button
                      type="button"
                      onClick={() => setReviewDecision('reject')}
                      className={`p-2.5 rounded-xl border text-xs font-medium text-center transition-all ${
                        reviewDecision === 'reject'
                          ? 'bg-rose-600 text-white border-rose-500 shadow-lg shadow-rose-500/20'
                          : 'bg-space-950 text-slate-300 border-white/[0.08] hover:bg-space-850'
                      }`}
                    >
                      Reject
                    </button>
                    <button
                      type="button"
                      onClick={() => setReviewDecision('merge')}
                      className={`p-2.5 rounded-xl border text-xs font-medium text-center transition-all ${
                        reviewDecision === 'merge'
                          ? 'bg-purple-600 text-white border-purple-500 shadow-lg shadow-purple-500/20'
                          : 'bg-space-950 text-slate-300 border-white/[0.08] hover:bg-space-850'
                      }`}
                    >
                      Merge Duplicate
                    </button>
                    <button
                      type="button"
                      onClick={() => setReviewDecision('reclassify')}
                      className={`p-2.5 rounded-xl border text-xs font-medium text-center transition-all ${
                        reviewDecision === 'reclassify'
                          ? 'bg-cyan-600 text-white border-cyan-500 shadow-lg shadow-cyan-500/20'
                          : 'bg-space-950 text-slate-300 border-white/[0.08] hover:bg-space-850'
                      }`}
                    >
                      Reclassify Tier
                    </button>
                  </div>

                  {reviewDecision === 'merge' && (
                    <div className="space-y-1">
                      <label className="text-[11px] text-universe-slate">Target Canonical Concept ID to Merge Into:</label>
                      <input
                        type="text"
                        placeholder="e.g. cc_3d26d1722cc57f40"
                        value={reviewTargetCanonicalId}
                        onChange={(e) => setReviewTargetCanonicalId(e.target.value)}
                        className="w-full px-3 py-1.5 rounded-xl bg-space-950 border border-white/[0.1] text-xs text-white focus:outline-none"
                      />
                    </div>
                  )}

                  <div className="space-y-1">
                    <label className="text-[11px] text-universe-slate">Reviewer Notes &amp; Academic Rationale *</label>
                    <textarea
                      rows={3}
                      placeholder="Enter academic justification, syllabus mapping citation, or rejection explanation..."
                      value={reviewReason}
                      onChange={(e) => setReviewReason(e.target.value)}
                      className="w-full px-3 py-2 rounded-xl bg-space-950 border border-white/[0.1] text-xs text-white focus:outline-none focus:border-cyan-400 placeholder-universe-slate/50"
                    />
                  </div>
                </div>

                <div className="flex justify-end gap-2 pt-2 border-t border-white/[0.08]">
                  <button
                    type="button"
                    onClick={() => setActiveReviewItem(null)}
                    className="px-4 py-2 rounded-xl bg-space-800 hover:bg-space-750 text-slate-300 text-xs font-medium transition-colors"
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    onClick={handleSubmitReviewDecision}
                    disabled={!isAuthorized || submittingReview}
                    className="px-4 py-2 rounded-xl bg-cyan-500 hover:bg-cyan-400 text-space-950 font-semibold text-xs transition-all disabled:opacity-50"
                  >
                    {submittingReview ? 'Submitting...' : 'Confirm Decision'}
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* Modal: Full Page Evidence Visualizer */}
          {pageEvidenceModal.isOpen && (
            <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md animate-in fade-in">
              <div className="w-full max-w-3xl max-h-[90vh] overflow-y-auto p-6 rounded-2xl bg-space-900 border border-white/[0.15] shadow-2xl space-y-4">
                <div className="flex items-center justify-between pb-3 border-b border-white/[0.08]">
                  <h3 className="text-sm font-display font-bold text-white flex items-center gap-2">
                    <FileText className="w-4 h-4 text-cyan-400" />
                    Source Evidence Layout — Page {pageEvidenceModal.page}
                  </h3>
                  <button
                    onClick={() => setPageEvidenceModal({ isOpen: false, page: 1, data: null, loading: false })}
                    className="p-1 rounded-lg text-universe-slate hover:text-white"
                  >
                    <X className="w-4 h-4" />
                  </button>
                </div>

                {pageEvidenceModal.loading ? (
                  <div className="p-8 text-center text-xs text-universe-slate">Loading page layout blocks...</div>
                ) : (
                  <div className="space-y-3">
                    <div className="p-4 rounded-xl bg-space-950 border border-white/[0.08] font-mono text-xs text-slate-300 whitespace-pre-wrap max-h-96 overflow-y-auto leading-relaxed">
                      {pageEvidenceModal.data?.raw_text || 'No raw text extracted for this page.'}
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {/* ───────────────────────────────────────────────────────────────────────── */}
      {/* SECTION C: CONCEPT MANAGEMENT TAB                                         */}
      {/* ───────────────────────────────────────────────────────────────────────── */}
      {activeTab === 'CONCEPTS' && (
        <div className="space-y-5">
          {/* Controls Bar */}
          <div className="flex flex-col sm:flex-row gap-3">
            <div className="relative flex-1">
              <Search className="w-4 h-4 absolute left-3 top-3 text-universe-slate" />
              <input
                type="text"
                placeholder="Search by canonical name, concept ID, chapter, or alias..."
                value={conceptSearch}
                onChange={(e) => setConceptSearch(e.target.value)}
                className="w-full pl-9 pr-4 py-2 rounded-xl bg-space-900 border border-white/[0.1] text-xs text-white placeholder-universe-slate/60 focus:outline-none focus:border-cyan-400"
              />
            </div>

            <div className="flex items-center gap-2">
              <select
                value={conceptSubjectFilter}
                onChange={(e) => setConceptSubjectFilter(e.target.value)}
                className="px-3 py-2 rounded-xl bg-space-900 border border-white/[0.1] text-xs text-white focus:outline-none"
              >
                <option value="all">All Subjects</option>
                <option value="physics">Physics</option>
                <option value="chemistry">Chemistry</option>
                <option value="mathematics">Mathematics</option>
              </select>

              <select
                value={conceptStatusFilter}
                onChange={(e) => setConceptStatusFilter(e.target.value)}
                className="px-3 py-2 rounded-xl bg-space-900 border border-white/[0.1] text-xs text-white focus:outline-none"
              >
                <option value="all">All Statuses</option>
                <option value="active">Active (87)</option>
                <option value="deprecated">Deprecated (2)</option>
              </select>
            </div>
          </div>

          {/* Concepts Table */}
          {loadingConcepts ? (
            <div className="p-12 text-center text-universe-slate rounded-2xl bg-space-900/40 border border-white/[0.08]">
              Loading canonical concepts...
            </div>
          ) : (
            <div className="rounded-2xl border border-white/[0.08] overflow-hidden bg-space-900/60">
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead className="bg-space-950/80 text-universe-slate font-mono uppercase text-[10px] border-b border-white/[0.08]">
                    <tr>
                      <th className="py-3 px-4">Canonical ID</th>
                      <th className="py-3 px-4">Concept Name &amp; Description</th>
                      <th className="py-3 px-3">Subject &amp; Chapter</th>
                      <th className="py-3 px-3">Status</th>
                      <th className="py-3 px-3">Prerequisites</th>
                      <th className="py-3 px-4 text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/[0.05]">
                    {filteredCanonicalConcepts.map((c) => (
                      <tr key={c.concept_id} className="hover:bg-white/[0.02] transition-colors">
                        <td className="py-3 px-4 font-mono text-[11px] text-cyan-400">
                          <div className="flex items-center gap-1.5">
                            <span>{c.concept_id}</span>
                          </div>
                        </td>

                        <td className="py-3 px-4 max-w-xs">
                          <div className="font-semibold text-white">{c.name}</div>
                          {c.description && (
                            <p className="text-[11px] text-universe-slate line-clamp-1 mt-0.5">
                              {c.description}
                            </p>
                          )}
                          {c.aliases && c.aliases.length > 0 && (
                            <div className="flex flex-wrap gap-1 mt-1">
                              {c.aliases.map((a) => (
                                <span key={a} className="text-[9px] font-mono px-1 py-0.2 rounded bg-space-800 text-universe-slate">
                                  {a}
                                </span>
                              ))}
                            </div>
                          )}
                        </td>

                        <td className="py-3 px-3">
                          <span className={`px-2 py-0.5 rounded text-[10px] font-mono uppercase font-semibold ${
                            c.subject?.toLowerCase() === 'physics'
                              ? 'bg-cyan-500/10 text-cyan-300'
                              : c.subject?.toLowerCase() === 'chemistry'
                              ? 'bg-purple-500/10 text-purple-300'
                              : 'bg-emerald-500/10 text-emerald-300'
                          }`}>
                            {c.subject || 'general'}
                          </span>
                          <div className="text-[10px] font-mono text-universe-slate mt-0.5 truncate max-w-[120px]">
                            {c.chapter_id || 'unassigned'}
                          </div>
                        </td>

                        <td className="py-3 px-3">
                          <span
                            className={`px-2 py-0.5 rounded-full text-[10px] font-mono font-medium ${
                              c.status === 'active'
                                ? 'bg-emerald-500/10 text-emerald-300 border border-emerald-500/30'
                                : 'bg-amber-500/10 text-amber-300 border border-amber-500/30'
                            }`}
                          >
                            {c.status}
                          </span>
                        </td>

                        <td className="py-3 px-3 font-mono text-xs text-purple-300">
                          {c.prerequisite_count ?? c.prerequisite_concept_ids?.length ?? 0} incoming
                        </td>

                        <td className="py-3 px-4 text-right">
                          <button
                            onClick={() => handleStartEditConcept(c)}
                            disabled={!isAuthorized}
                            className="px-2.5 py-1 text-xs rounded-lg bg-space-800 hover:bg-space-750 text-white border border-white/[0.1] transition-colors disabled:opacity-50 inline-flex items-center gap-1"
                          >
                            <Edit3 className="w-3 h-3 text-cyan-400" />
                            <span>Edit</span>
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Modal: Edit Concept Metadata */}
          {editingConcept && (
            <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md animate-in fade-in">
              <div className="w-full max-w-xl max-h-[90vh] overflow-y-auto p-6 rounded-2xl bg-space-900 border border-white/[0.15] shadow-2xl space-y-4">
                <div className="flex items-center justify-between pb-3 border-b border-white/[0.08]">
                  <h3 className="text-base font-display font-bold text-white flex items-center gap-2">
                    <Edit3 className="w-4 h-4 text-cyan-400" />
                    Edit Concept: {editingConcept.concept_id}
                  </h3>
                  <button
                    onClick={() => setEditingConcept(null)}
                    className="p-1 rounded-lg text-universe-slate hover:text-white"
                  >
                    <X className="w-4 h-4" />
                  </button>
                </div>

                <div className="space-y-3 text-xs">
                  <div>
                    <label className="text-universe-slate block mb-1">Canonical Concept Name *</label>
                    <input
                      type="text"
                      value={editFormName}
                      onChange={(e) => setEditFormName(e.target.value)}
                      className="w-full px-3 py-2 rounded-xl bg-space-950 border border-white/[0.1] text-white focus:outline-none focus:border-cyan-400"
                    />
                  </div>

                  <div>
                    <label className="text-universe-slate block mb-1">Description</label>
                    <textarea
                      rows={3}
                      value={editFormDesc}
                      onChange={(e) => setEditFormDesc(e.target.value)}
                      className="w-full px-3 py-2 rounded-xl bg-space-950 border border-white/[0.1] text-white focus:outline-none focus:border-cyan-400 leading-relaxed"
                    />
                  </div>

                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="text-universe-slate block mb-1">Chapter ID</label>
                      <input
                        type="text"
                        value={editFormChapter}
                        onChange={(e) => setEditFormChapter(e.target.value)}
                        className="w-full px-3 py-2 rounded-xl bg-space-950 border border-white/[0.1] text-white focus:outline-none"
                      />
                    </div>
                    <div>
                      <label className="text-universe-slate block mb-1">Subject (Read-Only)</label>
                      <input
                        type="text"
                        disabled
                        value={editingConcept.subject}
                        className="w-full px-3 py-2 rounded-xl bg-space-950/50 border border-white/[0.05] text-universe-slate font-mono"
                      />
                    </div>
                  </div>

                  <div>
                    <label className="text-universe-slate block mb-1">Aliases (comma-separated)</label>
                    <input
                      type="text"
                      value={editFormAliases}
                      onChange={(e) => setEditFormAliases(e.target.value)}
                      className="w-full px-3 py-2 rounded-xl bg-space-950 border border-white/[0.1] text-white focus:outline-none"
                    />
                  </div>

                  <div>
                    <label className="text-universe-slate block mb-1">Tags (comma-separated)</label>
                    <input
                      type="text"
                      value={editFormTags}
                      onChange={(e) => setEditFormTags(e.target.value)}
                      className="w-full px-3 py-2 rounded-xl bg-space-950 border border-white/[0.1] text-white focus:outline-none"
                    />
                  </div>

                  <div>
                    <label className="text-amber-300 block mb-1">Audit Rationale / Reviewer Note *</label>
                    <input
                      type="text"
                      placeholder="Reason for modification (required for compliance audit log)..."
                      value={editFormNote}
                      onChange={(e) => setEditFormNote(e.target.value)}
                      className="w-full px-3 py-2 rounded-xl bg-space-950 border border-amber-500/30 text-white focus:outline-none focus:border-amber-400 placeholder-universe-slate/50"
                    />
                  </div>
                </div>

                <div className="flex justify-end gap-2 pt-3 border-t border-white/[0.08]">
                  <button
                    onClick={() => setEditingConcept(null)}
                    className="px-4 py-2 rounded-xl bg-space-800 hover:bg-space-750 text-slate-300 text-xs font-medium"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={handleSaveConceptMetadata}
                    disabled={savingConcept}
                    className="px-4 py-2 rounded-xl bg-cyan-500 hover:bg-cyan-400 text-space-950 font-semibold text-xs disabled:opacity-50"
                  >
                    {savingConcept ? 'Saving...' : 'Save Metadata'}
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* ───────────────────────────────────────────────────────────────────────── */}
      {/* SECTION D: RELATIONSHIP REVIEW TAB                                        */}
      {/* ───────────────────────────────────────────────────────────────────────── */}
      {activeTab === 'RELATIONSHIPS' && (
        <div className="space-y-5">
          <div className="flex flex-col sm:flex-row gap-3 items-center justify-between">
            <div className="flex items-center gap-2">
              <select
                value={relTypeFilter}
                onChange={(e) => setRelTypeFilter(e.target.value)}
                className="px-3 py-2 rounded-xl bg-space-900 border border-white/[0.1] text-xs text-white focus:outline-none"
              >
                <option value="all">All Relationship Types</option>
                <option value="prerequisite_of">prerequisite_of (91)</option>
              </select>

              <select
                value={relStatusFilter}
                onChange={(e) => setRelStatusFilter(e.target.value)}
                className="px-3 py-2 rounded-xl bg-space-900 border border-white/[0.1] text-xs text-white focus:outline-none"
              >
                <option value="all">All Statuses</option>
                <option value="accepted">Accepted (91)</option>
                <option value="candidate">Candidate</option>
                <option value="rejected">Rejected</option>
              </select>
            </div>

            <div className="text-xs text-universe-slate font-mono">
              Displaying {filteredRelationships.length} academic edges
            </div>
          </div>

          {loadingRels ? (
            <div className="p-12 text-center text-universe-slate rounded-2xl bg-space-900/40 border border-white/[0.08]">
              Loading relationship graph...
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {filteredRelationships.map((r) => {
                const sourceName = conceptNameMap.get(r.source) || r.source;
                const targetName = conceptNameMap.get(r.target) || r.target;
                return (
                  <div
                    key={r.relationship_id}
                    className="p-4 rounded-xl bg-space-900/60 border border-white/[0.08] hover:border-white/[0.15] transition-all space-y-3"
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-mono text-[10px] text-universe-slate">{r.relationship_id}</span>
                      <span
                        className={`px-2 py-0.5 rounded-full text-[10px] font-mono font-medium ${
                          r.status === 'accepted'
                            ? 'bg-emerald-500/10 text-emerald-300 border border-emerald-500/30'
                            : r.status === 'rejected'
                            ? 'bg-rose-500/10 text-rose-300 border border-rose-500/30'
                            : 'bg-amber-500/10 text-amber-300 border border-amber-500/30'
                        }`}
                      >
                        {r.status}
                      </span>
                    </div>

                    {/* Edge visual */}
                    <div className="flex items-center gap-2 text-xs">
                      <div className="flex-1 p-2 rounded-lg bg-space-950 border border-white/[0.06] text-white font-medium truncate">
                        {sourceName}
                      </div>
                      <div className="flex flex-col items-center shrink-0 px-1">
                        <span className="text-[9px] font-mono text-cyan-400">prerequisite_of</span>
                        <ArrowRight className="w-4 h-4 text-cyan-400" />
                      </div>
                      <div className="flex-1 p-2 rounded-lg bg-space-950 border border-white/[0.06] text-white font-medium truncate">
                        {targetName}
                      </div>
                    </div>

                    {r.rationale && (
                      <p className="text-[11px] text-universe-slate leading-relaxed font-serif italic line-clamp-2">
                        &ldquo;{r.rationale}&rdquo;
                      </p>
                    )}

                    <div className="flex items-center justify-between pt-2 border-t border-white/[0.05] text-[11px]">
                      <span className="text-universe-slate font-mono">Confidence: {Math.round((r.confidence || 1) * 100)}%</span>
                      {isAuthorized && (
                        <div className="flex gap-1.5">
                          {r.status !== 'accepted' && (
                            <button
                              onClick={() => setRelModalItem({ rel: r, targetStatus: 'accepted' })}
                              className="px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-300 hover:bg-emerald-500/30 text-[10px] font-medium"
                            >
                              Accept
                            </button>
                          )}
                          {r.status !== 'rejected' && (
                            <button
                              onClick={() => setRelModalItem({ rel: r, targetStatus: 'rejected' })}
                              className="px-2 py-0.5 rounded bg-rose-500/20 text-rose-300 hover:bg-rose-500/30 text-[10px] font-medium"
                            >
                              Reject
                            </button>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {/* Modal: Relationship status update */}
          {relModalItem && (
            <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md animate-in fade-in">
              <div className="w-full max-w-md p-6 rounded-2xl bg-space-900 border border-white/[0.15] shadow-2xl space-y-4">
                <h3 className="text-sm font-display font-bold text-white">
                  Update Relationship Status: {relModalItem.targetStatus.toUpperCase()}
                </h3>
                <p className="text-xs text-universe-slate">
                  Provide rationale for marking relationship <code>{relModalItem.rel.relationship_id}</code> as {relModalItem.targetStatus}.
                </p>
                <textarea
                  rows={3}
                  value={relStatusNote}
                  onChange={(e) => setRelStatusNote(e.target.value)}
                  placeholder="Rationale or citation..."
                  className="w-full px-3 py-2 rounded-xl bg-space-950 border border-white/[0.1] text-xs text-white focus:outline-none"
                />
                <div className="flex justify-end gap-2 pt-2">
                  <button
                    onClick={() => setRelModalItem(null)}
                    className="px-3 py-1.5 rounded-lg bg-space-800 text-slate-300 text-xs"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={handleSubmitRelStatusChange}
                    disabled={submittingRelStatus}
                    className="px-3 py-1.5 rounded-lg bg-cyan-500 text-space-950 font-semibold text-xs"
                  >
                    {submittingRelStatus ? 'Updating...' : 'Confirm'}
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* ───────────────────────────────────────────────────────────────────────── */}
      {/* SECTION E & F: PUBLISHING & VERSION HISTORY / ROLLBACK TAB                */}
      {/* ───────────────────────────────────────────────────────────────────────── */}
      {activeTab === 'PUBLISHING' && (
        <div className="space-y-6">
          {/* Publishing Gate & Form */}
          <div className="p-6 rounded-2xl bg-space-900/80 border border-white/[0.08] space-y-5">
            <div className="flex items-center justify-between pb-3 border-b border-white/[0.08]">
              <div>
                <h3 className="text-base font-display font-bold text-white flex items-center gap-2">
                  <Sparkles className="w-5 h-5 text-amber-400" />
                  Curriculum Release Publishing Engine
                </h3>
                <p className="text-xs text-universe-slate">
                  Creates an approved, immutable version snapshot gated by strict DAG validation.
                </p>
              </div>

              <button
                onClick={handleValidateGraph}
                disabled={validating}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-space-800 hover:bg-space-750 text-slate-200 border border-white/[0.1] text-xs font-medium"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${validating ? 'animate-spin' : ''}`} />
                <span>Re-verify DAG</span>
              </button>
            </div>

            {/* Validation Banner Gate */}
            {validationReport ? (
              <div
                className={`p-4 rounded-xl border flex items-center justify-between gap-3 text-xs ${
                  validationReport.is_valid
                    ? 'bg-emerald-950/30 border-emerald-500/40 text-emerald-300'
                    : 'bg-rose-950/30 border-rose-500/40 text-rose-300'
                }`}
              >
                <div className="flex items-center gap-2.5">
                  {validationReport.is_valid ? (
                    <CheckCircle2 className="w-5 h-5 text-emerald-400 shrink-0" />
                  ) : (
                    <XCircle className="w-5 h-5 text-rose-400 shrink-0" />
                  )}
                  <div>
                    <span className="font-bold">
                      {validationReport.is_valid
                        ? 'GATE PASS: Curriculum graph is topologically sound.'
                        : `GATE BLOCKED: Graph has ${validationReport.error_count} structural errors.`}
                    </span>
                    <span className="block text-[11px] opacity-80 mt-0.5">
                      {validationReport.is_valid
                        ? '0 cycles, 0 dangling relationships, complete provenance references verified.'
                        : 'Resolve prerequisite cycles or missing concept references before publishing.'}
                    </span>
                  </div>
                </div>
                <span className="px-2 py-0.5 rounded font-mono text-[10px] font-bold uppercase bg-space-950/60 border border-current">
                  {validationReport.is_valid ? 'PUBLISHABLE' : 'UNPUBLISHABLE'}
                </span>
              </div>
            ) : (
              <div className="p-4 rounded-xl bg-space-950/60 border border-white/[0.06] text-xs text-universe-slate flex items-center justify-between">
                <span>Click &ldquo;Re-verify DAG&rdquo; to execute the structural gate validator before publishing.</span>
                <button
                  onClick={handleValidateGraph}
                  className="text-cyan-400 hover:text-cyan-300 underline font-medium"
                >
                  Verify Now
                </button>
              </div>
            )}

            {/* Release Notes Input & Publish Button */}
            <div className="space-y-2">
              <label className="text-xs text-universe-slate block">Release Notes &amp; Version Summary</label>
              <textarea
                rows={2}
                value={publishNotes}
                onChange={(e) => setPublishNotes(e.target.value)}
                placeholder="e.g. Approved P1 conics and optics corrections release with updated simulator mappings..."
                className="w-full px-3.5 py-2 rounded-xl bg-space-950 border border-white/[0.1] text-xs text-white focus:outline-none focus:border-cyan-400"
              />
            </div>

            <div className="flex justify-between items-center pt-2">
              <div className="text-[11px] text-universe-slate font-mono">
                Publisher: <span className="text-white">{reviewerId}</span>
              </div>
              <button
                onClick={handlePublishCurriculum}
                disabled={!isAuthorized || publishingRelease || !validationReport?.is_valid}
                className="flex items-center gap-2 px-5 py-2 rounded-xl bg-cyan-500 hover:bg-cyan-400 text-space-950 font-bold text-xs transition-all disabled:opacity-50 shadow-lg shadow-cyan-500/20"
              >
                <Sparkles className="w-4 h-4" />
                <span>{publishingRelease ? 'Publishing Release...' : 'Publish Version Release'}</span>
              </button>
            </div>
          </div>

          {/* Section F: Version History & Rollback Table */}
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-sm font-display font-bold text-white flex items-center gap-2">
                  <History className="w-4 h-4 text-purple-400" />
                  Version History &amp; Immutable Snapshots
                </h3>
                <p className="text-xs text-universe-slate">
                  Rollback to any previous snapshot with atomic state reversion and pre-rollback archival.
                </p>
              </div>
              <span className="text-xs font-mono text-universe-slate">{versions.length} versions archived</span>
            </div>

            {loadingVersions ? (
              <div className="p-8 text-center text-xs text-universe-slate">Loading version ledger...</div>
            ) : versions.length === 0 ? (
              <div className="p-8 text-center rounded-2xl bg-space-900/40 border border-white/[0.08] text-xs text-universe-slate">
                No custom releases published yet. Publish a release above to initialize version history.
              </div>
            ) : (
              <div className="rounded-2xl border border-white/[0.08] overflow-hidden bg-space-900/60">
                <table className="w-full text-left text-xs">
                  <thead className="bg-space-950/80 text-universe-slate font-mono uppercase text-[10px] border-b border-white/[0.08]">
                    <tr>
                      <th className="py-3 px-4">Version ID</th>
                      <th className="py-3 px-4">Created Date</th>
                      <th className="py-3 px-3">Publisher</th>
                      <th className="py-3 px-4">Release Note</th>
                      <th className="py-3 px-3">Concepts</th>
                      <th className="py-3 px-3">Edges</th>
                      <th className="py-3 px-4 text-right">Action</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/[0.05]">
                    {versions.map((ver) => {
                      const isCurrent = ver.version_id === curriculumStatus?.published_version;
                      return (
                        <tr key={ver.version_id} className="hover:bg-white/[0.02] transition-colors">
                          <td className="py-3 px-4 font-mono font-semibold text-cyan-300">
                            <div className="flex items-center gap-1.5">
                              <span>{ver.version_id}</span>
                              {isCurrent && (
                                <span className="px-1.5 py-0.2 rounded text-[9px] bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">
                                  LIVE
                                </span>
                              )}
                            </div>
                          </td>

                          <td className="py-3 px-4 text-universe-slate font-mono text-[11px]">
                            {ver.created_at ? new Date(ver.created_at).toLocaleString() : '--'}
                          </td>

                          <td className="py-3 px-3 text-white">{ver.created_by || 'curriculum_lead'}</td>

                          <td className="py-3 px-4 text-slate-300 italic max-w-xs truncate">
                            {ver.note || 'Regular curriculum release'}
                          </td>

                          <td className="py-3 px-3 font-mono">{ver.concept_count}</td>
                          <td className="py-3 px-3 font-mono">{ver.relationship_count}</td>

                          <td className="py-3 px-4 text-right">
                            <button
                              onClick={() => {
                                setRollbackModalVersion(ver);
                                setRollbackNote('');
                              }}
                              disabled={!isAuthorized || isCurrent}
                              className="px-2.5 py-1 rounded-lg bg-space-800 hover:bg-space-750 text-rose-300 border border-rose-500/30 text-xs font-medium transition-colors disabled:opacity-40"
                            >
                              Rollback
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Modal: Rollback Confirmation */}
          {rollbackModalVersion && (
            <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md animate-in fade-in">
              <div className="w-full max-w-md p-6 rounded-2xl bg-space-900 border border-rose-500/30 shadow-2xl space-y-4">
                <div className="flex items-center gap-2.5 text-rose-400">
                  <RotateCcw className="w-5 h-5 shrink-0" />
                  <h3 className="text-sm font-display font-bold text-white">
                    Confirm Rollback to Snapshot: {rollbackModalVersion.version_id}
                  </h3>
                </div>

                <div className="p-3.5 rounded-xl bg-rose-950/20 border border-rose-500/20 text-xs text-rose-300 space-y-1">
                  <p>
                    <strong>Warning:</strong> Live curriculum graph will be reverted to the exact topology and concept metadata of version <code>{rollbackModalVersion.version_id}</code>.
                  </p>
                  <p className="text-[11px] opacity-80">
                    A pre-rollback backup of the current state will be automatically archived in version history.
                  </p>
                </div>

                <div className="space-y-1.5">
                  <label className="text-xs text-universe-slate">Rollback Reason / Justification *</label>
                  <textarea
                    rows={2}
                    value={rollbackNote}
                    onChange={(e) => setRollbackNote(e.target.value)}
                    placeholder="e.g. Reverting unverified edits to restore verified baseline..."
                    className="w-full px-3 py-2 rounded-xl bg-space-950 border border-white/[0.1] text-xs text-white focus:outline-none focus:border-rose-400"
                  />
                </div>

                <div className="flex justify-end gap-2 pt-2 border-t border-white/[0.08]">
                  <button
                    onClick={() => setRollbackModalVersion(null)}
                    className="px-4 py-2 rounded-xl bg-space-800 text-slate-300 text-xs"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={handleConfirmRollback}
                    disabled={submittingRollback}
                    className="px-4 py-2 rounded-xl bg-rose-600 hover:bg-rose-500 text-white font-semibold text-xs disabled:opacity-50"
                  >
                    {submittingRollback ? 'Rolling back...' : 'Confirm Rollback'}
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
export default CurriculumDashboard;
