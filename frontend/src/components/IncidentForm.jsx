/**
 * IncidentForm — submit a new incident with optional dashboard screenshot.
 * On successful submission, navigates to AgentTimeline for live progress.
 */
import { useCallback, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

function readFileAsBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result.split(",")[1] ?? "");
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

const PLACEHOLDER = `Paste raw logs or describe the incident here…

Example:
2024-01-15T14:23:01Z ERROR api-gateway Connection refused to payment-service:8080
2024-01-15T14:23:02Z ERROR api-gateway Retry 1/3 failed: dial tcp 10.0.1.45:8080
2024-01-15T14:23:03Z WARN  load-balancer 502 upstream error — payment-service`;

export default function IncidentForm() {
  const navigate = useNavigate();
  const [description, setDescription] = useState("");
  const [imageFile, setImageFile] = useState(null);
  const [imagePreview, setImagePreview] = useState(null);
  const [isDragging, setIsDragging] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const fileInputRef = useRef(null);

  const handleImageSelect = useCallback((file) => {
    if (!file || !file.type.startsWith("image/")) return;
    setImageFile(file);
    const reader = new FileReader();
    reader.onload = (e) => setImagePreview(e.target.result);
    reader.readAsDataURL(file);
  }, []);

  const handleDrop = useCallback(
    (e) => {
      e.preventDefault();
      setIsDragging(false);
      const file = e.dataTransfer.files[0];
      handleImageSelect(file);
    },
    [handleImageSelect]
  );

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!description.trim()) {
      setError("Please provide an incident description or raw logs.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const imageB64 = imageFile ? await readFileAsBase64(imageFile) : "";
      const incidentId = crypto.randomUUID();
      navigate(`/incidents/${incidentId}`, {
        state: { description, imageB64 },
      });
    } catch (err) {
      setError("Failed to prepare incident. Please try again.");
      setLoading(false);
    }
  };

  return (
    <div className="max-w-3xl mx-auto">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-white mb-2">New Incident</h1>
        <p className="text-gray-400">
          Paste logs or describe the issue. Attach a dashboard screenshot for richer context.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-6">
        {/* Log / description textarea */}
        <div>
          <label className="block text-sm font-medium text-gray-300 mb-2">
            Incident Description / Raw Logs <span className="text-red-400">*</span>
          </label>
          <textarea
            rows={10}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder={PLACEHOLDER}
            className="w-full bg-gray-800 border border-gray-700 rounded-lg p-4 text-gray-200
                       font-mono text-sm placeholder-gray-600 focus:outline-none
                       focus:ring-2 focus:ring-blue-500 focus:border-transparent resize-y"
          />
        </div>

        {/* Image drag-and-drop */}
        <div>
          <label className="block text-sm font-medium text-gray-300 mb-2">
            Dashboard Screenshot <span className="text-gray-500">(optional)</span>
          </label>
          <div
            onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
            onDragLeave={() => setIsDragging(false)}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
            className={`border-2 border-dashed rounded-lg p-6 text-center cursor-pointer transition-colors
                        ${isDragging
                          ? "border-blue-500 bg-blue-500/10"
                          : "border-gray-700 hover:border-gray-500 bg-gray-800/50"
                        }`}
          >
            {imagePreview ? (
              <div className="space-y-3">
                <img
                  src={imagePreview}
                  alt="Preview"
                  className="max-h-48 mx-auto rounded-lg object-contain"
                />
                <p className="text-sm text-gray-400">{imageFile?.name}</p>
                <button
                  type="button"
                  onClick={(e) => { e.stopPropagation(); setImageFile(null); setImagePreview(null); }}
                  className="text-xs text-red-400 hover:text-red-300"
                >
                  Remove
                </button>
              </div>
            ) : (
              <div className="text-gray-500">
                <svg className="mx-auto h-12 w-12 mb-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                    d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
                </svg>
                <p className="text-sm">Drop an image here or <span className="text-blue-400">browse</span></p>
                <p className="text-xs mt-1">PNG, JPG, GIF up to 10MB</p>
              </div>
            )}
          </div>
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*"
            className="hidden"
            onChange={(e) => handleImageSelect(e.target.files[0])}
          />
        </div>

        {/* Error */}
        {error && (
          <div className="bg-red-900/30 border border-red-700 rounded-lg p-4 text-red-300 text-sm">
            {error}
          </div>
        )}

        {/* Submit */}
        <button
          type="submit"
          disabled={loading}
          className="w-full py-3 px-6 bg-blue-600 hover:bg-blue-500 disabled:bg-blue-800
                     disabled:cursor-not-allowed text-white font-semibold rounded-lg
                     transition-colors flex items-center justify-center gap-3"
        >
          {loading ? (
            <>
              <svg className="animate-spin h-5 w-5" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor"
                  d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              Analyzing…
            </>
          ) : (
            "Analyze Incident"
          )}
        </button>
      </form>
    </div>
  );
}
