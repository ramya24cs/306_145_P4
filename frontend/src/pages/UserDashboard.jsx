import { useEffect, useState } from "react";
import { api } from "../api.js";
import { Empty, ErrorBox, PageHeader, ReportDetail, ReportTable, Spinner, StatCard, useLoad, useToast } from "../ui.jsx";

export default function UserDashboard({ initialQuery = "" }) {
  const toast = useToast();
  const [q, setQ] = useState(initialQuery);
  const [filters, setFilters] = useState({ status: "", category: "", zone: "" });
  const [selected, setSelected] = useState(null);
  const stats = useLoad(() => api.analytics(), [], 8000);
  const list = useLoad(() => api.reports({ q, ...filters }), [q, filters.status, filters.category, filters.zone], 8000);

  useEffect(() => {
    if (/^RPT-\d+$/i.test(initialQuery.trim())) api.report(initialQuery.trim()).then(setSelected).catch((e) => toast("error", e.message));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function open(r) {
    try { setSelected(await api.report(r.report_id)); } catch (e) { toast("error", e.message); }
  }
  async function search(e) {
    e.preventDefault();
    if (!/^RPT-\d+$/i.test(q.trim())) return;       // exact report ID -> open its details
    try { setSelected(await api.report(q.trim())); } catch (err) { toast("error", err.message); }
  }
  const s = stats.data?.status_counts;
  const setF = (k) => (e) => setFilters({ ...filters, [k]: e.target.value });

  return (
    <>
      <PageHeader title="Reports" sub="Every submitted report, updated live as doctors work on them. Select a row for the full timeline." />
      <div className="stats">
        <StatCard label="Total reports" value={stats.data?.summary.total} />
        <StatCard label="Pending" value={s?.Pending} tone="warn" />
        <StatCard label="Assigned" value={s?.Assigned} />
        <StatCard label="In progress" value={s?.["In Progress"]} />
        <StatCard label="Resolved" value={s?.Resolved} tone="ok" />
      </div>
      {stats.error && <ErrorBox message={stats.error} onRetry={stats.reload} />}
      <section className="card">
        <form className="row" onSubmit={search}>
          <input style={{ flex: "2 1 220px" }} placeholder="Search by report ID (RPT-000001) or patient ID, then press Enter" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search reports" />
          <select style={{ flex: "1 1 130px" }} value={filters.status} onChange={setF("status")} aria-label="Filter by status">
            <option value="">All statuses</option><option>Pending</option><option>Assigned</option><option>In Progress</option><option>Resolved</option>
          </select>
          <select style={{ flex: "1 1 130px" }} value={filters.category} onChange={setF("category")} aria-label="Filter by category">
            <option value="">All categories</option><option>Critical</option><option>Stat</option><option>Routine</option><option>Pending</option><option>Error</option>
          </select>
          <select style={{ flex: "1 1 120px" }} value={filters.zone} onChange={setF("zone")} aria-label="Filter by zone">
            <option value="">All zones</option><option value="A">Zone A</option><option value="B">Zone B</option><option value="C">Zone C</option><option value="D">Zone D</option>
          </select>
          <button type="button" className="btn" onClick={() => { setQ(""); setFilters({ status: "", category: "", zone: "" }); }}>Clear</button>
        </form>
      </section>
      {selected && <ReportDetail report={selected} onClose={() => setSelected(null)} />}
      <section className="card">
        <h3>Reports {list.data && <span className="muted">({list.data.count})</span>}</h3>
        {list.loading && !list.data ? <Spinner label="Loading reports" /> : list.error ? <ErrorBox message={list.error} onRetry={list.reload} /> :
          list.data.reports.length === 0 ? <Empty>No reports match. Submit one from the Submit report page.</Empty> :
          <ReportTable reports={list.data.reports} onRowClick={open} columns={["id", "patient", "category", "zone", "priority", "status", "queue", "doctor", "submitted"]} />}
      </section>
    </>
  );
}
