import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  CheckCircle2,
  XCircle,
  AlertCircle,
  Edit3,
  Copy,
  FileText,
  Layers,
  GitBranch,
  ShieldCheck,
  Eye,
  RefreshCw,
  Search,
  Filter,
  Clock,
  ArrowRight,
  Plus,
  Check,
  AlertTriangle,
  FolderGit2,
  Trash2,
  MapPin,
} from 'lucide-react';
import {
  ApiClient,
  type ConceptReviewItem,
  type DocumentReviewResponse,
  type ReviewAuditLogEntry,
  type PageEvidenceResponse,
  type Subject,
} from '../../api/client';

export interface ConceptReviewWorkspaceProps {
  reviewerId: string;
  initialDocumentId?: string;
  onNavigateToAtlas?: () => void;
}

export const ConceptReviewWorkspace: React.FC<ConceptReviewWorkspaceProps> = ({
  reviewerId,
  initialDocumentId,
  onNavigateToAtlas,
}) => {
  // Available documents
  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [selectedDocId, setSelectedDocId] = useState<string>(initialDocumentId || '');
  const [loadingDocs, setLoadingDocs] = useState<boolean>(true);

  // Document review payload
  const [docReview, setDocReview] = useState<DocumentReviewResponse | null>(null);
  const [loadingReview, setLoadingReview] = useState<boolean>(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  // Concept selection and filters
  const [selectedConceptId, setSelectedConceptId] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [tierFilter, setTierFilter] = useState<string>('all');

  // Active inspector tab
  const [inspectorTab, setInspectorTab] = useState<'evidence' | 'mapping' | 'hierarchy' | 'prereqs' | 'audit'>('evidence');

  // Page evidence modal / inspection
  const [pageEvidence, setPageEvidence] = useState<PageEvidenceResponse | null>(null);
  const [loadingPageEvidence, setLoadingPageEvidence] = useState<boolean>(false);
  const [showPageEvidenceModal, setShowPageEvidenceModal] = useState<boolean>(false);

  // Edit Name Modal State
  const [isEditNameModalOpen, setIsEditNameModalOpen] = useState<boolean>(false);
  const [editNameValue, setEditNameValue] = useState<string>('');

  // Rejection Reason Modal State
  const [isRejectModalOpen, setIsRejectModalOpen] = useState<boolean>(false);
  const [rejectionReason, setRejectionReason] = useState<string>('');

  // New Prerequisite Modal State
  const [isAddPrereqModalOpen, setIsAddPrereqModalOpen] = useState<boolean>(false);
  const [targetPrereqId, setTargetPrereqId] = useState<string>('');
  const [prereqError, setPrereqError] = useState<string | null>(null);

  // Action in progress flag
  const [isExecutingAction, setIsExecutingAction] = useState<boolean>(false);

  // 1. Load subjects on mount
  useEffect(() => {
    async function loadSubjects() {
      try {
        setLoadingDocs(true);
        const list = await ApiClient.getSubjects();
        setSubjects(list);
        if (!selectedDocId && list.length > 0) {
          setSelectedDocId(list[0].id);
        }
      } catch (err: any) {
        setErrorMessage(err.message || 'Failed to load documents list');
      } finally {
        setLoadingDocs(false);
      }
    }
    loadSubjects();
  }, []);

  // 2. Load review items for selected document
  const fetchReviewItems = useCallback(async (docId: string) => {
    if (!docId) return;
    try {
      setLoadingReview(true);
      setErrorMessage(null);
      const res = await ApiClient.getDocumentReviewItems(docId);
      setDocReview(res);
      // Select first concept if none selected
      if (res.concepts.length > 0) {
        setSelectedConceptId((prev) => {
          if (prev && res.concepts.some((c) => c.concept_id === prev)) return prev;
          return res.concepts[0].concept_id;
        });
      } else {
        setSelectedConceptId(null);
      }
    } catch (err: any) {
      setErrorMessage(err.message || `Failed to load review items for ${docId}`);
      setDocReview(null);
    } finally {
      setLoadingReview(false);
    }
  }, []);

  useEffect(() => {
    if (selectedDocId) {
      fetchReviewItems(selectedDocId);
    }
  }, [selectedDocId, fetchReviewItems]);

  // Selected concept object
  const selectedConcept = useMemo<ConceptReviewItem | null>(() => {
    if (!docReview || !selectedConceptId) return null;
    return docReview.concepts.find((c) => c.concept_id === selectedConceptId) || null;
  }, [docReview, selectedConceptId]);

  // Filtered concepts
  const filteredConcepts = useMemo(() => {
    if (!docReview) return [];
    return docReview.concepts.filter((c) => {
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const matchesName = c.canonical_name.toLowerCase().includes(q);
        const matchesExcerpt = c.evidence_excerpt.toLowerCase().includes(q);
        if (!matchesName && !matchesExcerpt) return false;
      }
      if (statusFilter !== 'all' && c.review_status !== statusFilter) {
        return false;
      }
      if (tierFilter !== 'all' && c.hierarchical_level !== tierFilter) {
        return false;
      }
      return true;
    });
  }, [docReview, searchQuery, statusFilter, tierFilter]);

  // Handle Review Decision
  const handleApplyDecision = async (
    decision: string,
    extra: {
      reason?: string;
      new_name?: string;
      duplicate_of_concept_id?: string;
      target_canonical_id?: string;
      new_hierarchical_level?: string;
      new_parent_topic_id?: string;
      status?: string;
    } = {}
  ) => {
    if (!selectedDocId || !selectedConceptId) return;
    try {
      setIsExecutingAction(true);
      setErrorMessage(null);
      await ApiClient.applyConceptReviewDecision(selectedDocId, {
        concept_id: selectedConceptId,
        decision,
        reviewer_id: reviewerId,
        ...extra,
      });
      setSuccessMessage(`Successfully applied '${decision}' decision.`);
      setTimeout(() => setSuccessMessage(null), 3500);
      await fetchReviewItems(selectedDocId);
    } catch (err: any) {
      setErrorMessage(err.message || `Action failed: ${err}`);
    } finally {
      setIsExecutingAction(false);
    }
  };

  // Handle Prerequisite Decision
  const handlePrereqDecision = async (
    sourceId: string,
    targetId: string,
    action: 'approve' | 'reject' | 'add' | 'remove',
    reason?: string
  ) => {
    if (!selectedDocId) return;
    try {
      setIsExecutingAction(true);
      setPrereqError(null);
      setErrorMessage(null);
      await ApiClient.applyPrerequisiteReviewDecision(selectedDocId, {
        source_concept_id: sourceId,
        target_concept_id: targetId,
        action,
        reviewer_id: reviewerId,
        reason: reason || `Prerequisite ${action}ed by reviewer`,
      });
      setSuccessMessage(`Prerequisite relationship updated.`);
      setTimeout(() => setSuccessMessage(null), 3000);
      setIsAddPrereqModalOpen(false);
      await fetchReviewItems(selectedDocId);
    } catch (err: any) {
      setPrereqError(err.message || 'Prerequisite operation failed');
      setErrorMessage(err.message || 'Prerequisite operation failed');
    } finally {
      setIsExecutingAction(false);
    }
  };

  // Handle Batch Approval
  const handleBatchApprove = async () => {
    if (!selectedDocId) return;
    const confirmMsg = 'Are you sure you want to approve all verified and pending concepts for the canonical curriculum and diagnostic question generation?';
    if (!window.confirm(confirmMsg)) return;

    try {
      setIsExecutingAction(true);
      setErrorMessage(null);
      const res = await ApiClient.approveBatchConcepts(selectedDocId, {
        reviewer_id: reviewerId,
        reason: 'Batch approved via Teacher Concept Verification Workspace',
      });
      setSuccessMessage(`Batch approved ${res.approved_count} concepts for curriculum.`);
      setTimeout(() => setSuccessMessage(null), 4000);
      await fetchReviewItems(selectedDocId);
    } catch (err: any) {
      setErrorMessage(err.message || 'Batch approval failed');
    } finally {
      setIsExecutingAction(false);
    }
  };

  // Fetch full page evidence
  const handleViewPageEvidence = async (pageNumber: number) => {
    if (!selectedDocId) return;
    try {
      setLoadingPageEvidence(true);
      const data = await ApiClient.getDocumentPageEvidence(selectedDocId, pageNumber);
      setPageEvidence(data);
      setShowPageEvidenceModal(true);
    } catch (err: any) {
      setErrorMessage(err.message || 'Failed to load page evidence blocks');
    } finally {
      setLoadingPageEvidence(false);
    }
  };

  // Status Badge Helper
  const renderStatusBadge = (status: string) => {
    switch (status) {
      case 'approved_for_curriculum':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-mono font-semibold bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
            <CheckCircle2 className="w-3 h-3" /> Approved
          </span>
        );
      case 'accepted':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-mono font-semibold bg-cyan-500/15 text-cyan-400 border border-cyan-500/30">
            <Check className="w-3 h-3" /> Accepted
          </span>
        );
      case 'rejected':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-mono font-semibold bg-rose-500/15 text-rose-400 border border-rose-500/30">
            <XCircle className="w-3 h-3" /> Rejected
          </span>
        );
      case 'duplicate':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-mono font-semibold bg-amber-500/15 text-amber-400 border border-amber-500/30">
            <Copy className="w-3 h-3" /> Duplicate
          </span>
        );
      case 'needs_canonical_mapping':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-mono font-semibold bg-purple-500/15 text-purple-400 border border-purple-500/30">
            <Layers className="w-3 h-3" /> Needs Mapping
          </span>
        );
      case 'needs_evidence_review':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-mono font-semibold bg-orange-500/15 text-orange-400 border border-orange-500/30">
            <Eye className="w-3 h-3" /> Needs Evidence
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-mono font-semibold bg-space-800 text-universe-slate border border-white/[0.08]">
            <Clock className="w-3 h-3" /> Pending Review
          </span>
        );
    }
  };

  // Tier Badge Helper
  const renderTierBadge = (tier: string) => {
    switch (tier) {
      case 'level_1':
        return <span className="px-1.5 py-0.5 rounded text-[9px] font-mono font-bold bg-indigo-500/20 text-indigo-300 border border-indigo-400/30">L1 CORE</span>;
      case 'level_2':
        return <span className="px-1.5 py-0.5 rounded text-[9px] font-mono font-bold bg-blue-500/20 text-blue-300 border border-blue-400/30">L2 TOPIC</span>;
      default:
        return <span className="px-1.5 py-0.5 rounded text-[9px] font-mono font-bold bg-space-800 text-universe-slate border border-white/[0.08]">L3 SUB</span>;
    }
  };

  return (
    <div className="space-y-6 animate-fade-in pb-12">
      {/* 1. Header Toolbar */}
      <div className="universe-panel rounded-3xl p-6 lg:p-8 flex flex-col md:flex-row items-start md:items-center justify-between gap-6">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <span className="px-2 py-0.5 rounded-full bg-cyan-500/15 text-cyan-300 border border-cyan-400/30 text-[10px] font-mono uppercase font-bold tracking-wider">
              PERSON 2 KNOWLEDGE GOVERNANCE
            </span>
            <span className="text-universe-slate text-xs font-mono">•</span>
            <span className="text-xs font-mono text-universe-slate">Reviewer: {reviewerId}</span>
          </div>
          <h2 className="text-2xl sm:text-3xl font-display font-extrabold text-white tracking-tight flex items-center gap-2">
            Concept Verification & Curriculum Review
          </h2>
          <p className="text-xs text-universe-slate max-w-2xl">
            Audit extracted academic concepts against verbatim source PDF evidence, verify canonical curriculum mappings, review prerequisites, and gate concepts before diagnostic question generation.
          </p>
        </div>

        {/* Document Selector & Batch Action */}
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2 bg-space-900 border border-white/[0.08] rounded-xl px-3 py-1.5">
            <FileText className="w-4 h-4 text-cyan-400" />
            <select
              value={selectedDocId}
              onChange={(e) => setSelectedDocId(e.target.value)}
              disabled={loadingDocs || loadingReview}
              className="bg-transparent text-xs text-white font-medium focus:outline-none cursor-pointer"
            >
              {subjects.map((s) => (
                <option key={s.id} value={s.id} className="bg-space-950 text-white">
                  {s.title} ({s.concept_count} concepts)
                </option>
              ))}
            </select>
          </div>

          <button
            onClick={() => fetchReviewItems(selectedDocId)}
            disabled={loadingReview}
            className="p-2 rounded-xl bg-space-900 hover:bg-space-800 border border-white/[0.08] text-universe-slate hover:text-white transition-all cursor-pointer"
            title="Refresh review items"
          >
            <RefreshCw className={`w-4 h-4 ${loadingReview ? 'animate-spin text-cyan-400' : ''}`} />
          </button>

          <button
            onClick={handleBatchApprove}
            disabled={isExecutingAction || !docReview}
            className="px-4 py-2 rounded-xl bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-300 border border-emerald-400/40 text-xs font-semibold font-mono flex items-center gap-1.5 transition-all shadow-sm cursor-pointer"
          >
            <ShieldCheck className="w-4 h-4 text-emerald-400" />
            <span>Approve All Verified</span>
          </button>

          {onNavigateToAtlas && (
            <button
              onClick={onNavigateToAtlas}
              className="px-3 py-2 rounded-xl bg-space-900 hover:bg-space-800 border border-white/[0.08] text-xs font-mono text-universe-slate hover:text-white flex items-center gap-1.5 transition-all cursor-pointer"
              title="Open Knowledge Atlas"
            >
              <MapPin className="w-4 h-4 text-cyan-400" />
              <span>Atlas</span>
            </button>
          )}
        </div>
      </div>

      {/* Notifications */}
      {errorMessage && (
        <div className="p-4 rounded-2xl bg-rose-950/50 border border-rose-500/40 text-rose-200 text-xs font-mono flex items-center justify-between gap-3 animate-fade-in">
          <div className="flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 text-rose-400 shrink-0" />
            <span>{errorMessage}</span>
          </div>
          <button onClick={() => setErrorMessage(null)} className="underline hover:text-white">Dismiss</button>
        </div>
      )}

      {successMessage && (
        <div className="p-4 rounded-2xl bg-emerald-950/50 border border-emerald-500/40 text-emerald-200 text-xs font-mono flex items-center justify-between gap-3 animate-fade-in">
          <div className="flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
            <span>{successMessage}</span>
          </div>
          <button onClick={() => setSuccessMessage(null)} className="underline hover:text-white">Dismiss</button>
        </div>
      )}

      {/* 2. Document Summary Chips */}
      {docReview && (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
          <div className="p-3.5 rounded-2xl bg-space-850/60 border border-white/[0.06] space-y-1">
            <span className="text-[10px] font-mono text-universe-slate uppercase tracking-wider">Total Concepts</span>
            <div className="text-xl font-bold font-display text-white">{docReview.total_concepts}</div>
            <span className="text-[10px] font-mono text-universe-slate">{docReview.subject}</span>
          </div>

          <div className="p-3.5 rounded-2xl bg-space-850/60 border border-white/[0.06] space-y-1">
            <span className="text-[10px] font-mono text-universe-slate uppercase tracking-wider">Approved</span>
            <div className="text-xl font-bold font-display text-emerald-400">
              {docReview.status_counts['approved_for_curriculum'] || 0}
            </div>
            <span className="text-[10px] font-mono text-emerald-400/70">Diagnostic Ready</span>
          </div>

          <div className="p-3.5 rounded-2xl bg-space-850/60 border border-white/[0.06] space-y-1">
            <span className="text-[10px] font-mono text-universe-slate uppercase tracking-wider">Accepted</span>
            <div className="text-xl font-bold font-display text-cyan-400">
              {docReview.status_counts['accepted'] || 0}
            </div>
            <span className="text-[10px] font-mono text-cyan-400/70">Verified</span>
          </div>

          <div className="p-3.5 rounded-2xl bg-space-850/60 border border-white/[0.06] space-y-1">
            <span className="text-[10px] font-mono text-universe-slate uppercase tracking-wider">Pending Review</span>
            <div className="text-xl font-bold font-display text-universe-slate">
              {docReview.status_counts['pending_review'] || 0}
            </div>
            <span className="text-[10px] font-mono text-universe-slate/70">Awaiting Decision</span>
          </div>

          <div className="p-3.5 rounded-2xl bg-space-850/60 border border-white/[0.06] space-y-1">
            <span className="text-[10px] font-mono text-universe-slate uppercase tracking-wider">Rejected / Dupe</span>
            <div className="text-xl font-bold font-display text-rose-400">
              {(docReview.status_counts['rejected'] || 0) + (docReview.status_counts['duplicate'] || 0)}
            </div>
            <span className="text-[10px] font-mono text-rose-400/70">Excluded</span>
          </div>

          <div className="p-3.5 rounded-2xl bg-space-850/60 border border-white/[0.06] space-y-1">
            <span className="text-[10px] font-mono text-universe-slate uppercase tracking-wider">Audit Entries</span>
            <div className="text-xl font-bold font-display text-purple-400">
              {docReview.audit_history_count}
            </div>
            <span className="text-[10px] font-mono text-purple-400/70">Immutable Log</span>
          </div>
        </div>
      )}

      {/* 3. Main Split View */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        {/* Left Column: Concept List & Filters (5 cols) */}
        <div className="lg:col-span-5 universe-panel rounded-3xl p-5 space-y-4">
          <div className="flex items-center justify-between pb-2 border-b border-white/[0.06]">
            <h3 className="text-sm font-display font-bold text-white flex items-center gap-2">
              <FolderGit2 className="w-4 h-4 text-cyan-400" />
              <span>Extracted Concepts ({filteredConcepts.length})</span>
            </h3>
            <span className="text-[10px] font-mono text-universe-slate">Click to inspect</span>
          </div>

          {/* Search & Filters */}
          <div className="space-y-2">
            <div className="relative">
              <Search className="w-3.5 h-3.5 text-universe-slate absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search concepts or excerpts..."
                className="w-full bg-space-900 border border-white/[0.08] rounded-xl pl-9 pr-3 py-2 text-xs text-white placeholder-universe-slate focus:outline-none focus:border-cyan-400/40"
              />
            </div>

            <div className="flex items-center gap-2">
              <div className="flex items-center gap-1.5 flex-1">
                <Filter className="w-3 h-3 text-universe-slate" />
                <select
                  value={statusFilter}
                  onChange={(e) => setStatusFilter(e.target.value)}
                  className="bg-space-900 border border-white/[0.08] rounded-lg px-2 py-1 text-[11px] text-universe-slate focus:outline-none w-full"
                >
                  <option value="all">All Statuses</option>
                  <option value="pending_review">Pending Review</option>
                  <option value="accepted">Accepted</option>
                  <option value="approved_for_curriculum">Approved</option>
                  <option value="rejected">Rejected</option>
                  <option value="duplicate">Duplicate</option>
                  <option value="needs_canonical_mapping">Needs Canonical</option>
                  <option value="needs_evidence_review">Needs Evidence</option>
                </select>
              </div>

              <select
                value={tierFilter}
                onChange={(e) => setTierFilter(e.target.value)}
                className="bg-space-900 border border-white/[0.08] rounded-lg px-2 py-1 text-[11px] text-universe-slate focus:outline-none"
              >
                <option value="all">All Levels</option>
                <option value="level_1">L1 Core Topic</option>
                <option value="level_2">L2 Major Principle</option>
                <option value="level_3">L3 Supporting</option>
              </select>
            </div>
          </div>

          {/* Concepts Scroll List */}
          <div className="space-y-2 max-h-[640px] overflow-y-auto pr-1">
            {filteredConcepts.length === 0 ? (
              <div className="p-8 text-center text-universe-slate text-xs font-mono">
                No extracted concepts match the current filters.
              </div>
            ) : (
              filteredConcepts.map((c) => {
                const isSelected = c.concept_id === selectedConceptId;
                return (
                  <button
                    key={c.concept_id}
                    onClick={() => setSelectedConceptId(c.concept_id)}
                    className={`w-full text-left p-3.5 rounded-2xl border transition-all cursor-pointer flex flex-col gap-2 ${
                      isSelected
                        ? 'bg-cyan-500/10 border-cyan-400/40 shadow-sm'
                        : 'bg-space-850/50 hover:bg-space-800/80 border-white/[0.06] hover:border-white/[0.12]'
                    }`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex items-center gap-2">
                        {renderTierBadge(c.hierarchical_level)}
                        <span className={`text-xs font-semibold ${isSelected ? 'text-white' : 'text-universe-text'}`}>
                          {c.canonical_name}
                        </span>
                      </div>
                      {renderStatusBadge(c.review_status)}
                    </div>

                    <p className="text-[11px] text-universe-slate font-sans line-clamp-2">
                      "{c.evidence_excerpt}"
                    </p>

                    <div className="flex items-center justify-between text-[10px] font-mono text-universe-slate/70 pt-1 border-t border-white/[0.04]">
                      <span>Page {c.page_number}</span>
                      {c.duplicate_candidates.length > 0 && (
                        <span className="text-amber-400/90 font-bold">
                          {c.duplicate_candidates.length} dupe candidate
                        </span>
                      )}
                      <span>ID: {c.concept_id.slice(0, 10)}...</span>
                    </div>
                  </button>
                );
              })
            )}
          </div>
        </div>

        {/* Right Column: Concept Inspector Deck (7 cols) */}
        <div className="lg:col-span-7 space-y-4">
          {selectedConcept ? (
            <div className="universe-panel rounded-3xl p-6 space-y-6">
              {/* Concept Title & Quick Actions */}
              <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 pb-4 border-b border-white/[0.08]">
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    {renderTierBadge(selectedConcept.hierarchical_level)}
                    {renderStatusBadge(selectedConcept.review_status)}
                    <span className="text-[10px] font-mono text-universe-slate">Page {selectedConcept.page_number}</span>
                  </div>
                  <h3 className="text-xl font-display font-extrabold text-white">
                    {selectedConcept.canonical_name}
                  </h3>
                  <div className="text-[10px] font-mono text-universe-slate">
                    Concept ID: <code className="text-cyan-300">{selectedConcept.concept_id}</code> (Immutable Anchor)
                  </div>
                </div>

                <div className="flex flex-wrap items-center gap-2 self-end sm:self-center">
                  <button
                    onClick={() => {
                      setEditNameValue(selectedConcept.canonical_name);
                      setIsEditNameModalOpen(true);
                    }}
                    className="px-2.5 py-1.5 rounded-xl bg-space-850 hover:bg-space-800 border border-white/[0.08] text-universe-slate hover:text-white text-xs font-mono flex items-center gap-1.5 transition-all cursor-pointer"
                    title="Rename concept while preserving stable ID and evidence"
                  >
                    <Edit3 className="w-3.5 h-3.5 text-cyan-400" />
                    <span>Edit Name</span>
                  </button>

                  <button
                    onClick={() => handleApplyDecision('accept')}
                    disabled={isExecutingAction}
                    className="px-3 py-1.5 rounded-xl bg-cyan-500/20 hover:bg-cyan-500/30 text-cyan-300 border border-cyan-400/40 text-xs font-mono font-semibold flex items-center gap-1.5 transition-all cursor-pointer"
                  >
                    <Check className="w-3.5 h-3.5 text-cyan-400" />
                    <span>Accept</span>
                  </button>

                  <button
                    onClick={() => setIsRejectModalOpen(true)}
                    disabled={isExecutingAction}
                    className="px-3 py-1.5 rounded-xl bg-rose-500/20 hover:bg-rose-500/30 text-rose-300 border border-rose-400/40 text-xs font-mono font-semibold flex items-center gap-1.5 transition-all cursor-pointer"
                  >
                    <XCircle className="w-3.5 h-3.5 text-rose-400" />
                    <span>Reject</span>
                  </button>

                  <button
                    onClick={() => handleApplyDecision('approve_for_curriculum')}
                    disabled={isExecutingAction}
                    className="px-3 py-1.5 rounded-xl bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-300 border border-emerald-400/40 text-xs font-mono font-semibold flex items-center gap-1.5 transition-all cursor-pointer"
                  >
                    <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
                    <span>Approve</span>
                  </button>
                </div>
              </div>

              {/* Inspector Sub-Tabs */}
              <div className="flex items-center gap-1 border-b border-white/[0.06] pb-2 overflow-x-auto text-xs font-semibold">
                <button
                  onClick={() => setInspectorTab('evidence')}
                  className={`px-3 py-1.5 rounded-xl transition-all cursor-pointer flex items-center gap-1.5 ${
                    inspectorTab === 'evidence'
                      ? 'bg-cyan-500/15 text-cyan-300 border border-cyan-400/30'
                      : 'text-universe-slate hover:text-white'
                  }`}
                >
                  <FileText className="w-3.5 h-3.5" />
                  <span>Evidence & Provenance</span>
                </button>

                <button
                  onClick={() => setInspectorTab('mapping')}
                  className={`px-3 py-1.5 rounded-xl transition-all cursor-pointer flex items-center gap-1.5 ${
                    inspectorTab === 'mapping'
                      ? 'bg-cyan-500/15 text-cyan-300 border border-cyan-400/30'
                      : 'text-universe-slate hover:text-white'
                  }`}
                >
                  <Layers className="w-3.5 h-3.5" />
                  <span>Canonical Mapping</span>
                </button>

                <button
                  onClick={() => setInspectorTab('hierarchy')}
                  className={`px-3 py-1.5 rounded-xl transition-all cursor-pointer flex items-center gap-1.5 ${
                    inspectorTab === 'hierarchy'
                      ? 'bg-cyan-500/15 text-cyan-300 border border-cyan-400/30'
                      : 'text-universe-slate hover:text-white'
                  }`}
                >
                  <FolderGit2 className="w-3.5 h-3.5" />
                  <span>Hierarchy & Topic</span>
                </button>

                <button
                  onClick={() => setInspectorTab('prereqs')}
                  className={`px-3 py-1.5 rounded-xl transition-all cursor-pointer flex items-center gap-1.5 ${
                    inspectorTab === 'prereqs'
                      ? 'bg-cyan-500/15 text-cyan-300 border border-cyan-400/30'
                      : 'text-universe-slate hover:text-white'
                  }`}
                >
                  <GitBranch className="w-3.5 h-3.5" />
                  <span>Prerequisites</span>
                </button>

                <button
                  onClick={() => setInspectorTab('audit')}
                  className={`px-3 py-1.5 rounded-xl transition-all cursor-pointer flex items-center gap-1.5 ${
                    inspectorTab === 'audit'
                      ? 'bg-cyan-500/15 text-cyan-300 border border-cyan-400/30'
                      : 'text-universe-slate hover:text-white'
                  }`}
                >
                  <Clock className="w-3.5 h-3.5" />
                  <span>Audit History</span>
                </button>
              </div>

              {/* Tab 1: Evidence & Source Page */}
              {inspectorTab === 'evidence' && (
                <div className="space-y-4">
                  <div className="p-4 rounded-2xl bg-space-850/80 border border-white/[0.06] space-y-3">
                    <div className="flex items-center justify-between text-xs font-mono text-universe-slate">
                      <span className="flex items-center gap-1 text-cyan-400 font-bold">
                        <FileText className="w-3.5 h-3.5" />
                        Verbatim Grounded Evidence Excerpt
                      </span>
                      <span>Page {selectedConcept.page_number} • Block: {selectedConcept.block_id || 'N/A'}</span>
                    </div>

                    <div className="p-3.5 rounded-xl bg-space-950/70 border border-white/[0.04] text-xs font-serif leading-relaxed text-universe-text border-l-2 border-l-cyan-400">
                      "{selectedConcept.evidence_excerpt}"
                    </div>

                    {selectedConcept.span && (
                      <div className="text-[10px] font-mono text-universe-slate">
                        Character Offsets: [{selectedConcept.span.start_offset} → {selectedConcept.span.end_offset}]
                      </div>
                    )}
                  </div>

                  <div className="flex items-center justify-between p-4 rounded-2xl bg-space-850/50 border border-white/[0.06]">
                    <div>
                      <h4 className="text-xs font-bold text-white">Full Source Page Inspection</h4>
                      <p className="text-[11px] text-universe-slate">
                        Verify whether the concept is genuinely taught on page {selectedConcept.page_number} or is merely an incidental mention.
                      </p>
                    </div>
                    <button
                      onClick={() => handleViewPageEvidence(selectedConcept.page_number)}
                      disabled={loadingPageEvidence}
                      className="px-3.5 py-2 rounded-xl bg-space-900 hover:bg-space-800 text-cyan-300 border border-cyan-400/30 text-xs font-mono font-semibold flex items-center gap-1.5 transition-all cursor-pointer"
                    >
                      <Eye className="w-3.5 h-3.5" />
                      <span>{loadingPageEvidence ? 'Loading...' : 'Inspect Page ' + selectedConcept.page_number}</span>
                    </button>
                  </div>

                  {/* Flag Options */}
                  <div className="flex items-center gap-3 pt-2">
                    <button
                      onClick={() => handleApplyDecision('flag_review', { status: 'needs_evidence_review' })}
                      className="text-xs font-mono text-orange-400 hover:text-orange-300 flex items-center gap-1 underline cursor-pointer"
                    >
                      <AlertCircle className="w-3.5 h-3.5" />
                      <span>Flag as Incidental Mention (Needs Evidence Review)</span>
                    </button>
                  </div>
                </div>
              )}

              {/* Tab 2: Canonical Mapping Review */}
              {inspectorTab === 'mapping' && (
                <div className="space-y-4">
                  {/* Current Canonical Target */}
                  <div className="p-4 rounded-2xl bg-space-850/80 border border-white/[0.06] space-y-2">
                    <span className="text-[10px] font-mono text-universe-slate uppercase tracking-wider">
                      Current Canonical Graph Mapping
                    </span>
                    {selectedConcept.current_canonical_mapping ? (
                      <div className="flex items-start justify-between">
                        <div>
                          <div className="text-sm font-bold text-white">
                            {selectedConcept.current_canonical_mapping.canonical_name}
                          </div>
                          <div className="text-xs font-mono text-cyan-400">
                            ID: {selectedConcept.current_canonical_mapping.canonical_concept_id}
                          </div>
                          {selectedConcept.current_canonical_mapping.aliases.length > 0 && (
                            <div className="text-[10px] font-mono text-universe-slate mt-1">
                              Aliases: {selectedConcept.current_canonical_mapping.aliases.join(', ')}
                            </div>
                          )}
                        </div>
                        <span className="px-2 py-0.5 rounded-full bg-cyan-500/15 text-cyan-400 border border-cyan-500/30 text-[10px] font-mono">
                          {selectedConcept.current_canonical_mapping.status}
                        </span>
                      </div>
                    ) : (
                      <div className="text-xs text-rose-300 font-mono">
                        Not currently mapped to any canonical concept in the JEE curriculum graph.
                      </div>
                    )}
                  </div>

                  {/* Alternative Suggestions */}
                  {selectedConcept.alternative_canonical_candidates.length > 0 && (
                    <div className="space-y-2">
                      <h4 className="text-xs font-bold text-white flex items-center gap-1.5">
                        <Layers className="w-3.5 h-3.5 text-cyan-400" />
                        <span>Alternative Canonical Concept Matches</span>
                      </h4>
                      <div className="space-y-2">
                        {selectedConcept.alternative_canonical_candidates.map((cand) => (
                          <div
                            key={cand.canonical_concept_id}
                            className="p-3 rounded-xl bg-space-900 border border-white/[0.06] flex items-center justify-between"
                          >
                            <div>
                              <div className="text-xs font-bold text-white">{cand.canonical_name}</div>
                              <div className="text-[10px] font-mono text-universe-slate">
                                Topic: {cand.parent_topic} • Similarity: {(cand.similarity * 100).toFixed(0)}%
                              </div>
                            </div>
                            <button
                              onClick={() =>
                                handleApplyDecision('accept', {
                                  target_canonical_id: cand.canonical_concept_id,
                                  reason: `Remapped to canonical concept '${cand.canonical_name}'`,
                                })
                              }
                              className="px-2.5 py-1 rounded-lg bg-cyan-500/15 hover:bg-cyan-500/25 text-cyan-300 border border-cyan-400/30 text-[11px] font-mono cursor-pointer"
                            >
                              Map to This
                            </button>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Request New Canonical Proposal */}
                  <div className="p-4 rounded-2xl bg-space-850/50 border border-white/[0.06] flex items-center justify-between">
                    <div>
                      <h4 className="text-xs font-bold text-white">Missing Canonical Concept?</h4>
                      <p className="text-[11px] text-universe-slate">
                        Propose this concept as a brand new canonical entity in the official curriculum queue.
                      </p>
                    </div>
                    <button
                      onClick={() => handleApplyDecision('request_new_canonical', { reason: 'Requested new canonical concept entry from review workspace' })}
                      className="px-3 py-1.5 rounded-xl bg-space-900 hover:bg-space-800 text-purple-300 border border-purple-400/30 text-xs font-mono font-semibold flex items-center gap-1 cursor-pointer"
                    >
                      <Plus className="w-3.5 h-3.5" />
                      <span>Propose New</span>
                    </button>
                  </div>

                  {/* Duplicate Candidates */}
                  {selectedConcept.duplicate_candidates.length > 0 && (
                    <div className="p-4 rounded-2xl bg-amber-950/30 border border-amber-500/30 space-y-2">
                      <div className="flex items-center gap-2 text-xs font-bold text-amber-300">
                        <Copy className="w-4 h-4 text-amber-400" />
                        <span>Intra-Document Duplicate Detected</span>
                      </div>
                      <p className="text-[11px] text-amber-200/80">
                        The extraction pipeline discovered similar concepts within this same document. Link this concept as a duplicate to unify knowledge.
                      </p>
                      <div className="space-y-1.5 pt-1">
                        {selectedConcept.duplicate_candidates.map((dupe) => (
                          <div key={dupe.concept_id} className="flex items-center justify-between p-2 rounded-lg bg-space-950/70 border border-white/[0.04]">
                            <span className="text-xs text-white">{dupe.name}</span>
                            <button
                              onClick={() =>
                                handleApplyDecision('mark_duplicate', {
                                  duplicate_of_concept_id: dupe.concept_id,
                                  reason: `Marked as duplicate of '${dupe.name}' (${dupe.concept_id})`,
                                })
                              }
                              className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-amber-500/20 text-amber-300 border border-amber-400/40 cursor-pointer"
                            >
                              Link as Duplicate
                            </button>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* Tab 3: Hierarchy & Topic */}
              {inspectorTab === 'hierarchy' && (
                <div className="space-y-4">
                  <div className="p-4 rounded-2xl bg-space-850/80 border border-white/[0.06] space-y-3">
                    <h4 className="text-xs font-bold text-white flex items-center gap-1.5">
                      <FolderGit2 className="w-3.5 h-3.5 text-cyan-400" />
                      <span>Hierarchical Tier Reassignment</span>
                    </h4>
                    <p className="text-[11px] text-universe-slate">
                      Select whether this concept represents an overarching chapter topic (L1), a core fundamental principle (L2), or a specialized supporting formula / detail (L3).
                    </p>

                    <div className="grid grid-cols-3 gap-2 pt-1">
                      {[
                        { id: 'level_1', title: 'Level 1: Core Topic', desc: 'Overarching theme' },
                        { id: 'level_2', title: 'Level 2: Major Concept', desc: 'Central principle' },
                        { id: 'level_3', title: 'Level 3: Supporting Detail', desc: 'Specific formula/application' },
                      ].map((tier) => {
                        const isCurrent = selectedConcept.hierarchical_level === tier.id;
                        return (
                          <button
                            key={tier.id}
                            onClick={() =>
                              handleApplyDecision('accept', {
                                new_hierarchical_level: tier.id,
                                reason: `Hierarchical tier changed to ${tier.id}`,
                              })
                            }
                            className={`p-3 rounded-xl border text-left transition-all cursor-pointer ${
                              isCurrent
                                ? 'bg-cyan-500/15 border-cyan-400/40 text-white'
                                : 'bg-space-900 border-white/[0.06] text-universe-slate hover:text-white'
                            }`}
                          >
                            <div className="text-xs font-bold">{tier.title}</div>
                            <div className="text-[10px] font-mono text-universe-slate mt-0.5">{tier.desc}</div>
                          </button>
                        );
                      })}
                    </div>
                  </div>

                  {/* Parent Topic Assignment */}
                  {Boolean(docReview && docReview.topics.length > 0) && (
                    <div className="p-4 rounded-2xl bg-space-850/80 border border-white/[0.06] space-y-2">
                      <h4 className="text-xs font-bold text-white">Parent Topic Reassignment</h4>
                      <select
                        value={selectedConcept.parent_topic_id || ''}
                        onChange={(e) =>
                          handleApplyDecision('accept', {
                            new_parent_topic_id: e.target.value,
                            reason: `Reassigned parent topic to '${e.target.value}'`,
                          })
                        }
                        className="w-full bg-space-900 border border-white/[0.08] rounded-xl px-3 py-2 text-xs text-white focus:outline-none"
                      >
                        {(docReview?.topics || []).map((t) => (
                          <option key={t.topic_id} value={t.topic_id}>
                            {t.name} (Level {t.level})
                          </option>
                        ))}
                      </select>
                    </div>
                  )}
                </div>
              )}

              {/* Tab 4: Prerequisites Review */}
              {inspectorTab === 'prereqs' && (
                <div className="space-y-4">
                  <div className="flex items-center justify-between">
                    <div>
                      <h4 className="text-xs font-bold text-white flex items-center gap-1.5">
                        <GitBranch className="w-3.5 h-3.5 text-cyan-400" />
                        <span>Prerequisite Relationships</span>
                      </h4>
                      <p className="text-[11px] text-universe-slate">
                        Review prerequisite dependencies. Prerequisite cycles are strictly prevented (DAG validation).
                      </p>
                    </div>
                    <button
                      onClick={() => {
                        setTargetPrereqId('');
                        setPrereqError(null);
                        setIsAddPrereqModalOpen(true);
                      }}
                      className="px-3 py-1.5 rounded-xl bg-space-900 hover:bg-space-800 text-cyan-300 border border-cyan-400/30 text-xs font-mono font-semibold flex items-center gap-1 cursor-pointer"
                    >
                      <Plus className="w-3.5 h-3.5" />
                      <span>Add Edge</span>
                    </button>
                  </div>

                  {/* List of prerequisites where this concept is source or target */}
                  <div className="space-y-2">
                    {(docReview?.prerequisites || []).filter(
                      (p) => p.source_concept_id === selectedConcept.concept_id || p.target_concept_id === selectedConcept.concept_id
                    ).length === 0 ? (
                      <div className="p-6 text-center text-xs font-mono text-universe-slate bg-space-850/30 rounded-2xl">
                        No prerequisite relationships linked to this concept yet.
                      </div>
                    ) : (
                      (docReview?.prerequisites || [])
                        .filter(
                          (p) => p.source_concept_id === selectedConcept.concept_id || p.target_concept_id === selectedConcept.concept_id
                        )
                        .map((p, idx) => (
                          <div
                            key={idx}
                            className="p-3.5 rounded-xl bg-space-900 border border-white/[0.06] flex items-center justify-between gap-3"
                          >
                            <div className="flex items-center gap-2 text-xs">
                              <span className={`font-semibold ${p.source_concept_id === selectedConcept.concept_id ? 'text-cyan-300 font-bold' : 'text-white'}`}>
                                {p.source_name}
                              </span>
                              <ArrowRight className="w-3.5 h-3.5 text-universe-slate" />
                              <span className={`font-semibold ${p.target_concept_id === selectedConcept.concept_id ? 'text-cyan-300 font-bold' : 'text-white'}`}>
                                {p.target_name}
                              </span>
                            </div>

                            <div className="flex items-center gap-2">
                              <span className={`px-2 py-0.5 rounded text-[10px] font-mono font-bold ${
                                p.status === 'accepted' ? 'bg-emerald-500/20 text-emerald-400' : 'bg-rose-500/20 text-rose-400'
                              }`}>
                                {p.status}
                              </span>
                              {p.status !== 'rejected' && (
                                <button
                                  onClick={() => handlePrereqDecision(p.source_concept_id, p.target_concept_id, 'reject')}
                                  className="p-1 rounded hover:bg-space-800 text-rose-400 cursor-pointer"
                                  title="Reject prerequisite edge"
                                >
                                  <Trash2 className="w-3.5 h-3.5" />
                                </button>
                              )}
                            </div>
                          </div>
                        ))
                    )}
                  </div>
                </div>
              )}

              {/* Tab 5: Audit History */}
              {inspectorTab === 'audit' && (
                <div className="space-y-3">
                  <h4 className="text-xs font-bold text-white flex items-center gap-1.5">
                    <Clock className="w-3.5 h-3.5 text-purple-400" />
                    <span>Concept Review Audit Log</span>
                  </h4>
                  <div className="space-y-2 max-h-80 overflow-y-auto">
                    {ApiClient && (
                      <AuditTrailSection documentId={selectedDocId} conceptId={selectedConcept.concept_id} />
                    )}
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="universe-panel rounded-3xl p-12 text-center text-universe-slate space-y-3">
              <FolderGit2 className="w-8 h-8 text-cyan-400 mx-auto opacity-40" />
              <div className="text-sm font-semibold text-white">Select a Concept to Verify</div>
              <p className="text-xs max-w-sm mx-auto">
                Choose an extracted concept from the list on the left to inspect its evidence excerpt, source PDF page, canonical mapping, and review status.
              </p>
            </div>
          )}
        </div>
      </div>

      {/* 4. Edit Name Modal */}
      {isEditNameModalOpen && selectedConcept && (
        <div className="fixed inset-0 bg-space-950/80 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="universe-panel rounded-3xl p-6 max-w-md w-full space-y-4 border border-white/[0.1]">
            <h3 className="text-base font-display font-bold text-white flex items-center gap-2">
              <Edit3 className="w-4 h-4 text-cyan-400" />
              <span>Edit Extracted Concept Name</span>
            </h3>
            <p className="text-xs text-universe-slate">
              Renaming updates the student-facing label while preserving the immutable ID (<code className="text-cyan-300">{selectedConcept.concept_id}</code>) and grounding provenance.
            </p>
            <input
              type="text"
              value={editNameValue}
              onChange={(e) => setEditNameValue(e.target.value)}
              className="w-full bg-space-900 border border-white/[0.08] rounded-xl px-3 py-2 text-xs text-white focus:outline-none focus:border-cyan-400/40"
              placeholder="Clean academic concept name..."
            />
            <div className="flex items-center justify-end gap-2 pt-2">
              <button
                onClick={() => setIsEditNameModalOpen(false)}
                className="px-3 py-1.5 rounded-xl text-xs font-mono text-universe-slate hover:text-white"
              >
                Cancel
              </button>
              <button
                onClick={() => {
                  handleApplyDecision('edit_name', { new_name: editNameValue });
                  setIsEditNameModalOpen(false);
                }}
                disabled={!editNameValue.trim()}
                className="px-4 py-1.5 rounded-xl bg-cyan-500/20 hover:bg-cyan-500/30 text-cyan-300 border border-cyan-400/40 text-xs font-mono font-semibold"
              >
                Save Name
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 5. Reject Concept Modal */}
      {isRejectModalOpen && selectedConcept && (
        <div className="fixed inset-0 bg-space-950/80 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="universe-panel rounded-3xl p-6 max-w-md w-full space-y-4 border border-white/[0.1]">
            <h3 className="text-base font-display font-bold text-rose-400 flex items-center gap-2">
              <XCircle className="w-4 h-4" />
              <span>Reject Extracted Concept</span>
            </h3>
            <p className="text-xs text-universe-slate">
              Provide an academic justification for rejecting this concept. Rejected concepts will be strictly excluded from the canonical curriculum and student diagnostic question generation.
            </p>
            <textarea
              value={rejectionReason}
              onChange={(e) => setRejectionReason(e.target.value)}
              rows={3}
              className="w-full bg-space-900 border border-white/[0.08] rounded-xl p-3 text-xs text-white placeholder-universe-slate focus:outline-none focus:border-rose-400/40"
              placeholder="Reason (e.g., 'Incidental section header, not an evaluatable JEE physics concept')..."
            />
            <div className="flex items-center justify-end gap-2 pt-2">
              <button
                onClick={() => setIsRejectModalOpen(false)}
                className="px-3 py-1.5 rounded-xl text-xs font-mono text-universe-slate hover:text-white"
              >
                Cancel
              </button>
              <button
                onClick={() => {
                  handleApplyDecision('reject', { reason: rejectionReason.trim() });
                  setIsRejectModalOpen(false);
                  setRejectionReason('');
                }}
                disabled={!rejectionReason.trim()}
                className="px-4 py-1.5 rounded-xl bg-rose-500/20 hover:bg-rose-500/30 text-rose-300 border border-rose-400/40 text-xs font-mono font-semibold"
              >
                Confirm Rejection
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 6. Add Prerequisite Edge Modal */}
      {isAddPrereqModalOpen && selectedConcept && docReview && (
        <div className="fixed inset-0 bg-space-950/80 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="universe-panel rounded-3xl p-6 max-w-md w-full space-y-4 border border-white/[0.1]">
            <h3 className="text-base font-display font-bold text-white flex items-center gap-2">
              <GitBranch className="w-4 h-4 text-cyan-400" />
              <span>Add Prerequisite Dependency</span>
            </h3>
            <p className="text-xs text-universe-slate">
              Select which concept must be understood before learning <strong className="text-white">{selectedConcept.canonical_name}</strong>.
            </p>
            {prereqError && (
              <div className="p-3 rounded-xl bg-rose-950/50 border border-rose-500/40 text-rose-200 text-xs font-mono">
                {prereqError}
              </div>
            )}
            <select
              value={targetPrereqId}
              onChange={(e) => setTargetPrereqId(e.target.value)}
              className="w-full bg-space-900 border border-white/[0.08] rounded-xl px-3 py-2 text-xs text-white focus:outline-none"
            >
              <option value="">-- Choose Prerequisite Concept --</option>
              {docReview.concepts
                .filter((c) => c.concept_id !== selectedConcept.concept_id)
                .map((c) => (
                  <option key={c.concept_id} value={c.concept_id}>
                    {c.canonical_name} (Page {c.page_number})
                  </option>
                ))}
            </select>
            <div className="flex items-center justify-end gap-2 pt-2">
              <button
                onClick={() => setIsAddPrereqModalOpen(false)}
                className="px-3 py-1.5 rounded-xl text-xs font-mono text-universe-slate hover:text-white"
              >
                Cancel
              </button>
              <button
                onClick={() => handlePrereqDecision(targetPrereqId, selectedConcept.concept_id, 'add')}
                disabled={!targetPrereqId}
                className="px-4 py-1.5 rounded-xl bg-cyan-500/20 hover:bg-cyan-500/30 text-cyan-300 border border-cyan-400/40 text-xs font-mono font-semibold"
              >
                Add Prerequisite
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 7. Page Evidence Modal */}
      {showPageEvidenceModal && pageEvidence && (
        <div className="fixed inset-0 bg-space-950/85 backdrop-blur-md z-50 flex items-center justify-center p-4">
          <div className="universe-panel rounded-3xl p-6 max-w-2xl w-full max-h-[85vh] flex flex-col space-y-4 border border-white/[0.1]">
            <div className="flex items-center justify-between pb-3 border-b border-white/[0.08]">
              <div>
                <h3 className="text-base font-display font-bold text-white flex items-center gap-2">
                  <FileText className="w-4 h-4 text-cyan-400" />
                  <span>Source Document Page {pageEvidence.page_number} / {pageEvidence.total_pages}</span>
                </h3>
                <span className="text-[10px] font-mono text-universe-slate">{selectedDocId}</span>
              </div>
              <button
                onClick={() => setShowPageEvidenceModal(false)}
                className="p-1.5 rounded-xl bg-space-850 hover:bg-space-800 text-universe-slate hover:text-white text-xs font-mono"
              >
                Close
              </button>
            </div>

            <div className="flex-1 overflow-y-auto space-y-3 pr-2">
              {pageEvidence.blocks.length === 0 ? (
                <div className="text-xs font-mono text-universe-slate p-4">No structured layout blocks found on this page.</div>
              ) : (
                pageEvidence.blocks.map((b) => (
                  <div key={b.block_id} className="p-3.5 rounded-xl bg-space-900 border border-white/[0.04] space-y-1">
                    <div className="text-[10px] font-mono text-cyan-400 flex items-center justify-between">
                      <span>{b.block_type.toUpperCase()} • ID: {b.block_id}</span>
                      {b.section_title && <span className="text-universe-slate">{b.section_title}</span>}
                    </div>
                    <p className="text-xs text-universe-text font-serif leading-relaxed whitespace-pre-wrap">
                      {b.text}
                    </p>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

// Inner component to fetch and render immutable audit log
const AuditTrailSection: React.FC<{ documentId: string; conceptId: string }> = ({ documentId, conceptId }) => {
  const [entries, setEntries] = useState<ReviewAuditLogEntry[]>([]);
  const [loading, setLoading] = useState<boolean>(true);

  useEffect(() => {
    async function load() {
      try {
        setLoading(true);
        const res = await ApiClient.getDocumentReviewAuditHistory(documentId);
        // Filter to this concept or all
        const relevant = res.entries.filter((e) => e.concept_id === conceptId);
        setEntries(relevant.reverse());
      } catch (e) {
        console.error('Failed to load audit trail', e);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [documentId, conceptId]);

  if (loading) {
    return <div className="text-xs font-mono text-universe-slate p-4">Loading audit entries...</div>;
  }

  if (entries.length === 0) {
    return (
      <div className="text-xs font-mono text-universe-slate p-4 bg-space-850/30 rounded-xl">
        No review decisions recorded yet for this concept.
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {entries.map((entry) => (
        <div key={entry.entry_id} className="p-3 rounded-xl bg-space-900 border border-white/[0.04] space-y-1">
          <div className="flex items-center justify-between text-[10px] font-mono text-universe-slate">
            <span className="text-cyan-400 font-bold">{entry.action.toUpperCase()}</span>
            <span>{new Date(entry.timestamp).toLocaleString()}</span>
          </div>
          <div className="text-xs text-white">
            Status: <span className="text-universe-slate">{entry.previous_status}</span> → <strong className="text-cyan-300">{entry.new_status}</strong>
          </div>
          {entry.reason && (
            <div className="text-[11px] text-universe-slate italic">
              Reason: "{entry.reason}"
            </div>
          )}
          <div className="text-[9px] font-mono text-universe-slate/60">
            Reviewer: {entry.reviewer_id} • Audit ID: {entry.entry_id}
          </div>
        </div>
      ))}
    </div>
  );
};
