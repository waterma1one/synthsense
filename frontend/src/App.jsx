/**
 * Root application component for SynthSense.
 * Sets up routing, navigation sidebar, and dark-theme layout.
 */
import { Link, Route, Routes, useLocation } from "react-router-dom";
import AgentTimeline from "./components/AgentTimeline";
import EvalDashboard from "./components/EvalDashboard";
import IncidentForm from "./components/IncidentForm";
import IncidentList from "./components/IncidentList";
import RunbookUpload from "./components/RunbookUpload";

const NAV_LINKS = [
  { to: "/",         label: "New Incident", icon: "+" },
  { to: "/history",  label: "History",      icon: "🕒" },
  { to: "/runbooks", label: "Runbooks",     icon: "📄" },
  { to: "/evals",    label: "RAG Quality",  icon: "📊" },
];

function NavLink({ to, label, icon }) {
  const { pathname } = useLocation();
  const active = pathname === to;
  return (
    <Link
      to={to}
      className={`flex items-center gap-3 px-4 py-2.5 rounded-lg text-sm font-medium transition-colors
                  ${active
                    ? "bg-blue-600 text-white"
                    : "text-gray-400 hover:text-white hover:bg-gray-700"}`}
    >
      <span className="text-base">{icon}</span>
      {label}
    </Link>
  );
}

export default function App() {
  return (
    <div className="min-h-screen bg-gray-900 flex">
      {/* Sidebar */}
      <aside className="w-56 flex-shrink-0 bg-gray-800 border-r border-gray-700 flex flex-col p-4">
        <div className="mb-8 px-2">
          <h1 className="text-xl font-bold text-white">SynthSense</h1>
          <p className="text-xs text-gray-500 mt-0.5">Incident Intelligence</p>
        </div>
        <nav className="space-y-1 flex-1">
          {NAV_LINKS.map((link) => (
            <NavLink key={link.to} {...link} />
          ))}
        </nav>
        <div className="mt-auto px-2 pb-2">
          <p className="text-xs text-gray-600">Powered by Groq + LangGraph</p>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-auto">
        <div className="max-w-5xl mx-auto px-8 py-10">
          <Routes>
            <Route path="/" element={<IncidentForm />} />
            <Route path="/incidents/:id" element={<AgentTimeline />} />
            <Route path="/history" element={<IncidentList />} />
            <Route path="/runbooks" element={<RunbookUpload />} />
            <Route path="/evals" element={<EvalDashboard />} />
          </Routes>
        </div>
      </main>
    </div>
  );
}
