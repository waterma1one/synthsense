/**
 * EvalDashboard — displays RAGAS quality scores as gauges and trend lines.
 * Uses Recharts RadialBarChart for current scores and LineChart for trends.
 */
import { useEffect, useState } from "react";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  RadialBarChart, RadialBar, ResponsiveContainer,
} from "recharts";
import { getAllScores, getLatestScores } from "../api/client";

const METRIC_COLORS = {
  faithfulness:      "#60a5fa",  // blue-400
  answer_relevancy:  "#a78bfa",  // violet-400
  context_recall:    "#34d399",  // emerald-400
};

const METRIC_LABELS = {
  faithfulness:     "Faithfulness",
  answer_relevancy: "Answer Relevancy",
  context_recall:   "Context Recall",
};

function GaugeCard({ metric, value }) {
  const pct = value != null ? Math.round(value * 100) : null;
  const color = METRIC_COLORS[metric];
  const gaugeData = [{ name: metric, value: pct ?? 0, fill: color }];

  return (
    <div className="bg-gray-800 border border-gray-700 rounded-xl p-5 flex flex-col items-center">
      <h3 className="text-sm font-medium text-gray-400 mb-3">{METRIC_LABELS[metric]}</h3>

      {pct != null ? (
        <>
          <ResponsiveContainer width={140} height={140}>
            <RadialBarChart
              cx="50%" cy="50%" innerRadius="60%" outerRadius="90%"
              startAngle={180} endAngle={0}
              data={gaugeData}
            >
              <RadialBar dataKey="value" cornerRadius={6} />
            </RadialBarChart>
          </ResponsiveContainer>
          <p className="text-3xl font-bold mt-2" style={{ color }}>{pct}%</p>
        </>
      ) : (
        <div className="flex items-center justify-center h-36 text-gray-600 text-sm">
          No data yet
        </div>
      )}
    </div>
  );
}

function TrendChart({ records }) {
  if (!records.length) return null;

  const data = records.map((r, i) => ({
    run: `Run ${i + 1}`,
    faithfulness: r.scores?.faithfulness != null ? Math.round(r.scores.faithfulness * 100) : null,
    answer_relevancy: r.scores?.answer_relevancy != null ? Math.round(r.scores.answer_relevancy * 100) : null,
    context_recall: r.scores?.context_recall != null ? Math.round(r.scores.context_recall * 100) : null,
  }));

  return (
    <div className="bg-gray-800 border border-gray-700 rounded-xl p-6">
      <h3 className="text-sm font-medium text-gray-400 mb-6">Score Trends Over Time</h3>
      <ResponsiveContainer width="100%" height={220}>
        <LineChart data={data} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
          <XAxis dataKey="run" tick={{ fill: "#9ca3af", fontSize: 12 }} />
          <YAxis domain={[0, 100]} tick={{ fill: "#9ca3af", fontSize: 12 }} unit="%" />
          <Tooltip
            contentStyle={{ background: "#1f2937", border: "1px solid #374151", borderRadius: 8 }}
            labelStyle={{ color: "#d1d5db" }}
            itemStyle={{ color: "#d1d5db" }}
            formatter={(v) => `${v}%`}
          />
          <Legend wrapperStyle={{ color: "#9ca3af", fontSize: 12 }} />
          {Object.entries(METRIC_COLORS).map(([key, color]) => (
            <Line
              key={key}
              type="monotone"
              dataKey={key}
              stroke={color}
              strokeWidth={2}
              dot={{ r: 4, fill: color }}
              activeDot={{ r: 6 }}
              name={METRIC_LABELS[key]}
              connectNulls
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export default function EvalDashboard() {
  const [latest, setLatest] = useState(null);
  const [allRecords, setAllRecords] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    async function fetchData() {
      try {
        const [latestData, allData] = await Promise.all([getLatestScores(), getAllScores()]);
        setLatest(latestData);
        setAllRecords(allData || []);
      } catch (err) {
        setError("Could not load evaluation data. Run the eval harness first.");
      } finally {
        setLoading(false);
      }
    }
    fetchData();
  }, []);

  return (
    <div className="max-w-4xl mx-auto space-y-8">
      <div>
        <h1 className="text-3xl font-bold text-white mb-2">RAG Quality Dashboard</h1>
        <p className="text-gray-400">
          RAGAS scores assess the diagnosis agent's retrieval quality.
          Runs automatically every {10} incidents.
        </p>
        {latest?.timestamp && (
          <p className="text-xs text-gray-600 mt-1">
            Last assessment: {new Date(latest.timestamp).toLocaleString()} —{" "}
            {latest.sample_size} samples
          </p>
        )}
      </div>

      {loading && (
        <div className="text-center text-gray-500 py-16">
          <svg className="animate-spin h-8 w-8 mx-auto mb-3" viewBox="0 0 24 24" fill="none">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
          Loading scores…
        </div>
      )}

      {error && (
        <div className="bg-yellow-900/30 border border-yellow-700 rounded-lg p-4 text-yellow-300 text-sm">
          {error}
          <p className="mt-2 font-mono text-xs">
            python -m eval.ragas_eval run
          </p>
        </div>
      )}

      {!loading && !error && (
        <>
          {/* RAGAS gauge charts */}
          <div className="grid grid-cols-3 gap-4">
            {Object.keys(METRIC_LABELS).map((metric) => (
              <GaugeCard
                key={metric}
                metric={metric}
                value={latest?.scores?.[metric]}
              />
            ))}
          </div>

          {/* LLM Judge scores */}
          {latest?.scores?.judge && (
            <div className="bg-gray-800 border border-gray-700 rounded-xl p-6">
              <h3 className="text-sm font-medium text-gray-400 uppercase tracking-wider mb-4">
                LLM Judge Scores
              </h3>
              <div className="grid grid-cols-5 gap-3">
                {["accuracy", "completeness", "actionability", "specificity", "overall"].map((k) => {
                  const val = latest.scores.judge[k];
                  const pct = val != null ? Math.round(val * 100) : null;
                  const isOverall = k === "overall";
                  return (
                    <div
                      key={k}
                      className={`rounded-lg p-3 text-center ${isOverall ? "bg-blue-900/30 border border-blue-700" : "bg-gray-700/50"}`}
                    >
                      <p className="text-xs text-gray-400 capitalize mb-1">{k}</p>
                      <p className={`text-2xl font-bold ${isOverall ? "text-blue-400" : "text-white"}`}>
                        {pct != null ? `${pct}%` : "—"}
                      </p>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Trend line */}
          {allRecords.length > 1 && <TrendChart records={allRecords} />}

          {allRecords.length <= 1 && !loading && (
            <div className="bg-gray-800 border border-gray-700 rounded-xl p-6 text-center text-gray-500 text-sm">
              Run more assessments to see trends. At least 2 runs are needed.
            </div>
          )}
        </>
      )}
    </div>
  );
}
