/**
 * RemediationCard — displays the structured remediation plan with interactive checkboxes.
 * Severity badge uses color-coded styling. Copy-to-clipboard available for the full plan.
 */
import { useState } from "react";

const SEVERITY_BADGE = {
  critical: "bg-red-900 text-red-300 border border-red-700",
  high:     "bg-orange-900 text-orange-300 border border-orange-700",
  medium:   "bg-yellow-900 text-yellow-300 border border-yellow-700",
  low:      "bg-green-900 text-green-300 border border-green-700",
};

function CopyButton({ text }) {
  const [copied, setCopied] = useState(false);
  const handleCopy = async () => {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };
  return (
    <button
      onClick={handleCopy}
      className="flex items-center gap-1.5 text-xs text-gray-400 hover:text-white
                 bg-gray-700 hover:bg-gray-600 px-3 py-1.5 rounded-md transition-colors"
    >
      {copied ? (
        <>
          <svg className="h-3.5 w-3.5 text-green-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
          </svg>
          Copied!
        </>
      ) : (
        <>
          <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
              d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
          </svg>
          Copy Plan
        </>
      )}
    </button>
  );
}

function ChecklistItem({ text, index }) {
  const [checked, setChecked] = useState(false);
  return (
    <li
      className={`flex gap-3 items-start p-3 rounded-lg transition-colors cursor-pointer
                  ${checked ? "bg-green-900/20 opacity-60" : "hover:bg-gray-700/30"}`}
      onClick={() => setChecked(!checked)}
    >
      <div className={`mt-0.5 flex-shrink-0 w-5 h-5 rounded border-2 flex items-center justify-center
                       transition-colors ${checked ? "bg-green-500 border-green-500" : "border-gray-500"}`}>
        {checked && (
          <svg className="h-3 w-3 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
          </svg>
        )}
      </div>
      <div>
        <span className="text-xs font-mono text-gray-500 mr-2">{index + 1}.</span>
        <span className={`text-sm text-gray-200 ${checked ? "line-through text-gray-500" : ""}`}>{text}</span>
      </div>
    </li>
  );
}

export default function RemediationCard({ severity, remediation, remediationText }) {
  const sevKey = severity?.toLowerCase() || "medium";
  const badgeClass = SEVERITY_BADGE[sevKey] || SEVERITY_BADGE.medium;

  const immediateSteps = remediation?.immediate_steps || [];
  const investigationSteps = remediation?.investigation_steps || [];
  const escalation = remediation?.escalation_threshold || "";
  const eta = remediation?.estimated_resolution_time || "";
  const runbookRefs = remediation?.runbook_references || [];

  const copyText = remediationText || JSON.stringify(remediation, null, 2);

  return (
    <div className="border border-gray-700 rounded-xl overflow-hidden">
      {/* Header */}
      <div className="bg-gray-800 px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h2 className="text-lg font-semibold text-white">Remediation Plan</h2>
          <span className={`text-xs font-bold px-2.5 py-1 rounded-full uppercase tracking-wider ${badgeClass}`}>
            {sevKey}
          </span>
        </div>
        <CopyButton text={copyText} />
      </div>

      <div className="p-6 space-y-6">
        {/* Immediate steps */}
        {immediateSteps.length > 0 && (
          <div>
            <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wider mb-3 flex items-center gap-2">
              <span className="text-red-400">⚡</span> Immediate Steps
            </h3>
            <ul className="space-y-1">
              {immediateSteps.map((step, i) => (
                <ChecklistItem key={i} text={step} index={i} />
              ))}
            </ul>
          </div>
        )}

        {/* Investigation steps */}
        {investigationSteps.length > 0 && (
          <div>
            <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wider mb-3 flex items-center gap-2">
              <span className="text-blue-400">🔍</span> Investigation Steps
            </h3>
            <ul className="space-y-1 text-sm text-gray-400">
              {investigationSteps.map((step, i) => (
                <li key={i} className="flex gap-2 p-2">
                  <span className="text-gray-600">—</span> {step}
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Meta info */}
        {(escalation || eta) && (
          <div className="grid grid-cols-2 gap-4 pt-4 border-t border-gray-700">
            {escalation && (
              <div>
                <p className="text-xs text-gray-500 uppercase tracking-wider mb-1">Escalate if</p>
                <p className="text-sm text-gray-300">{escalation}</p>
              </div>
            )}
            {eta && (
              <div>
                <p className="text-xs text-gray-500 uppercase tracking-wider mb-1">ETA</p>
                <p className="text-sm text-gray-300">{eta}</p>
              </div>
            )}
          </div>
        )}

        {/* Runbook references */}
        {runbookRefs.length > 0 && (
          <div className="pt-4 border-t border-gray-700">
            <p className="text-xs text-gray-500 uppercase tracking-wider mb-2">Runbook References</p>
            <div className="flex flex-wrap gap-2">
              {runbookRefs.map((ref, i) => (
                <span key={i} className="text-xs bg-gray-700 text-gray-300 px-2 py-1 rounded font-mono">
                  {ref}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Fallback: raw remediation text */}
        {immediateSteps.length === 0 && remediationText && (
          <pre className="text-sm text-gray-300 whitespace-pre-wrap font-mono bg-gray-800/50 p-4 rounded-lg">
            {remediationText}
          </pre>
        )}
      </div>
    </div>
  );
}
