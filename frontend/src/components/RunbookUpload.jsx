/**
 * RunbookUpload — drag-and-drop PDF ingestion into the vector store.
 * Deduplicates by filename (backend returns skipped=true for re-uploads).
 */
import { useCallback, useRef, useState } from "react";
import { uploadRunbook } from "../api/client";

function UploadResult({ result }) {
  return (
    <div
      className={`border rounded-lg p-4 flex items-start gap-3 ${
        result.skipped
          ? "border-yellow-700 bg-yellow-900/20"
          : "border-green-700 bg-green-900/20"
      }`}
    >
      <span className="text-xl mt-0.5">{result.skipped ? "⚠️" : "✅"}</span>
      <div>
        <p className={`font-medium text-sm ${result.skipped ? "text-yellow-300" : "text-green-300"}`}>
          {result.skipped ? "Already indexed" : `Indexed ${result.chunk_count} chunks`}
        </p>
        <p className="text-gray-400 text-xs mt-0.5">{result.message}</p>
      </div>
    </div>
  );
}

export default function RunbookUpload() {
  const [isDragging, setIsDragging] = useState(false);
  const [uploads, setUploads] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const fileInputRef = useRef(null);

  const handleFiles = useCallback(async (files) => {
    const pdfs = Array.from(files).filter((f) => f.name.toLowerCase().endsWith(".pdf"));
    if (pdfs.length === 0) {
      setError("Only PDF files are accepted.");
      return;
    }
    setError(null);
    setLoading(true);

    const results = [];
    for (const pdf of pdfs) {
      try {
        const result = await uploadRunbook(pdf);
        results.push({ ...result, ok: true });
      } catch (err) {
        results.push({
          filename: pdf.name,
          chunk_count: 0,
          skipped: false,
          message: err.response?.data?.detail || `Upload failed: ${err.message}`,
          ok: false,
        });
      }
    }

    setUploads((prev) => [...results, ...prev]);
    setLoading(false);
  }, []);

  const handleDrop = useCallback(
    (e) => {
      e.preventDefault();
      setIsDragging(false);
      handleFiles(e.dataTransfer.files);
    },
    [handleFiles]
  );

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-white mb-1">Upload Runbooks</h1>
        <p className="text-gray-400">
          PDF runbooks are chunked and indexed into the vector store for RAG retrieval.
          Re-uploading the same file is a no-op.
        </p>
      </div>

      {/* Drop zone */}
      <div
        onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={handleDrop}
        onClick={() => fileInputRef.current?.click()}
        className={`border-2 border-dashed rounded-xl p-12 text-center cursor-pointer transition-colors
                    ${isDragging
                      ? "border-blue-500 bg-blue-500/10"
                      : "border-gray-700 hover:border-gray-500 bg-gray-800/50"
                    } ${loading ? "pointer-events-none opacity-60" : ""}`}
      >
        {loading ? (
          <div className="flex flex-col items-center gap-3 text-gray-400">
            <svg className="animate-spin h-10 w-10" viewBox="0 0 24 24" fill="none">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            <p className="text-sm">Indexing…</p>
          </div>
        ) : (
          <div className="text-gray-500">
            <svg className="mx-auto h-14 w-14 mb-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
            <p className="text-sm mb-1">Drop PDF runbooks here or <span className="text-blue-400">browse</span></p>
            <p className="text-xs">Accepts PDF files up to 20 MB</p>
          </div>
        )}
      </div>

      <input
        ref={fileInputRef}
        type="file"
        accept=".pdf"
        multiple
        className="hidden"
        onChange={(e) => handleFiles(e.target.files)}
      />

      {error && (
        <div className="bg-red-900/30 border border-red-700 rounded-lg p-4 text-red-300 text-sm">
          {error}
        </div>
      )}

      {uploads.length > 0 && (
        <div className="space-y-3">
          <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wider">Upload Results</h2>
          {uploads.map((r, i) => (
            <UploadResult key={i} result={r} />
          ))}
        </div>
      )}
    </div>
  );
}
