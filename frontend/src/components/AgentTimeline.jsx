/**
 * AgentTimeline — live SSE feed showing each agent card as it completes.
 * Cards fade and slide in progressively. On completion, renders RemediationCard.
 */
import { useEffect, useState } from "react";
import { useLocation, useParams } from "react-router-dom";
import { getIncident, streamIncidentPost } from "../api/client";
import RemediationCard from "./RemediationCard";

const AGENT_META = {
  preprocess: { label: "Preprocessing", icon: "⚙️", color: "blue" },
  triage:     { label: "Triage",         icon: "🚨", color: "yellow" },
  diagnose:   { label: "Diagnosis",      icon: "🔬", color: "purple" },
  remediate:  { label: "Remediation",    icon: "🛠️", color: "green" },
  postmortem: { label: "Postmortem",     icon: "📋", color: "gray" },
  store:      { label: "Stored",         icon: "💾", color: "gray" },
};

const COLOR_CLASSES = {
  blue:   "border-blue-500 bg-blue-500/10",
  yellow: "border-yellow-500 bg-yellow-500/10",
  purple: "border-purple-500 bg-purple-500/10",
  green:  "border-green-500 bg-green-500/10",
  gray:   "border-gray-500 bg-gray-500/10",
};

function AgentCard({ name, output, isNew }) {
  const meta = AGENT_META[name] || { label: name, icon: "🤖", color: "blue" };
  const colorClass = COLOR_CLASSES[meta.color] || COLOR_CLASSES.blue;

  return (
    <div
      className={`border rounded-lg p-5 transition-all duration-500 ${colorClass}
                  ${isNew ? "opacity-0 translate-y-4 animate-fade-in" : "opacity-100"}`}
      style={{ animation: isNew ? "fadeSlideIn 0.5s ease forwards" : "none" }}
    >
      <div className="flex items-center gap-3 mb-3">
        <span className="text-2xl">{meta.icon}</span>
        <div>
          <h3 className="font-semibold text-white">{meta.label}</h3>
          <span className="text-xs text-green-400 flex items-center gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-green-400 inline-block" />
            Completed
          </span>
        </div>
      </div>

      <div className="space-y-2 text-sm text-gray-300">
        {name === "triage" && output.triage_result && (
          <>
            <p><span className="text-gray-500">Severity:</span> {output.triage_result.severity}</p>
            <p><span className="text-gray-500">Confidence:</span> {(output.triage_result.confidence * 100).toFixed(0)}%</p>
            <p><span className="text-gray-500">Reasoning:</span> {output.triage_result.reasoning}</p>
          </>
        )}
        {name === "preprocess" && (
          <p><span className="text-gray-500">Image:</span> {output.image_description?.slice(0, 120) || "No image"}{output.image_description?.length > 120 ? "…" : ""}</p>
        )}
        {name === "diagnose" && output.diagnosis && (
          <p><span className="text-gray-500">Root cause:</span> {output.diagnosis?.slice(0, 200)}{output.diagnosis?.length > 200 ? "…" : ""}</p>
        )}
        {name === "postmortem" && output.postmortem && (
          <p className="text-gray-400 italic">{output.postmortem?.slice(0, 200)}{output.postmortem?.length > 200 ? "…" : ""}</p>
        )}
      </div>
    </div>
  );
}

function RunningCard({ name }) {
  const meta = AGENT_META[name] || { label: name, icon: "🤖", color: "blue" };
  return (
    <div className="border border-gray-600 rounded-lg p-5 bg-gray-800/50 animate-pulse">
      <div className="flex items-center gap-3">
        <span className="text-2xl">{meta.icon}</span>
        <div>
          <h3 className="font-semibold text-white">{meta.label}</h3>
          <span className="text-xs text-blue-400 flex items-center gap-1">
            <svg className="animate-spin h-3 w-3" viewBox="0 0 24 24" fill="none">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            Running…
          </span>
        </div>
      </div>
    </div>
  );
}

export default function AgentTimeline() {
  const { id: incidentId } = useParams();
  const location = useLocation();
  const description = location.state?.description;
  const imageB64 = location.state?.imageB64 || "";

  const [completedNodes, setCompletedNodes] = useState([]);
  const [currentNode, setCurrentNode] = useState(null);
  const [done, setDone] = useState(false);
  const [finalState, setFinalState] = useState(null);
  const [error, setError] = useState(null);
  const latestNodeRef = useState(null);

  useEffect(() => {
    let cancelled = false;

    if (description !== undefined) {
      // New incident — stream via POST fetch
      async function runStream() {
        try {
          for await (const data of streamIncidentPost(incidentId, description, imageB64)) {
            if (cancelled) break;
            if (data.agent === "done") {
              setCurrentNode(null);
              setDone(true);
              break;
            }
            if (data.agent === "error") {
              setError(data.error || "Pipeline error");
              break;
            }
            latestNodeRef[0] = data.agent;
            setCurrentNode(data.agent);
            setCompletedNodes((prev) => [
              ...prev,
              { name: data.agent, output: data.output, isNew: true },
            ]);
            if (data.output?.remediation_result || data.output?.remediation) {
              setFinalState((prev) => ({ ...prev, ...data.output }));
            }
          }
        } catch (err) {
          if (!cancelled) setError(`Stream failed: ${err.message}`);
        }
      }
      runStream();
    } else {
      // Existing incident from history — fetch stored result
      getIncident(incidentId)
        .then((incident) => {
          if (cancelled) return;
          const nodes = ["preprocess", "triage"];
          if (incident.diagnosis) nodes.push("diagnose");
          nodes.push("remediate");
          if (incident.postmortem && !incident.postmortem.startsWith("Postmortem deferred"))
            nodes.push("postmortem");
          setCompletedNodes(nodes.map((name) => ({ name, output: incident, isNew: false })));
          setFinalState(incident);
          setDone(true);
        })
        .catch(() => setError("Could not load incident. It may not exist yet."));
    }

    return () => { cancelled = true; };
  }, [incidentId]);

  return (
    <div className="max-w-3xl mx-auto space-y-8">
      <style>{`
        @keyframes fadeSlideIn {
          from { opacity: 0; transform: translateY(16px); }
          to   { opacity: 1; transform: translateY(0); }
        }
      `}</style>

      <div>
        <h1 className="text-2xl font-bold text-white mb-1">Agent Timeline</h1>
        <p className="text-gray-500 font-mono text-sm">{incidentId}</p>
      </div>

      {error && (
        <div className="bg-red-900/30 border border-red-700 rounded-lg p-4 text-red-300 text-sm">
          {error}
        </div>
      )}

      <div className="space-y-4">
        {completedNodes.map((node, i) => (
          <AgentCard
            key={`${node.name}-${i}`}
            name={node.name}
            output={node.output}
            isNew={node.isNew && node.name === latestNodeRef[0]}
          />
        ))}
        {currentNode && !done && <RunningCard name={currentNode} />}
        {!done && completedNodes.length === 0 && !currentNode && !error && (
          <div className="text-center text-gray-500 py-12">
            <svg className="animate-spin h-8 w-8 mx-auto mb-4" viewBox="0 0 24 24" fill="none">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            Connecting to agent pipeline…
          </div>
        )}
      </div>

      {done && finalState && (
        <RemediationCard
          severity={finalState.severity || finalState.triage_result?.severity}
          remediation={finalState.remediation_result || {}}
          remediationText={finalState.remediation || ""}
        />
      )}
    </div>
  );
}
