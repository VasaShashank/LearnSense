import React, { useState } from 'react';
import type { SourceDocument } from '../../api/client';
import { ApiClient } from '../../api/client';
import { FileText, Upload, CheckCircle2, AlertTriangle, RefreshCw, ArrowRight, BookOpen, Sparkles } from 'lucide-react';

export interface SourceLibraryProps {
  sources: SourceDocument[];
  onReloadSources: () => void;
  onSelectSubject?: (subjectId: string, isNewUpload?: boolean) => void;
}

export const SourceLibrary: React.FC<SourceLibraryProps> = ({
  sources,
  onReloadSources,
  onSelectSubject,
}) => {
  const [uploading, setUploading] = useState<boolean>(false);
  const [uploadResult, setUploadResult] = useState<{
    document_id: string;
    filename: string;
    page_count: number;
    concept_count: number;
  } | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    setUploadError(null);
    setUploadResult(null);

    try {
      const res = await ApiClient.uploadSource(file);
      setUploadResult({
        document_id: res.document_id,
        filename: res.filename || file.name,
        page_count: res.page_count || 1,
        concept_count: res.concept_count || 0,
      });
      onReloadSources();
      // Every upload routes straight into strength rating + verification test.
      // Pass isNewUpload=true to trigger onboarding flow (verification → diagnostic → Atlas)
      if (onSelectSubject && res.document_id) {
        onSelectSubject(res.document_id, true);
      }
    } catch (err: any) {
      console.error('File upload failed', err);
      setUploadError(err.message || 'Failed to parse and extract knowledge graph from source document.');
    } finally {
      setUploading(false);
      e.target.value = '';
    }
  };

  return (
    <div className="space-y-6 animate-fade-in">
      
      {/* 1. Header & Ingestion Deck */}
      <div className="universe-panel rounded-3xl p-6 lg:p-8 flex flex-wrap items-center justify-between gap-6">
        <div className="space-y-1 max-w-xl flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => window.history.back()}
              className="p-1.5 rounded-lg bg-space-800 hover:bg-space-700 border border-white/[0.07] hover:border-cyan-400/30 text-cyan-400 hover:text-cyan-300 transition-all flex items-center justify-center"
              title="Go back"
              aria-label="Go back"
            >
              <ArrowRight className="w-4 h-4 rotate-180" />
            </button>
            <Sparkles className="w-4 h-4 text-cyan-400" />
            <span className="text-[10px] font-mono tracking-widest text-cyan-300 uppercase font-bold">
              KNOWLEDGE INGESTION & CITATIONS
            </span>
          </div>
          <h2 className="text-2xl sm:text-3xl font-display font-extrabold text-white tracking-tight">
            Source Document Library
          </h2>
          <p className="text-xs text-universe-slate font-sans leading-relaxed">
            Every question, quiz item, and tutor explanation in LearnSense is mathematically grounded in these verified source texts. Supports PDF, PPTX, DOCX, and images.
          </p>
        </div>

        {/* Upload Trigger */}
        <label className="px-5 py-3.5 rounded-xl bg-cyan-400 hover:bg-cyan-300 text-space-950 font-display font-bold text-xs flex items-center gap-2.5 cursor-pointer shadow-[0_0_24px_rgba(0,240,255,0.25)] transition-all hover:scale-[1.02]">
          <Upload className="w-4 h-4" />
          <span>{uploading ? 'Processing...' : 'Ingest New Document (PDF, PPTX, DOCX)'}</span>
          <input
            type="file"
            accept=".pdf,.pptx,.docx,.png,.jpg,.jpeg"
            disabled={uploading}
            onChange={handleFileUpload}
            className="hidden"
          />
        </label>
      </div>

      {/* Success Notification Banner */}
      {uploadResult && (
        <div className="p-5 rounded-2xl bg-emerald-950/40 border border-emerald-500/40 shadow-[0_0_24px_rgba(16,185,129,0.15)] flex flex-wrap items-center justify-between gap-4 animate-fade-in">
          <div className="flex items-center gap-3">
            <CheckCircle2 className="w-5 h-5 text-emerald-400 shrink-0" />
            <div>
              <h4 className="text-xs font-display font-bold text-white">
                Ingestion Succeeded: {uploadResult.filename}
              </h4>
              <p className="text-[11px] text-emerald-300/90 font-mono mt-0.5">
                Parsed {uploadResult.page_count} pages • Extracted {uploadResult.concept_count} conceptual nodes into Knowledge Atlas.
              </p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            {onSelectSubject && uploadResult.document_id && (
              <button
                onClick={() => onSelectSubject(uploadResult.document_id, false)}
                className="py-2 px-4 rounded-xl bg-emerald-400 hover:bg-emerald-300 text-space-950 text-xs font-display font-bold flex items-center gap-1.5 transition-all shadow-sm"
              >
                <BookOpen className="w-3.5 h-3.5" />
                <span>Open in Atlas</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </button>
            )}
            <button
              onClick={() => setUploadResult(null)}
              className="text-xs text-emerald-400/80 hover:text-emerald-200 font-mono underline"
            >
              Dismiss
            </button>
          </div>
        </div>
      )}

      {/* Error Notification Banner */}
      {uploadError && (
        <div className="p-4 rounded-2xl bg-rose-950/40 border border-rose-500/40 flex items-center justify-between gap-4 animate-fade-in">
          <div className="flex items-center gap-3">
            <AlertTriangle className="w-5 h-5 text-rose-400 shrink-0" />
            <p className="text-xs text-rose-200 font-mono">{uploadError}</p>
          </div>
          <button
            onClick={() => setUploadError(null)}
            className="text-xs text-rose-400 hover:text-rose-200 underline font-mono"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* 2. Source Documents List */}
      <div className="universe-panel rounded-3xl p-6 lg:p-8 space-y-4">
        <div className="flex items-center justify-between pb-3 border-b border-white/[0.06]">
          <span className="text-[10px] font-mono tracking-widest text-universe-slate uppercase font-bold">
            VERIFIED INGESTED REPOSITORY ({sources.length})
          </span>
        </div>

        <div className="space-y-3">
          {sources.map((src) => {
            let statusBadge = (
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-emerald-950/60 border border-emerald-500/40 text-emerald-300 text-[10px] font-mono font-semibold">
                <CheckCircle2 className="w-3 h-3 text-emerald-400" /> FULLY GROUNDED
              </span>
            );

            if (src.recovery_state?.includes('RECOVER') || src.status === 'PROCESSING') {
              statusBadge = (
                <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-amber-950/60 border border-amber-500/40 text-amber-300 text-[10px] font-mono font-semibold animate-pulse">
                  <RefreshCw className="w-3 h-3 text-amber-400 animate-spin" /> PIPELINE RECOVERY
                </span>
              );
            } else if (src.status === 'PARTIAL') {
              statusBadge = (
                <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-rose-950/60 border border-rose-500/40 text-rose-300 text-[10px] font-mono font-semibold">
                  <AlertTriangle className="w-3 h-3 text-rose-400" /> PARTIAL EXTRACTION
                </span>
              );
            }

            return (
              <div
                key={src.document_id}
                className="p-5 rounded-2xl bg-space-850/50 hover:bg-space-800/80 border border-white/[0.06] hover:border-white/[0.12] transition-all flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4"
              >
                <div className="flex items-center gap-4">
                  <div className="w-10 h-10 rounded-xl bg-space-950 border border-white/[0.08] text-cyan-400 flex items-center justify-center shrink-0 shadow-sm">
                    <FileText className="w-5 h-5" />
                  </div>
                  <div>
                    <h4 className="text-sm font-display font-bold text-white">{src.title}</h4>
                    <div className="flex items-center gap-3 text-xs text-universe-slate font-mono mt-0.5">
                      <span>{src.page_count} Pages</span>
                      <span>•</span>
                      <span>{(src.file_size_bytes / (1024 * 1024)).toFixed(1)} MB</span>
                      <span>•</span>
                      <span className="text-universe-slate/70 truncate max-w-xs">{src.document_id}</span>
                    </div>
                  </div>
                </div>

                <div className="flex items-center gap-3 self-end sm:self-center">
                  {statusBadge}

                  {onSelectSubject && (
                    <button
                      onClick={() => onSelectSubject(src.document_id)}
                      className="py-2 px-3.5 rounded-xl bg-space-900 hover:bg-cyan-400 hover:text-space-950 text-universe-text border border-white/[0.08] hover:border-transparent text-xs font-mono font-bold flex items-center gap-1.5 transition-all shadow-sm"
                    >
                      <BookOpen className="w-3.5 h-3.5" />
                      <span>Study in Atlas</span>
                      <ArrowRight className="w-3.5 h-3.5" />
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>

    </div>
  );
};
