import React, { useState } from 'react';
import type { SourceDocument } from '../../api/client';
import { FileText, Upload, CheckCircle2, AlertTriangle, RefreshCw } from 'lucide-react';

export interface SourceLibraryProps {
  sources: SourceDocument[];
  onReloadSources: () => void;
}

export const SourceLibrary: React.FC<SourceLibraryProps> = ({
  sources,
  onReloadSources,
}) => {
  const [uploading, setUploading] = useState<boolean>(false);

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);

    try {
      const formData = new FormData();
      formData.append('file', file);
      const res = await fetch('http://localhost:8000/api/sources/upload', {
        method: 'POST',
        body: formData,
      });
      if (res.ok) {
        onReloadSources();
      }
    } catch (err) {
      console.error('File upload failed', err);
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="p-6 rounded-3xl border border-slate-800 bg-slate-950 text-slate-100">
      <div className="flex items-center justify-between pb-4 border-b border-slate-800">
        <div>
          <h3 className="text-lg font-bold text-white flex items-center gap-2">
            <FileText className="w-5 h-5 text-cyan-400" />
            Source Document Library
          </h3>
          <p className="text-xs text-slate-400 mt-1">
            Uploaded textbook materials, EKR processing states, and Phase 5 self-healing recovery boundaries.
          </p>
        </div>

        {/* Upload Button */}
        <label className="py-2.5 px-4 rounded-xl bg-cyan-500 hover:bg-cyan-400 text-slate-950 font-bold text-xs flex items-center gap-2 cursor-pointer shadow-glow-cyan transition-all">
          <Upload className="w-4 h-4" />
          <span>{uploading ? 'Processing...' : 'Upload PDF Source'}</span>
          <input type="file" accept=".pdf" onChange={handleFileUpload} className="hidden" />
        </label>
      </div>

      <div className="mt-6 space-y-4">
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
              className="p-5 rounded-2xl border border-slate-800 bg-slate-900/60 flex items-center justify-between gap-4"
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

              <div>{recoveryBadge}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
