import React, { useState } from 'react';
import type { SourceDocument } from '../../api/client';
import { ApiClient } from '../../api/client';
import { FileText, Upload, CheckCircle2, AlertTriangle, RefreshCw, ArrowRight, BookOpen } from 'lucide-react';

export interface SourceLibraryProps {
  sources: SourceDocument[];
  onReloadSources: () => void;
  onSelectSubject?: (subjectId: string) => void;
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
    } catch (err: any) {
      console.error('File upload failed', err);
      setUploadError(err.message || 'Failed to upload and parse PDF source document.');
    } finally {
      setUploading(false);
      // Reset input
      e.target.value = '';
    }
  };

  return (
    <div className="p-6 rounded-3xl border border-slate-800 bg-slate-950 text-slate-100 space-y-6">
      <div className="flex flex-wrap items-center justify-between pb-4 border-b border-slate-800 gap-4">
        <div>
          <h3 className="text-lg font-bold text-white flex items-center gap-2">
            <FileText className="w-5 h-5 text-cyan-400" />
            Source Document Library
          </h3>
          <p className="text-xs text-slate-400 mt-1">
            Uploaded textbooks, PowerPoint slides, Word notes, and diagrams. Supports PDF, PPTX, DOCX, PNG, JPG.
          </p>
        </div>

        {/* Upload Button */}
        <label className="py-2.5 px-4 rounded-xl bg-cyan-500 hover:bg-cyan-400 text-slate-950 font-bold text-xs flex items-center gap-2 cursor-pointer shadow-glow-cyan transition-all">
          <Upload className="w-4 h-4" />
          <span>{uploading ? 'Parsing & Indexing Material...' : 'Upload Material (PDF, PPTX, DOCX, IMG)'}</span>
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
        <div className="p-4 rounded-2xl bg-emerald-950/80 border border-emerald-500/50 shadow-glow-emerald flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <CheckCircle2 className="w-5 h-5 text-emerald-400 shrink-0" />
            <div>
              <h4 className="text-xs font-bold text-white">
                Document Ingestion Complete: {uploadResult.filename}
              </h4>
              <p className="text-[11px] text-emerald-300 font-mono mt-0.5">
                Successfully parsed {uploadResult.page_count} pages • Extracted {uploadResult.concept_count} conceptual units into Knowledge Atlas.
              </p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            {onSelectSubject && uploadResult.document_id && (
              <button
                onClick={() => onSelectSubject(uploadResult.document_id)}
                className="py-1.5 px-3 rounded-xl bg-emerald-400 hover:bg-emerald-300 text-slate-950 text-xs font-black flex items-center gap-1.5 transition-all shadow-glow-emerald"
              >
                <BookOpen className="w-3.5 h-3.5" />
                <span>Open in Learning Atlas</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </button>
            )}
            <button
              onClick={() => setUploadResult(null)}
              className="text-xs text-emerald-400 hover:text-emerald-200 underline font-mono"
            >
              Dismiss
            </button>
          </div>
        </div>
      )}

      {/* Error Notification Banner */}
      {uploadError && (
        <div className="p-4 rounded-2xl bg-rose-950/80 border border-rose-500/50 flex items-center justify-between gap-4">
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

      <div className="space-y-4">
        {sources.map((src) => {
          let recoveryBadge = (
            <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded bg-emerald-950/80 border border-emerald-500/50 text-emerald-300 text-[10px] font-mono">
              <CheckCircle2 className="w-3 h-3 text-emerald-400" /> FULLY INTEGRATED
            </span>
          );

          if (src.recovery_state.includes('RECOVER') || src.status === 'PROCESSING') {
            recoveryBadge = (
              <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded bg-amber-950/80 border border-amber-500/50 text-amber-300 text-[10px] font-mono animate-pulse">
                <RefreshCw className="w-3 h-3 text-amber-400 animate-spin" /> PHASE 5 RECOVERY RETRY
              </span>
            );
          } else if (src.status === 'PARTIAL') {
            recoveryBadge = (
              <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded bg-rose-950/80 border border-rose-500/50 text-rose-300 text-[10px] font-mono">
                <AlertTriangle className="w-3 h-3 text-rose-400" /> PARTIAL EXTRACTION
              </span>
            );
          }

          return (
            <div
              key={src.document_id}
              className="p-5 rounded-2xl border border-slate-800 bg-slate-900/60 flex flex-wrap items-center justify-between gap-4 hover:border-slate-700 transition-colors"
            >
              <div className="flex items-center gap-4">
                <div className="p-3 rounded-xl bg-slate-950 border border-slate-800 text-cyan-400">
                  <FileText className="w-6 h-6" />
                </div>
                <div>
                  <h4 className="text-sm font-bold text-white">{src.title}</h4>
                  <div className="flex items-center gap-3 text-xs text-slate-400 font-mono mt-1">
                    <span>{src.page_count} Pages</span>
                    <span>•</span>
                    <span>{(src.file_size_bytes / (1024 * 1024)).toFixed(1)} MB</span>
                  </div>
                </div>
              </div>

              <div className="flex items-center gap-3">
                <div>{recoveryBadge}</div>

                {onSelectSubject && (
                  <button
                    onClick={() => onSelectSubject(src.document_id)}
                    className="py-1.5 px-3 rounded-xl bg-slate-800 hover:bg-cyan-500 hover:text-slate-950 text-slate-200 border border-slate-700 text-xs font-bold flex items-center gap-1.5 transition-all"
                  >
                    <BookOpen className="w-3.5 h-3.5" />
                    <span>Study In Atlas</span>
                    <ArrowRight className="w-3.5 h-3.5" />
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};

