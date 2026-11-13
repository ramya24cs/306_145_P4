
import { useEffect, useState } from "react";
import { api } from "./api.js";
import { Icon, useLiveCtx } from "./ui.jsx";
import Overview from "./pages/Overview.jsx";
import SubmitReport from "./pages/SubmitReport.jsx";
import UserDashboard from "./pages/UserDashboard.jsx";
import HandlerDashboard from "./pages/HandlerDashboard.jsx";
import RoutingDashboard from "./pages/RoutingDashboard.jsx";
import Analytics from "./pages/Analytics.jsx";

const PAGES = [
  { id: "overview", label: "Command center", icon: "home", view: Overview },
  { id: "submit", label: "Submit report", icon: "plus", view: SubmitReport },
  { id: "reports", label: "Reports", icon: "list", view: UserDashboard },
  { id: "handler", label: "Handler desk", icon: "pulse", view: HandlerDashboard },
  { id: "routing", label: "Routing", icon: "route", view: RoutingDashboard },
  { id: "analytics", label: "Analytics", icon: "chart", view: Analytics },
];

export default function App() {
  const initial = window.location.hash.replace("#", "");

  const [page, setPage] = useState(
    PAGES.some((p) => p.id === initial) ? initial : "overview"
  );

  const [menu, setMenu] = useState(false);
  const [quick, setQuick] = useState("");
  const [quickKey, setQuickKey] = useState(0);
  const [atRisk, setAtRisk] = useState(0);

  const { version } = useLiveCtx();

  useEffect(() => {
    window.location.hash = page;
    window.scrollTo(0, 0);
  }, [page]);

  useEffect(() => {
    api
      .routingTable()
      .then((d) =>
        setAtRisk(
          d.escalated.length +
          d.waiting.filter((r) => r.priority <= 2).length
        )
      )
      .catch(() => {});
  }, [version]);

  const go = (id) => {
    setPage(id);
    setMenu(false);
  };

  const Current = PAGES.find((p) => p.id === page).view;

  const search = (e) => {
    e.preventDefault();

    if (!quick.trim()) return;

    setQuickKey((k) => k + 1);
    go("reports");
  };

  return (
    <div className="shell">
      <aside className={`sidebar ${menu ? "open" : ""}`}>
        <div className="brand">
          <span className="brand-mark">
            <svg viewBox="0 0 24 24">
              <path d="M12 2.5c3.6 4.3 6.2 7.4 6.2 10.6a6.2 6.2 0 0 1-12.4 0C5.8 9.9 8.4 6.8 12 2.5z" />
            </svg>
          </span>

          <div>
            <strong>LabNotify</strong>
            <small>Pathology result dispatch</small>
          </div>
        </div>

        <nav>
          {PAGES.map((p) => (
            <button
              key={p.id}
              className={`nav-item ${page === p.id ? "active" : ""}`}
              onClick={() => go(p.id)}
            >
              <Icon name={p.icon} />
              {p.label}

              {p.id === "routing" && atRisk > 0 && (
                <span className="nav-badge">{atRisk}</span>
              )}
            </button>
          ))}
        </nav>

        <div className="side-foot">
          <b>Always on</b>
          Reports reach doctors the moment they are routed. No refresh needed.
        </div>
      </aside>

      <div>
        <div className="topbar">
          <button
            className="menu-btn"
            onClick={() => setMenu(!menu)}
            aria-label="Open navigation"
          >
            <Icon name="menu" />
          </button>

          <form className="quick" onSubmit={search}>
            <Icon name="search" />

            <input
              value={quick}
              onChange={(e) => setQuick(e.target.value)}
              placeholder="Jump to a report or patient ID"
              aria-label="Quick search"
            />
          </form>
        </div>

        <main
          className="content"
          key={page + quickKey}
          onClick={() => menu && setMenu(false)}
        >
          <Current
            go={go}
            initialQuery={page === "reports" ? quick : ""}
          />
        </main>
      </div>
    </div>
  );
}
