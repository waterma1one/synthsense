/**
 * IncidentList — browse past incidents from Supabase.
 * Clicking a row opens AgentTimeline in read-only mode (no streaming).
 */
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { listIncidents } from "../api/client";

const SEVERITY_STYLES = {
  critical: "text-red-400 bg-red-900/20 border border-red-800",
  high:     "text-orange-400 bg-orange-900/20 border border-orange-800",
  medium:   "text-yellow-400 bg-yellow-900/20 border border-yellow-800",
  low:      "text-green-400 bg-green-900/20 border border-green-800",
};

function SeverityBadge({ severity }) {
  const cls = SEVERITY_STYLES[severity?.toLowerCase()] || SEVERITY_STYLES.medium;
  return (
    <span className={`text-xs font-bold px-2 py-0.5 rounded-full uppercase tracking-wider ${cls}`}>
      {severity || "—"}
    </span>
  );
}

export default function IncidentList() {
  const [incidents, setIncidents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    listIncidents(50)
      .then(setIncidents)
      .catch(() => setError("Could not load incidents. Is the backend running?"))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-white mb-1">Incident History</h1>
          <p className="text-gray-400">Past incidents stored in Supabase.</p>
        </div>
        <Link
          to="/"
          className="flex items-center gap-2 text-sm bg-blue-600 hover:bg-blue-500 text-white
                     px-4 py-2 rounded-lg transition-colors font-medium"
        >
          + New Incident
        </Link>
      </div>

      {loading && (
        <div className="text-center text-gray-500 py-16">
          <svg className="animate-spin h-8 w-8 mx-auto mb-3" viewBox="0 0 24 24" fill="none">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
          Loading incidents…
        </div>
      )}

      {error && (
        <div className="bg-red-900/30 border border-red-700 rounded-lg p-4 text-red-300 text-sm">
          {error}
        </div>
      )}

      {!loading && !error && incidents.length === 0 && (
        <div className="text-center py-16 text-gray-500">
          <p className="text-lg mb-2">No incidents yet.</p>
          <p className="text-sm">Submit your first incident to get started.</p>
        </div>
      )}

      {!loading && incidents.length > 0 && (
        <div className="rounded-xl border border-gray-700 overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-800 border-b border-gray-700">
              <tr>
                <th className="text-left px-5 py-3 text-gray-400 font-medium">Incident</th>
                <th className="text-left px-5 py-3 text-gray-400 font-medium w-28">Severity</th>
                <th className="text-left px-5 py-3 text-gray-400 font-medium w-44">Time</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800">
              {incidents.map((inc) => (
                <tr
                  key={inc.id}
                  className="hover:bg-gray-800/60 transition-colors"
                >
                  <td className="px-5 py-3">
                    <Link
                      to={`/incidents/${inc.id}`}
                      className="text-blue-400 hover:text-blue-300 font-medium"
                    >
                      {inc.title || "Untitled incident"}
                    </Link>
                    <p className="text-gray-600 font-mono text-xs mt-0.5">{inc.id}</p>
                  </td>
                  <td className="px-5 py-3">
                    <SeverityBadge severity={inc.severity} />
                  </td>
                  <td className="px-5 py-3 text-gray-500 text-xs">
                    {inc.created_at
                      ? new Date(inc.created_at).toLocaleString()
                      : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
