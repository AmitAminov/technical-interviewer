/** Application shell + routing. The interview room hides the global header. */
import { Link, Navigate, NavLink, Route, Routes, useLocation } from 'react-router-dom';

import InterviewPage from './pages/InterviewPage';
import ProgressPage from './pages/ProgressPage';
import ReportPage from './pages/ReportPage';
import SessionsPage from './pages/SessionsPage';
import SetupPage from './pages/SetupPage';

/** NavLink styling: active route gets white text + an indigo underline
 * (NavLink also sets aria-current="page" on the active link). */
function navLinkClass({ isActive }: { isActive: boolean }) {
  return isActive
    ? 'text-white underline decoration-indigo-400 underline-offset-8 transition-colors'
    : 'text-slate-300 transition-colors hover:text-white';
}

function Header() {
  return (
    <header className="border-b border-slate-800 bg-slate-950/95">
      <div className="mx-auto flex max-w-5xl items-center gap-6 px-6 py-3">
        <Link to="/" className="flex items-center gap-2">
          <img src="/ti-emblem.svg" alt="" className="h-7 w-7 rounded-md" />
          <span className="text-sm font-semibold tracking-tight text-slate-100">
            Technical Interviewer
          </span>
        </Link>
        <nav className="ml-auto flex items-center gap-4 text-sm">
          <NavLink to="/" end className={navLinkClass}>
            New interview
          </NavLink>
          <NavLink to="/sessions" className={navLinkClass}>
            Sessions
          </NavLink>
          <NavLink to="/progress" className={navLinkClass}>
            Progress
          </NavLink>
        </nav>
      </div>
    </header>
  );
}

export default function App() {
  const location = useLocation();
  const inInterviewRoom = location.pathname.startsWith('/interview/');
  return (
    <div className="min-h-full bg-slate-950 text-slate-100">
      {!inInterviewRoom && <Header />}
      <Routes>
        <Route path="/" element={<SetupPage />} />
        <Route path="/interview/:id" element={<InterviewPage />} />
        <Route path="/report/:id" element={<ReportPage />} />
        <Route path="/sessions" element={<SessionsPage />} />
        <Route path="/progress" element={<ProgressPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </div>
  );
}
