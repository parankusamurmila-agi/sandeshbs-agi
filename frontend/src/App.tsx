import { Link, Route, Routes } from "react-router-dom";
import { HashRouter } from "react-router-dom";
import CorrespondenceDetail from "./pages/CorrespondenceDetail";
import CorrespondenceList from "./pages/CorrespondenceList";
import UploadPage from "./pages/UploadPage";
import arisGlobalLogo from "./assets/arisglobal-logo.png";

/** Document-with-approved-reply mark for the HA Request & Response Agent. */
function BrandIcon() {
  return (
    <span className="brand-icon">
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <rect x="3" y="2.5" width="13" height="17" rx="2.4" fill="#fff" />
        <line x1="6" y1="7" x2="13" y2="7" stroke="#2d5fda" strokeWidth="1.5" strokeLinecap="round" />
        <line x1="6" y1="10" x2="13" y2="10" stroke="#8fa6e0" strokeWidth="1.5" strokeLinecap="round" />
        <line x1="6" y1="13" x2="10.5" y2="13" stroke="#8fa6e0" strokeWidth="1.5" strokeLinecap="round" />
        <circle cx="16.5" cy="16.5" r="5.3" fill="#2d5fda" stroke="#fff" strokeWidth="1.4" />
        <path
          d="M14.3 16.7l1.5 1.5 3-3.1"
          stroke="#fff"
          strokeWidth="1.7"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </span>
  );
}

export default function App() {
  return (
    <HashRouter>
      <header className="app-header">
        <Link to="/" className="brand">
          <BrandIcon />
          <span className="app-title">
            HA Request &amp; Response Agent
            <span className="app-subtitle">Regulatory response drafting</span>
          </span>
        </Link>
        <Link to="/upload" className="nav-link">
          Upload correspondence
        </Link>
        <span className="brand-logo-wrap">
          <img src={arisGlobalLogo} alt="ArisGlobal" className="brand-logo" />
        </span>
      </header>
      <main className="app-main">
        <Routes>
          <Route path="/" element={<CorrespondenceList />} />
          <Route path="/upload" element={<UploadPage />} />
          <Route path="/correspondence/:id" element={<CorrespondenceDetail />} />
        </Routes>
      </main>
    </HashRouter>
  );
}
