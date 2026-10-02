import { Link, Route, Routes } from "react-router-dom";
import { HashRouter } from "react-router-dom";
import CorrespondenceDetail from "./pages/CorrespondenceDetail";
import CorrespondenceList from "./pages/CorrespondenceList";
import UploadPage from "./pages/UploadPage";

export default function App() {
  return (
    <HashRouter>
      <header className="app-header">
        <Link to="/" className="app-title">
          HA Request &amp; Response Agent
        </Link>
        <Link to="/upload" className="nav-link">
          Upload correspondence
        </Link>
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
